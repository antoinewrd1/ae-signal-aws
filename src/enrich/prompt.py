"""Prompt construction and the Bedrock tool schema.

PROMPT_VERSION is bumped on every change to the prompt or tool schema. Eval
results are meaningless without it - a score improvement that turns out to be
a prompt edit rather than a model change is a wasted week.
"""

from __future__ import annotations

PROMPT_VERSION = "v1"

SYSTEM = (
    "You are assisting with pharmacovigilance triage of public FDA adverse "
    "event reports. Given the reported reaction terms and the drugs involved, "
    "judge whether the report describes a serious adverse event.\n\n"
    "Serious means the event involved death, a life-threatening condition, "
    "hospitalisation or its prolongation, persistent or significant disability, "
    "a congenital anomaly, or required intervention to prevent permanent "
    "impairment. Everything else is non-serious.\n\n"
    "Judge only from the information given. Do not speculate about facts not "
    "present. If the reported drugs do not clearly point to one substance, "
    "return null for primary_suspect rather than guessing.\n\n"
    "This is a triage aid for review, not a clinical determination."
)

# Mirrors the Assessment model. Bedrock's tool-use path constrains the response
# shape at the API level, which is far more reliable than asking for JSON in
# prose and hoping. Validation still happens after - the schema constrains
# structure, not whether the content makes sense.
TOOL_SCHEMA = {
    "name": "record_assessment",
    "description": "Record the seriousness assessment for one adverse event report.",
    "inputSchema": {
        "json": {
            "type": "object",
            "properties": {
                "seriousness": {
                    "type": "string",
                    "enum": ["serious", "non_serious"],
                    "description": "Predicted seriousness of the report.",
                },
                "primary_suspect": {
                    "type": ["string", "null"],
                    "description": "Active substance most likely responsible, or null.",
                },
                "key_reactions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 5,
                    "description": "Reaction terms driving the judgement.",
                },
                "confidence": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                },
                "rationale": {
                    "type": "string",
                    "description": "One or two sentences. Under 400 characters.",
                },
            },
            "required": ["seriousness", "confidence", "rationale"],
        }
    },
}


def build_user_message(record: dict) -> str:
    """Render a report for the model.

    Seriousness flags are deliberately excluded. Including them would leak the
    label and make every eval score meaningless.
    """
    reactions = record.get("reactions") or []
    drugs = record.get("drugs") or []

    lines = ["Adverse event report", ""]

    age = record.get("patient_onset_age")
    sex = record.get("patient_sex")
    if age or sex:
        parts = []
        if age:
            parts.append(f"age {age:g}")
        if sex:
            parts.append(str(sex))
        lines.append(f"Patient: {', '.join(parts)}")

    country = record.get("occur_country")
    if country:
        lines.append(f"Country: {country}")

    lines.append("")
    lines.append("Reported reactions:")
    if reactions:
        for r in reactions:
            outcome = r.get("reaction_outcome")
            term = r.get("reaction_term")
            lines.append(f"  - {term}" + (f" (outcome: {outcome})" if outcome else ""))
    else:
        lines.append("  - none reported")

    lines.append("")
    lines.append("Drugs reported:")
    if drugs:
        for d in drugs:
            role = d.get("drug_role") or "role unknown"
            substance = d.get("active_substance") or d.get("medicinal_product") or "unnamed"
            indication = d.get("indication")
            line = f"  - {substance} ({role})"
            if indication:
                line += f", indication: {indication}"
            lines.append(line)
    else:
        lines.append("  - none reported")

    lines.append("")
    lines.append("Assess this report using the record_assessment tool.")
    return "\n".join(lines)
