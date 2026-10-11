# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Offline, source-bound mapping review for a captured run asset."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from verboisy.evidence.models import ProjectionPlan
from verboisy.extractor.dataset import parse_dataset
from verboisy.extractor.mapping import (
    SchemaMappingError,
    declared_mapping,
    suggest_mapping,
    validate_mapping,
)
from verboisy.extractor.profile import profile_dataset
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError


def _aliases(path: Path | None, label: str = "Aliases") -> dict[str, Any] | None:
    if path is None:
        return None
    with path.open("rb") as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise SchemaMappingError(f"{label} file exceeds 1 MiB")
    rows = parse_dataset(b"[" + raw + b"]", "json").rows
    if len(rows) != 1:
        raise SchemaMappingError(f"{label} file must contain exactly one JSON object")
    return rows[0].values


def _publish(path: Path, value: Any) -> None:
    """Publish a complete JSON file without replacing an existing destination."""
    data = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data.encode("utf-8"))
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink()


def review_mapping(
    database: Path,
    run_id: str,
    asset_id: str,
    output: Path,
    *,
    aliases_path: Path | None = None,
    plan_path: Path | None = None,
    projection_path: Path | None = None,
) -> dict[str, Any]:
    """Journal a proposal or explicit plan request; never alter run policy or records."""
    if not database.is_file() or database.is_symlink():
        raise VerboisyError("Choose an existing research database")
    if aliases_path is not None and projection_path is not None:
        raise SchemaMappingError("Choose aliases or an explicit projection plan, not both")
    outputs = [output] + ([] if plan_path is None else [plan_path])
    protected = {
        database.resolve(),
        Path(str(database) + ".lock").resolve(),
        Path(str(database) + "-wal").resolve(),
        Path(str(database) + "-shm").resolve(),
    }
    if aliases_path is not None:
        protected.add(aliases_path.resolve())
    if projection_path is not None:
        protected.add(projection_path.resolve())
    resolved = [path.resolve() for path in outputs]
    if len(set(resolved)) != len(resolved) or any(path in protected for path in resolved):
        raise VerboisyError("Mapping outputs overlap an input or each other")
    if any(path.exists() or path.is_symlink() or not path.parent.is_dir() for path in outputs):
        raise VerboisyError("Mapping outputs require new files in existing directories")
    aliases = _aliases(aliases_path)
    declared = (
        None
        if projection_path is None
        else ProjectionPlan.model_validate(_aliases(projection_path, "Projection"))
    )
    store = ResearchStore(str(database))
    try:
        run = store.load(run_id)
        asset = store.load_dataset_asset(run_id, asset_id)
        schema = json.loads(run["schema_json"])
        profile = profile_dataset(asset.download.dataset)
        suggestion = (
            suggest_mapping(profile, schema, aliases=aliases)
            if declared is None
            else declared_mapping(profile, schema, declared)
        )
        reason = None
        plan = None
        try:
            plan = validate_mapping(asset.download.dataset, schema, suggestion)
        except SchemaMappingError as exc:
            reason = str(exc)
        decision = "proposed" if plan_path is None else "blocked" if plan is None else "approved"
        report = {
            "review_version": "1",
            "run_id": run_id,
            "asset_id": asset_id,
            "aliases": aliases,
            "proposal_kind": "suggested" if declared is None else "declared_plan",
            "profile": asdict(profile),
            "suggestion": asdict(suggestion),
            "full_row_validation": "passed" if plan is not None else "failed",
            "validation_reason": reason,
            "decision": decision,
            "plan": None if plan is None else plan.model_dump(mode="json"),
            "applied_to_run": False,
        }
        published: list[Path] = []
        try:
            _publish(output, report)
            published.append(output)
            if plan_path is not None and plan is not None:
                _publish(plan_path, plan.model_dump(mode="json"))
                published.append(plan_path)
            store.event(run_id, "dataset_mapping_review", report)
        except BaseException:
            for path in published:
                path.unlink(missing_ok=True)
            raise
        return report
    finally:
        store.close()
