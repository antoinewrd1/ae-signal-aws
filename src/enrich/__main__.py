"""Local CLI:

python -m src.enrich --silver ./data/silver --limit 20
python -m src.enrich --silver ./data/silver --limit 100 --no-cache
"""

from __future__ import annotations

import argparse
import logging

from ..extract.storage import LocalSink, S3Sink
from .bedrock import BedrockAssessor
from .cache import ResponseCache
from .loader import from_jsonl, from_silver_parquet
from .runner import enrich_records


def main() -> int:
    parser = argparse.ArgumentParser(description="Bedrock enrichment")
    parser.add_argument("--silver", default="./data/silver")
    parser.add_argument("--jsonl", default=None, help="use pre-built inputs instead of silver")
    parser.add_argument("--dest", default="./data")
    parser.add_argument("--limit", type=int, default=20, help="cap records; every one costs money")
    parser.add_argument("--model-id", default=None)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(name)s: %(message)s",
    )

    records = (
        from_jsonl(args.jsonl, args.limit)
        if args.jsonl
        else from_silver_parquet(args.silver, args.limit)
    )
    if not records:
        print("No records found. Run: make transform-local")
        return 1

    sink = (
        S3Sink(args.dest.removeprefix("s3://").split("/")[0])
        if args.dest.startswith("s3://")
        else LocalSink(args.dest)
    )

    metrics = enrich_records(
        records=records,
        sink=sink,
        assessor=BedrockAssessor(model_id=args.model_id, region=args.region),
        cache=ResponseCache(enabled=not args.no_cache),
    )

    print()
    for k in (
        "attempted",
        "enriched",
        "dead_lettered",
        "success_rate",
        "cache_hits",
        "input_tokens",
        "output_tokens",
        "estimated_cost_usd",
        "cost_per_1k_records_usd",
        "duration_seconds",
    ):
        print(f"  {k:26} {metrics[k]}")
    print(f"  {'model_id':26} {metrics['model_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
