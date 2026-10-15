# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Invalid model JSON consumes bounded attempts and retains request reservations."""

from unittest.mock import AsyncMock

import pytest
from verboisy.llm.client import LLMClient
from verboisy.utils.exceptions import LLMResponseError

from tests.test_llm.test_client import response


@pytest.mark.parametrize(
    "content", ['{"x":1,"x":2}', '{"x":1e999}', '"\\ud800"', '{"x":"\\udfff"}', "[]", ""]
)
async def test_invalid_model_json_reservations(config, monkeypatch, content):
    config.llm_retries = 1
    config.llm_min_interval_seconds = 0
    transport = AsyncMock(return_value=response(content))
    monkeypatch.setattr("verboisy.llm.client._complete", transport)
    client = LLMClient(config=config)
    with pytest.raises(LLMResponseError, match="invalid or incomplete JSON"):
        await client.complete_json("system", "user")
    assert transport.await_count == 2 and client.reserved_tokens > 0 and client.total_tokens == 14
