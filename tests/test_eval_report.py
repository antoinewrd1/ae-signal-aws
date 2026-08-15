"""Report assembly."""

import json

from src.eval.report import build_report, to_markdown


def _record(
    actual, predicted, confidence="high", suspect="ASPIRIN", substances=("ASPIRIN",), rid="A"
):
    return {
        "safetyreportid": rid,
        "assessment": {
            "seriousness": predicted,
            "primary_suspect": suspect,
            "key_reactions": [],
            "confidence": confidence,
            "rationale": "x",
        },
        "model_id": "test-model",
        "prompt_version": "v1",
        "input_tokens": 100,
        "output_tokens": 20,
        "latency_ms": 200,
        "cached": False,
        "label_seriousness": actual,
        "input_substances": list(substances),
    }


def test_report_carries_model_provenance():
    r = build_report([_record("serious", "serious")])
    assert r.model_id == "test-model"
    assert r.prompt_version == "v1"


def test_unlabeled_records_excluded_from_scoring_but_counted():
    records = [_record("serious", "serious")]
    unlabeled = _record("serious", "serious")
    unlabeled["label_seriousness"] = None
    r = build_report(records + [unlabeled])
    assert r.n_scored == 1
    assert r.n_unlabeled == 1


def test_baseline_reported_alongside_accuracy():
    """A raw accuracy figure without its baseline is not interpretable."""
    records = [_record("serious", "serious", rid=str(i)) for i in range(17)]
    records += [_record("non_serious", "serious", rid=f"n{i}") for i in range(3)]
    r = build_report(records)
    assert r.metrics["accuracy"] == 0.85
    assert r.baseline["majority_accuracy"] == 0.85
    assert r.baseline["lift_over_baseline"] == 0.0
    assert r.baseline["beats_baseline"] is False
    assert r.metrics["cohens_kappa"] == 0.0


def test_model_that_genuinely_beats_baseline():
    records = [_record("serious", "serious", rid=str(i)) for i in range(15)]
    records += [_record("non_serious", "non_serious", rid=f"n{i}") for i in range(5)]
    r = build_report(records)
    assert r.baseline["beats_baseline"] is True
    assert r.metrics["cohens_kappa"] == 1.0


def test_hallucination_surfaced_in_report():
    r = build_report([_record("serious", "serious", suspect="WARFARIN", substances=("ASPIRIN",))])
    assert r.hallucination["invented"] == 1
    assert r.hallucination["rate"] == 1.0


def test_cached_records_excluded_from_latency():
    """Cache hits return in microseconds and would flatter the latency figures."""
    live = _record("serious", "serious", rid="A")
    cached = _record("serious", "serious", rid="B")
    cached["cached"] = True
    cached["latency_ms"] = 0
    r = build_report([live, cached])
    assert r.performance["p50_latency_ms"] == 200


def test_markdown_leads_with_the_baseline():
    records = [_record("serious", "serious", rid=str(i)) for i in range(9)]
    records += [_record("non_serious", "serious", rid="n1")]
    md = to_markdown(build_report(records))
    assert "Majority-class baseline" in md
    assert "Lift over baseline" in md
    assert "Cohen's kappa" in md
    assert "has learned nothing" in md


def test_report_serializes_to_json():
    r = build_report([_record("serious", "serious")])
    parsed = json.loads(r.to_json())
    assert parsed["metrics"]["accuracy"] == 1.0
    assert "baseline" in parsed
