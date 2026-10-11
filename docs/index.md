<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Verboisy

Verboisy is an evidence-backed autonomous web research engine that turns a goal and requested columns into a persistent structured dataset.

Start with the simple interface:

```bash
verboisy run \
  --goal "Find white laptops under €1000" \
  --schema '[name,brand,color,price,screen_size]' \
  --export laptops.csv
```

The same evidence engine still supports explicit JSON Schema and advanced TaskSpec configuration.

Read the [CLI reference](cli.md), [dataset contract](contracts.md), [SmartID guide](smartid.md), and [proof guide](proof.md). The [architecture document](https://github.com/EmanueleTorrisi/verboisy/blob/main/ARCHITECTURE.md) explains the research and verification boundaries.

Package metadata currently identifies a `1.0.0` development build. Production
acceptance remains pending. Follow the [finite release plan](development-roadmap.md)
and [acceptance protocol](production-acceptance.md). Current limitations remain
documented in the README and architecture documentation.
