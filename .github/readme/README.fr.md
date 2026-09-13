<p align="center">
  <img src="../../logo.png" alt="verboisy" width="300" />
</p>
<p align="center">
  <strong align="center">Un agent autonome de recherche web et de scraping structuré vers JSON.</strong>
</p>
<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/EmanueleTorrisi/verboisy?style=flat" alt="License"></a>
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

## Comment installer :

```bash
pip install verboisy
playwright install --with-deps chromium
```

## Comment configurer :

Copiez .env.example vers .env et définissez vos clés API :

-> OPENAI_API_KEY=sk-...

-> LITELLM_MODEL=gpt-4o

## Comment utiliser :

Verboisy fonctionne via une interface en ligne de commande simple.
Vous lui fournissez un objectif en anglais simple et un schéma JSON définissant la structure exacte des données que vous souhaitez obtenir.

Voici un exemple de commande complète :
```bash
verboisy run \
  --goal "Trouvez les dernières startups d’IA de Y Combinator W24" \
  --schema examples/yc_startups/schema.json \
  --export result.json
```

Détail de la commande :

*run*: La commande principale pour démarrer l'agent autonome.

*--goal* (ou -g): Indiquez à l'agent exactement ce qu'il doit chercher et où aller. Soyez aussi précis que possible.

*--schema* (ou -s): Le chemin d'accès vers votre schéma JSON personnalisé. Ce fichier indique exactement à Verboisy quels champs de données extraire (ex. nom de l'entreprise, site web, description).

*--export* (ou -e): (Optionnel) Le chemin du fichier dans lequel vous souhaitez enregistrer les données finales extraites. Il prend en charge les formats .json et .csv.

Une fois que vous appuyez sur Entrée, Verboisy démarrera un navigateur headless, naviguera de manière autonome sur le Web, analysera le DOM de la page, extraira les données correspondant à votre schéma et les enregistrera dans votre fichier result.json.


----------------------------------------------------------------------------------------
**Verboisy a été écrit par Emanuele Torrisi et est publié sous la licence BSD à 2 clauses.**
