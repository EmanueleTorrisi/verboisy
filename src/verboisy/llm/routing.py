# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Deterministic, provider-scoped selection from an approved model catalog."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from verboisy.llm.providers import ResolvedProvider, resolve_provider
from verboisy.provider_config import PRIMARY_ROLES, ApprovedModel, ModelRole
from verboisy.utils.exceptions import LLMError

if TYPE_CHECKING:
    from verboisy.utils.config import Settings

_DEFAULT_INPUT: dict[ModelRole, int] = {
    "semantic_plan": 8_192,
    "source_assessment": 32_768,
    "extraction": 32_768,
    "escalation": 32_768,
}


@dataclass(frozen=True)
class ModelRoute:
    model: str
    estimated_microdollars: int
    planned_input_tokens: int
    output_tokens: int
    selection: str


@dataclass(frozen=True)
class ModelRouting:
    provider: str
    routes: dict[ModelRole, ModelRoute]
    context_by_model: dict[str, int]
    transport_by_model: dict[str, ResolvedProvider]

    def model_for(self, role: ModelRole) -> str:
        return (self.routes.get(role) or self.routes["extraction"]).model

    def transport_for(self, model: str) -> ResolvedProvider:
        transport = self.transport_by_model.get(model)
        if transport is None:
            raise LLMError("Requested model is outside the approved provider routes")
        return transport

    def validate_request(self, model: str, units: int) -> None:
        if units > self.context_by_model[model]:
            raise LLMError("Model request exceeds the selected model's configured context")

    def summary(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "roles": {
                role: {
                    "model": route.model,
                    "selection": route.selection,
                    "planned_input_tokens": route.planned_input_tokens,
                    "output_tokens": route.output_tokens,
                    "estimated_microdollars": route.estimated_microdollars,
                }
                for role, route in self.routes.items()
            },
        }


def _eligible_cost(
    config: "Settings", candidate: ApprovedModel, input_tokens: int
) -> tuple[int, ResolvedProvider] | None:
    transport = resolve_provider(config, candidate.model)
    if transport.prefix is None and (config.litellm_api_base or config.litellm_api_key):
        # Only an explicit profile may authorize an endpoint or key for this provider.
        return None
    output_tokens = transport.max_tokens
    if (
        output_tokens > candidate.max_output_tokens
        or input_tokens + output_tokens > candidate.context_tokens
        or (transport.response_mode == "json_object" and not candidate.json_object)
    ):
        return None
    price = (
        input_tokens * candidate.input_price_microdollars_per_million
        + output_tokens * candidate.output_price_microdollars_per_million
    )
    return price, transport


def plan_model_routing(config: "Settings", model: str | None = None) -> ModelRouting | None:
    """Resolve approved roles once; callers retain the same routes for a run."""
    policy = config.llm_model_routing
    if policy is None:
        return None

    routes: dict[ModelRole, ModelRoute] = {}
    context_by_model: dict[str, int] = {}
    transport_by_model: dict[str, ResolvedProvider] = {}
    extraction_override = model or (
        config.litellm_model if "litellm_model" in config.model_fields_set else None
    )
    roles: tuple[ModelRole, ...] = (*PRIMARY_ROLES, "escalation")
    for role in roles:
        configured = getattr(config, f"{role}_model")
        if role == "extraction" and not configured:
            configured = extraction_override
        input_tokens = policy.input_tokens_by_role.get(role, _DEFAULT_INPUT[role])
        options = [item for item in policy.models if role in item.roles]
        if role == "escalation" and not configured and not options:
            continue
        if configured:
            options = [item for item in options if item.model == configured]
        eligible = []
        for item in options:
            rated = _eligible_cost(config, item, input_tokens)
            if rated is not None:
                price, transport = rated
                eligible.append((price, item.model, item.context_tokens, transport))
        if not eligible:
            label = (
                "The explicit model is incompatible with"
                if configured
                else "No approved model fits"
            )
            raise LLMError(f"{label} the {role} role for the selected provider")
        price, selected, context, transport = min(eligible, key=lambda item: (item[0], item[1]))
        routes[role] = ModelRoute(
            model=selected,
            estimated_microdollars=(price + 999_999) // 1_000_000,
            planned_input_tokens=input_tokens,
            output_tokens=transport.max_tokens,
            selection="explicit" if configured else "least_estimated_cost",
        )
        context_by_model[selected] = context
        transport_by_model[selected] = transport
    return ModelRouting(policy.provider, routes, context_by_model, transport_by_model)
