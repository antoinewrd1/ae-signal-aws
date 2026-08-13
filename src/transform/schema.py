"""Explicit bronze schema.

Schema inference is not used. Inferring from a sample means the job's schema
silently changes when the sample does, and openFDA's optional nested fields
make that near-certain. An explicit schema turns a schema change into a
visible diff in version control instead of a surprise in production.
"""

from __future__ import annotations

from pyspark.sql.types import (
    ArrayType,
    StringType,
    StructField,
    StructType,
)

_ACTIVE_SUBSTANCE = StructType([StructField("activesubstancename", StringType())])

_OPENFDA = StructType(
    [
        StructField("application_number", ArrayType(StringType())),
        StructField("brand_name", ArrayType(StringType())),
        StructField("generic_name", ArrayType(StringType())),
        StructField("manufacturer_name", ArrayType(StringType())),
        StructField("substance_name", ArrayType(StringType())),
    ]
)

_DRUG = StructType(
    [
        StructField("activesubstance", _ACTIVE_SUBSTANCE),
        StructField("drugcharacterization", StringType()),
        StructField("drugdosagetext", StringType()),
        StructField("drugindication", StringType()),
        StructField("drugstartdate", StringType()),
        StructField("drugstartdateformat", StringType()),
        StructField("drugenddate", StringType()),
        StructField("drugenddateformat", StringType()),
        StructField("medicinalproduct", StringType()),
        StructField("openfda", _OPENFDA),
    ]
)

_REACTION = StructType(
    [
        StructField("reactionmeddrapt", StringType()),
        StructField("reactionmeddraversionpt", StringType()),
        StructField("reactionoutcome", StringType()),
    ]
)

_PATIENT = StructType(
    [
        StructField("patientonsetage", StringType()),
        StructField("patientonsetageunit", StringType()),
        StructField("patientsex", StringType()),
        StructField("drug", ArrayType(_DRUG)),
        StructField("reaction", ArrayType(_REACTION)),
    ]
)

_PRIMARY_SOURCE = StructType(
    [
        StructField("qualification", StringType()),
        StructField("reportercountry", StringType()),
    ]
)

BRONZE_SCHEMA = StructType(
    [
        StructField("safetyreportid", StringType()),
        StructField("safetyreportversion", StringType()),
        StructField("receivedate", StringType()),
        StructField("receivedateformat", StringType()),
        StructField("receiptdate", StringType()),
        StructField("receiptdateformat", StringType()),
        StructField("serious", StringType()),
        StructField("seriousnessdeath", StringType()),
        StructField("seriousnesshospitalization", StringType()),
        StructField("seriousnesslifethreatening", StringType()),
        StructField("occurcountry", StringType()),
        StructField("companynumb", StringType()),
        StructField("duplicate", StringType()),
        StructField("primarysource", _PRIMARY_SOURCE),
        StructField("patient", _PATIENT),
    ]
)

# openFDA encodes date precision in a companion *dateformat field.
# 102 = YYYYMMDD, 610 = YYYYMM, 602 = YYYY.
DATE_FORMAT_FULL = "102"
DATE_FORMAT_MONTH = "610"
DATE_FORMAT_YEAR = "602"

# Coded value lookups, kept here so the meaning lives with the schema.
SEX_CODES = {"1": "male", "2": "female"}
SERIOUS_CODES = {"1": "serious", "2": "non_serious"}
DRUG_ROLE_CODES = {"1": "suspect", "2": "concomitant", "3": "interacting"}
REACTION_OUTCOME_CODES = {
    "1": "recovered",
    "2": "recovering",
    "3": "not_recovered",
    "4": "recovered_with_sequelae",
    "5": "fatal",
    "6": "unknown",
}
