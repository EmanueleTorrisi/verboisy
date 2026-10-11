<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# File capabilities

Run `poetry run verboisy formats` to inspect the implemented format contracts.
Choose the format explicitly with `--dataset-file FORMAT=PATH` or
`--dataset-source FORMAT=URL`. An extension, media type or embedded link never
selects a parser, invokes a model, or authorizes another source.

| Declaration | Support level | Output records | Important boundaries |
| --- | --- | --- | --- |
| `csv` | Deterministic parse | Header-keyed strings | UTF-8; unique nonempty headers; exact row widths |
| `tsv` | Deterministic parse | Header-keyed strings | Same strict contract, tab delimiter; quoted multiline fields supported |
| `json` | Deterministic parse | Array of typed objects | Duplicate keys, non-finite values and scalar rows rejected |
| `jsonl` | Deterministic parse | Typed objects | One object per nonblank physical line; source line locations retained |
| `text` | Deterministic parse | `{"text": "observed line"}` | UTF-8 plain text/Markdown; physical lines, including blank lines; no markup interpretation |
| `docx` | Deterministic parse | `{"text": "observed paragraph"}` | Main-body paragraphs, including table paragraphs; tabs and breaks retained |
| `xlsx` | Deterministic parse | `{"sheet": "name", "values": {...}}` | First physical row supplies unique text headers; typed observed cell values |
| `asset` | Capture and index | `{"sha256": "...", "byte_count": 123}` | Arbitrary immutable bytes; contents are not interpreted |

All modes preserve original bytes and their SHA-256 hash in the existing asset
store and portable export bundle. Row evidence references the captured asset and
its line or part locator. Resume replays captured bytes; removing the original
file does not remove its evidence. Output rows still require the supplied schema,
explicit projections and the normal verification rules.

There is no model-assisted file adapter in this inventory. PDF, images, audio,
video, archives, columnar/scientific files and other binary formats can be
captured with `asset`; this does not extract their text, objects, samples or tables.
Capture is useful for building a verifiable file index, not a substitute for a
format-specific interpretation adapter. No format is advertised merely because
its bytes can be preserved.

## Deterministic document and worksheet extraction

The Office adapters read selected OOXML parts in memory. DOCX emits paragraphs
in main-body order with locators such as `/word/document.xml/paragraphs/1`.
Headers, footers, comments, drawings, page layout and OCR are outside that contract.
No macros, external references or embedded files execute or acquire new sources.
Strict OOXML namespace variants and legacy `.doc`/`.xls` are not supported.

XLSX emits worksheets in workbook order, with physical-row locators such as
`/xl/worksheets/sheet1.xml/rows/3`. The first row of each sheet must contain
unique, nonempty text headers with no missing header cells. Data cells omitted
within those columns become JSON nulls; explicit empty strings remain strings.
Rows must have increasing valid Excel row numbers. Cells beyond the declared
headers, repeated addresses and rows wider than 1,024 columns are rejected.
Hidden rows/sheets are included: this is an observed-cell table, not a rendered view.
Merged-cell layout is not reconstructed.

Inline and shared text, booleans, numeric cells and explicitly typed ISO date
strings are supported. Plain integer lexemes retain integer precision; fractional
and exponent lexemes use finite Python floating-point values, as JSON parsing does.
Styles are not used to infer dates or units: Excel date serials remain numeric.
Phonetic guides do not become visible shared text. Formula cells are rejected,
including cached formula results. Calculate a separate values-only worksheet
outside Verboisy if evaluation is required; no formula is silently executed.

The adapters follow the main-document and workbook/worksheet structures described
in Microsoft's [WordprocessingML documentation](https://learn.microsoft.com/en-us/office/open-xml/word/structure-of-a-wordprocessingml-document)
and [SpreadsheetML documentation](https://learn.microsoft.com/en-us/office/open-xml/spreadsheet/structure-of-a-spreadsheetml-document).
These are deliberately limited extraction contracts, not full Office renderers.

## Capture an arbitrary file

```bash
poetry run verboisy run --goal 'Index the supplied file' \
  --schema '[sha256,byte_count]' \
  --dataset-file 'asset=/srv/verboisy-inputs/report.pdf' \
  --export files.json
```

Grant `/srv/verboisy-inputs` through `DATASET_LOCAL_ROOTS` first. The file's exact
bytes travel in the portable bundle; the exported JSON/CSV row is an index record.
Inspect `verboisy assets --run-id RUN_ID` for capture metadata and support level.
Content type is not restricted in explicit `asset` mode, while source scope,
origin credentials, redirect authorization, TLS, DNS pinning and byte limits
remain in force. HTTP content encoding must remain identity; arbitrary ZIP/gzip
file bytes can be captured, but are not automatically expanded.

## Bounds and rejection behavior

Current default acquisition is 16 MiB and 100,000 output records per asset.
These adapters are not streaming or qualified for gigabyte-scale inputs.
Office archives additionally allow at most 1,024 entries, 16 MiB combined declared
uncompressed size and a 200:1 maximum per-entry expansion ratio. Members are never
extracted to disk. Unsafe paths, symlink members, duplicate entries, encryption and
compression methods other than stored/deflate are rejected. XML permits at most
100,000 nodes per part and the configured nesting depth; DTD/entity declarations,
malformed parts and non-UTF-8 XML are rejected before producing output.

These limits are part of the current bounded adapter contract. A rejected source
is recorded through the existing failure outcome, not presented as a completed
interpretation. To retain a file that falls outside a parser contract, select
`asset` explicitly; Verboisy does not silently downgrade parsing to capture.
