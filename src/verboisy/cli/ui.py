# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Rich console helpers for the Verboisy CLI."""

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text

console = Console()


class CLIUserInterface:
    """Structured terminal UI components for normal CLI usage."""

    @staticmethod
    def print_header(title: str, subtitle: str) -> None:
        """Display the product banner with one blank line above and below."""
        panel = Panel(
            Text(subtitle, style="bold cyan"),
            title=Text(title, style="bold green"),
            expand=False,
        )
        console.print()
        console.print(panel)
        console.print()

    @staticmethod
    def print_error(message: str) -> None:
        """Display a formatted error message."""
        console.print(Text("Error: " + message, style="bold red"))

    @staticmethod
    def print_success(message: str) -> None:
        """Display a formatted success message."""
        console.print(Text("Success: " + message, style="bold green"))

    @staticmethod
    def print_signoff() -> None:
        """Display the closing message after a successful run."""
        message = Text("Thank you, and ")
        message.append("best of luck with your work", style="bold")
        message.append(".")
        console.print()
        console.print(message)
        console.print()

    @staticmethod
    def display_results_table(data: list[dict[str, Any]]) -> None:
        """Preview five rows and five columns, clipping long text with three dots."""
        from rich.cells import cell_len

        if not data:
            console.print("[yellow]No data was extracted during this run.[/yellow]")
            return

        headers = list(data[0])[:5]
        if not headers:
            console.print("[yellow]The first returned record contains no fields.[/yellow]")
            return

        def single_line(value: Any) -> str:
            text = "".join(
                " " if ord(char) < 32 or 127 <= ord(char) < 160 else char for char in str(value)
            )
            return " ".join(text.split())

        def shorten(text: str, width: int) -> str:
            if cell_len(text) <= width:
                return text
            suffix = "." * min(3, width)
            remaining = width - len(suffix)
            prefix = []
            for char in text:
                size = cell_len(char)
                if size > remaining:
                    break
                prefix.append(char)
                remaining -= size
            return "".join(prefix) + suffix

        names = [single_line(header) for header in headers]
        values = [[single_line(row.get(header, "")) for header in headers] for row in data[:5]]
        widths = [
            min(50, max(1, cell_len(name), *(cell_len(row[index]) for row in values)))
            for index, name in enumerate(names)
        ]
        padding = 1
        overhead = 3 * len(headers) + 1
        if sum(min(width, 3) for width in widths) + overhead > console.width:
            padding = 0
            overhead = len(headers) + 1
        available = console.width - overhead
        if available < len(headers):
            console.print("[yellow]Widen the terminal to display the results preview.[/yellow]")
            return
        while sum(widths) > available:
            index = max(range(len(widths)), key=lambda position: widths[position])
            widths[index] -= 1

        table = Table(
            show_header=True,
            header_style="bold magenta",
            padding=(0, padding),
            width=sum(widths) + overhead,
        )
        for name, width in zip(names, widths, strict=True):
            table.add_column(
                Text(shorten(name, width)),
                width=width,
                min_width=width,
                max_width=width,
                no_wrap=True,
                overflow="crop",
            )
        for row in values:
            table.add_row(
                *(Text(shorten(value, width)) for value, width in zip(row, widths, strict=True))
            )
        console.print(table)

        if len(data) > 5:
            console.print(f"[dim]... and {len(data) - 5} more rows.[/dim]")

    @staticmethod
    def create_spinner() -> Progress:
        """Create a progress context manager with a spinner."""
        return Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
            console=console,
        )
