# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

import verboisy.cli.ui as ui
from rich.console import Console
from rich.progress import Progress
from verboisy.cli.ui import CLIUserInterface


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
    assert "... and 2 more rows." in output


def test_display_results_table_with_empty_record(monkeypatch) -> None:
    test_console = make_console()
    monkeypatch.setattr(ui, "console", test_console)

    CLIUserInterface.display_results_table([{}])

    output = test_console.export_text()
    assert "The first returned record contains no fields." in output


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
