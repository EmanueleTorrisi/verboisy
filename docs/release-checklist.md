<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Release checklist

A release should identify its source commit, dependency lock, artifacts and verified
support scope. Tests, benchmarks and model evaluations answer different questions;
record their actual environment and outcome rather than treating one as a substitute
for another.

| Area | Evidence to retain |
| --- | --- |
| Product contract | Supported workflows, schema/source boundaries and declared limitations |
| Real-task acceptance | Independently reviewed results, negative controls and recorded failures |
| Experience and economics | Usability, recovery, completion, latency and billed-cost measurements |
| Reliability | Applicable platform, browser, native, package, security and interruption checks |
| Documentation and rights | README/translations, current license, ownership review and third-party notices |
| Independent beta | Representative users complete intended tasks; defects are triaged |
| Distribution | Artifact hashes, installation verification, support scope and release notes |

## Engineering checks

```bash
make validate
make repo-check
```

Record the final tested commit and rebuild after code, dependency or packaging changes.
A required failure must be resolved, not converted to a skip. Optional native builds
and deployment-specific container checks need their documented profiles. Model-based
evaluation requires authorized sources, credentials and an explicit spending limit.

## Package and documentation checks

- Verify version metadata, LICENSE, included notices and package contents.
- Install the built artifact in a clean environment and check CLI/API entry points.
- Check navigation, examples and translations against the same supported contract.
- Review dependency advisories and publication credentials for least privilege.
- Ensure reports, examples and logs contain no secrets or confidential material.
- Confirm release notes state known limitations and the applicable support policy.

## Commercial and publication checks

Review prior license grants and included Git history before the initial public
source release. Confirm permissions for supplied artifacts and separately licensed
execution. Review claims against measured evidence and establish commercial support
terms where applicable. Enable publication only for a reviewed release.

Historical evaluation reports retain their original scope and hashes. They are
useful evidence, but do not certify a later commit, different provider or new input
class. See [release operations](release.md), [distribution](distribution.md) and
[licensing](licensing.md).

---

[Overview](index.md) · [CLI](cli.md) · [API](api.md) · [Licensing](licensing.md)
