# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Offline regression tests for provider retry and rate-limit handling."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from verboisy.llm.client import LLMClient
from verboisy.utils.config import settings
from verboisy.utils.exceptions import LLMError, LLMRateLimitError


class FakeProviderError(Exception):
    """Simulate provider errors without making network requests."""

    def __init__(
        self,
        message: str = "temporary rate limit",
        *,
        status: int | None = 429,
        headers: dict[str, str] | None = None,
        response_status: int | None = None,
        exception_headers: dict[str, str] | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)

        if status is not None:
            self.status_code = status

        if headers is not None or response_status is not None:
            self.response = SimpleNamespace(
                status_code=response_status,
                headers=headers or {},
            )
        else:
            self.response = None

        if exception_headers is not None:
            self.headers = exception_headers

        if code is not None:
            self.code = code


def success_response() -> SimpleNamespace:
    return SimpleNamespace(
        usage=SimpleNamespace(total_tokens=9),
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content='{"results": []}'),
                finish_reason="stop",
            )
        ],
    )


async def invoke(*responses):
    """Return result/error and mocks from an entirely offline call."""

    completion = AsyncMock(side_effect=list(responses))
    sleeping = AsyncMock()

    config = settings.model_copy(
        update={
            "llm_retries": 2,
            "llm_min_interval_seconds": 0,
            "max_total_tokens": 1_000_000,
            "model_request_budget": 1_000_000,
        }
    )

    with (
        patch(
            "verboisy.llm.client._complete",
            new=completion,
        ),
        patch(
            "verboisy.llm.client.asyncio.sleep",
            new=sleeping,
        ),
    ):
        try:
            result = await LLMClient(config=config).complete_json(
                "Return JSON.",
                "Return an empty results array.",
            )
        except LLMError as error:
            return None, error, completion, sleeping

    return result, None, completion, sleeping


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        FakeProviderError(),
        FakeProviderError(
            headers={"Retry-After": "30"},
        ),
        FakeProviderError(
            exception_headers={"RETRY-AFTER": "30"},
        ),
        FakeProviderError(
            status=None,
            response_status=429,
        ),
    ],
)
async def test_rate_limit_pauses_immediately(error):
    result, failure, completion, sleeping = await invoke(
        error,
        success_response(),
    )

    assert result is None
    assert isinstance(failure, LLMRateLimitError)
    assert str(failure) == "OpenAI rate limit reached"
    assert completion.await_count == 1
    sleeping.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("insufficient_quota", None),
        ("tokens per day exceeded", None),
        (
            "ordinary provider error",
            "insufficient_quota",
        ),
        ("credit_balance_exhausted", None),
    ],
)
async def test_permanent_quota_errors_are_not_retried(
    message,
    code,
):
    result, error, completion, sleeping = await invoke(
        FakeProviderError(
            message,
            code=code,
        ),
    )

    assert result is None
    assert isinstance(error, LLMError)
    assert not isinstance(error, LLMRateLimitError)
    assert "quota" in str(error).lower()
    assert completion.await_count == 1
    sleeping.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        FakeProviderError(
            "temporary server failure",
            status=500,
        ),
        TimeoutError("temporary timeout"),
    ],
)
async def test_other_transient_failures_retry(error):
    result, failure, completion, sleeping = await invoke(
        error,
        success_response(),
    )

    assert failure is None
    assert result == {"results": []}
    assert completion.await_count == 2
    sleeping.assert_awaited_once()

    delay = sleeping.await_args.args[0]
    assert 1 <= delay <= 2


@pytest.mark.asyncio
async def test_nonretryable_http_error():
    result, error, completion, sleeping = await invoke(
        FakeProviderError(
            "bad request",
            status=400,
        ),
    )

    assert result is None
    assert isinstance(error, LLMError)
    assert not isinstance(error, LLMRateLimitError)
    assert "400" in str(error)
    assert completion.await_count == 1
    sleeping.assert_not_awaited()
