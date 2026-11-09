# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Read-only workflow envelopes, exact pins and typed source bindings."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from verboisy.workflows import (
    WorkflowError,
    parse_bindings,
    read_workflow,
    saved_workflow_origin,
)


class WorkflowDefinitionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = self.root / "catalog.json"
        self.base = {
            "version": "1",
            "name": "catalog",
            "revision": 2,
            "goal": "Prepare the supplied catalog.",
            "schema": ["name", "price"],
        }

    def write(self, **changes):
        self.path.write_bytes(json.dumps({**self.base, **changes}).encode())
        return self.path

    def test_reads_exact_fingerprint_and_rebinds_without_mutating_definition(self):
        self.write(
            task={
                "dataset_sources": [
                    {"url": "input:catalog", "format": "jsonl"},
                    {"url": "https://example.test/public.csv?year=2026", "format": "csv"},
                ],
                "target_records": 5,
            }
        )
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        recipe = read_workflow(self.path, expected_sha256=digest)
        self.assertEqual(
            recipe.origin(),
            {
                "version": "1",
                "name": "catalog",
                "revision": 2,
                "sha256": digest,
            },
        )
        self.assertEqual(recipe.inputs, ("catalog",))
        first = self.root / "before=original.jsonl"
        second = self.root / "after.jsonl"
        for path in (first, second):
            task, bound = recipe.bind({"catalog": path})
            self.assertEqual(bound, (path,))
            self.assertEqual(task["dataset_sources"][0]["url"], path.as_uri())
            self.assertEqual(
                task["dataset_sources"][1]["url"], recipe.task["dataset_sources"][1]["url"]
            )
            self.assertEqual(task["target_records"], 5)
            self.assertFalse(path.exists())
        self.assertEqual(recipe.task["dataset_sources"][0]["url"], "input:catalog")

    def test_byte_pin_does_not_accept_an_edited_revision_file(self):
        self.write()
        before = read_workflow(self.path)
        self.path.write_bytes(self.path.read_bytes() + b"\n")
        after = read_workflow(self.path)
        self.assertEqual(before.revision, after.revision)
        self.assertNotEqual(before.sha256, after.sha256)
        with self.assertRaisesRegex(WorkflowError, "differs"):
            read_workflow(self.path, expected_sha256=before.sha256)
        for bad in ("A" * 64, "b" * 63, 12):
            with self.subTest(bad=bad), self.assertRaisesRegex(WorkflowError, "lowercase"):
                read_workflow(self.path, expected_sha256=bad)

    def test_refuses_malformed_or_unbounded_files(self):
        with self.assertRaisesRegex(WorkflowError, "Cannot read"):
            read_workflow(self.path)
        for raw in (b'{"version":"1","version":"1"}', b"{", b"\xff", b"NaN"):
            self.path.write_bytes(raw)
            with self.subTest(raw=raw), self.assertRaisesRegex(WorkflowError, "UTF-8 JSON"):
                read_workflow(self.path)
        self.path.write_bytes(b" " * 1_048_577)
        with self.assertRaisesRegex(WorkflowError, "1 MiB"):
            read_workflow(self.path)
        deep = {"value": "leaf"}
        for _ in range(70):
            deep = {"next": [deep]}
        with self.assertRaisesRegex(WorkflowError, "64 levels"):
            read_workflow(self.write(schema=deep))

    def test_workflow_envelope_has_no_execution_or_file_reference_overrides(self):
        for changes, message in (
            ({"version": 1}, "version 1"),
            ({"name": "Team/NASA"}, "lowercase"),
            ({"name": 9}, "lowercase"),
            ({"revision": True}, "revision"),
            ({"revision": "2"}, "revision"),
            ({"revision": 0}, "revision"),
            ({"goal": 1}, "goal"),
            ({"goal": " "}, "goal"),
            ({"goal": "x" * 8193}, "goal"),
            ({"schema": "schema.json"}, "inline"),
            ({"schema": []}, "inline"),
            ({"schema": [1]}, "string names"),
            ({"schema": ["x"] * 101}, "string names"),
            ({"task": "task.json"}, "inline"),
            ({"export": "result.json"}, "unsupported"),
        ):
            with (
                self.subTest(changes=changes.keys()),
                self.assertRaisesRegex(WorkflowError, message),
            ):
                read_workflow(self.write(**changes))
        self.path.write_bytes(b"[]")
        with self.assertRaisesRegex(WorkflowError, "unsupported"):
            read_workflow(self.path)

    def test_task_sources_reject_ambiguous_scope_and_invalid_input_names(self):
        source = {"url": "input:catalog", "format": "csv"}
        for task, message in (
            ({"seed_urls": "https://example.test/"}, "browser seeds"),
            ({"seed_urls": ["https://example.test/"] * 101}, "browser seeds"),
            ({"dataset_sources": {}}, "dataset sources"),
            ({"dataset_sources": [source] * 101}, "dataset sources"),
            (
                {"seed_urls": ["https://example.test/"], "dataset_sources": [source]},
                "browser seeds",
            ),
            ({"seed_urls": [0]}, "strings"),
            ({"dataset_sources": [0]}, "needs a URL"),
            ({"dataset_sources": [{}]}, "needs a URL"),
            ({"dataset_sources": [source, source]}, "distinct"),
            ({"dataset_sources": [{"url": "input:../../private"}]}, "valid and distinct"),
        ):
            with self.subTest(task=task.keys()), self.assertRaisesRegex(WorkflowError, message):
                read_workflow(self.write(task=task))

    def test_reusable_sources_cannot_embed_local_paths_or_url_credentials(self):
        for url in (
            "file:///private.csv",
            "ftp://example.test/example.csv",
            "https:///missing",
            "https://username@example.test/data",
            "https://u:p@example.test/data",
            "https://example.test:0/data",
            "https://example.test:bad/data",
            "https://example.test/bad path",
            "https://example.test/\\bad",
            "https://example.test/\x00",
        ):
            with self.subTest(url=url), self.assertRaisesRegex(WorkflowError, "URL"):
                read_workflow(self.write(task={"dataset_sources": [{"url": url, "format": "csv"}]}))
        valid = read_workflow(self.write(task={"seed_urls": ["https://example.test:443/catalog"]}))
        self.assertEqual(valid.bind(None), (valid.task, ()))

    def test_bindings_must_match_each_explicit_local_input(self):
        recipe = read_workflow(
            self.write(task={"dataset_sources": [{"url": "input:catalog", "format": "csv"}]})
        )
        for invalid in (None, ["catalog"], {"other": "x.csv"}, {"catalog": "x", "extra": "y"}):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(WorkflowError, "no extras"):
                recipe.bind(invalid)
        for invalid in (True, ""):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(WorkflowError, "file paths"):
                recipe.bind({"catalog": invalid})
        with (
            patch.object(Path, "absolute", side_effect=OSError("fixture")),
            self.assertRaisesRegex(WorkflowError, "Cannot resolve"),
        ):
            recipe.bind({"catalog": "catalog.csv"})

    def test_cli_binding_parser_is_exact_and_preserves_path_text(self):
        self.assertEqual(
            parse_bindings(["catalog=some path=1.csv", "other=other.json"]),
            {"catalog": Path("some path=1.csv"), "other": Path("other.json")},
        )
        for declarations in (["catalog"], ["Catalog=x"], ["catalog= "], ["catalog=x", "catalog=y"]):
            with (
                self.subTest(declarations=declarations),
                self.assertRaisesRegex(WorkflowError, "once"),
            ):
                parse_bindings(declarations)

    def test_saved_origin_is_unique_and_validated(self):
        origin = read_workflow(self.write()).origin()
        self.assertIsNone(saved_workflow_origin([{"kind": "other"}]))
        event = {"kind": "workflow_origin", "payload": origin}
        self.assertEqual(saved_workflow_origin([event]), origin)
        for events in ([event, event], [{"kind": "workflow_origin", "payload": []}]):
            with self.subTest(events=events), self.assertRaisesRegex(WorkflowError, "ambiguous"):
                saved_workflow_origin(events)
        for changes in ({"extra": True}, {"sha256": 5}, {"sha256": "X" * 64}):
            with self.subTest(changes=changes), self.assertRaisesRegex(WorkflowError, "malformed"):
                saved_workflow_origin([dict(event, payload={**origin, **changes})])
