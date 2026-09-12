"""
Typer application entrypoint for the Verbosiy CLI.
"""

import asyncio
import json
from pathlib import Path
import typer

from verboisy.core.agent import Agent
from verboisy.storage.exporters import DataExporter
from verboisy.cli.ui import CLIUserInterface

app = typer.Typer(
    name="verboisy",
    help="⛏️ Verboisy: Autonomous web research and scrape-to-JSON agent.",
    add_completion=False
)


@app.command("run")
def run_agent(
    goal: str = typer.Option(..., "--goal", "-g", help="The research objective or starting point."),
    schema_path: Path = typer.Option(..., "--schema", "-s", help="Path to the target JSON schema file.", exists=True),
    export_path: Path = typer.Option(None, "--export", "-e", help="File path to save the extracted results (CSV or JSON)."),
    max_steps: int = typer.Option(20, "--max-steps", "-m", help="Maximum number of browser actions allowed.")
) -> None:
    """Start an autonomous web research run based on a goal and a schema."""
    CLIUserInterface.print_header("Verboisy Agent", "Autonomous Web Extraction Initialized")

    # Load JSON schema
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            target_schema = json.load(f)
    except Exception as e:
        CLIUserInterface.print_error(f"Failed to load schema from {schema_path}: {e}")
        raise typer.Exit(code=1)

    agent = Agent(goal=goal, target_schema=target_schema, max_steps=max_steps)

    # Execute async agent loop with UI spinner
    try:
        with CLIUserInterface.create_spinner() as progress:
            progress.add_task(description=f"[cyan]Executing goal: {goal}...", total=None)
            final_state = asyncio.run(agent.run())
    except KeyboardInterrupt:
        CLIUserInterface.print_error("Run aborted by user.")
        raise typer.Exit(code=1)
    except Exception as e:
        CLIUserInterface.print_error(f"Agent execution failed unexpectedly: {e}")
        raise typer.Exit(code=1)

    # Display results summary
    if final_state.status == "COMPLETED":
        CLIUserInterface.print_success(f"Agent finished successfully in {final_state.step_count} steps.")
        CLIUserInterface.display_results_table(final_state.extracted_data)

        # Export data if requested
        if export_path and final_state.extracted_data:
            try:
                if export_path.suffix.lower() == ".csv":
                    DataExporter.export_csv(final_state.extracted_data, export_path)
                else:
                    DataExporter.export_json(final_state.extracted_data, export_path)
                CLIUserInterface.print_success(f"Exported data to {export_path}")
            except Exception as e:
                CLIUserInterface.print_error(f"Failed to export data: {e}")
    else:
        CLIUserInterface.print_error(f"Agent run failed. Status: {final_state.status}")


if __name__ == "__main__":
    app()
