# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""CLI-to-SQLite identity integration with controlled pages and proposals."""

import importlib
import json

import pytest
from typer.testing import CliRunner
from verboisy.core.fitness import build_field_semantics
from verboisy.core.research import ResearchRunner
from verboisy.evidence.models import Candidate, PageProposal, Proof
from verboisy.evidence.verify import verify
from verboisy.extractor.evidenced import EvidenceExtractor
from verboisy.storage.research import ResearchStore

from tests.test_research.test_contracts import PAGES


@pytest.mark.parametrize("missing_key", [False, True])
def test_cli_compound_identity_deduplicates_without_merging_names(
    config, world, monkeypatch, tmp_path, missing_key
):
    cli = importlib.import_module("verboisy.cli.main")
    seeds = [f"https://people.test/{suffix}" for suffix in ("a", "b", "c")]
    for url, namespace in zip(seeds, ("north", "north", "south"), strict=True):
        monkeypatch.setitem(PAGES, url, f"<p>{namespace}</p><p>SKU-7</p><p>Shared name</p>")

    async def discover(*args):
        return seeds, []

    async def semantics(self):
        self.field_semantics = build_field_semantics(self.schema)
        self.extractor.field_semantics = self.field_semantics
        self.semantic_plan_ready = True

    async def propose(self, page, sources):
        namespace = "south" if page.url.endswith("/c") else "north"
        by_text = {source.text: source for source in sources}
        record = {"namespace": namespace, "sku": "SKU-7", "name": "Shared name"}
        if missing_key and namespace == "south":
            record["sku"] = None
        return PageProposal(
            candidates=[
                Candidate(
                    scope="page",
                    record=record,
                    evidence={
                        f"/{key}": Proof(source=by_text[value].id, quote=value)
                        for key, value in record.items()
                        if value is not None
                    },
                )
            ],
            priority_links=[],
        )

    async def check(self, candidate, page):
        return verify(candidate, page, self.schema, self.task)

    monkeypatch.setattr(cli, "Settings", lambda: config)
    monkeypatch.setattr("verboisy.api._discover_seeds", discover)
    monkeypatch.setattr(ResearchRunner, "ensure_field_semantics", semantics)
    monkeypatch.setattr(EvidenceExtractor, "propose", propose)
    monkeypatch.setattr(EvidenceExtractor, "check", check)
    output = tmp_path / "identity.json"
    result = CliRunner().invoke(
        cli.app,
        [
            "run",
            "--goal",
            "Collect two distinct inventory entities",
            "--schema",
            "[namespace,sku,name]",
            "--identity",
            "/namespace",
            "--identity",
            "/sku",
            "--maxrows",
            "2",
            "--max-steps",
            "3",
            "--export",
            str(output),
        ],
    )
    assert result.exit_code == (2 if missing_key else 0), result.output
    manifest = json.loads(output.with_name(output.name + ".manifest.json").read_text())
    rid = manifest["run_id"]
    assert manifest["task"]["identity_fields"] == ["/namespace", "/sku"]
    rows = json.loads(output.read_text())
    assert len(rows) == (1 if missing_key else 2)
    assert {row["name"] for row in rows} == {"Shared name"}
    assert {row["namespace"] for row in rows} == ({"north"} if missing_key else {"north", "south"})
    assert manifest["pages"] == {"done": 3}
    store = ResearchStore(config.sqlite_db_path)
    try:
        before = store.records(rid)
        evidence = store.evidence(rid)
        assert store.summary(rid)["identity_conflicts"] == 0
        assert (
            store.db.execute("SELECT COUNT(*) FROM candidates WHERE run_id=?", (rid,)).fetchone()[0]
            == 3
        )
        if missing_key:
            rejected = store.db.execute(
                "SELECT reasons FROM candidates WHERE run_id=? AND accepted=0", (rid,)
            ).fetchall()
            assert any("/sku:invalid_identity" in row["reasons"] for row in rejected)
    finally:
        store.close()
    reopened = ResearchStore(config.sqlite_db_path)
    try:
        assert reopened.records(rid) == before
        assert reopened.evidence(rid) == evidence
    finally:
        reopened.close()
