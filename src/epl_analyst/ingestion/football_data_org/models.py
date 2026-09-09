"""Immutable, secret-safe models for football-data.org ingestion."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from epl_analyst.bronze import BronzeWriteResult


@dataclass(frozen=True)
class ProviderResponse:
    """Successful provider response without HTTP client or credential state."""

    raw_bytes: bytes = field(repr=False)
    status_code: int
    content_type: str | None
    method: str
    endpoint: str
    params: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))


@dataclass(frozen=True)
class ResourceIngestionResult:
    """Safe result for one requested production resource."""

    resource: str
    succeeded: bool
    bronze: BronzeWriteResult | None = None
    error: str | None = None


@dataclass(frozen=True)
class IngestionRunResult:
    """Immutable result of an all-resource or targeted ingestion run."""

    target: str
    resources: tuple[ResourceIngestionResult, ...]

    @property
    def succeeded(self) -> bool:
        return all(result.succeeded for result in self.resources)

    @property
    def success_count(self) -> int:
        return sum(result.succeeded for result in self.resources)

    @property
    def failure_count(self) -> int:
        return len(self.resources) - self.success_count

    @property
    def exit_code(self) -> int:
        return 0 if self.succeeded else 1
