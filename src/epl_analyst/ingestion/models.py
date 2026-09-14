"""Shared immutable models at the provider-to-Bronze boundary."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


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
