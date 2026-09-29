"""Offline regression tests for provider rate-limit retry handling."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from verboisy.llm.client import LLMClient
from verboisy.utils.config import settings
from verboisy.utils.exceptions import LLMError


class FakeProviderError(Exception):
    """Simulate provider errors without making network requests."""

    def __init__(
        self,
        message="temporary rate limit",
        *,
        status=429,
        headers=None,
        response_status=None,
        exception_headers=None,
        code=None,
    ):
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


def success_response():
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
    """Return the result/error and mocks from an entirely offline call."""

    completion = AsyncMock(side_effect=list(responses))
    sleeping = AsyncMock()

    config = settings.model_copy(
        update={
            "llm_retries": 2,
            "llm_min_interval_seconds": 0,
            "max_total_tokens": 1_000_000,
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
        patch(
            "random.uniform",
            return_value=0,
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
    ("headers", "expected_delay"),
    [
        (None, 15),
        ({"Retry-After": "4"}, 4),
        ({"retry-after": "3"}, 3),
        ({"Retry-After": "not-a-date"}, 15),
        ({"Retry-After": "nan"}, 15),
        ({"Retry-After": "inf"}, 15),
        (
            {"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"},
            1,
        ),
        (
            {"Retry-After": "Wed, 21 Oct 2015 07:28:00"},
            1,
        ),
    ],
)
async def test_rate_limit_retry_delays(
    headers,
    expected_delay,
):
    result, error, completion, sleeping = await invoke(
        FakeProviderError(headers=headers),
        success_response(),
    )

    assert error is None
    assert result == {"results": []}
    assert completion.await_count == 2
    sleeping.assert_awaited_once_with(expected_delay)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("insufficient_quota", None),
        ("tokens per day exceeded", None),
        ("ordinary provider error", "insufficient_quota"),
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
    assert "quota" in str(error).lower()
    assert completion.await_count == 1
    sleeping.assert_not_awaited()


@pytest.mark.asyncio
async def test_status_code_from_response():
    result, error, completion, sleeping = await invoke(
        FakeProviderError(
            status=None,
            response_status=429,
            headers={"Retry-After": "2"},
        ),
        success_response(),
    )

    assert error is None
    assert result == {"results": []}
    assert completion.await_count == 2
    sleeping.assert_awaited_once_with(2)


@pytest.mark.asyncio
async def test_retry_after_on_exception_headers():
    result, error, completion, sleeping = await invoke(
        FakeProviderError(exception_headers={"RETRY-AFTER": "3"}),
        success_response(),
    )

    assert error is None
    assert result == {"results": []}
    assert completion.await_count == 2
    sleeping.assert_awaited_once_with(3)


@pytest.mark.asyncio
async def test_excessive_retry_after_stops():
    result, error, completion, sleeping = await invoke(
        FakeProviderError(headers={"Retry-After": "121"}),
    )

    assert result is None
    assert isinstance(error, LLMError)
    assert "two minutes" in str(error)
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
    sleeping.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_retries_are_bounded():
    result, error, completion, sleeping = await invoke(
        FakeProviderError(),
        FakeProviderError(),
        FakeProviderError(),
    )

    assert result is None
    assert isinstance(error, LLMError)
    assert "429" in str(error)
    assert completion.await_count == 3
    assert sleeping.await_count == 2
    assert [call.args[0] for call in sleeping.await_args_list] == [15, 30]


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
    assert "400" in str(error)
    assert completion.await_count == 1
    sleeping.assert_not_awaited()
