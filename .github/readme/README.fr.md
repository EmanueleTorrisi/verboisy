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
<p align="center"><strong>D'une question de recherche à un jeu de données dont les sources sont vérifiables.</strong></p>
<p align="center">Recherche fondée sur des preuves · Extraction structurée · Données locales · Provenance portable</p>


> **État de la version :** la version `1.0.0` est prête pour une utilisation en production dans le cadre des processus documentés, des environnements pris en charge et des limites testées. La [matrice de publication](https://github.com/EmanueleTorrisi/verboisy/blob/main/evals/release-matrix.json) consigne les vérifications techniques, l’évaluation de tâches réelles, la bêta indépendante et les approbations des responsables de la publication.

## Le produit

Verboisy est un moteur de recherche et d'extraction destiné aux personnes qui ont besoin d'informations structurées et veulent en comprendre l'origine. Une question, un schéma et les sources autorisées définissent le travail. Le système capture les observations, vérifie les enregistrements proposés et conserve preuves et transformations. La CLI et l'API Python permettent des processus reproductibles et la reprise d'un travail enregistré.

Le projet prépare aussi des données locales ou HTTP déclarées avec des adaptateurs déterministes, sans appels à un modèle, à la recherche ou au navigateur. Un parcours distinct utilise un registre sur disque et des buffers limités pour les grands fichiers locaux.

**Code consultable, utilisation sous licence distincte.** [LICENSE](https://github.com/EmanueleTorrisi/verboisy/blob/main/LICENSE) autorise l'inspection du code, pas son exécution. Tests, modifications et déploiement nécessitent un accord écrit séparé. Les exemples décrivent un usage autorisé.

## Voir la CLI en action

<p align="center">
  <a href="https://asciinema.org/a/kao32h7xRRkFwtkc">
    <img src="../assets/verboisy-demo.gif" alt="Verboisy CLI Demo">
  </a>
</p>

## Pourquoi cette approche

Un JSON ou un tableau ne suffit pas à expliquer si un fait a été observé ou comment un résultat a été transformé. Verboisy intègre ces vérifications au processus :

- **Des preuves avant l'acceptation :** les candidats du modèle nécessitent des liens vers des sources observées et une vérification déterministe ; la revue sémantique est distincte.
- **Des exigences maîtrisées :** JSON Schema, identité, périmètre des sources et comparabilité définissent les sorties acceptables.
- **Un travail récupérable :** captures immuables, points de reprise et journaux des requêtes conservent progrès et dépenses.
- **Des transformations traçables :** unités, projections, présentation et regroupements restent liés aux valeurs brutes et aux contributeurs.
- **Des décisions explicites :** une proposition suspend le travail avant de remplacer la question ou le schéma.

Les usages incluent analyse, données de référence, préparation de jeux de données, systèmes internes et enquêtes reproductibles. Les usages scientifiques ou réglementés nécessitent une revue indépendante des sources, de l'échantillonnage et des conclusions. L'ambition est de devenir un standard fiable d'extraction fondée sur des preuves, pas de revendiquer une position de leader déjà acquise.

### Réserver l’IA aux étapes où l’interprétation apporte une valeur

Verboisy associe code déterministe et IA sémantique. La lecture des fichiers structurés, la validation des schémas, la vérification des correspondances avec les preuves observées et l’export sont exécutés par le code. Les modèles contribuent à la planification et à l’interprétation lorsque le processus le demande. Les étapes déterministes ne consomment aucun token de modèle et évitent les frais d’inférence qu’entraînerait leur traitement par un LLM payant. La préparation de jeux de données locaux peut fonctionner intégralement sans fournisseur de modèles.

Cette approche réduit les appels superflus et rend les dépenses vérifiables. L’économie totale dépend de la tâche, du modèle, des nouvelles tentatives et du travail de contrôle. Une comparaison équitable emploie les mêmes sources, exigences de sortie et critères de qualité, en incluant les échecs. La vérification des preuves réduit les résultats non étayés ; la justesse sémantique dépend toujours des sources et de leur examen.

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

La capture binaire n'est ni de l'OCR ni une compréhension universelle des documents. OAuth, pilotes de bases de données, connecteurs applicatifs et pagination d'API demandent des intégrations spécifiques. Voir [formats](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/formats.md).

## Installation et configuration

Python **3.11–3.14** et une autorisation écrite d’exécution sont nécessaires. Poetry sert au développement ; la commande installée est `verboisy`. Utilisez les profils de système d’exploitation et d’interpréteur indiqués dans la matrice de publication. La recherche web nécessite un fournisseur configuré, Chromium et ses bibliothèques système. Les sources locales exigent des répertoires autorisés et de l’espace disque. Aucun compilateur C++ n’est requis.

Exécutez les commandes suivantes depuis une copie autorisée du dépôt. Avec pipx installé, `pipx install .` rend la commande disponible hors du projet. Après publication autorisée sur PyPI : `pipx install verboisy`. La disponibilité sur PyPI n’est pas présumée. `python examples/local_quickstart.py` vérifie deux enregistrements synthétiques sans modèle ni navigateur.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
verboisy --help
```

Conserver les clés dans un environnement privé ou `.env`, à partir de [.env.example](https://github.com/EmanueleTorrisi/verboisy/blob/main/.env.example). Ne pas les publier. Les exemples shell utilisent POSIX ; sous Windows, configurer les variables avec la méthode équivalente.

```bash
verboisy setup
verboisy model-config
```

`model-config` indique les réglages et la présence d'identifiants sans afficher les clés. La préparation locale déterministe ne nécessite ni modèle ni navigateur. Voir [fournisseurs](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/providers.md) et [validation](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/validation.md).

## Recherche web et API

```bash
verboisy run \
  --goal "Trouve des établissements de recherche et leurs sites web officiels explicitement publiés" \
  --schema '[nom,site_web,pays]' \
  --export institutions.json
```

La découverte automatique demande un fournisseur de recherche ; un task peut déclarer des URL de départ explicites. JSON Schema permet des types et contraintes précis. Les informations absentes peuvent rester `null` ; les valeurs non étayées sont rejetées. Une sortie acceptée ne certifie pas l'exhaustivité du web.

```python
from verboisy import run

resultat = run(
    goal="Trouve des établissements de recherche et leurs sites web officiels publiés",
    schema=["nom", "site_web", "pays"],
    export="institutions.json",
)
print(resultat.run_id, resultat.status, resultat.records)
```

Les applications asynchrones utilisent `arun`. L'API habituelle matérialise les enregistrements acceptés ; les grands fichiers locaux utilisent le parcours streaming.

## Données locales et internes

```bash
export DATASET_LOCAL_ROOTS='["/srv/donnees-verboisy"]'
verboisy run \
  --goal "Prépare les observations locales selon le schéma fourni en conservant les valeurs sources" \
  --dataset-file 'jsonl=/srv/donnees-verboisy/observations.jsonl' \
  --schema schema-observations.json \
  --mass-unit source --length-unit source --date-format source \
  --export observations.json
```

Le répertoire et le schéma doivent exister. Les identifiants d'un modèle n'accordent pas d'accès au système de fichiers. Les sources HTTP déclarées utilisent téléchargements limités, politique de redirection, DNS épinglé et secrets associés à l'origine. Le lieu des sources est indépendant de l'exécution du modèle : un modèle distant peut recevoir les observations. Examiner transferts, journaux, réseau et conservation avant de traiter des données confidentielles.

## Grands jeux de données

```bash
verboisy stream \
  --database observations-flux.db \
  --dataset-file 'jsonl=/srv/donnees-verboisy/observations.jsonl' \
  --schema schema-observations.json \
  --export observations.jsonl
```

Le registre streaming conserve les blocs immuables et l'avancement transactionnel. `stream-status` liste les tâches ; `stream --resume ID_TACHE` reprend une tâche enregistrée. `StreamLedger` donne accès aux enregistrements par pages.

Un scénario JSONL mesuré sous Linux/Python 3.12 a préparé et exporté **1 000 000 de lignes** à partir de **1 105 888 890 octets**, avec **89,15 MiB** de RSS maximal et **130,81 s** de durée. Reprise après suppression de la source originale et intégrité des exports ont été vérifiées. Ce résultat concerne un scénario, pas toutes les machines ou données. Voir [streaming](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/streaming.md) et [mesures](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/benchmarks.md).

## Propositions, reprise et preuves

```bash
verboisy changes --run-id ID_EXECUTION
verboisy status --run-id ID_EXECUTION
verboisy run --resume ID_EXECUTION
```

`--resume` conserve les exigences et refuse la proposition ; `--okresume` accepte exactement les changements enregistrés. Une proposition peut modifier types, colonnes ou périmètre de recherche. La reprise ne remet pas la dépense à zéro et n'élargit pas implicitement les sources autorisées.

Un intervalle reste un intervalle : une borne inférieure ne devient ni une valeur exacte ni un maximum inventé. Des colonnes numériques min/max demandent un schéma adapté. Les valeurs par défaut sont kilogrammes, mètres et jour/mois/année ; les alternatives explicites préservent les preuves originales. Les diagnostics temporels n'interpolent pas les observations et ne devinent pas les heures locales ambiguës.

Les exports portables incluent preuves, événements pertinents, provenance des sorties et sources capturées selon le parcours. Les groupes identifient leurs contributeurs. Les sommes de contrôle établissent la cohérence des octets avec le manifeste, pas la vérité ou une authenticité indépendante. Voir [provenance](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/proof.md).

## Architecture et documentation

Python assure orchestration, contrats, adaptateurs, CLI et registres SQLite. Des composants C++17 optionnels accélèrent certains rapprochements de preuves tout en conservant les références Python. Tests et CI couvrent plateformes, navigateur, reprise et intégrité ; une couverture complète des instructions et branches est requise. La qualité réelle et la compatibilité des fournisseurs nécessitent des évaluations distinctes.

[CLI](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/cli.md) · [API](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/api.md) · [Contrats](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/contracts.md) · [Identité](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/smartid.md) · [Ingestion](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/ingestion.md) · [Présentation](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/presentation.md) · [Sémantique](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/research-semantics.md) · [Architecture](https://github.com/EmanueleTorrisi/verboisy/blob/main/ARCHITECTURE.md) · [Versions](https://github.com/EmanueleTorrisi/verboisy/blob/main/CHANGELOG.md)

## Licences, démonstrations et contacts commerciaux

Verboisy est propriétaire, **pas open source**. La licence anglaise fait autorité ; cette traduction ne change pas les permissions. La version applicable figure dans le fichier [LICENSE](https://github.com/EmanueleTorrisi/verboisy/blob/main/LICENSE) fourni avec le logiciel. Les composants tiers conservent leurs licences. Exécution, tests, modification, intégration, distribution et hébergement nécessitent des permissions écrites séparées.

Contacter **[emanueletorrisi98@gmail.com](mailto:emanueletorrisi98@gmail.com)** pour une démo, une évaluation, une licence interne/entreprise, un partenariat ou une éventuelle collaboration rémunérée. Décrire processus, sources, volume et environnement ; ne pas envoyer de secrets ou de données confidentielles. Prix, support et droits sont convenus individuellement. Voir [licences](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/licensing.md) et [contacts commerciaux](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/commercial.md).

## Retours et collaboration

**Emanuele Torrisi** crée et maintient Verboisy et en est actuellement le seul développeur. [Rapports de bugs et demandes de fonctionnalités](https://github.com/EmanueleTorrisi/verboisy/issues) sont bienvenus. Les vulnérabilités se signalent en privé selon la [politique de sécurité](https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/SECURITY.md).

Les contributions de code non sollicitées ne sont pas acceptées. Une collaboration rémunérée nécessite un accord préalable sur le périmètre, la rémunération, la confidentialité et la propriété intellectuelle. Les changements figurent dans le [changelog](https://github.com/EmanueleTorrisi/verboisy/blob/main/CHANGELOG.md) ; l’[historique](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/development-roadmap.md) décrit le parcours de 0.1.0 à 1.0.0. Voir [participation](https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/CONTRIBUTING.md) et [droits](https://github.com/EmanueleTorrisi/verboisy/blob/main/COPYRIGHT.md).

## Exemples de workflows

[Catalogue des établissements de recherche](https://github.com/EmanueleTorrisi/verboisy/blob/main/examples/research_catalog/README.md) ·
[Traitement de grands jeux de données locaux d’observations](https://github.com/EmanueleTorrisi/verboisy/blob/main/examples/streaming_observations/README.md) ·
[Historique des versions : 0.1.0–1.0.0](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/development-roadmap.md)


## Contrats de données et qualification

Dans les résultats ordinaires, `id` est réservé aux métadonnées générées. Les identifiants source doivent être projetés explicitement vers `source_id`; les identifiants imbriqués et de streaming restent permis. Les champs optionnels absents restent absents; null explicite est conservé. Le streaming valide chaque ligne et refuse les contraintes de collection non prises en charge. Une préparation en pause retourne le code 2. Les mesures historiques concernent le code source et l’environnement indiqués dans le rapport correspondant.

[Résultats historiques](https://github.com/EmanueleTorrisi/verboisy/blob/main/evals/results/offline-validation.json) · [Preuves et approbations de publication](https://github.com/EmanueleTorrisi/verboisy/blob/main/evals/release-matrix.json).


## Pourquoi choisir un accord commercial ?

Ce dépôt contient **l’édition publique de Verboisy destinée à l’inspection du code source**. Les clients commerciaux reçoivent **une édition maintenue séparément, dotée de fonctionnalités supplémentaires** qui ne sont pas distribuées dans ce dépôt.

Le [comparatif des éditions](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/commercial.md) présente le périmètre des éditions, les modes de déploiement et les services. Les notes de version commerciales et l’accord signé précisent les fonctionnalités supplémentaires livrées. Le dépôt public continuera de recevoir des mises à jour.

Les fonctionnalités livrées, droits d’utilisation, prestations d’assistance, droits aux mises à jour, tarifs et dates de livraison sont définis dans l’accord signé.

| Objectif | Périmètre à convenir |
| --- | --- |
| Utiliser Verboisy au quotidien | Droits écrits d’exécution et d’usage interne pour les utilisateurs et environnements convenus |
| Intégrer le produit | Droits adaptés de modification, d’intégration, de déploiement ou de redistribution |
| Réduire le travail initial | Accompagnement, conception de schémas et évaluation de données représentatives |
| Utiliser une infrastructure privée | Étude du déploiement et intégration des sources autorisées |
| Planifier maintenance et assistance | Mises à jour, prestations et délais de réponse définis au contrat |

L’édition et les services sont choisis selon le processus métier, les contraintes de déploiement et les critères de réception. Le contrat précise les livrables et les responsabilités.

[emanueletorrisi98@gmail.com](mailto:emanueletorrisi98@gmail.com)

[Installation](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/installation.md) · [Publication et évaluation](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/release.md)
