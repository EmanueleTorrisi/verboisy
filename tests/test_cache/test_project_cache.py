# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Real SQLite cache isolation, expiry, corruption and transaction boundaries."""

import hashlib
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from verboisy.cache import CacheError, ProjectCache, _decode, _private
from verboisy.cache_policy import CachePolicy, is_cache_integer


def key(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


class ProjectCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "cache"
        self.policy = CachePolicy(self.root, "procurement", 65536, 4096, 10, 3)

    def tearDown(self):
        self.temp.cleanup()

    def test_real_reopen_preserves_typed_json_and_independent_values(self):
        value = {"null": None, "bool": True, "unicode": "日本語", "values": [1, 2.5, {"s": "x"}]}
        with ProjectCache(self.policy) as cache:
            self.assertEqual(cache.get(key(1)).state, "miss")
            self.assertTrue(cache.put(key(1), value))
        with ProjectCache(self.policy) as cache:
            result = cache.get(key(1))
            self.assertEqual(result.payload, value)
            result.payload["values"].append(9)
            self.assertEqual(cache.get(key(1)).payload, value)
            stats = cache.stats()
            self.assertEqual(stats["entries"], 1)
            self.assertEqual(stats["counters"]["hits"], 2)
            self.assertLessEqual(stats["database_bytes"], self.policy.max_bytes)

    def test_scope_isolation_and_file_scope_binding(self):
        other = CachePolicy(self.root, "engineering", 65536, 4096, 10, 3)
        with ProjectCache(self.policy) as first, ProjectCache(other) as second:
            first.put(key(1), {"project": "one"})
            self.assertEqual(second.get(key(1)).state, "miss")
        # Copying the database to another scope must not import its entries.
        other.database.write_bytes(self.policy.database.read_bytes())
        with self.assertRaises(CacheError):
            ProjectCache(other)

    def test_expiry_rollback_clock_and_shorter_policy(self):
        with ProjectCache(self.policy) as cache:
            with patch("verboisy.cache.time.time_ns", return_value=20_000_000_000):
                cache.put(key(1), {"value": 1})
                cache.put(key(2), {"value": 2})
            with patch("verboisy.cache.time.time_ns", return_value=30_000_000_000):
                self.assertEqual(cache.get(key(1)).state, "expired")
            with patch("verboisy.cache.time.time_ns", return_value=19_000_000_000):
                self.assertEqual(cache.get(key(2)).state, "expired")
            with patch("verboisy.cache.time.time_ns", return_value=40_000_000_000):
                cache.put(key(3), {"value": 3})
        short = CachePolicy(self.root, "procurement", 65536, 4096, 1, 3)
        with (
            ProjectCache(short) as cache,
            patch("verboisy.cache.time.time_ns", return_value=41_000_000_000),
        ):
            self.assertEqual(cache.get(key(3)).state, "expired")

    def test_lru_evicts_oldest_and_replacement_accounting_is_exact(self):
        with ProjectCache(self.policy) as cache:
            for i in range(3):
                cache.put(key(i), {"value": i})
            cache.get(key(0))
            cache.put(key(3), {"value": 3})
            self.assertEqual(cache.get(key(1)).state, "miss")
            self.assertEqual(cache.get(key(0)).state, "hit")
            cache.put(key(0), {"other": "longer value"})
            actual = (
                cache._db().execute("SELECT count(*),sum(length(payload)) FROM entries").fetchone()
            )
            self.assertEqual((cache.stats()["entries"], cache.stats()["payload_bytes"]), actual)
            self.assertEqual(cache.stats()["counters"]["evictions"], 1)

    def test_payload_capacity_causes_eviction_without_unbounded_database_growth(self):
        policy = CachePolicy(self.root, "procurement", 65536, 15000, 10, 100)
        with ProjectCache(policy) as cache:
            for i in range(12):
                cache.put(key(i), {"pad": "a" * 14000})
            self.assertLessEqual(cache.stats()["payload_bytes"], 32768)
            self.assertLessEqual(cache.stats()["database_bytes"], 65536)
            self.assertEqual(cache.get(key(11)).state, "hit")

    def test_oversized_entry_does_not_evict_previous_data(self):
        with ProjectCache(self.policy) as cache:
            cache.put(key(1), {"value": 1})
            self.assertFalse(cache.put(key(1), {"large": "x" * 5000}))
            self.assertEqual(cache.get(key(1)).payload, {"value": 1})

    def test_corrupt_payload_metadata_and_typed_envelope_are_not_hits(self):
        with ProjectCache(self.policy) as cache:
            for column, value in (
                ("payload", b"altered"),
                ("digest", "invalid"),
                ("created", "text"),
                ("expires", "text"),
            ):
                cache.put(key(1), {"value": 1})
                cache._db().execute(
                    "UPDATE entries SET " + column + "=? WHERE key=?", (value, key(1))
                )
                self.assertIn(cache.get(key(1)).state, {"corrupt", "expired"})
            for raw in (b'{"v":1,"v":2}', b'{"v":NaN}', b"[]", b'"\xff"'):
                cache.put(key(1), {"value": 1})
                created, expires = (
                    cache._db().execute("SELECT created,expires FROM entries").fetchone()
                )
                cache._db().execute(
                    "UPDATE entries SET payload=?,digest=? WHERE key=?",
                    (raw, cache._digest(key(1), raw, created, expires), key(1)),
                )
                self.assertEqual(cache.get(key(1)).state, "corrupt")

    def test_clear_reclaims_pages_and_never_changes_another_scope(self):
        other = CachePolicy(self.root, "other", 65536, 4096, 10, 3)
        with ProjectCache(self.policy) as first, ProjectCache(other) as second:
            first.put(key(1), {"v": 1})
            second.put(key(1), {"v": 2})
            first.clear()
            self.assertEqual(first.stats()["entries"], 0)
            self.assertEqual(first.stats()["counters"], {})
            self.assertEqual(second.get(key(1)).payload, {"v": 2})

    def test_invalid_keys_and_non_json_payloads_are_controlled(self):
        with ProjectCache(self.policy) as cache:
            for value in ("plain text", "A" * 64, "a" * 63, None):
                with self.assertRaises(CacheError):
                    cache.get(value)
            for value in (
                [1],
                {"v": float("nan")},
                {"v": object()},
                {"v": "\ud800"},
                {1: "v"},
                {"v": (1, 2)},
            ):
                with self.assertRaises(CacheError):
                    cache.put(key(1), value)
            for raw in (b"[]", b'{"v":Infinity}', b'{"v":1e999}', b'{"v":1,"v":2}'):
                with self.assertRaises(ValueError):
                    _decode(raw)

    def test_existing_unrelated_file_is_preserved(self):
        self.root.mkdir(mode=0o700)
        self.policy.database.write_bytes(b"unrelated private input")
        self.policy.database.chmod(0o600)
        with self.assertRaises(CacheError):
            ProjectCache(self.policy)
        self.assertEqual(self.policy.database.read_bytes(), b"unrelated private input")

    def test_symlinks_hardlinks_and_open_permissions_are_refused(self):
        if os.name == "nt":
            return  # POSIX permissions and link creation are qualified on POSIX jobs.
        self.root.mkdir(mode=0o700)
        self.root.chmod(0o755)
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o755)
        with self.assertRaises(CacheError):
            ProjectCache(self.policy)
        self.root.chmod(0o700)
        target = Path(self.temp.name) / "target"
        target.write_bytes(b"private")
        self.policy.database.symlink_to(target)
        with self.assertRaises(CacheError):
            ProjectCache(self.policy)
        self.policy.database.unlink()
        os.link(target, self.policy.database)
        with self.assertRaises(CacheError):
            ProjectCache(self.policy)
        self.policy.database.unlink()
        other = Path(self.temp.name) / "alias"
        other.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(CacheError):
            ProjectCache(CachePolicy(other, "scope"))
        with self.assertRaises(CacheError):
            _private(target, directory=True)

    def test_two_connections_serialize_and_lock_failure_preserves_committed_entry(self):
        with ProjectCache(self.policy) as first, ProjectCache(self.policy) as second:
            first.put(key(1), {"v": 1})
            first._db().execute("BEGIN IMMEDIATE")
            try:
                with self.assertRaises(CacheError):
                    second.put(key(2), {"v": 2})
                with self.assertRaises(CacheError):
                    second.get(key(1))
            finally:
                first._db().rollback()
            self.assertEqual(second.get(key(1)).payload, {"v": 1})
            second.put(key(2), {"v": 2})
            self.assertEqual(first.get(key(2)).payload, {"v": 2})

    def test_storage_and_operational_failures_are_controlled(self):
        cache = ProjectCache(self.policy)
        cache.close()
        cache.close()
        with self.assertRaises(CacheError):
            cache.get(key(1))
        with ProjectCache(self.policy) as cache:
            cache._db().execute("DROP TABLE counters")
            with self.assertRaises(CacheError):
                cache.put(key(1), {"v": 1})
            with self.assertRaises(CacheError):
                cache.get(key(1))
            with self.assertRaises(CacheError):
                cache.stats()
            with self.assertRaises(CacheError):
                cache.clear()

    def test_version_mismatch_and_tighter_physical_limit_are_refused(self):
        with ProjectCache(self.policy) as cache:
            cache._db().execute("PRAGMA user_version=2")
        with self.assertRaises(CacheError):
            ProjectCache(self.policy)
        self.policy.database.unlink()
        bigger = CachePolicy(self.root, "procurement", 131072, 30000, 10, 10)
        with ProjectCache(bigger) as cache:
            for i in range(5):
                cache.put(key(i), {"v": "x" * 28000})
            self.assertGreater(cache.stats()["database_bytes"], 65536)
        with self.assertRaises(CacheError):
            ProjectCache(self.policy)

    def test_first_open_failure_removes_only_its_new_empty_cache(self):
        with (
            patch(
                "verboisy.cache.sqlite3.connect", side_effect=sqlite3.OperationalError("synthetic")
            ),
            self.assertRaises(CacheError),
        ):
            ProjectCache(self.policy)
        self.assertFalse(self.policy.database.exists())

    def test_permission_logic_is_explicit_on_both_platform_branches(self):
        info = SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_nlink=1, st_uid=42)
        path = Mock()
        path.lstat.return_value = info
        path.is_symlink.return_value = False
        with patch("verboisy.cache.os", SimpleNamespace(name="posix", getuid=lambda: 42)):
            _private(path, directory=True)
            info.st_uid = 43
            with self.assertRaises(CacheError):
                _private(path, directory=True)
        with patch("verboisy.cache.os", SimpleNamespace(name="nt")):
            _private(path, directory=True)

    def test_sidecar_alias_bad_accounting_and_oversized_saved_payload_are_refused(self):
        with ProjectCache(self.policy) as cache:
            cache.put(key(1), {"v": "x" * 1000})
        smaller = CachePolicy(self.root, "procurement", 65536, 100, 10, 3)
        with ProjectCache(smaller) as cache:
            self.assertEqual(cache.get(key(1)).state, "corrupt")
            cache._db().execute("UPDATE project SET entries=-1")
        with self.assertRaises(CacheError):
            ProjectCache(self.policy)
        if os.name != "nt":
            self.policy.database.unlink()
            target = Path(self.temp.name) / "unrelated"
            target.write_bytes(b"original")
            journal = Path(str(self.policy.database) + "-journal")
            journal.symlink_to(target)
            with self.assertRaises(CacheError):
                ProjectCache(self.policy)
            self.assertEqual(target.read_bytes(), b"original")

    def test_fresh_python_process_can_reuse_committed_entry(self):
        with ProjectCache(self.policy) as cache:
            cache.put(key(1), {"value": 42})
        import verboisy.cache as module

        code = (
            "import sys; from pathlib import Path; sys.path.insert(0,"
            + repr(str(Path(module.__file__).parents[1]))
            + ");"
            "from verboisy.cache import ProjectCache; "
            "from verboisy.cache_policy import CachePolicy;"
            "p=CachePolicy(Path(" + repr(str(self.root)) + "),'procurement',65536,4096,10,3);"
            "c=ProjectCache(p); print(c.get(" + repr(key(1)) + ").payload['value']); c.close()"
        )
        result = subprocess.run(
            [sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=15
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "42")


class CachePolicyTests(unittest.TestCase):
    def test_integer_quantities_never_accept_booleans_or_numeric_strings(self):
        for value in (True, False, 1.0, "1", None):
            self.assertFalse(is_cache_integer(value))
        self.assertTrue(is_cache_integer(1))
        for field in ("ttl_seconds", "max_entries", "max_entry_bytes"):
            with self.assertRaises(ValueError):
                CachePolicy(Path.cwd(), "team", **{field: True})

    def test_policy_fingerprints_scope_and_protects_sidecars(self):
        p = CachePolicy(Path.cwd(), "one")
        self.assertEqual(len(p.protected_paths), 4)
        self.assertNotEqual(p.database, CachePolicy(Path.cwd(), "two").database)
        self.assertEqual(CachePolicy(Path.cwd(), "one", 65536, 100).entry_limit, 64)

    def test_bad_policy_is_rejected_before_opening_storage(self):
        for kwargs in (
            {"directory": Path("relative")},
            {"directory": "absolute"},
            {"scope": ""},
            {"scope": " "},
            {"scope": "x" * 129},
            {"scope": "\ud800"},
            {"max_bytes": True},
            {"max_bytes": "1"},
            {"max_bytes": 1},
            {"ttl_seconds": 0},
            {"max_entries": False},
            {"max_entry_bytes": 0},
            {"max_entry_bytes": 64 * 1024**2},
        ):
            with self.assertRaises(ValueError):
                CachePolicy(**{"directory": Path.cwd(), "scope": "p", **kwargs})
