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
<p align="center"><strong>調査の問いから、出典を確認できるデータセットへ。</strong></p>
<p align="center">証拠に基づく調査 · 構造化抽出 · ローカルデータ · 持ち運べる来歴</p>


> **リリース状況：** バージョン `1.0.0` は、文書化されたワークフロー、対応環境、検証済みの制限の範囲内で、本番利用に対応しています。[リリースマトリクス](https://github.com/EmanueleTorrisi/verboisy/blob/main/evals/release-matrix.json)には、その根拠となる技術検証、実タスク評価、独立したベータテスト、リリース責任者による承認を記録しています。

## 製品について

Verboisy は、構造化された情報と、その情報がどこから得られたかを確認する手段を必要とする人のための調査・データ抽出エンジンです。問い、スキーマ、許可された情報源で作業を定義します。観測を取得し、提案されたレコードを検証して、根拠と出力変換を保持します。CLI と Python API は、再現可能な処理と保存済み作業の再開に対応します。

ローカルファイルや宣言された HTTP データセットは、モデル・検索・ブラウザーを呼ばない決定論的アダプターでも処理できます。大容量のローカル入力には、バッファーを制限し、ディスク上の台帳を使う独立した処理経路があります。

**ソースは閲覧可能ですが、実行には別途ライセンスが必要です。** [LICENSE](https://github.com/EmanueleTorrisi/verboisy/blob/main/LICENSE) が許可するのはソースの検査です。実行、テスト、変更、配布には別の書面による許可が必要です。以下の例は許可された利用を説明します。

## CLI の実行例

<p align="center">
  <a href="https://asciinema.org/a/kao32h7xRRkFwtkc">
    <img src="../assets/verboisy-demo.gif" alt="Verboisy CLI Demo">
  </a>
</p>

## この設計の意義

JSON や表だけでは、その事実が実際に観測されたのか、値がどのように変換されたのかは分かりません。Verboisy はその確認を処理の一部にします。

- **採用前の証拠検証：** モデルの候補は観測済みの出典と決定論的検証を必要とし、意味的レビューは別の段階です。
- **利用者が決める契約：** JSON Schema、同一性、情報源の範囲、比較可能性が許容する出力を定義します。
- **復旧可能な作業：** 不変の取得データ、チェックポイント、リクエスト記録が進捗と消費量を保存します。
- **説明可能な変換：** 単位、射影、表示、集約は元の値と寄与レコードに結び付きます。
- **明示的な判断：** 問いやスキーマを黙って変更せず、提案を示して処理を停止します。

分析、参照データの収集、データ準備、社内情報の処理、再現可能な調査に役立ちます。科学研究や規制対象の用途では、情報源、標本、結論を独立して評価する必要があります。証拠に基づくデータ抽出の信頼できる標準を目指していますが、現在の市場での地位を主張するものではありません。

### 解釈に価値がある処理で AI を活用

Verboisy は決定論的なコードと意味解釈を担う AI を組み合わせます。構造化ファイルの読み取り、スキーマ検証、観測済みの証拠との照合、エクスポートはコードで実行し、必要な計画や解釈にモデルを使用します。決定論的な処理はモデルのトークンを消費しないため、同じ処理を有料 LLM に任せた場合の推論料金を回避できます。ローカルデータセットの準備は、モデルプロバイダーを使わずに完結できます。

この設計は不要なモデル呼び出しを減らし、支出を確認しやすくします。全体の費用削減幅はタスク、モデル、再試行、レビュー作業によって異なります。公平な比較では、同じ情報源、出力要件、品質基準を用い、失敗した試行も含めて測定します。証拠の検証は裏付けのない出力を減らしますが、意味的な正しさには情報源の品質と内容の確認が必要です。

## 処理経路と形式

Web 調査はブラウザーと設定済みモデルを使い、検索による情報源発見は任意です。決定論的準備は許可されたファイルや宣言済み HTTP GET 情報源を読みます。独立したストリーミング処理は件数、レコードのページ、チェックポイントを返します。

| 入力 | 解釈 |
| --- | --- |
| CSV / TSV | 正確な文字列、明示的なヘッダー、列数の検査 |
| JSON / JSONL | 厳密にデコードする型付きオブジェクト |
| テキスト | 出典位置を持つテキストレコード |
| DOCX / XLSX | 制限が文書化されたアダプター。マクロや数式を実行しません |
| 画像、動画、その他のファイル | 不変のバイト取得、ハッシュ、参照。内容の自動理解は行いません |
| 時系列 | 系列・時刻の明示的な規則、並べ替え、欠落と重複の診断 |

バイナリー取得は OCR やあらゆる文書の解釈を意味しません。OAuth、データベースドライバー、アプリのコネクター、API のページ処理には個別の実装が必要です。[形式](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/formats.md)を参照してください。

## インストールと設定

Python **3.11–3.14** と書面による実行許可が必要です。Poetry は開発用ツールで、インストール後のコマンドは `verboisy` です。リリースマトリクスに記載された OS とインタープリターの構成を使用してください。Web 調査にはプロバイダーの設定、Chromium、システムライブラリーが必要です。ローカル入力にはディレクトリーの許可と空き容量が必要です。C++ コンパイラーは不要です。

許可されたチェックアウトで以下のコマンドを実行してください。pipx が導入済みなら、`pipx install .` によりプロジェクト外でもコマンドを使えます。許可された PyPI 公開後は `pipx install verboisy` を使えます。現時点での PyPI 公開は前提としていません。`python examples/local_quickstart.py` はモデルやブラウザーなしで 2 件の合成レコードを検証します。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
verboisy --help
```

キーは私的な環境または `.env` に保存し、[.env.example](https://github.com/EmanueleTorrisi/verboisy/blob/main/.env.example)を参照してください。キーをコミットしないでください。シェル例は POSIX 構文です。Windows では同等の方法で環境変数を設定します。

```bash
verboisy setup
verboisy model-config
```

`model-config` は設定と資格情報の有無を表示し、キーの値は表示しません。ローカルの決定論的準備にはモデルもブラウザーも不要です。[プロバイダー](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/providers.md)と[検証](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/validation.md)を参照してください。

## Web 調査と API

```bash
verboisy run \
  --goal "研究機関と、明示的に公開されている公式ウェブサイトを探してください" \
  --schema '[名称,ウェブサイト,国]' \
  --export 研究機関.json
```

自動発見には検索プロバイダーが必要です。タスクに開始 URL を明示する方法もあります。JSON Schema で型と制約を定義できます。欠けた情報は `null` のままとなり、裏付けのない値は拒否されます。採用された出力は Web 全体の網羅性を保証しません。

```python
from verboisy import run

結果 = run(
    goal="研究機関と、公開されている公式ウェブサイトを探してください",
    schema=["名称", "ウェブサイト", "国"],
    export="研究機関.json",
)
print(結果.run_id, 結果.status, 結果.records)
```

非同期アプリは `arun` を使います。通常の API は採用レコードをメモリー上にまとめます。大容量のローカル入力にはストリーミング経路を使ってください。

## ローカル・社内データ

```bash
export DATASET_LOCAL_ROOTS='["/srv/verboisy入力"]'
verboisy run \
  --goal "指定されたスキーマに従ってローカルの観測データを準備し、元の値を保持してください" \
  --dataset-file 'jsonl=/srv/verboisy入力/観測データ.jsonl' \
  --schema 観測スキーマ.json \
  --mass-unit source --length-unit source --date-format source \
  --export 観測データ.json
```

ディレクトリーとスキーマファイルはあらかじめ必要です。モデル資格情報はファイルシステムへのアクセス権を与えません。宣言済み HTTP 情報源では、取得量制限、リダイレクト規則、DNS 固定、オリジン別の資格情報を使います。情報源の場所とモデルの実行場所は別です。リモートモデルには観測内容が送られることがあります。機密情報を扱う前に、転送、ログ、ネットワーク、保存方針を確認してください。

## 大容量データセット

```bash
verboisy stream \
  --database 観測ストリーム.db \
  --dataset-file 'jsonl=/srv/verboisy入力/観測データ.jsonl' \
  --schema 観測スキーマ.json \
  --export 観測データ.jsonl
```

台帳は不変の取得ブロックとトランザクション単位の進捗を保存します。`stream-status` でジョブを一覧し、`stream --resume ジョブID` で保存済みジョブを再開できます。`StreamLedger` はページ単位のアクセスを提供します。

Linux/Python 3.12 の JSONL 測定では、**1,000,000 行**、**1,105,888,890 バイト**を準備・出力し、最大 RSS は **89.15 MiB**、経過時間は **130.81 秒**でした。元ファイル削除後の復旧と出力の整合性も確認しました。これは一つの負荷の測定で、一般的な速度や容量の保証ではありません。[ストリーミング](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/streaming.md)と[ベンチマーク](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/benchmarks.md)を参照してください。

## 提案、再開、証拠

```bash
verboisy changes --run-id 実行ID
verboisy status --run-id 実行ID
verboisy run --resume 実行ID
```

`--resume` は現在の要件を維持して提案を辞退します。`--okresume` は保存された変更だけを承認します。提案は型、列、調査範囲を変更できます。再開は消費量をリセットせず、情報源への権限も暗黙に増やしません。

範囲は範囲として保持します。下限を正確な値や架空の上限に変換しません。数値の最小・最大列には適切なスキーマが必要です。表示の既定値はキログラム、メートル、日/月/年で、明示的な代替設定でも元の証拠を保存します。時系列診断は欠けた観測を補間せず、曖昧な現地時刻を推測しません。

持ち運べる出力には、証拠、関連イベント、出力来歴、該当する取得資料が含まれます。集約には寄与レコードを記録します。チェックサムはマニフェストとのバイト整合性を示し、真実性や独立した真正性を証明しません。[来歴](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/proof.md)を参照してください。

## 設計と文書

Python が制御、契約、アダプター、CLI、SQLite 台帳を担当します。任意の C++17 コンポーネントは特定の証拠照合作業を高速化し、Python 参照実装を保持します。テストと CI は各環境、ブラウザー、復旧、整合性を検証し、命令・分岐の完全なカバレッジを要求します。実際の調査品質とプロバイダー互換性は別途評価が必要です。

[CLI](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/cli.md) · [API](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/api.md) · [契約](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/contracts.md) · [同一性](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/smartid.md) · [入力](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/ingestion.md) · [表示](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/presentation.md) · [意味](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/research-semantics.md) · [設計](https://github.com/EmanueleTorrisi/verboisy/blob/main/ARCHITECTURE.md) · [変更履歴](https://github.com/EmanueleTorrisi/verboisy/blob/main/CHANGELOG.md)

## ライセンス、デモ、商談

Verboisy は独自ライセンスのソフトウェアで、**オープンソースではありません**。英語の LICENSE が正式な条件で、この翻訳は権利を変更しません。適用される版は、ソフトウェアに付属する [LICENSE](https://github.com/EmanueleTorrisi/verboisy/blob/main/LICENSE) に記載されています。第三者のコンポーネントにはそれぞれのライセンスが適用されます。実行、テスト、変更、統合、配布、ホスティングには別の書面による許可が必要です。

デモ、評価、社内・企業ライセンス、提携、将来の有償協力については **[emanueletorrisi98@gmail.com](mailto:emanueletorrisi98@gmail.com)** へ連絡してください。用途、情報源、量、実行環境を説明し、資格情報や機密データは送らないでください。料金、サポート、権利は個別に合意します。[ライセンス](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/licensing.md)と[商談](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/commercial.md)を参照してください。

## フィードバックと協力

**Emanuele Torrisi** が Verboisy を制作・保守し、現在は唯一の開発者です。[不具合報告と機能要望](https://github.com/EmanueleTorrisi/verboisy/issues)を歓迎します。脆弱性は[セキュリティ方針](https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/SECURITY.md)に従い非公開で報告してください。

依頼していないコード提供は受け付けません。有償協力には、範囲、報酬、守秘義務、知的財産権について事前の合意が必要です。版ごとの変更は[変更履歴](https://github.com/EmanueleTorrisi/verboisy/blob/main/CHANGELOG.md)、0.1.0 から 1.0.0 への構成の変遷は[バージョン履歴](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/development-roadmap.md)に記録しています。[参加方針](https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/CONTRIBUTING.md)と[著作権](https://github.com/EmanueleTorrisi/verboisy/blob/main/COPYRIGHT.md)も参照してください。
## 実践的なワークフロー

[研究機関のカタログ](https://github.com/EmanueleTorrisi/verboisy/blob/main/examples/research_catalog/README.md) ·
[大規模なローカル観測データの処理](https://github.com/EmanueleTorrisi/verboisy/blob/main/examples/streaming_observations/README.md) ·
[バージョン履歴：0.1.0–1.0.0](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/development-roadmap.md)


## データ契約と検証範囲

通常の出力では `id` は生成メタデータ用です。元データの ID は明示的に `source_id` に投影してください。入れ子の ID とストリーミングの ID は保持されます。欠落した任意項目は欠落のままで、明示的な null は保持されます。ストリーミングは各行を検証し、未対応の配列全体の制約を拒否します。一時停止した準備処理の終了コードは 2 です。過去の計測結果は、各レポートに記載されたソースコードと実行環境に適用されます。

[過去の検証結果](https://github.com/EmanueleTorrisi/verboisy/blob/main/evals/results/offline-validation.json) · [リリースの根拠と承認](https://github.com/EmanueleTorrisi/verboisy/blob/main/evals/release-matrix.json).


## 商用契約を選ぶ理由

このリポジトリーには、**ソースコードの閲覧・検査を目的とする Verboisy の公開版**が含まれています。商用のお客様には、**別途保守される追加機能付きのエディション**を提供します。その追加機能は、このリポジトリーでは配布していません。

[エディション比較](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/commercial.md)では、各エディションの範囲、配備形態、サービスを説明しています。納品される追加機能は、商用版のリリースノートと締結した契約に明記します。公開リポジトリーの更新も継続します。

納品する機能、利用権、サポート、更新の提供範囲、料金、納期は、締結した契約で定めます。

| 目的 | 契約で定める範囲 |
| --- | --- |
| 日常業務で利用する | 合意した利用者と環境に対する書面での実行・社内利用権 |
| 製品に組み込む | 用途に応じた変更・統合・配備・再配布の権利 |
| 導入作業を減らす | 導入支援、スキーマ設計、代表的なデータによる評価 |
| プライベート環境で運用する | 配備の検討と許可されたソースの統合 |
| 保守と支援を計画する | 更新、支援範囲、応答時間を契約で明確化 |

業務フロー、配備要件、受入基準に合わせてエディションとサービスを選択します。提供物と責任範囲は契約で明確にします。

[emanueletorrisi98@gmail.com](mailto:emanueletorrisi98@gmail.com)

[インストール](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/installation.md) · [リリースと評価](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/release.md)
