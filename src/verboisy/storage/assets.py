# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Immutable, run-scoped dataset acquisitions in the research SQLite ledger."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from typing import Any

from verboisy.extractor.dataset import DatasetParseError, parse_dataset
from verboisy.extractor.download import DownloadedDataset
from verboisy.utils.exceptions import VerboisyError


class DatasetAssetError(VerboisyError):
    """A persisted acquisition is missing, inconsistent or outside parser limits."""


@dataclass(frozen=True)
class StoredDatasetAsset:
    id: str
    run_id: str
    acquired_at: str
    download: DownloadedDataset


def _metadata(download: DownloadedDataset) -> str:
    value = asdict(download)
    del value["dataset"]["original_bytes"]
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _identifier(rid: str, metadata: str) -> str:
    digest = hashlib.sha256(metadata.encode("utf-8")).hexdigest()
    return uuid.uuid5(uuid.NAMESPACE_URL, f"verboisy:asset:{rid}:{digest}").hex


def _validate(download: DownloadedDataset) -> None:
    try:
        parsed = parse_dataset(download.dataset.original_bytes, download.dataset.format)
        if parsed != download.dataset:
            raise DatasetAssetError("Dataset bytes and parsed rows differ")
        _validate_redirect_metadata(download)
    except DatasetParseError as error:
        raise DatasetAssetError("Dataset asset violates the version 1 parser contract") from error


def _validate_redirect_metadata(download: DownloadedDataset) -> None:
    """Apply the same captured-endpoint invariant during admission and replay."""
    if (
        not download.redirect_chain
        or download.redirect_chain[0] != download.original_url
        or download.redirect_chain[-1] != download.final_url
    ):
        raise DatasetAssetError("Dataset acquisition has inconsistent redirect metadata")


def _replay_download(value: dict[str, Any], content: bytes) -> DownloadedDataset:
    """Parse captured bytes once and reconstruct consistent source metadata."""
    parsed = parse_dataset(content, value["dataset"]["format"])
    download = DownloadedDataset(
        value["original_url"],
        value["final_url"],
        tuple(value["redirect_chain"]),
        value["content_type"],
        value["remote_disposition"],
        parsed,
    )
    _validate_redirect_metadata(download)
    return download


def save_asset(db: sqlite3.Connection, rid: str, download: DownloadedDataset) -> str:
    """Atomically capture bytes, source metadata, row locators and a journal event.

    Repeating the same acquisition in the same run is idempotent. Changed bytes
    or source metadata produce a separate acquisition; neither overwrites history.
    """
    _validate(download)
    metadata = _metadata(download)
    asset_id = _identifier(rid, metadata)
    with db:
        if db.execute("SELECT 1 FROM research_runs WHERE id=?", (rid,)).fetchone() is None:
            raise DatasetAssetError("No research run for dataset asset")
        blob = db.execute(
            "SELECT content FROM dataset_blobs WHERE sha256=?", (download.dataset.sha256,)
        ).fetchone()
        if blob is not None and blob[0] != download.dataset.original_bytes:
            raise DatasetAssetError("Existing dataset bytes failed integrity verification")
        previous = db.execute(
            "SELECT metadata,sha256,run_id FROM dataset_assets WHERE id=?", (asset_id,)
        ).fetchone()
        if previous is not None:
            if (
                previous[0] != metadata
                or previous[1] != download.dataset.sha256
                or previous[2] != rid
                or blob is None
            ):
                raise DatasetAssetError(
                    "Existing dataset acquisition failed integrity verification"
                )
            return asset_id
        db.execute(
            "INSERT OR IGNORE INTO dataset_blobs(sha256,content) VALUES(?,?)",
            (download.dataset.sha256, download.dataset.original_bytes),
        )
        db.execute(
            "INSERT INTO dataset_assets(id,run_id,sha256,metadata) VALUES(?,?,?,?)",
            (asset_id, rid, download.dataset.sha256, metadata),
        )
        db.execute(
            "INSERT INTO events(run_id,kind,payload) VALUES(?,?,?)",
            (
                rid,
                "dataset_asset",
                json.dumps(
                    {
                        "asset_id": asset_id,
                        "sha256": download.dataset.sha256,
                        "format": download.dataset.format,
                        "row_count": len(download.dataset.rows),
                    },
                    sort_keys=True,
                ),
            ),
        )
    return asset_id


def load_asset(db: sqlite3.Connection, rid: str, asset_id: str) -> StoredDatasetAsset:
    """Verify and replay a saved acquisition without fetching or model calls."""
    row = db.execute(
        "SELECT a.metadata,a.sha256,a.acquired_at,b.content FROM dataset_assets a "
        "JOIN dataset_blobs b ON b.sha256=a.sha256 WHERE a.run_id=? AND a.id=?",
        (rid, asset_id),
    ).fetchone()
    if row is None:
        raise DatasetAssetError("No dataset asset in the requested run")
    try:
        metadata, digest, acquired_at, content = row
        if _identifier(rid, metadata) != asset_id:
            raise DatasetAssetError("Dataset acquisition metadata failed integrity verification")
        value: Any = json.loads(metadata)
        download = _replay_download(value, content)
        if download.dataset.sha256 != digest or _metadata(download) != metadata:
            raise DatasetAssetError("Dataset asset failed integrity verification")
    except (DatasetParseError, ValueError, TypeError, KeyError, UnicodeError) as error:
        raise DatasetAssetError("Dataset asset cannot be replayed") from error
    return StoredDatasetAsset(asset_id, rid, acquired_at, download)


def list_assets(db: sqlite3.Connection, rid: str) -> list[StoredDatasetAsset]:
    """Return verified acquisitions in capture order, restricted to this run."""
    rows = db.execute(
        "SELECT id FROM dataset_assets WHERE run_id=? ORDER BY rowid", (rid,)
    ).fetchall()
    return [load_asset(db, rid, row[0]) for row in rows]
