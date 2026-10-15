<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# SmartID

SmartID creates foreign-key-like relationships between a new dataset and a previous Verboisy CSV or JSON file.

```bash
verboisy run \
  --goal "Find public details about these people" \
  --schema '[name,surname,company,age,nationality]' \
  --smartid people.csv \
  --export demographics.csv
```

If the previous file is named `people.csv`, the relationship column is `person_id`.

## Matching rules

The current implementation is conservative.

Strong exact identifiers are preferred, including URLs, domains, SKU-like identifiers, ISBN-like identifiers, and email addresses when present.

A name is not enough by itself. Name-based matching requires additional exact context. If multiple previous rows still qualify, the relation is `null`.

## Input validation

SmartID input is treated as untrusted data. CSV and JSON inputs are checked for:

- UTF-8 decoding;
- supported file format;
- valid CSV headers;
- object-shaped JSON rows;
- required stable `id` values;
- duplicate IDs;
- file-size limits.

## Provenance

The manifest and proof path can record:

- relation field name;
- matched prior ID;
- fields that contributed to the match;
- candidate prior IDs;
- exact, ambiguous, or unresolved outcome.

## Current limitation

SmartID currently resolves relationships after extraction. The planned relational research planner will use the previous dataset itself as the input entity set, allowing a new schema such as `[age,nationality]` without repeating identifying columns.

Until that planner is implemented, include enough identifying fields in the researched output for the relationship to be audited safely.

## Identifier integrity

Conflicting nonempty strong identifiers veto a match, even when another strong
field agrees. Strong identifiers use exact, type-preserving comparison: SKU case,
URL path case, trailing slashes, and string versus integer identifiers are not
silently normalized. This can leave equivalent but differently formatted values
unresolved; review or normalize them under an explicit domain policy first.

Ambiguous prior IDs are reported deterministically even when their types differ.
An existing output column with the proposed relation name causes an error rather
than being overwritten.

These safeguards do not establish globally unique namespaces or automatically
resolve entity identity. The existing name-plus-context fallback remains in use;
review relationships before treating them as verified entity joins.

## Declared compound keys

When a run declares `--identity` fields (or `task.identity_fields`), SmartID uses
that saved key for linking too. Every pointer must exist in both rows and match
exactly. There is no single-field or name-based fallback for a declared key.
Matching nonempty string or integer components are supported; other component
types remain unresolved. Nested object pointers and escaped field names work.
Additional conflicting strong identifiers still veto a link.

For example, `--identity /namespace --identity /sku` distinguishes the same SKU
used by separate source namespaces. Missing namespaces remain unresolved, and
multiple prior IDs for the complete key remain ambiguous. Resume reuses the saved
key. Runs with no declared key retain the existing SmartID heuristics.


## Verified reference loading and resume

References are bounded to 50,000,000 bytes and 100,000 rows. Files must be regular,
unchanged during reading, with unique nonempty supported IDs. JSON is strict and finite;
CSV requires unique nonblank headers, strict syntax and exact row widths.

An adjacent manifest is bounded to 1 MiB and verifies the primary file's exact hash.
Ordinary format-3 JSON CSV has literal headers and JSON cells; stream-1 JSON CSV encodes
headers too. Empty ordinary JSON cells mean absence; `null` means observed null.
Plain CSV stays text, without guessed JSON types. Spreadsheet escaping retains text
semantics. Unsupported/malformed existing manifests fail without fallback.

Both reference and potential sidecar are protected publication inputs. New SmartID
events bind file/manifest hashes and mode; resume rejects changed references. Historical
unbound events establish a first verified binding labelled unrecorded, without claiming
retroactive verification. Checksums establish consistency, not authenticity. Matching
remains conservative and exact; source IDs require ordinary explicit projection.

---

[Overview](index.md) · [CLI](cli.md) · [API](api.md) · [Licensing](licensing.md)
