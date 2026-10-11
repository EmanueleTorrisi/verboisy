<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Dataset contract

The schema is owned by the caller. Draft 2020-12 is supported, with local references.
An object schema validates each record; an array schema additionally validates the
collection at completion. No metadata keys are injected into records. Types are not
coerced. Optional absence differs from explicit null.

Every accepted non-null leaf has a JSON Pointer, source ID, quoted span or actual
observed href, and a deterministic transformation. Nested arrays use numeric indices;
property names escape `~` as `~0` and `/` as `~1`. Text is whitespace-normalized, not
paraphrased. Numbers use unambiguous decimal literals. A quote must match a lexical
span, not a digit or word fragment inside another value.

An additional model review checks field meanings, research criteria and entity
association. This review can be wrong. Evidence proves what was observed, not that
the publisher's assertion is true. Required unsupported fields reject the candidate.
Nullable unknowns are exported only when the schema allows them and `allow_nulls` is true.
Empty arrays/objects are conservatively unsupported as field values by the literal
verifier; they are not proof that a source has no members. Derived summaries, arbitrary
unit conversion, date interpretation and cross-page joins are not automatic.

Task options are strict: unknown keys produce configuration errors. `seed_urls` is a
list of real HTTP(S) locations. Without it, goal URLs are used; without either, Brave
provides at most ten discovery leads. Search snippets are never extraction evidence.
`allowed_hosts` uses exact hostnames, not wildcard suffixes. If omitted, seed hosts
form the crawl boundary. `include_paths` and `exclude_paths` use shell-style glob
patterns on URL paths, not regexes or query strings. Navigation depth starts at zero.

`target_records` is explicit; a natural-language number alone is not an executable
completion contract. `identity_fields` contains JSON Pointers; declare stable business
identifiers when you need entity counts. Otherwise equality means exact record equality.
Conflicting identities quarantine both versions and prevent completion. There is no
automatic fuzzy merging. Start a reviewed replacement run after resolving conflicts.

`max_pages` is cumulative. `--max-steps` limits visits during one invocation. Exceeding
link, depth, snapshot or pagination limits produces visible coverage gaps. The engine
considers observed HTML links and explicit pagination only; unobserved hidden controls
and open-web completeness are unknown. Target completion may leave a pending frontier.

Example user-owned field rules:

```json
{
  "field_rules": {
    "/source_url": {"source": "page_url"},
    "/official_site": {"source": "link", "external": true},
    "/available": {"mapping": {"true": "In stock", "false": "Out of stock"}}
  }
}
```

Mappings use JSON-encoded output values as keys. Rule pointers are exact; there are
no wildcard field rules. `external` means a different hostname, not independently
verified company ownership. The semantic review must still reject a founder's social
link when a company website is requested. With no explicit page-url rule, the model
cannot turn the currently visited profile into an invented website value.

The manifest is written last. Check its file hashes before using a generation; a crash
between writes may leave a dataset without a valid manifest. JSON is canonical. CSV
JSON mode encodes each present data cell with `json.dumps`; empty means absent, `null` means
null. Spreadsheet mode escapes formula-like strings and intentionally loses the
missing/null distinction. Never mix the two modes in a pipeline without recording it.

JSON-mode headers preserve field names exactly for programmatic readers. For spreadsheets
use spreadsheet mode, which also escapes formula-like headers.

---

[Overview](index.md) · [CLI](cli.md) · [API](api.md) · [Licensing](licensing.md)
