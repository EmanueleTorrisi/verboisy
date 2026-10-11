# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

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


class LLMResponseError(LLMError):
    """Raised when an LLM response cannot be safely consumed."""

    pass


class LLMRateLimitError(LLMError):
    """Provider temporarily rate-limited the current research run."""

    pass


class BudgetExceededError(VerboisyError):
    """The invocation's model budget has been exhausted."""


class SearchBudgetExceededError(BudgetExceededError):
    """The run has exhausted its separate search-attempt budget."""


class ResumeError(VerboisyError):
    """No unique saved run could be restored."""


class BrowserActionError(VerboisyError):
    """An interaction failed; observe the page again before deciding what to do."""


class SearchUnavailableError(VerboisyError):
    """Search could not produce a usable response; pause without claiming completion."""
