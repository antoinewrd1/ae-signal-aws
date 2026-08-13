"""Extraction orchestration: windows -> pages -> batched objects -> manifest."""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import date

from .client import OpenFDAClient
from .manifest import RunManifest, sha256_of, utcnow_iso
from .storage import Sink, bronze_key, gzip_bytes, manifest_key
from .windows import partition_by_days, received_date_query

LOG = logging.getLogger(__name__)

DATASET = "drug_event"


def run_extraction(
    sink: Sink,
    start: date,
    end: date,
    ingest_date: str | None = None,
    window_days: int = 7,
    max_records_per_window: int | None = 500,
    batch_size: int = 500,
    api_key: str | None = None,
    run_id: str | None = None,
) -> RunManifest:
    """Pull openFDA drug event records for a date range and land them raw.

    Records are written unmodified. Any cleaning belongs in the silver layer -
    a bronze layer that has already been transformed cannot be replayed.
    """
    run_id = run_id or uuid.uuid4().hex[:12]
    ingest_date = ingest_date or date.today().isoformat()
    client = OpenFDAClient(api_key=api_key)

    manifest = RunManifest(
        run_id=run_id,
        dataset=DATASET,
        ingest_date=ingest_date,
        started_at=utcnow_iso(),
        query_params={
            "start": start.isoformat(),
            "end": end.isoformat(),
            "window_days": window_days,
            "max_records_per_window": max_records_per_window,
            "batch_size": batch_size,
            "api_key_used": bool(api_key),
        },
    )

    started = time.monotonic()
    digest_input = bytearray()
    buffer: list[dict] = []
    part = 0

    def flush() -> None:
        nonlocal buffer, part
        if not buffer:
            return
        payload = ("\n".join(json.dumps(r, sort_keys=True) for r in buffer)).encode("utf-8")
        digest_input.extend(payload)
        compressed = gzip_bytes(payload)
        key = bronze_key(DATASET, ingest_date, part)
        sink.write(key, compressed)
        manifest.object_keys.append(key)
        manifest.byte_count += len(compressed)
        part += 1
        buffer = []

    try:
        for window_start, window_end in partition_by_days(start, end, window_days):
            search = received_date_query(window_start, window_end)
            window_records = 0

            for record in client.iter_records(search, max_records=max_records_per_window):
                buffer.append(record)
                window_records += 1
                manifest.record_count += 1
                if len(buffer) >= batch_size:
                    flush()

            manifest.window_count += 1
            manifest.windows.append(
                {
                    "start": window_start.isoformat(),
                    "end": window_end.isoformat(),
                    "records": window_records,
                }
            )
            LOG.info("Window %s..%s yielded %d records", window_start, window_end, window_records)

        flush()
        manifest.content_sha256 = sha256_of(bytes(digest_input))
        manifest.request_count = client.request_count

    except Exception as exc:  # noqa: BLE001 - recorded then re-raised
        flush()
        manifest.request_count = client.request_count
        manifest.fail(exc)
        manifest.complete(started, time.monotonic())
        sink.write(manifest_key(DATASET, ingest_date, run_id), manifest.to_json())
        raise

    manifest.complete(started, time.monotonic())
    sink.write(manifest_key(DATASET, ingest_date, run_id), manifest.to_json())
    return manifest
