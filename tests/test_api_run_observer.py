# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Run observers receive the actual persisted identity before work starts."""

import json

import pytest
from verboisy.api import arun
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError


async def test_observer_receives_persisted_identity_for_new_and_resumed_run(tmp_path):
    source = tmp_path / "input.jsonl"
    source.write_text(json.dumps({"name": "A", "country": "Italy"}) + "\n")
    config = Settings(
        _env_file=None, sqlite_db_path=str(tmp_path / "run.db"), dataset_local_roots=[str(tmp_path)]
    )
    observed = []

    def started(run_id, goal):
        store = ResearchStore(config.sqlite_db_path, read_only=True)
        try:
            state = store.load(run_id)
            observed.append((run_id, goal, state["goal"]))
        finally:
            store.close()

    result = await arun(
        goal="Prepare supplied records",
        schema="[name,country]",
        maxrows=1,
        dataset_sources=[{"format": "jsonl", "url": source.as_uri()}],
        config=config,
        on_started=started,
    )
    assert result.completed and observed == [
        (result.run_id, "Prepare supplied records", "Prepare supplied records")
    ]
    resumed = await arun(resume=result.run_id, config=config, on_started=started)
    assert resumed.run_id == result.run_id and observed[1] == observed[0]


async def test_invalid_request_does_not_emit_a_fictitious_run_id(tmp_path):
    observed = []
    config = Settings(_env_file=None, sqlite_db_path=str(tmp_path / "run.db"))
    with pytest.raises(VerboisyError, match="goal and --schema"):
        await arun(config=config, on_started=lambda *args: observed.append(args))
    assert observed == [] and not (tmp_path / "run.db").exists()
