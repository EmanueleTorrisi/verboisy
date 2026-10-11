# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Saved display errors must stop before accepting or declining requirement changes."""

from copy import deepcopy
from unittest.mock import patch

import pytest
from verboisy import arun
from verboisy.evidence.models import TaskSpec
from verboisy.presentation_config import (
    PresentationPreferences,
    resolve_preferences,
    resolve_saved_preferences,
)
from verboisy.storage.changes import propose_change
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError

from tests.test_storage.test_admission_transactions import SCHEMA

CHOICES = {"mass_unit": "kg", "length_unit": "m", "date_format": "dmy"}
DAMAGED = [
    (field, value) for field in CHOICES for value in (None, True, 17, [], {}, "private-invalid")
]


@pytest.mark.parametrize("field,value", DAMAGED)
def test_explicit_override_cannot_mask_invalid_saved_choice(field, value):
    defaults = PresentationPreferences()
    with pytest.raises(VerboisyError, match="Display preferences") as error:
        resolve_preferences(defaults, {field: value}, {field: CHOICES[field]})
    assert "private-invalid" not in str(error.value)


@pytest.mark.parametrize(
    "saved", [None, [], "private-invalid"] + [{field: value} for field, value in DAMAGED]
)
@pytest.mark.parametrize("accept", [False, True])
@pytest.mark.parametrize("override", [False, True])
async def test_display_preflight_preserves_pending_decision_and_budget(
    tmp_path, saved, accept, override
):
    path = tmp_path / "run.db"
    store = ResearchStore(path)
    task = TaskSpec(seed_urls=["https://example.test/"])
    rid = store.create("People", SCHEMA, task, None)
    propose_change(
        store,
        rid,
        {
            "description": "Include ages",
            "goal": "People and ages",
            "schema": SCHEMA,
            "task": task.model_dump(),
        },
    )
    store.event(rid, "presentation_preferences", saved)
    store.finish(rid, "PAUSED", "proposed_changes", 17, 796)
    before = state(store)
    store.close()
    output = tmp_path / "rows.json"
    output.write_bytes(b"existing output")
    with (
        patch("verboisy.api.decide_change", side_effect=AssertionError("decision reached")),
        pytest.raises(VerboisyError, match="Display preferences") as error,
    ):
        await arun(
            resume=False if accept else rid,
            okresume=rid if accept else False,
            config=Settings(_env_file=None, sqlite_db_path=str(path), search_provider="disabled"),
            **(CHOICES if override else {}),
        )
    assert "private-invalid" not in str(error.value)
    store = ResearchStore(path)
    try:
        assert state(store) == before
        assert output.read_bytes() == b"existing output"
    finally:
        store.close()


def state(store):
    return {
        table: [tuple(row) for row in store.db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
        for table in ("research_runs", "events", "pages", "candidates", "records")
    }


@pytest.mark.parametrize(
    "events",
    [
        [],
        [{"payload": {}}],
        [{"payload": {"mass_unit": "kg"}}],
        [{"payload": {"mass_unit": "lb", "date_format": "iso"}}],
    ],
)
@pytest.mark.parametrize("override", [{}, {"mass_unit": "source", "date_format": "mdy"}])
def test_valid_partial_history_keeps_precedence_without_mutation(events, override):
    before = deepcopy(events)
    defaults = PresentationPreferences(mass_unit="lb", length_unit="ft", date_format="iso")
    raw = events[-1]["payload"] if events else {}
    expected = {**defaults.model_dump(), **raw, **override}
    assert resolve_saved_preferences(defaults, events, override).model_dump() == expected
    assert events == before


def test_newest_valid_entry_retains_existing_history_selection():
    events = [{"payload": {"mass_unit": "historical-invalid"}}, {"payload": {"mass_unit": "kg"}}]
    assert resolve_saved_preferences(PresentationPreferences(), events, {}).mass_unit == "kg"
