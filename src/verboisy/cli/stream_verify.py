# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Check a received analytical bundle without loading its ledger or a provider."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from verboisy.utils.exceptions import VerboisyError


def stream_verify_command(
    directory: Annotated[Path, typer.Argument(help="Completed analytical bundle directory.")],
    sha256: Annotated[
        str | None, typer.Option("--manifest-sha256", help="Expected digest from a trusted sender.")
    ] = None,
    require_rows: Annotated[
        bool,
        typer.Option("--require-row-checks", help="Refuse Parquet; check every gzip JSONL row."),
    ] = False,
    max_bundle_bytes: Annotated[
        int | None, typer.Option("--max-bundle-bytes", help="Override the 32 GiB file-byte limit.")
    ] = None,
    max_decoded_bytes: Annotated[
        int | None,
        typer.Option("--max-decoded-bytes", help="Override the 128 GiB decoded byte limit."),
    ] = None,
    max_row_bytes: Annotated[
        int | None, typer.Option("--max-row-bytes", help="Override the 1 MiB JSONL row limit.")
    ] = None,
) -> None:
    """Verify analytical files and proofs, plus row digests for gzip JSONL."""
    from verboisy.streaming.analytics_contract import DEFAULT_OUTPUT_BYTES
    from verboisy.streaming.analytics_verify import (
        DEFAULT_DECODED_BYTES,
        DEFAULT_ROW_BYTES,
        verify_stream_analytics,
    )

    try:
        result = verify_stream_analytics(
            directory,
            expected_manifest_sha256=sha256,
            require_row_checks=require_rows,
            max_bundle_bytes=DEFAULT_OUTPUT_BYTES if max_bundle_bytes is None else max_bundle_bytes,
            max_decoded_bytes=DEFAULT_DECODED_BYTES
            if max_decoded_bytes is None
            else max_decoded_bytes,
            max_row_bytes=DEFAULT_ROW_BYTES if max_row_bytes is None else max_row_bytes,
        )
    except KeyboardInterrupt:
        raise typer.Exit(130) from None
    except (VerboisyError, OSError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(1) from None
    typer.echo(json.dumps(asdict(result), ensure_ascii=False, allow_nan=False))
