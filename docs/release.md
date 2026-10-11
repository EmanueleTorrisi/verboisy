<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Private validation and public release

Keep this repository private while validating. The supplied workflow intentionally requires
both a public repository and an explicit variable before publication or Pages deployment.
No release, tag, GitHub settings, PyPI ownership or production accuracy has been certified
merely by delivering these files.

## Repository configuration

1. Settings → Secrets and variables → Actions → Variables: keep `PAGES_ENABLED=false`
   and `RELEASE_ENABLED=false` during private development. Do not add live model keys to
   ordinary pull-request CI. Run paid evaluations explicitly in a trusted environment.
2. If you use private Codecov uploads, configure `CODECOV_TOKEN` as an Actions secret.
   Its failure is intentionally a CI failure on main. If you do not use Codecov, remove
   that integration in a reviewed change rather than allowing a permanently failing job.
3. Under branch rules/rulesets, protect `main`: pull requests, required CI jobs and review
   appropriate to your team. Required-check names must match the actual completed jobs.
   Some protection features depend on your GitHub plan and repository visibility.
4. Create environment `pypi` before release. Configure permitted release tags and reviewers
   where your account plan supports them. Keep write permissions minimal.
5. Review third-party Actions, dependency updates, Dependabot alerts and secret scanning.
   An empty known-vulnerability report is not proof of absence of vulnerabilities.

## Release gates

Run all commands in validation.md, the Docker sandbox smoke test and the delivery's clean
wheel test. Require the new commit's Python/OS matrix, real browser, package and Docker
jobs, not historic successes from 0.1. Review schema/provenance/adversarial fixtures and
held-out live datasets against manually checked sources. Review all negative controls.
The basic LLM baseline is a controlled comparison, not a universal superiority claim.

Freeze the tested commit, model, prompt hashes, settings, fixtures and report. Document
supported site classes and remaining limits. Rebuild and retest after any code/dependency
change. Do not label this candidate production-ready while any release gate is unrun.

## When ready to become public

1. Review the **entire Git history**, files, examples and Actions logs for secrets or private
   data before changing visibility. Rotate exposed credentials; deleting their latest file
   alone does not remove them from history. Preserve licenses and third-party attribution.
2. Change repository visibility yourself under Settings → General → Danger Zone only after
   the release review. This is deliberately not automated by the delivery.
3. To publish documentation, Settings → Pages → Source → GitHub Actions, then set
   `PAGES_ENABLED=true`. Rerun the docs workflow from main and verify the deployed site.
4. Confirm ownership/availability of the PyPI name `verboisy`. Configure a PyPI Trusted
   Publisher for owner `EmanueleTorrisi`, repository `verboisy`, workflow `publish.yml`,
   environment `pypi`. Use a pending publisher if the project has not yet been created.
   See [PyPI Trusted Publishers](https://docs.pypi.org/trusted-publishers/).
5. Set `RELEASE_ENABLED=true` only after those checks and the acceptance gates.
   If publishing a prerelease, select a reviewed candidate version, update both package
   metadata and `__version__`, rerun the gates and use its matching tag. The current
   `1.0.0` development metadata is not evidence of a published stable release.
   A prerelease normally needs `pip install --pre verboisy`.
6. For a stable release, change both `pyproject.toml` and `src/verboisy/__init__.py` to the
   reviewed stable version on a PR, refresh the lockfile as required, rerun all gates,
   merge, and publish the matching GitHub release/tag. The publishing workflow validates
   the tag and uploads the exact distribution artifact built and checked by its CI job.
7. Verify installation in a clean environment from PyPI and archive hashes/release results.
   Only a published stable version supports the intended plain `pip install verboisy` path.

The wheel installs the Python program; Chromium is downloaded at first browser use or
`verboisy setup`. Linux system libraries cannot reliably be provisioned by pip without
system privileges. Use a prebuilt, tested container where that requirement is unsuitable.

## Consolidated implementation candidate

The six implementation batches have a finite scope. Their final documentation,
repository consistency checks and per-file commit plan prepare a reviewable candidate;
they do not authorize publication or paid research. Follow the
[release evidence checklist](release-checklist.md), [commit policy](commit-policy.md)
and [distribution review](distribution.md). Historical benchmark and offline reports
retain their original implementation hashes and limited qualification scope.
