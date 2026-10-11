<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Product roadmap

Verboisy aims to become a trusted standard for evidence-backed data extraction:
structured information that can be inspected, reproduced and integrated into
real workflows. Future versions will build on validated capabilities rather than
trade evidence quality for broader unsupported claims.

## Implemented foundations

| Area | Current capability |
| --- | --- |
| Research | Declared source scope, observed snapshots, grounded candidates and saved progress |
| Data preparation | Bounded local/HTTP adapters, immutable assets, profiles and explicit projections |
| Scale | Separate disk-backed local streaming, cursor paging and durable checkpoints |
| Semantics | Grounded units, descriptors, reference periods, ranges and explicit time-series policies |
| User decisions | Reviewable requirement proposals and distinct accept/decline resume paths |
| Engineering | CLI/API, provider profiles, request journals, browser tests and optional C++ acceleration |

These foundations do not imply universal provider, source or format compatibility.
Technical contracts and limitations are documented in the corresponding references.

## Near-term priorities

1. **Real-task acceptance.** Evaluate representative research and internal-data
   workflows against independently reviewed expected results.
2. **Quality and cost.** Measure useful output, false acceptance, completion, latency
   and billed cost; address demonstrated defects before expanding scope.
3. **User experience.** Improve onboarding, useful diagnostics, proposal review,
   recovery and the route from schema to a usable export.
4. **Deployment reliability.** Maintain platform, browser, package and native
   qualification and exercise interruption, storage and security boundaries.
5. **Commercial readiness.** Deliver suitable evaluation agreements, support scope,
   distribution records and accurate enterprise demonstrations.

## Future directions

Broader source adapters, service-specific integrations, better workflow ergonomics
and additional scale scenarios are candidates for later versions. They are not
announced features or committed delivery dates. Connector design must preserve
source permissions, credential isolation, provenance and durable accounting.

Paid engineering collaboration may be arranged where it supports these priorities.
Bug reports and feature requests help identify practical requirements. See
[commercial enquiries](commercial.md) and [participation guidelines](https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/CONTRIBUTING.md).

## How release quality is assessed

The evaluation framework covers seven areas: product contracts, real acceptance,
user experience and economics, reliability, repository/legal readiness, independent
beta and distribution. [Acceptance methodology](production-acceptance.md) defines
the measurements; the [release checklist](release-checklist.md) defines evidence
needed for a specific release. Results are scoped to the tested version, sources
and settings. A successful build is not a guarantee of factual accuracy.

---

[Overview](index.md) · [CLI](cli.md) · [API](api.md) · [Licensing](licensing.md)
