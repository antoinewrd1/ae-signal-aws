"""Glue entrypoint.

Deliberately thin. All logic lives in silver.py, gold.py and quality.py as
pure DataFrame functions so it can be unit tested against a local
SparkSession without Glue, without AWS, and without cost. This module only
wires arguments to functions and writes output.

Nothing here uses DynamicFrame or GlueContext beyond the required boilerplate,
so the same code runs unchanged on any Spark.
"""

from __future__ import annotations

import logging
import sys

from pyspark.sql import SparkSession

from .gold import build_drug_reaction_pairs, build_gold_signals
from .quality import (
    check_date_ordering,
    check_not_null,
    check_null_rate,
    check_row_count,
    check_unique,
    enforce,
)
from .schema import BRONZE_SCHEMA
from .silver import build_silver_drug, build_silver_reaction, build_silver_report

LOG = logging.getLogger(__name__)

WRITE_MODE = "overwrite"


def read_bronze(spark: SparkSession, path: str):
    """Read with an explicit schema. Never infer - see schema.py."""
    return spark.read.schema(BRONZE_SCHEMA).json(path)


def run(
    spark: SparkSession, bronze_path: str, silver_path: str, gold_path: str, min_rows: int = 1
) -> dict:
    LOG.info("Reading bronze from %s", bronze_path)
    bronze = read_bronze(spark, bronze_path).cache()

    enforce(
        [check_row_count(bronze, minimum=min_rows), check_not_null(bronze, "safetyreportid")],
        "bronze",
    )

    report = build_silver_report(bronze).cache()
    drug = build_silver_drug(bronze).cache()
    reaction = build_silver_reaction(bronze).cache()

    enforce(
        [
            check_unique(report, ["safetyreportid"]),
            check_not_null(report, "safetyreportid"),
            check_date_ordering(report, "receive_date", "receipt_date"),
            check_null_rate(report, "receipt_date", max_rate=0.05),
            check_unique(drug, ["safetyreportid", "drug_seq"]),
            check_unique(reaction, ["safetyreportid", "reaction_seq"]),
        ],
        "silver",
    )

    report.write.mode(WRITE_MODE).parquet(f"{silver_path}/report")
    drug.write.mode(WRITE_MODE).parquet(f"{silver_path}/drug")
    reaction.write.mode(WRITE_MODE).parquet(f"{silver_path}/reaction")

    pairs = build_drug_reaction_pairs(drug, reaction).cache()
    signals = build_gold_signals(pairs)

    enforce([check_not_null(signals, "active_substance")], "gold")

    signals.write.mode(WRITE_MODE).parquet(f"{gold_path}/drug_reaction_signals")

    stats = {
        "bronze_rows": bronze.count(),
        "silver_report_rows": report.count(),
        "silver_drug_rows": drug.count(),
        "silver_reaction_rows": reaction.count(),
        "gold_signal_rows": signals.count(),
    }
    LOG.info("Transform complete: %s", stats)
    return stats


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")

    try:
        from awsglue.utils import getResolvedOptions

        args = getResolvedOptions(sys.argv, ["JOB_NAME", "bronze_path", "silver_path", "gold_path"])
    except ImportError:
        # Running outside Glue - parse the same flags directly, and pin the
        # worker interpreter. Spark otherwise launches workers with whatever
        # `python3` is on PATH, which is the system interpreter rather than
        # this venv; a minor-version difference fails every task with
        # PYTHON_VERSION_MISMATCH. Glue sets these itself.
        import argparse
        import os

        os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
        os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)

        parser = argparse.ArgumentParser()
        parser.add_argument("--bronze_path", required=True)
        parser.add_argument("--silver_path", required=True)
        parser.add_argument("--gold_path", required=True)
        parser.add_argument("--JOB_NAME", default="local")
        args = vars(parser.parse_args())

    spark = (
        SparkSession.builder.appName(args.get("JOB_NAME", "ae-signal-transform"))
        .config("spark.sql.sources.partitionOverwriteMode", "dynamic")
        .getOrCreate()
    )

    try:
        stats = run(spark, args["bronze_path"], args["silver_path"], args["gold_path"])
        for k, v in stats.items():
            print(f"  {k:26} {v}")
        return 0
    finally:
        spark.stop()


if __name__ == "__main__":
    raise SystemExit(main())
