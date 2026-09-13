<p align="center">
  <img src="../../logo.png" alt="verboisy" width="300" />
</p>
<p align="center">
  <strong align="center">Un agente autonomo per la ricerca web e lo scraping strutturato in JSON.</strong>
</p>
<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/EmanueleTorrisi/verboisy?style=flat" alt="License"></a>
</p>

<p align="center">
  <a href="../../README.md" title="English" aria-label="English">GB</a> ·
  <strong title="Italiano" aria-label="Italiano">IT</strong> ·
  <a href="README.de.md" title="Deutsch" aria-label="Deutsch">🇩🇪</a> ·
  <a href="README.zh-CN.md" title="简体中文" aria-label="简体中文">🇨🇳</a> ·
  <a href="README.fr.md" title="Français" aria-label="Français">🇫🇷</a> ·
  <a href="README.es.md" title="Español" aria-label="Español">🇪🇸</a> ·
  <a href="README.hi.md" title="हिन्दी" aria-label="हिन्दी">🇮🇳</a> ·
  <a href="README.ar.md" title="العربية" aria-label="العربية">🇸🇦</a>
</p>

## Come installare:

```
pip install verboisy
playwright install --with-deps chromium
```

## Come configurare:

Copia .env.example in .env e imposta le tue chiavi API:

-> OPENAI_API_KEY=sk-...

-> LITELLM_MODEL=gpt-4o

## Come utilizzare:

Verboisy opera tramite una semplice interfaccia a riga di comando.
Gli fornisci un obiettivo in linguaggio naturale e uno schema JSON che definisce l'esatta struttura dei dati che desideri ottenere.

Ecco un esempio di comando completo:
```
verboisy run \
  --goal "Trova le startup di IA più recenti di Y Combinator W24" \
  --schema examples/yc_startups/schema.json \
  --export result.json
```

Dettaglio del comando:

*run*: Il comando principale per avviare l'agente autonomo.

*--goal* (o -g): Dice all'agente esattamente cosa cercare e dove andare. Sii il più specifico possibile.

*--schema* (o -s): Il percorso del file al tuo schema JSON personalizzato. Questo file dice a Verboisy esattamente quali campi di dati estrarre (es. nome dell'azienda, sito web, descrizione).

*--export* (o -e): (Opzionale) Il percorso del file in cui desideri salvare i dati finali estratti. Supporta i formati .json e .csv.

Una volta premuto invio, Verboisy avvierà un browser headless, navigherà autonomamente sul web, analizzerà il DOM della pagina, estrarrà i dati corrispondenti al tuo schema e li salverà nel tuo file result.json.


----------------------------------------------------------------------------------------
**Verboisy è stato scritto da Emanuele Torrisi ed è rilasciato sotto la licenza BSD a 2 clausole.**
