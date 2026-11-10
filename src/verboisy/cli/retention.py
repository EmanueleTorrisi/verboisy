# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Preview or explicitly apply owner-private local retention plans."""

import json
from pathlib import Path
from typing import Annotated

import typer

from verboisy.utils.exceptions import VerboisyError


def retention_command(
    workspace: Annotated[
        Path, typer.Option("--workspace", help="Owned Linux directory, mode 0700.")
    ],
    database: Annotated[str, typer.Option("--database", help="Ledger filename in the workspace.")],
    kind: Annotated[str, typer.Option("--kind", help="research or stream.")] = "research",
    keep_last: Annotated[
        int, typer.Option("--keep-last", help="Number of newest completed entries to retain.")
    ] = 10,
    limit: Annotated[
        int, typer.Option("--limit", help="Maximum completed entries in one plan.")
    ] = 25,
    protect: Annotated[
        list[str] | None,
        typer.Option("--protect-run-id", help="Keep a saved ID; repeat as needed."),
    ] = None,
    apply_plan: Annotated[
        str | None, typer.Option("--apply-plan", help="Apply an unchanged preview by its SHA-256.")
    ] = None,
) -> None:
    """Preview completed ledger deletions; apply only with an exact preview digest."""
    from verboisy.retention import retain_completed

    try:
        result = retain_completed(
            workspace,
            database,
            kind=kind,
            keep_last=keep_last,
            limit=limit,
            protect=tuple(protect or ()),
            apply_plan=apply_plan,
        )
        typer.echo(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
    except KeyboardInterrupt:
        raise typer.Exit(130) from None
    except (VerboisyError, OSError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(1) from None
