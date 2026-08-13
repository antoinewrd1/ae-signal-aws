"""Handler tests using moto - no real AWS calls."""

import json
from unittest.mock import patch

import boto3
from moto import mock_aws

BUCKET = "test-bronze"


def _body(n, total):
    return {
        "meta": {"results": {"total": total, "skip": 0}},
        "results": [{"safetyreportid": str(i)} for i in range(n)],
    }


@mock_aws
@patch("src.extract.client.OpenFDAClient._get")
def test_handler_writes_objects_and_returns_summary(mock_get, monkeypatch):
    mock_get.side_effect = [_body(3, 3)]
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    monkeypatch.setenv("BRONZE_BUCKET", BUCKET)

    from src.extract.handler import lambda_handler

    result = lambda_handler(
        {"start": "2024-01-01", "end": "2024-01-07", "ingest_date": "2024-06-01"}, None
    )

    assert result["status"] == "succeeded"
    assert result["record_count"] == 3
    assert result["content_sha256"]

    keys = [o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET)["Contents"]]
    assert any(k.startswith("bronze/drug_event/ingest_date=2024-06-01/") for k in keys)
    assert any("_manifests" in k for k in keys)


@mock_aws
@patch("src.extract.client.OpenFDAClient._get")
def test_manifest_is_readable_json(mock_get, monkeypatch):
    mock_get.side_effect = [_body(1, 1)]
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    monkeypatch.setenv("BRONZE_BUCKET", BUCKET)

    from src.extract.handler import lambda_handler

    lambda_handler({"start": "2024-01-01", "end": "2024-01-07", "ingest_date": "2024-06-01"}, None)

    key = next(
        o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET)["Contents"] if "_manifests" in o["Key"]
    )
    manifest = json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())
    assert manifest["dataset"] == "drug_event"
    assert manifest["status"] == "succeeded"
    assert manifest["record_count"] == 1
