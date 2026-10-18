<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

<p align="center"><img src="https://raw.githubusercontent.com/EmanueleTorrisi/verboisy/main/logo.png" alt="Verboisy" width="220" /></p>

<p align="center">
  <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/README.md">English</a> ·
  <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/readme/README.it.md">Italiano</a> ·
  <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/readme/README.de.md">Deutsch</a> ·
  <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/readme/README.fr.md">Français</a> ·
  <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/readme/README.es.md">Español</a> ·
  <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/readme/README.ja.md">日本語</a> ·
  <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/readme/README.ko.md">한국어</a> ·
  <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/readme/README.zh-CN.md">简体中文</a>
</p>

<h1 align="center">Verboisy</h1>
<p align="center"><strong>Von einer Forschungsfrage zu einem Datensatz mit nachvollziehbaren Quellen.</strong></p>
<p align="center">Beleggestützte Recherche · Strukturierte Extraktion · Lokale Daten · Portable Provenienz</p>


> **Release-Status:** Version `1.0.0` ist innerhalb der dokumentierten Arbeitsabläufe, unterstützten Umgebungen und geprüften Grenzen für den Produktionseinsatz freigegeben. Die [Release-Matrix](https://github.com/EmanueleTorrisi/verboisy/blob/main/evals/release-matrix.json) dokumentiert die technischen Prüfungen, die Bewertung realer Aufgaben, den unabhängigen Betatest und die Freigaben der Release-Verantwortlichen.

## Das Produkt

Verboisy ist eine Recherche- und Datenextraktionssoftware für strukturierte Informationen mit überprüfbarer Herkunft. Eine Frage, ein Schema und zugelassene Quellen bestimmen den Auftrag. Die Software erfasst Beobachtungen, prüft vorgeschlagene Datensätze und bewahrt Belege sowie Ausgabetransformationen. CLI und Python-API unterstützen wiederholbare Abläufe und die Fortsetzung gespeicherter Arbeit.

Zusätzlich bereitet Verboisy lokale und deklarierte HTTP-Daten mit deterministischen Adaptern auf, ohne Modell-, Such- oder Browseraufrufe. Große lokale Dateien nutzen einen getrennten Ablauf mit begrenzten Puffern und einem Datenspeicher auf Festplatte.

**Quellcode einsehbar, Nutzung separat lizenziert.** [LICENSE](https://github.com/EmanueleTorrisi/verboisy/blob/main/LICENSE) erlaubt Quellcodeprüfung, nicht die Ausführung. Tests, Änderungen und Bereitstellung benötigen eine gesonderte schriftliche Vereinbarung. Die Beispiele beschreiben autorisierte Nutzung.

## Warum dieser Ansatz wichtig ist

JSON oder eine Tabelle allein zeigen nicht, ob ein Fakt beobachtet wurde oder wie ein Wert entstanden ist. Verboisy integriert diese Fragen in den Datenprozess:

- **Belege vor Annahme:** Modellvorschläge benötigen beobachtete Quellenbezüge und deterministische Prüfung; semantische Prüfung ist ein eigener Schritt.
- **Kontrollierbare Anforderungen:** JSON Schema, Identitätsregeln, Quellumfang und Vergleichbarkeit bestimmen zulässige Ergebnisse.
- **Wiederaufnahme:** Unveränderliche Erfassungen, Checkpoints und Anfragejournale bewahren Fortschritt und Verbrauch.
- **Nachvollziehbare Transformationen:** Einheiten, Projektionen, Darstellung und Gruppen bleiben mit Rohwerten und beitragenden Datensätzen verbunden.
- **Explizite Entscheidungen:** Änderungsvorschläge unterbrechen den Ablauf, statt Frage oder Schema unbemerkt zu ersetzen.

Geeignet sind Analyse, Referenzdaten, Datenaufbereitung, interne Informationsabläufe und reproduzierbare Untersuchungen. Wissenschaftliche und regulierte Anwendungen verlangen unabhängige Prüfung von Quellen, Stichproben und Schlussfolgerungen. Das langfristige Ziel ist ein vertrauenswürdiger Standard für beleggestützte Datenextraktion, keine Behauptung bestehender Marktführerschaft.

### KI dort einsetzen, wo Interpretation einen Mehrwert bietet

Verboisy verbindet deterministischen Code mit semantischer KI. Das Einlesen strukturierter Dateien, die Schema-Validierung, der Abgleich beobachteter Belege und der Export erfolgen im Code. Modelle unterstützen Planung und Interpretation, soweit der Arbeitsablauf dies erfordert. Deterministische Schritte verbrauchen keine Modell-Tokens und vermeiden die Inferenzkosten, die bei der Ausführung derselben Schritte durch ein kostenpflichtiges LLM anfallen würden. Lokale Datensätze lassen sich vollständig ohne Modellanbieter aufbereiten.

Das reduziert unnötige Modellaufrufe und macht Ausgaben nachvollziehbar. Die Gesamtersparnis hängt von Aufgabe, Modell, Wiederholungen und Prüfaufwand ab. Ein belastbarer Vergleich verwendet dieselben Quellen, Ausgabeanforderungen und Qualitätskriterien und berücksichtigt auch fehlgeschlagene Versuche. Belegprüfungen verringern nicht gestützte Ausgaben; semantische Korrektheit erfordert geeignete Quellen und eine inhaltliche Prüfung.

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

Binärerfassung bedeutet weder OCR noch universelle Dokumentinterpretation. OAuth, Datenbanktreiber, Anwendungskonnektoren und API-Paginierung erfordern spezifische Integrationen. Siehe [Formate](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/formats.md).

## Installation und Konfiguration

Python **3.11–3.14** und schriftliche Ausführungsrechte sind erforderlich. Poetry dient der Entwicklung; der installierte Befehl heißt `verboisy`. CI definiert Jobs für Linux, macOS und Windows; aktuelle Ergebnisse müssen geprüft werden. Webrecherche benötigt einen konfigurierten Anbieter, Chromium und Systembibliotheken. Lokale Quellen brauchen freigegebene Verzeichnisse und Speicherplatz. Ein C++-Compiler ist nicht erforderlich.

Führen Sie die folgenden Befehle in einem autorisierten Checkout aus. Mit installiertem pipx macht `pipx install .` den Befehl auch außerhalb des Projekts verfügbar. Nach autorisierter Veröffentlichung auf PyPI: `pipx install verboisy`. Die Verfügbarkeit auf PyPI wird nicht vorausgesetzt. `python examples/local_quickstart.py` prüft zwei synthetische Datensätze ohne Modell oder Browser.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
verboisy --help
```

Schlüssel gehören in eine private Umgebung oder `.env`; Vorlage: [.env.example](https://github.com/EmanueleTorrisi/verboisy/blob/main/.env.example). Keine echten Schlüssel einchecken. Shellbeispiele verwenden POSIX-Syntax; unter Windows Umgebungsvariablen entsprechend konfigurieren.

```bash
verboisy setup
verboisy model-config
```

`model-config` zeigt Einstellungen und das Vorhandensein von Zugangsdaten, keine Schlüsselwerte. Deterministische lokale Aufbereitung benötigt weder Modell noch Browser. Siehe [Anbieter](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/providers.md) und [Validierung](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/validation.md).

## Webrecherche und API

```bash
verboisy run \
  --goal "Finde Forschungseinrichtungen und ihre ausdrücklich veröffentlichten offiziellen Websites" \
  --schema '[name,webseite,land]' \
  --export forschungseinrichtungen.json
```

Automatische Entdeckung benötigt einen Suchanbieter; explizite Start-URLs können in einem Task deklariert werden. JSON Schema ermöglicht präzise Typen und Regeln. Fehlende Angaben können `null` bleiben; unbelegte Werte werden zurückgewiesen. Angenommene Ergebnisse bedeuten keine vollständige Webabdeckung.

```python
from verboisy import run

ergebnis = run(
    goal="Finde Forschungseinrichtungen und ihre veröffentlichten offiziellen Websites",
    schema=["name", "webseite", "land"],
    export="forschungseinrichtungen.json",
)
print(ergebnis.run_id, ergebnis.status, ergebnis.records)
```

Asynchrone Anwendungen verwenden `arun`. Die normale API materialisiert angenommene Datensätze; große lokale Eingaben benötigen den Streaming-Ablauf.

## Lokale und interne Daten

```bash
export DATASET_LOCAL_ROOTS='["/srv/verboisy-eingaben"]'
verboisy run \
  --dataset-file 'jsonl=/srv/verboisy-eingaben/beobachtungen.jsonl' \
  --schema beobachtungsschema.json \
  --export beobachtungen.json
```

Verzeichnis und Schema müssen vorhanden sein. Modellzugangsdaten gewähren keinen Dateisystemzugriff. Deklarierte HTTP-Quellen verwenden begrenzte Downloads, Redirect-Prüfung, DNS-Pinning und ursprungsgebundene Geheimnisse. Quellort und Modellausführung sind unabhängig: Ein entferntes Modell kann Beobachtungen erhalten. Vor vertraulichen Daten sind Datenübertragung, Protokolle, Netzwerk und Aufbewahrung zu prüfen.

## Große Datensätze

```bash
verboisy stream \
  --database beobachtungen-stream.db \
  --dataset-file 'jsonl=/srv/verboisy-eingaben/beobachtungen.jsonl' \
  --schema beobachtungsschema.json \
  --export beobachtungen.jsonl
```

Der Streaming-Speicher bewahrt unveränderliche Quellblöcke und transaktionalen Fortschritt. `stream-status` listet Aufträge; `stream --resume AUFTRAG_ID` setzt einen gespeicherten Auftrag fort. `StreamLedger` bietet seitenweisen Zugriff.

Ein gemessener Linux/Python-3.12-JSONL-Workload verarbeitete und exportierte **1.000.000 Zeilen** aus **1.105.888.890 Bytes**, bei **89,15 MiB** maximalem RSS und **130,81 s** Laufzeit. Wiederaufnahme nach Entfernung der Originalquelle und Exportintegrität wurden geprüft. Das beschreibt einen Workload, keine allgemeine Zusicherung. Siehe [Streaming](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/streaming.md) und [Benchmarks](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/benchmarks.md).

## Vorschläge, Wiederaufnahme und Belege

```bash
verboisy changes --run-id LAUF_ID
verboisy status --run-id LAUF_ID
verboisy run --resume LAUF_ID
```

`--resume` behält Anforderungen bei und lehnt das Angebot ab; `--okresume` akzeptiert genau die gespeicherten Änderungen. Angebote können Typen, Spalten oder Suchumfang ändern. Wiederaufnahme setzt Verbrauch nicht zurück und erweitert Quellrechte nicht stillschweigend.

Intervalle bleiben Intervalle: Eine Untergrenze wird weder zum exakten Wert noch zur erfundenen Obergrenze. Numerische Min-/Max-Spalten erfordern ein geeignetes Schema. Standarddarstellung ist Kilogramm, Meter und Tag/Monat/Jahr; explizite Alternativen bewahren die ursprünglichen Belege. Zeitreihendiagnostik interpoliert keine fehlenden Daten und rät nicht bei mehrdeutigen Ortszeiten.

Portable Exporte enthalten Belege, relevante Ereignisse, Ausgabeprovenienz und gegebenenfalls erfasste Quellen. Gruppen nennen ihre beitragenden Datensätze. Prüfsummen bestätigen Byte-Konsistenz zum Manifest, nicht Wahrheit oder unabhängige Authentizität. Siehe [Provenienz](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/proof.md).

## Architektur und Dokumentation

Python übernimmt Orchestrierung, Verträge, Adapter, CLI und SQLite-Speicher. Optionale C++17-Komponenten beschleunigen bestimmte Belegvergleiche bei erhaltenen Python-Referenzimplementierungen. Tests und CI prüfen Plattformen, Browser, Wiederaufnahme und Integrität; vollständige Anweisungs- und Zweigabdeckung ist erforderlich. Reale Ergebnisqualität und Anbieterkompatibilität benötigen eigene Bewertung.

[CLI](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/cli.md) · [API](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/api.md) · [Verträge](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/contracts.md) · [Identität](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/smartid.md) · [Datenaufnahme](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/ingestion.md) · [Darstellung](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/presentation.md) · [Semantik](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/research-semantics.md) · [Architektur](https://github.com/EmanueleTorrisi/verboisy/blob/main/ARCHITECTURE.md) · [Versionshinweise](https://github.com/EmanueleTorrisi/verboisy/blob/main/CHANGELOG.md)

## Lizenzen, Demos und geschäftliche Anfragen

Verboisy ist proprietäre Software, **kein Open Source**. Maßgeblich ist die englische Lizenz; diese Übersetzung ändert keine Rechte. Kennung: `LicenseRef-Verboisy-Source-Inspection-1.0`. Drittanbieter behalten ihre eigenen Lizenzen. Ausführung, Tests, Änderungen, Integration, Verteilung und Hosting erfordern separate schriftliche Erlaubnis.

Kontakt: **[emanueletorrisi98@gmail.com](mailto:emanueletorrisi98@gmail.com)** für Demos, Evaluationen, interne/Enterprise-Lizenzen, Partnerschaften und mögliche bezahlte Zusammenarbeit. Ablauf, Quellen, Datenvolumen und Umgebung beschreiben; keine vertraulichen Daten oder Schlüssel mitsenden. Preise, Support und Rechte werden individuell vereinbart. Siehe [Lizenzierung](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/licensing.md) und [geschäftliche Anfragen](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/commercial.md).

## Feedback und Zusammenarbeit

**Emanuele Torrisi** entwickelt und betreut Verboisy derzeit als einziger Entwickler. [Fehlerberichte und Funktionswünsche](https://github.com/EmanueleTorrisi/verboisy/issues) sind willkommen. Sicherheitsprobleme gemäß [Sicherheitsrichtlinie](https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/SECURITY.md) privat melden.

Unaufgeforderte Codebeiträge werden derzeit nicht angenommen. Bezahlte Zusammenarbeit erfordert vorherige Vereinbarungen zu Umfang, Vergütung, Vertraulichkeit und geistigem Eigentum. Versionsänderungen stehen im [Changelog](https://github.com/EmanueleTorrisi/verboisy/blob/main/CHANGELOG.md); die [Versionsgeschichte](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/development-roadmap.md) beschreibt den Weg von 0.1.0 zu 1.0.0. Siehe [Teilnahme](https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/CONTRIBUTING.md) und [Copyright](https://github.com/EmanueleTorrisi/verboisy/blob/main/COPYRIGHT.md).
## Anwendungsbeispiele

[Katalog der Forschungseinrichtungen](https://github.com/EmanueleTorrisi/verboisy/blob/main/examples/research_catalog/README.md) ·
[Verarbeitung großer lokaler Beobachtungsdatensätze](https://github.com/EmanueleTorrisi/verboisy/blob/main/examples/streaming_observations/README.md) ·
[Versionsgeschichte: 0.1.0–1.0.0](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/development-roadmap.md)


## Datenverträge und Qualifikation

In gewöhnlichen Ergebnissen ist `id` für erzeugte Metadaten reserviert. Quell-IDs müssen ausdrücklich nach `source_id` projiziert werden; verschachtelte IDs und Streaming-IDs bleiben erhalten. Fehlende optionale Felder bleiben fehlend, explizites null bleibt erhalten. Streaming validiert einzelne Zeilen und lehnt nicht unterstützte Bedingungen auf der Array-Wurzel ab. Ein pausierter Vorbereitungslauf endet mit Code 2. CI ist konfiguriert; historische Messungen gelten nur für ihren dokumentierten Quellstand und Host.

[Historische Ergebnisse](https://github.com/EmanueleTorrisi/verboisy/blob/main/evals/results/offline-validation.json) · [Release-Nachweise und Freigaben](https://github.com/EmanueleTorrisi/verboisy/blob/main/evals/release-matrix.json).


## Warum eine kommerzielle Vereinbarung?

Dieses Repository enthält **Verboisys öffentliche Edition zur Einsicht in den Quellcode**. Kommerzielle Kunden erhalten **eine separat gepflegte Edition mit zusätzlichen Funktionen**, die nicht in diesem Repository veröffentlicht werden.

Der [Vergleich der Editionen](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/commercial.md) beschreibt die Funktionen der einzelnen Editionen, unterstützte Bereitstellungsoptionen und verfügbare Dienstleistungen. Das öffentliche Repository wird weiterhin aktualisiert.

Gelieferte Funktionen, Nutzungsrechte, Support, Update-Berechtigung, Vergütung und Liefertermine werden im unterzeichneten Vertrag festgelegt.

| Ziel | Zu vereinbarender Umfang |
| --- | --- |
| Verboisy im Arbeitsalltag nutzen | Schriftliche Ausführungs- und interne Nutzungsrechte für vereinbarte Nutzer und Umgebungen |
| In ein Produkt integrieren | Passende Rechte zur Änderung, Integration und Bereitstellung oder Weitergabe |
| Einrichtungsaufwand verringern | Onboarding, Schemaentwurf und Bewertung repräsentativer Daten |
| Private Infrastruktur nutzen | Bewertung der Bereitstellung und Integration genehmigter Quellen |
| Wartung und Unterstützung planen | Vertraglich definierte Updates, Leistungen und Reaktionszeiten |

Edition und Dienstleistungen richten sich nach dem Arbeitsablauf, den Anforderungen an die Bereitstellung und den Abnahmekriterien. Der Vertrag legt Leistungen und Verantwortlichkeiten ausdrücklich fest.

[emanueletorrisi98@gmail.com](mailto:emanueletorrisi98@gmail.com)

[Installation](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/installation.md) · [Release und Bewertung](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/release.md)
