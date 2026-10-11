# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""CI must reject missing, empty, skipped or failed compiled-test evidence."""

from types import SimpleNamespace

import pytest

from scripts import check_native_tests as gate


@pytest.mark.parametrize("root", ["testsuites", "testsuite"])
def test_successful_native_report_counts_testcases(tmp_path, root):
    xml = '<testsuite><testcase name="one"/><testcase name="two"/></testsuite>'
    if root == "testsuites":
        xml = "<testsuites>" + xml + "</testsuites>"
    report = tmp_path / "native.xml"
    report.write_text(xml)
    assert gate.checked_test_count(report) == 2


@pytest.mark.parametrize("status", ["skipped", "failure", "error"])
def test_status_cannot_be_hidden_by_successful_suite_totals(tmp_path, status):
    report = tmp_path / "native.xml"
    report.write_text(
        '<testsuite tests="1" failures="0" skipped="0">'
        f'<testcase name="native"><{status}/></testcase></testsuite>'
    )
    with pytest.raises(ValueError, match=status):
        gate.checked_test_count(report)


@pytest.mark.parametrize("xml", ["<testsuites/>", "<testsuite/>", "<other><testcase/></other>"])
def test_empty_or_unexpected_report_fails(tmp_path, xml):
    report = tmp_path / "native.xml"
    report.write_text(xml)
    with pytest.raises(ValueError):
        gate.checked_test_count(report)


def configure_root(tmp_path, monkeypatch):
    script = tmp_path / "scripts/check_native_tests.py"
    script.parent.mkdir()
    monkeypatch.setattr(gate, "__file__", str(script))
    monkeypatch.setattr(
        gate,
        "inspect_native_builds",
        lambda: {
            name: dict.fromkeys(
                (
                    "binary_present",
                    "metadata_present",
                    "binary_matches_metadata",
                    "sources_match_metadata",
                ),
                True,
            )
            for name in ("production", "tests")
        },
    )
    return tmp_path / "build/native/native-test-results.xml"


def test_main_controls_selection_and_removes_stale_report(tmp_path, monkeypatch, capsys):
    report = configure_root(tmp_path, monkeypatch)
    report.parent.mkdir(parents=True)
    report.write_text("stale")
    monkeypatch.setenv("PYTEST_ADDOPTS", "-m not_native")
    monkeypatch.setenv("CXX", "c++")

    def run(command, *, cwd, env, check):
        assert not report.exists()
        assert cwd == tmp_path
        assert command[:8] == [
            gate.sys.executable,
            "-m",
            "pytest",
            "-m",
            "native",
            "--no-cov",
            "-q",
            "-ra",
        ]
        assert command[-2:] == ["--junitxml", str(report)]
        assert "PYTEST_ADDOPTS" not in env and env["CXX"] == "c++"
        assert check is False
        report.write_text('<testsuite><testcase name="native"/></testsuite>')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(gate.subprocess, "run", run)
    assert gate.main() == 0
    assert "1 tests, no skips" in capsys.readouterr().out


@pytest.mark.parametrize(
    "xml",
    [None, "broken XML", "<testsuite/>", "<testsuite><testcase><skipped/></testcase></testsuite>"],
)
def test_main_fails_when_pytest_success_lacks_valid_results(tmp_path, monkeypatch, capsys, xml):
    report = configure_root(tmp_path, monkeypatch)

    def run(*_args, **_kwargs):
        if xml is not None:
            report.write_text(xml)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(gate.subprocess, "run", run)
    assert gate.main() == 1
    assert "Native validation failed" in capsys.readouterr().err


def test_pytest_failure_exit_code_propagates(tmp_path, monkeypatch):
    configure_root(tmp_path, monkeypatch)
    monkeypatch.setattr(
        gate.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=5)
    )
    assert gate.main() == 5


@pytest.mark.parametrize("build", ["production", "tests"])
@pytest.mark.parametrize(
    "field",
    ["binary_present", "metadata_present", "binary_matches_metadata", "sources_match_metadata"],
)
@pytest.mark.parametrize("value", [False, None])
def test_unchecked_or_stale_build_never_launches_pytest(
    tmp_path, monkeypatch, capsys, build, field, value
):
    report = configure_root(tmp_path, monkeypatch)
    report.parent.mkdir(parents=True)
    report.write_text("stale success report")
    reports = gate.inspect_native_builds()
    reports[build][field] = value
    monkeypatch.setattr(gate, "inspect_native_builds", lambda: reports)
    monkeypatch.setattr(
        gate.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("pytest launched")
    )
    assert gate.main() == 1
    assert not report.exists()
    error = capsys.readouterr().err
    assert build in error and field in error and "rebuild both" in error


@pytest.mark.parametrize("error", [OSError("unreadable build"), ValueError("invalid manifest")])
def test_inspection_failure_prevents_native_execution(tmp_path, monkeypatch, capsys, error):
    configure_root(tmp_path, monkeypatch)

    def inspect():
        raise error

    monkeypatch.setattr(gate, "inspect_native_builds", inspect)
    monkeypatch.setattr(
        gate.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("pytest launched")
    )
    assert gate.main() == 1
    assert str(error) in capsys.readouterr().err
