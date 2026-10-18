<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Verboisy documentation

Verboisy turns research questions and permitted sources into structured records with
inspectable evidence. It also prepares existing datasets through deterministic
adapters and supports a separate disk-backed workflow for large local files.

## Start with your workflow

| Goal | Guide |
| --- | --- |
| Install the direct `verboisy` command | [Installation](installation.md) |
| Research a question and export structured records | [CLI](cli.md), [contracts](contracts.md) and [providers](providers.md) |
| Prepare local or declared HTTP inputs | [Ingestion](ingestion.md) and [file capabilities](formats.md) |
| Prepare large local files with checkpoints | [Streaming](streaming.md) |
| Integrate with an application | [Python API](api.md) |
| Inspect evidence and transformations | [Proof](proof.md), [research semantics](research-semantics.md) and [presentation](presentation.md) |

## Understand the system

[Architecture](architecture.md) describes component ownership and trust boundaries.
[Engineering validation](validation.md) and [evaluation](evaluation.md)
explain how engineering correctness and real-task quality are evaluated. Read
[release notes](https://github.com/EmanueleTorrisi/verboisy/blob/main/CHANGELOG.md)
and the [roadmap](development-roadmap.md) for technical changes and version evolution.

## Licensing and contact

Verboisy is proprietary, with limited source-inspection permissions. Software
execution, testing, modification and deployment require separate written permission.
Read [licensing](licensing.md). For demos, evaluations, enterprise use, partnerships
or paid collaboration, contact [emanueletorrisi98@gmail.com](mailto:emanueletorrisi98@gmail.com).
Compare the public source-inspection edition and separately maintained commercial
edition in [commercial solutions](commercial.md).

Bug reports and feature requests are welcome. Security reports should be sent
privately through the [security policy](https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/SECURITY.md).


## Data guarantees and qualification

Ordinary output reserves generated `id`; source IDs require explicit projection.
Optional absence and explicit null remain distinct. Streaming is a separate row-validation
contract with verified capture/checkpoint paging; see [streaming](streaming.md).

Version `1.0.0` is qualified for the documented workflows, supported environments
and tested limits. The [release matrix](https://github.com/EmanueleTorrisi/verboisy/blob/main/evals/release-matrix.json) records current evidence and
approvals. [Historical offline results](https://github.com/EmanueleTorrisi/verboisy/blob/main/evals/results/offline-validation.json)
retain their original source and environment context. See [validation](validation.md)
for the engineering process and [evaluation](evaluation.md) for acceptance methods.

## Prepare a release

[Release qualification](release.md) explains the seven evidence gates.
[Publishing and customer delivery](distribution.md) covers PyPI, pipx, private wheels and commercial access.
