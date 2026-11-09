# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Export completed stream rows for local analytics or training."""

import json
from pathlib import Path
from typing import Annotated

import typer

from verboisy.streaming.analytics_contract import (
    DEFAULT_OUTPUT_BYTES,
    DEFAULT_SHARD_ROWS,
    MAX_SCHEMA_BYTES,
)
from verboisy.utils.exceptions import VerboisyError
from verboisy.utils.json_payload import read_json_object


def stream_analytics_command(
    job_id: Annotated[str, typer.Option("--job", help="Completed streaming job ID.")],
    output: Annotated[Path, typer.Option("--output-dir", help="New bundle directory.")],
    database: Annotated[Path, typer.Option("--database")] = Path("verboisy-stream.db"),
    output_format: Annotated[
        str, typer.Option("--format", help="jsonl (gzip compressed) or parquet (requires PyArrow).")
    ] = "jsonl",
    column_contract: Annotated[
        Path | None,
        typer.Option(
            "--columns",
            help='Parquet JSON contract: {"version":"1","columns":[{"name":"id",'
            '"type":"int64","nullable":false}]}',
        ),
    ] = None,
    shard_rows: Annotated[
        int, typer.Option("--shard-rows", help="Maximum rows per shard (also bounded by bytes).")
    ] = DEFAULT_SHARD_ROWS,
    max_output_bytes: Annotated[
        int, typer.Option("--max-output-bytes", help="Ceiling for all files in the new bundle.")
    ] = DEFAULT_OUTPUT_BYTES,
) -> None:
    """Write verified analytical shards and an evidence manifest without model calls."""
    from verboisy.streaming import export_stream_analytics

    try:
        schema = (
            read_json_object(column_contract, max_bytes=MAX_SCHEMA_BYTES)
            if column_contract is not None
            else None
        )
        result = export_stream_analytics(
            database=database,
            job_id=job_id,
            output_dir=output,
            output_format=output_format,
            column_contract=schema,
            shard_rows=shard_rows,
            max_output_bytes=max_output_bytes,
        )
        typer.echo(
            json.dumps(
                {
                    "manifest": str(result.manifest),
                    "rows": result.rows,
                    "shards": result.shards,
                    "output_bytes": result.output_bytes,
                },
                ensure_ascii=False,
            )
        )
    except KeyboardInterrupt:
        raise typer.Exit(130) from None
    except (VerboisyError, OSError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(1) from None
