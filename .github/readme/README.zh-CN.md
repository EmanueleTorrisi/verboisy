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
<p align="center"><strong>从研究问题，到能够核查来源的数据集。</strong></p>
<p align="center">基于证据的研究 · 结构化提取 · 本地数据 · 可移植溯源</p>


> **发布状态：** 版本 `1.0.0` 已具备生产使用条件，适用范围为文档所述的工作流、受支持的环境和经过测试的限制。[发布矩阵](https://github.com/EmanueleTorrisi/verboisy/blob/main/evals/release-matrix.json)记录了作为依据的工程检查、真实任务评估、独立 Beta 测试以及发布负责人的批准。

## 产品介绍

Verboisy 是一个研究与数据提取引擎，面向需要结构化信息并希望核查其来源的用户。问题、模式和允许的来源共同定义任务。系统采集观察内容，验证候选记录，保留证据及输出转换过程。CLI 和 Python API 支持可重复的工作流以及已保存任务的恢复。

它也能通过确定性适配器准备本地或声明的 HTTP 数据集，无需调用模型、搜索或浏览器。大型本地文件使用独立流程，通过受限缓冲区和磁盘台账处理。

**源码可供查阅，运行需要单独许可。** [LICENSE](https://github.com/EmanueleTorrisi/verboisy/blob/main/LICENSE) 允许源码审查，不授予运行权。测试、修改和部署需要另行书面授权。以下示例描述的是已获授权的使用方式。

## 查看 CLI 操作演示

[![Verboisy CLI Demo](https://asciinema.org/a/kao32h7xRRkFwtkc.svg)](https://asciinema.org/a/kao32h7xRRkFwtkc).

## 这种设计的意义

JSON 或表格本身不能说明事实是否被观察到，也不能解释数值如何转换。Verboisy 将这些检查纳入数据流程：

- **先验证证据，再接受记录：** 模型候选需要关联已观察的来源并接受确定性验证；语义审查是独立环节。
- **由用户控制的数据约定：** JSON Schema、身份规则、来源范围和可比性要求决定哪些输出可接受。
- **可恢复的工作：** 不可变采集、检查点和请求日志保留进度与消耗。
- **可解释的转换：** 单位、投影、显示和分组仍关联原始值及贡献记录。
- **明确的决策：** 变更建议会暂停任务，而不会悄悄替换问题或模式。

它适用于分析、参考数据收集、数据准备、内部信息流程和可重复调查。科学研究及受监管用途仍需独立检查来源、抽样和结论。长期目标是成为值得信赖的证据型数据提取标准，而不是声称已经具备市场领导地位。

### 将 AI 用于需要理解和判断的环节

Verboisy 将确定性代码与承担语义理解的 AI 结合使用。结构化文件读取、模式验证、与已观察证据的匹配以及导出由代码执行；模型负责工作流中需要的规划与理解。确定性步骤不消耗模型 token，因此可避免将相同操作交给付费 LLM 所产生的推理费用。本地数据集准备可以完全不使用模型服务。

这种设计减少不必要的模型调用，使支出更易核查。整体节省幅度取决于任务、模型、重试次数和审核工作量。公平比较应采用相同的数据源、输出要求和质量标准，并计入失败的尝试。证据检查可减少缺乏支持的输出；语义正确性仍需要可靠的来源和内容审核。

## 工作流与格式

网页研究使用浏览器及已配置模型，搜索发现来源为可选功能。确定性准备读取获准文件或声明的 HTTP GET 来源。独立流式流程返回计数、记录分页和检查点。

| 输入 | 解释方式 |
| --- | --- |
| CSV / TSV | 保留精确文本，使用明确表头并检查行宽 |
| JSON / JSONL | 严格解码的带类型对象 |
| 文本 | 带来源位置的文本记录 |
| DOCX / XLSX | 具有明确限制的适配器，不执行宏或公式 |
| 图片、视频及其他文件 | 不可变字节采集、哈希及引用，不自动理解内容 |
| 时间序列 | 明确的序列与时间戳策略、排序、缺口和重复诊断 |

二进制采集不等同于 OCR 或通用文档理解。OAuth、数据库驱动、应用连接器和 API 分页需要专门集成。请参阅[格式能力](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/formats.md)。

## 安装与配置

需要 Python **3.11–3.14** 和书面运行许可。Poetry 是开发工具，安装后的命令是 `verboisy`。请使用发布矩阵列明的操作系统和解释器配置。网页研究需要配置提供商、Chromium 和系统库。本地输入需要目录授权及磁盘空间，无需 C++ 编译器。

请在已获授权的源码目录中执行以下命令。安装 pipx 后，可用 `pipx install .` 在项目目录之外使用该命令。经授权发布到 PyPI 后，可用 `pipx install verboisy`。这里不假定软件已在 PyPI 发布。`python examples/local_quickstart.py` 无需模型或浏览器即可核验两条合成记录。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
verboisy --help
```

请按照 [.env.example](https://github.com/EmanueleTorrisi/verboisy/blob/main/.env.example) 将密钥放在私有环境或 `.env` 中，不要提交真实密钥。Shell 示例采用 POSIX 语法；Windows 请使用等效方法设置环境变量。

```bash
verboisy setup
verboisy model-config
```

`model-config` 显示设置和凭据是否存在，不显示密钥值。确定性的本地准备无需模型或浏览器。请参阅[提供商](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/providers.md)和[验证](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/validation.md)。

## 网页研究与 API

```bash
verboisy run \
  --goal "查找研究机构及其明确公开的官方网站" \
  --schema '[名称,网站,国家]' \
  --export 研究机构.json
```

自动发现需要搜索提供商，也可在任务中声明起始 URL。JSON Schema 可精确定义类型与约束。缺失信息可能保持为 `null`；无证据支持的值会被拒绝。接受输出不代表已穷尽整个网页范围。

```python
from verboisy import run

结果 = run(
    goal="查找研究机构及其公开的官方网站",
    schema=["名称", "网站", "国家"],
    export="研究机构.json",
)
print(结果.run_id, 结果.status, 结果.records)
```

异步应用使用 `arun`。普通 API 会将接受的记录物化到内存；大型本地输入应使用流式流程。

## 本地与内部数据

```bash
export DATASET_LOCAL_ROOTS='["/srv/verboisy输入"]'
verboisy run \
  --goal "按照提供的模式准备本地观测数据并保留原始值" \
  --dataset-file 'jsonl=/srv/verboisy输入/观测数据.jsonl' \
  --schema 观测模式.json \
  --mass-unit source --length-unit source --date-format source \
  --export 观测数据.json
```

目录和模式文件必须存在。模型凭据不会授予文件系统权限。声明的 HTTP 来源采用受限下载、重定向策略、DNS 固定以及按来源绑定的凭据。来源位置与模型运行位置是独立选择：远程模型可能接收观察内容。处理机密数据前应检查传输、日志、网络和保留策略。

## 大型数据集

```bash
verboisy stream \
  --database 观测流.db \
  --dataset-file 'jsonl=/srv/verboisy输入/观测数据.jsonl' \
  --schema 观测模式.json \
  --export 观测数据.jsonl
```

流式台账保存不可变来源块及事务提交的进度。`stream-status` 列出任务，`stream --resume 任务ID` 恢复已保存任务。`StreamLedger` 提供分页读取。

在 Linux/Python 3.12 的 JSONL 测量中，处理并导出了 **1,000,000 行**、**1,105,888,890 字节**，峰值 RSS 为 **89.15 MiB**，耗时 **130.81 秒**。删除原始来源后的恢复和导出完整性也经过验证。这是一项特定负载的测量，不是普遍速度或内存保证。请参阅[流式处理](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/streaming.md)和[基准测试](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/benchmarks.md)。

## 建议、恢复与证据

```bash
verboisy changes --run-id 运行ID
verboisy status --run-id 运行ID
verboisy run --resume 运行ID
```

`--resume` 保留原要求并拒绝建议；`--okresume` 只接受已保存的确切变更。建议可改变类型、列或搜索范围。恢复不会重置消耗，也不会隐式扩大来源权限。

区间仍是区间：下界不会变成精确值或虚构上界。数值型 min/max 列需要适合的模式。默认显示单位为千克、米，日期为日/月/年；明确的替代设置仍保留原始证据。时间序列诊断不会插补缺失观察，也不会猜测有歧义的本地时间。

可移植导出包含证据、相关事件、输出溯源及适用的已采集材料。分组标明贡献记录。校验和证明与清单的字节一致性，不证明事实正确或独立真实性。请参阅[溯源](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/proof.md)。

## 架构与文档

Python 负责流程编排、数据约定、适配器、CLI 和 SQLite 台账。可选 C++17 组件加速特定证据匹配，同时保留 Python 参考实现。测试和 CI 覆盖平台、浏览器、恢复与完整性，要求完整语句及分支覆盖。真实研究质量和提供商兼容性需要独立评估。

[CLI](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/cli.md) · [API](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/api.md) · [数据约定](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/contracts.md) · [身份](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/smartid.md) · [摄取](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/ingestion.md) · [显示](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/presentation.md) · [语义](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/research-semantics.md) · [架构](https://github.com/EmanueleTorrisi/verboisy/blob/main/ARCHITECTURE.md) · [版本记录](https://github.com/EmanueleTorrisi/verboisy/blob/main/CHANGELOG.md)

## 许可、演示与商业联系

Verboisy 是专有软件，**不是开源项目**。英文 LICENSE 是正式条款，本译文不改变权限。适用版本以软件随附的 [LICENSE](https://github.com/EmanueleTorrisi/verboisy/blob/main/LICENSE) 为准。第三方组件保留各自许可证。运行、测试、修改、集成、分发和托管需要单独书面许可。

如需演示、评估、内部或企业许可、合作及潜在有偿工程协作，请联系 **[emanueletorrisi98@gmail.com](mailto:emanueletorrisi98@gmail.com)**。说明工作流、来源、规模和环境，不要发送凭据或机密数据。价格、支持和权利逐项商定。请参阅[许可](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/licensing.md)和[商业联系](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/commercial.md)。

## 反馈与合作

**Emanuele Torrisi** 创建并维护 Verboisy，目前是项目唯一开发者。欢迎通过 [GitHub Issues](https://github.com/EmanueleTorrisi/verboisy/issues) 提交缺陷和功能请求。漏洞请按照[安全政策](https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/SECURITY.md)私下报告。

目前不接受未经邀请的代码贡献。有偿合作需事先约定范围、报酬、保密和知识产权。版本变化记录在[更新日志](https://github.com/EmanueleTorrisi/verboisy/blob/main/CHANGELOG.md)中；[版本历史](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/development-roadmap.md)说明从 0.1.0 到 1.0.0 的架构演进。请参阅[参与政策](https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/CONTRIBUTING.md)和[版权](https://github.com/EmanueleTorrisi/verboisy/blob/main/COPYRIGHT.md)。

## 应用工作流示例

[研究机构目录](https://github.com/EmanueleTorrisi/verboisy/blob/main/examples/research_catalog/README.md) ·
[大型本地观测数据处理流程](https://github.com/EmanueleTorrisi/verboisy/blob/main/examples/streaming_observations/README.md) ·
[版本历史：0.1.0–1.0.0](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/development-roadmap.md)


## 数据契约与验证范围

普通输出中的 `id` 保留给生成的元数据。源 ID 必须显式映射为 `source_id`；嵌套 ID 和流式源 ID 仍可使用。缺失的可选字段保持缺失，显式 null 保留。流式处理逐行验证，并拒绝不支持的数组整体约束。暂停的准备任务返回退出码 2。历史测量结果适用于相应报告所记录的源代码和运行环境。

[历史验证结果](https://github.com/EmanueleTorrisi/verboisy/blob/main/evals/results/offline-validation.json) · [发布依据与批准记录](https://github.com/EmanueleTorrisi/verboisy/blob/main/evals/release-matrix.json).


## 为什么选择商业协议？

此仓库包含 **Verboisy 的公开源代码审阅版**。商业客户获得的是**单独维护、具备额外功能的版本**；这些额外功能不在此仓库中分发。

[版本对比](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/commercial.md)说明各版本的范围、部署方式及服务。具体交付的额外功能由商业版发布说明及签署的协议列明。公开仓库将持续更新。

交付功能、使用权、支持服务、更新权益、费用及交付日期均以签署的协议为准。

| 目标 | 需要约定的范围 |
| --- | --- |
| 用于日常工作 | 针对约定用户和环境的书面运行及内部使用权 |
| 集成到产品 | 适用的修改、集成、部署或再分发权利 |
| 减少初期工作 | 入门指导、模式设计和代表性数据评估 |
| 在私有基础设施运行 | 部署评估和已授权数据源的集成 |
| 规划维护和支持 | 合同明确的更新、支持范围及响应时间 |

根据实际工作流、部署要求和验收标准选择版本与服务。协议明确交付内容及各方责任。

[emanueletorrisi98@gmail.com](mailto:emanueletorrisi98@gmail.com)

[安装](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/installation.md) · [发布与评估](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/release.md)
