# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Provider failure hints from recognized structured fields, never raw response text."""

from typing import Any

_CODES = {
    "unsupported_parameter",
    "unsupported_value",
    "invalid_parameter",
    "invalid_value",
    "model_not_found",
    "context_length_exceeded",
    "invalid_api_key",
}
_PARAMETERS = {
    "max_tokens",
    "max_completion_tokens",
    "temperature",
    "response_format",
    "model",
    "messages",
}


def provider_failure_message(error: Exception, status: Any) -> str:
    """Describe a failed request without copying provider messages, URLs or credentials."""
    body = getattr(error, "body", None)
    structured = body if isinstance(body, dict) else {}
    nested = structured.get("error")
    if isinstance(nested, dict):
        structured = nested
    code = getattr(error, "code", None)
    if not isinstance(code, str) or code not in _CODES:
        code = structured.get("code")
    param = getattr(error, "param", None)
    if not isinstance(param, str) or param not in _PARAMETERS:
        param = structured.get("param")
    safe_status = status if isinstance(status, int) and not isinstance(status, bool) else None
    parts = [type(error).__name__, f"HTTP {safe_status}"]
    if isinstance(code, str) and code in _CODES:
        parts.append(f"code={code}")
    if isinstance(param, str) and param in _PARAMETERS:
        parts.append(f"parameter={param}")
    if safe_status == 401:
        hint = "Check the configured provider API key and endpoint."
    elif safe_status == 403:
        hint = "Check provider permissions and model access."
    elif safe_status == 404:
        hint = "Check the configured model identifier, provider and endpoint."
    elif safe_status == 400 and param == "messages":
        hint = "Check message structure and explicit JSON output instructions."
    elif safe_status == 400:
        hint = "Check model compatibility with max_tokens, temperature and JSON response_format."
    else:
        hint = "Check provider limits and configuration."
    return f"LLM request failed ({', '.join(parts)}); {hint}"
