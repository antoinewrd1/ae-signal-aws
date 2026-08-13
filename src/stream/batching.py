"""Batch accumulation logic, deliberately separated from the Kafka client.

Keeping this pure means the interesting behaviour - when to flush, what the
offsets are at flush time - is unit testable without running a broker.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class BatchedMessage:
    key: str | None
    value: dict
    topic: str
    partition: int
    offset: int


@dataclass
class BatchAccumulator:
    """Flushes on record count or elapsed time, whichever comes first.

    Time-based flushing matters: without it, a low-volume topic leaves records
    sitting in memory indefinitely, and an unclean shutdown loses them.
    """

    max_records: int = 200
    max_seconds: float = 10.0
    _messages: list[BatchedMessage] = field(default_factory=list)
    _opened_at: float = field(default_factory=time.monotonic)

    def __len__(self) -> int:
        return len(self._messages)

    @property
    def is_empty(self) -> bool:
        return not self._messages

    def add(self, message: BatchedMessage) -> bool:
        """Append a message. Returns True when the batch is ready to flush."""
        if self.is_empty:
            self._opened_at = time.monotonic()
        self._messages.append(message)
        return self.should_flush()

    def should_flush(self, now: float | None = None) -> bool:
        if self.is_empty:
            return False
        if len(self._messages) >= self.max_records:
            return True
        now = time.monotonic() if now is None else now
        return (now - self._opened_at) >= self.max_seconds

    def drain(self) -> list[BatchedMessage]:
        messages, self._messages = self._messages, []
        self._opened_at = time.monotonic()
        return messages

    def max_offsets(self) -> dict[tuple[str, int], int]:
        """Highest offset seen per (topic, partition).

        Committing the max offset per partition is what makes the commit
        correct when a batch spans several partitions.
        """
        highest: dict[tuple[str, int], int] = {}
        for m in self._messages:
            key = (m.topic, m.partition)
            highest[key] = max(highest.get(key, -1), m.offset)
        return highest
