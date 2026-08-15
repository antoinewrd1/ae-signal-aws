"""Enrichment orchestration: cache -> model -> validate -> retry -> DLQ."""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import date

from pydantic import ValidationError

from ..extract.storage import Sink, gzip_bytes
from .bedrock import BedrockAssessor, BedrockError, estimate_cost
from .cache import ResponseCache, cache_key
from .models import Assessment, DeadLetter, EnrichedRecord
from .prompt import PROMPT_VERSION

LOG = logging.getLogger(__name__)

MAX_VALIDATION_ATTEMPTS = 2


def gold_key(ingest_date: str, run_id: str) -> str:
    return f"gold/assessments/ingest_date={ingest_date}/run-{run_id}.json.gz"


def dlq_key(ingest_date: str, run_id: str) -> str:
    return f"gold/_dlq/assessments/ingest_date={ingest_date}/run-{run_id}.json.gz"


def metrics_key(ingest_date: str, run_id: str) -> str:
    return f"gold/_metrics/assessments/ingest_date={ingest_date}/run-{run_id}.json"


def enrich_records(
    records: list[dict],
    sink: Sink,
    assessor: BedrockAssessor | None = None,
    cache: ResponseCache | None = None,
    ingest_date: str | None = None,
    run_id: str | None = None,
) -> dict:
    """Assess each record, validate, and land results plus a DLQ and metrics.

    Records that fail schema validation twice go to the dead letter prefix.
    They are never dropped: a silent drop makes the denominator wrong and every
    downstream rate look better than it is.
    """
    assessor = assessor or BedrockAssessor()
    cache = cache if cache is not None else ResponseCache()
    ingest_date = ingest_date or date.today().isoformat()
    run_id = run_id or uuid.uuid4().hex[:12]

    enriched: list[EnrichedRecord] = []
    dead: list[DeadLetter] = []
    started = time.monotonic()
    cache_hits = 0
    total_input = 0
    total_output = 0

    for record in records:
        rid = str(record.get("safetyreportid", ""))
        key = cache_key(record, assessor.model_id, PROMPT_VERSION)

        cached = cache.get(key)
        result: dict | None = cached
        if cached is not None:
            cache_hits += 1

        attempts = 0
        last_error = ""
        assessment: Assessment | None = None

        while assessment is None and attempts < MAX_VALIDATION_ATTEMPTS:
            attempts += 1
            try:
                if result is None:
                    result = assessor.assess(record)
                    cache.put(key, result)
                assessment = Assessment.model_validate(result["tool_input"])
            except ValidationError as exc:
                # The tool schema constrains shape, not semantics. A response can
                # satisfy the schema and still fail the model - so retry once
                # with a fresh call rather than trusting the first reply.
                last_error = f"ValidationError: {exc.errors()[:2]}"
                LOG.warning("Validation failed for %s (attempt %d)", rid, attempts)
                result = None
            except BedrockError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                LOG.error("Bedrock failure for %s: %s", rid, exc)
                break

        if assessment is None:
            dead.append(
                DeadLetter(
                    safetyreportid=rid,
                    reason=last_error or "unknown",
                    raw_response=json.dumps(result.get("tool_input"))[:1000] if result else "",
                    attempts=attempts,
                )
            )
            continue

        total_input += result["input_tokens"]
        total_output += result["output_tokens"]

        enriched.append(
            EnrichedRecord(
                safetyreportid=rid,
                assessment=assessment,
                model_id=result["model_id"],
                prompt_version=PROMPT_VERSION,
                input_tokens=result["input_tokens"],
                output_tokens=result["output_tokens"],
                latency_ms=result["latency_ms"],
                cached=cached is not None,
                label_seriousness=record.get("label_seriousness"),
                label_primary_suspect=record.get("label_primary_suspect"),
                input_substances=[
                    (d.get("active_substance") or "").strip().upper()
                    for d in (record.get("drugs") or [])
                    if d.get("active_substance")
                ],
            )
        )

    if enriched:
        payload = "\n".join(e.model_dump_json() for e in enriched).encode("utf-8")
        sink.write(gold_key(ingest_date, run_id), gzip_bytes(payload))

    if dead:
        payload = "\n".join(d.model_dump_json() for d in dead).encode("utf-8")
        sink.write(dlq_key(ingest_date, run_id), gzip_bytes(payload))

    attempted = len(records)
    metrics = {
        "run_id": run_id,
        "ingest_date": ingest_date,
        "model_id": assessor.model_id,
        "prompt_version": PROMPT_VERSION,
        "attempted": attempted,
        "enriched": len(enriched),
        "dead_lettered": len(dead),
        # Rate over everything attempted, including the failures. Computing it
        # over successes only would report 100% no matter how much was lost.
        "success_rate": round(len(enriched) / attempted, 4) if attempted else 0.0,
        "cache_hits": cache_hits,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "estimated_cost_usd": round(estimate_cost(total_input, total_output), 6),
        "cost_per_1k_records_usd": (
            round(estimate_cost(total_input, total_output) / attempted * 1000, 4)
            if attempted
            else 0.0
        ),
        "duration_seconds": round(time.monotonic() - started, 2),
    }
    sink.write(metrics_key(ingest_date, run_id), json.dumps(metrics, indent=2).encode("utf-8"))
    LOG.info("Enrichment complete: %s", metrics)
    return metrics
