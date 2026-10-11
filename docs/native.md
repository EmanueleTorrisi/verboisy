<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Optional native quote matching

The evidence verifier now finds literal quotes using a portable Python matcher.
It preserves the former regex's Unicode word boundaries and numeric-prefix and
decimal-tail rules. Whitespace normalization remains in the verifier. Matching
does not establish factual truth, infer values, or loosen entity-scope checks.

The first C++ implementation accelerates only this bounded operation. It uses
CPython's Unicode search and character classifications, including non-ASCII
numbers, astral characters and surrogate code points. It does not use a C++ locale,
normalize Unicode, convert strings to UTF-8, or release the GIL. Overlapping valid
occurrences remain visible, and forbidden-prefix runs are skipped to avoid
repeated long-literal searches inside a single word.

## Native source layout

The optional extension has four implementation files, each with one responsibility:

| File | Responsibility |
| --- | --- |
| `native/python_module.cpp` | Python argument validation and module registration |
| `native/quote_match.cpp` | Literal search, overlap handling and boundary decisions |
| `native/unicode_boundaries.cpp` | CPython Unicode word and numeric-prefix classifications |
| `native/quote_batch.cpp` | Bounded batch validation, ordered matching and output ownership |

The three headers declare the scalar, batch and classification interfaces. All four
implementation files compile into the same extension. The Python API, backend
selection, installation and build command are unchanged; ordinary Python usage
needs neither a compiler nor a native binary. The matcher requires Unicode inputs
and the GIL; the adapter validates inputs before calling it.

Build metadata version 2 records `source_hashes` for all four implementations and
three headers, replacing the single-file `source_sha256` field. Benchmark source
hashes also include all seven files so a boundary or binding change remains visible
in performance comparisons. Rebuild the extension after applying this source
reorganization, before running native tests or selecting native mode.

## Build and validate

Run from a source checkout, with the interpreter used by Verboisy:

```bash
poetry run python scripts/build_native.py
poetry run pytest tests/test_quote_match.py tests/test_native_quote_match.py --no-cov -q
```

The builder uses a local C++17 compiler and CPython development headers. It does
not download dependencies, install packages, modify the ledger or contact providers.
`CXX` can select a compiler command. The script supports Linux/WSL and macOS;
Windows-native builds and PyPy currently use the Python fallback. Local validation
was performed on Linux with CPython 3.12. Other interpreters and platforms need
their own build and validation before native mode is used.

The extension and compiler/source/ABI metadata live under ignored `build/native/`.
They are not part of the existing pure-Python wheel. This stage supplies a local
source-build experiment, not portable native release wheels. Do not copy a binary
between interpreter versions or platforms. Rebuild with the target interpreter.

## Explicit backend selection

Python is the default and needs no compiler. These are **shell environment** options:

```bash
VERBOISY_QUOTE_MATCHER=python poetry run python -m benchmarks.runner --case verify --rows 10000 --repeats 3 --output benchmark-results/verify-python.json
VERBOISY_QUOTE_MATCHER=native poetry run python -m benchmarks.runner --case verify --rows 10000 --repeats 3 --output benchmark-results/verify-native.json
VERBOISY_QUOTE_MATCHER=regex poetry run python -m benchmarks.runner --case verify --rows 10000 --repeats 3 --output benchmark-results/verify-regex.json
```

Native mode is explicitly requested; a missing or incompatible extension raises
an actionable error. It does not silently fall back. Set `VERBOISY_QUOTE_MATCHER=python`
to return to the portable implementation. The regex mode retains the old algorithm
for equivalence checks and benchmark comparisons. These experimental switches are
not Settings fields and are not loaded from `.env`.

`VERBOISY_NATIVE_QUOTE_DIR` can select an absolute directory containing the expected
interpreter-specific extension filename. The native module is loaded once per
process. Restart after changing that directory or rebuilding the binary; loaded
shared libraries are not hot-reloaded. Never rebuild a module while a process that
uses it is running. The builder publishes a completed compilation with atomic
replacement; its accompanying JSON is build metadata, not a transactional bundle.

## Measure the actual benefit

The dedicated workload contains eight positive and negative quote cases per source
row, with unique literals and numeric boundaries. All three backends must produce
the same output digest:

```bash
poetry run python -m benchmarks.runner --case quote_regex --case quote_python --case quote_native --rows 10000 --repeats 3 --output benchmark-results/quotes.json
```

These cases are opt-in; the default eight-workload benchmark does not require a
native build. Native reports record the compiled module's SHA-256; source hashes
also include the C++ implementation and builder. Record `build/native/quote-build.json`
with experiments that compare compiler flags or toolchains.

Compare whole-verifier timings as well as matcher timings. A fast isolated helper
does not guarantee the same improvement for research, where schema validation,
network access and model responses still consume time. Keep input sizes, fixtures,
output digests, environment and machine conditions matched.

Differential tests cover the former regex, the Python implementation and the actual
compiled extension, including generated Unicode cases, overlaps, repeated literals,
argument errors, threaded calls and complete verification rejection reasons.
Tests marked `native` skip when the optional binary is absent; the regular Python
suite still checks the loader contract and explicit missing-build error.

## Direct C++ test suites

The production extension also has assertions written directly in C++:

| File | Responsibility |
| --- | --- |
| `native/tests/test_quote_match.cpp` | Expected literal, Unicode, numeric, overlap and repeated-call outcomes |
| `native/tests/test_unicode_boundaries.cpp` | Word character and numeric-prefix classification expectations |
| `native/tests/test_quote_batch.cpp` | Ordered batch results, container errors, maximum size and partial-input rejection |
| `native/tests/python_test_module.cpp` | Test-only Python entry point and exception reporting |
| `native/tests/test_support.hpp` | Reference ownership and assertions that remain active in optimized builds |

Build and execute them with the same interpreter as the production extension:

```bash
poetry run python scripts/build_native_tests.py
poetry run pytest tests/test_native_cpp_suites.py --no-cov -vv
```

This separate test binary links the actual production matcher and boundary
implementations. Python owns interpreter initialization and the GIL; a failed C++
assertion reaches pytest as an exception with its case label. The test suite needs
no third-party C++ framework, download or embedded-interpreter linker setup.
It includes embedded NULs, surrogate code points, Unicode decimal tails, astral
word boundaries and long repeated literals. Tests reject stale source or binary
fingerprints and check repeat execution and argument handling.

The existing `scripts/build_native.py` command and production module are unchanged.
The additional test module and `quote-tests-build.json` remain under ignored
`build/native/`; they are not included in the Python wheel. Rebuild the test module
after changing any linked source, and restart processes that loaded it before a
rebuild. Its tests skip when that separate binary is absent. Python's source
coverage percentage does not measure C++ coverage; these are behavioral C++ tests,
not a claim of complete native line or branch coverage.

## Bounded batch experiment

`verboisy.evidence.quote_batch.quotes_observed` accepts a plain list or tuple of
`(text, quote, numeric)` tuples. Both text inputs must be strings and `numeric`
must be a Boolean. It returns a fresh list of Boolean decisions in input order,
including duplicate inputs, and accepts at most 4096 entries per call. Empty
batches return an empty list. Malformed or oversized input raises without exposing
a partial result. The C++ loop retains the GIL and delegates every match to the
existing scalar implementation; it does not normalize source text or infer values.

The API supports the same explicit Python, regex and native backend selection as
scalar matching. Native mode requires a rebuilt production extension; an older
binary with no batch export reports an actionable rebuild error. Cached bindings
do not cache matching results. Normal installation and user commands remain
unchanged: Python remains the default. Explicit native verification now batches
eligible textual proofs within each candidate, after the existing scope, URL and
dataset gates. Value authorization remains in Python. Quote-related errors retain
their original field order, and identity errors still follow field errors.
Candidates with more than 4096 eligible proofs use consecutive bounded chunks.
This introduces no automatic native selection or changes to evidence acceptance.

Rebuild both binaries and run the batch checks:

```bash
poetry run python scripts/build_native.py
poetry run python scripts/build_native_tests.py
poetry run pytest tests/test_quote_batch.py tests/test_native_quote_batch.py tests/test_native_cpp_suites.py tests/test_native_quote_match.py tests/test_quote_match.py --no-cov -q
```

Compare scalar and batch matching with identical inputs and checked output hashes:

```bash
poetry run python -m benchmarks.runner --case quote_python --case quote_native --case quote_batch_python --case quote_batch_native --rows 10000 --repeats 7 --output benchmark-results/quote-batches.json
```

Batch workloads prepare chunks of 1024 entries outside the timed region. Their
timed work includes dispatch, input validation, matching and result flattening.
All four workloads use the same eight cases per source row and must produce the
same output digest. The direct native suite checks the 4096-entry limit separately.
An isolated batch speedup does not establish a whole-verifier or research speedup.

## Measure integrated verification

The verifier's `batch_quotes=False` keyword retains scalar native dispatch for
controlled comparisons; normal calls default to batching when native mode is
explicitly selected. Python and regex verification remain scalar. The benchmark
runner exposes that comparison without changing the research CLI:

```bash
VERBOISY_QUOTE_MATCHER=native poetry run python -m benchmarks.runner --case verify --scalar-native-quotes --rows 10000 --repeats 7 --output benchmark-results/verify-native-scalar.json
VERBOISY_QUOTE_MATCHER=native poetry run python -m benchmarks.runner --case verify --rows 10000 --repeats 7 --output benchmark-results/verify-native-batch.json
poetry run python -m benchmarks.comparison benchmark-results/verify-native-scalar.json benchmark-results/verify-native-batch.json --output benchmark-results/verify-native-comparison.json
```

Reports record `native_verifier_quote_mode` as `scalar` or `batch`, as well as the
source and binary fingerprints. All schema, projection, scope, mapping, value and
identity checks remain active. Tests compare complete ordered rejection lists,
mixed eligible/ineligible proofs, JSON mapping keys and multi-chunk candidates.
Explicit native errors propagate rather than
returning partially verified evidence. Normal Python installation needs no binary
or compiler and keeps the same default behavior.

## Mandatory native CI validation

The CI workflow has a separate native job that builds both extensions and runs
`scripts/check_native_tests.py`. Its configured matrix covers Linux CPython
3.11–3.14 and macOS CPython 3.11 and 3.14. These jobs exercise the platform's C++
compiler and the running interpreter's Unicode tables and extension ABI. Windows
continues to use the existing Python-only test matrix.

The strict runner selects all tests marked `native`, ignores `PYTEST_ADDOPTS`
selection overrides, and requires a fresh JUnit report with at least one successful
testcase and no skips, failures or errors. Expected-failure skips also fail the
gate. Thus missing binaries cannot produce a green native job through pytest's
ordinary optional-test skips. Pytest failure exit codes propagate unchanged.

Run the same gate locally after building both modules:

```bash
poetry run python scripts/build_native.py
poetry run python scripts/build_native_tests.py
poetry run python scripts/check_native_tests.py
```

The workflow retains the JUnit report and both build fingerprints as diagnostic
artifacts for seven days. It does not publish shared libraries or native wheels.
The regular installation, Python-only jobs and research CLI are unchanged.
The matrix is configured here; a successful local Linux run does not establish
that every remote Python/macOS job has passed. Those results require execution
on GitHub before any broader support or automatic-default claim is made.

In the initial Linux/CPython 3.12 synthetic experiment, the native matcher was
about 3.3 times faster than the Python matcher in the isolated eight-case workload.
Complete 10,000-record verification took about 0.54 seconds with either new matcher,
versus 1.21 seconds with regex. Thus no additional whole-verifier native speedup
was established in that experiment. Python remains the default; target-machine
measurements and broader workload evidence are required before changing it.

## Inspect local native configuration

```bash
poetry run verboisy native-config
```

This read-only command reports the selected quote backend, the current
interpreter's extension filename, binary and metadata presence, and whether
the binary and seven production source files match `quote-build.json`. Missing
or changed sources are listed separately. A null fingerprint result means
that it could not be checked because the required artifact is absent.
Malformed, oversized or unsupported metadata produces an inspection error.
Only the known production source paths are inspected; metadata cannot nominate
arbitrary files. Compiler commands and unrelated environment values are omitted.

Selection comes from the shell's `VERBOISY_QUOTE_MATCHER` and
`VERBOISY_NATIVE_QUOTE_DIR`, matching the runtime loader. This command does not
load `.env`, instantiate application settings, open a ledger, contact providers,
compile code or load a shared library. It leaves the Python default unchanged.
An explicit native selection still fails if native loading is unavailable;
there is no automatic fallback.

Matching hashes establish file consistency, not provenance or loadability.
The report always says `binary_loaded: false` and `loadability: not_checked`.
Use `scripts/check_native_tests.py` to exercise both compiled modules.
Build platform eligibility describes the builder's CPython/Linux/macOS guard,
not a claim that the remote CI matrix has passed.

## Reject stale native builds before testing

The strict native gate now checks both production and direct-test build
fingerprints before pytest loads either extension. It requires the current
interpreter's binary filenames, both metadata files, matching binary hashes,
and matching hashes for all known source/header inputs. The production manifest
uses version 2; the test manifest uses version 1 and purpose `direct_cpp_tests`.
Missing, changed, unchecked or malformed inputs stop validation before compiled
code executes and request a rebuild of both modules.

A stale JUnit report is removed even when this preflight fails, so a previous
success cannot be mistaken for current validation. The gate continues to reject
all skipped native tests and propagates pytest failures. `native-config` retains
its read-only production report; the stricter preflight applies to the explicit
developer test command, with no change to installation or normal research use.
Fingerprints establish consistency with the inspected files, not trust in
metadata or proof that remote CI has passed.

---

[Overview](index.md) · [CLI](cli.md) · [API](api.md) · [Licensing](licensing.md)
