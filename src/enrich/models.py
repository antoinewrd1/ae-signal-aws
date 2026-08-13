"""Structured output schema.

The enrichment task is deliberately one with checkable answers. Asking the
model to summarise a report would produce output nobody can grade; asking it
to predict seriousness from the reaction terms alone produces a prediction
that can be scored against the report's own seriousness flags - which are
withheld from the prompt.

That gives free ground truth for every record, which is what makes the eval
harness on day 5 possible at all.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class Seriousness(StrEnum):
    SERIOUS = "serious"
    NON_SERIOUS = "non_serious"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Assessment(BaseModel):
    """What the model must return. Enforced by the Bedrock tool schema and
    re-validated here - a tool schema constrains the shape, not the semantics.
    """

    seriousness: Seriousness = Field(
        description="Predicted seriousness based only on the reaction terms and outcomes."
    )
    primary_suspect: str | None = Field(
        default=None,
        description="Active substance most likely responsible, or null if undeterminable.",
    )
    key_reactions: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="Reaction terms that drove the seriousness judgement.",
    )
    confidence: Confidence
    rationale: str = Field(max_length=400)

    @field_validator("primary_suspect")
    @classmethod
    def normalize_substance(cls, v: str | None) -> str | None:
        # Normalized the same way silver normalizes active_substance, so the
        # prediction can be compared to the label without a fuzzy match.
        if v is None:
            return None
        cleaned = v.strip().upper()
        return cleaned or None

    @field_validator("key_reactions")
    @classmethod
    def normalize_reactions(cls, v: list[str]) -> list[str]:
        return [r.strip().upper() for r in v if r and r.strip()]


class EnrichedRecord(BaseModel):
    """One enrichment result, carrying provenance alongside the prediction.

    model_id and prompt_version are stored per record rather than per run.
    Model IDs get retired and prompts get edited; without both recorded here,
    yesterday's eval numbers cannot be attributed to anything.
    """

    safetyreportid: str
    assessment: Assessment
    model_id: str
    prompt_version: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    cached: bool = False

    # Ground truth, carried through for scoring. Never shown to the model.
    label_seriousness: str | None = None
    label_primary_suspect: str | None = None


class DeadLetter(BaseModel):
    """A record the model could not produce valid output for.

    Routed here rather than dropped. A silent drop makes the denominator wrong
    and every downstream rate look better than it is.
    """

    safetyreportid: str
    reason: str
    raw_response: str = ""
    attempts: int = 0
