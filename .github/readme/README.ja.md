<p align="center">
  <img src="../../logo.png" alt="verboisy" width="300" />
</p>
<p align="center">
  <strong align="center">自律型ウェブリサーチおよび構造化データ（Scrape-to-JSON）抽出エージェント。</strong>
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
  <a href="README.es.md" title="Español" aria-label="Español">🇪🇸</a> ·
  <a href="README.ko.md" title="한국어" aria-label="한국어">🇰🇷</a> ·
  <strong title="日本語" aria-label="日本語">🇯🇵</strong>
</p>

## インストール方法:

```bash
pip install verboisy
playwright install --with-deps chromium
```

## 設定方法:

.env.example を .env にコピーして、APIキーを設定します:

-> OPENAI_API_KEY=sk-...

-> LITELLM_MODEL=gpt-4o

## 使用方法:

Verboisy はシンプルなコマンドラインインターフェースを介して動作します。
平易な英語での目的（goal）と、取得したい正確なデータ構造を定義した JSON スキーマを指定するだけです。

完全なコマンドの例は以下の通りです:
```bash
verboisy run \
  --goal "Y Combinator W24の最新のAIスタートアップを探してください" \
  --schema examples/yc_startups/schema.json \
  --export result.json
```

コマンドの解説:

*run*: 自律型エージェントを起動するためのメインコマンド。

*--goal* (または -g): エージェントに何を検索し、どこへ行くべきかを正確に指示します。できるだけ具体的に指定してください。

*--schema* (または -s): カスタム JSON スキーマのファイルパス。このファイルは Verboisy に対して、どのデータフィールド（例: 会社名、ウェブサイト、説明）を抽出するかを正確に指示します。

*--export* (または -e): (オプション) 抽出した最終データを保存するファイルパス。.json および .csv 形式に対応しています。

Enter キーを押すと、Verboisy はヘッドレスブラウザを起動し、自律的にウェブをナビゲートしてページの DOM を解析し、スキーマに一致するデータを抽出して result.json ファイルに保存します。


----------------------------------------------------------------------------------------
**Verboisy は Emanuele Torrisi によって開発され、BSD 2条項ライセンスの 下で公開されています。**
