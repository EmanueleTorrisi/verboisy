<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Verboisy 2.0.0 documentation

Verboisy turns research questions and permitted sources into structured records with
inspectable evidence. It also prepares existing datasets through deterministic
adapters and supports a separate disk-backed workflow for large local files. The
production scope covers local dataset preparation and extraction from declared public
sources. [Read the 2.0.0 release notes](https://github.com/EmanueleTorrisi/verboisy/blob/main/CHANGELOG.md#200).

## Start with your workflow

| Goal | Guide |
| --- | --- |
| Install the direct `verboisy` command | [Installation](installation.md) |
| Research a question and export structured records | [CLI](cli.md), [contracts](contracts.md) and [providers](providers.md) |
| Prepare local or declared HTTP inputs | [Ingestion](ingestion.md) and [file capabilities](formats.md) |
| Reuse a pinned research or ingestion definition | [Versioned workflows](cli.md#versioned-workflows) |
| Prepare, compare, and verify large local datasets | [Streaming](streaming.md) |
| Extract declared metadata and table cells from web pages | [Declared HTML extraction](search-and-recovery.md#declared-html-extraction) |
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


## Data guarantees

Ordinary output reserves generated `id`; source IDs require explicit projection.
Optional absence and explicit null remain distinct. Streaming is a separate row-validation
contract with verified capture/checkpoint paging; see [streaming](streaming.md).

Saved captures and ordered schemas support repeatable exports, and evidence sidecars
preserve each accepted value’s origin. See [proof](proof.md) for delivery checks,
[providers](providers.md) for hosted research, and [validation](validation.md) for
engineering evidence by build and environment.

## Prepare a release

[Release qualification](release.md) explains the seven evidence gates.
[Publishing and customer delivery](distribution.md) covers PyPI, pipx, private wheels and commercial access.
