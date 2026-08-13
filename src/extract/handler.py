"""Lambda entrypoint.

Returns a summary dict rather than logging and exiting, so Step Functions can
branch on record_count in a Choice state on day 6.
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta

from .runner import run_extraction
from .storage import S3Sink

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
LOG = logging.getLogger(__name__)


def _parse_date(value: str | None, default: date) -> date:
    return date.fromisoformat(value) if value else default


def lambda_handler(event: dict | None, context) -> dict:
    event = event or {}

    # Default to a window ending 30 days ago. openFDA lags real time by weeks,
    # so querying yesterday reliably returns nothing.
    default_end = date.today() - timedelta(days=30)
    default_start = default_end - timedelta(days=6)

    start = _parse_date(event.get("start"), default_start)
    end = _parse_date(event.get("end"), default_end)

    bucket = os.environ["BRONZE_BUCKET"]
    max_records = event.get("max_records_per_window")
    if max_records is None:
        max_records = int(os.environ.get("MAX_RECORDS_PER_WINDOW", "500"))

    LOG.info("Extracting %s..%s into s3://%s", start, end, bucket)

    manifest = run_extraction(
        sink=S3Sink(bucket),
        start=start,
        end=end,
        ingest_date=event.get("ingest_date") or date.today().isoformat(),
        window_days=int(event.get("window_days", 7)),
        max_records_per_window=max_records,
        api_key=os.environ.get("OPENFDA_API_KEY") or None,
    )

    return {
        "run_id": manifest.run_id,
        "status": manifest.status,
        "record_count": manifest.record_count,
        "window_count": manifest.window_count,
        "object_keys": manifest.object_keys,
        "duration_seconds": manifest.duration_seconds,
        "content_sha256": manifest.content_sha256,
    }
