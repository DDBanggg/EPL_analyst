"""Small immutable models returned by Bronze storage operations."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BronzeWriteResult:
    """Paths and integrity values for one committed Bronze observation."""

    bronze_id: str
    payload_path: Path
    metadata_path: Path
    sha256: str
    byte_size: int
