# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Bounded inspection of verified saved dataset captures without acquisition."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from verboisy.storage.assets import load_asset
from verboisy.storage.research import DB_VERSION
from verboisy.utils.exceptions import VerboisyError


def inspect_dataset_assets(database: Path, run_id: str, *, limit: int = 100) -> dict[str, Any]:
    """List capture identities after checking their persisted bytes and metadata."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise VerboisyError("Asset inventory limit must be an integer from 1 to 1000")
    if not database.is_file() or database.is_symlink():
        raise VerboisyError("Choose an existing research database")
    try:
        db = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error:
        raise VerboisyError("Cannot open the research database for inspection") from None
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN")
        versions = db.execute("SELECT version FROM research_meta").fetchall()
        if len(versions) != 1 or versions[0]["version"] != DB_VERSION:
            raise VerboisyError("Asset inspection requires the current ledger version")
        run = db.execute("SELECT status FROM research_runs WHERE id=?", (run_id,)).fetchone()
        if run is None:
            raise VerboisyError("No saved research run found")
        captures = db.execute(
            "SELECT id FROM dataset_assets WHERE run_id=? ORDER BY rowid LIMIT ?",
            (run_id, limit + 1),
        ).fetchall()
        assets = []
        for row in captures[:limit]:
            asset = load_asset(db, run_id, row["id"])
            download = asset.download
            assets.append(
                {
                    "asset_id": asset.id,
                    "acquired_at": asset.acquired_at,
                    "original_url": download.original_url,
                    "final_url": download.final_url,
                    "sha256": download.dataset.sha256,
                    "format": download.dataset.format,
                    "row_count": len(download.dataset.rows),
                    "byte_count": len(download.dataset.original_bytes),
                    "parser_version": download.dataset.parser_version,
                    "support_level": (
                        "capture_and_index"
                        if download.dataset.format == "asset"
                        else "deterministic_parse"
                    ),
                }
            )
        return {
            "inventory_version": "1",
            "run_id": run_id,
            "run_status": run["status"],
            "limit": limit,
            "truncated": len(captures) > limit,
            "assets": assets,
        }
    except sqlite3.Error:
        raise VerboisyError("Not a readable current research ledger") from None
    finally:
        db.close()
