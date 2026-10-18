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
        """Show every result field and at most five records, fitted to the terminal."""
        from rich import box
        from rich.cells import cell_len

        if not data:
            console.print("[yellow]No data was extracted during this run.[/yellow]")
            return

        headers = list(dict.fromkeys(key for row in data for key in row))
        sample = data[:5]

        def display_value(value: Any) -> str:
            text = "null" if value is None else str(value)
            return "".join(
                f"\\u{ord(char):04x}" if ord(char) < 32 or 127 <= ord(char) < 160 else char
                for char in text
            )

        names = [display_value(header) for header in headers]
        values = [[display_value(row.get(header, "")) for header in headers] for row in sample]
        contents = [[name, *(row[index] for row in values)] for index, name in enumerate(names)]
        widths = [
            max([1, *(cell_len(char) for text in column for char in text)])
            for column in contents
        ]
        desired = [max(1, *(cell_len(text) for text in column)) for column in contents]
        padding = 1 if len(headers) <= 7 else 0
        overhead = len(headers) + 1 + 2 * padding * len(headers)
        if sum(widths) + overhead > console.width:
            padding = 0
            overhead = len(headers) + 1

        if not headers:
            console.print("[yellow]The returned records contain no fields.[/yellow]")
        elif sum(widths) + overhead > console.width:
            console.print(
                "[dim]Terminal too narrow for one table; showing every field by record.[/dim]"
            )
            for index, row in enumerate(values, start=1):
                table = Table(
                    title=f"Record {index}", header_style="bold magenta", width=console.width
                )
                table.add_column("Field", overflow="fold")
                table.add_column("Value", overflow="fold")
                for name, value in zip(names, row, strict=True):
                    table.add_row(Text(name), Text(value))
                console.print(table)
        else:
            remaining = console.width - overhead - sum(widths)
            while remaining > 0:
                candidates = [
                    index for index in range(len(headers)) if widths[index] < desired[index]
                ]
                if not candidates:
                    break
                index = min(candidates, key=lambda position: (widths[position], position))
                widths[index] += 1
                remaining -= 1
            table = Table(
                show_header=True,
                header_style="bold magenta",
                box=box.SQUARE,
                show_lines=True,
                padding=(0, padding),
                width=sum(widths) + overhead,
            )
            for name, width in zip(names, widths, strict=True):
                table.add_column(
                    Text(name), width=width, min_width=width, max_width=width,
                    overflow="fold", no_wrap=False,
                )
            for row in values:
                table.add_row(*(Text(value) for value in row))
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
