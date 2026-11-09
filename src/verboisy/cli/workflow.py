# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Validate a reusable workflow without acquiring sources or opening a ledger."""

import json
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from verboisy.utils.exceptions import VerboisyError
from verboisy.workflows import WorkflowDefinition, read_workflow


def _validate(definition: WorkflowDefinition) -> None:
    from verboisy.evidence.models import TaskSpec
    from verboisy.extractor.schema_builder import SchemaBuilder
    from verboisy.product import parse_simple_schema
    from verboisy.research_contract import validate_research_contract
    from verboisy.time_series import validate_time_series

    schema = SchemaBuilder.normalize(
        parse_simple_schema(definition.schema)
        if isinstance(definition.schema, list)
        else definition.schema
    )
    task = TaskSpec.model_validate(definition.task)
    validate_research_contract(schema, task)
    item = schema["items"] if schema["type"] == "array" else schema
    validate_time_series(
        task.time_series, list(item.get("properties", {})), None, False, task.identity_fields
    )


def workflow_check_command(
    workflow: Annotated[Path, typer.Argument(help="Versioned workflow JSON file.")],
    sha256: Annotated[
        str | None, typer.Option("--sha256", help="Require this exact file fingerprint.")
    ] = None,
) -> None:
    """Validate and identify a workflow without running it or reading its data inputs."""
    try:
        definition = read_workflow(workflow, expected_sha256=sha256)
        _validate(definition)
    except ValidationError:
        typer.echo("Error: Invalid workflow task specification", err=True)
        raise typer.Exit(1) from None
    except VerboisyError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(1) from None
    typer.echo(
        json.dumps(
            {
                "workflow_origin": definition.origin(),
                "required_inputs": definition.inputs,
                "validated": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
