"""Lambda entrypoint for the enrichment stage.

Reads the newline-delimited JSON that the Glue job materialised, so this
function needs no Spark. Returns a summary dict for Step Functions to branch
on rather than logging and exiting.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
from datetime import date

import boto3

from .bedrock import BedrockAssessor
from .cache import ResponseCache
from .runner import enrich_records

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
LOG = logging.getLogger(__name__)


def read_jsonl_from_s3(bucket: str, prefix: str, limit: int | None = None) -> list[dict]:
    s3 = boto3.client("s3")
    records: list[dict] = []

    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/") or "_SUCCESS" in key:
                continue
            body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            if key.endswith(".gz"):
                body = gzip.decompress(body)
            for line in body.decode("utf-8").splitlines():
                if line.strip():
                    records.append(json.loads(line))
                    if limit and len(records) >= limit:
                        return records
    return records


def lambda_handler(event: dict | None, context) -> dict:
    event = event or {}
    bucket = os.environ["BRONZE_BUCKET"]

    # Hard cap. Every record is a billed model call, and an unbounded run
    # triggered by a schedule is the most expensive mistake available here.
    limit = int(event.get("limit") or os.environ.get("ENRICH_LIMIT", "50"))

    prefix = event.get("prefix", "silver/enrichment_input/")
    records = read_jsonl_from_s3(bucket, prefix, limit=limit)

    if not records:
        LOG.warning("No enrichment input under s3://%s/%s", bucket, prefix)
        return {"status": "no_input", "attempted": 0, "enriched": 0, "dead_lettered": 0}

    from ..extract.storage import S3Sink

    metrics = enrich_records(
        records=records,
        sink=S3Sink(bucket),
        assessor=BedrockAssessor(
            model_id=os.environ.get("BEDROCK_MODEL_ID") or None,
            region=os.environ.get("AWS_REGION", "us-east-1"),
        ),
        # No cache in Lambda: the filesystem is ephemeral, so it would never
        # hit and would only add write latency.
        cache=ResponseCache(enabled=False),
        ingest_date=event.get("ingest_date") or date.today().isoformat(),
    )
    return metrics
