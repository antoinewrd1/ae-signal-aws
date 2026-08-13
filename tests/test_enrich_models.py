"""Schema validation. No AWS, no Spark."""

import pytest
from pydantic import ValidationError

from src.enrich.models import Assessment, DeadLetter, EnrichedRecord


def _valid(**kw):
    base = {"seriousness": "serious", "confidence": "high", "rationale": "Fatal outcome reported."}
    base.update(kw)
    return base


def test_valid_assessment_parses():
    a = Assessment.model_validate(_valid())
    assert a.seriousness.value == "serious"


def test_invalid_enum_rejected():
    """A tool schema constrains shape, not semantics - revalidate regardless."""
    with pytest.raises(ValidationError):
        Assessment.model_validate(_valid(seriousness="very_serious"))


def test_missing_required_field_rejected():
    with pytest.raises(ValidationError):
        Assessment.model_validate({"seriousness": "serious"})


def test_substance_normalized_to_match_silver():
    """Predictions must be comparable to labels without a fuzzy match."""
    a = Assessment.model_validate(_valid(primary_suspect="  dupilumab "))
    assert a.primary_suspect == "DUPILUMAB"


def test_blank_substance_becomes_none_not_empty_string():
    assert Assessment.model_validate(_valid(primary_suspect="   ")).primary_suspect is None


def test_reactions_normalized_and_blanks_dropped():
    a = Assessment.model_validate(_valid(key_reactions=[" nausea ", "", "RASH"]))
    assert a.key_reactions == ["NAUSEA", "RASH"]


def test_too_many_reactions_rejected():
    with pytest.raises(ValidationError):
        Assessment.model_validate(_valid(key_reactions=[f"R{i}" for i in range(6)]))


def test_overlong_rationale_rejected():
    with pytest.raises(ValidationError):
        Assessment.model_validate(_valid(rationale="x" * 401))


def test_enriched_record_carries_provenance():
    """Model id and prompt version per record - both change independently."""
    r = EnrichedRecord(
        safetyreportid="A",
        assessment=Assessment.model_validate(_valid()),
        model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        prompt_version="v1",
    )
    assert r.model_id.startswith("us.anthropic")
    assert r.prompt_version == "v1"


def test_dead_letter_records_reason_and_attempts():
    d = DeadLetter(safetyreportid="A", reason="ValidationError", attempts=2)
    assert d.attempts == 2
