"""Storage abstraction so the extractor runs identically locally and in Lambda.

Same interface either way: a local path during development, S3 in deployment.
This is what lets the unit tests run with no AWS calls at all.
"""

from __future__ import annotations

import gzip
import logging
from abc import ABC, abstractmethod
from pathlib import Path

LOG = logging.getLogger(__name__)


class Sink(ABC):
    @abstractmethod
    def write(self, key: str, payload: bytes, content_type: str = "application/json") -> str:
        """Persist payload at key. Returns a URI for the manifest."""


class LocalSink(Sink):
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def write(self, key: str, payload: bytes, content_type: str = "application/json") -> str:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        LOG.info("Wrote %d bytes to %s", len(payload), path)
        return str(path)


class S3Sink(Sink):
    def __init__(self, bucket: str, client=None) -> None:
        import boto3

        self.bucket = bucket
        self.client = client or boto3.client("s3")

    def write(self, key: str, payload: bytes, content_type: str = "application/json") -> str:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=payload,
            ContentType=content_type,
            ContentEncoding="gzip" if key.endswith(".gz") else "identity",
        )
        LOG.info("Wrote %d bytes to s3://%s/%s", len(payload), self.bucket, key)
        return f"s3://{self.bucket}/{key}"


def gzip_bytes(payload: bytes) -> bytes:
    # mtime=0 keeps the output byte-identical across runs, so re-running the
    # same extraction produces the same checksum instead of spurious drift.
    return gzip.compress(payload, mtime=0)


def bronze_key(dataset: str, ingest_date: str, part: int) -> str:
    return f"bronze/{dataset}/ingest_date={ingest_date}/part-{part:05d}.json.gz"


def manifest_key(dataset: str, ingest_date: str, run_id: str) -> str:
    return f"bronze/_manifests/{dataset}/ingest_date={ingest_date}/{run_id}.json"
