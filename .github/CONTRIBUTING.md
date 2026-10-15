<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Reporting, feedback and collaboration

Verboisy is created and maintained by Emanuele Torrisi. The project welcomes bug
reports and feature requests. It currently has one developer and does not accept
unsolicited code contributions or general community pull requests.

## Report a bug

Search [existing issues](https://github.com/EmanueleTorrisi/verboisy/issues) first,
then use the bug-report template. Include:

- The version or commit, operating system and Python version.
- The affected workflow and a minimal, authorized reproduction.
- The schema or relevant settings, with all secrets and private data removed.
- Expected and observed behavior, including the run status or error text.
- Whether the problem repeats and whether it affects saved data or recovery.

Use synthetic or publicly shareable inputs. Do not attach a populated `.env`,
provider keys, a private ledger, proprietary source files or full confidential
exports. Send suspected vulnerabilities through [private security reporting](SECURITY.md).

## Request a feature

Explain the problem, who encounters it and the desired outcome. Describe source
formats, data volume, deployment constraints and an example of a successful result.
Suggestions about quality, accessibility, cost and recovery are as useful as new
features. An accepted request is not a delivery-date or support commitment.

## Discuss paid collaboration

Contact [emanueletorrisi98@gmail.com](mailto:emanueletorrisi98@gmail.com) with relevant
experience, an area of expertise and the work you propose. Future collaboration may
be arranged through employment or a paid contract when appropriate to the roadmap.
No position, compensation or engagement is promised by this page.

Scope, compensation, confidentiality, software permissions and intellectual-property
terms must be agreed in writing before work begins. Do not submit implementation
code, start speculative paid work or assume an issue assignment is a contract.

## Authorized engineering work

Invited developers use the agreed repository access and a dedicated branch. Changes
should explain the problem, resulting behavior and relevant verification. Preserve
public API contracts, source attribution and third-party notices. Update documentation
when user-visible behavior changes and add regressions that demonstrate the defect.

```bash
poetry install
make validate
make repo-check
```

Browser and optional native checks require their documented runtimes. Model-based
evaluation is separate and requires authorized sources, credentials and a spending
limit. See [engineering validation](../docs/validation.md) and [architecture](../ARCHITECTURE.md).

Participation follows the [Code of Conduct](CODE_OF_CONDUCT.md). Feedback and issue
reporting do not grant execution or reuse rights; [LICENSE](../LICENSE) and the
applicable written agreement govern those rights.


## Authorized verification

Provision Chromium before browser verification with `poetry run verboisy setup`;
Linux OS dependencies may require `poetry run python -m playwright install --with-deps chromium`
and administrator rights. Keep sandbox requirements visible.

Use `make test-native` for both optional builders and the no-skip direct-test gate.
Ordinary `make test` supports Python-only installations. After `poetry build`, run
`poetry run python scripts/check_distribution.py --dist-dir dist --from-sdist --install-smoke`.
`make release-verify` adds native and package gates to validation. Dependency-index
access or a prepared cache is needed for isolated builds/installation.

Record exact commands, source hashes and actual pass/failure/blocker outcomes. Current
fingerprints exclude `evals/results/` to avoid recursive evidence hashes. Configuration
of a CI job is not execution evidence. Keep keys and private ledgers out of reports.
