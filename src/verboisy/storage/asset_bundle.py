# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Checksummed portable dataset captures, independent of SQLite and remote sources."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from verboisy.extractor.dataset import DatasetParseError
from verboisy.storage.assets import (
    DatasetAssetError,
    StoredDatasetAsset,
    _identifier,
    _metadata,
    _replay_download,
)
from verboisy.storage.json_payload import decode_saved_json

if TYPE_CHECKING:
    from verboisy.storage.research import ResearchStore


def asset_bundle(store: ResearchStore, rid: str) -> dict[str, Any]:
    """Include all verified captures, including rejected and unselected source rows."""
    return {
        "format_version": 1,
        "run_id": rid,
        "assets": [
            {
                "id": asset.id,
                "acquired_at": asset.acquired_at,
                "metadata": json.loads(_metadata(asset.download)),
                "original_bytes_base64": base64.b64encode(
                    asset.download.dataset.original_bytes
                ).decode("ascii"),
            }
            for asset in store.dataset_assets(rid)
        ],
    }


def load_portable_assets(
    manifest_path: Path, *, max_bundle_bytes: int = 268_435_456
) -> list[StoredDatasetAsset]:
    """Verify the manifest-referenced asset sidecar and replay its version 1 captures.

    This verifies integrity relative to the supplied manifest, not its authenticity
    or factual truth. No database, download, filename extraction or model is used.
    """
    if (
        not isinstance(max_bundle_bytes, int)
        or isinstance(max_bundle_bytes, bool)
        or max_bundle_bytes < 1
    ):
        raise ValueError("Invalid portable bundle byte limit")

    def read(path: Path) -> bytes:
        with path.open("rb") as stream:
            content = stream.read(max_bundle_bytes + 1)
        if len(content) > max_bundle_bytes:
            raise DatasetAssetError("Portable bundle byte limit exceeded")
        return content

    try:
        manifest = decode_saved_json(read(manifest_path))
        name = manifest.get("asset_bundle")
        if name is None:
            return []
        if not isinstance(name, str) or Path(name).name != name or name in ("", ".", ".."):
            raise DatasetAssetError("Unsafe portable asset filename")
        path = manifest_path.parent / name
        if path.is_symlink() or path.resolve().parent != manifest_path.parent.resolve():
            raise DatasetAssetError("Unsafe portable asset path")
        content = read(path)
        if hashlib.sha256(content).hexdigest() != manifest["files"][name]:
            raise DatasetAssetError("Portable asset bundle checksum mismatch")
        value = decode_saved_json(content)
        rid = manifest["run_id"]
        if (
            not isinstance(value["format_version"], int)
            or isinstance(value["format_version"], bool)
            or value["format_version"] != 1
            or value["run_id"] != rid
        ):
            raise DatasetAssetError("Unsupported or mismatched portable asset bundle")
        if not isinstance(value["assets"], list):
            raise DatasetAssetError("Invalid portable asset list")
        result = []
        seen = set()
        for entry in value["assets"]:
            if not isinstance(entry["acquired_at"], str) or not entry["acquired_at"]:
                raise DatasetAssetError("Invalid portable acquisition timestamp")
            metadata = entry["metadata"]
            original = base64.b64decode(entry["original_bytes_base64"], validate=True)
            download = _replay_download(metadata, original)
            encoded = _metadata(download)
            expected = json.dumps(metadata, ensure_ascii=False, sort_keys=True, allow_nan=False)
            if encoded != expected or _identifier(rid, encoded) != entry["id"]:
                raise DatasetAssetError("Portable acquisition metadata mismatch")
            if entry["id"] in seen:
                raise DatasetAssetError("Duplicate portable acquisition")
            seen.add(entry["id"])
            result.append(StoredDatasetAsset(entry["id"], rid, entry["acquired_at"], download))
        return result
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        DatasetParseError,
        binascii.Error,
    ) as error:
        raise DatasetAssetError("Cannot verify portable dataset assets") from error
