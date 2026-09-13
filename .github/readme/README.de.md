<p align="center">
  <img src="../../logo.png" alt="verboisy" width="300" />
</p>
<p align="center">
  <strong align="center">Ein autonomer Agent für Web-Recherche und strukturiertes Scrape-to-JSON.</strong>
</p>
<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/EmanueleTorrisi/verboisy?style=flat" alt="License"></a>
</p>

<p align="center">
  <a href="../../README.md" title="English" aria-label="English">🇬🇧</a> ·
  <a href="README.it.md" title="Italiano" aria-label="Italiano">🇮🇹</a> ·
  <strong title="Deutsch" aria-label="Deutsch">🇩🇪</strong> ·
  <a href="README.zh-CN.md" title="简体中文" aria-label="简体中文">🇨🇳</a> ·
  <a href="README.fr.md" title="Français" aria-label="Français">🇫🇷</a> ·
  <a href="README.es.md" title="Español" aria-label="Español">🇪🇸</a> ·
  <a href="README.hi.md" title="हिन्दी" aria-label="हिन्दी">🇮🇳</a> ·
  <a href="README.ar.md" title="العربية" aria-label="العربية">🇸🇦</a>
</p>

## So installieren Sie:

```
pip install verboisy
playwright install --with-deps chromium
```

## So konfigurieren Sie:

Kopieren Sie die .env.example nach .env und legen Sie Ihre API-Schlüssel fest:

-> OPENAI_API_KEY=sk-...

-> LITELLM_MODEL=gpt-4o

## So verwenden Sie es:

Verboisy funktioniert über eine einfache Befehlszeilenschnittstelle.
Sie geben ein Ziel in einfachem Englisch und ein JSON-Schema vor, das die genaue Datenstruktur definiert, die Sie zurückerhalten möchten.

Hier ist ein vollständiger Beispielbefehl:
```
verboisy run \
  --goal "Finde die neuesten KI-Startups von Y Combinator W24" \
  --schema examples/yc_startups/schema.json \
  --export result.json
```

Aufschlüsselung des Befehls:

*run*: Der Hauptbefehl zum Starten des autonomen Agenten.

*--goal* (oder -g): Teilen Sie dem Agenten genau mit, wonach er suchen und wohin er navigieren soll. Seien Sie so spezifisch wie möglich.

*--schema* (oder -s): Der Dateipfad zu Ihrem benutzerdefinierten JSON-Schema. Diese Datei teilt Verboisy genau mit, welche Datenfelder extrahiert werden sollen (z. B. Firmenname, Website, Beschreibung).

*--export* (oder -e): (Optional) Der Dateipfad, in dem Sie die extrahierten Enddaten speichern möchten. Es werden die Formate .json und .csv unterstützt.

Sobald Sie die Eingabetaste drücken, startet Verboisy einen Headless-Browser, navigiert autonom durchs Web, analysiert das Seiten-DOM, extrahiert die Ihrem Schema entsprechenden Daten und speichert sie in Ihrer result.json-Datei.


----------------------------------------------------------------------------------------
**Verboisy wurde von Emanuele Torrisi geschrieben und wird unter der 2-Klausel-BSD-Lizenz veröffentlicht.**
