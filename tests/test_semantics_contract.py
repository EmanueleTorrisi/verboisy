# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Saved decisions remain effective when optional policy fields are introduced."""

import copy
import json

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.extractor.range_changes import offer_range_change
from verboisy.extractor.research_changes import offer_research_change
from verboisy.storage.changes import decide_change

from tests.test_extractor.test_range_changes import conflict, page
from tests.test_extractor.test_range_changes import ledger as ledger
from tests.test_extractor.test_research_changes import suggestion

__all__ = ["ledger"]


@pytest.mark.parametrize("kind", ["range", "research"])
def test_historical_decline_does_not_reappear(ledger, monkeypatch, kind):
    store, rid = ledger

    def offer():
        return (
            offer_range_change(store, rid, page(), [conflict()])
            if kind == "range"
            else offer_research_change(store, rid, page("City restrictions"), [suggestion()])
        )

    change = offer()
    assert change is not None
    decide_change(store, rid, accept=False)
    original = store.events

    def legacy_events(*args, **kwargs):
        events = copy.deepcopy(original(*args, **kwargs))
        for event in events:
            if event["kind"] == "change_proposed":
                event["payload"]["request"]["task"].pop("time_series", None)
        return events

    monkeypatch.setattr(store, "events", legacy_events)
    assert offer() is None


@pytest.mark.parametrize("kind", ["range", "research"])
@pytest.mark.parametrize("protected", [True, False])
def test_automatic_offer_cannot_remove_series_contract(ledger, kind, protected):
    store, rid = ledger
    task = TaskSpec(
        time_series={
            "timestamp_field": "weight" if protected else "name",
            "timestamp_kind": "date",
        },
    )
    store.db.execute(
        "UPDATE research_runs SET task_json=? WHERE id=?", (task.model_dump_json(), rid)
    )
    store.db.commit()
    if kind == "range":
        assert (offer_range_change(store, rid, page(), [conflict()]) is None) is protected
    else:
        assert (
            offer_research_change(store, rid, page("City restrictions"), [suggestion()]) is None
        ) is protected
    assert json.loads(store.load(rid)["task_json"])["time_series"] == task.time_series.model_dump()
