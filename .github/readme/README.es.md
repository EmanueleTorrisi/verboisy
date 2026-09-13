<p align="center">
  <img src="../../logo.png" alt="verboisy" width="300" />
</p>
<p align="center">
  <strong align="center">Un agente autónomo de investigación web y scraping estructurado a JSON.</strong>
</p>
<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/EmanueleTorrisi/verboisy?style=flat" alt="License"></a>
</p>

<p align="center">
  <a href="../../README.md" title="English" aria-label="English">🇬🇧</a> ·
  <a href="README.it.md" title="Italiano" aria-label="Italiano">🇮🇹</a> ·
  <a href="README.de.md" title="Deutsch" aria-label="Deutsch">🇩🇪</a> ·
  <a href="README.zh-CN.md" title="简体中文" aria-label="简体中文">🇨🇳</a> ·
  <a href="README.fr.md" title="Français" aria-label="Français">🇫🇷</a> ·
  <strong title="Español" aria-label="Español">🇪🇸</strong> ·
  <a href="README.hi.md" title="हिन्दी" aria-label="हिन्दी">🇮🇳</a> ·
  <a href="README.ar.md" title="العربية" aria-label="العربية">🇸🇦</a>
</p>

## Cómo instalar:

```
pip install verboisy
playwright install --with-deps chromium
```

## Cómo configurar:

Copia .env.example a .env y configura tus claves API:

-> OPENAI_API_KEY=sk-...

-> LITELLM_MODEL=gpt-4o

## Cómo utilizar:

Verboisy funciona a través de una sencilla interfaz de línea de comandos.
Le proporcionas un objetivo en inglés sencillo y un esquema JSON que define la estructura exacta de los datos que deseas obtener.

Aquí tienes un ejemplo de comando completo:
```
verboisy run \
  --goal "Encuentra las startups de IA más recientes de Y Combinator W24" \
  --schema examples/yc_startups/schema.json \
  --export result.json
```

Desglose del comando:

*run*: El comando principal para iniciar el agente autónomo.

*--goal* (o -g): Dile al agente exactamente qué buscar y adónde ir. Sé lo más específico posible.

*--schema* (o -s): La ruta del archivo a tu esquema JSON personalizado. Este archivo le dice exactamente a Verboisy qué campos de datos extraer (ej. nombre de la empresa, sitio web, descripción).

*--export* (o -e): (Opcional) La ruta del archivo donde deseas guardar los datos finales extraídos. Soporta los formatos .json y .csv.

Una vez que presiones enter, Verboisy iniciará un navegador headless, navegará de forma autónoma por la web, analizará el DOM de la página, extraerá los datos que coincidan con tu esquema y los guardará en tu archivo result.json.


----------------------------------------------------------------------------------------
**Verboisy fue escrito por Emanuele Torrisi y se publica bajo la licencia BSD de 2 cláusulas.**
