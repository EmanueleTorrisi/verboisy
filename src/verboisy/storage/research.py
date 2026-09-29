"""Versioned evidence ledger, single writer and atomic record acceptance."""

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

from verboisy.evidence.models import Candidate, Snapshot, TaskSpec
from verboisy.evidence.verify import lookup
from verboisy.utils.exceptions import VerboisyError


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


class ResearchStore:
    def __init__(self, path: str):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(self.path) + ".lock")
        try:
            self.lock.acquire(timeout=0)
        except Timeout:
            raise VerboisyError("Database is in use by another run") from None
        try:
            self.db = sqlite3.connect(self.path)
        except BaseException:
            self.lock.release()
            raise
        self.db.row_factory = sqlite3.Row
        try:
            tables = {
                r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "runs" in tables and "research_runs" not in tables:
                raise VerboisyError(
                    "Legacy database: preserve it and choose a new SQLITE_DB_PATH. Leg"
                    "acy records are unverified."
                )
            if (
                "research_meta" in tables
                and self.db.execute("SELECT version FROM research_meta").fetchone()[0] != 2
            ):
                raise VerboisyError("Unsupported research database version")
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS research_meta(version INTEGER NOT NULL);
                INSERT INTO research_meta SELECT 2 WHERE NOT EXISTS(SELECT 1 FROM research_meta);
                CREATE TABLE IF NOT EXISTS research_runs(id TEXT PRIMARY KEY,goal TEXT,schema_json
                TEXT,
                  task_json TEXT,status TEXT,reason TEXT,tokens INTEGER DEFAULT 0,reserved INTEGER
                DEFAULT 0,export_path TEXT);
                CREATE TABLE IF NOT EXISTS pages(id INTEGER PRIMARY KEY,run_id TEXT REFERENCES
                research_runs(id),
                  url TEXT,parent_url TEXT,depth INTEGER,status TEXT DEFAULT 'queued',reason
                TEXT,UNIQUE(run_id,url));
                CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY,run_id TEXT REFERENCES
                research_runs(id),
                  page_id INTEGER REFERENCES pages(id),payload TEXT,html TEXT,visible_html TEXT);
                CREATE TABLE IF NOT EXISTS candidates(id INTEGER PRIMARY KEY,run_id TEXT
                REFERENCES research_runs(id),
                  snapshot_id TEXT REFERENCES snapshots(id),payload TEXT,reasons TEXT,accepted
                INTEGER);
                CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY,run_id TEXT REFERENCES
                research_runs(id),
                  identity TEXT,payload TEXT,candidate_id INTEGER REFERENCES
                candidates(id),UNIQUE(run_id,identity));
                CREATE TABLE IF NOT EXISTS conflicts(run_id TEXT REFERENCES
                research_runs(id),identity TEXT,PRIMARY KEY(run_id,identity));
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,run_id TEXT REFERENCES
                research_runs(id),
                  kind TEXT,payload TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            """)
            self.db.commit()
        except BaseException:
            self.close()
            raise

    def create(self, goal: str, schema: dict[str, Any], task: TaskSpec, export: str | None) -> str:
        rid = str(uuid.uuid4())
        with self.db:
            self.db.execute(
                (
                    "INSERT INTO research_runs(id,goal,schema_json,task_json,status,ex"
                    "port_path) VALUES(?,?,?,?,?,?)"
                ),
                (rid, goal, encode(schema), task.model_dump_json(), "RUNNING", export),
            )
        return rid

    def load(self, rid: str | None) -> dict[str, Any]:
        rows = (
            self.db.execute("SELECT * FROM research_runs WHERE id=?", (rid,)).fetchall()
            if rid
            else self.db.execute(
                "SELECT * FROM research_runs WHERE status!='COMPLETED' ORDER BY rowid DESC LIMIT 1"
            ).fetchall()
        )
        if len(rows) != 1:
            raise VerboisyError(f"No saved research run found in {self.path}")
        return dict(rows[0])

    def event(self, rid: str, kind: str, value: Any) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO events(run_id,kind,payload) VALUES(?,?,?)", (rid, kind, encode(value))
            )

    def queue(self, rid: str, url: str, depth: int, parent: str | None) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO pages(run_id,url,depth,parent_url) VALUES(?,?,?,?)",
                (rid, url, depth, parent),
            )

    def next_page(self, rid: str) -> dict[str, Any] | None:
        with self.db:
            row = self.db.execute(
                "SELECT * FROM pages WHERE run_id=? AND status='queued' ORDER BY depth,id LIMIT 1",
                (rid,),
            ).fetchone()
            if row is None:
                return None
            self.db.execute("UPDATE pages SET status='active' WHERE id=?", (row["id"],))
            return dict(row)

    def recover(self, rid: str) -> None:
        with self.db:
            self.db.execute(
                (
                    "UPDATE pages SET status='queued',reason=NULL WHERE run_id=? AND s"
                    "tatus IN ('active','failed')"
                ),
                (rid,),
            )

    def mark_page(self, pid: int, status: str, reason: str | None = None) -> None:
        with self.db:
            self.db.execute("UPDATE pages SET status=?,reason=? WHERE id=?", (status, reason, pid))

    def snapshot(
        self, rid: str, pid: int, page: Snapshot, html: str, visible_html: str | None = None
    ) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO snapshots VALUES(?,?,?,?,?,?)",
                (page.id, rid, pid, page.model_dump_json(), html, visible_html or html),
            )

    def accept(
        self, rid: str, page: Snapshot, candidate: Candidate, reasons: list[str], task: TaskSpec
    ) -> str:
        payload = encode(candidate.record)
        identity = (
            encode([lookup(candidate.record, p) for p in task.identity_fields])
            if task.identity_fields and not reasons
            else payload
        )
        key = hashlib.sha256(identity.encode()).hexdigest()
        with self.db:
            previous = self.db.execute(
                "SELECT payload FROM records WHERE run_id=? AND identity=?", (rid, key)
            ).fetchone()
            blocked = self.db.execute(
                "SELECT 1 FROM conflicts WHERE run_id=? AND identity=?", (rid, key)
            ).fetchone()
            if not reasons and blocked:
                reasons = ["identity_conflict"]
            if not reasons and previous and previous[0] != payload:
                self.db.execute("INSERT OR IGNORE INTO conflicts VALUES(?,?)", (rid, key))
                self.db.execute(
                    (
                        "UPDATE candidates SET accepted=0,reasons=? WHERE id IN (SELECT ca"
                        "ndidate_id FROM records WHERE run_id=? AND identity=?)"
                    ),
                    (encode(["identity_conflict"]), rid, key),
                )
                self.db.execute("DELETE FROM records WHERE run_id=? AND identity=?", (rid, key))
                reasons = ["identity_conflict"]
            cur = self.db.execute(
                (
                    "INSERT INTO candidates(run_id,snapshot_id,payload,reasons,accepte"
                    "d) VALUES(?,?,?,?,?)"
                ),
                (rid, page.id, candidate.model_dump_json(), encode(reasons), int(not reasons)),
            )
            if reasons:
                return "rejected"
            self.db.execute(
                "INSERT OR IGNORE INTO records(run_id,identity,payload,candidate_id) "
                "VALUES(?,?,?,?)",
                (rid, key, payload, cur.lastrowid),
            )
            return "duplicate" if previous else "accepted"

    def records(self, rid: str) -> list[dict[str, Any]]:
        return [
            json.loads(r[0])
            for r in self.db.execute(
                "SELECT payload FROM records WHERE run_id=? ORDER BY id", (rid,)
            )
        ]

    def finish(self, rid: str, status: str, reason: str, tokens: int, reserved: int) -> None:
        with self.db:
            self.db.execute(
                "UPDATE research_runs SET status=?,reason=?,tokens=?,reserved=? WHERE id=?",
                (status, reason, tokens, reserved, rid),
            )

    def evidence(self, rid: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            (
                "SELECT c.payload,s.payload AS snapshot FROM records r JOIN candid"
                "ates c ON r.candidate_id=c.id JOIN snapshots s ON c.snapshot_id=s"
                ".id WHERE r.run_id=? ORDER BY r.id"
            ),
            (rid,),
        ).fetchall()
        return [
            {
                "row_index": i,
                "candidate": json.loads(r["payload"]),
                "snapshot": json.loads(r["snapshot"]),
            }
            for i, r in enumerate(rows)
        ]

    def summary(self, rid: str) -> dict[str, Any]:
        pages = {
            r[0]: r[1]
            for r in self.db.execute(
                "SELECT status,COUNT(*) FROM pages WHERE run_id=? GROUP BY status", (rid,)
            )
        }
        rejected = self.db.execute(
            "SELECT COUNT(*) FROM candidates WHERE run_id=? AND accepted=0", (rid,)
        ).fetchone()[0]
        gaps = self.db.execute(
            "SELECT COUNT(*) FROM events WHERE run_id=? AND kind='coverage_gap'", (rid,)
        ).fetchone()[0]
        conflicts = self.db.execute(
            "SELECT COUNT(*) FROM conflicts WHERE run_id=?", (rid,)
        ).fetchone()[0]
        return {
            "pages": pages,
            "rejected_candidates": rejected,
            "coverage_gaps": gaps,
            "identity_conflicts": conflicts,
        }

    def close(self) -> None:
        self.db.close()
        self.lock.release()
