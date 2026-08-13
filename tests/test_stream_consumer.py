"""Delivery-semantics tests. No broker required."""

import gzip
import json

import pytest

from src.stream.batching import BatchedMessage
from src.stream.consumer import stream_key, write_batch
from src.stream.producer import message_key


class RecordingSink:
    def __init__(self, fail=False):
        self.objects = {}
        self.fail = fail

    def write(self, key, payload, content_type="application/json"):
        if self.fail:
            raise OSError("s3 unavailable")
        self.objects[key] = payload
        return f"mem://{key}"


def _msgs(n):
    return [
        BatchedMessage(
            key=str(i), value={"safetyreportid": str(i)}, topic="t", partition=0, offset=i
        )
        for i in range(n)
    ]


def test_batch_written_as_gzipped_ndjson():
    sink = RecordingSink()
    key = write_batch(sink, _msgs(3), "2026-06-01")
    lines = gzip.decompress(sink.objects[key]).decode().splitlines()
    assert len(lines) == 3
    assert json.loads(lines[0])["safetyreportid"] == "0"


def test_write_failure_propagates_so_offsets_are_never_committed():
    """The whole at-least-once guarantee rests on this.

    If write_batch swallowed the error, consume() would commit offsets for a
    batch that never reached storage - silent data loss on every S3 blip.
    """
    with pytest.raises(OSError):
        write_batch(RecordingSink(fail=True), _msgs(2), "2026-06-01")


def test_stream_key_is_partitioned_by_ingest_date():
    key = stream_key("2026-06-01", "abc123")
    assert key.startswith("bronze-stream/drug_event/ingest_date=2026-06-01/")
    assert key.endswith(".json.gz")


def test_message_key_uses_safetyreportid_for_per_report_ordering():
    assert message_key({"safetyreportid": 12345}) == "12345"


def test_message_key_none_when_absent():
    """Unkeyed messages round-robin across partitions and lose per-key ordering."""
    assert message_key({"companynumb": "X"}) is None
