"""Shared streaming configuration."""

from __future__ import annotations

import os

TOPIC = os.environ.get("AE_TOPIC", "ae-signal.drug-event.raw")
BOOTSTRAP = os.environ.get("AE_BOOTSTRAP", "localhost:9092")
CONSUMER_GROUP = os.environ.get("AE_CONSUMER_GROUP", "ae-signal-bronze-writer")


def producer_config(bootstrap: str = BOOTSTRAP) -> dict:
    return {
        "bootstrap.servers": bootstrap,
        # Idempotence stops the producer's own retries from creating
        # duplicates. It does nothing about consumer-side duplicates - those
        # are handled downstream, see docs/streaming.md.
        "enable.idempotence": True,
        "acks": "all",
        "retries": 5,
        "linger.ms": 50,
        "compression.type": "gzip",
    }


def consumer_config(bootstrap: str = BOOTSTRAP, group: str = CONSUMER_GROUP) -> dict:
    return {
        "bootstrap.servers": bootstrap,
        "group.id": group,
        "auto.offset.reset": "earliest",
        # The single most consequential setting here. Auto-commit would
        # acknowledge records before they reach S3, turning a crash into
        # silent data loss. Committing manually after a successful write
        # trades that for at-least-once delivery.
        "enable.auto.commit": False,
        "session.timeout.ms": 45000,
        "max.poll.interval.ms": 300000,
    }
