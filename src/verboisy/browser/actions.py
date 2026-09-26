"""Strict, bounded interactions. Failures require observation, never force clicks."""

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from verboisy.core.state import ActionRequest
from verboisy.utils.exceptions import BrowserActionError


async def interact(page: Page, request: ActionRequest, timeout_ms: int) -> None:
    parameters = request.parameters
    operation = request.action.lower()
    try:
        locator = page.locator(parameters["selector"])
        if request.action == "CLICK":
            await locator.click(timeout=timeout_ms)
        elif request.action == "CHECK":
            await locator.set_checked(parameters["checked"], timeout=timeout_ms)
        elif request.action == "SELECT":
            await locator.select_option(value=parameters["value"], timeout=timeout_ms)
        else:  # TYPE, validated by ActionRequest and dispatched by Agent.
            operation = "fill"
            await locator.fill(parameters["text"], timeout=timeout_ms)
            if parameters.get("submit", True):
                operation = "submit"
                await locator.press("Enter", timeout=timeout_ms)
    except PlaywrightError as exc:
        raise BrowserActionError(
            f"Browser {operation} failed ({type(exc).__name__}). "
            "The action may have partly executed. Inspect the current page, choose one "
            "observed visible control, and verify its state before retrying. "
            "Do not repeat an unchanged failed selector or bypass actionability checks.",
            details={"error_type": type(exc).__name__},
        ) from None
