<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

<p align="center"><img src="../../logo.png" alt="Verboisy" width="220" /></p>

<p align="center">
  <a href="../../README.md">English</a> ·
  <a href="README.it.md">Italiano</a> ·
  <a href="README.de.md">Deutsch</a> ·
  <a href="README.fr.md">Français</a> ·
  <a href="README.es.md">Español</a> ·
  <a href="README.ja.md">日本語</a> ·
  <a href="README.ko.md">한국어</a> ·
  <a href="README.zh-CN.md">简体中文</a>
</p>

<h1 align="center">Verboisy</h1>
**Von einer Forschungsfrage zu einem Datensatz mit nachvollziehbaren Quellen.**

Beleggestützte Recherche · Strukturierte Extraktion · Lokale Daten · Portable Provenienz

## Das Produkt

Verboisy ist eine Recherche- und Datenextraktionssoftware für strukturierte Informationen mit überprüfbarer Herkunft. Eine Frage, ein Schema und zugelassene Quellen bestimmen den Auftrag. Die Software erfasst Beobachtungen, prüft vorgeschlagene Datensätze und bewahrt Belege sowie Ausgabetransformationen. CLI und Python-API unterstützen wiederholbare Abläufe und die Fortsetzung gespeicherter Arbeit.

Zusätzlich bereitet Verboisy lokale und deklarierte HTTP-Daten mit deterministischen Adaptern auf, ohne Modell-, Such- oder Browseraufrufe. Große lokale Dateien nutzen einen getrennten Ablauf mit begrenzten Puffern und einem Datenspeicher auf Festplatte.

**Quellcode einsehbar, Nutzung separat lizenziert.** [LICENSE](../../LICENSE) erlaubt Quellcodeprüfung, nicht die Ausführung. Tests, Änderungen und Bereitstellung benötigen eine gesonderte schriftliche Vereinbarung. Die Beispiele beschreiben autorisierte Nutzung.

## Warum dieser Ansatz wichtig ist

JSON oder eine Tabelle allein zeigen nicht, ob ein Fakt beobachtet wurde oder wie ein Wert entstanden ist. Verboisy integriert diese Fragen in den Datenprozess:

- **Belege vor Annahme:** Modellvorschläge benötigen beobachtete Quellenbezüge und deterministische Prüfung; semantische Prüfung ist ein eigener Schritt.
- **Kontrollierbare Anforderungen:** JSON Schema, Identitätsregeln, Quellumfang und Vergleichbarkeit bestimmen zulässige Ergebnisse.
- **Wiederaufnahme:** Unveränderliche Erfassungen, Checkpoints und Anfragejournale bewahren Fortschritt und Verbrauch.
- **Nachvollziehbare Transformationen:** Einheiten, Projektionen, Darstellung und Gruppen bleiben mit Rohwerten und beitragenden Datensätzen verbunden.
- **Explizite Entscheidungen:** Änderungsvorschläge unterbrechen den Ablauf, statt Frage oder Schema unbemerkt zu ersetzen.

Geeignet sind Analyse, Referenzdaten, Datenaufbereitung, interne Informationsabläufe und reproduzierbare Untersuchungen. Wissenschaftliche und regulierte Anwendungen verlangen unabhängige Prüfung von Quellen, Stichproben und Schlussfolgerungen. Das langfristige Ziel ist ein vertrauenswürdiger Standard für beleggestützte Datenextraktion, keine Behauptung bestehender Marktführerschaft.

## Abläufe und Formate

Webrecherche verwendet Browser und konfigurierte Modelle sowie optional einen Suchanbieter. Deterministische Aufbereitung liest freigegebene Dateien oder deklarierte HTTP-GET-Quellen. Der separate Streaming-Ablauf liefert Zählwerte, Datenseiten und Checkpoints.

| Eingabe | Interpretation |
| --- | --- |
| CSV / TSV | Unveränderte Textfelder, explizite Überschriften und Prüfung der Zeilenbreite |
| JSON / JSONL | Typisierte Objekte mit strikter Dekodierung |
| Text | Textdatensätze mit Quellpositionen |
| DOCX / XLSX | Begrenzte dokumentierte Adapter; keine Makro- oder Formelausführung |
| Bilder, Videos und andere Dateien | Unveränderliche Byte-Erfassung, Hashes und Referenzen; keine automatische Inhaltsinterpretation |
| Zeitreihen | Explizite Reihen-/Zeitstempelregeln, Sortierung sowie Lücken- und Duplikatdiagnostik |

Binärerfassung bedeutet weder OCR noch universelle Dokumentinterpretation. OAuth, Datenbanktreiber, Anwendungskonnektoren und API-Paginierung erfordern spezifische Integrationen. Siehe [Formate](../../docs/formats.md).

## Installation und Konfiguration

Voraussetzungen sind Python **3.11–3.14**, Poetry und schriftliche Ausführungsrechte. CI deckt Linux, macOS und Windows ab. Modellrecherche benötigt ein kompatibles Profil und Zugangsdaten; Browserrecherche Chromium und Systembibliotheken. Lokale Quellen brauchen freigegebene Verzeichnisse und Speicherplatz. Für die normale Installation ist kein C++-Compiler erforderlich.

```bash
poetry install
poetry run verboisy --help
```

Schlüssel gehören in eine private Umgebung oder `.env`; Vorlage: [.env.example](../../.env.example). Keine echten Schlüssel einchecken. Shellbeispiele verwenden POSIX-Syntax; unter Windows Umgebungsvariablen entsprechend konfigurieren.

```bash
poetry run verboisy setup
poetry run verboisy model-config
```

`model-config` zeigt Einstellungen und das Vorhandensein von Zugangsdaten, keine Schlüsselwerte. Deterministische lokale Aufbereitung benötigt weder Modell noch Browser. Siehe [Anbieter](../../docs/providers.md) und [Validierung](../../docs/validation.md).

## Webrecherche und API

```bash
poetry run verboisy run \
  --goal "Find research institutions and their explicitly published homepages" \
  --schema '[name,website,country]' \
  --export institutions.json
```

Automatische Entdeckung benötigt einen Suchanbieter; explizite Start-URLs können in einem Task deklariert werden. JSON Schema ermöglicht präzise Typen und Regeln. Fehlende Angaben können `null` bleiben; unbelegte Werte werden zurückgewiesen. Angenommene Ergebnisse bedeuten keine vollständige Webabdeckung.

```python
from verboisy import run

result = run(
    goal="Find research institutions and their published homepages",
    schema=["name", "website", "country"],
    export="institutions.json",
)
print(result.run_id, result.status, result.records)
```

Asynchrone Anwendungen verwenden `arun`. Die normale API materialisiert angenommene Datensätze; große lokale Eingaben benötigen den Streaming-Ablauf.

## Lokale und interne Daten

```bash
export DATASET_LOCAL_ROOTS='["/srv/verboisy-inputs"]'
poetry run verboisy run \
  --dataset-file 'jsonl=/srv/verboisy-inputs/observations.jsonl' \
  --schema observation-schema.json \
  --export observations.json
```

Verzeichnis und Schema müssen vorhanden sein. Modellzugangsdaten gewähren keinen Dateisystemzugriff. Deklarierte HTTP-Quellen verwenden begrenzte Downloads, Redirect-Prüfung, DNS-Pinning und ursprungsgebundene Geheimnisse. Quellort und Modellausführung sind unabhängig: Ein entferntes Modell kann Beobachtungen erhalten. Vor vertraulichen Daten sind Datenübertragung, Protokolle, Netzwerk und Aufbewahrung zu prüfen.

## Große Datensätze

```bash
poetry run verboisy stream \
  --database observations-stream.db \
  --dataset-file 'jsonl=/srv/verboisy-inputs/observations.jsonl' \
  --schema observation-schema.json \
  --export observations.jsonl
```

Der Streaming-Speicher bewahrt unveränderliche Quellblöcke und transaktionalen Fortschritt. `stream-status` listet Aufträge; `stream --resume JOB_ID` setzt einen gespeicherten Auftrag fort. `StreamLedger` bietet seitenweisen Zugriff.

Ein gemessener Linux/Python-3.12-JSONL-Workload verarbeitete und exportierte **1.000.000 Zeilen** aus **1.105.888.890 Bytes**, bei **89,15 MiB** maximalem RSS und **130,81 s** Laufzeit. Wiederaufnahme nach Entfernung der Originalquelle und Exportintegrität wurden geprüft. Das beschreibt einen Workload, keine allgemeine Zusicherung. Siehe [Streaming](../../docs/streaming.md) und [Benchmarks](../../docs/benchmarks.md).

## Vorschläge, Wiederaufnahme und Belege

```bash
poetry run verboisy changes --run-id RUN_ID
poetry run verboisy status --run-id RUN_ID
poetry run verboisy run --resume RUN_ID
```

`--resume` behält Anforderungen bei und lehnt das Angebot ab; `--okresume` akzeptiert genau die gespeicherten Änderungen. Angebote können Typen, Spalten oder Suchumfang ändern. Wiederaufnahme setzt Verbrauch nicht zurück und erweitert Quellrechte nicht stillschweigend.

Intervalle bleiben Intervalle: Eine Untergrenze wird weder zum exakten Wert noch zur erfundenen Obergrenze. Numerische Min-/Max-Spalten erfordern ein geeignetes Schema. Standarddarstellung ist Kilogramm, Meter und Tag/Monat/Jahr; explizite Alternativen bewahren die ursprünglichen Belege. Zeitreihendiagnostik interpoliert keine fehlenden Daten und rät nicht bei mehrdeutigen Ortszeiten.

Portable Exporte enthalten Belege, relevante Ereignisse, Ausgabeprovenienz und gegebenenfalls erfasste Quellen. Gruppen nennen ihre beitragenden Datensätze. Prüfsummen bestätigen Byte-Konsistenz zum Manifest, nicht Wahrheit oder unabhängige Authentizität. Siehe [Provenienz](../../docs/proof.md).

## Architektur und Dokumentation

Python übernimmt Orchestrierung, Verträge, Adapter, CLI und SQLite-Speicher. Optionale C++17-Komponenten beschleunigen bestimmte Belegvergleiche bei erhaltenen Python-Referenzimplementierungen. Tests und CI prüfen Plattformen, Browser, Wiederaufnahme und Integrität; vollständige Anweisungs- und Zweigabdeckung ist erforderlich. Reale Ergebnisqualität und Anbieterkompatibilität benötigen eigene Bewertung.

[CLI](../../docs/cli.md) · [API](../../docs/api.md) · [Verträge](../../docs/contracts.md) · [Identität](../../docs/smartid.md) · [Datenaufnahme](../../docs/ingestion.md) · [Darstellung](../../docs/presentation.md) · [Semantik](../../docs/research-semantics.md) · [Architektur](../../ARCHITECTURE.md) · [Versionshinweise](../../CHANGELOG.md)

## Lizenzen, Demos und geschäftliche Anfragen

Verboisy ist proprietäre Software, **kein Open Source**. Maßgeblich ist die englische Lizenz; diese Übersetzung ändert keine Rechte. Kennung: `LicenseRef-Verboisy-Source-Inspection-1.0`. Drittanbieter behalten ihre eigenen Lizenzen. Ausführung, Tests, Änderungen, Integration, Verteilung und Hosting erfordern separate schriftliche Erlaubnis.

Kontakt: **[emanueletorrisi98@gmail.com](mailto:emanueletorrisi98@gmail.com)** für Demos, Evaluationen, interne/Enterprise-Lizenzen, Investitionen, Partnerschaften und mögliche bezahlte Zusammenarbeit. Ablauf, Quellen, Datenvolumen und Umgebung beschreiben; keine vertraulichen Daten oder Schlüssel mitsenden. Preise, Support und Rechte werden individuell vereinbart. Siehe [Lizenzierung](../../docs/licensing.md) und [geschäftliche Anfragen](../../docs/commercial.md).

## Feedback und Zusammenarbeit

**Emanuele Torrisi** entwickelt und betreut Verboisy derzeit als einziger Entwickler. [Fehlerberichte und Funktionswünsche](https://github.com/EmanueleTorrisi/verboisy/issues) sind willkommen. Sicherheitsprobleme gemäß [Sicherheitsrichtlinie](../SECURITY.md) privat melden.

Unaufgeforderte Codebeiträge werden derzeit nicht angenommen. Bezahlte Zusammenarbeit erfordert vorherige Vereinbarungen zu Umfang, Vergütung, Vertraulichkeit und geistigem Eigentum. Versionsänderungen stehen im [Changelog](../../CHANGELOG.md); die [Versionsgeschichte](../../docs/development-roadmap.md) beschreibt den Weg von 0.1.0 zu 1.0.0. Siehe [Teilnahme](../CONTRIBUTING.md) und [Copyright](../../COPYRIGHT.md).
## Anwendungsbeispiele

[Research catalogue](../../examples/research_catalog/README.md) ·
[Large local observation pipeline](../../examples/streaming_observations/README.md) ·
[Version history: 0.1.0–1.0.0](../../docs/development-roadmap.md)
