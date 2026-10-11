# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""CLI review uses captured bytes and keeps approval separate from run acceptance."""

import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner
from verboisy.cli.main import app
from verboisy.evidence.models import TaskSpec
from verboisy.extractor.mapping import SchemaMappingError
from verboisy.extractor.review import _aliases, _publish, review_mapping
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError

from tests.test_storage.test_dataset_assets import capture


@pytest.fixture
def saved(tmp_path):
    database = tmp_path / "run.db"
    store = ResearchStore(str(database))
    schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
    rid = store.create("people", schema, TaskSpec(), None)
    aid = store.save_dataset_asset(rid, capture('[{"name":"Anaïs"}]'.encode(), "json"))
    store.close()
    return database, rid, aid


def command(saved, output, *extra):
    db, rid, aid = saved
    return CliRunner().invoke(
        app,
        [
            "map",
            "--database",
            str(db),
            "--run-id",
            rid,
            "--asset-id",
            aid,
            "--output",
            str(output),
            *extra,
        ],
    )


def test_cli_proposal_and_explicit_approval_saved_journal(tmp_path, saved):
    db, rid, aid = saved
    original = db.read_bytes()
    report = tmp_path / "review.json"
    with patch("verboisy.api.run", side_effect=AssertionError("No run")):
        result = command(saved, report)
    assert result.exit_code == 0, result.output
    value = json.loads(report.read_text())
    assert value["decision"] == "proposed" and value["full_row_validation"] == "passed"
    assert value["applied_to_run"] is False
    plan = tmp_path / "plan.json"
    approved = tmp_path / "approved.json"
    result = command(saved, approved, "--plan", str(plan))
    assert result.exit_code == 0, result.output
    assert json.loads(plan.read_text())["fields"][0]["source"] == "/name"
    store = ResearchStore(str(db))
    try:
        assert [e["payload"]["decision"] for e in store.events(rid, "dataset_mapping_review")] == [
            "proposed",
            "approved",
        ]
        assert store.records(rid) == []
        assert store.load(rid)["status"] == "RUNNING"
        assert store.load_dataset_asset(rid, aid).download.dataset.rows[0].values == {
            "name": "Anaïs"
        }
    finally:
        store.close()
    assert db.read_bytes() != original


@pytest.mark.parametrize("approve", [False, True])
def test_unresolved_writes_report_and_journals_blocked_request(tmp_path, saved, approve):
    db, rid, aid = saved
    store = ResearchStore(str(db))
    store.db.execute(
        "UPDATE research_runs SET schema_json=? WHERE id=?",
        (json.dumps({"type": "object", "properties": {"years": {"type": "integer"}}}), rid),
    )
    store.db.commit()
    store.close()
    report = tmp_path / "review.json"
    plan = tmp_path / "plan.json"
    result = command(saved, report, *(["--plan", str(plan)] if approve else []))
    assert result.exit_code == (2 if approve else 0), result.output
    value = json.loads(report.read_text())
    assert value["decision"] == ("blocked" if approve else "proposed")
    assert value["full_row_validation"] == "failed" and value["plan"] is None
    assert not plan.exists()


def test_aliases_are_explicit_and_preserved(tmp_path, saved):
    db, rid, aid = saved
    store = ResearchStore(str(db))
    store.db.execute(
        "UPDATE research_runs SET schema_json=? WHERE id=?",
        (json.dumps({"type": "object", "properties": {"person": {"type": "string"}}}), rid),
    )
    store.db.commit()
    store.close()
    aliases = tmp_path / "aliases.json"
    aliases.write_text('{"/person":["/name"]}')
    value = review_mapping(
        db,
        rid,
        aid,
        tmp_path / "review.json",
        aliases_path=aliases,
        plan_path=tmp_path / "plan.json",
    )
    assert value["aliases"] == {"/person": ["/name"]}
    assert value["decision"] == "approved"


@pytest.mark.parametrize(
    "kind", ["same", "database", "aliases", "existing", "directory", "symlink", "parent"]
)
def test_output_protection(tmp_path, saved, kind):
    db, rid, aid = saved
    output = tmp_path / "review.json"
    plan = None
    aliases = None
    if kind == "same":
        plan = output
    if kind == "database":
        output = db
    if kind == "aliases":
        aliases = output
    if kind == "existing":
        output.write_text("preserve")
    if kind == "directory":
        output.mkdir()
    if kind == "symlink":
        output.symlink_to(tmp_path / "absent")
    if kind == "parent":
        output = tmp_path / "absent" / "review.json"
    with pytest.raises(VerboisyError):
        review_mapping(db, rid, aid, output, aliases_path=aliases, plan_path=plan)
    if kind == "existing":
        assert output.read_text() == "preserve"


@pytest.mark.parametrize("kind", ["absent", "symlink", "directory"])
def test_existing_database_required(tmp_path, kind):
    db = tmp_path / "db"
    if kind == "directory":
        db.mkdir()
    if kind == "symlink":
        db.symlink_to(tmp_path / "absent")
    with pytest.raises(VerboisyError, match="existing"):
        review_mapping(db, "run", "asset", tmp_path / "review.json")


@pytest.mark.parametrize(
    "data", [b'{"a":1,"a":2}', b"[]", b"not json", b'{"/name":"/name"}', b"", b"{},{}"]
)
def test_invalid_aliases_fail_without_report(tmp_path, saved, data):
    aliases = tmp_path / "aliases.json"
    aliases.write_bytes(data)
    result = command(saved, tmp_path / "review.json", "--aliases", str(aliases))
    assert result.exit_code == 1
    assert not (tmp_path / "review.json").exists()


def test_alias_byte_limit(tmp_path):
    aliases = tmp_path / "aliases.json"
    aliases.write_bytes(b" " * (1024 * 1024 + 1))
    with pytest.raises(SchemaMappingError, match="1 MiB"):
        _aliases(aliases)


def test_no_overwrite_at_publication_race(tmp_path):
    output = tmp_path / "review.json"
    output.write_text("preserve")
    with pytest.raises(FileExistsError):
        _publish(output, {})
    assert output.read_text() == "preserve"
    assert list(tmp_path.iterdir()) == [output]


def test_unknown_run_closes_ledger(tmp_path, saved):
    db, _, aid = saved
    with pytest.raises(VerboisyError):
        review_mapping(db, "unknown", aid, tmp_path / "review.json")
    store = ResearchStore(str(db))
    store.close()


@pytest.mark.parametrize("failure", ["report", "plan", "journal"])
def test_publication_failure_cleans_own_files(tmp_path, saved, failure):
    db, rid, aid = saved
    output = tmp_path / "review.json"
    plan = tmp_path / "plan.json"
    original = _publish

    def publish(path, value):
        if path == (output if failure == "report" else plan):
            raise OSError("publication failed")
        original(path, value)

    target = (
        "verboisy.extractor.review._publish"
        if failure != "journal"
        else "verboisy.storage.research.ResearchStore.event"
    )
    with (
        patch(target, side_effect=publish if failure != "journal" else OSError("journal failed")),
        pytest.raises(OSError),
    ):
        review_mapping(db, rid, aid, output, plan_path=plan)
    assert not output.exists() and not plan.exists()
    store = ResearchStore(str(db))
    assert store.events(rid, "dataset_mapping_review") == []
    store.close()


def test_late_unsampled_schema_failure_cannot_approve(tmp_path, saved):
    db, rid, _ = saved
    store = ResearchStore(str(db))
    rows = [{"name": "Anaïs"}] * 1000 + [{"name": 22}]
    aid = store.save_dataset_asset(rid, capture(json.dumps(rows).encode(), "json"))
    store.close()
    output = tmp_path / "review.json"
    report = review_mapping(db, rid, aid, output, plan_path=tmp_path / "plan.json")
    assert report["profile"]["sampled_rows"] == 1000
    assert report["suggestion"]["profile_incomplete"]
    assert report["decision"] == "blocked"
    assert "full-row" in report["validation_reason"]
