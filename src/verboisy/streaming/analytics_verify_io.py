# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Bounded read-only file and gzip handling for analytical bundle verification."""

import hashlib
import io
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from gzip import GzipFile
from pathlib import Path
from typing import Any, BinaryIO

from verboisy.streaming.contract import StreamError

BLOCK_BYTES = 1024 * 1024


def _stamp(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _linked(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


@contextmanager
def stable_directory(path: Path) -> Iterator[None]:
    """Use an explicit directory and detect changes to its membership during a check."""
    before = path.lstat()
    if not stat.S_ISDIR(before.st_mode) or _linked(before):
        raise StreamError("Choose a real analytical bundle directory")
    yield
    if _stamp(path.lstat()) != _stamp(before):
        raise StreamError("Analytical bundle directory changed during verification")


@contextmanager
def regular_file(path: Path, ceiling: int) -> Iterator[tuple[BinaryIO, int]]:
    """Reject linked and special files before reading, and bind the read to its inode."""
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or _linked(before):
        raise StreamError("Analytical bundle files must be unlinked regular files")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_BINARY", 0)
    )
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if _stamp(before) != _stamp(opened):
            raise StreamError("Analytical bundle file changed before reading")
        if not 0 < opened.st_size <= ceiling:
            raise StreamError("Analytical bundle file exceeds its size limit or is empty")
        yield stream, opened.st_size
        if _stamp(opened) != _stamp(os.fstat(stream.fileno())) or _stamp(opened) != _stamp(
            path.lstat()
        ):
            raise StreamError("Analytical bundle file changed during verification")


class CheckedReader(io.RawIOBase):
    """Hash the same compressed bytes that are consumed, with no second file scan."""

    def __init__(self, stream: BinaryIO, size: int) -> None:
        super().__init__()
        self.stream = stream
        self.remaining = size
        self.digest = hashlib.sha256()

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        with memoryview(buffer) as target:
            data = self.stream.read(min(len(target), self.remaining + 1, BLOCK_BYTES))
            if len(data) > self.remaining:
                raise StreamError("Analytical shard grew while reading")
            target[: len(data)] = data
        self.remaining -= len(data)
        self.digest.update(data)
        return len(data)

    def finish(self, digest: str) -> None:
        if self.remaining or self.digest.hexdigest() != digest:
            raise StreamError("Analytical shard SHA-256 does not match the manifest")


class DecodedBudget:
    def __init__(self, ceiling: int) -> None:
        self.remaining = ceiling

    def line(self, stream: GzipFile, ceiling: int) -> bytes:
        data = stream.readline(min(ceiling + 1, self.remaining) + 1)
        if len(data) > self.remaining:
            raise StreamError("Analytical bundle exceeds its decoded byte limit")
        if len(data) > ceiling + 1:
            raise StreamError("Analytical bundle contains an oversized row")
        if not data.endswith(b"\n"):
            raise StreamError("Analytical bundle row is missing or lacks its final newline")
        self.remaining -= len(data)
        return data[:-1]
