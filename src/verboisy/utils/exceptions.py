"""
Custom exception hierarchy for Verboisy.
"""


class VerboisyError(Exception):
    """Base exception for all Verboisy related errors."""

    def __init__(self, message: str, details: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NavigationError(VerboisyError):
    """Raised when the browser fails to navigate or locate an element."""

    pass


class ExtractionError(VerboisyError):
    """Raised when data extraction or schema validation fails."""

    pass


class PlanningError(VerboisyError):
    """Raised when the LLM planner fails to generate a valid next action."""

    pass


class LLMError(VerboisyError):
    """Raised when an API call to the underlying LLM provider fails."""

    pass
