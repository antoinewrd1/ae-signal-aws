"""Silver transform behaviour. Runs against a local SparkSession."""

import datetime as dt


def test_report_is_one_row_per_report(bronze_df, make_report, make_drug, make_reaction):
    from src.transform.silver import build_silver_report

    df = bronze_df(
        [
            make_report(
                "A",
                drugs=[make_drug("X"), make_drug("Y")],
                reactions=[make_reaction("N"), make_reaction("M")],
            )
        ]
    )
    out = build_silver_report(df).collect()
    assert len(out) == 1
    # Counts are preserved on the header rather than exploded into it.
    assert out[0]["drug_count"] == 2
    assert out[0]["reaction_count"] == 2


def test_no_cartesian_explosion_across_drugs_and_reactions(
    bronze_df, make_report, make_drug, make_reaction
):
    """A 4-drug, 3-reaction report is 4 drug rows and 3 reaction rows - not 12."""
    from src.transform.silver import build_silver_drug, build_silver_reaction

    df = bronze_df(
        [
            make_report(
                "A",
                drugs=[make_drug(f"D{i}") for i in range(4)],
                reactions=[make_reaction(f"R{i}") for i in range(3)],
            )
        ]
    )
    assert build_silver_drug(df).count() == 4
    assert build_silver_reaction(df).count() == 3


def test_dedup_keeps_latest_receipt_date(bronze_df, make_report):
    from src.transform.silver import build_silver_report

    df = bronze_df(
        [
            make_report("A", receipt="20240110", version="1"),
            make_report("A", receipt="20240220", version="2"),
        ]
    )
    out = build_silver_report(df).collect()
    assert len(out) == 1
    assert out[0]["receipt_date"] == dt.date(2024, 2, 20)
    assert out[0]["safetyreportversion"] == "2"


def test_replayed_duplicate_collapses_to_one_row(bronze_df, make_report):
    """At-least-once streaming delivery means identical records genuinely arrive twice."""
    from src.transform.silver import build_silver_report

    record = make_report("A")
    assert build_silver_report(bronze_df([record, record])).count() == 1


def test_partial_month_date_resolves_to_start_of_period(bronze_df, make_report):
    from src.transform.silver import build_silver_report

    df = bronze_df([make_report("A", receipt="202403", receiptdateformat="610")])
    row = build_silver_report(df).collect()[0]
    assert row["receipt_date"] == dt.date(2024, 3, 1)
    # Precision is retained so downstream users know the day was invented.
    assert row["receipt_date_precision"] == "month"


def test_year_only_date_is_null_not_guessed(bronze_df, make_report):
    from src.transform.silver import build_silver_report

    df = bronze_df([make_report("A", receipt="2024", receiptdateformat="602")])
    row = build_silver_report(df).collect()[0]
    assert row["receipt_date"] is None
    assert row["receipt_date_precision"] == "unknown"


def test_coded_values_are_decoded(bronze_df, make_report, make_drug, make_reaction):
    from src.transform.silver import build_silver_drug, build_silver_reaction, build_silver_report

    df = bronze_df(
        [
            make_report(
                "A", drugs=[make_drug("X", role="2")], reactions=[make_reaction("N", outcome="5")]
            )
        ]
    )
    assert build_silver_report(df).collect()[0]["patient_sex"] == "female"
    assert build_silver_drug(df).collect()[0]["drug_role"] == "concomitant"
    assert build_silver_reaction(df).collect()[0]["reaction_outcome"] == "fatal"


def test_unknown_code_becomes_null_not_a_wrong_label(bronze_df, make_report, make_drug):
    from src.transform.silver import build_silver_drug

    df = bronze_df([make_report("A", drugs=[make_drug("X", role="99")])])
    assert build_silver_drug(df).collect()[0]["drug_role"] is None


def test_substance_names_are_normalized_for_joining(bronze_df, make_report, make_drug):
    from src.transform.silver import build_silver_drug

    df = bronze_df([make_report("A", drugs=[make_drug("  dupilumab  ")])])
    assert build_silver_drug(df).collect()[0]["active_substance"] == "DUPILUMAB"


def test_report_with_no_drugs_still_produces_a_header_row(bronze_df, make_report):
    from src.transform.silver import build_silver_drug, build_silver_report

    df = bronze_df([make_report("A", drugs=[])])
    assert build_silver_report(df).count() == 1
    assert build_silver_drug(df).count() == 0
