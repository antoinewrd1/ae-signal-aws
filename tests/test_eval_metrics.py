"""Metric correctness. Pure functions, no Spark, no AWS."""

import pytest

from src.eval.metrics import (
    calibration,
    cohens_kappa,
    confusion,
    hallucination,
    majority_baseline,
    percentile,
)


def test_confusion_counts_each_cell():
    y_true = ["serious", "serious", "non_serious", "non_serious"]
    y_pred = ["serious", "non_serious", "serious", "non_serious"]
    m = confusion(y_true, y_pred, "serious")
    assert (m.tp, m.fn, m.fp, m.tn) == (1, 1, 1, 1)
    assert m.accuracy == 0.5
    assert m.precision == 0.5
    assert m.recall == 0.5


def test_mismatched_lengths_rejected():
    with pytest.raises(ValueError):
        confusion(["a"], ["a", "b"], "a")


def test_perfect_prediction():
    y = ["serious"] * 3 + ["non_serious"] * 2
    m = confusion(y, y, "serious")
    assert m.accuracy == 1.0
    assert m.f1 == 1.0


def test_precision_is_zero_not_nan_when_nothing_predicted_positive():
    m = confusion(["serious", "serious"], ["non_serious", "non_serious"], "serious")
    assert m.precision == 0.0
    assert m.f1 == 0.0


def test_majority_baseline_reflects_class_imbalance():
    """The number that decides whether an accuracy figure means anything."""
    y = ["serious"] * 17 + ["non_serious"] * 3
    label, acc = majority_baseline(y)
    assert label == "serious"
    assert acc == 0.85


def test_constant_predictor_matches_baseline_exactly():
    """85% accuracy sounds good until you see the model predicted one class."""
    y_true = ["serious"] * 17 + ["non_serious"] * 3
    y_pred = ["serious"] * 20
    m = confusion(y_true, y_pred, "serious")
    _, baseline = majority_baseline(y_true)
    assert m.accuracy == baseline
    # And kappa correctly reports that nothing was learned.
    assert cohens_kappa(y_true, y_pred) == 0.0


def test_kappa_is_one_for_perfect_agreement():
    y = ["serious", "non_serious", "serious", "non_serious"]
    assert cohens_kappa(y, y) == 1.0


def test_kappa_is_negative_when_worse_than_chance():
    y_true = ["serious", "serious", "non_serious", "non_serious"]
    y_pred = ["non_serious", "non_serious", "serious", "serious"]
    assert cohens_kappa(y_true, y_pred) < 0


def test_calibration_buckets_ordered_high_to_low():
    records = [
        {"confidence": "low", "predicted": "a", "actual": "b"},
        {"confidence": "high", "predicted": "a", "actual": "a"},
        {"confidence": "medium", "predicted": "a", "actual": "a"},
    ]
    assert [b.confidence for b in calibration(records)] == ["high", "medium", "low"]


def test_calibration_detects_an_uncalibrated_model():
    """If high confidence is no more accurate than low, the field is decoration."""
    records = [{"confidence": "high", "predicted": "a", "actual": "b"}] * 5 + [
        {"confidence": "low", "predicted": "a", "actual": "a"}
    ] * 5
    buckets = {b.confidence: b.accuracy for b in calibration(records)}
    assert buckets["high"] == 0.0
    assert buckets["low"] == 1.0


def test_hallucination_flags_a_substance_not_in_the_input():
    records = [
        {"safetyreportid": "A", "predicted_suspect": "ASPIRIN", "input_substances": ["IBUPROFEN"]},
        {
            "safetyreportid": "B",
            "predicted_suspect": "IBUPROFEN",
            "input_substances": ["IBUPROFEN"],
        },
    ]
    h = hallucination(records)
    assert h.checked == 2
    assert h.invented == 1
    assert h.rate == 0.5
    assert h.examples[0]["safetyreportid"] == "A"


def test_abstention_is_not_counted_as_hallucination():
    """Declining on ambiguous input is correct; penalising it rewards guessing."""
    records = [
        {"safetyreportid": "A", "predicted_suspect": None, "input_substances": ["IBUPROFEN"]}
    ]
    h = hallucination(records)
    assert h.abstained == 1
    assert h.checked == 0
    assert h.rate == 0.0


def test_hallucination_match_is_case_insensitive():
    records = [
        {"safetyreportid": "A", "predicted_suspect": "aspirin", "input_substances": ["ASPIRIN"]}
    ]
    assert hallucination(records).invented == 0


def test_percentile_and_empty_input():
    assert percentile([1, 2, 3, 4, 5], 50) == 3
    assert percentile([], 95) == 0.0
