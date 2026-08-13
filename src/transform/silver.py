"""Bronze to silver.

The bronze record is one deeply nested document per adverse event report,
containing arrays of drugs and arrays of reactions. Exploding both in a single
table would produce a cartesian product - a report with 8 drugs and 6
reactions becomes 48 rows, and every downstream count is silently inflated.

Silver is therefore three normalized tables sharing safetyreportid:

    silver_report    one row per report
    silver_drug      one row per (report, drug)
    silver_reaction  one row per (report, reaction)
"""

from __future__ import annotations

from pyspark.sql import Column, DataFrame, Window
from pyspark.sql import functions as F

from .schema import (
    DATE_FORMAT_FULL,
    DATE_FORMAT_MONTH,
    DRUG_ROLE_CODES,
    REACTION_OUTCOME_CODES,
    SERIOUS_CODES,
    SEX_CODES,
)


def decode(column: Column, mapping: dict[str, str]) -> Column:
    """Map coded values to labels, leaving unknown codes as null."""
    expr = F.create_map([F.lit(x) for kv in mapping.items() for x in kv])
    return expr[column]


def parse_fda_date(value: Column, fmt: Column) -> Column:
    """Parse openFDA dates, which carry three different precisions.

    A partial date is real information - it means the reporter did not know
    the exact day. Coercing YYYYMM to the first of the month would invent
    precision, so partial dates resolve to the start of their period and the
    precision is preserved in a separate column.
    """
    return (
        F.when(fmt == F.lit(DATE_FORMAT_FULL), F.to_date(value, "yyyyMMdd"))
        .when(fmt == F.lit(DATE_FORMAT_MONTH), F.to_date(F.concat(value, F.lit("01")), "yyyyMMdd"))
        .when(
            fmt.isNull() & (F.length(value) == 8),
            F.to_date(value, "yyyyMMdd"),
        )
        .otherwise(F.lit(None).cast("date"))
    )


def date_precision(value: Column, fmt: Column) -> Column:
    return (
        F.when(fmt == F.lit(DATE_FORMAT_FULL), F.lit("day"))
        .when(fmt == F.lit(DATE_FORMAT_MONTH), F.lit("month"))
        .when(fmt.isNull() & (F.length(value) == 8), F.lit("day"))
        .otherwise(F.lit("unknown"))
    )


def deduplicate_reports(df: DataFrame) -> DataFrame:
    """Keep one row per safetyreportid: the most recently received version.

    Required, not optional. The streaming path is at-least-once, so replays
    produce genuine duplicates, and openFDA itself issues amended reports
    reusing the same safetyreportid with a higher version.
    """
    # Ordered on the parsed date column, not the raw bronze string. Sorting
    # the raw YYYYMMDD string happens to work; sorting a mix of YYYYMMDD and
    # YYYYMM does not, because "202403" sorts below "20240110".
    ordering = Window.partitionBy("safetyreportid").orderBy(
        F.col("receipt_date").desc_nulls_last(),
        F.col("safetyreportversion").cast("int").desc_nulls_last(),
    )
    return (
        df.withColumn("_rank", F.row_number().over(ordering))
        .filter(F.col("_rank") == 1)
        .drop("_rank")
    )


def build_silver_report(bronze: DataFrame) -> DataFrame:
    df = bronze.select(
        F.col("safetyreportid"),
        F.col("safetyreportversion"),
        parse_fda_date(F.col("receivedate"), F.col("receivedateformat")).alias("receive_date"),
        parse_fda_date(F.col("receiptdate"), F.col("receiptdateformat")).alias("receipt_date"),
        date_precision(F.col("receiptdate"), F.col("receiptdateformat")).alias(
            "receipt_date_precision"
        ),
        decode(F.col("serious"), SERIOUS_CODES).alias("seriousness"),
        (F.col("seriousnessdeath") == "1").alias("outcome_death"),
        (F.col("seriousnesshospitalization") == "1").alias("outcome_hospitalization"),
        (F.col("seriousnesslifethreatening") == "1").alias("outcome_life_threatening"),
        F.col("occurcountry").alias("occur_country"),
        F.col("primarysource.reportercountry").alias("reporter_country"),
        F.col("companynumb").alias("company_number"),
        (F.col("duplicate") == "1").alias("flagged_duplicate"),
        decode(F.col("patient.patientsex"), SEX_CODES).alias("patient_sex"),
        F.col("patient.patientonsetage").cast("double").alias("patient_onset_age"),
        F.col("patient.patientonsetageunit").alias("patient_onset_age_unit"),
        F.size(F.coalesce(F.col("patient.drug"), F.array())).alias("drug_count"),
        F.size(F.coalesce(F.col("patient.reaction"), F.array())).alias("reaction_count"),
    ).filter(F.col("safetyreportid").isNotNull())

    return deduplicate_reports(df)


def build_silver_drug(bronze: DataFrame) -> DataFrame:
    exploded = bronze.select(
        F.col("safetyreportid"),
        F.col("receiptdate"),
        F.col("receiptdateformat"),
        F.posexplode_outer("patient.drug").alias("drug_seq", "drug"),
    ).filter(F.col("safetyreportid").isNotNull() & F.col("drug").isNotNull())

    return exploded.select(
        F.col("safetyreportid"),
        F.col("drug_seq"),
        F.upper(F.trim(F.col("drug.medicinalproduct"))).alias("medicinal_product"),
        F.upper(F.trim(F.col("drug.activesubstance.activesubstancename"))).alias(
            "active_substance"
        ),
        F.element_at(F.col("drug.openfda.generic_name"), 1).alias("generic_name"),
        F.element_at(F.col("drug.openfda.manufacturer_name"), 1).alias("manufacturer"),
        decode(F.col("drug.drugcharacterization"), DRUG_ROLE_CODES).alias("drug_role"),
        F.col("drug.drugindication").alias("indication"),
        parse_fda_date(F.col("drug.drugstartdate"), F.col("drug.drugstartdateformat")).alias(
            "drug_start_date"
        ),
        parse_fda_date(F.col("drug.drugenddate"), F.col("drug.drugenddateformat")).alias(
            "drug_end_date"
        ),
    ).dropDuplicates(["safetyreportid", "drug_seq"])


def build_silver_reaction(bronze: DataFrame) -> DataFrame:
    exploded = bronze.select(
        F.col("safetyreportid"),
        F.posexplode_outer("patient.reaction").alias("reaction_seq", "reaction"),
    ).filter(F.col("safetyreportid").isNotNull() & F.col("reaction").isNotNull())

    return exploded.select(
        F.col("safetyreportid"),
        F.col("reaction_seq"),
        F.upper(F.trim(F.col("reaction.reactionmeddrapt"))).alias("reaction_term"),
        F.col("reaction.reactionmeddraversionpt").alias("meddra_version"),
        decode(F.col("reaction.reactionoutcome"), REACTION_OUTCOME_CODES).alias("reaction_outcome"),
    ).dropDuplicates(["safetyreportid", "reaction_seq"])
