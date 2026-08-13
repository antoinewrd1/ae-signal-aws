import os
import sys

import pytest

# Spark launches Python workers with whatever `python3` resolves to on PATH -
# the system interpreter, not this venv. A minor-version difference between
# driver and worker fails every task with PYTHON_VERSION_MISMATCH. Pinning both
# to sys.executable keeps them identical.
os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)

# Degrade gracefully when pyspark is unavailable. importorskip at module scope
# would abort collection entirely rather than skipping only the Spark tests.
try:
    import pyspark  # noqa: F401

    HAS_PYSPARK = True
except ImportError:
    HAS_PYSPARK = False

collect_ignore_glob = [] if HAS_PYSPARK else ["test_transform_*.py"]


@pytest.fixture(scope="session")
def spark():
    from pyspark.sql import SparkSession

    session = (
        SparkSession.builder.master("local[2]")
        .appName("ae-signal-tests")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.adaptive.enabled", "false")
        .getOrCreate()
    )
    session.sparkContext.setLogLevel("ERROR")
    yield session
    session.stop()


def _report(
    rid, receipt="20240110", receive="20240105", version="1", drugs=None, reactions=None, **kw
):
    base = {
        "safetyreportid": rid,
        "safetyreportversion": version,
        "receivedate": receive,
        "receivedateformat": "102",
        "receiptdate": receipt,
        "receiptdateformat": "102",
        "serious": "1",
        "seriousnessdeath": None,
        "seriousnesshospitalization": "1",
        "seriousnesslifethreatening": None,
        "occurcountry": "US",
        "companynumb": "C1",
        "duplicate": None,
        "primarysource": {"qualification": "1", "reportercountry": "US"},
        "patient": {
            "patientonsetage": "45",
            "patientonsetageunit": "801",
            "patientsex": "2",
            "drug": drugs if drugs is not None else [_drug("DUPILUMAB")],
            "reaction": reactions if reactions is not None else [_reaction("NAUSEA")],
        },
    }
    base.update(kw)
    return base


def _drug(substance, role="1", product=None):
    return {
        "activesubstance": {"activesubstancename": substance},
        "drugcharacterization": role,
        "drugdosagetext": "300 MG",
        "drugindication": "Dermatitis atopic",
        "drugstartdate": "20230915",
        "drugstartdateformat": "102",
        "drugenddate": None,
        "drugenddateformat": None,
        "medicinalproduct": product or substance,
        "openfda": {
            "application_number": ["BLA761055"],
            "brand_name": [product or substance],
            "generic_name": [substance],
            "manufacturer_name": ["Acme Pharma"],
            "substance_name": [substance],
        },
    }


def _reaction(term, outcome="1"):
    return {
        "reactionmeddrapt": term,
        "reactionmeddraversionpt": "26.1",
        "reactionoutcome": outcome,
    }


@pytest.fixture
def make_report():
    return _report


@pytest.fixture
def make_drug():
    return _drug


@pytest.fixture
def make_reaction():
    return _reaction


@pytest.fixture
def bronze_df(spark):
    from src.transform.schema import BRONZE_SCHEMA

    def _build(records):
        return spark.createDataFrame(records, schema=BRONZE_SCHEMA)

    return _build
