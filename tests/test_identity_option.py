# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Explicit identity declarations for the public API and command line."""

import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner
from verboisy.api import _declared_identity, arun
from verboisy.cli.main import app
from verboisy.core.research import ResearchRunner
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError

SCHEMA = {
    "type": "object",
    "properties": {
        "namespace": {"type": "string"},
        "sku": {"type": "string"},
        "a/b": {"type": "string"},
        "a~b": {"type": "string"},
        "nested": {"type": "object", "properties": {"code": {"type": "string"}}},
        "values": {"type": "array", "items": {"type": "string"}},
    },
}


@pytest.mark.parametrize("schema", [SCHEMA, {"type": "array", "items": SCHEMA}])
@pytest.mark.parametrize(
    "identity", [["/sku"], ["/namespace", "/sku"], ["/a~1b"], ["/a~0b"], ["/nested/code"]]
)
def test_declared_identity_preserves_explicit_pointers(schema, identity):
    assert _declared_identity(identity, schema) == identity


@pytest.mark.parametrize(
    "identity",
    [
        [],
        "/sku",
        b"/sku",
        ["/sku"] * 21,
        ["/sku", "/sku"],
        ["sku"],
        ["/missing"],
        ["/nested"],
        ["/values/*"],
        [42],
    ],
)
def test_invalid_identity_is_rejected(identity):
    with pytest.raises(VerboisyError):
        _declared_identity(identity, SCHEMA)


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [[], ["/namespace", "/sku"]])
async def test_api_persists_identity_and_resume_uses_saved_keys(tmp_path, monkeypatch, existing):
    seen = []

    async def no_network(self, max_steps):
        seen.append(self.task.identity_fields)
        self.store.finish(self.rid, "PAUSED", "page_budget", 0, 0)
        return "PAUSED", "page_budget"

    monkeypatch.setattr(ResearchRunner, "run", no_network)
    config = Settings(
        _env_file=None, sqlite_db_path=str(tmp_path / "identity.db"), search_provider="disabled"
    )
    first = await arun(
        goal="Fixture inventory",
        schema=SCHEMA,
        identity=["/namespace", "/sku"],
        task={"seed_urls": ["https://example.test/"], "identity_fields": existing},
        config=config,
    )
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert json.loads(store.load(first.run_id)["task_json"])["identity_fields"] == [
            "/namespace",
            "/sku",
        ]
    finally:
        store.close()
    second = await arun(resume=first.run_id, config=config)
    assert first.run_id == second.run_id
    assert seen == [["/namespace", "/sku"], ["/namespace", "/sku"]]
    with pytest.raises(VerboisyError, match="Resume uses its saved"):
        await arun(resume=first.run_id, config=config, identity=["/sku"])


@pytest.mark.asyncio
async def test_conflicting_task_identity_is_rejected(tmp_path):
    config = Settings(
        _env_file=None, sqlite_db_path=str(tmp_path / "identity.db"), search_provider="disabled"
    )
    with pytest.raises(VerboisyError, match="Identity conflicts"):
        await arun(
            goal="Fixture",
            schema=SCHEMA,
            identity=["/sku"],
            task={"identity_fields": ["/namespace"]},
            config=config,
        )


def test_cli_forwards_compound_identity(monkeypatch, tmp_path):
    import importlib

    cli = importlib.import_module("verboisy.cli.main")
    captured = {}

    def run(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            run_id="fixture",
            notices=(),
            status="COMPLETED",
            records=[],
            completed=True,
            export_paths=(),
            manifest_paths=(),
            proof_path=None,
        )

    monkeypatch.setattr(cli, "run", run)
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "run",
            "--goal",
            "Fixture",
            "--schema",
            "[namespace,sku]",
            "--identity",
            "/namespace",
            "--identity",
            "/sku",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["identity"] == ["/namespace", "/sku"]
    assert "--identity" in CliRunner().invoke(app, ["run", "--help"]).output
