import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
import verboisy.cli.main as main
from typer.testing import CliRunner

runner = CliRunner()


class DummyProgress:
    def add_task(self, **kwargs: object) -> None:
        pass


class DummySpinner:
    def __enter__(self) -> DummyProgress:
        return DummyProgress()

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        pass


def patch_ui(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.CLIUserInterface, "print_header", Mock())
    monkeypatch.setattr(main.CLIUserInterface, "print_error", Mock())
    monkeypatch.setattr(main.CLIUserInterface, "print_success", Mock())
    monkeypatch.setattr(main.CLIUserInterface, "display_results_table", Mock())
    monkeypatch.setattr(
        main.CLIUserInterface,
        "create_spinner",
        lambda: DummySpinner(),
    )


def make_schema(tmp_path: Path, content: object) -> Path:
    path = tmp_path / "schema.json"
    path.write_text(
        json.dumps(content),
        encoding="utf-8",
    )
    return path


def make_agent(
    monkeypatch: pytest.MonkeyPatch,
    state: SimpleNamespace,
    calls: list[tuple[str, dict[str, object]]],
) -> None:
    class FakeAgent:
        def __init__(
            self,
            goal: str,
            target_schema: dict[str, object],
            max_steps: int,
        ) -> None:
            calls.append(
                (
                    "init",
                    {
                        "goal": goal,
                        "target_schema": target_schema,
                        "max_steps": max_steps,
                    },
                )
            )

        async def run(self) -> SimpleNamespace:
            calls.append(("run", {}))
            return state

    monkeypatch.setattr(main, "Agent", FakeAgent)


def test_run_agent_completed_without_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ui(monkeypatch)

    calls: list[tuple[str, dict[str, object]]] = []
    state = SimpleNamespace(
        status="COMPLETED",
        step_count=3,
        extracted_data=[{"name": "Alice"}],
    )
    make_agent(monkeypatch, state, calls)

    schema_path = make_schema(
        tmp_path,
        {"type": "object", "properties": {"name": {"type": "string"}}},
    )

    result = runner.invoke(
        main.app,
        [
            "--goal",
            "find users",
            "--schema",
            str(schema_path),
        ],
    )

    assert result.exit_code == 0
    assert calls == [
        (
            "init",
            {
                "goal": "find users",
                "target_schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
                "max_steps": 20,
            },
        ),
        ("run", {}),
    ]


def test_run_agent_completed_exports_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ui(monkeypatch)

    state = SimpleNamespace(
        status="COMPLETED",
        step_count=2,
        extracted_data=[{"name": "Alice"}],
    )
    make_agent(monkeypatch, state, [])

    export_path = tmp_path / "results.json"
    schema_path = make_schema(tmp_path, {"type": "object"})

    export_json = Mock()
    export_csv = Mock()

    monkeypatch.setattr(main.DataExporter, "export_json", export_json)
    monkeypatch.setattr(main.DataExporter, "export_csv", export_csv)

    result = runner.invoke(
        main.app,
        [
            "--goal",
            "find users",
            "--schema",
            str(schema_path),
            "--export",
            str(export_path),
        ],
    )

    assert result.exit_code == 0
    export_json.assert_called_once_with(
        [{"name": "Alice"}],
        export_path,
    )
    export_csv.assert_not_called()


def test_run_agent_completed_exports_csv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ui(monkeypatch)

    state = SimpleNamespace(
        status="COMPLETED",
        step_count=2,
        extracted_data=[{"name": "Alice"}],
    )
    make_agent(monkeypatch, state, [])

    export_path = tmp_path / "results.csv"
    schema_path = make_schema(tmp_path, {"type": "object"})

    export_json = Mock()
    export_csv = Mock()

    monkeypatch.setattr(main.DataExporter, "export_json", export_json)
    monkeypatch.setattr(main.DataExporter, "export_csv", export_csv)

    result = runner.invoke(
        main.app,
        [
            "--goal",
            "find users",
            "--schema",
            str(schema_path),
            "--export",
            str(export_path),
        ],
    )

    assert result.exit_code == 0
    export_csv.assert_called_once_with(
        [{"name": "Alice"}],
        export_path,
    )
    export_json.assert_not_called()


def test_run_agent_export_skipped_when_data_is_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ui(monkeypatch)

    state = SimpleNamespace(
        status="COMPLETED",
        step_count=1,
        extracted_data=[],
    )
    make_agent(monkeypatch, state, [])

    schema_path = make_schema(tmp_path, {"type": "object"})
    export_json = Mock()
    export_csv = Mock()

    monkeypatch.setattr(main.DataExporter, "export_json", export_json)
    monkeypatch.setattr(main.DataExporter, "export_csv", export_csv)

    result = runner.invoke(
        main.app,
        [
            "--goal",
            "find users",
            "--schema",
            str(schema_path),
            "--export",
            str(tmp_path / "results.json"),
        ],
    )

    assert result.exit_code == 0
    export_json.assert_not_called()
    export_csv.assert_not_called()


def test_run_agent_failed_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ui(monkeypatch)

    state = SimpleNamespace(
        status="FAILED",
        step_count=4,
        extracted_data=[],
    )
    make_agent(monkeypatch, state, [])

    schema_path = make_schema(tmp_path, {"type": "object"})

    result = runner.invoke(
        main.app,
        [
            "--goal",
            "find users",
            "--schema",
            str(schema_path),
        ],
    )

    assert result.exit_code == 0
    main.CLIUserInterface.print_error.assert_called_once_with(
        "Agent run failed. Status: FAILED"
    )


def test_run_agent_invalid_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ui(monkeypatch)

    schema_path = tmp_path / "invalid.json"
    schema_path.write_text("{ invalid json", encoding="utf-8")

    result = runner.invoke(
        main.app,
        [
            "--goal",
            "find users",
            "--schema",
            str(schema_path),
        ],
    )

    assert result.exit_code == 1
    main.CLIUserInterface.print_error.assert_called_once()
    assert "Failed to load schema" in (
        main.CLIUserInterface.print_error.call_args.args[0]
    )


def test_run_agent_keyboard_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ui(monkeypatch)

    class FakeAgent:
        def __init__(
            self,
            goal: str,
            target_schema: dict[str, object],
            max_steps: int,
        ) -> None:
            pass

        async def run(self) -> SimpleNamespace:
            raise KeyboardInterrupt

    monkeypatch.setattr(main, "Agent", FakeAgent)

    schema_path = make_schema(tmp_path, {"type": "object"})

    result = runner.invoke(
        main.app,
        [
            "--goal",
            "find users",
            "--schema",
            str(schema_path),
        ],
    )

    assert result.exit_code == 1
    main.CLIUserInterface.print_error.assert_called_once_with(
        "Run aborted by user."
    )


def test_run_agent_unexpected_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ui(monkeypatch)

    class FakeAgent:
        def __init__(
            self,
            goal: str,
            target_schema: dict[str, object],
            max_steps: int,
        ) -> None:
            pass

        async def run(self) -> SimpleNamespace:
            raise RuntimeError("boom")

    monkeypatch.setattr(main, "Agent", FakeAgent)

    schema_path = make_schema(tmp_path, {"type": "object"})

    result = runner.invoke(
        main.app,
        [
            "--goal",
            "find users",
            "--schema",
            str(schema_path),
        ],
    )

    assert result.exit_code == 1
    main.CLIUserInterface.print_error.assert_called_once_with(
        "Agent execution failed unexpectedly: boom"
    )


def test_run_agent_reports_export_failure(monkeypatch, tmp_path) -> None:
    schema_path = tmp_path / "schema.json"
    schema_path.write_text("{}", encoding="utf-8")

    export_path = tmp_path / "results.json"

    final_state = SimpleNamespace(
        status="COMPLETED",
        step_count=1,
        extracted_data=[{"name": "Alice"}],
    )

    agent = Mock()
    agent.run = AsyncMock(return_value=final_state)

    monkeypatch.setattr(main, "Agent", Mock(return_value=agent))

    progress = Mock()
    spinner = MagicMock()
    spinner.__enter__.return_value = progress
    spinner.__exit__.return_value = False

    monkeypatch.setattr(
        main.CLIUserInterface,
        "create_spinner",
        Mock(return_value=spinner),
    )
    monkeypatch.setattr(main.CLIUserInterface, "print_header", Mock())
    monkeypatch.setattr(main.CLIUserInterface, "print_success", Mock())
    monkeypatch.setattr(main.CLIUserInterface, "display_results_table", Mock())

    print_error = Mock()
    monkeypatch.setattr(main.CLIUserInterface, "print_error", print_error)

    monkeypatch.setattr(
        main.DataExporter,
        "export_json",
        Mock(side_effect=RuntimeError("boom")),
    )

    main.run_agent(
        goal="test goal",
        schema_path=schema_path,
        export_path=export_path,
        max_steps=1,
    )

    print_error.assert_any_call("Failed to export data: boom")
