from datetime import date

import pytest

from src.extract.windows import fda_date, partition_by_days, received_date_query


def test_fda_date_has_no_separators():
    assert fda_date(date(2024, 3, 7)) == "20240307"


def test_query_bounds_are_inclusive():
    q = received_date_query(date(2024, 1, 1), date(2024, 1, 7))
    assert q == "receivedate:[20240101+TO+20240107]"


def test_partition_covers_range_without_gaps_or_overlap():
    windows = list(partition_by_days(date(2024, 1, 1), date(2024, 1, 20), days=7))
    assert windows[0] == (date(2024, 1, 1), date(2024, 1, 7))
    assert windows[-1][1] == date(2024, 1, 20)
    for (_, prev_end), (next_start, _) in zip(windows, windows[1:], strict=False):
        assert (next_start - prev_end).days == 1


def test_single_day_range_yields_one_window():
    assert list(partition_by_days(date(2024, 1, 1), date(2024, 1, 1))) == [
        (date(2024, 1, 1), date(2024, 1, 1))
    ]


def test_reversed_range_rejected():
    with pytest.raises(ValueError):
        list(partition_by_days(date(2024, 2, 1), date(2024, 1, 1)))
