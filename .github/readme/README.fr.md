<a id="readme-top"></a>
<p align="center">
  <img src="../../logo.png" alt="Verboisy" width="300" />
</p>
<p align="center">
  <strong>Un agent autonome de recherche web et d'extraction structurée vers JSON.</strong>
  <br />
  Donnez-lui un objectif en anglais simple et un schéma JSON. Il planifie sa propre navigation, lit la page et renvoie des données structurées et validées.
</p>

<p align="center">
  <a href="https://github.com/EmanueleTorrisi/verboisy/actions/workflows/ci.yml"><img src="https://github.com/EmanueleTorrisi/verboisy/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://codecov.io/gh/EmanueleTorrisi/verboisy"><img src="https://codecov.io/gh/EmanueleTorrisi/verboisy/graph/badge.svg?token=CINC6IHYF2" alt="Couverture"></a>
  <a href="https://emanueletorrisi.github.io/verboisy/"><img src="https://github.com/EmanueleTorrisi/verboisy/actions/workflows/docs.yml/badge.svg" alt="Documentation"></a>
  <a href="#installation"><img src="https://img.shields.io/badge/PyPI-coming%20soon-lightgrey?style=flat" alt="PyPI : bientôt disponible"></a>
  <!--<a href="https://pypi.org/project/verboisy/"><img src="https://img.shields.io/pypi/v/verboisy?style=flat" alt="Version PyPI"></a>-->
  <img src="https://img.shields.io/badge/python-3.11%2B-blue?style=flat" alt="Python 3.11+">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/EmanueleTorrisi/verboisy?style=flat" alt="Licence"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/badge/style-ruff-261230?style=flat" alt="Ruff"></a>
</p>

<p align="center">
  <em>v0.1.0 | version pré-1.0 en développement actif. Attendez-vous à des changements majeurs entre les versions mineures jusqu'à la 1.0.</em>
</p>

<p align="center">
  <a href="../../README.md" title="English" aria-label="English">🇬🇧</a> ·
  <a href="README.it.md" title="Italiano" aria-label="Italiano">🇮🇹</a> ·
  <a href="README.de.md" title="Deutsch" aria-label="Deutsch">🇩🇪</a> ·
  <a href="README.zh-CN.md" title="简体中文" aria-label="简体中文">🇨🇳</a> ·
  <strong title="Français" aria-label="Français">🇫🇷</strong> ·
  <a href="README.es.md" title="Español" aria-label="Español">🇪🇸</a> ·
  <a href="README.ko.md" title="한국어" aria-label="한국어">🇰🇷</a> ·
  <a href="README.ja.md" title="日本語" aria-label="日本語">🇯🇵</a>
</p>

## Table des matières

- [Démo](#démo)
- [Pourquoi Verboisy](#pourquoi-verboisy)
- [Comparatif](#comparatif)
- [Exemple rapide](#exemple-rapide)
- [Cas d'usage](#cas-dusage)
- [Comment ça marche](#comment-ça-marche)
- [Installation](#installation)
- [Configuration](#configuration)
- [Utilisation](#utilisation)
- [Docker](#docker)
- [Limitations connues](#limitations-connues)
- [Utilisation responsable](#utilisation-responsable)
- [Documentation](#documentation)
- [Contribution](#contribution)
- [Sécurité](#sécurité)
- [Licence](#licence)

## Démo

<p align="center">
  <img src="../../docs/demo.gif" alt="Verboisy CLI demo">
</p>

## Pourquoi Verboisy

- **Piloté par les objectifs, pas par les sélecteurs.** Décrivez l'objectif en anglais simple. Le planificateur décide du prochain clic, défilement ou lecture sur la page qu'il a sous les yeux. Rien n'est codé en dur, évitant ainsi de devoir tout réécrire lors d'une refonte du site.
- **Le schéma d'abord, pas le "au mieux".** Chaque enregistrement est vérifié par rapport à un modèle Pydantic généré à partir de votre schéma JSON avant d'être sauvegardé. Aucune donnée mal formée n'atteint votre base de données.
- **Apportez votre propre modèle, conservez votre infrastructure.** OpenAI, Anthropic ou un modèle Ollama local via [LiteLLM](https://github.com/BerriAI/litellm) : une seule variable d'environnement à modifier. S'exécute sur votre machine ou vos serveurs, pas dans une boîte noire hébergée.
- **Reprenable par conception.** Chaque enregistrement est écrit dans SQLite dès qu'il est validé. `verboisy run --resume` (ou `run(resume=True)` en Python) reprend la dernière exécution incomplète. Un plantage ne vous coûte que l'étape en cours, pas le travail déjà enregistré.

Ce qui accompagne cette boucle : Playwright asynchrone (Chromium, avec ou sans interface), un nettoyage du DOM optimisé pour les fenêtres de contexte des LLM au lieu de bruts HTML, et un export JSON ou CSV – ou interrogez directement la base de données SQLite.

## Comparatif

Verboisy se situe à l'intersection d'un agent navigateur autonome et d'un extracteur validé par schéma. Les outils existants couvrent généralement bien l'un de ces aspects ; celui-ci est conçu pour les deux.

| | Verboisy | [Browser Use](https://github.com/browser-use/browser-use) | [Firecrawl](https://github.com/firecrawl/firecrawl) | [Crawl4AI](https://github.com/unclecode/crawl4ai) |
| --- | --- | --- | --- | --- |
| Vous décrivez | un objectif **et** un schéma JSON | un objectif | une URL + prompt ou schéma | règles de crawl + un prompt |
| Navigation | le planificateur choisit les clics | le planificateur choisit les clics | crawl / sitemap | crawl |
| Validation | Pydantic depuis votre schéma, avant écriture | votre code | schéma d'extraction optionnel | votre code |
| Persistance | SQLite par enregistrement, `--resume` | en mémoire / votre code | API ou votre BD | votre code |
| Où il s'exécute | votre machine | votre machine | hébergé ou auto-hébergé | votre machine |

Si vous connaissez déjà l'URL et avez seulement besoin de markdown en sortie, Firecrawl ou Crawl4AI sont plus simples. Si vous avez besoin d'un agent généraliste d'utilisation d'ordinateur et validez plus tard, Browser Use est plus adapté. Si le résultat doit être composé de lignes correspondant à un schéma et que l'agent doit les trouver, c'est le rôle de Verboisy.

## Exemple rapide

Le schéma utilise JSON Schema. Pour une liste d'enregistrements, le niveau supérieur est un `"array"` dont les `"items"` définissent la structure de l'objet d'une ligne :

```json
{
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "name": { "type": "string" },
      "website": { "type": "string" },
      "description": { "type": "string" },
      "batch": { "type": "string" }
    },
    "required": ["name", "website"]
  }
}
```

Verboisy génère un modèle Pydantic à partir de ce schéma à l'exécution et rejette les lignes non conformes avant qu'elles n'atteignent SQLite.

CLI :

```bash
verboisy run \
  --goal "Find AI startups from the Y Combinator Fall 2026 (F26) batch" \
  --schema examples/yc_startups/schema.json \
  --export result.json
```

Même exécution en Python :

```python
from verboisy import run

result = run(
    goal="Find AI startups from the Y Combinator Fall 2026 (F26) batch",
    schema="examples/yc_startups/schema.json",
    export="result.json",
)

print(result.run_id, len(result.records))
for row in result.records:
    print(row["name"], row["website"])
```

Chacune de ces deux méthodes produit :

```json
[
  {
    "name": "Marrow",
    "website": "[https://marrow.example.com](https://marrow.example.com)",
    "description": "Environnements de staging pour agents IA en production.",
    "batch": "F26"
  },
  {
    "name": "Kiln Trace",
    "website": "[https://kilntrace.example.com](https://kilntrace.example.com)",
    "description": "Débogage de latence et de coût pour les workflows d'agents.",
    "batch": "F26"
  }
]
```

*(Résultat illustratif : les résultats réels dépendent de ce qui est en ligne au moment de l'exécution. Les noms d'exemple utilisent `.example.com` à dessein.)*

Si le processus s'interrompt au milieu du traitement, reprenez-le sans réexécuter les lignes déjà enregistrées :

```bash
verboisy run --resume
```

```python
result = run(resume=True)
```

## Cas d'usage

Verboisy est conçu pour des schémas de recherche qui méritent d'être exécutés plus d'une fois :

- **Veille concurrentielle et marché :** suivez les prix des concurrents, les pages produits et les annonces de manière programmée plutôt que manuellement.
- **Prospection B2B :** transformez une liste de noms d'entreprises en données structurées de firmographie et de stack technique, prêtes à être importées dans votre CRM.
- **Suivi e-commerce et retail :** observez les modifications de catalogue et de prix sur des boutiques en ligne riches en JavaScript.
- **Operations de recherche (ResOps) :** exécutez le même modèle de requête sur des centaines d'entités de façon récurrente.
- **Alimentation de RAG / base de connaissances :** alimentez un pipeline de recherche avec des enregistrements structurés et sourcés au lieu de contexte rassemblé manuellement.

Chacun de ces cas s'appuie sur le même principe d'objectif associé à un schéma que l'exemple rapide ci-dessus, appliqué à un site et à un format différents.

## Comment ça marche

Verboisy exécute une boucle principale **planifier → agir → observer → extraire** jusqu'à ce que le planificateur décide qu'il dispose de suffisamment de données ou atteigne la limite d'étapes.

```mermaid
flowchart LR
    F[run --resume] --> A
    A[Planifier la prochaine action] -->|naviguer ou cliquer| B[Le navigateur exécute]
    A -->|extraire| C[Parser le DOM en JSON]
    B --> D[Nettoyer le DOM pour le LLM]
    D --> A
    C --> E[Enregistrer dans SQLite]
    A -->|terminé| E
```

Chaque enregistrement extrait est validé puis enregistré dans SQLite sous un `run_id`. Si la boucle est interrompue (limite de débit, plantage, processus arrêté), `verboisy run --resume` (ou `run(resume=True)`) recharge l'objectif, le schéma et les lignes déjà sauvegardées pour reprendre. `--resume <id>` cible une exécution spécifique ; `--resume` sans ID prend la dernière exécution incomplète.

Le fichier d'exportation `--export` est généré à la fin de l'exécution (ou de la reprise). Les résultats partiels sont conservés dans `SQLITE_DB_PATH` entre-temps.

Le détail complet de chaque module se trouve dans [`ARCHITECTURE.md`](../../ARCHITECTURE.md).

## Installation

Nécessite Python 3.11+.

Pas encore disponible sur PyPI. Installation à partir des sources :

```bash
git clone [https://github.com/EmanueleTorrisi/verboisy.git](https://github.com/EmanueleTorrisi/verboisy.git)
cd verboisy && pip install -e .
playwright install --with-deps chromium
```

Une fois la première version publiée, la commande sera :

```bash
pip install verboisy
playwright install --with-deps chromium
```

## Configuration

Copiez `.env.example` vers `.env`. Tous les paramètres sont chargés via Pydantic dans `utils/config.py` ; tout paramètre non défini utilisera la valeur par défaut ci-dessous.

```bash
# Requis : au moins un fournisseur de LLM
OPENAI_API_KEY=sk-your-api-key-here
# ANTHROPIC_API_KEY=sk-ant-your-api-key-here

# Routage de modèle LiteLLM (ex. gpt-4o, claude-sonnet-5, ollama/llama3)
LITELLM_MODEL=gpt-4o

SQLITE_DB_PATH=verboisy.db
VERBOISY_LOG_LEVEL=INFO
VERBOISY_HEADLESS=true
```

| Variable | Valeur par défaut | Description |
| --- | --- | --- |
| `OPENAI_API_KEY` | - | Identifiants OpenAI. Requis sauf en cas d'utilisation d'Anthropic ou d'un modèle local. |
| `ANTHROPIC_API_KEY` | - | Identifiants Anthropic, utilisés à la place d'OpenAI. |
| `LITELLM_MODEL` | `gpt-4o` | Toute chaîne de modèle prise en charge par [LiteLLM](https://github.com/BerriAI/litellm). |
| `MAX_TOKENS` | `4096` | Nombre maximal de tokens par appel de planification ou d'extraction. |
| `TEMPERATURE` | `0.0` | Température d'échantillonnage pour le planificateur. |
| `VERBOISY_HEADLESS` | `true` | Exécuter Chromium sans interface graphique. Définissez à `false` pour visualiser le navigateur. |
| `BROWSER_TIMEOUT_MS` | `30000` | Délai d'attente de navigation par page, en ms. |
| `USER_AGENT_ROTATION` | `true` | Alterner le User-Agent entre les requêtes. |
| `SQLITE_DB_PATH` | `verboisy.db` | Emplacement de stockage de l'historique et des enregistrements extraits. |
| `VERBOISY_LOG_LEVEL` | `INFO` | Niveau de journalisation standard Python. `DEBUG` affiche chaque étape du planificateur. |

Vous payez directement le fournisseur de LLM. Les appels de planification et d'extraction sont plafonnés à `MAX_TOKENS` (4096 par défaut) avec une `TEMPERATURE` de 0.0. Un objectif de la taille d'un annuaire nécessite généralement quelques dizaines d'appels, pas des centaines. Il n'y a aucun compteur facturé.

## Utilisation

### CLI

```bash
verboisy run \
  --goal "Find AI startups from the Y Combinator Fall 2026 (F26) batch" \
  --schema examples/yc_startups/schema.json \
  --export result.json
```

La commande affiche un `run_id` (également stocké dans SQLite). Utilisez-le pour reprendre l'exécution plus tard.

| Option | Alias | Requis | Description |
| --- | --- | --- | --- |
| `--goal` | `-g` | Oui, sauf si `--resume` | Description claire en anglais de ce qu'il faut trouver et où. Soyez précis. |
| `--schema` | `-s` | Oui, sauf si `--resume` | Chemin vers un schéma JSON décrivant les champs à extraire. `array` racine contenant des `object`s d'enregistrement. |
| `--export` | `-e` | Non | Chemin de sortie. Prend en charge `.json` et `.csv`. Écrit à la fin de la tâche. |
| `--resume` | `-r` | Non | Reprendre une exécution. `--resume` seul poursuit la dernière tâche incomplète dans `SQLITE_DB_PATH`. `--resume <id>` reprend cette tâche spécifique. L'objectif et le schéma sont chargés depuis la session sauvegardée ; `--export` / le mode headless peuvent être remplacés. |

Exécutez `verboisy run --help` pour afficher la liste complète des options.

### Reprise (Resume)

```bash
# Dernière exécution incomplète dans verboisy.db
verboisy run --resume

# Une exécution spécifique
verboisy run --resume 7f3a2c1b --export result.json
```

Les lignes déjà validées ne sont pas extraites à nouveau. S'il n'y a pas d'exécution incomplète, la commande s'arrête en renvoyant une erreur indiquant la base de données consultée.

### Python

`run()` est l'API publique. La CLI est une fine couche au-dessus de celle-ci.

```python
from pathlib import Path
from verboisy import RunResult, run

result: RunResult = run(
    goal="Find AI startups from the Y Combinator Fall 2026 (F26) batch",
    schema="examples/yc_startups/schema.json",  # chemin str, Path ou dict
    export="result.json",
)

print(result.run_id)
print(result.records[0]["name"])
```

Schéma sous forme de dictionnaire, sans fichier requis :

```python
result = run(
    goal="Find AI startups from the Y Combinator Fall 2026 (F26) batch",
    schema={
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "website": {"type": "string"},
                "description": {"type": "string"},
                "batch": {"type": "string"},
            },
            "required": ["name", "website"],
        },
    },
)
```

Reprise :

```python
from verboisy import run

# Dernière exécution incomplète
result = run(resume=True)

# Exécution spécifique, avec écriture de l'export à la fin
result = run(resume=result.run_id, export="result.json")
```

Signature :

```python
def run(
    *,
    goal: str | None = None,
    schema: str | Path | dict | None = None,
    export: str | Path | None = None,
    resume: bool | str = False,
    headless: bool | None = None,
) -> RunResult: ...
```

Champs de `RunResult` :

| Champ | Type | Signification |
| --- | --- | --- |
| `run_id` | `str` | Identifiant stable enregistré dans SQLite. Transmettez-le à `run(resume=...)`. |
| `records` | `list[dict]` | Ensemble des lignes validées pour cette exécution jusqu'à présent. |
| `export_path` | `Path \| None` | Chemin du fichier exporté, si `--export` / `export=` était spécifié et que le traitement s'est terminé. |
| `db_path` | `Path` | Le fichier SQLite utilisé. |
| `completed` | `bool` | `True` lorsque le planificateur s'est arrêté parce qu'il a terminé, et non à cause d'un plantage. |

Règles :

- Nouvelle exécution : `goal` et `schema` sont requis ; `resume` doit être omis ou défini à `False`.
- Reprise : `resume=True` ou `resume="<id>"` ; `goal` / `schema` sont optionnels et ignorés si l'exécution les possède déjà.
- `headless=None` utilise la valeur de `VERBOISY_HEADLESS`. Passez `True` / `False` pour surcharger la configuration lors de cet appel.

### Observer une exécution

```bash
VERBOISY_HEADLESS=false VERBOISY_LOG_LEVEL=DEBUG \
  verboisy run \
    --goal "Find AI startups from the Y Combinator Fall 2026 (F26) batch" \
    --schema examples/yc_startups/schema.json \
    --export result.json
```

## Docker

```bash
docker compose -f docker/docker-compose.yml up -d --build
docker compose -f docker/docker-compose.yml exec verboisy verboisy run \
  --goal "Find AI startups from the Y Combinator Fall 2026 (F26) batch" \
  --schema examples/yc_startups/schema.json \
  --export result.json
```

Le conteneur démarre et reste actif avec les dépendances de navigateur de Playwright déjà installées, de sorte que les commandes s'exécutent via `exec` plutôt qu'en tant que point d'entrée du conteneur. Montez ou conservez le fichier `SQLITE_DB_PATH` si vous souhaitez que `--resume` fonctionne entre les redémarrages de conteneurs. `OPENAI_API_KEY` est automatiquement transmis depuis votre terminal : exportez-le d'abord. Pour transmettre d'autres variables (`ANTHROPIC_API_KEY`, `LITELLM_MODEL`, etc.), exportez-les également ou remplacez la section `environment:` de `docker/docker-compose.yml` par `env_file: [../.env]`.

## Limitations connues

Logiciel en version bêta, en toute transparence :

- **Pas de compte utilisateur ni d'historique centralisé :** mono-utilisateur. Les identifiants de session sont conservés dans le fichier SQLite local, sans tableau de bord.
- **Pas de planification intégrée :** lancez les exécutions manuellement ou intégrez-les à votre propre cron ou orchestrateur. `--resume` sert à gérer les pannes et les limites de taux, ce n'est pas un planificateur.
- **Pas d'API HTTP hébergée :** la CLI, `verboisy.run()` et l'image Docker constituent les seules interfaces pour l'instant.
- **Inconsistant sur les sites dotés de protections anti-robots agressives :** certaines cibles nécessiteront des tentatives supplémentaires ou une intervention manuelle.

Vous rencontrez une limitation qui bloque votre cas d'usage ? [Ouvrez un ticket (issue)](https://github.com/EmanueleTorrisi/verboisy/issues) : c'est le moyen le plus direct d'influencer le choix des priorités de développement.

## Utilisation responsable

Verboisy pilote un véritable navigateur pour votre compte. Vous êtes responsable du respect des conditions d'utilisation de chaque site ciblé, du fichier `robots.txt`, des limites de requêtes et de la législation en vigueur dans votre juridiction. Ne l'utilisez pas pour contourner des mécanismes d'authentification ou des contrôles d'accès auxquels vous n'avez pas droit.

## Documentation

La documentation complète, y compris la référence de configuration et les détails de l'API, est disponible sur **[emanueletorrisi.github.io/verboisy](https://emanueletorrisi.github.io/verboisy/)**.

## Contribution

Les contributions sont les bienvenues. Consultez [`CONTRIBUTING.md`](../CONTRIBUTING.md) pour la configuration locale et les conventions de code, et veuillez respecter le [Code de conduite](../CODE_OF_CONDUCT.md). Vous cherchez par où commencer ? Parcourez les tickets portant le label [`good first issue`](https://github.com/EmanueleTorrisi/verboisy/labels/good%20first%20issue).

## Sécurité

Vous avez trouvé une vulnérabilité ? Merci de ne pas ouvrir de ticket public : utilisez le [signalement privé de vulnérabilités](https://github.com/EmanueleTorrisi/verboisy/security/advisories/new) ou consultez [`SECURITY.md`](../SECURITY.md).

## Licence

BSD 2-Clause : consultez le fichier [`LICENSE`](../../LICENSE) pour le texte complet.

---

<p align="center">
  Créé par <a href="https://github.com/EmanueleTorrisi">Emanuele Torrisi</a> · <a href="#readme-top">Retour en haut ↑</a>
</p>
