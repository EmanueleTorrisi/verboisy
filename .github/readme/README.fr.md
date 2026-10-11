<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

<p align="center"><img src="../../logo.png" alt="Verboisy" width="220" /></p>

[English](../../README.md) · [Italiano](README.it.md) · [Deutsch](README.de.md) · [Français](README.fr.md) · [Español](README.es.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [简体中文](README.zh-CN.md)

# Verboisy

**D'une question de recherche à un jeu de données dont les sources sont vérifiables.**

Recherche fondée sur des preuves · Extraction structurée · Données locales · Provenance portable

## Le produit

Verboisy est un moteur de recherche et d'extraction destiné aux personnes qui ont besoin d'informations structurées et veulent en comprendre l'origine. Une question, un schéma et les sources autorisées définissent le travail. Le système capture les observations, vérifie les enregistrements proposés et conserve preuves et transformations. La CLI et l'API Python permettent des processus reproductibles et la reprise d'un travail enregistré.

Le projet prépare aussi des données locales ou HTTP déclarées avec des adaptateurs déterministes, sans appels à un modèle, à la recherche ou au navigateur. Un parcours distinct utilise un registre sur disque et des buffers limités pour les grands fichiers locaux.

**Code consultable, utilisation sous licence distincte.** [LICENSE](../../LICENSE) autorise l'inspection du code, pas son exécution. Tests, modifications et déploiement nécessitent un accord écrit séparé. Les exemples décrivent un usage autorisé.

## Pourquoi cette approche

Un JSON ou un tableau ne suffit pas à expliquer si un fait a été observé ou comment un résultat a été transformé. Verboisy intègre ces vérifications au processus :

- **Des preuves avant l'acceptation :** les candidats du modèle nécessitent des liens vers des sources observées et une vérification déterministe ; la revue sémantique est distincte.
- **Des exigences maîtrisées :** JSON Schema, identité, périmètre des sources et comparabilité définissent les sorties acceptables.
- **Un travail récupérable :** captures immuables, points de reprise et journaux des requêtes conservent progrès et dépenses.
- **Des transformations traçables :** unités, projections, présentation et regroupements restent liés aux valeurs brutes et aux contributeurs.
- **Des décisions explicites :** une proposition suspend le travail avant de remplacer la question ou le schéma.

Les usages incluent analyse, données de référence, préparation de jeux de données, systèmes internes et enquêtes reproductibles. Les usages scientifiques ou réglementés nécessitent une revue indépendante des sources, de l'échantillonnage et des conclusions. L'ambition est de devenir un standard fiable d'extraction fondée sur des preuves, pas de revendiquer une position de leader déjà acquise.

## Parcours et formats

La recherche web utilise navigateur et modèles configurés, avec découverte par moteur de recherche en option. La préparation déterministe lit des fichiers autorisés ou des sources HTTP GET déclarées. Le parcours streaming distinct fournit compteurs, pages d'enregistrements et points de reprise.

| Entrée | Interprétation |
| --- | --- |
| CSV / TSV | Champs textuels exacts, en-têtes explicites et contrôle du nombre de cellules |
| JSON / JSONL | Objets typés avec décodage strict |
| Texte | Enregistrements textuels avec localisation dans la source |
| DOCX / XLSX | Adaptateurs limités et documentés ; aucune exécution de macros ou formules |
| Images, vidéos et autres fichiers | Capture immuable des octets, empreintes et références ; aucune interprétation automatique |
| Séries temporelles | Règles explicites de séries/horodatages, tri et diagnostic des lacunes et doublons |

La capture binaire n'est ni de l'OCR ni une compréhension universelle des documents. OAuth, pilotes de bases de données, connecteurs applicatifs et pagination d'API demandent des intégrations spécifiques. Voir [formats](../../docs/formats.md).

## Installation et configuration

Python **3.11–3.14**, Poetry et une autorisation écrite d'exécution sont nécessaires. La CI couvre Linux, macOS et Windows. La recherche avec modèles exige un profil compatible et des identifiants ; l'acquisition web exige Chromium et ses bibliothèques système. Les fichiers locaux nécessitent des répertoires autorisés et de l'espace disque. Aucun compilateur C++ n'est requis pour l'installation normale.

```bash
poetry install
poetry run verboisy --help
```

Conserver les clés dans un environnement privé ou `.env`, à partir de [.env.example](../../.env.example). Ne pas les publier. Les exemples shell utilisent POSIX ; sous Windows, configurer les variables avec la méthode équivalente.

```bash
poetry run verboisy setup
poetry run verboisy model-config
```

`model-config` indique les réglages et la présence d'identifiants sans afficher les clés. La préparation locale déterministe ne nécessite ni modèle ni navigateur. Voir [fournisseurs](../../docs/providers.md) et [validation](../../docs/validation.md).

## Recherche web et API

```bash
poetry run verboisy run \
  --goal "Find research institutions and their explicitly published homepages" \
  --schema '[name,website,country]' \
  --export institutions.json
```

La découverte automatique demande un fournisseur de recherche ; un task peut déclarer des URL de départ explicites. JSON Schema permet des types et contraintes précis. Les informations absentes peuvent rester `null` ; les valeurs non étayées sont rejetées. Une sortie acceptée ne certifie pas l'exhaustivité du web.

```python
from verboisy import run

result = run(
    goal="Find research institutions and their published homepages",
    schema=["name", "website", "country"],
    export="institutions.json",
)
print(result.run_id, result.status, result.records)
```

Les applications asynchrones utilisent `arun`. L'API habituelle matérialise les enregistrements acceptés ; les grands fichiers locaux utilisent le parcours streaming.

## Données locales et internes

```bash
export DATASET_LOCAL_ROOTS='["/srv/verboisy-inputs"]'
poetry run verboisy run \
  --dataset-file 'jsonl=/srv/verboisy-inputs/observations.jsonl' \
  --schema observation-schema.json \
  --export observations.json
```

Le répertoire et le schéma doivent exister. Les identifiants d'un modèle n'accordent pas d'accès au système de fichiers. Les sources HTTP déclarées utilisent téléchargements limités, politique de redirection, DNS épinglé et secrets associés à l'origine. Le lieu des sources est indépendant de l'exécution du modèle : un modèle distant peut recevoir les observations. Examiner transferts, journaux, réseau et conservation avant de traiter des données confidentielles.

## Grands jeux de données

```bash
poetry run verboisy stream \
  --database observations-stream.db \
  --dataset-file 'jsonl=/srv/verboisy-inputs/observations.jsonl' \
  --schema observation-schema.json \
  --export observations.jsonl
```

Le registre streaming conserve les blocs immuables et l'avancement transactionnel. `stream-status` liste les tâches ; `stream --resume JOB_ID` reprend une tâche enregistrée. `StreamLedger` donne accès aux enregistrements par pages.

Un scénario JSONL mesuré sous Linux/Python 3.12 a préparé et exporté **1 000 000 de lignes** à partir de **1 105 888 890 octets**, avec **89,15 MiB** de RSS maximal et **130,81 s** de durée. Reprise après suppression de la source originale et intégrité des exports ont été vérifiées. Ce résultat concerne un scénario, pas toutes les machines ou données. Voir [streaming](../../docs/streaming.md) et [mesures](../../docs/benchmarks.md).

## Propositions, reprise et preuves

```bash
poetry run verboisy changes --run-id RUN_ID
poetry run verboisy status --run-id RUN_ID
poetry run verboisy run --resume RUN_ID
```

`--resume` conserve les exigences et refuse la proposition ; `--okresume` accepte exactement les changements enregistrés. Une proposition peut modifier types, colonnes ou périmètre de recherche. La reprise ne remet pas la dépense à zéro et n'élargit pas implicitement les sources autorisées.

Un intervalle reste un intervalle : une borne inférieure ne devient ni une valeur exacte ni un maximum inventé. Des colonnes numériques min/max demandent un schéma adapté. Les valeurs par défaut sont kilogrammes, mètres et jour/mois/année ; les alternatives explicites préservent les preuves originales. Les diagnostics temporels n'interpolent pas les observations et ne devinent pas les heures locales ambiguës.

Les exports portables incluent preuves, événements pertinents, provenance des sorties et sources capturées selon le parcours. Les groupes identifient leurs contributeurs. Les sommes de contrôle établissent la cohérence des octets avec le manifeste, pas la vérité ou une authenticité indépendante. Voir [provenance](../../docs/proof.md).

## Architecture et documentation

Python assure orchestration, contrats, adaptateurs, CLI et registres SQLite. Des composants C++17 optionnels accélèrent certains rapprochements de preuves tout en conservant les références Python. Tests et CI couvrent plateformes, navigateur, reprise et intégrité ; une couverture complète des instructions et branches est requise. La qualité réelle et la compatibilité des fournisseurs nécessitent des évaluations distinctes.

[CLI](../../docs/cli.md) · [API](../../docs/api.md) · [Contrats](../../docs/contracts.md) · [Identité](../../docs/smartid.md) · [Ingestion](../../docs/ingestion.md) · [Présentation](../../docs/presentation.md) · [Sémantique](../../docs/research-semantics.md) · [Architecture](../../ARCHITECTURE.md) · [Versions](../../CHANGELOG.md)

## Licences, démonstrations et contacts commerciaux

Verboisy est propriétaire, **pas open source**. La licence anglaise fait autorité ; cette traduction ne change pas les permissions. Identifiant : `LicenseRef-Verboisy-Source-Inspection-1.0`. Les composants tiers conservent leurs licences. Exécution, tests, modification, intégration, distribution et hébergement nécessitent des permissions écrites séparées.

Contacter **[emanueletorrisi98@gmail.com](mailto:emanueletorrisi98@gmail.com)** pour une démo, une évaluation, une licence interne/entreprise, un investissement, un partenariat ou une éventuelle collaboration rémunérée. Décrire processus, sources, volume et environnement ; ne pas envoyer de secrets ou de données confidentielles. Prix, support et droits sont convenus individuellement. Voir [licences](../../docs/licensing.md) et [contacts commerciaux](../../docs/commercial.md).

## Retours et prochaines versions

**Emanuele Torrisi** crée et maintient Verboisy et en est actuellement le seul développeur. [Rapports de bugs et demandes de fonctionnalités](https://github.com/EmanueleTorrisi/verboisy/issues) sont bienvenus. Les vulnérabilités se signalent en privé selon la [politique de sécurité](../SECURITY.md).

Les contributions de code non sollicitées ne sont pas acceptées. Une collaboration rémunérée pourra être convenue : définir périmètre, rémunération, confidentialité et propriété intellectuelle avant le travail. D'autres versions sont prévues pour améliorer qualité, sources, capacité et ergonomie. La [feuille de route](../../docs/development-roadmap.md) distingue fonctions actuelles et directions futures. Aucune exactitude parfaite ou compatibilité universelle n'est promise. Voir [participation](../CONTRIBUTING.md) et [copyright](../../COPYRIGHT.md).
