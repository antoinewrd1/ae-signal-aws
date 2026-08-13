"""Consumes the topic and lands batches in the bronze-stream prefix.

Delivery semantics are at-least-once by construction: the offset commit
happens only after the batch is durably written. A crash between write and
commit replays that batch, which is why the downstream layer deduplicates on
safetyreportid rather than assuming exactly-once.
"""

from __future__ import annotations

import json
import logging
import signal
import uuid
from datetime import date

from ..extract.storage import Sink, gzip_bytes
from .batching import BatchAccumulator, BatchedMessage
from .config import CONSUMER_GROUP, TOPIC, consumer_config

LOG = logging.getLogger(__name__)

_shutdown = False


def _handle_signal(signum, frame):  # noqa: ARG001
    global _shutdown
    LOG.info("Signal %s received - draining current batch before exit", signum)
    _shutdown = True


def stream_key(ingest_date: str, batch_id: str) -> str:
    return f"bronze-stream/drug_event/ingest_date={ingest_date}/batch-{batch_id}.json.gz"


def write_batch(sink: Sink, messages: list[BatchedMessage], ingest_date: str) -> str:
    payload = "\n".join(json.dumps(m.value, sort_keys=True) for m in messages)
    key = stream_key(ingest_date, uuid.uuid4().hex[:10])
    sink.write(key, gzip_bytes(payload.encode("utf-8")))
    return key


def consume(
    sink: Sink,
    topic: str = TOPIC,
    group: str = CONSUMER_GROUP,
    max_records: int = 200,
    max_seconds: float = 10.0,
    max_batches: int | None = None,
    idle_timeout: float = 30.0,
    bootstrap: str | None = None,
) -> dict:
    from confluent_kafka import Consumer, KafkaError

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    config = consumer_config(bootstrap, group) if bootstrap else consumer_config(group=group)
    consumer = Consumer(config)
    consumer.subscribe([topic])

    batch = BatchAccumulator(max_records=max_records, max_seconds=max_seconds)
    ingest_date = date.today().isoformat()
    stats = {"records": 0, "batches": 0, "keys": []}
    idle_polls = 0

    def flush() -> None:
        if batch.is_empty:
            return
        messages = batch.drain()
        key = write_batch(sink, messages, ingest_date)
        # Commit only after the write succeeded. If write_batch raises, the
        # offsets stay uncommitted and these records are redelivered.
        consumer.commit(asynchronous=False)
        stats["records"] += len(messages)
        stats["batches"] += 1
        stats["keys"].append(key)
        LOG.info("Flushed %d records to %s", len(messages), key)

    try:
        while not _shutdown:
            if max_batches is not None and stats["batches"] >= max_batches:
                break

            msg = consumer.poll(1.0)

            if msg is None:
                idle_polls += 1
                if batch.should_flush():
                    flush()
                if idle_polls >= idle_timeout:
                    LOG.info("Idle for %.0fs - stopping", idle_timeout)
                    break
                continue

            idle_polls = 0

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                LOG.error("Consumer error: %s", msg.error())
                continue

            record = json.loads(msg.value().decode("utf-8"))
            ready = batch.add(
                BatchedMessage(
                    key=msg.key().decode("utf-8") if msg.key() else None,
                    value=record,
                    topic=msg.topic(),
                    partition=msg.partition(),
                    offset=msg.offset(),
                )
            )
            if ready:
                flush()

        flush()
    finally:
        LOG.info("Closing consumer - triggers a clean group rebalance")
        consumer.close()

    return stats
