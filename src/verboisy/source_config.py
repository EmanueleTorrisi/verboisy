# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Origin-scoped acquisition credentials, kept outside persisted research tasks."""

import re
from urllib.parse import urlsplit

from pydantic import SecretStr


def http_origin(url: str) -> str:
    """Normalize scheme, host and effective port without retaining URL secrets."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("HTTP credentials require an HTTP(S) origin")
    host = parsed.hostname.lower()
    host = f"[{host}]" if ":" in host else host
    port = parsed.port
    suffix = "" if port is None or port == (443 if parsed.scheme == "https" else 80) else f":{port}"
    return f"{parsed.scheme}://{host}{suffix}"


def validate_http_headers(
    profiles: dict[str, dict[str, SecretStr]],
) -> dict[str, dict[str, SecretStr]]:
    """Reject ambiguous origins and headers that could override transport policy."""
    checked: dict[str, dict[str, SecretStr]] = {}
    reserved = {
        "host",
        "content-length",
        "accept-encoding",
        "connection",
        "transfer-encoding",
        "proxy-authorization",
    }
    for url, headers in profiles.items():
        parsed = urlsplit(url)
        origin = http_origin(url)
        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or origin in checked
            or any(ord(character) < 32 for character in url)
        ):
            raise ValueError("Dataset credential keys must be unique HTTP(S) origins")
        for name, secret in headers.items():
            if (
                not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name)
                or name.lower() in reserved
                or "\r" in secret.get_secret_value()
                or "\n" in secret.get_secret_value()
            ):
                raise ValueError("Dataset credential header violates transport policy")
        if len({name.lower() for name in headers}) != len(headers):
            raise ValueError("Dataset credential headers must have unique names")
        checked[origin] = headers
    return checked


def dataset_request_headers(profiles: dict[str, dict[str, SecretStr]], url: str) -> dict[str, str]:
    """Resolve every hop independently; redirect destinations never inherit headers."""
    return {
        name: value.get_secret_value() for name, value in profiles.get(http_origin(url), {}).items()
    }
