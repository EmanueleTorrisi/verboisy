# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Emit versioned, value-free operational reports for existing ledgers."""

import json
from pathlib import Path
from typing import Annotated

import typer

from verboisy.utils.exceptions import VerboisyError


def operations_command(
    database: Annotated[Path, typer.Option("--database", help="Existing Verboisy ledger.")],
    kind: Annotated[str, typer.Option("--kind", help="research or stream.")] = "research",
    run_id: Annotated[str | None, typer.Option("--run-id", help="One saved run or job ID.")] = None,
    limit: Annotated[
        int, typer.Option("--limit", help="Newest saved entries, from 1 to 500.")
    ] = 100,
) -> None:
    """Report saved outcomes, row counts and request accounting as JSON."""
    from verboisy import operational_report

    try:
        report = operational_report(database, kind=kind, run_id=run_id, limit=limit)
        typer.echo(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))
    except KeyboardInterrupt:
        raise typer.Exit(130) from None
    except (VerboisyError, OSError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(1) from None
