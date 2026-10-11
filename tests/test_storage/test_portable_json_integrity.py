# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""A checksum must not turn ambiguous portable JSON into trusted capture input."""

import hashlib
import json
from unittest.mock import patch

import pytest
from verboisy.storage.asset_bundle import load_portable_assets
from verboisy.storage.assets import DatasetAssetError
from verboisy.storage.json_payload import decode_saved_json

from tests.test_storage.test_asset_bundle import exported

__all__ = ["exported"]


AMBIGUOUS = [
    '"extra":1,"extra":2',
    '"extra":1,"extra":1',
    '"extra":1,"\\u0065xtra":2',
    '"extra":{"nested":1,"nested":2}',
    '"extra":[{"nested":1,"nested":2}]',
    '"extra":NaN',
    '"extra":Infinity',
    '"extra":-Infinity',
    '"extra":1e9999',
    '"extra":-1e9999',
]


def paths(manifest):
    info = json.loads(manifest.read_bytes())
    return info, manifest.parent / info["asset_bundle"]


def changed_json(raw, fragment):
    # Use raw text: a Python dictionary cannot represent duplicate JSON keys.
    return (raw.decode().rstrip()[:-1] + "," + fragment + "}").encode()


@pytest.mark.parametrize("boundary", ["manifest", "sidecar"])
@pytest.mark.parametrize("fragment", AMBIGUOUS)
def test_ambiguous_json_stops_before_capture_replay(exported, boundary, fragment):
    _, _, manifest = exported
    info, sidecar = paths(manifest)
    target = manifest if boundary == "manifest" else sidecar
    target.write_bytes(changed_json(target.read_bytes(), fragment))
    if boundary == "sidecar":
        info["files"][sidecar.name] = hashlib.sha256(sidecar.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(info), encoding="utf-8")
    before = (manifest.read_bytes(), sidecar.read_bytes())
    with (
        patch(
            "verboisy.storage.asset_bundle._replay_download",
            side_effect=AssertionError("ambiguous JSON reached capture replay"),
        ),
        pytest.raises(DatasetAssetError, match="Cannot verify portable dataset assets"),
    ):
        load_portable_assets(manifest)
    assert (manifest.read_bytes(), sidecar.read_bytes()) == before


@pytest.mark.parametrize("fragment", AMBIGUOUS)
def test_legacy_manifest_without_sidecar_still_checks_json(tmp_path, fragment):
    manifest = tmp_path / "legacy.manifest.json"
    manifest.write_bytes(changed_json(b'{"run_id":"legacy"}', fragment))
    with pytest.raises(DatasetAssetError, match="Cannot verify"):
        load_portable_assets(manifest)


def test_checksum_mismatch_precedes_sidecar_json_validation(exported):
    _, _, manifest = exported
    _, sidecar = paths(manifest)
    sidecar.write_bytes(changed_json(sidecar.read_bytes(), AMBIGUOUS[0]))
    with (
        patch(
            "verboisy.storage.asset_bundle.decode_saved_json", wraps=decode_saved_json
        ) as decoder,
        pytest.raises(DatasetAssetError, match="checksum mismatch"),
    ):
        load_portable_assets(manifest)
    assert decoder.call_count == 1


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "utf-32"])
@pytest.mark.parametrize("boundary", ["manifest", "sidecar"])
def test_valid_historical_json_byte_encodings_remain_supported(exported, encoding, boundary):
    store, rid, manifest = exported
    info, sidecar = paths(manifest)
    expected = store.dataset_assets(rid)
    target = manifest if boundary == "manifest" else sidecar
    target.write_bytes(target.read_text(encoding="utf-8").encode(encoding))
    if boundary == "sidecar":
        info["files"][sidecar.name] = hashlib.sha256(sidecar.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(info), encoding="utf-8")
    before = (manifest.read_bytes(), sidecar.read_bytes())
    assert load_portable_assets(manifest) == expected
    assert (manifest.read_bytes(), sidecar.read_bytes()) == before


@pytest.mark.parametrize("payload", [b'{"text":"Caf\xc3\xa9"}', bytearray(b'{"value":1.5}')])
def test_shared_decoder_accepts_bytes_without_model_coercion(payload):
    assert decode_saved_json(payload) == json.loads(payload)
