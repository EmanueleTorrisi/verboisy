<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

<p align="center"><img src="../../logo.png" alt="Verboisy" width="220" /></p>

[English](../../README.md) · [Italiano](README.it.md) · [Deutsch](README.de.md) · [Français](README.fr.md) · [Español](README.es.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [简体中文](README.zh-CN.md)

# Verboisy

**Dalla domanda di ricerca a un dataset di cui puoi verificare le fonti.**

Ricerca con prove · Estrazione strutturata · Dati locali · Provenienza portabile

## Il prodotto

Verboisy è un motore di ricerca ed estrazione dei dati per chi ha bisogno di informazioni strutturate e vuole capire da dove provengono. Una domanda, uno schema e le fonti consentite definiscono il lavoro: il sistema acquisisce osservazioni, verifica i record proposti e conserva le prove e le trasformazioni che portano al risultato. CLI e API Python permettono flussi ripetibili e ripresa del lavoro salvato.

Il progetto prepara anche dataset locali o HTTP dichiarati tramite adattatori deterministici, senza chiamate a modelli, ricerca o browser. Un percorso separato usa un registro su disco e buffer limitati per file locali di grandi dimensioni.

**Codice consultabile, utilizzo soggetto a licenza commerciale.** [LICENSE](../../LICENSE) permette l'ispezione del codice, non l'esecuzione. Test, modifiche e distribuzione richiedono un accordo scritto separato. Gli esempi descrivono un utilizzo autorizzato.

## Perché questo approccio

Un JSON o una tabella non spiegano, da soli, se un fatto sia stato osservato o come sia stato trasformato. Verboisy integra questi controlli nel flusso dei dati:

- **Prove prima dell'accettazione:** i candidati del modello richiedono collegamenti a fonti osservate e verifica deterministica; la revisione semantica è distinta.
- **Requisiti controllabili:** JSON Schema, identità, ambito delle fonti e comparabilità definiscono l'output accettabile.
- **Lavoro recuperabile:** acquisizioni immutabili, checkpoint e registri delle richieste conservano progressi e spesa.
- **Trasformazioni spiegabili:** unità, proiezioni, visualizzazione e gruppi restano collegati ai valori originali e ai record contributori.
- **Decisioni esplicite:** una proposta di cambiamento interrompe il lavoro prima di sostituire domanda o schema.

È utile per analisi, dati di riferimento, preparazione di dataset, sistemi interni e indagini riproducibili. Ricerca scientifica e usi regolamentati richiedono revisione indipendente di fonti, campionamento e conclusioni. L'ambizione è diventare uno standard affidabile per l'estrazione dei dati con prove verificabili, non dichiarare una leadership già raggiunta.

## Flussi e formati

La ricerca web usa browser e modelli configurati, con ricerca delle fonti opzionale. La preparazione deterministica legge file autorizzati o fonti HTTP GET dichiarate. Il percorso streaming è separato e produce conteggi, pagine di record e checkpoint.

| Input | Interpretazione |
| --- | --- |
| CSV / TSV | Campi testuali esatti, intestazioni esplicite e controllo della larghezza delle righe |
| JSON / JSONL | Record tipizzati con decodifica rigorosa |
| Testo | Record di testo con posizione nella fonte |
| DOCX / XLSX | Adattatori con limiti documentati; macro e formule non vengono eseguite |
| Immagini, video e altri file | Acquisizione immutabile di byte, hash e riferimenti; nessuna comprensione automatica del contenuto |
| Serie temporali | Politiche esplicite per serie e timestamp, ordinamento e diagnostica di lacune e duplicati |

L'acquisizione di file binari non equivale a OCR o interpretazione universale. OAuth, driver per database, connettori applicativi e paginazione delle API richiedono integrazioni specifiche. Vedi [formati](../../docs/formats.md).

## Installazione e configurazione

Servono Python **3.11–3.14**, Poetry e un'autorizzazione scritta all'esecuzione. La CI copre Linux, macOS e Windows. Per la ricerca con modelli occorrono un profilo compatibile e credenziali; per il browser, Chromium e le librerie di sistema. I file locali richiedono directory autorizzate e spazio disco. L'installazione normale non richiede un compilatore C++.

```bash
poetry install
poetry run verboisy --help
```

Conserva le chiavi in un ambiente privato o in `.env`, usando [.env.example](../../.env.example). Non inserirle nel repository. Gli esempi shell usano sintassi POSIX; su Windows configura le variabili con il metodo equivalente.

```bash
poetry run verboisy setup
poetry run verboisy model-config
```

`model-config` mostra le impostazioni e la presenza delle credenziali, non le chiavi. La preparazione locale deterministica non richiede modelli o browser. Leggi [provider](../../docs/providers.md) e [validazione](../../docs/validation.md).

## Ricerca web e API

```bash
poetry run verboisy run \
  --goal "Find research institutions and their explicitly published homepages" \
  --schema '[name,website,country]' \
  --export institutions.json
```

La scoperta automatica richiede un provider di ricerca; un task può invece dichiarare URL iniziali espliciti. JSON Schema permette tipi e vincoli precisi. Informazioni assenti possono restare `null`; valori non supportati vengono rifiutati. L'accettazione non certifica una copertura esaustiva del web.

```python
from verboisy import run

result = run(
    goal="Find research institutions and their published homepages",
    schema=["name", "website", "country"],
    export="institutions.json",
)
print(result.run_id, result.status, result.records)
```

Le applicazioni asincrone usano `arun`. L'API ordinaria materializza i record accettati; per grandi input locali usa il percorso streaming.

## Dati locali e sistemi interni

```bash
export DATASET_LOCAL_ROOTS='["/srv/verboisy-inputs"]'
poetry run verboisy run \
  --dataset-file 'jsonl=/srv/verboisy-inputs/observations.jsonl' \
  --schema observation-schema.json \
  --export observations.json
```

Directory e schema devono esistere. Le credenziali di un modello non autorizzano l'accesso al filesystem. Gli input HTTP dichiarati usano download limitati, controlli sui redirect, DNS vincolato e credenziali associate all'origine. La posizione delle fonti è indipendente dall'esecuzione del modello: un modello remoto può ricevere le osservazioni. Valuta trattamento dei dati, log, rete e conservazione prima di usare informazioni riservate.

## Grandi dataset

```bash
poetry run verboisy stream \
  --database observations-stream.db \
  --dataset-file 'jsonl=/srv/verboisy-inputs/observations.jsonl' \
  --schema observation-schema.json \
  --export observations.jsonl
```

Il registro streaming conserva blocchi immutabili e progressi transazionali. `stream-status` elenca i lavori; `stream --resume JOB_ID` riprende un lavoro salvato. `StreamLedger` permette accesso per pagine.

Un carico JSONL misurato su Linux/Python 3.12 ha preparato ed esportato **1.000.000 di righe**, da **1.105.888.890 byte**, con **89,15 MiB** di RSS massimo e **130,81 s** di durata. Sono stati verificati integrità dell'export e recupero dopo la cancellazione della fonte originale. È una misura di quel carico, non una garanzia generale. Vedi [streaming](../../docs/streaming.md) e [benchmark](../../docs/benchmarks.md).

## Proposte, ripresa e prove

```bash
poetry run verboisy changes --run-id RUN_ID
poetry run verboisy status --run-id RUN_ID
poetry run verboisy run --resume RUN_ID
```

`--resume` conserva i requisiti e rifiuta la proposta; `--okresume` accetta esattamente le modifiche salvate. Le proposte possono cambiare tipi, colonne o ambito della ricerca. La ripresa non azzera la spesa e non autorizza altre fonti implicitamente.

Gli intervalli rimangono intervalli: un limite inferiore non diventa un valore esatto o un massimo inventato. Colonne numeriche min/max richiedono lo schema appropriato. Le preferenze predefinite sono chilogrammi, metri e giorno/mese/anno; le alternative esplicite conservano i valori originali nelle prove. Le serie temporali non interpolano dati mancanti né risolvono orari locali ambigui per supposizione.

Gli export portabili comprendono prove, eventi rilevanti, provenienza dell'output e materiale acquisito quando applicabile. I gruppi identificano i contributori. I checksum verificano coerenza dei byte rispetto al manifest, non verità o autenticità indipendente. Vedi [provenienza](../../docs/proof.md).

## Architettura e documentazione

Python gestisce orchestrazione, contratti, adattatori, CLI e registri SQLite. Componenti C++17 opzionali accelerano specifici confronti delle prove, mantenendo implementazioni Python di riferimento. Test e CI verificano piattaforme, browser, recupero e integrità; è richiesta copertura completa di istruzioni e rami. Qualità su casi reali e compatibilità dei provider richiedono valutazioni proprie.

[CLI](../../docs/cli.md) · [API](../../docs/api.md) · [Contratti](../../docs/contracts.md) · [Identità](../../docs/smartid.md) · [Ingestione](../../docs/ingestion.md) · [Presentazione](../../docs/presentation.md) · [Semantica](../../docs/research-semantics.md) · [Architettura](../../ARCHITECTURE.md) · [Versioni](../../CHANGELOG.md)

## Licenze, demo e opportunità commerciali

Verboisy è software proprietario, **non open source**. La licenza inglese è il testo vincolante; questa traduzione non ne modifica i termini. Identificatore: `LicenseRef-Verboisy-Source-Inspection-1.0`. I componenti di terze parti conservano le proprie licenze. Esecuzione, test, modifica, integrazione, distribuzione e hosting richiedono permessi scritti separati.

Contatta **[emanueletorrisi98@gmail.com](mailto:emanueletorrisi98@gmail.com)** per demo, valutazioni, licenze interne o enterprise, investimenti, partnership o eventuale collaborazione retribuita. Indica flusso, fonti, volume e ambiente; non inviare credenziali o dati riservati. Prezzi, supporto e diritti vengono concordati individualmente. Vedi [licenze](../../docs/licensing.md) e [opportunità commerciali](../../docs/commercial.md).

## Feedback e prossime versioni

Verboisy è creato e mantenuto da **Emanuele Torrisi**, attualmente unico sviluppatore. [Segnalazioni di bug e richieste di funzionalità](https://github.com/EmanueleTorrisi/verboisy/issues) sono benvenute. Le vulnerabilità vanno segnalate privatamente secondo la [politica di sicurezza](../SECURITY.md).

Non si accettano contributi di codice non richiesti. Collaborazioni retribuite potranno essere concordate in futuro: definire prima ambito, compenso, riservatezza e proprietà intellettuale. Sono previste nuove versioni per migliorare qualità, fonti, scala e usabilità. La [roadmap](../../docs/development-roadmap.md) distingue capacità attuali e direzioni future. Non sono promesse accuratezza perfetta o compatibilità universale. Vedi [partecipazione](../CONTRIBUTING.md) e [copyright](../../COPYRIGHT.md).
