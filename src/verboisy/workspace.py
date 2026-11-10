# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Explicit owner-private local workspace access for ledger administration."""

import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from verboisy.utils.exceptions import VerboisyError

_SIDECARS = (".lock", "-shm", "-wal", "-journal")
_Stamp = tuple[int, int, int, int, int]


def _owner_uid() -> int:
    current = getattr(os, "geteuid", None)
    if sys.platform != "linux" or not callable(current):
        raise VerboisyError("Private workspace controls require Linux or WSL")
    return int(current())


def _lstat(path: Path) -> os.stat_result:
    return path.lstat()


def _directory(root: Path, uid: int) -> os.stat_result:
    info = _lstat(root)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_mode & 0o777 != 0o700:
        raise VerboisyError("Workspace must be an owned directory with mode 0700")
    for parent in root.parents:
        ancestor = _lstat(parent)
        if (
            not stat.S_ISDIR(ancestor.st_mode)
            or ancestor.st_uid not in (0, uid)
            or (ancestor.st_mode & 0o022 and not ancestor.st_mode & stat.S_ISVTX)
        ):
            raise VerboisyError("Workspace has an unsafe ancestor directory")
    return info


def _file(path: Path, uid: int, *, optional: bool) -> os.stat_result | None:
    try:
        info = _lstat(path)
    except FileNotFoundError:
        if optional:
            return None
        raise VerboisyError("Choose an existing ledger in the private workspace") from None
    if not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_nlink != 1:
        raise VerboisyError("Ledger and sidecars must be owned regular files without links")
    return info


def _fingerprint(info: os.stat_result) -> _Stamp:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


@dataclass(frozen=True)
class WorkspaceLedger:
    path: Path
    owner: int

    def stamp(self) -> tuple[tuple[int, int], _Stamp, _Stamp | None]:
        """Bind a plan to the database and nonempty WAL, excluding reader sidecars."""
        try:
            directory = _directory(self.path.parent, self.owner)
            database = _file(self.path, self.owner, optional=False)
            assert database is not None
            wal = None
            for suffix in _SIDECARS:
                sidecar = self.path.with_name(self.path.name + suffix)
                info = _file(sidecar, self.owner, optional=True)
                if info is not None and info.st_size:
                    if suffix == ".lock":
                        raise VerboisyError("Ledger lock path contains data; preserve it")
                    if suffix == "-journal":
                        raise VerboisyError("Ledger has an active or unrecovered rollback journal")
                    if suffix == "-wal":
                        wal = _fingerprint(info)
            return (directory.st_dev, directory.st_ino), _fingerprint(database), wal
        except OSError:
            raise VerboisyError("Cannot inspect private workspace access") from None


def workspace_ledger(workspace: Path, database: str) -> WorkspaceLedger:
    """Require a direct ledger name under a private, canonical Linux directory."""
    if (
        not isinstance(database, str)
        or not database
        or not database.isprintable()
        or database in (".", "..")
        or any(separator in database for separator in ("/", "\\", ":"))
    ):
        raise VerboisyError("Choose a single ledger filename inside the workspace")
    uid = _owner_uid()
    try:
        root = workspace.resolve(strict=True)
    except (OSError, RuntimeError):
        raise VerboisyError("Choose an existing private workspace directory") from None
    if root != workspace.absolute():
        raise VerboisyError("Use a canonical workspace path without symlinks or parent traversals")
    ledger = WorkspaceLedger(root / database, uid)
    ledger.stamp()
    return ledger
