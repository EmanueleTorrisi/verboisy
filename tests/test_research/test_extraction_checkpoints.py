# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Saved model work is revalidated, bound to a run, and replayed without spending."""

import asyncio
import hashlib
import json
from contextlib import closing
from unittest.mock import AsyncMock

import pytest
from verboisy.evidence.models import PageProposal, Review, TaskSpec
from verboisy.extractor.extraction_journal import ExtractionJournal
from verboisy.llm.client import LLMClient
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError


def make_run(store):
    return store.create("List inspection dates", {"type": "object"}, TaskSpec(), None)


async def test_checkpoint_changes_when_request_run_or_provider_contract_changes(tmp_path):
    same_response = PageProposal(candidates=[])
    transport = AsyncMock(return_value=same_response)
    database = str(tmp_path / "research.db")
    cfg = Settings(_env_file=None, openai_api_key="private-test-credential")
    with closing(ResearchStore(database)) as store:
        first = make_run(store)
        second = make_run(store)
        journal = ExtractionJournal(store, first, LLMClient(config=cfg))
        await journal.complete("proposal", "instructions", "original", PageProposal, transport)
        with pytest.raises(asyncio.CancelledError):
            await journal.complete(
                "proposal",
                "instructions",
                "unfinished",
                PageProposal,
                AsyncMock(side_effect=asyncio.CancelledError),
            )
        assert transport.await_count == 1

    with closing(ResearchStore(database)) as store:
        # Reopen the ledger: the first result is available after process interruption.
        journal = ExtractionJournal(store, first, LLMClient(config=cfg))
        assert (
            await journal.complete("proposal", "instructions", "original", PageProposal, transport)
            == same_response
        )
        assert transport.await_count == 1
        await journal.complete("proposal", "instructions", "unfinished", PageProposal, transport)
        await journal.complete("proposal", "revised", "original", PageProposal, transport)
        other_run = ExtractionJournal(store, second, LLMClient(config=cfg))
        await other_run.complete("proposal", "instructions", "original", PageProposal, transport)
        changed_cfg = cfg.model_copy(
            update={
                "litellm_api_base": "https://gateway.example.test",
                "llm_send_temperature": False,
            }
        )
        changed = ExtractionJournal(store, first, LLMClient(config=changed_cfg))
        await changed.complete("proposal", "instructions", "original", PageProposal, transport)
        assert transport.await_count == 5
        persisted = json.dumps(store.events(first) + store.events(second))
        assert "private-test-credential" not in persisted
        assert "gateway.example.test" not in persisted


@pytest.mark.parametrize(
    "alteration",
    [
        "duplicate",
        None,
        {"unexpected": "field"},
        {"result": {"relevant": False}, "sha256": "invalid"},
        {"result": '{"relevant": false}', "sha256": "invalid"},
        {
            "result": '{"relevant": false}',
            "sha256": hashlib.sha256(b'{"relevant": false}').hexdigest(),
        },
    ],
)
async def test_corrupt_checkpoint_stops_without_a_provider_call(tmp_path, alteration):
    with closing(ResearchStore(str(tmp_path / "research.db"))) as store:
        rid = make_run(store)
        cfg = Settings(_env_file=None)
        journal = ExtractionJournal(store, rid, LLMClient(config=cfg))
        response = Review(relevant=True, same_entity=True, supported_fields=[], rejected_fields=[])
        transport = AsyncMock(return_value=response)
        await journal.complete("review", "requirements", "observations", Review, transport)
        entry = store.events(rid)[0]
        if alteration == "duplicate":
            store.event(rid, entry["kind"], entry["payload"])
        else:
            store.db.execute(
                "UPDATE events SET payload=? WHERE run_id=?", (json.dumps(alteration), rid)
            )
        with pytest.raises(VerboisyError, match="checkpoint failed integrity"):
            await journal.complete("review", "requirements", "observations", Review, transport)
        assert transport.await_count == 1
