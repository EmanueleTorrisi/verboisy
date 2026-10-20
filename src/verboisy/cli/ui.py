# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Compact terminal presentation of real run state, records and exported artifacts."""

import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from rich.cells import cell_len
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.style import Style
from rich.table import Table
from rich.text import Text

console = Console()


def _pause(seconds: float, animate: bool) -> None:
    if animate and console.is_terminal:
        time.sleep(seconds)


def _type_line(value: str, *, animate: bool, signoff: bool = False) -> None:
    style = "italic #4B0082" if signoff else ""
    if not animate or not console.is_terminal:
        console.print(Text(value, style=style))
        return
    for char in value:
        console.print(Text(char, style=style), end="", soft_wrap=True)
        if signoff:
            if char == ",":
                time.sleep(0.1)
            time.sleep(0.02)
        else:
            if char == "✦":
                time.sleep(1)
            if char == " ":
                time.sleep(0.03)
            time.sleep(0.005)
    time.sleep(0.6 if signoff else 1)
    console.print()


def _message(value: str) -> str:
    # Preserve line boundaries while treating messages as literal terminal text.
    return "\n".join(_single_line(line) for line in value.splitlines())


def _single_line(value: Any) -> str:
    text = "".join(" " if ord(char) < 32 or 127 <= ord(char) < 160 else char for char in str(value))
    return " ".join(text.split())


def _shorten(text: str, width: int) -> str:
    if cell_len(text) <= width:
        return text
    suffix = "." * min(3, width)
    remaining = width - len(suffix)
    prefix = []
    # The overlong input necessarily exhausts the available cell width.
    for char in text:  # pragma: no branch
        size = cell_len(char)
        if size > remaining:
            break
        prefix.append(char)
        remaining -= size
    return "".join(prefix) + suffix


def _fields(data: list[dict[str, Any]]) -> list[str]:
    return list(dict.fromkeys(key for row in data for key in row))


def _artifact_uri(path: str | Path) -> str:
    uri = Path(path).absolute().as_uri()
    # Windows Terminal opens links on Windows, so a WSL file needs its UNC address.
    distro = os.environ.get("WSL_DISTRO_NAME")
    if sys.platform == "linux" and os.environ.get("WT_SESSION") and distro:
        return f"file://wsl.localhost/{quote(distro, safe='')}{urlsplit(uri).path}"
    return uri


class RunDisplay:
    """Show a persisted run identity and replace the running line only on a TTY."""

    def __init__(self, *, animate: bool = False) -> None:
        self.run_id: str | None = None
        self.live: Live | None = None
        self.animate = animate

    def started(self, run_id: str, goal: str) -> None:
        if self.run_id is not None:
            return
        self.run_id = run_id
        _pause(0.5, self.animate)
        _type_line("✦ " + _single_line(goal), animate=self.animate)
        _pause(1, self.animate)
        console.print(Text("⟡ Run ID: " + _single_line(run_id)))
        console.print()
        _pause(1.5, self.animate)
        status = Text("Status: ")
        if console.is_terminal:
            self.live = Live(status, console=console, auto_refresh=False, transient=True)
            self.live.start(refresh=True)
            _pause(3, self.animate)
            status.append("running...", style="grey70")
            self.live.update(status, refresh=True)
        else:
            status.append("running...", style="grey70")
            console.print(status)

    def close(self) -> None:
        if self.live is not None:
            self.live.stop()
            self.live = None

    def finish(self, status: str) -> None:
        self.close()
        style = {
            "COMPLETED": "bright_green",
            "PAUSED": "yellow",
            "INTERRUPTED": "yellow",
            "FAILED": "bright_red",
        }.get(status, "white")
        text = Text("Status: ")
        text.append(_single_line(status), style=style)
        console.print(text)
        console.print()
        if status == "COMPLETED":
            _pause(3, self.animate)


class CLIUserInterface:
    """Structured terminal UI components for normal CLI usage."""

    @staticmethod
    def print_header(title: str, subtitle: str, *, animate: bool = False) -> None:
        _pause(1, animate)
        panel = Panel(
            Text(_single_line(subtitle), style="#8A2BE2"),
            title=Text(_single_line(title), style="#4169E1"),
            expand=False,
        )
        console.print()
        console.print(panel)
        console.print()
        _pause(2, animate)

    @staticmethod
    def print_error(message: str) -> None:
        console.print(Text("! Error: " + _message(message), style="bold red"), soft_wrap=True)

    @staticmethod
    def print_notice(message: str) -> None:
        text = Text("⟡ ", style="#4169E1")
        text.append(_message(message).removeprefix("* "))
        console.print(text, soft_wrap=True)

    @staticmethod
    def print_success(message: str) -> None:
        console.print(Text("Success: " + message, style="bold green"))

    @staticmethod
    def print_signoff(*, animate: bool = False) -> None:
        console.print()
        _pause(2, animate)
        _type_line("Thank you, and best of luck with your work.", animate=animate, signoff=True)
        console.print()
        _pause(0.3, animate)

    @staticmethod
    def display_results_table(
        data: list[dict[str, Any]], *, label: str = "CSV", animate: bool = False
    ) -> None:
        """Show five actual rows, six fields and the actual omitted-column count."""
        if not data:
            console.print("[yellow]No data was extracted during this run.[/yellow]")
            return

        all_headers = _fields(data)
        if not all_headers:
            console.print("[yellow]The returned records contain no fields.[/yellow]")
            return
        headers = all_headers[:6]
        hidden = len(all_headers) - len(headers)
        names = [_single_line(header) for header in headers]
        values = [[_single_line(row.get(header, "")) for header in headers] for row in data[:5]]
        if hidden:
            names.append(f"⋯ {hidden} more columns →")
            for row in values:
                row.append("⋯")

        widths = [
            min(50, max(1, cell_len(name), *(cell_len(row[index]) for row in values)))
            for index, name in enumerate(names)
        ]
        padding = 1
        overhead = 3 * len(names) + 1
        if sum(min(width, 3) for width in widths) + overhead > console.width:
            padding = 0
            overhead = len(names) + 1
        available = console.width - overhead
        if available < len(names):
            console.print("[yellow]Widen the terminal to display the results preview.[/yellow]")
            return
        while sum(widths) > available:
            index = max(range(len(widths)), key=lambda position: widths[position])
            widths[index] -= 1

        console.print(Text(f"{label} preview: first {len(values)} of {len(data)} rows."))
        table = Table(header_style="bold", padding=(0, padding), width=sum(widths) + overhead)
        for index, (name, width) in enumerate(zip(names, widths, strict=True)):
            table.add_column(
                Text(_shorten(name, width)),
                width=width,
                min_width=width,
                max_width=width,
                no_wrap=True,
                overflow="crop",
                style="dim" if hidden and index == len(names) - 1 else "",
            )
        for row in values:
            table.add_row(
                *(Text(_shorten(value, width)) for value, width in zip(row, widths, strict=True))
            )
        console.print(table)
        _pause(4, animate)

    @staticmethod
    def display_json_preview(data: list[dict[str, Any]], *, animate: bool = False) -> None:
        """Preview three records and six source fields, without changing exported values."""
        if not data:
            return
        fields = [key for key in _fields(data) if key != "id"]
        selected = fields[:6]
        sample = [{key: row[key] for key in selected if key in row} for row in data[:3]]
        console.print()
        console.print(
            Text(
                f"JSON preview: first {len(sample)} of {len(data)} rows; "
                f"{len(selected)} of {len(fields)} source columns."
            )
        )
        text = json.dumps(sample, ensure_ascii=False, allow_nan=False, indent=2)
        # Escape controls that JSON permits literally but terminals may interpret.
        text = "".join(
            f"\\u{ord(char):04x}" if 127 <= ord(char) < 160 or char in "\u2028\u2029" else char
            for char in text
        )
        lines = text.splitlines()
        clipped = len(lines) > 50 or any(cell_len(line) > console.width for line in lines[:50])
        for line in lines[:50]:
            console.print(Text(_shorten(line, console.width)), soft_wrap=True)
        if clipped:
            console.print(
                Text("… Preview shortened; the underlying records retain the full values.", "dim")
            )
        console.print()
        _pause(3, animate)

    @staticmethod
    def print_artifact(label: str, path: str | Path, *, animate: bool = False) -> None:
        text = Text(f"→ {label:>6}: ")
        text.append(
            _single_line(path),
            style=Style(color="white", underline=True, link=_artifact_uri(path)),
        )
        console.print(text, soft_wrap=True)
        if label in {"CSV", "JSON"}:
            _pause(1, animate)

    @staticmethod
    def create_spinner() -> Progress:
        return Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
            console=console,
        )
