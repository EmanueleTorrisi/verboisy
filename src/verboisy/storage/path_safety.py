# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Reject export aliases before replacing data or provenance files.

Path resolution detects parent-directory aliases; inode comparison detects hard
links. These checks protect ordinary local use, not concurrent hostile filesystem
mutation. Deployments must give each writer exclusive control of its directory.
"""

from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import url2pathname

from verboisy.evidence.models import TaskSpec


def protected_run_paths(database: Path, task_json: str, events: list[dict[str, Any]]) -> set[Path]:
    """Derive input protection from persisted facts, independent of export overrides."""
    task = TaskSpec.model_validate_json(task_json)
    inputs = {Path(str(database) + suffix) for suffix in ("", "-wal", "-shm", ".lock")}
    inputs.update(local_source_paths(source.url for source in task.dataset_sources))
    inputs.update(export_input_paths(events))
    for event in events:
        if event.get("kind") != "product_options":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("Saved product options are malformed")
        reference = payload.get("smartid")
        if reference is not None:
            if not isinstance(reference, str):
                raise ValueError("Saved SmartID reference must be a path string")
            inputs.add(Path(reference).resolve())
    return inputs


def export_input_paths(events: list[dict[str, Any]]) -> set[Path]:
    """Decode saved input paths without trusting malformed journal payloads."""
    inputs: set[Path] = set()
    for event in events:
        if event.get("kind") != "export_inputs":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict) or not isinstance(payload.get("paths"), list):
            raise ValueError("Saved export input journal is malformed")
        for value in payload["paths"]:
            if not isinstance(value, str) or not Path(value).is_absolute():
                raise ValueError("Saved export input paths must be absolute strings")
            inputs.add(Path(value))
    return inputs


def local_source_paths(urls: Iterable[str]) -> tuple[Path, ...]:
    """Return local declared inputs without interpreting remote URLs as paths."""
    return tuple(
        Path(url2pathname(urlsplit(url).path)) for url in urls if urlsplit(url).scheme == "file"
    )


def dataset_output_paths(destination: Path) -> tuple[Path, ...]:
    """Include every potential sidecar, even when this generation omits one."""
    return (
        destination,
        *(
            destination.with_suffix(destination.suffix + suffix)
            for suffix in (".manifest.json", ".evidence.json", ".events.json", ".assets.json")
        ),
        destination.with_name(destination.stem + ".proof.txt"),
    )


def validate_output_paths(outputs: Iterable[Path], protected: Iterable[Path]) -> None:
    """Fail closed on unsafe destinations or aliases of protected input files."""
    seen_paths: set[Path] = set()
    seen_inodes: set[tuple[int, int]] = set()
    inputs = tuple(protected)
    protected_paths = {path.resolve() for path in inputs}
    protected_inodes = {
        (stat.st_dev, stat.st_ino) for path in inputs if path.exists() for stat in (path.stat(),)
    }
    for path in outputs:
        if path.is_symlink() or path.is_dir():
            raise ValueError("Export destination is a symlink or directory")
        resolved = path.resolve()
        if resolved in protected_paths or resolved in seen_paths:
            raise ValueError("Export destination aliases an input or another output")
        seen_paths.add(resolved)
        if path.exists():
            stat = path.stat()
            inode = (stat.st_dev, stat.st_ino)
            if inode in protected_inodes or inode in seen_inodes:
                raise ValueError("Export destination aliases an input or another output inode")
            seen_inodes.add(inode)
