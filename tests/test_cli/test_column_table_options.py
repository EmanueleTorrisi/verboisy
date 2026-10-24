# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Column layout is an explicit, bounded and repeatable CLI task declaration."""

import pytest
import verboisy.cli.main as cli
from typer.testing import CliRunner
from verboisy.api import RunResult
from verboisy.evidence.models import TaskSpec
from verboisy.utils.exceptions import VerboisyError


@pytest.mark.parametrize(
    "schema,mode", [("[body]", "spreadsheet"), ("  [body]", "spreadsheet"), ("schema.json", "json")]
)
def test_explicit_tables_reach_the_api_and_empty_option_preserves_defaults(
    monkeypatch, tmp_path, schema, mode
):
    seen = []

    def execute(**kwargs):
        seen.append(kwargs)
        return RunResult(
            run_id="column-test",
            records=[],
            export_path=None,
            db_path=tmp_path / "run.db",
            completed=True,
            status="COMPLETED",
            stop_reason="target_met",
        )

    monkeypatch.setattr(cli, "run", execute)
    runner = CliRunner()
    args = ["run", "--goal", "Objects", "--schema", schema, "--no-animation"]
    result = runner.invoke(cli.app, [*args, "--column-table", "1", "--column-table", "3"])
    assert result.exit_code == 0, result.output
    assert seen[-1]["task"] == {"column_tables": [{"table": 1}, {"table": 3}], "csv_mode": mode}
    assert runner.invoke(cli.app, args).exit_code == 0
    assert "task" not in seen[-1]
    assert "--column-table" in runner.invoke(cli.app, ["run", "--help"]).output


@pytest.mark.parametrize("number", ["0", "101", "abc"])
def test_bad_table_numbers_fail_before_research(monkeypatch, number):
    def execute(**_kwargs):
        pytest.fail("Invalid table number reached research")

    monkeypatch.setattr(cli, "run", execute)
    result = CliRunner().invoke(cli.app, ["run", "--column-table", number])
    assert result.exit_code == 2


def test_duplicate_table_declaration_is_reported_as_user_error(monkeypatch):
    def execute(**kwargs):
        try:
            TaskSpec.model_validate(kwargs["task"])
        except ValueError as error:
            raise VerboisyError("Invalid task declaration") from error

    monkeypatch.setattr(cli, "run", execute)
    result = CliRunner().invoke(cli.app, ["run", "--column-table", "1", "--column-table", "1"])
    assert result.exit_code == 1
    assert "Invalid task declaration" in result.output
