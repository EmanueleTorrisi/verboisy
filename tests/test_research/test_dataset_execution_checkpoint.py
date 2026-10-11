# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Dataset runtime failures must save accurate status and model accounting."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from verboisy.core.research import ResearchRunner
from verboisy.evidence.models import TaskSpec
from verboisy.extractor.ingestion import run_dataset_sources
from verboisy.storage.research import ResearchStore

from tests.test_research.test_contracts import SCHEMA


def make_runner(store, rid):
    runner = ResearchRunner.__new__(ResearchRunner)
    runner.store, runner.rid = store, rid
    runner.config = SimpleNamespace(run_timeout_seconds=10)
    runner.client = SimpleNamespace(total_tokens=17, reserved_tokens=123)
    runner.task = TaskSpec.model_validate_json(store.load(rid)["task_json"])
    return runner


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["records", "dataset_assets"])
@pytest.mark.parametrize("error_type", [RuntimeError, OSError])
async def test_unexpected_dataset_read_failure_saves_execution_failure(
    tmp_path, operation, error_type
):
    store = ResearchStore(tmp_path / "run.sqlite3")
    try:
        spec = TaskSpec.model_validate(
            {"dataset_sources": [{"url": "https://data.test/rows.json", "format": "json"}]}
        )
        rid = store.create("Customers", SCHEMA, spec, None)
        runner = make_runner(store, rid)
        failure = error_type("Private failure detail")
        with (
            patch.object(store, operation, side_effect=failure),
            pytest.raises(error_type) as caught,
        ):
            await run_dataset_sources(runner, 1)
        assert caught.value is failure
        state = store.load(rid)
        assert state["status"] == "FAILED"
        assert state["reason"] == f"execution_{error_type.__name__}"
        assert state["tokens"] == 17
        assert state["reserved"] == 123
    finally:
        store.close()


@pytest.mark.asyncio
async def test_dataset_keyboard_interrupt_saves_interrupted_checkpoint_then_propagates(tmp_path):
    store = ResearchStore(tmp_path / "run.sqlite3")
    try:
        spec = TaskSpec.model_validate(
            {"dataset_sources": [{"url": "https://data.test/rows.json", "format": "json"}]}
        )
        rid = store.create("Customers", SCHEMA, spec, None)
        runner = make_runner(store, rid)
        interruption = KeyboardInterrupt()
        with (
            patch.object(store, "dataset_assets", side_effect=interruption),
            pytest.raises(KeyboardInterrupt) as caught,
        ):
            await run_dataset_sources(runner, 1)
        assert caught.value is interruption
        state = store.load(rid)
        assert state["status"] == "PAUSED"
        assert state["reason"] == "interrupted"
        assert state["tokens"] == 17
        assert state["reserved"] == 123
    finally:
        store.close()
