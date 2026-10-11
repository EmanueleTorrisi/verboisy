<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Engineering change workflow

Changes should be reviewable, explain their user-visible effect and preserve the
public contracts documented in this repository. Repository access and code changes
are limited to the maintainer and explicitly authorized collaborators.

## Describe the change

A commit subject should use a clear verb and a concrete outcome. Conventional
prefixes such as `fix`, `feat`, `docs`, `test` and `build` are useful when they clarify
the purpose. The description should explain the problem, resulting behavior and
relevant verification. Avoid generic subjects that say only “update” or “changes”.

## Review and validate

Inspect the diff and stage explicit paths. Keep unrelated work out of the change.
Preserve copyright notices, third-party attribution and exact-byte evidence fixtures.
Document compatibility implications, migrations and material limitations.

```bash
git diff -- path/to/file
git add -- path/to/file
make validate
```

Validate the completed change against the commit proposed for review. Browser,
optional native and model-based evaluations have different runtime requirements;
record which checks actually ran. A test failure must not be hidden by an unrelated
skip, weakened assertion or a fabricated report.

## Review and merge

Use a pull request that explains the final implementation and links relevant issues.
Require the applicable CI checks and review before merging. Keep credentials,
private inputs and generated diagnostic logs out of repository history. Release
artifacts are rebuilt from a reviewed version; see [release operations](release.md).

Bug reports and feature suggestions are welcome. Unsolicited implementation changes
are not currently accepted; see [participation](https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/CONTRIBUTING.md).

---

[Overview](index.md) · [CLI](cli.md) · [API](api.md) · [Licensing](licensing.md)
