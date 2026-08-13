import gzip
import json
from datetime import date
from unittest.mock import patch

import pytest

from src.extract.runner import run_extraction
from src.extract.storage import LocalSink


class FakeSink(LocalSink):
    def __init__(self):
        self.objects = {}

    def write(self, key, payload, content_type="application/json"):
        self.objects[key] = payload
        return f"mem://{key}"


def _body(n, total):
    return {
        "meta": {"results": {"total": total, "skip": 0}},
        "results": [{"safetyreportid": str(i)} for i in range(n)],
    }


@patch("src.extract.client.OpenFDAClient._get")
def test_records_land_gzipped_and_manifest_written(mock_get):
    mock_get.side_effect = [_body(3, 3), _body(2, 2)]
    sink = FakeSink()

    manifest = run_extraction(
        sink=sink,
        start=date(2024, 1, 1),
        end=date(2024, 1, 14),
        ingest_date="2024-06-01",
        window_days=7,
        run_id="testrun",
    )

    assert manifest.status == "succeeded"
    assert manifest.record_count == 5
    assert manifest.window_count == 2

    data_keys = [k for k in sink.objects if k.endswith(".json.gz")]
    assert len(data_keys) == 1
    lines = gzip.decompress(sink.objects[data_keys[0]]).decode().splitlines()
    assert len(lines) == 5
    assert json.loads(lines[0])["safetyreportid"] == "0"


@patch("src.extract.client.OpenFDAClient._get")
def test_manifest_records_failure_and_reraises(mock_get):
    mock_get.side_effect = RuntimeError("boom")
    sink = FakeSink()

    with pytest.raises(RuntimeError):
        run_extraction(
            sink=sink,
            start=date(2024, 1, 1),
            end=date(2024, 1, 7),
            ingest_date="2024-06-01",
            run_id="failrun",
        )

    key = "bronze/_manifests/drug_event/ingest_date=2024-06-01/failrun.json"
    manifest_blob = json.loads(sink.objects[key])
    assert manifest_blob["status"] == "failed"
    assert "boom" in manifest_blob["error"]


@patch("src.extract.client.OpenFDAClient._get")
def test_checksum_is_stable_across_identical_runs(mock_get):
    def fresh():
        return [_body(4, 4)]

    mock_get.side_effect = fresh()
    a = run_extraction(
        sink=FakeSink(),
        start=date(2024, 1, 1),
        end=date(2024, 1, 7),
        ingest_date="2024-06-01",
        run_id="a",
    )
    mock_get.side_effect = fresh()
    b = run_extraction(
        sink=FakeSink(),
        start=date(2024, 1, 1),
        end=date(2024, 1, 7),
        ingest_date="2024-06-01",
        run_id="b",
    )
    assert a.content_sha256 == b.content_sha256


class _FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


@patch("src.extract.client.urllib.request.urlopen")
def test_manifest_counts_api_requests(mock_urlopen):
    """request_count must reflect real HTTP calls, not stay at its zero default.

    Patched at the urlopen boundary rather than at _get, because the counter
    lives inside _get so that retries are counted too - they consume quota
    exactly like successful calls do.
    """
    mock_urlopen.side_effect = [_FakeResponse(_body(2, 2))]
    manifest = run_extraction(
        sink=FakeSink(),
        start=date(2024, 1, 1),
        end=date(2024, 1, 7),
        ingest_date="2024-06-01",
        run_id="counted",
    )
    # One request, not two: the client stops at the reported total rather
    # than making a wasted call to discover an empty page.
    assert manifest.request_count == 1
    assert manifest.record_count == 2
