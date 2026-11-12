# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Exercise declared table acceptance through the real run, ledger and export APIs."""

import csv
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from verboisy import api
from verboisy.core import research
from verboisy.evidence.models import Candidate, Snapshot, TaskSpec
from verboisy.evidence.verify import verify
from verboisy.llm import client
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError

SEED = "https://example.test/measurements"
OUTSIDE = "https://example.test/unlisted"
HTML = (
    '<html><body><table class="samples"><thead><tr><th>Key</th><th>Count</th></tr></thead>'
    "<tbody><tr><td>south</td><td>18</td></tr><tr><td>north</td><td>21</td></tr>"
    "</tbody></table></body></html>"
)
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"key": {"type": "string"}, "count": {"type": "integer", "minimum": 0}},
    "required": ["key", "count"],
}
TASK = TaskSpec.model_validate(
    {
        "seed_urls": [SEED],
        "identity_fields": ["/key"],
        "target_records": 2,
        "max_pages": 1,
        "settle_ms": 0,
        "html_table": {
            "selector": "table.samples",
            "fields": {
                "key": {"header": "Key"},
                "count": {"header": "Count", "value_type": "integer"},
            },
            "key_field": "key",
            "keys": ["north", "south"],
        },
    }
)


class TestHtmlTableRun(IsolatedAsyncioTestCase):
    async def test_exact_table_completes_and_replays_typed_exports(self):
        await self.run_case(HTML, SEED)

    async def test_missing_key_is_not_partial_success(self):
        await self.run_case(
            HTML.replace("<td>north</td>", "<td>west</td>"), SEED, "html_table_layout"
        )

    async def test_schema_failure_is_not_partial_success(self):
        await self.run_case(HTML.replace("<td>21</td>", "<td>-21</td>"), SEED, "html_table_schema")

    async def test_unlisted_redirect_is_not_admitted(self):
        await self.run_case(HTML, OUTSIDE, "navigation_failed")

    async def test_collection_schema_is_checked_before_admission(self):
        schema = {
            "type": "array",
            "items": SCHEMA,
            "contains": {"properties": {"count": {"minimum": 25}}},
        }
        await self.run_case(HTML, SEED, "html_table_schema", schema=schema)

    async def test_altered_saved_cells_and_proofs_cannot_be_replayed(self):
        await self.run_case(HTML, SEED, tamper=True)

    async def run_case(self, document, location, failure=None, *, schema=SCHEMA, tamper=False):
        seen = []

        class Browser:
            def __init__(self, **_kwargs):
                self.navigation_scope = None

            async def start(self):
                return self

            async def navigate_to(self, url):
                assert self.navigation_scope(url)
                assert not self.navigation_scope(OUTSIDE)
                seen.append(url)

            async def get_page(self):
                return self

            async def evaluate(self, _script, _limit):
                return {
                    "url": location,
                    "html": document,
                    "visible_html": document,
                    "oversized": False,
                }

            async def close(self):
                pass

        blocked = AsyncMock(side_effect=AssertionError("A literal table must not use a provider"))
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(research, "BrowserManager", Browser),
            patch.object(client, "_complete", blocked),
            patch.object(api, "web_search", blocked),
            patch.object(research, "web_search", blocked),
        ):
            root = Path(directory)
            config = Settings(
                _env_file=None, sqlite_db_path=str(root / "run.db"), action_delay_seconds=0
            )
            result = await api.arun(
                goal=f"Read the declared measurements; ignore {OUTSIDE}",
                schema=schema,
                task=TASK,
                config=config,
                include=["example.test"],
                max_steps=1,
                export=[root / "data.json", root / "data.csv"] if failure is None else None,
                proof=failure is None,
            )
            blocked.assert_not_called()
            assert seen == [SEED]
            assert result.completed is (failure is None), (result.status, result.stop_reason)
            with closing(ResearchStore(str(result.db_path), read_only=True)) as store:
                state = store.load(result.run_id)
                assert state["tokens"] == state["reserved"] == 0
                assert not store.events(result.run_id, "search_request")
                assert not store.events(result.run_id, "extraction_proposal")
                evidence = store.evidence(result.run_id)
                if failure is not None:
                    assert result.records == [] and evidence == []
                    event = "page_failure" if failure == "navigation_failed" else "coverage_gap"
                    reasons = {
                        entry["payload"]["reason"] for entry in store.events(result.run_id, event)
                    }
                    assert failure in reasons
                    return
                assert len(evidence) == 2
                assert len({entry["snapshot"]["id"] for entry in evidence}) == 1
                for entry in evidence:
                    candidate = Candidate.model_validate(entry["candidate"])
                    snapshot = Snapshot.model_validate(entry["snapshot"])
                    assert len(candidate.evidence) == 2
                    assert verify(candidate, snapshot, schema, TASK) == []
            expected = [{"key": "north", "count": 21}, {"key": "south", "count": 18}]
            rows = json.loads((root / "data.json").read_text(encoding="utf-8"))
            assert (
                sorted(
                    ({k: v for k, v in row.items() if k != "id"} for row in rows),
                    key=lambda row: row["key"],
                )
                == expected
            )
            with (root / "data.csv").open(encoding="utf-8", newline="") as stream:
                csv_rows = [
                    {key: json.loads(value) for key, value in row.items()}
                    for row in csv.DictReader(stream)
                ]
            assert json.dumps(csv_rows, sort_keys=True) == json.dumps(rows, sort_keys=True)
            if tamper:
                self.reject_tampered_rows(result.db_path, result.run_id)

    def reject_tampered_rows(self, path, run_id):
        with closing(sqlite3.connect(path)) as db, db:
            candidate_id, payload = db.execute(
                "SELECT id,payload FROM candidates WHERE run_id=? ORDER BY id LIMIT 1", (run_id,)
            ).fetchone()
            candidate = json.loads(payload)
            candidate["evidence"]["/count"]["quote"] = "999"
            db.execute(
                "UPDATE candidates SET payload=? WHERE id=?", (json.dumps(candidate), candidate_id)
            )
        with (
            closing(ResearchStore(str(path), read_only=True)) as store,
            self.assertRaisesRegex(VerboisyError, "candidate differs from its bound row"),
        ):
            store.evidence(run_id)

        with closing(sqlite3.connect(path)) as db, db:
            db.execute("UPDATE candidates SET payload=? WHERE id=?", (payload, candidate_id))
            snapshot_id, saved = db.execute(
                "SELECT id,payload FROM snapshots WHERE run_id=?", (run_id,)
            ).fetchone()
            snapshot = json.loads(saved)
            snapshot["sources"][0]["text"] = "999"
            db.execute(
                "UPDATE snapshots SET payload=? WHERE id=?", (json.dumps(snapshot), snapshot_id)
            )
        with (
            closing(ResearchStore(str(path), read_only=True)) as store,
            self.assertRaisesRegex(VerboisyError, "snapshot failed binding verification"),
        ):
            store.evidence(run_id)
