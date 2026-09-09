"""Atomic persistence of immutable provider response bytes and metadata."""

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from epl_analyst.bronze.models import BronzeWriteResult

SCHEMA_VERSION = 1
_STORAGE_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]*$")
_METHOD_PATTERN = re.compile(r"^[A-Z]+$")
_FORMAT_EXTENSIONS = {"json": ".json", "csv": ".csv"}


class BronzeWriteError(ValueError):
    """Raised when a response does not satisfy the Bronze storage contract."""


class BronzeWriter:
    """Write one successful provider response as one immutable Bronze object."""

    def __init__(self, bronze_root: Path) -> None:
        self.bronze_root = Path(bronze_root).expanduser().resolve()
        if not self.bronze_root.is_dir():
            raise BronzeWriteError(
                f"Bronze root must be an existing directory: {self.bronze_root}"
            )

    def write_response(
        self,
        *,
        provider: str,
        resource: str,
        payload_format: str,
        raw_bytes: bytes,
        http_status: int,
        method: str,
        endpoint: str,
        params: Mapping[str, Any] | None = None,
        fetched_at: datetime | None = None,
        content_type: str | None = None,
    ) -> BronzeWriteResult:
        """Persist exact response bytes and commit its metadata sidecar last."""
        _validate_storage_key("provider", provider)
        _validate_storage_key("resource", resource)
        extension = _validate_payload_format(payload_format)
        _validate_raw_bytes(raw_bytes)
        _validate_http_status(http_status)
        _validate_method(method)
        _validate_endpoint(endpoint)
        _validate_content_type(content_type)
        request_params = _validate_params(params)
        observed_at = _normalize_fetched_at(fetched_at)

        ingest_date = observed_at.date().isoformat()
        partition = self.bronze_root / provider / resource / ingest_date
        bronze_id, payload_path, metadata_path = self._available_paths(
            partition, observed_at, extension
        )
        digest = hashlib.sha256(raw_bytes).hexdigest()

        metadata = {
            "bronze_id": bronze_id,
            "byte_size": len(raw_bytes),
            "content_type": content_type,
            "fetched_at": _format_utc(observed_at),
            "http_status": http_status,
            "ingest_date": ingest_date,
            "payload_file": payload_path.name,
            "payload_format": payload_format,
            "provider": provider,
            "request": {
                "endpoint": endpoint,
                "method": method,
                "params": request_params,
            },
            "resource": resource,
            "schema_version": SCHEMA_VERSION,
            "sha256": digest,
        }
        try:
            metadata_bytes = (
                json.dumps(
                    metadata,
                    allow_nan=False,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise BronzeWriteError(
                "Request params must contain only JSON-serializable values"
            ) from error

        partition.mkdir(parents=True, exist_ok=True)
        payload_temp: Path | None = None
        metadata_temp: Path | None = None
        payload_committed = False
        try:
            payload_temp = _write_temp(payload_path, raw_bytes)
            metadata_temp = _write_temp(metadata_path, metadata_bytes)
            _commit_temp(payload_temp, payload_path)
            payload_temp = None
            payload_committed = True
            _commit_temp(metadata_temp, metadata_path)
            metadata_temp = None
        except Exception:
            _remove_if_exists(payload_temp)
            _remove_if_exists(metadata_temp)
            if payload_committed and not metadata_path.exists():
                _remove_if_exists(payload_path)
            raise

        return BronzeWriteResult(
            bronze_id=bronze_id,
            payload_path=payload_path,
            metadata_path=metadata_path,
            sha256=digest,
            byte_size=len(raw_bytes),
        )

    def _available_paths(
        self, partition: Path, fetched_at: datetime, extension: str
    ) -> tuple[str, Path, Path]:
        for _ in range(100):
            timestamp = fetched_at.strftime("%Y%m%dT%H%M%S%fZ")
            bronze_id = f"{timestamp}_{uuid4().hex[:12]}"
            payload_path = partition / f"{bronze_id}{extension}"
            metadata_path = partition / f"{bronze_id}.meta.json"
            if not payload_path.exists() and not metadata_path.exists():
                return bronze_id, payload_path, metadata_path
        raise BronzeWriteError("Could not generate an available Bronze object ID")


def _validate_storage_key(name: str, value: str) -> None:
    if not isinstance(value, str) or not _STORAGE_KEY_PATTERN.fullmatch(value):
        raise BronzeWriteError(
            f"{name} must match ^[a-z0-9][a-z0-9_]*$"
        )


def _validate_payload_format(payload_format: str) -> str:
    try:
        return _FORMAT_EXTENSIONS[payload_format]
    except (KeyError, TypeError) as error:
        raise BronzeWriteError("payload_format must be 'json' or 'csv'") from error


def _validate_raw_bytes(raw_bytes: bytes) -> None:
    if not isinstance(raw_bytes, bytes):
        raise BronzeWriteError("raw_bytes must be bytes")


def _validate_http_status(http_status: int) -> None:
    if isinstance(http_status, bool) or not isinstance(http_status, int):
        raise BronzeWriteError("http_status must be an integer")
    if not 200 <= http_status < 300:
        raise BronzeWriteError("Only successful 2xx responses may enter Bronze")


def _validate_method(method: str) -> None:
    if not isinstance(method, str) or not _METHOD_PATTERN.fullmatch(method):
        raise BronzeWriteError("method must contain uppercase ASCII letters only")


def _validate_endpoint(endpoint: str) -> None:
    unsafe = ("?", "#", "://", "\r", "\n")
    if (
        not isinstance(endpoint, str)
        or not endpoint.startswith("/")
        or any(value in endpoint for value in unsafe)
    ):
        raise BronzeWriteError(
            "endpoint must be a relative path without query, fragment, or credentials"
        )


def _validate_content_type(content_type: str | None) -> None:
    if content_type is not None and (
        not isinstance(content_type, str)
        or not content_type
        or "\r" in content_type
        or "\n" in content_type
    ):
        raise BronzeWriteError("content_type must be a non-empty single-line string")


def _validate_params(params: Mapping[str, Any] | None) -> dict[str, Any]:
    if params is None:
        return {}
    if not isinstance(params, Mapping) or not all(
        isinstance(key, str) for key in params
    ):
        raise BronzeWriteError("params must be a mapping with string keys")
    return dict(params)


def _normalize_fetched_at(fetched_at: datetime | None) -> datetime:
    observed_at = datetime.now(timezone.utc) if fetched_at is None else fetched_at
    if not isinstance(observed_at, datetime):
        raise BronzeWriteError("fetched_at must be a datetime")
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise BronzeWriteError("fetched_at must be timezone-aware")
    return observed_at.astimezone(timezone.utc)


def _format_utc(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _write_temp(target: Path, content: bytes) -> Path:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temp_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        return temp_path
    except Exception:
        _remove_if_exists(temp_path)
        raise


def _commit_temp(temp_path: Path, target: Path) -> None:
    os.replace(temp_path, target)


def _remove_if_exists(path: Path | None) -> None:
    if path is not None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
