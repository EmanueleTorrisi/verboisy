"""Core state types; orchestration imports are lazy to avoid dependency cycles."""

from typing import Any

from .state import ActionRequest, AgentState

__all__ = ["ActionRequest", "Agent", "AgentState", "Planner"]


def __getattr__(name: str) -> Any:
    if name == "Agent":
        from .agent import Agent

        return Agent
    if name == "Planner":
        from .planner import Planner

        return Planner
    raise AttributeError(name)
