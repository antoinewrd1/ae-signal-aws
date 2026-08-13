"""Content-addressed response cache.

Development means running the same records repeatedly. Without a cache, every
iteration re-bills every record. The key covers the model, the prompt version
and the record content, so a change to any of the three correctly misses.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

LOG = logging.getLogger(__name__)


def cache_key(record: dict, model_id: str, prompt_version: str) -> str:
    payload = json.dumps(record, sort_keys=True, default=str)
    digest = hashlib.sha256(f"{model_id}|{prompt_version}|{payload}".encode()).hexdigest()
    return digest[:32]


class ResponseCache:
    """Local disk cache. Deliberately not S3 - this exists to protect a
    development loop, not to be shared infrastructure.
    """

    def __init__(self, root: str | Path = ".cache/bedrock", enabled: bool = True) -> None:
        self.root = Path(root)
        self.enabled = enabled
        if self.enabled:
            self.root.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> dict | None:
        if not self.enabled:
            return None
        path = self.root / f"{key}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            # A corrupt cache entry is a cache miss, never a crash.
            LOG.warning("Discarding unreadable cache entry %s", key)
            path.unlink(missing_ok=True)
            return None

    def put(self, key: str, value: dict) -> None:
        if not self.enabled:
            return
        try:
            (self.root / f"{key}.json").write_text(json.dumps(value, default=str))
        except OSError as exc:
            LOG.warning("Could not write cache entry %s: %s", key, exc)

    def clear(self) -> int:
        if not self.enabled or not self.root.exists():
            return 0
        files = list(self.root.glob("*.json"))
        for f in files:
            f.unlink(missing_ok=True)
        return len(files)
