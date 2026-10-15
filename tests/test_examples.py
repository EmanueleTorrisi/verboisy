# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Examples exercise real contracts, exclusive generation and captured-source recovery."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def invoke(script, *arguments):
    environment = {**os.environ, "DATASET_LOCAL_ROOTS": "[]"}
    return subprocess.run(
        [sys.executable, str(ROOT / "examples" / script), *map(str, arguments)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        cwd=ROOT,
        timeout=60,
    )


def test_research_preview_uses_real_scoped_sources_without_creating_a_run(tmp_path):
    output = tmp_path / "research"
    result = invoke("research_catalog/research.py", "--output", output)
    assert result.returncode == 0, result.stderr
    task = json.JSONDecoder().raw_decode(result.stdout)[0]
    assert task["target_records"] == 100
    assert len(task["seed_urls"]) >= 2
    assert "www.bnl.gov" in task["allowed_hosts"]
    assert task["identity_fields"] == ["/organization", "/facility_name"]
    assert not output.exists()


def test_research_rejects_seed_credentials_before_execution(tmp_path):
    output = tmp_path / "research"
    result = invoke(
        "research_catalog/research.py",
        "--seed",
        "https://user:secret@example.com/data",
        "--output",
        output,
        "--live",
    )
    assert result.returncode == 2
    assert "without credentials" in result.stderr
    assert not output.exists()


def test_generation_is_distinct_typed_and_refuses_overwrite(tmp_path):
    source = tmp_path / "input.jsonl"
    result = invoke(
        "streaming_observations/generate.py",
        "--output",
        source,
        "--rows",
        30,
        "--metadata-bytes",
        64,
    )
    assert result.returncode == 0, result.stderr
    before = source.read_bytes()
    rows = [json.loads(line) for line in before.splitlines()]
    assert len(rows) == 30
    assert len({row["observation_id"] for row in rows}) == 30
    assert rows[0]["observed_at"] < rows[-1]["observed_at"]
    assert all(row["quality"] == "synthetic" and row["unit"] == "kW" for row in rows)
    report = json.loads(result.stdout)
    assert report["bytes"] == len(before)
    repeated = invoke("streaming_observations/generate.py", "--output", source, "--rows", 2)
    assert repeated.returncode != 0
    assert source.read_bytes() == before


def test_observation_pipeline_resumes_captured_bytes_and_exports_all_rows(tmp_path):
    source = tmp_path / "input.jsonl"
    database = tmp_path / "stream.db"
    output = tmp_path / "output.jsonl"
    generated = invoke(
        "streaming_observations/generate.py",
        "--output",
        source,
        "--rows",
        40,
        "--metadata-bytes",
        16,
    )
    assert generated.returncode == 0, generated.stderr
    expected = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    paused = invoke(
        "streaming_observations/prepare.py",
        "--source",
        source,
        "--database",
        database,
        "--rows-per-invocation",
        17,
    )
    assert paused.returncode == 2, paused.stderr
    first = json.loads(paused.stdout)
    assert first["result"]["status"] == "PAUSED"
    assert first["result"]["processed_rows"] == 17
    assert len(first["first_committed_rows"]) == 5
    source.unlink()
    resumed = invoke(
        "streaming_observations/prepare.py",
        "--database",
        database,
        "--resume",
        first["result"]["job_id"],
        "--export",
        output,
    )
    assert resumed.returncode == 0, resumed.stderr
    final = json.loads(resumed.stdout)
    assert final["result"]["status"] == "COMPLETED"
    assert final["result"]["processed_rows"] == 40
    assert [
        json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()
    ] == expected


def test_catalogue_identity_through_real_grounded_verifier():
    from verboisy.evidence.models import Candidate, Proof, TaskSpec
    from verboisy.evidence.snapshot import snapshot
    from verboisy.evidence.verify import lookup, verify
    from verboisy.research_contract import validate_research_contract

    schema = json.loads((ROOT / "examples/research_catalog/schema.json").read_text())
    task = TaskSpec(identity_fields=["/organization", "/facility_name"])
    validate_research_contract(schema, task)
    page = snapshot("<p>Research organization</p><p>Facility A</p>", "https://example.test/")
    values = {name: None for name in schema["items"]["properties"]}
    values.update(organization="Research organization", facility_name="Facility A")
    sources = {source.text: source.id for source in page.sources}
    candidate = Candidate(
        scope="page",
        record=values,
        evidence={
            pointer: Proof(source=sources[lookup(values, pointer)], quote=lookup(values, pointer))
            for pointer in task.identity_fields
        },
    )
    assert verify(candidate, page, schema, task) == []


def test_prepare_example_reports_missing_source_without_traceback(tmp_path):
    result = invoke(
        "streaming_observations/prepare.py",
        "--database",
        tmp_path / "stream.db",
        "--source",
        tmp_path / "missing.jsonl",
    )
    assert result.returncode == 1 and "Traceback" not in result.stderr
    saved = json.loads(result.stdout)
    assert saved["result"]["status"] == "FAILED"
    assert "missing.jsonl" in saved["result"]["reason"]
    assert saved["first_committed_rows"] == []
