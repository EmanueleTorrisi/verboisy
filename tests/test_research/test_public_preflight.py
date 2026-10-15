# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Resolved invalid public options cannot open a ledger or call providers."""

from unittest.mock import Mock

import pytest
from verboisy.api import arun
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError


@pytest.mark.parametrize(
    "kwargs",
    [{"maxrows": v} for v in [0, -1, 100001, 1.5, True, "2"]]
    + [
        {"headless": "yes"},
        {"proof": True},
        {"order": [{}]},
        {"order": [(None, "asc")]},
        {"strings": 1},
        {"task": {"identity_fields": ["n"]}},
        {"task": {"identity_fields": ["/n", "/n"]}},
        {"task": {"identity_fields": ["/bad~2"]}},
        {"task": {"identity_fields": ["/missing"]}},
    ],
)
async def test_invalid_public_options_have_no_state(tmp_path, monkeypatch, kwargs):
    spy = Mock(side_effect=AssertionError("store opened"))
    monkeypatch.setattr("verboisy.api.ResearchStore", spy)
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}}
    with pytest.raises(VerboisyError):
        await arun(
            goal="Synthetic",
            schema=schema,
            config=Settings(_env_file=None, sqlite_db_path=str(tmp_path / "run.db")),
            **kwargs,
        )
    spy.assert_not_called()
    assert not (tmp_path / "run.db").exists()


@pytest.mark.parametrize(
    "policy",
    [
        {"x-verboisy-temporal-class": "typo"},
        {"x-verboisy-reference-period": "typo"},
        {"x-verboisy-unit-sensitive": "true"},
    ],
)
async def test_invalid_explicit_policies_before_state(tmp_path, monkeypatch, policy):
    spy = Mock(side_effect=AssertionError("store"))
    monkeypatch.setattr("verboisy.api.ResearchStore", spy)
    schema = {"type": "object", "properties": {"n": {"type": "integer", **policy}}}
    with pytest.raises(VerboisyError):
        await arun(
            goal="Synthetic",
            schema=schema,
            config=Settings(_env_file=None, sqlite_db_path=str(tmp_path / "run.db")),
        )
    spy.assert_not_called()


def test_complete_task_revalidation_rejects_model_copy_bypass():
    from verboisy.evidence.models import TaskSpec
    from verboisy.research_contract import validate_research_contract

    task = TaskSpec().model_copy(update={"max_depth": -1})
    with pytest.raises(VerboisyError):
        validate_research_contract({"type": "object"}, task)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"order": 1},
        {"groupby": "missing"},
        {"task": {"target_records": True}},
        {"onlyinclude": None},
    ],
)
async def test_early_shape_errors_before_store(tmp_path, monkeypatch, kwargs):
    spy = Mock(side_effect=AssertionError("store"))
    monkeypatch.setattr("verboisy.api.ResearchStore", spy)
    with pytest.raises(VerboisyError):
        await arun(
            goal="Synthetic",
            schema={"type": "object", "additionalProperties": False},
            config=Settings(_env_file=None, sqlite_db_path=str(tmp_path / "run.db")),
            **kwargs,
        )
    spy.assert_not_called()


async def test_override_host_ceiling_is_revalidated_before_state(tmp_path, monkeypatch):
    spy = Mock(side_effect=AssertionError("store"))
    monkeypatch.setattr("verboisy.api.ResearchStore", spy)
    with pytest.raises(VerboisyError, match="resolved task"):
        await arun(
            goal="Synthetic",
            schema={"type": "object"},
            onlyinclude=True,
            include=[f"host{i}.example" for i in range(101)],
            config=Settings(_env_file=None, sqlite_db_path=str(tmp_path / "run.db")),
        )
    spy.assert_not_called()


async def test_misspelled_policy_is_not_a_permissive_default(tmp_path, monkeypatch):
    spy = Mock(side_effect=AssertionError("store"))
    monkeypatch.setattr("verboisy.api.ResearchStore", spy)
    schema = {
        "type": "object",
        "properties": {"n": {"type": "integer", "x-verboisy-reference-perod": "required"}},
    }
    with pytest.raises(VerboisyError, match="Unknown explicit"):
        await arun(
            goal="Synthetic",
            schema=schema,
            config=Settings(_env_file=None, sqlite_db_path=str(tmp_path / "run.db")),
        )
    spy.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("task_json", '{"max_pages":"private-invalid"}'),
        ("schema_json", '{"type":"array","items":false}'),
    ],
)
async def test_invalid_saved_requirements_fail_before_decisions(
    tmp_path, monkeypatch, field, value
):
    from verboisy.evidence.models import TaskSpec
    from verboisy.storage.research import ResearchStore

    store = ResearchStore(tmp_path / "run.db")
    rid = store.create("Synthetic", {"type": "object"}, TaskSpec(), None)
    with store.db:
        store.db.execute(f"UPDATE research_runs SET {field}=?", (value,))
    store.close()
    decision = Mock(side_effect=AssertionError("decision"))
    monkeypatch.setattr("verboisy.api.decide_change", decision)
    with pytest.raises(VerboisyError) as error:
        await arun(
            resume=rid, config=Settings(_env_file=None, sqlite_db_path=str(tmp_path / "run.db"))
        )
    assert "private-invalid" not in str(error.value)
    decision.assert_not_called()
