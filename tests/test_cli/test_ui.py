# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

import copy
import io
import json

import verboisy.cli.ui as ui
from rich.console import Console
from rich.progress import Progress
from verboisy.cli.ui import CLIUserInterface, RunDisplay


def make_console() -> Console:
    return Console(record=True, color_system=None, width=120)


def test_print_header(monkeypatch) -> None:
    test_console = make_console()
    monkeypatch.setattr(ui, "console", test_console)

    CLIUserInterface.print_header("Verboisy Agent", "Extraction started")

    output = test_console.export_text()
    assert "Verboisy Agent" in output
    assert "Extraction started" in output


def test_print_error(monkeypatch) -> None:
    test_console = make_console()
    monkeypatch.setattr(ui, "console", test_console)

    CLIUserInterface.print_error("Something went wrong")

    output = test_console.export_text()
    assert "Error:" in output
    assert "Something went wrong" in output


def test_print_success(monkeypatch) -> None:
    test_console = make_console()
    monkeypatch.setattr(ui, "console", test_console)

    CLIUserInterface.print_success("Operation completed")

    output = test_console.export_text()
    assert "Success:" in output
    assert "Operation completed" in output


def test_display_results_table_with_no_data(monkeypatch) -> None:
    test_console = make_console()
    monkeypatch.setattr(ui, "console", test_console)

    CLIUserInterface.display_results_table([])

    output = test_console.export_text()
    assert "No data was extracted during this run." in output


def test_display_results_table_with_data(monkeypatch) -> None:
    test_console = make_console()
    monkeypatch.setattr(ui, "console", test_console)

    data = [
        {
            "name": "Alice",
            "email": "alice@example.com",
            "role": "Developer",
            "city": "Rome",
            "company": "Example",
            "department": "Engineering",
            "ignored_column": "should not appear",
        },
        {
            "name": "Bob",
            "email": "bob@example.com",
            "role": "Designer",
        },
    ]

    CLIUserInterface.display_results_table(data)

    output = test_console.export_text()

    assert "name" in output
    assert "email" in output
    assert "role" in output
    assert "city" in output
    assert "company" in output
    assert "department" in output
    assert "1 more columns" in output
    assert "ignored_column" not in output


def test_display_results_table_limits_rows_and_truncates_values(
    monkeypatch,
) -> None:
    test_console = make_console()
    monkeypatch.setattr(ui, "console", test_console)

    long_value = "x" * 100

    data = [
        {"name": long_value},
        {"name": "row2"},
        {"name": "row3"},
        {"name": "row4"},
        {"name": "row5"},
        {"name": "row6"},
        {"name": "row7"},
    ]

    CLIUserInterface.display_results_table(data)

    output = test_console.export_text()

    assert "x" * 47 + "..." in output
    assert "x" * 48 not in output
    assert "CSV preview: first 5 of 7 rows." in output
    assert "row6" not in output and "row7" not in output


def test_display_results_table_with_empty_record(monkeypatch) -> None:
    test_console = make_console()
    monkeypatch.setattr(ui, "console", test_console)

    CLIUserInterface.display_results_table([{}])

    output = test_console.export_text()
    assert "The returned records contain no fields." in output


def test_display_results_table_with_wide_characters(monkeypatch) -> None:
    test_console = make_console()
    monkeypatch.setattr(ui, "console", test_console)

    CLIUserInterface.display_results_table(
        [
            {"name": "界" * 30},
        ]
    )

    output = test_console.export_text()

    assert "界" * 23 + "..." in output


def test_display_results_table_with_narrow_terminal(monkeypatch) -> None:
    test_console = Console(
        record=True,
        color_system=None,
        width=25,
    )
    monkeypatch.setattr(ui, "console", test_console)

    data = [
        {f"column_{i}": "long-value" for i in range(5)},
    ]

    CLIUserInterface.display_results_table(data)

    output = test_console.export_text()

    assert "..." in output
    assert "Widen the terminal" not in output


def test_display_results_table_with_terminal_too_narrow(monkeypatch) -> None:
    test_console = Console(
        record=True,
        color_system=None,
        width=10,
    )
    monkeypatch.setattr(ui, "console", test_console)

    data = [
        {f"column_{i}": "value" for i in range(5)},
    ]

    CLIUserInterface.display_results_table(data)

    output = test_console.export_text()

    assert "Widen" in output


def test_create_spinner(monkeypatch) -> None:
    test_console = make_console()
    monkeypatch.setattr(ui, "console", test_console)

    spinner = CLIUserInterface.create_spinner()

    assert isinstance(spinner, Progress)
    assert spinner.console is test_console


def test_preview_counts_optional_fields_across_records_without_mutation(monkeypatch):
    test_console = Console(record=True, color_system=None, width=180)
    monkeypatch.setattr(ui, "console", test_console)
    data = [{"id": 1, **{f"field{i}": i for i in range(11)}}, {"id": 2, "optional": None}]
    before = copy.deepcopy(data)
    CLIUserInterface.display_results_table(data)
    output = test_console.export_text()
    assert "first 2 of 2 rows" in output and "7 more columns" in output
    assert data == before


def test_json_preview_preserves_types_missing_fields_and_actual_counts(monkeypatch):
    test_console = make_console()
    monkeypatch.setattr(ui, "console", test_console)
    fields = {"name": "A", "price": 2.5, "stock": True, "unknown": None, "count": 3, "city": "Rome"}
    data = [{"id": i, **fields, "hidden": "not displayed"} for i in range(5)]
    del data[1]["unknown"]
    before = copy.deepcopy(data)
    CLIUserInterface.display_json_preview(data)
    output = test_console.export_text()
    assert "first 3 of 5 rows; 6 of 7 source columns" in output
    payload = json.loads(output[output.index("[\n") :].strip())
    assert payload == [
        {k: v for k, v in row.items() if k not in {"id", "hidden"}} for row in data[:3]
    ]
    assert data == before


def test_json_preview_empty_and_large_values_are_bounded(monkeypatch):
    test_console = Console(record=True, color_system=None, width=60)
    monkeypatch.setattr(ui, "console", test_console)
    CLIUserInterface.display_json_preview([])
    assert not test_console.export_text()
    data = [{"name": "x" * 300 + "\u0085\u2028", "nested": list(range(100))}]
    before = copy.deepcopy(data)
    CLIUserInterface.display_json_preview(data)
    output = test_console.export_text()
    assert "Preview shortened" in output
    assert len(output.splitlines()) < 60
    assert data == before


def test_goal_headers_values_and_paths_are_literal_terminal_text(monkeypatch):
    test_console = make_console()
    monkeypatch.setattr(ui, "console", test_console)
    display = RunDisplay()
    display.started("saved-id", "[red]literal[/red]\nnext\x1b[2J")
    display.started("ignored-id", "ignored goal")
    display.finish("PAUSED")
    CLIUserInterface.display_results_table([{}, {"long\nheading": "[blue]literal[/blue]\tvalue"}])
    CLIUserInterface.print_artifact("CSV", "/tmp/[red]literal.csv")
    CLIUserInterface.print_signoff()
    output = test_console.export_text()
    assert "[red]literal[/red]" in output and "\x1b" not in output
    assert output.count("Run ID:") == 1 and "saved-id" in output
    assert "ignored-id" not in output and "Status: PAUSED" in output
    assert "long heading" in output and "[blue]literal[/blue] value" in output
    assert "/tmp/[red]literal.csv" in output
    assert "Thank you, and best of luck with your work." in output


def test_terminal_running_line_is_closed_before_final_status(monkeypatch):
    stream = io.StringIO()
    test_console = Console(file=stream, force_terminal=True, color_system="truecolor", width=120)
    monkeypatch.setattr(ui, "console", test_console)
    display = RunDisplay()
    display.started("actual-id", "Actual goal")
    assert display.live is not None
    display.finish("COMPLETED")
    display.close()
    assert display.live is None and "COMPLETED" in stream.getvalue()


def test_interactive_pacing_matches_blueprint_without_fake_research_time(monkeypatch):
    stream = io.StringIO()
    test_console = Console(file=stream, force_terminal=True, color_system=None, width=180)
    monkeypatch.setattr(ui, "console", test_console)
    delays = []
    monkeypatch.setattr(ui.time, "sleep", delays.append)
    CLIUserInterface.print_header("Verboisy 1.0.0", "Autonomous web research", animate=True)
    display = RunDisplay(animate=True)
    display.started("real-run", "Find records")
    display.finish("COMPLETED")
    CLIUserInterface.display_results_table([{"id": 1, "name": "A"}], animate=True)
    CLIUserInterface.display_json_preview([{"id": 1, "name": "A"}], animate=True)
    CLIUserInterface.print_artifact("CSV", "/tmp/records.csv", animate=True)
    CLIUserInterface.print_artifact("JSON", "/tmp/records.json", animate=True)
    CLIUserInterface.print_artifact("Proof", "/tmp/records.proof.txt", animate=True)
    CLIUserInterface.print_signoff(animate=True)
    expected = [1, 2, 0.5]
    for char in "✦ Find records":
        if char == "✦":
            expected.append(1)
        if char == " ":
            expected.append(0.03)
        expected.append(0.005)
    expected.extend([1, 1, 1.5, 3, 3, 4, 3, 1, 1, 2])
    for char in "Thank you, and best of luck with your work.":
        if char == ",":
            expected.append(0.1)
        expected.append(0.02)
    expected.extend([0.6, 0.3])
    assert delays == expected
    assert 16 not in delays
    assert "✦ Find records" in stream.getvalue()
    assert "Thank you, and best of luck with your work." in stream.getvalue()


def test_animation_is_immediate_for_redirected_output_or_explicit_opt_out(monkeypatch):
    def unexpected_sleep(_seconds):
        raise AssertionError("Automation must not wait for presentation")

    monkeypatch.setattr(ui.time, "sleep", unexpected_sleep)
    for terminal, animate in ((False, True), (True, False)):
        stream = io.StringIO()
        monkeypatch.setattr(
            ui,
            "console",
            Console(file=stream, force_terminal=terminal, color_system=None, width=120),
        )
        CLIUserInterface.print_header("Verboisy", "Research", animate=animate)
        display = RunDisplay(animate=animate)
        display.started("persisted", "Read local data")
        display.finish("COMPLETED")
        CLIUserInterface.display_results_table([{"name": "A"}], animate=animate)
        CLIUserInterface.display_json_preview([{"name": "A"}], animate=animate)
        CLIUserInterface.print_artifact("CSV", "/tmp/a.csv", animate=animate)
        CLIUserInterface.print_signoff(animate=animate)
        assert "COMPLETED" in stream.getvalue()


def test_review_and_error_messages_preserve_actions_without_typing_or_markup(monkeypatch):
    stream = io.StringIO()
    monkeypatch.setattr(
        ui, "console", Console(file=stream, force_terminal=True, color_system=None, width=120)
    )
    delays = []
    monkeypatch.setattr(ui.time, "sleep", delays.append)
    CLIUserInterface.print_notice(
        "* Proposed changes: [red]literal[/red]\nAccept: --okresume saved"
    )
    CLIUserInterface.print_error("Invalid field\x1b[2J\nResume: --resume saved")
    output = stream.getvalue()
    assert "⟡ Proposed changes: [red]literal[/red]" in output
    assert "Accept: --okresume saved" in output
    assert "! Error:" in output and "Resume: --resume saved" in output
    assert "\x1b[2J" not in output and delays == []
