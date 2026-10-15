<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Display preferences

Display preferences affect exported values and their portable lineage. They do not
change accepted evidence, research requirements, identity matching or budgets.
Defaults are kilograms, metres and DD/MM/YYYY.

## Configure and inspect defaults

```dotenv
VERBOISY_MASS_UNIT=kg
VERBOISY_LENGTH_UNIT=m
VERBOISY_DATE_FORMAT=dmy
```

```bash
poetry run verboisy presentation-config
poetry run verboisy run --resume RUN_ID --mass-unit lb --length-unit ft --date-format iso
```

`presentation-config` reports configured defaults only. It does not open a database,
inspect a saved run, make provider calls or print credential values. Use a saved run's
`presentation_preferences` events or export manifest to inspect its recorded choices.

| Choice | Environment variable | Python settings field | Accepted values |
| --- | --- | --- | --- |
| Mass | `VERBOISY_MASS_UNIT` | `display_mass_unit` | `kg`, `lb`, `source` |
| Length | `VERBOISY_LENGTH_UNIT` | `display_length_unit` | `m`, `ft`, `source` |
| Date | `VERBOISY_DATE_FORMAT` | `display_date_format` | `dmy`, `mdy`, `iso`, `source` |

The process environment takes precedence over `.env`, following the standard
settings loader. An explicit `Settings(...)` field takes precedence over either.
Unsupported choices fail validation before a run opens its ledger.

## Precedence during a run

For each display choice, Verboisy uses the first supplied value in this order:

1. An explicit CLI flag or `arun`/`run` argument.
2. The last saved display choice for the run.
3. The configured default.
4. The built-in default.

| Situation | Result |
| --- | --- |
| New run, no overrides | Configured defaults are saved for that run. |
| Resume, no overrides | Saved preferences remain in effect even after `.env` changes. |
| Resume with `--mass-unit lb` | Mass changes to pounds; saved date and length choices remain. |
| Older run with no saved preferences | Current defaults are saved at its next invocation. |
| Saved snapshot lacks one preference | Current defaults fill only the missing choice. |

Changing display preferences does not accept a research proposal. `--resume` declines
a pending proposal; `--okresume` accepts it. An incomplete run continues research
when resumed. A completed run can re-export saved data without new provider work.

## Supported measurements

| Dimension | Recognized display labels |
| --- | --- |
| Mass | `kg`, `kilogram`, `kilograms`; `g`, `gram`, `grams`; `lb`, `lbs`, `pound`, `pounds` |
| Length | `m`, `meter`, `meters`, `metre`, `metres`; `cm`; `mm`; `km`, `kilometer`, `kilometers`, `kilometre`, `kilometres`; `ft`, `foot`, `feet`; `in`, `inch`, `inches` |

Numeric cells require a unit verified against accepted source evidence or a replayable
declared dataset unit projection. Column names are insufficient. Prior normalization
is replayed to prevent double scaling. Grouped conversions require matching effective
units from every contributor. Unit-base dataset projections retain their own narrower
canonical-unit vocabulary; display settings do not extend the ingestion parser.

Text cells require a complete explicit measurement, such as `100 lb` or
`100 - 120 lb`. A range needs two observed endpoints. Bare `m` and `in` in text need
`"x-verboisy-dimension": "length"` on the field, because these labels have other meanings.
Scientific notation is not supported in unit-bearing text; finite numeric cells can
use the numeric notation admitted by their extraction contract.

Unknown units, missing or conflicting bindings, lower bounds, rates and shortened
scale expressions do not authorize conversion. Ounces, stone, yards, currency,
temperature and custom unit expressions are currently unsupported.

Successful numeric conversions retain numeric column types; string-mode columns
remain strings. Rounding uses six decimal places and half-even rounding. Original
precision stays in evidence. Values that cannot be represented safely remain unchanged,
without a false target-unit claim. Target units and verified bindings appear in cell
lineage in the export manifest; a unit column is not added automatically.

`source` preserves the effective ledger value. If an accepted value was already
normalized to grams or metres, this option does not undo that normalization.

## Supported dates

| Preference | Display of the ISO date `2026-10-08` |
| --- | --- |
| `dmy` | `08/10/2026` |
| `mdy` | `10/08/2026` |
| `iso` | `2026-10-08` |
| `source` | `2026-10-08` |

Formatting requires a schema field with `format: date` or `format: date-time` and a
valid ISO value. Date-times require a timezone designator; clock time, fractional
seconds and the original offset are preserved. No timezone conversion occurs.
Ambiguous local dates, invalid calendar dates and arbitrary format patterns are not
interpreted. Reference-year projections are a separate grounded ingestion operation.

## Evidence and schema checks

Sorting, grouping and identity matching happen before presentation. Protected identity
fields remain unchanged. Display steps record their input, output and preferences;
numeric steps also record source units, target units and evidence bindings.

The manifest keeps the original extraction schema. A localized date, a fractional
conversion of an integer field, or a changed unit-dependent bound can make
`collection_schema_valid` false for the export view. This does not rewrite the source
contract or invalidate otherwise accepted source records. Inspect the evidence and
cell lineage alongside the output when the displayed schema check differs.


## Referenced fields

Local references resolve through the shared schema index once per output generation.
An inline `{"type":"string","format":"date"}` and a local `$defs` reference to that
schema both display `2026-10-08` as `08/10/2026` under DMY preferences. Numeric dimensions
use the same conservative rules; names do not imply dates or units.

Generated IDs, declared identity/matching values and raw evidence remain protected.
Display output may differ from the collection schema, which manifests disclose.
Ambiguous explicit format/dimension policies fail research preflight.

---

[Overview](index.md) · [CLI](cli.md) · [API](api.md) · [Licensing](licensing.md)
