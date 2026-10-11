# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""HTTP acquisition limits and redirect policy are enforced before destination fetch."""

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from verboisy.extractor.dataset import DatasetParseError
from verboisy.extractor.download import DatasetDownloadError, download_dataset
from verboisy.utils.config import Settings

START = "https://example.test/people.csv"


class Stream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            if isinstance(chunk, BaseException):
                raise chunk
            yield chunk

    async def aclose(self):
        self.closed = True


def reply(status=200, headers=None, chunks=None):
    return httpx.Response(
        status,
        headers={"content-type": "text/csv", **(headers or {})},
        stream=Stream([b"person\nAnais\n"] if chunks is None else chunks),
    )


@pytest.fixture
def fixture(monkeypatch):
    requests = []
    responses = []
    original = httpx.AsyncClient
    dns = AsyncMock()
    monkeypatch.setattr("verboisy.extractor.download.validate_url", dns)

    def handle(request):
        requests.append(request)
        value = responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr(
        "verboisy.extractor.download.httpx.AsyncClient",
        lambda **kw: original(
            transport=httpx.MockTransport(handle),
            **{key: value for key, value in kw.items() if key != "transport"},
        ),
    )
    return requests, responses, dns


async def fetch(**kwargs):
    return await download_dataset(
        START,
        Settings(_env_file=None),
        dataset_format="csv",
        permits=lambda url: url.startswith("https://example.test/"),
        **kwargs,
    )


async def test_raw_bytes_headers_filename_and_stream_cleanup(fixture):
    requests, responses, _ = fixture
    response = reply(
        headers={
            "content-disposition": 'attachment; filename="../../outside.csv"',
            "content-length": "13",
        }
    )
    responses.append(response)
    result = await fetch()
    assert result.dataset.original_bytes == b"person\nAnais\n"
    assert result.dataset.rows[0].values == {"person": "Anais"}
    assert result.original_url == result.final_url == START
    assert result.redirect_chain == (START,)
    assert "../" in result.remote_disposition
    assert response.is_closed
    assert requests[0].headers["accept-encoding"] == "identity"


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
async def test_allowed_relative_redirect(fixture, status):
    requests, responses, _ = fixture
    responses.extend([reply(status, {"location": "/data.csv"}), reply()])
    result = await fetch()
    assert result.final_url == "https://example.test/data.csv"
    assert result.redirect_chain == (START, result.final_url)
    assert len(requests) == 2


@pytest.mark.parametrize(
    "destination",
    ["https://outside.test/data.csv", "http://127.0.0.1/data.csv", "file:///data.csv"],
)
async def test_scope_redirect_never_fetches_destination(fixture, destination):
    requests, responses, dns = fixture
    responses.append(reply(302, {"location": destination}))
    with pytest.raises(DatasetDownloadError, match="scope"):
        await fetch()
    assert len(requests) == 1
    assert dns.await_count == 1


async def test_second_hop_is_checked(fixture):
    requests, responses, _ = fixture
    responses.extend(
        [
            reply(302, {"location": "/next.csv"}),
            reply(302, {"location": "https://outside.test/data.csv"}),
        ]
    )
    with pytest.raises(DatasetDownloadError, match="scope"):
        await fetch()
    assert len(requests) == 2


@pytest.mark.parametrize(
    "headers,message",
    [
        ({"content-encoding": "gzip"}, "Compressed"),
        ({"content-type": "text/html"}, "content type"),
        ({"content-length": "-1"}, "content length"),
        ({"content-length": "NaN"}, "content length"),
        ({"content-length": "١٣"}, "content length"),
        ({"content-length": "1025"}, "byte limit"),
        ({"content-length": "12"}, "length mismatch"),
    ],
)
async def test_response_headers_and_length(fixture, headers, message):
    _, responses, _ = fixture
    # Non-ASCII header values are represented by their raw UTF-8 bytes.
    raw_headers = {key: value.encode() for key, value in headers.items()}
    response = reply(headers=raw_headers)
    responses.append(response)
    with pytest.raises(DatasetDownloadError, match=message):
        await fetch(max_bytes=1024)
    assert response.is_closed


async def test_stream_limit_applies_without_content_length(fixture):
    _, responses, _ = fixture
    response = reply(chunks=[b"person\n", b"x" * 1024])
    responses.append(response)
    with pytest.raises(DatasetDownloadError, match="byte limit"):
        await fetch(max_bytes=1024)
    assert response.is_closed


async def test_html_disguised_as_csv_is_rejected(fixture):
    _, responses, _ = fixture
    responses.append(reply(chunks=[b"<!doctype html><html>Access denied</html>"]))
    with pytest.raises(DatasetParseError, match="Markup"):
        await fetch()


@pytest.mark.parametrize(
    "case,message", [("missing", "no location"), ("loop", "loop"), ("limit", "redirect limit")]
)
async def test_redirect_errors(fixture, case, message):
    requests, responses, _ = fixture
    responses.append(
        reply(
            302, {} if case == "missing" else {"location": START if case == "loop" else "/data.csv"}
        )
    )
    with pytest.raises(DatasetDownloadError, match=message):
        await fetch(max_redirects=0 if case == "limit" else 5)
    assert len(requests) == 1


async def test_status_failure(fixture):
    _, responses, _ = fixture
    responses.append(reply(404))
    with pytest.raises(DatasetDownloadError, match="HTTP 404"):
        await fetch()


@pytest.mark.parametrize(
    "error", [httpx.ConnectError("Sensitive detail"), TimeoutError("Sensitive detail")]
)
async def test_transport_errors_are_redacted(fixture, error):
    _, responses, _ = fixture
    responses.append(error)
    with pytest.raises(DatasetDownloadError) as caught:
        await fetch()
    assert "Sensitive detail" not in str(caught.value)


async def test_cancellation_closes_stream_and_propagates(fixture):
    _, responses, _ = fixture
    response = reply(chunks=[asyncio.CancelledError()])
    responses.append(response)
    with pytest.raises(asyncio.CancelledError):
        await fetch()
    assert response.is_closed


@pytest.mark.parametrize(
    "limits",
    [
        {"max_bytes": 0},
        {"max_rows": -1},
        {"max_depth": 0},
        {"max_redirects": -1},
        {"timeout_seconds": 0},
    ],
)
async def test_invalid_limits_precede_network(fixture, limits):
    requests, _, dns = fixture
    with pytest.raises(ValueError):
        await fetch(**limits)
    assert requests == []
    dns.assert_not_awaited()


async def test_unsupported_format():
    with pytest.raises(DatasetDownloadError, match="format"):
        await download_dataset(
            START, Settings(_env_file=None), dataset_format="unknown", permits=lambda _url: True
        )


async def test_private_address_rejected_before_request():
    with pytest.raises(DatasetDownloadError, match="network policy"):
        await download_dataset(
            "http://127.0.0.1/data.csv",
            Settings(_env_file=None, allow_private_network=False),
            dataset_format="csv",
            permits=lambda _url: True,
        )


async def test_actual_timeout(fixture, monkeypatch):
    _, responses, _ = fixture
    responses.append(reply())

    async def wait(url, config):
        await asyncio.sleep(1)

    monkeypatch.setattr("verboisy.extractor.download.validate_url", wait)
    with pytest.raises(DatasetDownloadError, match="TimeoutError"):
        await fetch(timeout_seconds=0.001)


@pytest.mark.parametrize(
    "kind,mime,body",
    [
        ("json", "application/json", b'[{"person":"Anais"}]'),
        ("jsonl", "application/x-ndjson", b'{"person":"Anais"}\n'),
    ],
)
async def test_json_formats(fixture, kind, mime, body):
    _, responses, _ = fixture
    responses.append(reply(headers={"content-type": mime}, chunks=[body]))
    result = await download_dataset(
        START, Settings(_env_file=None), dataset_format=kind, permits=lambda _url: True
    )
    assert result.dataset.rows[0].values == {"person": "Anais"}


async def test_long_filename_remains_bounded_metadata(fixture):
    _, responses, _ = fixture
    responses.append(reply(headers={"content-disposition": "x" * 3000}))
    result = await fetch()
    assert len(result.remote_disposition) == 1024


async def test_malformed_redirect_location_is_redacted(fixture):
    requests, responses, _ = fixture
    responses.append(reply(302, {"location": "http://["}))
    with pytest.raises(DatasetDownloadError, match="ValueError"):
        await fetch()
    assert len(requests) == 1


@pytest.mark.parametrize("timeout", [float("nan"), float("inf")])
async def test_nonfinite_timeout_rejected(fixture, timeout):
    requests, _, _ = fixture
    with pytest.raises(ValueError):
        await fetch(timeout_seconds=timeout)
    assert requests == []


@pytest.mark.parametrize(
    "limits",
    [
        {"max_bytes": float("inf")},
        {"max_rows": float("inf")},
        {"max_depth": float("inf")},
        {"max_redirects": float("inf")},
        {"max_bytes": True},
        {"max_rows": 1.5},
    ],
)
async def test_count_limits_require_finite_integers(fixture, limits):
    requests, _, dns = fixture
    with pytest.raises(ValueError):
        await fetch(**limits)
    assert requests == []
    dns.assert_not_awaited()
