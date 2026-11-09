# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Produce a bounded update file from completed local snapshots."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from verboisy.utils.exceptions import VerboisyError


def stream_update_command(
    baseline: Annotated[str, typer.Option("--baseline", help="Baseline streaming job ID.")],
    current: Annotated[str, typer.Option("--current", help="Current streaming job ID.")],
    keys: Annotated[
        list[str],
        typer.Option("--key", help="Record key JSON pointer. Repeat for a composite key."),
    ],
    output: Annotated[Path, typer.Option("--export", help="New .jsonl update file.")],
    database: Annotated[Path, typer.Option("--database")] = Path("verboisy-stream.db"),
    complete_snapshot: Annotated[
        bool,
        typer.Option(
            "--complete-snapshot",
            help="Confirm both captures cover the same full dataset; allow deletions.",
        ),
    ] = False,
    max_index_bytes: Annotated[int, typer.Option("--max-index-bytes")] = 4 * 1024**3,
    max_output_bytes: Annotated[int, typer.Option("--max-output-bytes")] = 8 * 1024**3,
) -> None:
    """Export only changed records from two verified streaming jobs. No model is called."""
    from verboisy.streaming import UpdateLimits, stream_updates

    try:
        result = stream_updates(
            database=database,
            baseline=baseline,
            current=current,
            keys=tuple(keys),
            output=output,
            complete_snapshot=complete_snapshot,
            limits=UpdateLimits(max_index_bytes, max_output_bytes),
        )
        typer.echo(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    except KeyboardInterrupt:
        raise typer.Exit(130) from None
    except (VerboisyError, OSError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(1) from None
