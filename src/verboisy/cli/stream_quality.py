# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Inspect dataset quality without changing the streaming ledger."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from verboisy.utils.exceptions import VerboisyError
from verboisy.utils.json_payload import read_json_object


def stream_quality_command(
    job_id: Annotated[str, typer.Option("--job", help="Completed streaming job ID.")],
    contract_file: Annotated[
        Path, typer.Option("--contract", help="Version 1 JSON quality rules.")
    ],
    database: Annotated[Path, typer.Option("--database")] = Path("verboisy-stream.db"),
    max_index_bytes: Annotated[int, typer.Option("--max-index-bytes")] = 4 * 1024**3,
    scratch_dir: Annotated[
        Path | None, typer.Option("--scratch-dir", help="Directory for the disposable key index.")
    ] = None,
) -> None:
    """Check row counts, completeness and uniqueness. Exit 3 on verified rule failures."""
    from verboisy.streaming import check_stream_quality
    from verboisy.streaming.quality_contract import MAX_CONTRACT_BYTES

    try:
        contract = read_json_object(contract_file, max_bytes=MAX_CONTRACT_BYTES)
        result = check_stream_quality(
            database=database,
            job_id=job_id,
            contract=contract,
            max_index_bytes=max_index_bytes,
            scratch_dir=scratch_dir,
        )
        typer.echo(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        if not result.passed:
            raise typer.Exit(3)
    except KeyboardInterrupt:
        raise typer.Exit(130) from None
    except (VerboisyError, OSError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(1) from None
