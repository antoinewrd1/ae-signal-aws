"""Run manifests.

Every extraction writes a manifest alongside its data. This is what makes the
question "did the pipeline run correctly?" answerable after the fact instead of
a matter of trust: it records what was requested, what came back, how long it
took, and a checksum of the payload.
"""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def sha256_of(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@dataclass
class RunManifest:
    run_id: str
    dataset: str
    ingest_date: str
    started_at: str
    finished_at: str = ""
    duration_seconds: float = 0.0
    record_count: int = 0
    window_count: int = 0
    request_count: int = 0
    byte_count: int = 0
    content_sha256: str = ""
    object_keys: list[str] = field(default_factory=list)
    windows: list[dict] = field(default_factory=list)
    query_params: dict = field(default_factory=dict)
    status: str = "running"
    error: str | None = None
    extractor_version: str = "0.1.0"
    python_version: str = field(default_factory=platform.python_version)

    def complete(self, started_monotonic: float, now_monotonic: float) -> None:
        self.finished_at = utcnow_iso()
        self.duration_seconds = round(now_monotonic - started_monotonic, 3)
        if self.status == "running":
            self.status = "succeeded"

    def fail(self, exc: Exception) -> None:
        self.status = "failed"
        self.error = f"{type(exc).__name__}: {exc}"

    def to_json(self) -> bytes:
        return json.dumps(asdict(self), indent=2, sort_keys=True).encode("utf-8")
