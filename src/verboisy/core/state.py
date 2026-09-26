"""Serializable state and validated planner actions."""

import uuid
from datetime import UTC, datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thought: str
    action: Literal[
        "NAVIGATE",
        "SEARCH",
        "CLICK",
        "TYPE",
        "CHECK",
        "SELECT",
        "SCROLL",
        "WAIT",
        "EXTRACT",
        "FINISH",
    ]
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_parameters(self) -> Self:
        required = {
            "NAVIGATE": ("url",),
            "SEARCH": ("query",),
            "CLICK": ("selector",),
            "TYPE": ("selector", "text"),
            "CHECK": ("selector",),
            "SELECT": ("selector", "value"),
        }
        allowed = {
            **required,
            "TYPE": ("selector", "text", "submit"),
            "CHECK": ("selector", "checked"),
            "SCROLL": ("pixels",),
            "WAIT": ("milliseconds",),
            "EXTRACT": (),
            "FINISH": (),
        }
        for key in required.get(self.action, ()):
            value = self.parameters.get(key)
            if not isinstance(value, str) or (key not in ("text", "value") and not value.strip()):
                raise ValueError(f"{self.action} requires a string '{key}' parameter")
            if len(value) > 8000:
                raise ValueError(f"{key} exceeds 8000 characters")
        if set(self.parameters) - set(allowed[self.action]):
            raise ValueError(f"Unexpected parameters for {self.action}")
        for key, low, high in (("pixels", -10000, 10000), ("milliseconds", 0, 10000)):
            if key in self.parameters:
                value = self.parameters[key]
                if (
                    not isinstance(value, int)
                    or isinstance(value, bool)
                    or not low <= value <= high
                ):
                    raise ValueError(f"{key} must be an integer between {low} and {high}")
        if "submit" in self.parameters and not isinstance(self.parameters["submit"], bool):
            raise ValueError("submit must be a boolean")
        if self.action == "CHECK" and not isinstance(self.parameters.get("checked"), bool):
            raise ValueError("CHECK requires a boolean 'checked' parameter")
        return self


class ActionHistory(BaseModel):
    action: str
    parameters: dict[str, Any]
    url: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ActionAttempt(BaseModel):
    """Checkpoint intent before dispatch, without model thoughts or typed text."""

    step: int
    action: str
    selector: str | None = None
    url: str


class ActionFailure(ActionAttempt):
    error_type: str
    message: str


class SearchResult(BaseModel):
    title: str
    url: str = Field(min_length=1, max_length=8000)
    description: str = ""


class SearchObservation(BaseModel):
    provider: Literal["brave"] = "brave"
    query: str
    results: list[SearchResult]


class AgentState(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    goal: str
    target_schema: dict[str, Any]
    history: list[ActionHistory] = Field(default_factory=list)
    extracted_data: list[dict[str, Any]] = Field(default_factory=list)
    status: Literal["INITIALIZED", "RUNNING", "COMPLETED", "FAILED", "PAUSED", "INTERRUPTED"] = (
        "INITIALIZED"
    )
    current_url: str | None = None
    step_count: int = Field(default=0, ge=0)
    max_steps: int = Field(default=20, gt=0)
    token_count: int = Field(default=0, ge=0)
    export_path: str | None = None
    stop_reason: str | None = None
    pending_action: ActionAttempt | None = None
    action_failures: list[ActionFailure] = Field(default_factory=list)
    search_observation: SearchObservation | None = None
