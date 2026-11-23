# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Replay completed proposals and reviews only for identical requests in one run."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING, Any, TypeVar

from pydantic import BaseModel

from verboisy.storage.json_payload import decode_saved_json
from verboisy.utils.exceptions import VerboisyError

if TYPE_CHECKING:
    from verboisy.llm.client import LLMClient, ModelRole
    from verboisy.storage.research import ResearchStore

_Response = TypeVar("_Response", bound=BaseModel)
_KIND = "extraction_checkpoint_v1"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _digest(value: Any) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return _sha256(raw)


@dataclass(frozen=True)
class ExtractionJournal:
    store: ResearchStore
    run_id: str
    client: LLMClient

    @cached_property
    def _decision(self) -> int:
        # A user decision starts a new extraction pass, even on the same requirements.
        row = self.store.db.execute(
            "SELECT COALESCE(MAX(id),0) FROM events WHERE run_id=? AND kind='change_decided'",
            (self.run_id,),
        ).fetchone()
        return int(row[0])

    def _route(self, role: ModelRole) -> dict[str, Any]:
        model = self.client.model_for(role)
        provider = self.client.provider_for(model)
        # Only the fingerprint is stored; keys are excluded altogether.
        return {
            "model": model,
            "endpoint": provider.api_base,
            "profile": provider.prefix,
            "response_mode": provider.response_mode,
            "token_parameter": provider.token_limit_parameter,
            "max_tokens": provider.max_tokens,
            "temperature": self.client.config.temperature if provider.send_temperature else None,
        }

    async def complete(
        self,
        stage: str,
        system_prompt: str,
        user_prompt: str,
        response_type: type[_Response],
        request: Callable[[], Awaitable[_Response]],
    ) -> _Response:
        binding = _digest(
            [
                self._decision,
                stage,
                system_prompt,
                user_prompt,
                self._route("extraction"),
                self._route("escalation"),
            ]
        )
        kind = f"{_KIND}:{stage}:{binding}"
        saved = self.store.events(self.run_id, kind)
        if saved:
            try:
                entry = saved[0]["payload"]
                if (
                    len(saved) != 1
                    or not isinstance(entry, dict)
                    or set(entry) != {"result", "sha256"}
                    or not isinstance(entry["result"], str)
                    or _sha256(entry["result"]) != entry["sha256"]
                ):
                    raise ValueError("Invalid checkpoint envelope")
                return response_type.model_validate(decode_saved_json(entry["result"]))
            except (ValueError, TypeError) as error:
                raise VerboisyError(
                    "Saved extraction checkpoint failed integrity verification"
                ) from error

        response = await request()
        # Keep model field order even though event envelopes sort their JSON keys.
        result = response.model_dump_json()
        self.store.event(self.run_id, kind, {"result": result, "sha256": _sha256(result)})
        return response
