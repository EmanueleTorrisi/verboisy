# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Inspect or clear one explicit project cache without starting research."""

from pathlib import Path
from typing import Annotated

import typer


def cache_command(
    directory: Annotated[
        Path, typer.Option("--directory", help="Absolute private cache directory.")
    ],
    scope: Annotated[str, typer.Option("--scope", help="Exact project scope to inspect or clear.")],
    clear: Annotated[
        bool, typer.Option("--clear", help="Delete only this project's cached assessments.")
    ] = False,
    max_bytes: Annotated[int, typer.Option("--max-bytes", min=65536, max=1024**3)] = 64 * 1024**2,
) -> None:
    import json

    from verboisy.cache import CacheError, ProjectCache
    from verboisy.cache_policy import CachePolicy

    try:
        policy = CachePolicy(directory, scope, max_bytes, min(1024**2, max_bytes // 4))
        # Inspection should not create a cache or touch unrelated project files.
        if policy.directory.is_symlink() or policy.database.is_symlink():
            raise CacheError("Linked cache inputs are not supported")
        if not policy.database.exists():
            typer.echo(json.dumps({"entries": 0, "exists": False, "cleared": False}))
            return
        with ProjectCache(policy) as cache:
            if clear:
                cache.clear()
            result = cache.stats()
        typer.echo(json.dumps({**result, "exists": True, "cleared": clear}, sort_keys=True))
    except (OSError, ValueError):
        typer.echo("Project cache unavailable or configuration invalid.", err=True)
        raise typer.Exit(1) from None
