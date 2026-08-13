import time

from src.stream.batching import BatchAccumulator, BatchedMessage


def _msg(offset, partition=0, topic="t"):
    return BatchedMessage(
        key=str(offset), value={"i": offset}, topic=topic, partition=partition, offset=offset
    )


def test_flushes_on_record_count():
    batch = BatchAccumulator(max_records=3, max_seconds=999)
    assert batch.add(_msg(0)) is False
    assert batch.add(_msg(1)) is False
    assert batch.add(_msg(2)) is True


def test_flushes_on_elapsed_time_even_when_under_count():
    """A low-volume topic must not leave records sitting in memory forever."""
    batch = BatchAccumulator(max_records=1000, max_seconds=0.05)
    batch.add(_msg(0))
    assert batch.should_flush() is False
    time.sleep(0.06)
    assert batch.should_flush() is True


def test_empty_batch_never_flushes():
    assert BatchAccumulator(max_seconds=0).should_flush() is False


def test_drain_empties_and_resets_the_clock():
    batch = BatchAccumulator(max_records=2, max_seconds=999)
    batch.add(_msg(0))
    batch.add(_msg(1))
    assert len(batch.drain()) == 2
    assert batch.is_empty
    assert batch.should_flush() is False


def test_max_offset_tracked_per_partition():
    """Committing one offset for a multi-partition batch would lose records."""
    batch = BatchAccumulator(max_records=99, max_seconds=999)
    for m in (_msg(5, 0), _msg(9, 0), _msg(2, 1), _msg(7, 1)):
        batch.add(m)
    assert batch.max_offsets() == {("t", 0): 9, ("t", 1): 7}
