"""Replays bronze records onto a Kafka topic to simulate a live feed.

Redpanda speaks the Kafka protocol, so this is real Kafka client code against
a real broker - it is simply running in Docker rather than on managed MSK.
"""

from __future__ import annotations

import gzip
import json
import logging
import time
from collections.abc import Iterator
from pathlib import Path

from .config import TOPIC, producer_config

LOG = logging.getLogger(__name__)


def read_bronze(root: str | Path) -> Iterator[dict]:
    """Yield records from gzipped newline-delimited JSON written by the extractor."""
    files = sorted(Path(root).rglob("part-*.json.gz"))
    if not files:
        raise FileNotFoundError(
            f"No bronze files under {root}. Run: python -m src.extract --dest ./data"
        )
    for path in files:
        LOG.info("Reading %s", path)
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)


def message_key(record: dict) -> str | None:
    """Partition on safetyreportid.

    Keying matters beyond load spreading: all messages for one report land on
    the same partition, so their relative order is preserved. Without a key,
    an amended report could be processed before the original.
    """
    key = record.get("safetyreportid")
    return str(key) if key is not None else None


def produce(
    source: str = "./data",
    topic: str = TOPIC,
    rate_per_second: float = 50.0,
    limit: int | None = None,
    bootstrap: str | None = None,
) -> int:
    from confluent_kafka import Producer

    config = producer_config(bootstrap) if bootstrap else producer_config()
    producer = Producer(config)

    delivered = 0
    failed = 0

    def on_delivery(err, msg):
        nonlocal delivered, failed
        if err is not None:
            failed += 1
            LOG.error("Delivery failed: %s", err)
        else:
            delivered += 1

    interval = 1.0 / rate_per_second if rate_per_second > 0 else 0.0
    sent = 0

    for record in read_bronze(source):
        if limit is not None and sent >= limit:
            break

        producer.produce(
            topic=topic,
            key=message_key(record),
            value=json.dumps(record, sort_keys=True).encode("utf-8"),
            on_delivery=on_delivery,
        )
        sent += 1

        # poll(0) services delivery callbacks. Without it the internal queue
        # fills and produce() starts raising BufferError.
        producer.poll(0)

        if interval:
            time.sleep(interval)

        if sent % 100 == 0:
            LOG.info("Produced %d records", sent)

    LOG.info("Flushing producer")
    remaining = producer.flush(timeout=30)
    if remaining:
        LOG.warning("%d messages still unflushed after timeout", remaining)

    LOG.info("Sent %d, delivered %d, failed %d", sent, delivered, failed)
    return delivered
