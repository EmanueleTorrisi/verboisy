"""Reject malformed model instructions before any side effect."""

import pytest
from pydantic import ValidationError
from verboisy.core.state import ActionRequest


@pytest.mark.parametrize(
    "action,parameters",
    [
        ("NAVIGATE", {}),
        ("CLICK", {"selector": ""}),
        ("TYPE", {"selector": "#q"}),
        ("SCROLL", {"pixels": True}),
        ("SCROLL", {"pixels": 10001}),
        ("WAIT", {"milliseconds": -1}),
        ("TYPE", {"selector": "#q", "text": "x", "submit": "yes"}),
        ("EXTRACT", {"file": "/tmp/x"}),
        ("FINISH", {"command": "anything"}),
        ("CHECK", {"selector": "#filter"}),
        ("CHECK", {"selector": "#filter", "checked": "true"}),
        ("SELECT", {"selector": "#industry"}),
    ],
)
def test_invalid_actions(action, parameters):
    with pytest.raises(ValidationError):
        ActionRequest(thought="fixture", action=action, parameters=parameters)


def test_clear_input_is_valid():
    request = ActionRequest(
        thought="Clear", action="TYPE", parameters={"selector": "#q", "text": ""}
    )
    assert request.parameters["text"] == ""


@pytest.mark.parametrize(
    ("action", "parameters"),
    [
        ("NAVIGATE", {"url": "x" * 8001}),
        ("CLICK", {"selector": "x" * 8001}),
        ("TYPE", {"selector": "#q", "text": "x" * 8001}),
    ],
)
def test_required_parameters_exceed_maximum_length(action, parameters):
    """Reject required string parameters longer than 8000 characters."""
    with pytest.raises(ValidationError, match="exceeds 8000 characters"):
        ActionRequest(
            thought="fixture",
            action=action,
            parameters=parameters,
        )


def test_required_parameter_at_maximum_length():
    """Accept a required string parameter of exactly 8000 characters."""
    request = ActionRequest(
        thought="fixture",
        action="NAVIGATE",
        parameters={"url": "x" * 8000},
    )

    assert len(request.parameters["url"]) == 8000


def test_select_empty_option_and_uncheck_are_valid():
    assert (
        ActionRequest(
            thought="Reset", action="SELECT", parameters={"selector": "select", "value": ""}
        ).parameters["value"]
        == ""
    )
    assert (
        ActionRequest(
            thought="Uncheck", action="CHECK", parameters={"selector": "#batch", "checked": False}
        ).parameters["checked"]
        is False
    )
