<p align="center">
  <img src="./logo.png" alt="verboisy" width="300" />
</p>
<p align="center">
  <strong align="center">An autonomous web research and structured scrape-to-JSON agent.</strong>
</p>
<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/EmanueleTorrisi/verboisy?style=flat" alt="License"></a>
</p>

<p align="center">
  <strong title="English" aria-label="English">🇬🇧</strong> ·
  <a href=".github/readme/README.it.md" title="Italiano" aria-label="Italiano">🇮🇹</a> ·
  <a href=".github/readme/README.de.md" title="Deutsch" aria-label="Deutsch">🇩🇪</a> ·
  <a href=".github/readme/README.zh-CN.md" title="简体中文" aria-label="简体中文">🇨🇳</a> ·
  <a href=".github/readme/README.fr.md" title="Français" aria-label="Français">🇫🇷</a> ·
  <a href=".github/readme/README.es.md" title="Español" aria-label="Español">🇪🇸</a> ·
  <a href=".github/readme/README.ko.md" title="한국어" aria-label="한국어">🇰🇷</a> ·
  <a href=".github/readme/README.ja.md" title="日本語" aria-label="日本語">🇯🇵</a>
</p>

## How to install:

```bash
pip install verboisy
playwright install --with-deps chromium
```

## How to configure:

Copy .env.example to .env and set your API keys:

-> OPENAI_API_KEY=sk-...

-> LITELLM_MODEL=gpt-4o

## How to use:

Verboisy operates through a simple command-line interface.
You provide it with a plain-english goal and a JSON schema defining the exact data structure you want back.

Here is a complete example command:
```bash
verboisy run \
  --goal "Find the latest AI startups from YCombinator W24" \
  --schema examples/yc_startups/schema.json \
  --export result.json
```

Command Breakdown:

*run*: The main command to start the autonomous agent.

*--goal* (or -g): Tell the agent exactly what to look for and where to go. Be as specific as possible.

*--schema* (or -s): The file path to your custom JSON schema. This file tells Verboisy exactly what data fields to extract (e.g., company name, website, description).

*--export* (or -e): (Optional) The file path where you want to save the final extracted data. It supports .json and .csv formats.

Once you hit enter, Verboisy will spin up a headless browser, autonomously navigate the web, analyze the page DOM, extract the data matching your schema, and save it to your result.json file.


----------------------------------------------------------------------------------------
**Verboisy was written by Emanuele Torrisi and is released under the BSD 2 clause license.**
