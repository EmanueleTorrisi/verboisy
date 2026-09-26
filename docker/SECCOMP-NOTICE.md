# Chromium seccomp profile

`seccomp_profile.json` adapts the Docker/Moby default syscall policy for Chromium:

- Base policy: https://github.com/moby/profiles/blob/main/seccomp/default.json
- Retrieved: 2026-09-25.
- Upstream guidance: https://playwright.dev/python/docs/docker#crawling-and-scraping
- Local SHA-256: `12c33f78b1c8ddb3a68c94f7f72ba4d3f943525174b9a2a1629c395b351f447b`.

Modification: one unconditional allow rule for `clone`, `setns` and `unshare` was
prepended, following Playwright's documented sandbox setup. All base policy entries
are retained, including modern syscall handling and the `clone3` ENOSYS fallback
for containers without `CAP_SYS_ADMIN`. JSON whitespace has been normalized.
The file is checked in so CI and deployments use the reviewed bytes rather than
downloading a mutable policy during startup. Review policy changes separately
when updating Docker, Chromium or the deployment host.

The added permissions support Chromium's user namespace sandbox. The default
action remains `SCMP_ACT_ERRNO`. This permits sandbox creation; it
does not establish that the host's kernel and security policy support that sandbox.
Run the sandboxed Docker gate on each intended host.

The base policy is maintained by the Moby project and distributed under the
[Apache License 2.0](https://github.com/moby/profiles/blob/main/LICENSE).
The license text is included in [LICENSE-APACHE-2.0.txt](LICENSE-APACHE-2.0.txt).
This third-party policy retains that license; Verboisy's own source retains its
existing license.
