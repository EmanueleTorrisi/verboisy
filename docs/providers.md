<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Provider compatibility

Verboisy routes model requests through its existing LiteLLM integration. Provider
profiles make request differences explicit without changing installation, the
research schema, evidence checks or shared budget accounting. They do not certify
every provider or bypass the provider's own authentication requirements.

## Defaults and model-specific profiles

Existing `LITELLM_MODEL`, role-model settings, credentials and gateway settings
retain their behavior when no profile matches. `LLM_RESPONSE_MODE=json_object`
is the default. Set it to `prompt` for a model that does not support the
`response_format` keyword. Both modes require a valid JSON object, and both retain
the trusted JSON instruction and strict response validation. Prompt mode does not
strip Markdown, repair malformed JSON or relax the evidence contract.

`LLM_PROVIDER_PROFILES` is a JSON object keyed by model identifier prefixes.
The longest matching prefix wins, including for escalation models. There is no
automatic provider probe or paid trial request. Profiles have these fields:

| Field | Meaning |
| --- | --- |
| `api_key` | Optional profile credential; stored as a secret setting |
| `api_base` | Optional explicit provider or gateway endpoint |
| `response_mode` | `json_object` (default) or `prompt` |
| `token_limit_parameter` | `max_tokens` or `max_completion_tokens`; absent uses the global setting |
| `max_tokens` | Positive integer output allowance; absent uses global `MAX_TOKENS` |
| `send_temperature` | Boolean; absent uses global `LLM_SEND_TEMPERATURE` |

An explicit profile does **not** inherit Verboisy's global API key or global
endpoint. This prevents the application from forwarding a gateway credential to
a different role's endpoint. If no profile credential is supplied, LiteLLM and
the selected provider SDK may use their own environment credentials or identity
mechanisms. Check those mechanisms separately; this setting is not an operating
system credential sandbox. Endpoints remain operator-controlled configuration.

## Mixed hosted and local models

This example selects an explicitly configured OpenAI-compatible local endpoint
for extraction and a separate gateway model for escalation. Replace identifiers
and credentials with values appropriate to the installed server; these illustrative
names are not advertised as live-tested models.

```dotenv
EXTRACTION_MODEL=openai/local-model
ESCALATION_MODEL=openai/gateway-model
LLM_PROVIDER_PROFILES='{"openai/local-model":{"api_base":"http://127.0.0.1:8000/v1","api_key":"local-server-key","response_mode":"prompt","max_tokens":4096,"send_temperature":false},"openai/gateway-model":{"api_base":"https://gateway.example/v1","api_key":"gateway-key","response_mode":"json_object","max_tokens":2048}}'
```

Keep populated configuration files private. Do not place real secrets in tasks,
schemas, source documents, logs or committed examples. A local extraction model
does not make a whole run offline: other roles, search, browser acquisition and
provider SDK behavior still need a separate no-egress qualification.

## Inspect before transport

```bash
verboisy model-config
```

The report retains its existing fields and adds `effective_provider_settings`
for every role, `provider_profile_count` and the global `response_mode`. Effective
settings show the matched prefix, output allowance, response mode, temperature
choice and credential/endpoint presence. Key and endpoint values are never
serialized. Inspection does not execute providers or open the research database.

Every attempt reserves message bytes plus the **resolved** output allowance before
transport. Failed attempts consume reservation units, and escalation uses the
same ledger and ceiling. Provider-reported tokens remain separate from request
units and from monetary cost. No compatibility fallback sends an unbudgeted
second request or silently changes model settings.

## Qualification boundary

The offline suite checks request construction, role routing, credential isolation,
prompt-mode validation, escalation, budget enforcement and safe inspection using
test transports. It does not measure live provider accuracy or availability.
Qualification must record the installed LiteLLM version, actual model identifier,
endpoint class, response mode and tested authentication mechanism. Run the same
held-out tasks for each advertised provider profile under an approved paid budget.

The integration uses LiteLLM's normalized completion interface. Providers requiring
additional custom authentication or request parameters need an adapter or a
configured gateway; unsupported parameters are not accepted as arbitrary kwargs.
See the upstream [SDK](https://docs.litellm.ai/docs/python_sdk) and
[custom-provider interface](https://docs.litellm.ai/docs/providers/custom_llm_server).


## Role availability and strict responses

Availability resolves the model/profile for the requested role. Semantic planning
and source assessment are independent; a matching explicit profile key or endpoint
enables its own role. Profiles without explicit keys retain provider SDK environment
or identity fallback. Configuration permits an attempt, not authenticated success.
Unprofiled first-party roles preserve the deterministic no-provider path.

Model JSON must be a unique-key, finite, safe UTF-8 object. Invalid responses use bounded
retries and consume each attempt's reserved request units. Inspection makes no paid
probe and prints no key/endpoint values. Configured profiles require separate live
cost/latency and annotated acceptance qualification.

---

[Overview](index.md) · [CLI](cli.md) · [API](api.md) · [Licensing](licensing.md)
