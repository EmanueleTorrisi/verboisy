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
