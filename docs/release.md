<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Release operations

Release operations publish reviewed artifacts from an identified version. Source
visibility, documentation hosting and package distribution are independently
controlled. The supplied workflows require an explicit enablement variable and a
public repository before publication.

## Repository controls

Protect `main` with the applicable pull-request checks and review rules. Keep
`PAGES_ENABLED` and `RELEASE_ENABLED` disabled until their corresponding publication
is intended. Ordinary CI must not receive live model credentials. Review dependency
updates, third-party Actions and secret-scanning findings before distribution.

If Codecov is used, configure the required Actions secret for private uploads.
If it is not used, remove the integration in a reviewed change instead of leaving
a permanently failing check. Repository features and protection options depend on
the account plan and visibility.

## Prepare the release

1. Complete the applicable [release checklist](release-checklist.md).
2. Confirm version metadata, supported environments and migration instructions.
3. Run validation against the final commit, including required browser checks.
4. Build and install wheel/sdist artifacts in clean environments; retain hashes.
5. Review LICENSE, third-party notices, source rights and commercial claims.
6. Review the complete included history, examples and logs for credentials and
   confidential content. Revoking a secret is required if it was exposed.
7. Confirm release notes, security contact and the actual support scope.

The first public source release needs a specific history/licensing review because
older versions carried BSD terms. See [distribution](distribution.md). Publishing
current source terms does not revoke historic grants.

## Documentation publication

The documentation workflow is gated by `PAGES_ENABLED == 'true'` and public
repository visibility. Review the generated site and its links before enablement.
The public site should state current licensing and supported capabilities without
exposing private source data or internal evaluation inputs.

## Package publication

The package workflow is gated by `RELEASE_ENABLED == 'true'` and public visibility.
Configure the intended package owner, trusted publishing and the `pypi` environment
before use. Limit publication to reviewed release tags and use environment approval
where available. Public PyPI availability is not assumed by installation guidance.

Public release artifacts remain subject to the inspection license unless a separate
agreement states otherwise. A download does not grant execution rights. Include
current notices and clear license metadata in every artifact.

## After publication

Verify the published artifacts and installation path, announce the actual changes,
and monitor reported defects and security advisories. Preserve evaluated failures
and known limitations. If a release must be withdrawn, explain the affected version,
reason and upgrade or mitigation path without disclosing sensitive details.

---

[Overview](index.md) · [CLI](cli.md) · [API](api.md) · [Licensing](licensing.md)
