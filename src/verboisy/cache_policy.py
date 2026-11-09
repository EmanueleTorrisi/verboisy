# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Explicit project cache limits, without importing clients or storage engines."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


def is_cache_integer(value: object) -> bool:
    """Accept integer quantities while excluding booleans."""
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True)
class CachePolicy:
    directory: Path
    scope: str
    max_bytes: int = 64 * 1024**2
    max_entry_bytes: int = 1024**2
    ttl_seconds: int = 3600
    max_entries: int = 10000

    def __post_init__(self) -> None:
        if not isinstance(self.directory, Path) or not self.directory.is_absolute():
            raise ValueError("Cache directory must be an absolute path")
        if not isinstance(self.scope, str) or not self.scope.strip() or len(self.scope) > 128:
            raise ValueError("Cache scope must contain 1 to 128 characters")
        try:
            self.scope.encode("utf-8")
        except UnicodeError as error:
            raise ValueError("Cache scope must be valid UTF-8") from error
        for value, low, high in (
            (self.max_bytes, 65536, 1024**3),
            (self.ttl_seconds, 1, 604800),
            (self.max_entries, 1, 1000000),
        ):
            if not is_cache_integer(value) or not low <= value <= high:
                raise ValueError("Cache limits must be integers within their supported bounds")
        if (
            not is_cache_integer(self.max_entry_bytes)
            or not 1 <= self.max_entry_bytes <= self.max_bytes // 4
        ):
            raise ValueError("Cache entries must fit within one quarter of the database limit")

    @property
    def database(self) -> Path:
        name = sha256(self.scope.encode("utf-8")).hexdigest()
        return self.directory / f"assessments-{name}.sqlite3"

    @property
    def protected_paths(self) -> tuple[Path, ...]:
        return tuple(
            Path(str(self.database) + suffix) for suffix in ("", "-journal", "-wal", "-shm")
        )

    @property
    def entry_limit(self) -> int:
        return min(self.max_entries, self.max_bytes // 1024)
