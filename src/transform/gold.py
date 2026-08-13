"""Silver to gold: drug-reaction pair frequencies with a disproportionality signal.

The metric computed here is the Proportional Reporting Ratio (PRR), a standard
first-pass pharmacovigilance screen. Its limitations are severe and are stated
in docs/architecture.md - spontaneous reporting data has no denominator, no
control group, and heavy reporting bias. PRR flags pairs worth a human look.
It does not establish causation and nothing here should be read as if it does.
"""

from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

# Below this count, PRR is dominated by noise. A pair seen twice can produce a
# spectacular ratio that means nothing at all.
MIN_PAIR_COUNT = 3

# Haldane-Anscombe correction. When a reaction is only ever reported with one
# drug, cell c is zero and PRR is mathematically undefined - yet that is the
# strongest possible signal, so returning null would discard exactly the rows
# most worth looking at. Adding 0.5 to every cell of the table when any cell is
# zero is the standard pharmacovigilance handling. The correction is flagged in
# the output so a reader knows the value is adjusted rather than observed.
CONTINUITY_CORRECTION = 0.5


def build_drug_reaction_pairs(
    silver_drug: DataFrame, silver_reaction: DataFrame, suspect_only: bool = True
) -> DataFrame:
    """One row per (report, substance, reaction).

    The join is within a report, so the cartesian product is bounded by that
    report's own drug and reaction counts - which is exactly the relationship
    being measured, and why silver kept the two exploded separately.
    """
    drugs = silver_drug.filter(F.col("active_substance").isNotNull())
    if suspect_only:
        drugs = drugs.filter(F.col("drug_role") == "suspect")

    return (
        drugs.select("safetyreportid", "active_substance")
        .join(
            silver_reaction.filter(F.col("reaction_term").isNotNull()).select(
                "safetyreportid", "reaction_term"
            ),
            on="safetyreportid",
            how="inner",
        )
        .dropDuplicates(["safetyreportid", "active_substance", "reaction_term"])
    )


def build_gold_signals(
    pairs: DataFrame,
    min_count: int = MIN_PAIR_COUNT,
    correction: float = CONTINUITY_CORRECTION,
) -> DataFrame:
    """Compute PRR per (substance, reaction) from the 2x2 contingency table.

    a = reports with this drug and this reaction
    b = reports with this drug, any other reaction
    c = reports with other drugs and this reaction
    d = reports with other drugs, other reactions

    PRR = (a / (a + b)) / (c / (c + d))
    """
    total = pairs.count()

    a = pairs.groupBy("active_substance", "reaction_term").agg(F.count("*").alias("a"))
    drug_totals = pairs.groupBy("active_substance").agg(F.count("*").alias("drug_total"))
    reaction_totals = pairs.groupBy("reaction_term").agg(F.count("*").alias("reaction_total"))

    joined = (
        a.join(drug_totals, on="active_substance", how="inner")
        .join(reaction_totals, on="reaction_term", how="inner")
        .withColumn("b", F.col("drug_total") - F.col("a"))
        .withColumn("c", F.col("reaction_total") - F.col("a"))
        .withColumn("d", F.lit(total) - F.col("a") - F.col("b") - F.col("c"))
    )

    has_zero_cell = (F.col("a") == 0) | (F.col("b") == 0) | (F.col("c") == 0) | (F.col("d") == 0)
    adj = F.when(has_zero_cell, F.lit(correction)).otherwise(F.lit(0.0))

    a_adj, b_adj = F.col("a") + adj, F.col("b") + adj
    c_adj, d_adj = F.col("c") + adj, F.col("d") + adj

    exposed_rate = a_adj / (a_adj + b_adj)
    unexposed_rate = c_adj / (c_adj + d_adj)

    return (
        joined.withColumn("continuity_corrected", has_zero_cell)
        .withColumn(
            "prr",
            F.when(unexposed_rate == 0, F.lit(None).cast("double")).otherwise(
                F.round(exposed_rate / unexposed_rate, 4)
            ),
        )
        .withColumn("report_count", F.col("a"))
        .withColumn("meets_min_count", F.col("a") >= F.lit(min_count))
        .select(
            "active_substance",
            "reaction_term",
            "report_count",
            "a",
            "b",
            "c",
            "d",
            "prr",
            "continuity_corrected",
            "meets_min_count",
        )
        .orderBy(F.col("report_count").desc(), F.col("prr").desc_nulls_last())
    )
