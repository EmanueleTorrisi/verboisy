<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Security reporting and trust boundaries

Do not report vulnerabilities through public issues, pull requests or discussions.
Use GitHub private vulnerability reporting when enabled. If that channel is unavailable,
contact the maintainer at the address published in the package metadata; send a concise
initial description without credentials or sensitive source data. No response-time SLA
or independently certified security posture is claimed for this development build.

Include the tested commit/version, platform, affected workflow, minimal reproduction,
impact and relevant configuration. Redact secrets, personal data and internal hostnames.
Agree a disclosure plan with the maintainer before publishing exploit details. A future
advisory should identify affected versions and the actually verified correction.

## Version status

The repository uses `1.0.0` development metadata while release acceptance is pending.
That value is not evidence of a published stable release or a support commitment for
historical versions. The maintainer will triage reports against the development branch
and any explicitly published support policy. Final release support must be documented
before public distribution.

## Runtime boundaries

| Boundary | Intended control | Operational responsibility |
| --- | --- | --- |
| Public browser | Declared scope and URL/navigation checks | Isolated account/container, egress policy and no personal profiles |
| Dataset HTTP | Bounded redirects/downloads, DNS-pinned transport, origin-scoped credentials | Authorize sources and protect secret settings |
| Local files | Explicit directory grants and immutable capture | Limit mounts and filesystem permissions; no hostile same-user sandbox claim |
| Models | Untrusted proposals, evidence checks and durable budgets | Approved providers/profiles and control of SDK telemetry/logging |
| Schemas/projections | Explicit deterministic validation and replay | Trusted schema authors; no general process isolation for hostile regex/recursion |
| Ledgers/exports | Hashes, checksums, stable evidence binding and transactional checkpoints | Protect plaintext records, source URLs, goals, metadata and retained assets |

Files and archives are not executed by dataset adapters. Capturing a binary asset does
not imply that it is safe to open with another application. Checksums detect inconsistency
relative to a supplied manifest, not authenticity or truth. Resource limits do not replace
OS/container quotas. SQLite journals and exports need disk space beyond database ceilings.

Keep provider keys out of ordinary CI, issues, fixtures and public artifacts. Run
`make validate` and review dependency advisories, package/native/browser/container results
for the tested release commit. A clean vulnerability audit covers known advisories at its
measurement time; it is not a proof of absence of vulnerabilities. Publication remains
behind private-repository and explicit enablement guards pending the release review.
