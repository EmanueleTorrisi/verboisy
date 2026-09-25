# Security Policy

## Reporting a Vulnerability

Please do **not** report security vulnerabilities through public GitHub issues, pull requests, or discussions.

If you believe you have found a security vulnerability in Verboisy, please report it privately through GitHub's security reporting features.

When reporting a vulnerability, please include as much of the following information as possible:

- A clear description of the vulnerability
- The affected Verboisy version or commit
- Steps to reproduce the issue
- A proof of concept, where appropriate
- The potential security impact
- Any suggested mitigation or fix
- Relevant environment or configuration details

Please remove passwords, API keys, tokens, credentials, personal information, and other sensitive information that is not necessary to reproduce the issue.

## Supported Versions

Security fixes are generally provided for the latest released version of Verboisy.

| Version | Supported |
| ------- | --------- |
| Latest release | ✅ |
| Older releases | ⚠️ |
| Unmaintained releases | ❌ |

If you are unsure whether a version is supported, report the vulnerability privately and we will evaluate it.

## Disclosure Policy

We follow a coordinated disclosure process.

After receiving a vulnerability report, maintainers will:

1. Review and validate the report.
2. Communicate with the reporter as needed.
3. Develop and test a fix.
4. Release the fix when appropriate.
5. Publish security advisory information when appropriate.

Please do not publicly disclose the vulnerability before a fix has been released and the maintainers have had a reasonable opportunity to address it.

## Security Advisories

Once a vulnerability has been investigated and resolved, maintainers may publish a GitHub Security Advisory containing relevant information about the issue, affected versions, and the available fix.

Thank you for helping keep Verboisy and its users secure.

## Runtime trust boundaries

Use an isolated OS account/container without personal browser profiles or sensitive
mounts. The browser has network access and processes untrusted web content. Default
HTTP URL checks block private addresses, but do not replace network egress controls
or provide complete DNS-rebinding and browser-protocol isolation. Prompt instructions
are not a complete prompt-injection defense.

Only use schemas from trusted authors; regex/recursive validation is not process-isolated.
SQLite contains scraped records, source URLs, goals and action history in plaintext.
Protect it with filesystem permissions. Do not type credentials through the agent.
Third-party model SDKs have their own logging and telemetry configuration.

Run `poetry run pip-audit --local` before release. A successful audit only covers known
advisories for the installed packages at that time. The supplied pytest dependency
was updated to address GHSA-6w46-j5rx-g56g; no exploit test was performed.
