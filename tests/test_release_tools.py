# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Release safeguards reject stale source, missing reviews and altered delivery artifacts."""

import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


MATRIX = load("release_matrix")
load("check_distribution")
VERIFY = load("verify_release")
PACKAGE = load("package_release")
CUSTOMER = load("customer_bundle")


@pytest.fixture
def release_root(tmp_path):
    (tmp_path / "evals/results").mkdir(parents=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/example.py").write_text("# original source\n")
    matrix = {
        "status": "pending",
        "production_status": "not_certified",
        "gates": [
            {"id": n, "status": "not_started", "criteria": {"test": "Real evidence"}}
            for n in range(1, 8)
        ],
    }
    MATRIX.save_matrix(matrix, tmp_path)
    return tmp_path


def complete_review(root):
    matrix = MATRIX.read_matrix(root)
    evidence = root / "evals/results/review.md"
    evidence.write_text("Actual test fixture evidence\n")
    digest = MATRIX.source_digest(root)
    for gate in matrix["gates"]:
        gate["status"] = "complete"
        gate["review"] = {
            "reviewer": "Fixture reviewer",
            "reviewed_at": "2026-10-17",
            "source_digest": digest,
            "attestation": f"I reviewed every criterion for gate {gate['id']}",
            "findings": {"test": "See retained fixture evidence"},
            "evidence": [{"path": "evals/results/review.md", "sha256": MATRIX.sha256(evidence)}],
        }
    MATRIX.save_matrix(matrix, root)
    return matrix


def test_reviews_do_not_invalidate_their_own_source_digest(release_root):
    before = MATRIX.source_digest(release_root)
    complete_review(release_root)
    assert MATRIX.source_digest(release_root) == before
    MATRIX.require_complete(release_root)


@pytest.mark.parametrize("change", ["source", "evidence", "findings", "missing_gate", "no_review"])
def test_completed_reviews_cannot_hide_missing_or_stale_evidence(release_root, change):
    matrix = complete_review(release_root)
    if change == "source":
        (release_root / "src/example.py").write_text("# changed\n")
    elif change == "evidence":
        (release_root / "evals/results/review.md").write_text("Different evidence\n")
    elif change == "findings":
        matrix["gates"][0]["review"]["findings"] = {}
    elif change == "no_review":
        matrix["gates"][0]["review"] = None
    else:
        matrix["gates"].pop()
    MATRIX.save_matrix(matrix, release_root)
    with pytest.raises(ValueError):
        MATRIX.require_complete(release_root)


def test_pending_gate_cannot_be_published_as_complete(release_root):
    with pytest.raises(ValueError, match="Pending"):
        MATRIX.require_complete(release_root)


@pytest.mark.parametrize(
    "name", ["../outside.txt", "/etc/passwd", "src/example.py", "evals/results/missing.md"]
)
def test_evidence_must_be_a_real_file_inside_results(release_root, name):
    with pytest.raises(ValueError):
        MATRIX.evidence_path(name, release_root)


def test_empty_evidence_is_rejected(release_root):
    (release_root / "evals/results/empty.md").touch()
    with pytest.raises(ValueError):
        MATRIX.evidence_path("evals/results/empty.md", release_root)


def passing_report(root, monkeypatch):
    dist = root / "build/release-checks/test/dist"
    dist.mkdir(parents=True)
    files = [dist / "verboisy-1.0.0-py3-none-any.whl", dist / "verboisy-1.0.0.tar.gz"]
    for path in files:
        path.write_bytes(b"fixture bytes")
    monkeypatch.setattr(PACKAGE, "inspect_archive", lambda _path: {"version": "1.0.0"})
    report = {
        "report_type": "engineering",
        "passed": True,
        "source_unchanged": True,
        "source_digest": MATRIX.source_digest(root),
        "checks": [
            {"name": name, "exit_code": 0}
            for name in sorted(VERIFY.BASE_CHECKS | VERIFY.PACKAGE_CHECKS)
        ],
        "artifacts": [
            {"path": p.relative_to(root).as_posix(), "sha256": MATRIX.sha256(p)} for p in files
        ],
    }
    path = root / "evals/results/engineering-test.json"
    path.write_text(json.dumps(report))
    return path, report, files


@pytest.mark.parametrize("change", ["source", "artifact", "checks", "failed", "traversal"])
def test_package_selection_rejects_unverified_or_changed_inputs(release_root, monkeypatch, change):
    path, report, files = passing_report(release_root, monkeypatch)
    PACKAGE.select_report(path, release_root)
    if change == "source":
        (release_root / "src/example.py").write_text("# new source\n")
    elif change == "artifact":
        files[0].write_bytes(b"replaced")
    elif change == "checks":
        report["checks"].pop()
    elif change == "failed":
        report["checks"][0]["exit_code"] = 1
    else:
        report["artifacts"][0]["path"] = "../outside.whl"
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError):
        PACKAGE.select_report(path, release_root)


def test_selected_report_cannot_be_replaced_later(release_root, monkeypatch):
    path, report, _ = passing_report(release_root, monkeypatch)
    candidate = PACKAGE.select_report(path, release_root)
    (release_root / PACKAGE.CANDIDATE).write_text(json.dumps(candidate))
    PACKAGE.read_candidate(release_root)
    report["checks"] = []
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="report changed"):
        PACKAGE.read_candidate(release_root)


def test_customer_delivery_contains_only_selected_files_and_refuses_overwrite(
    release_root, monkeypatch
):
    root = release_root
    wheel = root / "test.whl"
    wheel.write_bytes(b"fixture wheel")
    agreement = root / "test-agreement.pdf"
    agreement.write_bytes(b"%PDF-1.4\nExplicitly dummy test agreement\n")
    (root / "docs").mkdir()
    for name in ("LICENSE", "COPYRIGHT.md", "docs/installation.md"):
        (root / name).write_text("Fixture\n")
    monkeypatch.setattr(CUSTOMER, "read_candidate", lambda _selected: ({}, [wheel]))
    path = CUSTOMER.make_bundle("TEST-123", agreement, root)
    with zipfile.ZipFile(path) as archive:
        assert set(archive.namelist()) == {
            "test.whl",
            "AGREEMENT.pdf",
            "LICENSE",
            "COPYRIGHT.md",
            "INSTALLATION.md",
            "INSTALL.md",
            "SHA256SUMS",
        }
        assert archive.read("AGREEMENT.pdf") == agreement.read_bytes()
        assert b"activation server" in archive.read("INSTALL.md")
    with pytest.raises(FileExistsError):
        CUSTOMER.make_bundle("TEST-123", agreement, root)
    with pytest.raises(ValueError):
        CUSTOMER.make_bundle("../escape", agreement, root)
