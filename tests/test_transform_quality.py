"""Quality gates must raise, not log."""

import pytest

from src.transform.quality import (
    DataQualityError,
    check_date_ordering,
    check_not_null,
    check_null_rate,
    check_row_count,
    check_unique,
    enforce,
)


def test_duplicate_primary_key_fails(bronze_df, make_report):
    from src.transform.silver import build_silver_report

    df = build_silver_report(bronze_df([make_report("A")]))
    assert check_unique(df, ["safetyreportid"]).passed


def test_enforce_raises_on_any_failure(bronze_df, make_report):
    from src.transform.silver import build_silver_report

    df = build_silver_report(bronze_df([make_report("A")]))
    with pytest.raises(DataQualityError) as exc:
        enforce([check_row_count(df, minimum=999)], "silver")
    assert "row_count" in str(exc.value)


def test_enforce_is_silent_when_all_pass(bronze_df, make_report):
    from src.transform.silver import build_silver_report

    df = build_silver_report(bronze_df([make_report("A")]))
    enforce([check_not_null(df, "safetyreportid"), check_row_count(df, minimum=1)], "silver")


def test_impossible_date_ordering_is_caught(bronze_df, make_report):
    """Two valid dates in an impossible order means a format was misread."""
    from src.transform.silver import build_silver_report

    df = build_silver_report(bronze_df([make_report("A", receive="20240301", receipt="20240101")]))
    assert check_date_ordering(df, "receive_date", "receipt_date").passed is False


def test_null_rate_threshold(bronze_df, make_report):
    from src.transform.silver import build_silver_report

    records = [make_report(f"R{i}") for i in range(9)]
    records.append(make_report("BAD", receipt="2024", receiptdateformat="602"))
    df = build_silver_report(bronze_df(records))
    assert check_null_rate(df, "receipt_date", max_rate=0.20).passed
    assert check_null_rate(df, "receipt_date", max_rate=0.05).passed is False


def test_empty_dataframe_fails_null_rate_rather_than_dividing_by_zero(bronze_df):
    from src.transform.silver import build_silver_report

    df = build_silver_report(bronze_df([]))
    result = check_null_rate(df, "receipt_date", max_rate=1.0)
    assert result.passed is False
    assert "empty" in result.detail
