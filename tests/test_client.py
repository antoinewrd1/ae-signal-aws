"""Client tests. No network calls - _get is patched at the boundary."""

from unittest.mock import patch

import pytest

from src.extract.client import MAX_SKIP, OpenFDAClient, PaginationExhaustedError


def _body(records, total, skip=0):
    return {"meta": {"results": {"total": total, "skip": skip}}, "results": records}


def test_pagination_stops_at_reported_total():
    pages = [
        _body([{"i": n} for n in range(100)], total=150),
        _body([{"i": n} for n in range(50)], total=150, skip=100),
    ]
    client = OpenFDAClient()
    with patch.object(client, "_get", side_effect=pages) as mock:
        records = list(client.iter_records("q"))
    assert len(records) == 150
    assert mock.call_count == 2


def test_pagination_stops_on_empty_page():
    client = OpenFDAClient()
    pages = [_body([{"i": 1}], total=999), _body([], total=999, skip=1)]
    with patch.object(client, "_get", side_effect=pages):
        assert len(list(client.iter_records("q"))) == 1


def test_max_records_caps_output():
    client = OpenFDAClient()
    with patch.object(client, "_get", return_value=_body([{"i": n} for n in range(10)], 5000)):
        assert len(list(client.iter_records("q", max_records=10))) == 10


def test_skip_beyond_api_cap_raises():
    client = OpenFDAClient()
    with pytest.raises(PaginationExhaustedError):
        client.fetch_page("q", skip=MAX_SKIP + 1)


def test_limit_above_hundred_rejected():
    with pytest.raises(ValueError):
        OpenFDAClient().fetch_page("q", limit=500)


def test_search_param_is_not_percent_encoded():
    """openFDA's Lucene syntax breaks if brackets and + are encoded."""
    url = OpenFDAClient()._build_url({"search": "receivedate:[20240101+TO+20240107]", "limit": 100})
    assert "receivedate:[20240101+TO+20240107]" in url


def test_api_key_appended_when_present():
    assert "api_key=secret" in OpenFDAClient(api_key="secret")._build_url({"limit": 1})
    assert "api_key" not in OpenFDAClient()._build_url({"limit": 1})
