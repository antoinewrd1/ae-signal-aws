"""Enrichment Lambda handler. moto for S3, stub for Bedrock."""

import gzip
import json
from unittest.mock import patch

import boto3
from moto import mock_aws

BUCKET = "test-bronze"
PREFIX = "silver/enrichment_input/"


def _input_record(rid):
    return {
        "safetyreportid": rid,
        "patient_sex": "female",
        "patient_onset_age": 45.0,
        "occur_country": "US",
        "drugs": [{"active_substance": "DUPILUMAB", "drug_role": "suspect"}],
        "reactions": [{"reaction_term": "NAUSEA", "reaction_outcome": "recovered"}],
        "label_seriousness": "serious",
    }


def _seed(s3, records, gzipped=False):
    body = "\n".join(json.dumps(r) for r in records).encode()
    key = f"{PREFIX}part-0000.json" + (".gz" if gzipped else "")
    s3.put_object(Bucket=BUCKET, Key=key, Body=gzip.compress(body) if gzipped else body)


class _StubAssessor:
    model_id = "stub-model"

    def assess(self, record):
        return {
            "tool_input": {
                "seriousness": "serious",
                "primary_suspect": "DUPILUMAB",
                "key_reactions": ["NAUSEA"],
                "confidence": "high",
                "rationale": "Hospitalisation reported.",
            },
            "input_tokens": 100,
            "output_tokens": 20,
            "latency_ms": 300,
            "model_id": self.model_id,
        }


@mock_aws
def test_handler_reads_input_and_writes_gold(monkeypatch):
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    _seed(s3, [_input_record(str(i)) for i in range(3)])
    monkeypatch.setenv("BRONZE_BUCKET", BUCKET)

    from src.enrich.handler import lambda_handler

    with patch("src.enrich.handler.BedrockAssessor", return_value=_StubAssessor()):
        result = lambda_handler({"limit": 10}, None)

    assert result["attempted"] == 3
    assert result["enriched"] == 3
    assert result["dead_lettered"] == 0

    keys = [o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET)["Contents"]]
    assert any(k.startswith("gold/assessments/") for k in keys)


@mock_aws
def test_handler_reads_gzipped_input(monkeypatch):
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    _seed(s3, [_input_record("1")], gzipped=True)
    monkeypatch.setenv("BRONZE_BUCKET", BUCKET)

    from src.enrich.handler import lambda_handler

    with patch("src.enrich.handler.BedrockAssessor", return_value=_StubAssessor()):
        assert lambda_handler({}, None)["enriched"] == 1


@mock_aws
def test_limit_caps_billed_calls(monkeypatch):
    """Every record is a model call. An uncapped scheduled run is the most
    expensive mistake available here."""
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    _seed(s3, [_input_record(str(i)) for i in range(50)])
    monkeypatch.setenv("BRONZE_BUCKET", BUCKET)

    from src.enrich.handler import lambda_handler

    with patch("src.enrich.handler.BedrockAssessor", return_value=_StubAssessor()):
        assert lambda_handler({"limit": 5}, None)["attempted"] == 5


@mock_aws
def test_empty_input_returns_cleanly_rather_than_raising(monkeypatch):
    """Step Functions branches on this; an exception would fail the execution."""
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    monkeypatch.setenv("BRONZE_BUCKET", BUCKET)

    from src.enrich.handler import lambda_handler

    result = lambda_handler({}, None)
    assert result["status"] == "no_input"
    assert result["attempted"] == 0


@mock_aws
def test_spark_success_markers_skipped(monkeypatch):
    """Spark writes _SUCCESS alongside data; parsing it as JSON would fail."""
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    _seed(s3, [_input_record("1")])
    s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}_SUCCESS", Body=b"")
    monkeypatch.setenv("BRONZE_BUCKET", BUCKET)

    from src.enrich.handler import lambda_handler

    with patch("src.enrich.handler.BedrockAssessor", return_value=_StubAssessor()):
        assert lambda_handler({}, None)["enriched"] == 1
