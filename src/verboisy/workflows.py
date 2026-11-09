# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Read bounded workflow definitions and bind explicitly supplied local sources."""

import hashlib
import re
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from verboisy.utils.exceptions import VerboisyError
from verboisy.utils.json_payload import decode_json, read_bytes

_MAX_BYTES = 1_048_576
_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_IDENTITY = {"version", "name", "revision"}


class WorkflowError(VerboisyError):
    """A reusable workflow cannot be safely loaded or bound."""


def _identity(data: dict[str, Any]) -> dict[str, Any]:
    name, revision = data.get("name"), data.get("revision")
    if (
        data.get("version") != "1"
        or not isinstance(name, str)
        or not _NAME.fullmatch(name)
        or isinstance(revision, bool)
        or not isinstance(revision, int)
        or not 1 <= revision <= 2**31 - 1
    ):
        raise WorkflowError("Use workflow version 1, a lowercase name and a positive revision")
    return {"version": "1", "name": name, "revision": revision}


def _remote(url: str) -> None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise WorkflowError("Invalid workflow source URL") from None
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port == 0
        or any(char.isspace() or ord(char) < 32 or char == "\\" for char in url)
    ):
        raise WorkflowError("Workflow URLs must be HTTP(S) without embedded credentials")


def _required_inputs(task: dict[str, Any]) -> tuple[str, ...]:
    seeds, sources = task.get("seed_urls", []), task.get("dataset_sources", [])
    if (
        not isinstance(seeds, list)
        or not isinstance(sources, list)
        or len(seeds) > 100
        or len(sources) > 100
        or (seeds and sources)
    ):
        raise WorkflowError("Declare up to 100 browser seeds or dataset sources")
    for url in seeds:
        if not isinstance(url, str):
            raise WorkflowError("Workflow seed URLs must be strings")
        _remote(url)
    required = []
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("url"), str):
            raise WorkflowError("Each workflow dataset source needs a URL or input:name")
        url = source["url"]
        if not url.startswith("input:"):
            _remote(url)
            continue
        alias = url.removeprefix("input:")
        if not _NAME.fullmatch(alias) or alias in required:
            raise WorkflowError("Workflow input names must be valid and distinct")
        required.append(alias)
    return tuple(required)


def _check_depth(data: Any) -> None:
    pending = [(data, 0)]
    while pending:
        value, depth = pending.pop()
        if isinstance(value, dict | list):
            if depth >= 64:
                raise WorkflowError("Workflow nesting exceeds 64 levels")
            children = value.values() if isinstance(value, dict) else value
            pending.extend((child, depth + 1) for child in children)


@dataclass(frozen=True)
class WorkflowDefinition:
    """Read-only workflow identity and an independent task for each invocation."""

    path: Path
    name: str
    revision: int
    sha256: str
    goal: str
    schema: dict[str, Any] | list[str]
    task: dict[str, Any]
    inputs: tuple[str, ...]

    def origin(self) -> dict[str, Any]:
        return {"version": "1", "name": self.name, "revision": self.revision, "sha256": self.sha256}

    def bind(
        self, bindings: Mapping[str, str | Path] | None
    ) -> tuple[dict[str, Any], tuple[Path, ...]]:
        values: Mapping[str, str | Path] = {} if bindings is None else bindings
        if not isinstance(values, Mapping) or set(values) != set(self.inputs):
            raise WorkflowError("Bind each declared workflow input exactly once, with no extras")
        paths: dict[str, Path] = {}
        urls: dict[str, str] = {}
        for alias, value in values.items():
            if not isinstance(value, str | Path) or (isinstance(value, str) and not value.strip()):
                raise WorkflowError("Workflow inputs require local file paths")
            try:
                paths[alias] = Path(value).absolute()
                urls[alias] = paths[alias].as_uri()
            except (OSError, ValueError) as error:
                raise WorkflowError("Cannot resolve a workflow input path") from error
        task = deepcopy(self.task)
        for source in task.get("dataset_sources", []):
            if source["url"].startswith("input:"):
                source["url"] = urls[source["url"].removeprefix("input:")]
        return task, tuple(paths.values())


def read_workflow(path: Path, *, expected_sha256: str | None = None) -> WorkflowDefinition:
    """Check a definition's bytes before interpreting any execution fields."""
    if expected_sha256 is not None and (
        not isinstance(expected_sha256, str) or not _SHA256.fullmatch(expected_sha256)
    ):
        raise WorkflowError("Workflow SHA-256 must be 64 lowercase hexadecimal characters")
    try:
        resolved = path.resolve(strict=True)
        raw = read_bytes(resolved, max_bytes=_MAX_BYTES)
    except (OSError, ValueError, RuntimeError) as error:
        raise WorkflowError("Cannot read a stable workflow file within the 1 MiB limit") from error
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise WorkflowError("Workflow SHA-256 differs from the requested version")
    try:
        data = decode_json(raw)
    except ValueError as error:
        raise WorkflowError("Workflow must be valid, unique-key UTF-8 JSON") from error
    _check_depth(data)
    if not isinstance(data, dict) or set(data) - (_IDENTITY | {"goal", "schema", "task"}):
        raise WorkflowError("Workflow contains unsupported fields")
    identity = _identity(data)
    goal, schema, task = data.get("goal"), data.get("schema"), data.get("task", {})
    if not isinstance(goal, str) or not goal.strip() or len(goal) > 8192:
        raise WorkflowError("Workflow goal must contain 1 to 8192 characters")
    if not isinstance(schema, dict | list) or not schema:
        raise WorkflowError("Workflow schema must be an inline JSON Schema or column array")
    if isinstance(schema, list) and (
        len(schema) > 100 or any(not isinstance(name, str) for name in schema)
    ):
        raise WorkflowError("Workflow column arrays must contain up to 100 string names")
    if not isinstance(task, dict):
        raise WorkflowError("Workflow task must be an inline JSON object")
    return WorkflowDefinition(
        resolved,
        identity["name"],
        identity["revision"],
        digest,
        goal,
        schema,
        task,
        _required_inputs(task),
    )


def parse_bindings(declarations: Iterable[str]) -> dict[str, Path]:
    bindings = {}
    for declaration in declarations:
        name, separator, path = declaration.partition("=")
        if not separator or not _NAME.fullmatch(name) or not path.strip() or name in bindings:
            raise WorkflowError("Use --workflow-input NAME=PATH once per declared input")
        bindings[name] = Path(path)
    return bindings


def saved_workflow_origin(events: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    origins = [event.get("payload") for event in events if event.get("kind") == "workflow_origin"]
    if not origins:
        return None
    if len(origins) != 1 or not isinstance(origins[0], dict):
        raise WorkflowError("Saved workflow origin is ambiguous")
    payload = origins[0]
    digest = payload.get("sha256")
    if (
        set(payload) != _IDENTITY | {"sha256"}
        or not isinstance(digest, str)
        or not _SHA256.fullmatch(digest)
    ):
        raise WorkflowError("Saved workflow origin is malformed")
    return {**_identity(payload), "sha256": digest}
