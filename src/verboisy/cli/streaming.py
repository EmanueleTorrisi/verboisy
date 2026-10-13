# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Explicit scaled preparation; the ordinary research command keeps its existing contract."""

import json
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Literal

import typer

from verboisy.evidence.models import ProjectionPlan
from verboisy.storage.path_safety import validate_output_paths
from verboisy.streaming import StreamLedger, StreamLimits, stream_dataset
from verboisy.streaming.export import bundle_paths
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError


def stream_command(
    database: Annotated[Path, typer.Option("--database")] = Path("verboisy-stream.db"),
    dataset_file: Annotated[str | None, typer.Option("--dataset-file")] = None,
    schema: Annotated[Path | None, typer.Option("--schema")] = None,
    projection: Annotated[Path | None, typer.Option("--projection")] = None,
    resume: Annotated[str | None, typer.Option("--resume")] = None,
    export: Annotated[Path | None, typer.Option("--export")] = None,
    csv_mode: Annotated[Literal["spreadsheet", "json"] | None, typer.Option("--csv-mode")] = None,
    rows_per_invocation: Annotated[int | None, typer.Option("--rows-per-invocation")] = None,
    max_input_bytes: Annotated[int | None, typer.Option("--max-input-bytes")] = None,
    max_rows: Annotated[int | None, typer.Option("--max-rows")] = None,
    max_storage_bytes: Annotated[int | None, typer.Option("--max-storage-bytes")] = None,
) -> None:
    """Prepare large granted local CSV/TSV/JSONL/text files or capture an opaque asset.

    Schema and projection options are JSON files. Resume fixes the saved contract;
    an invocation row budget pauses at a committed checkpoint. No model is called.
    """
    try:
        if resume is not None and any(
            v is not None
            for v in (
                dataset_file,
                schema,
                projection,
                max_input_bytes,
                max_rows,
                max_storage_bytes,
                csv_mode,
            )
        ):
            raise VerboisyError("Resume uses the saved streaming contract")
        fmt, path = (dataset_file or "").partition("=")[::2]
        source = Path(path) if dataset_file is not None and path else None
        schema_value = (
            json.loads(schema.read_text(encoding="utf-8")) if schema is not None else None
        )
        plan = (
            ProjectionPlan.model_validate_json(projection.read_text(encoding="utf-8"))
            if projection is not None
            else None
        )
        input_paths = tuple(p for p in (schema, projection, Path(".env")) if p is not None)
        if export is not None:
            validate_output_paths(bundle_paths(export), input_paths)
        limits = (
            None
            if resume is not None
            else StreamLimits(
                **{
                    key: value
                    for key, value in {
                        "max_input_bytes": max_input_bytes,
                        "max_rows": max_rows,
                        "max_storage_bytes": max_storage_bytes,
                    }.items()
                    if value is not None
                }
            )
        )
        result = stream_dataset(
            database=database,
            source=source,
            dataset_format=fmt if dataset_file is not None else None,
            schema=schema_value,
            projection=plan,
            resume=resume,
            config=Settings(),
            limits=limits,
            rows_per_invocation=rows_per_invocation,
            export=export,
            csv_mode=csv_mode,
            protected_inputs=input_paths if resume is None else None,
        )
        typer.echo(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        if result.status == "FAILED":
            raise typer.Exit(1)
    except (VerboisyError, OSError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(1) from None


def stream_status(
    database: Annotated[Path, typer.Option("--database")] = Path("verboisy-stream.db"),
    limit: Annotated[int, typer.Option("--limit")] = 10,
) -> None:
    """Inspect bounded saved job metadata, including IDs recoverable after a crash."""
    try:
        with closing(StreamLedger(database, read_only=True)) as ledger:
            typer.echo(
                json.dumps(
                    {"inspection_version": "stream-1", "jobs": ledger.jobs(limit=limit)}, indent=2
                )
            )
    except VerboisyError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(1) from None
