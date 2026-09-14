"""Immutable PitchAPI control-plane and run-result models."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from epl_analyst.bronze import BronzeWriteResult


class RunStatus(StrEnum):
    SUCCESS = "SUCCESS"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class MatchRecord:
    match_id: str
    status: str
    time_utc: datetime


@dataclass(frozen=True)
class ResourceResult:
    resource: str
    status: RunStatus
    match_id: str | None = None
    bronze: BronzeWriteResult | None = None
    error_code: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class IngestionRunResult:
    mode: str
    resources: tuple[ResourceResult, ...]

    @property
    def success_count(self) -> int:
        return sum(item.status is RunStatus.SUCCESS for item in self.resources)

    @property
    def skipped_count(self) -> int:
        return sum(item.status is RunStatus.SKIPPED for item in self.resources)

    @property
    def failure_count(self) -> int:
        return sum(item.status is RunStatus.FAILED for item in self.resources)

    @property
    def succeeded(self) -> bool:
        return self.failure_count == 0

    @property
    def exit_code(self) -> int:
        return 0 if self.succeeded else 1
