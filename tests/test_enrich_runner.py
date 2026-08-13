"""Runner behaviour with a stubbed Bedrock client. No AWS calls."""

import gzip
import json

from src.enrich.cache import ResponseCache, cache_key
from src.enrich.runner import enrich_records


class RecordingSink:
    def __init__(self):
        self.objects = {}

    def write(self, key, payload, content_type="application/json"):
        self.objects[key] = payload
        return f"mem://{key}"


class StubAssessor:
    """Returns canned tool inputs in sequence and counts calls."""

    model_id = "stub-model"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def assess(self, record):
        self.calls += 1
        payload = self.responses.pop(0) if self.responses else self.responses
        return {
            "tool_input": payload,
            "input_tokens": 100,
            "output_tokens": 20,
            "latency_ms": 250,
            "model_id": self.model_id,
        }


def _good(**kw):
    base = {"seriousness": "serious", "confidence": "high", "rationale": "Fatal outcome."}
    base.update(kw)
    return base


def _records(n):
    return [
        {"safetyreportid": str(i), "reactions": [], "drugs": [], "label_seriousness": "serious"}
        for i in range(n)
    ]


def _read(sink, fragment):
    key = next(k for k in sink.objects if fragment in k)
    blob = sink.objects[key]
    text = gzip.decompress(blob).decode() if key.endswith(".gz") else blob.decode()
    return key, text


def test_valid_responses_land_in_gold():
    sink = RecordingSink()
    m = enrich_records(
        _records(2),
        sink,
        StubAssessor([_good(), _good()]),
        ResponseCache(enabled=False),
        "2026-06-01",
        "r1",
    )
    assert m["enriched"] == 2
    assert m["dead_lettered"] == 0
    _, text = _read(sink, "gold/assessments/")
    assert len(text.splitlines()) == 2


def test_invalid_response_retries_then_dead_letters():
    """Two bad replies for one record: two calls, then the DLQ - never a drop."""
    bad = {"seriousness": "extremely_serious", "confidence": "high", "rationale": "x"}
    sink = RecordingSink()
    assessor = StubAssessor([bad, bad])
    m = enrich_records(
        _records(1), sink, assessor, ResponseCache(enabled=False), "2026-06-01", "r2"
    )

    assert assessor.calls == 2
    assert m["enriched"] == 0
    assert m["dead_lettered"] == 1
    _, text = _read(sink, "_dlq/")
    assert "ValidationError" in json.loads(text)["reason"]


def test_second_attempt_can_succeed():
    bad = {"seriousness": "nope", "confidence": "high", "rationale": "x"}
    sink = RecordingSink()
    m = enrich_records(
        _records(1),
        sink,
        StubAssessor([bad, _good()]),
        ResponseCache(enabled=False),
        "2026-06-01",
        "r3",
    )
    assert m["enriched"] == 1
    assert m["dead_lettered"] == 0


def test_success_rate_denominator_includes_failures():
    """Computed over successes only, this would read 1.0 no matter what was lost."""
    bad = {"seriousness": "nope", "confidence": "high", "rationale": "x"}
    sink = RecordingSink()
    m = enrich_records(
        _records(2),
        sink,
        StubAssessor([_good(), bad, bad]),
        ResponseCache(enabled=False),
        "2026-06-01",
        "r4",
    )
    assert m["attempted"] == 2
    assert m["enriched"] == 1
    assert m["dead_lettered"] == 1
    assert m["success_rate"] == 0.5


def test_labels_are_carried_through_for_scoring():
    sink = RecordingSink()
    enrich_records(
        _records(1), sink, StubAssessor([_good()]), ResponseCache(enabled=False), "2026-06-01", "r5"
    )
    _, text = _read(sink, "gold/assessments/")
    assert json.loads(text.splitlines()[0])["label_seriousness"] == "serious"


def test_metrics_report_cost_and_provenance():
    sink = RecordingSink()
    enrich_records(
        _records(2),
        sink,
        StubAssessor([_good(), _good()]),
        ResponseCache(enabled=False),
        "2026-06-01",
        "r6",
    )
    _, text = _read(sink, "_metrics/")
    m = json.loads(text)
    assert m["input_tokens"] == 200
    assert m["estimated_cost_usd"] > 0
    assert m["model_id"] == "stub-model"
    assert m["prompt_version"]


def test_cache_prevents_a_second_billed_call(tmp_path):
    """The cache exists to protect a development loop from re-billing."""
    cache = ResponseCache(root=tmp_path / "c", enabled=True)
    records = _records(1)

    a = StubAssessor([_good()])
    enrich_records(records, RecordingSink(), a, cache, "2026-06-01", "r7")
    assert a.calls == 1

    b = StubAssessor([_good()])
    m = enrich_records(records, RecordingSink(), b, cache, "2026-06-01", "r8")
    assert b.calls == 0
    assert m["cache_hits"] == 1
    assert m["enriched"] == 1


def test_cache_key_changes_with_prompt_version():
    """A prompt edit must miss the cache, or the eval scores yesterday's prompt."""
    r = {"safetyreportid": "A"}
    assert cache_key(r, "m", "v1") != cache_key(r, "m", "v2")


def test_cache_key_changes_with_model():
    r = {"safetyreportid": "A"}
    assert cache_key(r, "model-a", "v1") != cache_key(r, "model-b", "v1")


def test_corrupt_cache_entry_is_a_miss_not_a_crash(tmp_path):
    cache = ResponseCache(root=tmp_path / "c", enabled=True)
    key = cache_key({"safetyreportid": "A"}, "m", "v1")
    (cache.root / f"{key}.json").write_text("{not json")
    assert cache.get(key) is None
