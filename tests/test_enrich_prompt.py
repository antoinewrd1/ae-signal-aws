"""The label must never reach the model."""

from src.enrich.prompt import TOOL_SCHEMA, build_user_message


def _record(**kw):
    base = {
        "safetyreportid": "A1",
        "patient_sex": "female",
        "patient_onset_age": 45.0,
        "occur_country": "US",
        "drugs": [
            {
                "active_substance": "DUPILUMAB",
                "drug_role": "suspect",
                "indication": "Dermatitis atopic",
            }
        ],
        "reactions": [{"reaction_term": "NAUSEA", "reaction_outcome": "recovered"}],
        "label_seriousness": "serious",
    }
    base.update(kw)
    return base


def test_label_is_not_leaked_into_the_prompt():
    """If the label appears in the prompt, every eval score is meaningless."""
    msg = build_user_message(_record())
    assert "label_seriousness" not in msg
    assert "serious" not in msg.lower().replace("seriousness assessment", "")


def test_prompt_includes_reactions_and_drugs():
    msg = build_user_message(_record())
    assert "NAUSEA" in msg
    assert "DUPILUMAB" in msg
    assert "suspect" in msg


def test_missing_reactions_renders_explicitly_not_blank():
    """A silently empty section reads to the model as an omission, not an absence."""
    msg = build_user_message(_record(reactions=[]))
    assert "none reported" in msg


def test_missing_drugs_renders_explicitly():
    assert "none reported" in build_user_message(_record(drugs=[]))


def test_record_with_no_demographics_still_renders():
    msg = build_user_message(_record(patient_sex=None, patient_onset_age=None, occur_country=None))
    assert "Reported reactions:" in msg


def test_tool_schema_enum_matches_model_enum():
    from src.enrich.models import Seriousness

    schema_values = set(TOOL_SCHEMA["inputSchema"]["json"]["properties"]["seriousness"]["enum"])
    assert schema_values == {s.value for s in Seriousness}
