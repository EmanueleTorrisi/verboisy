# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Dataset credentials are origin-scoped and cannot override transport policy."""

import pytest
from pydantic import ValidationError
from verboisy.extractor.download import download_dataset
from verboisy.source_config import dataset_request_headers, http_origin
from verboisy.utils.config import Settings

from tests.test_extractor import test_dataset_download as downloads
from tests.test_extractor.test_dataset_download import reply

fixture = downloads.fixture


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://EXAMPLE.test:443/path", "https://example.test"),
        ("http://example.test:80/path", "http://example.test"),
        ("http://example.test:8123/path", "http://example.test:8123"),
        ("https://[::1]:443/", "https://[::1]"),
    ],
)
def test_origin_normalization(url, expected):
    assert http_origin(url) == expected


@pytest.mark.parametrize(
    "origin",
    [
        "file:///data",
        "https:///no-host",
        "https://user:secret@example.test",
        "https://example.test/path",
        "https://example.test/?key=secret",
        "https://example.test/#secret",
        "https://example.test:wrong",
        "https://example.test\n",
    ],
)
def test_invalid_credential_origin(origin):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, dataset_http_headers={origin: {"Authorization": "PRIVATE"}})


@pytest.mark.parametrize(
    "header,value",
    [
        ("Host", "bad"),
        ("Accept-Encoding", "gzip"),
        ("Content-Length", "42"),
        ("Connection", "keep-alive"),
        ("Transfer-Encoding", "chunked"),
        ("Proxy-Authorization", "secret"),
        ("bad header", "value"),
        ("Authorization", "token\nnext"),
        ("Authorization", "token\rnext"),
    ],
)
def test_unsafe_credential_headers(header, value):
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, dataset_http_headers={"https://example.test": {header: value}})
    assert "input_value" not in str(error.value)


def test_duplicate_origins_and_case_folded_headers():
    for profiles in [
        {"https://example.test": {}, "https://EXAMPLE.test:443/": {}},
        {"https://example.test": {"Authorization": "first", "authorization": "second"}},
    ]:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, dataset_http_headers=profiles)


@pytest.mark.parametrize(
    "destination",
    ["https://other.test/data", "http://example.test/data", "https://example.test:444/data"],
)
async def test_redirect_drops_origin_credentials_and_response_cookies(fixture, destination):
    requests, responses, _ = fixture
    config = Settings(_env_file=None)
    config.dataset_http_headers = Settings(
        _env_file=None,
        dataset_http_headers={"https://example.test": {"Authorization": "Bearer PRIVATE"}},
    ).dataset_http_headers
    responses.extend(
        [
            reply(302, {"location": destination, "set-cookie": "session=PRIVATE; Path=/; Secure"}),
            reply(),
        ]
    )
    await download_dataset(
        "https://example.test/data", config, dataset_format="csv", permits=lambda _: True
    )
    assert requests[0].headers["authorization"] == "Bearer PRIVATE"
    assert "authorization" not in requests[1].headers
    assert "cookie" not in requests[1].headers


async def test_same_origin_redirect_uses_configured_headers(fixture):
    requests, responses, _ = fixture
    config = Settings(_env_file=None)
    config.dataset_http_headers = Settings(
        _env_file=None,
        dataset_http_headers={
            "https://example.test": {"Authorization": "Bearer PRIVATE", "Cookie": "explicit=value"}
        },
    ).dataset_http_headers
    responses.extend([reply(302, {"location": "/next"}), reply()])
    await download_dataset(
        "https://example.test/data", config, dataset_format="csv", permits=lambda _: True
    )
    assert all(request.headers["authorization"] == "Bearer PRIVATE" for request in requests)
    assert all(request.headers["cookie"] == "explicit=value" for request in requests)
    assert dataset_request_headers(config.dataset_http_headers, "https://other.test") == {}
