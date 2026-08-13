"""Local CLI: python -m src.extract --start 2024-01-01 --end 2024-01-07"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import date, timedelta

from .runner import run_extraction
from .storage import LocalSink, S3Sink


def main() -> int:
    default_end = date.today() - timedelta(days=30)

    parser = argparse.ArgumentParser(description="Extract openFDA drug event records")
    parser.add_argument("--start", type=date.fromisoformat, default=default_end - timedelta(days=6))
    parser.add_argument("--end", type=date.fromisoformat, default=default_end)
    parser.add_argument("--dest", default="./data", help="local directory, or s3://bucket for S3")
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument(
        "--max-records",
        type=int,
        default=200,
        help="per window; keeps development runs inside the API quota",
    )
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(name)s: %(message)s",
    )

    sink = (
        S3Sink(args.dest.removeprefix("s3://").split("/")[0])
        if args.dest.startswith("s3://")
        else LocalSink(args.dest)
    )

    manifest = run_extraction(
        sink=sink,
        start=args.start,
        end=args.end,
        window_days=args.window_days,
        max_records_per_window=args.max_records,
        batch_size=args.batch_size,
        api_key=os.environ.get("OPENFDA_API_KEY") or None,
    )

    print()
    print(f"  run_id        {manifest.run_id}")
    print(f"  status        {manifest.status}")
    print(f"  records       {manifest.record_count}")
    print(f"  windows       {manifest.window_count}")
    print(f"  objects       {len(manifest.object_keys)}")
    print(f"  bytes         {manifest.byte_count:,}")
    print(f"  duration      {manifest.duration_seconds}s")
    print(f"  sha256        {manifest.content_sha256[:16]}...")
    return 0 if manifest.status == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
