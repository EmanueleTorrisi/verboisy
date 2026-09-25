"""
Rich console wrappers for spinners, live panels, and tables.
"""

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text

console = Console()


class CLIUserInterface:
    """Provides structured terminal UI components for Verboisy CLI."""

    @staticmethod
    def print_header(title: str, subtitle: str) -> None:
        """Display a formatted panel header."""
        panel = Panel(
            Text(subtitle, style="bold cyan"),
            title=Text(title, style="bold green"),
            expand=False,
        )
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
    def display_results_table(data: list[dict[str, Any]]) -> None:
        """
        Display extracted dictionary data in a formatted Rich table.
        Limits to first 5 rows and 5 columns for terminal readability.
        """
        if not data:
            console.print("[yellow]No data was extracted during this run.[/yellow]")
            return

        table = Table(show_header=True, header_style="bold magenta")

        # Get up to 5 headers
        headers = list(data[0].keys())[:5]
        for header in headers:
            table.add_column(Text(header))

        # Add up to 5 rows
        for row in data[:5]:
            row_values = [str(row.get(h, ""))[:50] for h in headers]
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
