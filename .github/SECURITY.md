<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Security policy

## Report a vulnerability privately

Email **[emanueletorrisi98@gmail.com](mailto:emanueletorrisi98@gmail.com)** with the
subject **Verboisy security report**. If GitHub private vulnerability reporting is
enabled, [submit a private advisory](https://github.com/EmanueleTorrisi/verboisy/security/advisories/new).
Do not disclose vulnerabilities, exploit details or sensitive data in public issues,
pull requests or discussions.

For an initial report, include the affected version or commit, platform, component,
expected security boundary, impact and minimal reproduction. Use synthetic inputs;
remove tokens, personal data, internal hostnames and confidential source content.
Contact the maintainer before sending large or sensitive attachments.

## Assessment and coordinated disclosure

The maintainer reviews reports, requests additional information where necessary,
and coordinates remediation and disclosure with the reporter. Timing depends on
impact and reproducibility; this policy does not create a response-time SLA.
Affected versions, verified fixes and relevant mitigations should be included in
published advisories. Do not publish exploit details before agreeing a disclosure
plan. Credit is discussed with the reporter and requires their consent.

Security testing must be lawful, confined to systems and data you are authorized
to test, and covered by the necessary software permission. Source inspection is
permitted by [LICENSE](../LICENSE); software execution requires separate written
permission. This policy does not authorize testing third-party sites or bypassing
access controls, and does not create a paid bounty agreement.

## Version coverage

| Version | Report handling |
| --- | --- |
| Current development branch | Reports are investigated against the current implementation |
| Published releases | Support scope and upgrade guidance are stated in their release notes or written support agreement |
| Older or modified builds | Reports are useful; fixes may require an upgrade to a maintained version |

A package version alone does not establish a maintenance period or an enterprise
support commitment. Commercial support is agreed separately.

## Trust boundaries

| Component | Controls in the implementation | Deployment responsibility |
| --- | --- | --- |
| Browser research | Source scope, navigation/redirect policy, observed snapshots | Isolated browser/container, restricted egress, no personal browser profiles |
| HTTP datasets | Bounded requests/redirects, DNS-pinned transport, origin-scoped secrets | Authorized origins, trusted credentials and network rules |
| Local data | Explicit directory grants, source capture and replay | Minimal mounts, filesystem permissions and authorized inputs |
| Models | Untrusted candidates, evidence checks, explicit provider profiles and budgets | Approved providers, data-transfer policy and telemetry review |
| Schemas and projections | Explicit validation and deterministic transformations | Trusted schema authors and OS resource limits |
| Ledgers and exports | Ownership checks, strict decoding, hashes and transactional checkpoints | Access control, encryption, backups, retention and sufficient disk space |

Local grants are not a sandbox against a hostile process running as the same OS
user. Adapter parsing does not execute macros or formulas, but captured binary
assets may be unsafe to open elsewhere. Checksums establish byte consistency, not
source authenticity or factual truth. Input limits do not replace process, CPU,
memory, network or storage quotas.

## Operational safeguards

Keep credentials out of source control, issue logs, fixtures and exported artifacts.
Treat ledgers and bundles as sensitive: they may contain source text, URLs, research
goals, metadata and personal data. Encryption at rest and tenancy isolation are
operator responsibilities; the project does not claim built-in enterprise identity
management or a security certification.

Use approved providers and source rules. A local model is independent of local
filesystem grants. A remote model may receive observations; review the selected
provider's data handling before processing confidential material. Respect source
permissions, privacy obligations and access restrictions.

Validate dependencies, browser/native builds and packages for the deployed version.
A clean dependency audit covers known advisories at the audit time and does not
prove the absence of vulnerabilities. See [validation](../docs/validation.md) and
[commercial deployment guidance](../docs/commercial.md).
