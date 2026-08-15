"""Scoring metrics.

Implemented directly rather than pulled from scikit-learn. The arithmetic is
trivial, the dependency is not, and writing it out makes the definitions
visible - which matters when the whole point of this module is that the
numbers can be trusted.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class ConfusionMatrix:
    """Binary confusion matrix for a chosen positive class."""

    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0

    @property
    def n(self) -> int:
        return self.tp + self.fp + self.tn + self.fn

    @property
    def accuracy(self) -> float:
        return (self.tp + self.tn) / self.n if self.n else 0.0

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 0.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom else 0.0

    @property
    def specificity(self) -> float:
        denom = self.tn + self.fp
        return self.tn / denom if denom else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "tp": self.tp,
            "fp": self.fp,
            "tn": self.tn,
            "fn": self.fn,
            "accuracy": round(self.accuracy, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "specificity": round(self.specificity, 4),
            "f1": round(self.f1, 4),
        }


def confusion(y_true: list[str], y_pred: list[str], positive: str) -> ConfusionMatrix:
    if len(y_true) != len(y_pred):
        raise ValueError("y_true and y_pred must be the same length")
    m = ConfusionMatrix()
    for actual, predicted in zip(y_true, y_pred, strict=True):
        if predicted == positive and actual == positive:
            m.tp += 1
        elif predicted == positive and actual != positive:
            m.fp += 1
        elif predicted != positive and actual != positive:
            m.tn += 1
        else:
            m.fn += 1
    return m


def majority_baseline(y_true: list[str]) -> tuple[str, float]:
    """Accuracy of always predicting the most common class.

    This is the number that decides whether the model learned anything. If
    85% of reports are serious, a model scoring 85% has matched a constant
    and is worth nothing - yet 85% reads as a good result to anyone who
    doesn't see the base rate next to it. It belongs beside every accuracy
    figure this project publishes.
    """
    if not y_true:
        return ("", 0.0)
    counts = Counter(y_true)
    label, n = counts.most_common(1)[0]
    return (label, n / len(y_true))


def cohens_kappa(y_true: list[str], y_pred: list[str]) -> float:
    """Agreement corrected for the agreement expected by chance.

    Standard for inter-rater reliability, and that is exactly the situation:
    the model and the ground truth are two raters. Zero means chance-level.
    Negative means worse than chance.
    """
    if not y_true:
        return 0.0
    n = len(y_true)
    observed = sum(1 for a, b in zip(y_true, y_pred, strict=True) if a == b) / n

    true_counts = Counter(y_true)
    pred_counts = Counter(y_pred)
    expected = sum(
        (true_counts[label] / n) * (pred_counts[label] / n) for label in set(y_true) | set(y_pred)
    )

    if expected == 1.0:
        # Both raters used a single identical class; kappa is undefined.
        return 0.0
    return (observed - expected) / (1 - expected)


@dataclass
class CalibrationBucket:
    confidence: str
    n: int = 0
    correct: int = 0

    @property
    def accuracy(self) -> float:
        return self.correct / self.n if self.n else 0.0


def calibration(records: list[dict]) -> list[CalibrationBucket]:
    """Accuracy grouped by the model's stated confidence.

    A model whose 'high' confidence is no more accurate than its 'low' is
    uncalibrated, and its confidence field is decoration. Worth knowing before
    anyone downstream filters on it.
    """
    buckets: dict[str, CalibrationBucket] = {}
    for r in records:
        conf = r.get("confidence") or "unknown"
        b = buckets.setdefault(conf, CalibrationBucket(confidence=conf))
        b.n += 1
        if r.get("predicted") == r.get("actual"):
            b.correct += 1

    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(buckets.values(), key=lambda b: order.get(b.confidence, 99))


@dataclass
class HallucinationResult:
    checked: int = 0
    invented: int = 0
    abstained: int = 0
    examples: list[dict] = field(default_factory=list)

    @property
    def rate(self) -> float:
        return self.invented / self.checked if self.checked else 0.0


def hallucination(records: list[dict], max_examples: int = 5) -> HallucinationResult:
    """Count predicted substances absent from the report's own drug list.

    A named suspect that never appeared in the input is fabricated, not chosen.
    Abstentions (null) are tracked separately - declining to answer is correct
    behaviour when the input is ambiguous, and scoring it as a failure would
    push toward confident guessing.
    """
    result = HallucinationResult()
    for r in records:
        predicted = r.get("predicted_suspect")
        if predicted is None:
            result.abstained += 1
            continue
        result.checked += 1
        available = {s.upper() for s in (r.get("input_substances") or [])}
        if predicted.upper() not in available:
            result.invented += 1
            if len(result.examples) < max_examples:
                result.examples.append(
                    {
                        "safetyreportid": r.get("safetyreportid"),
                        "predicted": predicted,
                        "available": sorted(available)[:6],
                    }
                )
    return result


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile. No numpy dependency for one number."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(p / 100 * len(ordered) + 0.5)) - 1))
    return ordered[index]
