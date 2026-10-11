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
        """Display up to five rows and five columns for terminal readability."""
        if not data:
            console.print("[yellow]No data was extracted during this run.[/yellow]")
            return

        table = Table(show_header=True, header_style="bold magenta")
        headers = list(data[0].keys())[:5]

        for header in headers:
            table.add_column(Text(header))

        for row in data[:5]:
            row_values = [str(row.get(header, ""))[:50] for header in headers]
            table.add_row(*(Text(value) for value in row_values))

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
