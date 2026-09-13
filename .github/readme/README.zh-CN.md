<p align="center">
  <img src="../../logo.png" alt="verboisy" width="300" />
</p>
<p align="center">
  <strong align="center">一个用于网络研究和结构化抓取至 JSON 的自主代理。</strong>
</p>
<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/EmanueleTorrisi/verboisy?style=flat" alt="License"></a>
</p>

<p align="center">
  <a href="../../README.md" title="English" aria-label="English">GB</a> ·
  <a href="README.it.md" title="Italiano" aria-label="Italiano">IT</a> ·
  <a href="README.de.md" title="Deutsch" aria-label="Deutsch">🇩🇪</a> ·
  <strong title="简体中文" aria-label="简体中文">CN</strong> ·
  <a href="README.fr.md" title="Français" aria-label="Français">🇫🇷</a> ·
  <a href="README.es.md" title="Español" aria-label="Español">🇪🇸</a> ·
  <a href="README.hi.md" title="हिन्दी" aria-label="हिन्दी">🇮🇳</a> ·
  <a href="README.ar.md" title="العربية" aria-label="العربية">🇸🇦</a>
</p>

## 如何安装:

```
pip install verboisy
playwright install --with-deps chromium
```

## 如何配置:

将 .env.example 复制为 .env 并设置你的 API 密钥:

-> OPENAI_API_KEY=sk-...

-> LITELLM_MODEL=gpt-4o

## 如何使用:

Verboisy 通过一个简单的命令行界面运行。
你需要为它提供一个纯英语的目标描述，以及一个定义你确切想要返回的数据结构的 JSON schema

下面是一个完整的示例命令:
```
verboisy run \
  --goal "寻找 Y Combinator W24 最新的 AI 初创公司。" \
  --schema examples/yc_startups/schema.json \
  --export result.json
```

命令详解:

*run*: 启动自主代理的主命令。

*--goal* (或 -g): 准确告诉代理要寻找什么以及去哪里寻找。请尽可能具体。

*--schema* (或 -s): 你自定义的 JSON schema 的文件路径。此文件会准确告诉 Verboisy 需要提取哪些数据字段（例如：公司名称、网站、描述）。

*--export* (或 -e):（可选）你希望保存最终提取数据的目标文件路径。支持 .json 和 .csv 格式。

按下回车键后，Verboisy 将启动一个无头（headless）浏览器，自主进行网页导航，分析页面 DOM，提取与你的 schema 匹配的数据，并将其保存到你的 result.json 文件中。


----------------------------------------------------------------------------------------
**Verboisy 由 Emanuele Torrisi 编写，并在 BSD 2-clause 许可证下发布。**
