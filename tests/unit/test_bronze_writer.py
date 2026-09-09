import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

import pytest

import epl_analyst.bronze.writer as writer_module
from epl_analyst.bronze import BronzeWriteError, BronzeWriter

UTC_FETCHED_AT = datetime(2026, 9, 9, 5, 20, 30, 123456, tzinfo=timezone.utc)


@pytest.fixture
def bronze_root(tmp_path):
    root = tmp_path / "bronze"
    root.mkdir()
    return root


@pytest.fixture
def writer(bronze_root):
    return BronzeWriter(bronze_root)


def write_response(writer, **overrides):
    values = {
        "provider": "football_data_org",
        "resource": "matches",
        "payload_format": "json",
        "raw_bytes": b'{\n  "club": "Arsenal", "city": "M\xc3\xbcnchen"\n}\n',
        "fetched_at": UTC_FETCHED_AT,
        "http_status": 200,
        "content_type": "application/json",
        "method": "GET",
        "endpoint": "/v4/competitions/PL/matches",
        "params": {"season": 2026},
    }
    values.update(overrides)
    return writer.write_response(**values)


def test_json_bytes_and_sidecar_integrity_are_preserved(writer, bronze_root):
    raw_bytes = b'{\n  "z": 1,\n  "name": "Caf\xc3\xa9",\n  "a": [3, 2, 1]\n}\n'

    result = write_response(writer, raw_bytes=raw_bytes)
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))

    expected_partition = (
        bronze_root / "football_data_org" / "matches" / "2026-09-09"
    )
    assert result.payload_path.parent == expected_partition
    assert result.payload_path.read_bytes() == raw_bytes
    assert result.payload_path.suffix == ".json"
    assert result.metadata_path.name == f"{result.bronze_id}.meta.json"
    assert re.fullmatch(
        r"20260909T052030123456Z_[0-9a-f]{12}", result.bronze_id
    )
    assert metadata["schema_version"] == 1
    assert metadata["bronze_id"] == result.bronze_id
    assert metadata["provider"] == "football_data_org"
    assert metadata["resource"] == "matches"
    assert metadata["fetched_at"] == "2026-09-09T05:20:30.123456Z"
    assert metadata["ingest_date"] == "2026-09-09"
    assert metadata["payload_file"] == result.payload_path.name
    assert metadata["payload_format"] == "json"
    assert metadata["http_status"] == 200
    assert metadata["content_type"] == "application/json"
    assert metadata["request"] == {
        "endpoint": "/v4/competitions/PL/matches",
        "method": "GET",
        "params": {"season": 2026},
    }
    assert metadata["byte_size"] == len(raw_bytes) == result.byte_size
    assert metadata["sha256"] == hashlib.sha256(raw_bytes).hexdigest()
    assert result.sha256 == metadata["sha256"]
    assert result.payload_path.is_relative_to(bronze_root.resolve())


def test_csv_bytes_are_preserved_exactly(writer):
    raw_bytes = b'name,score\r\n"A, FC",2\r\nB FC,0\r\n'

    result = write_response(
        writer,
        payload_format="csv",
        raw_bytes=raw_bytes,
        content_type="text/csv; charset=utf-8",
    )

    assert result.payload_path.suffix == ".csv"
    assert result.payload_path.read_bytes() == raw_bytes


def test_identical_observations_are_stored_separately(writer):
    raw_bytes = b'{"same":true}'

    first = write_response(writer, raw_bytes=raw_bytes)
    second = write_response(writer, raw_bytes=raw_bytes)

    assert first.bronze_id != second.bronze_id
    assert first.payload_path != second.payload_path
    assert first.metadata_path != second.metadata_path
    assert first.payload_path.exists() and second.payload_path.exists()
    assert first.metadata_path.exists() and second.metadata_path.exists()
    assert first.sha256 == second.sha256
    assert first.byte_size == second.byte_size


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider", "bad/provider"),
        ("provider", "bad\\provider"),
        ("provider", ".."),
        ("resource", "match stats"),
        ("resource", "Matches"),
        ("resource", "matches-v2"),
    ],
)
def test_unsafe_storage_keys_are_rejected(writer, bronze_root, field, value):
    with pytest.raises(BronzeWriteError, match=field):
        write_response(writer, **{field: value})

    assert not any(bronze_root.rglob("*.meta.json"))


def test_non_utc_timestamp_is_normalized_for_name_partition_and_metadata(
    writer,
):
    local_time = datetime(
        2026, 9, 10, 1, 30, 0, 7, tzinfo=timezone(timedelta(hours=7))
    )

    result = write_response(writer, fetched_at=local_time)
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))

    assert result.payload_path.parent.name == "2026-09-09"
    assert result.bronze_id.startswith("20260909T183000000007Z_")
    assert metadata["fetched_at"] == "2026-09-09T18:30:00.000007Z"


def test_naive_timestamp_is_rejected(writer, bronze_root):
    with pytest.raises(BronzeWriteError, match="timezone-aware"):
        write_response(writer, fetched_at=datetime(2026, 9, 9, 5, 20, 30))

    assert not any(bronze_root.rglob("*.meta.json"))


def test_unsupported_format_leaves_no_object(writer, bronze_root):
    with pytest.raises(BronzeWriteError, match="json.*csv"):
        write_response(writer, payload_format="xml")

    assert not any(bronze_root.rglob("*.*"))


@pytest.mark.parametrize("status", [200, 201, 204, 299])
def test_success_statuses_accept_zero_length_bytes(writer, status):
    result = write_response(writer, http_status=status, raw_bytes=b"")

    assert result.payload_path.read_bytes() == b""
    assert result.byte_size == 0


@pytest.mark.parametrize("status", [199, 300, 400, 500])
def test_non_success_status_leaves_no_object(writer, bronze_root, status):
    with pytest.raises(BronzeWriteError, match="2xx"):
        write_response(writer, http_status=status)

    assert not any(bronze_root.rglob("*.*"))


def test_non_serializable_params_fail_before_commit(writer, bronze_root):
    with pytest.raises(BronzeWriteError, match="JSON-serializable"):
        write_response(writer, params={"unsafe": object()})

    assert not any(bronze_root.rglob("*.*"))


def test_sidecar_commit_failure_removes_payload_and_temporary_files(
    monkeypatch, writer, bronze_root
):
    original_commit = writer_module._commit_temp

    def fail_sidecar_commit(temp_path, target):
        if target.name.endswith(".meta.json"):
            raise OSError("simulated sidecar failure")
        original_commit(temp_path, target)

    monkeypatch.setattr(writer_module, "_commit_temp", fail_sidecar_commit)

    with pytest.raises(OSError, match="simulated sidecar failure"):
        write_response(writer)

    assert not any(path.is_file() for path in bronze_root.rglob("*"))


def test_missing_bronze_root_is_rejected(tmp_path):
    with pytest.raises(BronzeWriteError, match="existing directory"):
        BronzeWriter(tmp_path / "missing")
