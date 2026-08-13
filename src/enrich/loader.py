"""Assembles enrichment inputs from the silver layer.

Ground-truth labels are attached here and stripped before prompting, so the
label lives beside the prediction for scoring but never reaches the model.
"""

from __future__ import annotations

import glob
import json
from pathlib import Path


def from_silver_parquet(silver_path: str, limit: int | None = None) -> list[dict]:
    """Join silver report/drug/reaction into one dict per report."""
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F

    spark = SparkSession.builder.getOrCreate()

    report = spark.read.parquet(f"{silver_path}/report")
    drug = spark.read.parquet(f"{silver_path}/drug")
    reaction = spark.read.parquet(f"{silver_path}/reaction")

    if limit:
        report = report.limit(limit)

    drugs = drug.groupBy("safetyreportid").agg(
        F.collect_list(
            F.struct("active_substance", "medicinal_product", "drug_role", "indication")
        ).alias("drugs")
    )
    reactions = reaction.groupBy("safetyreportid").agg(
        F.collect_list(F.struct("reaction_term", "reaction_outcome")).alias("reactions")
    )

    joined = (
        report.join(drugs, "safetyreportid", "left")
        .join(reactions, "safetyreportid", "left")
        .select(
            "safetyreportid",
            "patient_sex",
            "patient_onset_age",
            "occur_country",
            "drugs",
            "reactions",
            # Labels. Carried alongside, never rendered into the prompt.
            F.col("seriousness").alias("label_seriousness"),
        )
    )

    return [json.loads(r) for r in joined.toJSON().collect()]


def from_jsonl(path: str, limit: int | None = None) -> list[dict]:
    """Load pre-built enrichment inputs from newline-delimited JSON."""
    files = sorted(glob.glob(path)) if "*" in path else [path]
    records: list[dict] = []
    for f in files:
        for line in Path(f).read_text().splitlines():
            if line.strip():
                records.append(json.loads(line))
                if limit and len(records) >= limit:
                    return records
    return records
