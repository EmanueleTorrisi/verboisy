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
<p align="center"><strong>Dalla domanda di ricerca a un dataset di cui puoi verificare le fonti.</strong></p>
<p align="center">Ricerca con prove · Estrazione strutturata · Dati locali · Provenienza portabile</p>


## Il prodotto

Verboisy è un motore di ricerca ed estrazione dei dati per chi ha bisogno di informazioni strutturate e vuole capire da dove provengono. Una domanda, uno schema e le fonti consentite definiscono il lavoro: il sistema acquisisce osservazioni, verifica i record proposti e conserva le prove e le trasformazioni che portano al risultato. CLI e API Python permettono flussi ripetibili e ripresa del lavoro salvato.

Il progetto prepara anche dataset locali o HTTP dichiarati tramite adattatori deterministici, senza chiamate a modelli, ricerca o browser. Un percorso separato usa un registro su disco e buffer limitati per file locali di grandi dimensioni.

**Codice consultabile, utilizzo soggetto a licenza commerciale.** [LICENSE](https://github.com/EmanueleTorrisi/verboisy/blob/main/LICENSE) permette l'ispezione del codice, non l'esecuzione. Test, modifiche e distribuzione richiedono un accordo scritto separato. Gli esempi descrivono un utilizzo autorizzato.

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

L'acquisizione di file binari non equivale a OCR o interpretazione universale. OAuth, driver per database, connettori applicativi e paginazione delle API richiedono integrazioni specifiche. Vedi [formati](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/formats.md).

## Installazione e configurazione

Servono Python **3.11–3.14** e un’autorizzazione scritta all’esecuzione. Poetry è uno strumento di sviluppo: il comando installato è `verboisy`. La CI definisce job per Linux, macOS e Windows; i risultati correnti devono essere verificati. Per la ricerca web servono il provider configurato, Chromium e le librerie di sistema. La preparazione locale richiede directory autorizzate e spazio disco. Non serve un compilatore C++.

Da un checkout autorizzato, esegui i comandi seguenti. Con pipx già installato puoi usare `pipx install .` per rendere il comando disponibile fuori dal progetto. Dopo la pubblicazione autorizzata su PyPI: `pipx install verboisy`. La disponibilità su PyPI non è presunta. `python examples/local_quickstart.py` verifica due record sintetici senza modelli o browser.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
verboisy --help
```

Conserva le chiavi in un ambiente privato o in `.env`, usando [.env.example](https://github.com/EmanueleTorrisi/verboisy/blob/main/.env.example). Non inserirle nel repository. Gli esempi shell usano sintassi POSIX; su Windows configura le variabili con il metodo equivalente.

```bash
verboisy setup
verboisy model-config
```

`model-config` mostra le impostazioni e la presenza delle credenziali, non le chiavi. La preparazione locale deterministica non richiede modelli o browser. Leggi [provider](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/providers.md) e [validazione](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/validation.md).

## Ricerca web e API

```bash
verboisy run \
  --goal "Trova istituti di ricerca e i loro siti web ufficiali esplicitamente pubblicati" \
  --schema '[nome,sito_web,paese]' \
  --export istituzioni.json
```

La scoperta automatica richiede un provider di ricerca; un task può invece dichiarare URL iniziali espliciti. JSON Schema permette tipi e vincoli precisi. Informazioni assenti possono restare `null`; valori non supportati vengono rifiutati. L'accettazione non certifica una copertura esaustiva del web.

```python
from verboisy import run

risultato = run(
    goal="Trova istituti di ricerca e i loro siti web ufficiali pubblicati",
    schema=["nome", "sito_web", "paese"],
    export="istituzioni.json",
)
print(risultato.run_id, risultato.status, risultato.records)
```

Le applicazioni asincrone usano `arun`. L'API ordinaria materializza i record accettati; per grandi input locali usa il percorso streaming.

## Dati locali e sistemi interni

```bash
export DATASET_LOCAL_ROOTS='["/srv/dati-verboisy"]'
verboisy run \
  --dataset-file 'jsonl=/srv/dati-verboisy/osservazioni.jsonl' \
  --schema schema-osservazioni.json \
  --export osservazioni.json
```

Directory e schema devono esistere. Le credenziali di un modello non autorizzano l'accesso al filesystem. Gli input HTTP dichiarati usano download limitati, controlli sui redirect, DNS vincolato e credenziali associate all'origine. La posizione delle fonti è indipendente dall'esecuzione del modello: un modello remoto può ricevere le osservazioni. Valuta trattamento dei dati, log, rete e conservazione prima di usare informazioni riservate.

## Grandi dataset

```bash
verboisy stream \
  --database osservazioni-stream.db \
  --dataset-file 'jsonl=/srv/dati-verboisy/osservazioni.jsonl' \
  --schema schema-osservazioni.json \
  --export osservazioni.jsonl
```

Il registro streaming conserva blocchi immutabili e progressi transazionali. `stream-status` elenca i lavori; `stream --resume ID_LAVORO` riprende un lavoro salvato. `StreamLedger` permette accesso per pagine.

Un carico JSONL misurato su Linux/Python 3.12 ha preparato ed esportato **1.000.000 di righe**, da **1.105.888.890 byte**, con **89,15 MiB** di RSS massimo e **130,81 s** di durata. Sono stati verificati integrità dell'export e recupero dopo la cancellazione della fonte originale. È una misura di quel carico, non una garanzia generale. Vedi [streaming](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/streaming.md) e [benchmark](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/benchmarks.md).

## Proposte, ripresa e prove

```bash
verboisy changes --run-id ID_ESECUZIONE
verboisy status --run-id ID_ESECUZIONE
verboisy run --resume ID_ESECUZIONE
```

`--resume` conserva i requisiti e rifiuta la proposta; `--okresume` accetta esattamente le modifiche salvate. Le proposte possono cambiare tipi, colonne o ambito della ricerca. La ripresa non azzera la spesa e non autorizza altre fonti implicitamente.

Gli intervalli rimangono intervalli: un limite inferiore non diventa un valore esatto o un massimo inventato. Colonne numeriche min/max richiedono lo schema appropriato. Le preferenze predefinite sono chilogrammi, metri e giorno/mese/anno; le alternative esplicite conservano i valori originali nelle prove. Le serie temporali non interpolano dati mancanti né risolvono orari locali ambigui per supposizione.

Gli export portabili comprendono prove, eventi rilevanti, provenienza dell'output e materiale acquisito quando applicabile. I gruppi identificano i contributori. I checksum verificano coerenza dei byte rispetto al manifest, non verità o autenticità indipendente. Vedi [provenienza](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/proof.md).

## Architettura e documentazione

Python gestisce orchestrazione, contratti, adattatori, CLI e registri SQLite. Componenti C++17 opzionali accelerano specifici confronti delle prove, mantenendo implementazioni Python di riferimento. Test e CI verificano piattaforme, browser, recupero e integrità; è richiesta copertura completa di istruzioni e rami. Qualità su casi reali e compatibilità dei provider richiedono valutazioni proprie.

[CLI](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/cli.md) · [API](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/api.md) · [Contratti](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/contracts.md) · [Identità](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/smartid.md) · [Ingestione](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/ingestion.md) · [Presentazione](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/presentation.md) · [Semantica](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/research-semantics.md) · [Architettura](https://github.com/EmanueleTorrisi/verboisy/blob/main/ARCHITECTURE.md) · [Versioni](https://github.com/EmanueleTorrisi/verboisy/blob/main/CHANGELOG.md)

## Licenze, demo e opportunità commerciali

Verboisy è software proprietario, **non open source**. La licenza inglese è il testo vincolante; questa traduzione non ne modifica i termini. Identificatore: `LicenseRef-Verboisy-Source-Inspection-1.0`. I componenti di terze parti conservano le proprie licenze. Esecuzione, test, modifica, integrazione, distribuzione e hosting richiedono permessi scritti separati.

Contatta **[emanueletorrisi98@gmail.com](mailto:emanueletorrisi98@gmail.com)** per demo, valutazioni, licenze interne o enterprise, investimenti, partnership o eventuale collaborazione retribuita. Indica flusso, fonti, volume e ambiente; non inviare credenziali o dati riservati. Prezzi, supporto e diritti vengono concordati individualmente. Vedi [licenze](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/licensing.md) e [opportunità commerciali](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/commercial.md).

## Feedback e collaborazione

Verboisy è creato e mantenuto da **Emanuele Torrisi**, attualmente unico sviluppatore. [Segnalazioni di bug e richieste di funzionalità](https://github.com/EmanueleTorrisi/verboisy/issues) sono benvenute. Le vulnerabilità vanno segnalate privatamente secondo la [politica di sicurezza](https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/SECURITY.md).

Non si accettano contributi di codice non richiesti. Le collaborazioni retribuite richiedono accordi preventivi su ambito, compenso, riservatezza e proprietà intellettuale. Le modifiche delle versioni sono documentate nel [changelog](https://github.com/EmanueleTorrisi/verboisy/blob/main/CHANGELOG.md); la [cronologia](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/development-roadmap.md) descrive il percorso da 0.1.0 a 1.0.0. Vedi [partecipazione](https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/CONTRIBUTING.md) e [copyright](https://github.com/EmanueleTorrisi/verboisy/blob/main/COPYRIGHT.md).
## Esempi applicativi

[Catalogo degli istituti di ricerca](https://github.com/EmanueleTorrisi/verboisy/blob/main/examples/research_catalog/README.md) ·
[Elaborazione di grandi dataset locali di osservazioni](https://github.com/EmanueleTorrisi/verboisy/blob/main/examples/streaming_observations/README.md) ·
[Cronologia delle versioni: 0.1.0–1.0.0](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/development-roadmap.md)


## Contratti dei dati e qualificazione

Nei risultati ordinari, `id` è riservato ai metadati generati. Gli ID della fonte richiedono una proiezione esplicita a `source_id`; restano validi gli ID annidati e dello streaming. I campi opzionali assenti restano assenti; null esplicito viene conservato. Lo streaming convalida singole righe e rifiuta i vincoli di collezione non supportati. Una preparazione in pausa restituisce il codice 2. La CI è configurata; le misure storiche valgono soltanto per il codice sorgente e l’ambiente registrati.

[Risultati storici; non qualificano automaticamente il codice corrente](https://github.com/EmanueleTorrisi/verboisy/blob/main/evals/results/offline-validation.json).


## Perché scegliere un accordo commerciale?

**Dall’ispezione del codice a un flusso di lavoro autorizzato e assistito.** Il valore commerciale comprende i diritti d’uso concordati e, se acquistati, servizi specialistici per configurare, integrare e mantenere il flusso.

| Obiettivo | Ambito da concordare |
| --- | --- |
| Usare Verboisy nel lavoro quotidiano | Diritti scritti di esecuzione e uso interno per utenti e ambienti concordati |
| Integrare il prodotto | Diritti di modifica, integrazione e distribuzione o deployment adeguati |
| Ridurre il lavoro iniziale | Onboarding, progettazione degli schemi e valutazione su dati rappresentativi |
| Operare in ambienti privati | Valutazione del deployment e integrazione delle fonti autorizzate |
| Pianificare manutenzione e supporto | Aggiornamenti, assistenza e tempi di risposta definiti nel contratto |

Servizi, prezzi, scadenze e diritti dipendono dall’accordo scritto. Il download non include automaticamente il supporto. Questo repository non contiene un livello Pro separato né un servizio di attivazione con codici. Hosting, pianificazione, spazi di lavoro condivisi e nuovi connettori sono obiettivi di sviluppo, non funzionalità già promesse.

[emanueletorrisi98@gmail.com](mailto:emanueletorrisi98@gmail.com)

[Installazione](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/installation.md) · [Rilascio e valutazione](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/release.md)

La versione è `1.0.0`, ma la qualificazione completa è ancora in sospeso. La matrice distingue test tecnici, valutazione su casi reali, beta indipendente e revisione del responsabile del rilascio.
