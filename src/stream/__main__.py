"""Local CLI.

python -m src.stream produce --rate 100 --limit 500
python -m src.stream consume --max-batches 5
"""

from __future__ import annotations

import argparse
import logging

from ..extract.storage import LocalSink, S3Sink
from .config import BOOTSTRAP, CONSUMER_GROUP, TOPIC


def main() -> int:
    parser = argparse.ArgumentParser(description="Kafka-API streaming slice")
    parser.add_argument("mode", choices=["produce", "consume"])
    parser.add_argument("--bootstrap", default=BOOTSTRAP)
    parser.add_argument("--topic", default=TOPIC)
    parser.add_argument("--source", default="./data", help="produce: bronze directory")
    parser.add_argument("--dest", default="./data", help="consume: local dir or s3://bucket")
    parser.add_argument("--rate", type=float, default=50.0, help="produce: records/sec")
    parser.add_argument("--limit", type=int, default=None, help="produce: stop after N")
    parser.add_argument("--group", default=CONSUMER_GROUP)
    parser.add_argument("--max-records", type=int, default=200, help="consume: batch size")
    parser.add_argument("--max-seconds", type=float, default=10.0, help="consume: batch age")
    parser.add_argument("--max-batches", type=int, default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(name)s: %(message)s",
    )

    if args.mode == "produce":
        from .producer import produce

        delivered = produce(
            source=args.source,
            topic=args.topic,
            rate_per_second=args.rate,
            limit=args.limit,
            bootstrap=args.bootstrap,
        )
        print(f"\n  delivered   {delivered}")
        return 0

    from .consumer import consume

    sink = (
        S3Sink(args.dest.removeprefix("s3://").split("/")[0])
        if args.dest.startswith("s3://")
        else LocalSink(args.dest)
    )
    stats = consume(
        sink=sink,
        topic=args.topic,
        group=args.group,
        max_records=args.max_records,
        max_seconds=args.max_seconds,
        max_batches=args.max_batches,
        bootstrap=args.bootstrap,
    )
    print(f"\n  records     {stats['records']}")
    print(f"  batches     {stats['batches']}")
    for k in stats["keys"]:
        print(f"    {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
