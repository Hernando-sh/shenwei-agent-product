# 仓库导览 · 每个文件夹、每个文件是干嘛的

> 对象：第一次打开 `shenwei-agent-product` 的人。目标：读完能说出"这个文件为什么在这里、谁调用它、改它会影响谁"。
> 基线：tag `w1.8`（W1 第 8 节，`get_shipment` 与 Release 还没进来）。

---

## 0. 先建立一张地图

这个仓库是深维 S6 课程「深维工作台 · 你的跨境数字员工」的参考实现，十二周按周推进。W1 只做一件事：

```
业务员一句话 ──▶ CLI ──▶ AgentLoop ──▶ 模型 / 工具 / 上下文 ──▶ 两个 ERP 只读工具 ──▶ 事件日志
```

所以仓库里的东西分四堆：

| 堆 | 在哪 | 干什么 |
|---|---|---|
| 规则与规格 | 根目录的 `README.md`、`AGENTS.md`、`CLAUDE.md`，以及 `docs/` | 给人和给 AI coding 工具读的"怎么跑、怎么改、要做成什么样" |
| 代码 | `apps/agent-python/src/agent_app/` | W1 真正跑起来的 Python 执行服务 |
| 证据 | `apps/agent-python/tests/`、`evals/`、`scripts/`、`runs/` | 证明代码按规格工作：单测、fixture、人工判定量表、录制脚本、运行日志 |
| 占位 | `apps/platform-java/`、`apps/web/`、`config/` | 后面几周才填的位置，现在只有 README 或空目录 |

---

## 1. 目录树（带一句话注释）

```
shenwei-agent-product/
├── README.md                     给人读：项目是什么、怎么起步、本周 tag 表
├── AGENTS.md                     给 AI coding 工具读：环境、流程、边界、Git、禁止、交付
├── CLAUDE.md                     一行：规则在 AGENTS.md，不另写一份
├── Makefile                      在根目录统一起 ERP、装依赖、跑测试、跑 agent
├── .env.example                  环境变量模板（复制为 .env）
├── .env                          本机真实配置，含 API Key，已被 .gitignore 忽略
├── .gitignore                    忽略 .env、runs/、缓存、虚拟环境
├── .github/workflows/ci.yml      CI：单测 + 密钥扫描
├── docs/                         规格、架构、需求、威胁、ADR、周计划
│   ├── architecture.md
│   ├── requirements.md
│   ├── threat-model.md
│   ├── repo-guide.md             ← 本文
│   ├── adr/ADR-001-control-mode.md
│   ├── specs/{product,w01-agent-loop,w01-order,w01-shipment}.md
│   └── weeks/w01/{README,test-plan}.md
├── evals/graders/w01-manual-rubric.md   真实模型冒烟的人工判定量表
├── scripts/
│   ├── record_fixtures.py        从模拟 ERP 录 tests/fixtures/erp/*.json
│   └── record_model_samples.py   从真实模型录 tests/fixtures/model/*.json
├── config/                       空目录（后续周的配置位）
└── apps/
    ├── agent-python/             ★ W1 全部代码在这里
    │   ├── AGENTS.md             子目录规则：包结构、加工具的方法、单测不联网
    │   ├── pyproject.toml        包定义、依赖（httpx）、agent-cli 入口、pytest 配置
    │   ├── uv.lock               依赖锁文件
    │   ├── .python-version       3.12
    │   ├── src/agent_app/        源码包（下文逐文件讲）
    │   ├── tests/                单测、集成测试、fixture
    │   ├── runs/                 CLI 跑出来的会话事件与历史（不入库）
    │   └── .pytest_cache/        pytest 缓存（不入库）
    ├── platform-java/README.md   W5 起搬入 Spring Boot 平台层的位置
    └── web/README.md             W5 起接入前端成品的位置
```

---

## 2. 根目录文件

### `README.md`
给人读的入口。讲三件事：项目定位（课程参考实现、tag 规则 `wN` / `wN.k`）、起步命令（`cp .env.example .env` → `uv sync` → `uv run pytest tests/unit -q` → `uv run agent-cli --help`）、本周每个小 tag 对应的内容表。它刻意不讲"怎么改代码"，那是 `AGENTS.md` 的事。

### `AGENTS.md`
给 AI coding 工具（Claude Code、Cursor 等）读的团队规则，每条后面标了来源。六个小节：

- **环境**：Python 3.12 + uv，不用 pip；单测离线，集成测试需要 ERP 9100，不可达自动跳过。
- **开发流程**：从 Issue 和周 spec 出发；总 spec 不在任务里改，要改先写 ADR；确定性行为先写测试，概率能力（模型选不选对工具）走 `evals/`。
- **任务边界**：只改任务允许的目录；改 `contracts/` 要列生产者、消费者、兼容策略；不删测试、不弱化断言。
- **Git 操作**：一任务一分支；不 push、不打 tag、不 merge，除非明确授权。
- **禁止**：密钥、`.env`、`runs/` 不进提交；API Key 不写进事件和日志。
- **交付**：PR 四行格式；报告真实跑过的测试。

文件开头有一句很重要的话：它不是权限设施，真正拦住的是保护分支、CI、审查人与凭据权限。

### `CLAUDE.md`
一行字，把 Claude Code 的默认入口重定向到 `AGENTS.md`，避免两份规则互相漂移。

### `Makefile`
让所有命令都能在仓库根目录执行，不用 cd 到 `apps/agent-python` 或课程环境目录。`make help` 列出全部目标。关键几个：`make erp` / `make erp-stop` 用 `docker compose` 起停课程环境 `../../环境` 里的模拟 ERP 容器，`make erp-tables` / `make erp-sql SQL="…"` 只读查容器里的 `erp.db`（镜像没有 sqlite3 命令，借它自带的 python 查）；`make sync` / `make test` / `make integration` 对应装依赖和两类测试；`make chat TEXT="…"`、`make chat-offline`、`make replay ID=…` 对应 CLI 的两个子命令；`make fixtures` / `make model-samples` 对应两个录制脚本。课程环境不在默认位置时用 `ENV_DIR=` 覆盖。

### `.env.example` 与 `.env`
`.env.example` 是模板，列出六个变量：

| 变量 | 作用 | 谁读 |
|---|---|---|
| `DASHSCOPE_API_KEY` | 阿里百炼 API Key | `config.py` → `DashScopeClient` |
| `AGENT_MODEL` | 模型名，默认 `qwen-plus` | 同上 |
| `AGENT_MODEL_BASE_URL` | 百炼 OpenAI 兼容接口地址 | 同上 |
| `ERP_BASE_URL` | 模拟 ERP 地址，默认 `http://localhost:9100` | `ErpClient` |
| `ERP_API_KEY` | 模拟 ERP 的租户 key（华东 `east-demo-key`），课程环境自带，不是秘密 | `ErpClient` |
| `AGENT_RUNS_DIR` | 事件与历史落盘目录，默认 `runs` | `ConversationStore`、`JsonlSink` |

`.env` 是复制后填了真值的本机文件，被 `.gitignore` 忽略。`config.py` 会从当前目录向上找它。

> ⚠️ 当前工作区里 `.env.example` 的 `DASHSCOPE_API_KEY` 一行被填入了一个形如 `sk-ws-…` 的真实 Key，且 `git status` 显示该文件已被修改。`.env.example` 是入库文件，而 CI 的密钥扫描恰好排除了它（`':!.env.example'`），所以这个 Key 会被静默提交。按 `AGENTS.md`「发现已提交的 Key 先报告」的规则，这里先报告：应把该行恢复为占位符，并到百炼控制台轮换这把 Key。

### `.gitignore`
忽略 `.env`、`runs/`、`__pycache__`、`.pytest_cache/`、`.venv/`、`.DS_Store`、`*.egg-info/`。对应 `AGENTS.md` 禁止项里"密钥、运行日志不进提交"。

### `.github/workflows/ci.yml`
两个 job，在 PR 和 `main` / `week/**` 分支 push 时跑：

- **unit**：`setup-uv` → 装 Python 3.12 → `uv sync` → `uv run pytest tests/unit -q`。只跑单测，因为单测离线。
- **secrets**：`git grep` 搜形如 `sk-` 开头 16 位以上的串，排除 `*.md` 和 `.env.example`，命中就失败。

---

## 3. `docs/` 规格与设计文档

追溯链是单向的：**总 spec 条目 → 周 spec → 测试 → tag**。读文档时顺着这条链走。

### `docs/specs/product.md` 总 spec（PRD 工程版，v1.0）
整个十二周的"要做成什么"。只能通过 ADR 修改。八节：

1. 范围与非目标：一个对话、一个 agent；不做客服机器人、审批流、真接企业系统、多 agent。
2. 三个口径：读自由写过闸 / SCRM 只有四个对象 / 价格只由 ERP 算。附三条从 W1 起成立的不变式 **I1**（模型看到的每条上下文都在事件日志里）、**I2**（工具调用先落日志再执行）、**I3**（报价工具没有自由金额参数）。
3. 五层与八个插件。
4. 用户故事 US-01 到 US-17，每条带"怎么算做对"和落在哪周。W1 承担 US-01。
5. 产品级验收 AC-01 到 AC-24。W1 承担 AC-01：事件日志能复原每一步请求，`--resume` 不丢轮次。
6. 七个质量指标与交付门槛（重复副作用必须为 0，错误动作率 ≤ 2%）。
7. 终态与 Run 状态。W1 只实现 running / completed / failed / stopped，并明确 completed 不等于业务正确。
8. 案例集规模。

### `docs/specs/w01-agent-loop.md` 周 spec（W1-QUERY，已冻结）
本周主线"查一下 X200 的规格和当前库存交期"的工程规格。核心是两张表：

- **任务分解表**：每一步谁负责（模型 / 宿主）、产出什么、异常分支怎么走（型号缺失 → 追问；未知工具 → 拒绝回注；404 → 业务无数据；超时 → timeout 不是零）。
- **周级验收 W1-AC-01 到 07**：每条写了验证方式（哪个测试 T 编号）、设计位置（哪个组件）、证据是什么。这张表是测试文件和代码的直接依据。

还有非功能数字（max_steps 6、模型超时 60 s、工具超时 5 s、墙钟 120 s），开放问题（重试几次），Release 条件（T01–T15 全绿、冒烟六条、故障卡、README 能跑、tag w1）。

### `docs/specs/w01-order.md` 与 `docs/specs/w01-shipment.md`
两个小任务书，各十几行。`w01-shipment.md` 是周内新增工具 `get_shipment` 的规格（输入、输出、失败分类），并写明设计检验：Loop 里不应出现 `if name == "get_shipment"`。`w01-order.md` 是学员独立变体 `get_order`，特别指出订单 `note` 字段可能藏指令，它是数据不是命令。这两份对应的代码在 w1.8 还没有（`ErpGateway` 和 `FakeERP` 已预留了 `get_shipment` / `get_order` 方法，但 `tools/` 下还没有文件）。

### `docs/architecture.md`
W1 的架构图与**职责边界表**。每个组件两列：负责什么、不负责什么。例如 ModelClient 负责请求响应适配，不负责决定业务动作是否获准；AgentLoop 负责推进执行和配对结果，不负责知道型号价格。末尾定义四个对象：Conversation（一段历史，可含多个 Run）、Run（一次输入的执行）、Step（一次模型请求及响应）、Event（追加的执行记录）。

### `docs/requirements.md`
周 spec 之外的横向非功能要求：预算、证据、密钥、评测、观测、CI，每条标"从哪周起"。

### `docs/threat-model.md`
威胁清单。W1 只标位置，W10 填满。五条：密钥泄露、工具参数不可信、订单备注注入、未注册工具、无限循环。每条写了 W1 在哪个组件做了什么最小防护。

### `docs/adr/ADR-001-control-mode.md`
第一条架构决策记录：主案例为什么用动态 Loop 而不是固定流程。给了四种输入下两种做法的对比，说明选 Loop 的理由（后续周请求形态多变）、代价（不确定性、每轮一次模型成本、需要预算与证据设施）、以及什么情况会回到固定流程。`AGENTS.md` 规定改总 spec 必须先写这种 ADR。

### `docs/weeks/w01/test-plan.md`
W1 测试计划：T01 到 T15 十五个行为覆盖点，每条列关键断言、对应的 W1-AC、在哪一节变绿、测试文件位置。这张表是 `tests/unit/` 里每个文件开头 docstring 中 T 编号的出处。

### `docs/weeks/w01/README.md`
一行占位：本周合并前的本地 review 记录与证据放这里。

---

## 4. `apps/agent-python/` 代码

### 4.1 包级文件

- **`AGENTS.md`**：子目录规则，覆盖根规则同名条款。规定了包内七个子目录的分工，以及**加新工具只许改 `tools/<name>.py`、注册、schema、测试、文档，不得在 `agent/loop.py` 里按工具名分支**。还规定 fixture 不手写，必须用脚本从 ERP 录。
- **`pyproject.toml`**：包名 `agent-app`，运行依赖只有 `httpx`；dev 组 `pytest`；`[project.scripts]` 把 `agent-cli` 指到 `agent_app.cli:main`；hatchling 打包 `src/agent_app`。
- **`uv.lock`**：uv 的锁文件，和 `pyproject.toml` 一起是依赖改动的唯一入口。
- **`.python-version`**：`3.12`，uv 据此选解释器。

### 4.2 `src/agent_app/` 源码

#### 4.2.0 先看结构

```
src/agent_app/
├── __init__.py              包版本号
├── config.py                读 .env，唯一碰密钥的地方
├── pricing.py               费用估算：按输入 / 输出 token 分别计价
├── cli.py                   命令行入口：chat / replay
├── contracts/               ① 共享契约：数据类型 + 四个 Protocol（最底层）
│   ├── __init__.py
│   ├── types.py
│   └── protocols.py
├── guardrails/              ② 参数校验：模型给的参数进业务函数前先拦
│   ├── __init__.py
│   └── args.py
├── observability/           ③ 事件：追加写的执行事实
│   ├── __init__.py
│   └── events.py
├── llm/                     ④ 模型适配：百炼 OpenAI 兼容接口
│   ├── __init__.py
│   └── dashscope_client.py
├── tools/                   ⑤ 工具层：ERP 客户端 + 每个工具一文件 + 注册与执行
│   ├── __init__.py
│   ├── erp_client.py
│   ├── product.py
│   ├── availability.py
│   └── registry.py
├── doubles/                 ⑥ 测试替身：假模型、假 ERP
│   ├── __init__.py
│   ├── scripted_model.py
│   └── fake_erp.py
└── agent/                   ⑦ 循环本体：上下文、Loop、会话、回放
    ├── __init__.py
    ├── context.py
    ├── loop.py
    ├── conversation.py
    └── replay.py
```

依赖只能从上往下指，编号小的不知道编号大的存在：

```
cli ──▶ agent ──▶ tools ──▶ guardrails ──▶ contracts
  │        │         │
  │        ├──▶ llm ─┼────────────────────▶ contracts
  │        └──▶ observability ────────────▶ contracts
  └──▶ doubles ───────────────────────────▶ contracts
  └──▶ config
```

一句话记法：`contracts` 定义"长什么样"，`guardrails` / `observability` / `llm` / `tools` / `doubles` 各自实现一块，`agent` 把它们串成循环，`cli` 负责装配和输入输出。

---

#### 4.2.1 `contracts/` 共享契约

**文件夹作用**：全仓库共用的数据类型和接口定义。它是最底层，谁都依赖它，它不依赖任何人。`AGENTS.md` 规定改这里要列出生产者、消费者和兼容策略，因为一处改动会波及所有层。

##### `contracts/types.py`
- **一句话**：W1 用到的全部数据结构，十一个 dataclass 和枚举。
- **里面有什么**：

  | 类型 | 是什么 | 关键点 |
  |---|---|---|
  | `ResponseKind` | 模型响应三种形态 | `final` 最终文本 / `tool_calls` 工具请求 / `malformed` 空响应，第三种是协议失败不是完成 |
  | `StopReason` | 为什么停 | completed / max_steps / wall_clock / protocol_error / model_error |
  | `RunStatus` | 一次 Run 的状态 | running / completed / stopped / failed；completed 只表示循环正常结束，不证明答案对 |
  | `ToolSpec` | 给模型看的工具说明 | name、description、JSON Schema；`to_openai()` 转成接口格式 |
  | `ToolCall` | 模型发起的一次工具请求 | `arguments` 保留原始字符串，解析校验是宿主的事 |
  | `ToolError` | 失败分类 | `category` 给程序分支用，`code` 是上游机器码，`message` 给人看 |
  | `ToolResult` | 带同一 `call_id` 回去的结果 | `ok=False` 时没有 data 只有 error；`to_message()` 变成 role=tool 的消息 |
  | `Usage` | token 用量 | `total_tokens is None` 即 unknown，不当零 |
  | `ModelResponse` | 归一化后的模型响应 | `raw` 留原始 JSON 进事件；`to_assistant_message()` 还原成 assistant 消息 |
  | `Budget` | 预算 | max_steps 6、模型超时 60 s、工具超时 5 s、墙钟 120 s、tool_retries 0 |
  | `RunResult` | 一次 Run 的产出 | run_id、状态、停止原因、答复、步数、完整 messages、用量 |

- **设计选择**：消息本身不另造类型，直接用 OpenAI chat 格式的 dict（role / content / tool_calls / tool_call_id）。这样事件快照里存的就是真正发给模型的东西，不需要再转换一次。
- **谁用它**：所有层。
- **它依赖谁**：只有标准库。

##### `contracts/protocols.py`
- **一句话**：四条可替换边界，用 `typing.Protocol` 写成接口。
- **里面有什么**：

  | Protocol | 方法 | 真实现 | 替身 |
  |---|---|---|---|
  | `ModelClient` | `generate(messages, tools, timeout_s) -> ModelResponse` | `llm.DashScopeClient` | `doubles.ScriptedModel` |
  | `ErpGateway` | `get_product` / `get_inventory` / `get_shipment` / `get_order` | `tools.ErpClient` | `doubles.FakeERP` |
  | `Tool` | 属性 `spec` + `run(args, timeout_s) -> dict` | `tools.GetProductSpec`、`tools.GetAvailability` | 无需替身 |
  | `EventSink` | `emit(event_type, **data)` | `observability.JsonlSink`、`cli.TeeSink` | `observability.ListSink`、`tools.registry.NullSink` |

  另有异常类 `ToolFailure(category, code, message)`：工具和 ERP 客户端内部用它报告失败，执行器把它接住变成 `ToolResult(ok=False)`。
- **为什么这样分**：换模型只改 `ModelClient` 的实现；换 ERP 只改 `ErpGateway` 的实现；CLI 换成网页只换调用方；离线测试用 doubles 实现同一组接口。
- **谁用它**：`agent/loop.py` 拿 `ModelClient` 和 `EventSink`，`tools/registry.py` 拿 `Tool` 和 `EventSink`，两个工具文件拿 `ErpGateway`。
- **它依赖谁**：`types.py`。

##### `contracts/__init__.py`
- **一句话**：把 types 和 protocols 里的全部名字导出，其它模块统一 `from agent_app.contracts import …`。

---

#### 4.2.2 `guardrails/` 参数校验

**文件夹作用**：模型按工具描述生成的参数不可信，进业务函数之前在这里拦。W1 只有校验，W2 会在这一层加授权与确认，所以单独成一个目录而不是塞进 tools。

##### `guardrails/args.py`
- **一句话**：一个函数 `validate_args(spec, raw_arguments) -> dict`，按 ToolSpec 里的 JSON Schema 校验模型给的原始参数字符串。
- **检查顺序和对应错误码**：

  | 步骤 | 不通过时的 code |
  |---|---|
  | JSON 能否解析 | `invalid_json` |
  | 是否是对象 | `wrong_type` |
  | `required` 字段是否都在 | `missing_field` |
  | `additionalProperties: false` 时有没有多余字段 | `unknown_field` |
  | 类型是否匹配（bool 不算 int） | `wrong_type` |
  | 字符串是否全空白 | `empty_field` |
  | 数值是否低于 `minimum` | `out_of_range` |

  全部失败都抛 `ToolFailure("input_error", code, …)`。通过后把字符串参数 strip 掉再返回。
- **对应验收**：W1-AC-02，参数非法时 ERP 调用次数为零。测试在 `test_tools.py` 的 T06。
- **谁用它**：只有 `tools/registry.py` 的 `ToolExecutor`。
- **它依赖谁**：`contracts`。

##### `guardrails/__init__.py`
- 导出 `validate_args`。

---

#### 4.2.3 `observability/` 事件

**文件夹作用**：记录执行事实。记请求、响应、工具调用、结果、停止原因；不记 API Key 和鉴权头；不是模型的思维链。W9 会在这里接 OTel Trace。

##### `observability/events.py`
- **一句话**：两个事件出口和一个读取函数。
- **里面有什么**：
  - `ListSink`：事件进内存列表，测试用。
  - `JsonlSink(path)`：一次会话一个文件，一行一个事件，只追加。构造时数已有行数接着编 `seq`，所以 `--resume` 后同一文件里的序号是连续的。每个事件带 `seq`、`ts`、`type` 和具体字段。
  - `read_events(path) -> (events, problems)`：读文件，坏行不抛异常而是记进 `problems`。进程写到一半被杀会留半行，回放要能报出来而不是崩掉。
- **事件类型一览**（由 Loop 和 Executor 发出）：`run.started`、`model.request`、`model.response`、`model.error`、`tool.requested`、`tool.rejected`、`tool.retry`、`tool.executed`、`budget.exhausted`、`run.completed` / `run.stopped` / `run.failed`。
- **谁用它**：`cli.py` 建 `JsonlSink`，`agent/replay.py` 用 `read_events`，测试用 `ListSink`。
- **它依赖谁**：只有标准库。

##### `observability/__init__.py`
- 导出 `JsonlSink`、`ListSink`、`read_events`。

---

#### 4.2.4 `llm/` 模型适配

**文件夹作用**：和模型供应商打交道的唯一位置。只做两件事：把 messages + tools 发出去；把原始 JSON 归一化成 `ModelResponse`。不决定业务动作，不执行任何函数。

##### `llm/dashscope_client.py`
- **一句话**：百炼 OpenAI 兼容接口的 `ModelClient` 实现。
- **里面有什么**：
  - `ModelError(category, message, status, body)`：模型调用层异常，category 有 config / timeout / network / http / malformed 五种。
  - `parse_chat_completion(raw) -> ModelResponse`：纯函数，不联网。规则：有 `tool_calls` 就是 TOOL_CALLS；否则有非空文本就是 FINAL；都没有就是 MALFORMED。`test_model_parse.py` 用真实录下的响应测它。
  - `DashScopeClient(api_key, model, base_url, temperature=0.2, max_tokens=1024, transport=None)`：
    - 构造时没 Key 直接抛 config 错，不会带空 Key 发请求。
    - `describe()`：返回进事件快照的模型名和生成参数，没有密钥。
    - `request_body()`：真正发出去的请求体，带 `tools`、`tool_choice: auto`、`parallel_tool_calls: true`。
    - `generate()`：httpx POST `/chat/completions`，把超时、网络错、HTTP 4xx/5xx、非 JSON 四种失败分别映射成 `ModelError`，正常则交给 `parse_chat_completion`。
    - `transport` 参数可注入 `httpx.MockTransport`，测试用它证明请求头确实带了 Bearer Key 而事件文件里没有。
- **谁用它**：`cli.py` 的 `build_registry()`（真实模式）、`scripts/record_model_samples.py`。
- **它依赖谁**：`contracts`、httpx。

##### `llm/__init__.py`
- 导出 `DashScopeClient`、`ModelError`、`parse_chat_completion`。

---

#### 4.2.5 `tools/` 工具层

**文件夹作用**：Agent 能做的事全在这里。规则写在 `apps/agent-python/AGENTS.md`：每个工具一文件、带 ToolSpec；新增工具只改 `tools/<name>.py`、注册、schema、测试、文档，不得在 Loop 里按工具名加分支。

##### `tools/erp_client.py`
- **一句话**：真实 ERP 的 HTTP 访问，实现 `ErpGateway`。
- **里面有什么**：
  - `ErpClient(base_url, api_key, transport=None)`：鉴权用 `X-Api-Key` 头。
  - 私有 `_get(path, params, timeout_s)`：所有请求走这里，把每种失败翻译成 `ToolFailure` 分类，不让 httpx 异常漏到上层：

    | 情况 | category | code |
    |---|---|---|
    | 客户端超时 | timeout | client_timeout |
    | 连接等其它 HTTP 错 | upstream_error | http_error |
    | 404 | not_found | 上游 code，如 product_not_found |
    | 504 或响应体 code 为 gateway_timeout | timeout | gateway_timeout |
    | 其它 4xx / 5xx | upstream_error | 上游 code 或状态码 |
    | 200 但不是 JSON | malformed | not_json |

  - 四个公开方法对应 ERP 的四个端点：`/v1/products/{sku}`、`/v1/inventory/{sku}?qty=`、`/v1/shipments/{no}`、`/v1/orders/{id}`。
- **错误分层的意义**：404 是业务无数据，超时是上游临时故障，非 JSON 是解析错误。三者回注给模型的措辞不同，重试策略也不同（只有 timeout 会重试）。
- **谁用它**：`cli.py` 真实模式下注入给两个工具。
- **它依赖谁**：`contracts`、httpx。

##### `tools/product.py`
- **一句话**：工具 `get_product_spec`，按型号查规格与主数据。
- **里面有什么**：
  - 模块级 `SPEC`：名字、给模型看的描述、参数 schema（只有 `model`，必填，不许多余字段）。
  - `GetProductSpec(erp)`：持有一个 `ErpGateway`。`run()` 调 `erp.get_product()`，然后把 ERP 原始字段整理成模型好读的形状：model、name、name_en、category、key_spec、specs（去掉 null）、list_price、lifecycle、lead_time_days、doc_ref、spec_source、source_version。
- **谁用它**：`cli.py` 注册进 `ToolRegistry`；`scripts/record_model_samples.py` 拿 `SPEC`。
- **它依赖谁**：`contracts`，以及注入进来的 `ErpGateway`。

##### `tools/availability.py`
- **一句话**：工具 `get_availability`，按型号和数量查库存与交期。
- **里面有什么**：
  - `SPEC`：参数 `model`（必填）和 `qty`（integer，minimum 1，默认 1）。
  - `GetAvailability(erp)`：`run()` 调 `erp.get_inventory()`，输出可用量、在途、最早发运日、整单发运日、依据、排程行、贸易术语，以及 `observed_at`。库存是时点数据，系统提示要求回答时带上观测时间。
- **谁用它**、**它依赖谁**：同 `product.py`。

##### `tools/registry.py`
- **一句话**：工具的名册和执行器。
- **里面有什么**：
  - `NullSink`：不想记事件时用的空实现。
  - `ToolRegistry(tools)`：按名字存取工具；`specs()` 返回全部 ToolSpec 给 Loop 发给模型；`register()` 加一个。
  - `ToolExecutor(registry, sink).execute(call, timeout_s, run_id, retries) -> ToolResult`，顺序固定为**查 → 验 → 执 → 回**：
    1. 先发 `tool.requested` 事件（不变式 I2：先落日志再执行，被拒绝的也要记）。
    2. 查名册，没有就发 `tool.rejected` 并返回 `unknown_tool`。
    3. 调 `validate_args`，失败就发 `tool.rejected` 并返回 `input_error`。
    4. 进入尝试循环调 `tool.run()`。只对 `timeout` 类别做有界重试，每次重试发 `tool.retry`；成功或最终失败都发 `tool.executed`，带 attempts 和 duration_ms。
    5. 返回带同一 `call_id` 的 `ToolResult`。`tool.executed` 事件里带上成功时的 `data` 或失败时的 `message`，所以事件文件本身就能看到工具返回了什么。
- **对应验收**：W1-AC-01 只有已注册工具可执行、W1-AC-05 超时记为失败。测试 T05、T07、T08、T11。
- **谁用它**：`agent/loop.py` 调 `execute()`，`cli.py` 装配。
- **它依赖谁**：`contracts`、`guardrails`。

##### `tools/__init__.py`
- 导出 `ToolExecutor`、`ToolRegistry`。

---

#### 4.2.6 `doubles/` 测试替身

**文件夹作用**：真实模型和真实 ERP 的假冒实现，接口一样、行为可控。让单测不联网不花钱、结果可预测，也让 `make chat-offline` 没有 Key 和 ERP 也能跑。它们只验证程序控制逻辑，不模拟模型的智能。

##### `doubles/scripted_model.py`
- **一句话**：按剧本说话的假模型，实现 `ModelClient`。
- **里面有什么**：
  - 三个造响应的函数：`final(text)`、`tool_calls((name, args), …)`（args 可以是 dict 也可以是故意非法的原始字符串）、`malformed()`。
  - `ScriptedModel(script, repeat_last=False)`：第 N 次调用返回脚本第 N 条；每次收到的 messages / tools / timeout 存进 `requests`，测试据此断言"第二轮真正发给模型的是什么"。脚本用尽默认抛 AssertionError；`repeat_last=True` 一直返回最后一条，模拟"永远请求工具"。
- **谁用它**：全部单测、`cli.py` 的 `--scripted`。
- **它依赖谁**：`contracts`。

##### `doubles/fake_erp.py`
- **一句话**：内存里的假 ERP，实现 `ErpGateway`。
- **里面有什么**：
  - 四张字典当数据表：products、inventory、shipments、orders。查找不区分大小写。
  - `calls`：按方法名的调用计数，测试断言"ERP 调了几次"靠它。
  - `inject(method, failure, times=None)`：让某方法前 N 次抛指定 `ToolFailure`，之后恢复；不给 times 就一直失败。`FakeERP.timeout()` 是造超时故障的快捷方式。
  - `from_fixtures(dir)`：读 `scripts/record_fixtures.py` 录下的 JSON，只装 status 200 的，404 样本留给契约测试。
- **谁用它**：`tests/unit/conftest.py` 的 `erp` fixture、`cli.py` 的 `--scripted`。
- **它依赖谁**：`contracts`。

##### `doubles/__init__.py`
- 导出 `FakeERP`、`ScriptedModel`、`final`、`malformed`、`tool_calls`。

---

#### 4.2.7 `agent/` 循环本体

**文件夹作用**：把模型、工具、事件串成一次执行，并处理执行之外的两件事：会话怎么存取、事件怎么回放。这里不知道任何具体工具的名字，也不知道型号和价格。

##### `agent/context.py`
- **一句话**：`ContextBuilder.build(history, user_input)` 把系统提示、历史、本次输入拼成 messages。只组装，不保存权威事实。
- **里面有什么**：`DEFAULT_SYSTEM` 四条给模型的规则：事实只能来自工具结果；工具失败如实说无法确认，不说库存为零；型号不明先追问；不复述原始 JSON，库存带观测时间。
- **谁用它**：`loop.py`。
- **它依赖谁**：无。

##### `agent/loop.py`
- **一句话**：`AgentLoop`，整个 W1 的心脏，约一百行。
- **构造参数**：model、executor、tools、context、sink、budget、clock。clock 可注入，测墙钟时不用真等 120 秒。
- **`run(user_input, history, run_id) -> RunResult` 的控制流**：
  1. 组上下文，发 `run.started`。
  2. `while steps < max_steps`：先查墙钟，超了发 `budget.exhausted` 以 WALL_CLOCK 停。
  3. 发 `model.request`，快照里是真正发给模型的 messages、tools、timeout、模型参数（不变式 I1），没有密钥。
  4. 调 `model.generate()`；抛 `ModelError` 则发 `model.error` 以 MODEL_ERROR 失败。
  5. 累加用量；为 None 则标 unknown，不当零。发 `model.response`。
  6. TOOL_CALLS：先把完整 assistant 消息（含 call_id）追加进 messages，再逐个串行执行，每个结果以同一 call_id 的 tool 消息追加回去，全部配对后才进下一轮。
  7. FINAL：追加 assistant 消息，以 COMPLETED 结束。
  8. MALFORMED：以 PROTOCOL_ERROR 失败。
  9. 循环自然退出即步数耗尽，以 MAX_STEPS 停，此时 messages 停在完整边界。
- **设计检验**：这里没有任何 `if name == "某工具"`。加新工具不碰这个文件。
- **谁用它**：`cli.py`、全部 Loop 相关测试。
- **它依赖谁**：`contracts`、`llm`（只为 `ModelError` 类型）、`tools`、`context.py`。

##### `agent/conversation.py`
- **一句话**：会话的持久化与装载。
- **里面有什么**：
  - `ConversationStore(runs_dir)`：以 `runs/<conversation_id>/` 为会话目录。`save()` 存 `history.json`（去掉 system 消息）；`load()` 读回来并裁边界；`events_path()` 给 `JsonlSink` 用。
  - `complete_boundary(messages) -> LoadedHistory`：处理"进程在工具执行到一半被杀"的历史。若最后停在 assistant 请求了两个工具但只有一个结果，就裁回最后一个完整边界，并在 `note` 里报告裁了几条。
- **语义边界**：继续会话 = 新 Run + 已保存的完整历史，**不是恢复被杀的执行**。后者是 W6 的检查点续跑。
- **谁用它**：`cli.py`（`--resume`）、`test_resume.py`。
- **它依赖谁**：只有标准库。

##### `agent/replay.py`
- **一句话**：只读回放，`replay(events_path) -> ReplayReport`。
- **里面有什么**：读事件文件，按 run_id + step 把 request / response / tool 事件配对成 `ReplayStep`，列出每个 Run 的停止记录，并报告缺损：有响应没请求、工具结果找不到请求、发了请求没响应（中断点）、工具请求没执行记录、Run 没有停止记录。
- **设计检验**：函数签名里没有模型也没有 ERP，`external_calls_made` 是给读者看的常量 0。对应 W1-AC-07。
- **谁用它**：`cli.py` 的 `replay` 子命令、`test_replay.py`。
- **它依赖谁**：`observability.read_events`。

##### `agent/__init__.py`
- 导出 `AgentLoop`、`ContextBuilder`。

---

#### 4.2.8 顶层四个文件

##### `config.py`
- **一句话**：配置只从环境变量来，`.env` 由这里读。
- **里面有什么**：
  - `load_dotenv()`：从当前目录向上找 `.env`，逐行解析，不覆盖已存在的环境变量，不引第三方包。
  - `Settings.from_env()`：冻结 dataclass，六个字段对应 `.env.example` 的六个变量，都有默认值。Key 默认空串，`DashScopeClient` 构造时会拒绝。
- **安全边界**：密钥只在这里被读一次，然后只传给 `DashScopeClient` 的构造函数，不进事件、不进日志。
- **谁用它**：`cli.py`、`scripts/record_model_samples.py`。

##### `pricing.py`
- **一句话**：把 token 用量换算成元。
- **里面有什么**：`DEFAULT_PRICES` 内置价目表（qwen-plus 等，元 / 千 token，整理时的标价，可能过时）；`Price.cost(usage)` 按输入、输出分别计价，用量未知返回 None 不当零；`resolve(model, in, out)` 决定单价来源：`.env` 的 `AGENT_PRICE_INPUT_PER_1K` / `AGENT_PRICE_OUTPUT_PER_1K` 优先，其次内置表，都没有就返回 None 显示"无法估算"。输出里会标明单价来自哪里。
- **边界**：这是估算，不是账单；W4 的费用预算和 W11 的成本记账会在此基础上做。
- **谁用它**：`cli.py` 的 chat 摘要、每步用量行和 replay 合计。
- **它依赖谁**：`contracts.Usage`。

##### `cli.py`
- **一句话**：命令行入口 `agent-cli`，负责输入输出和装配，不实现另一份 Loop。
- **里面有什么**：
  - 终端排版小工具：ANSI 颜色函数、`short_id()`、`rule()`。stderr 是终端时才上色，`NO_COLOR=1` 关、`FORCE_COLOR=1` 强开。
  - `TeeSink`：事件既写 JSONL 又在 stderr 打给人看（▶ 发模型、◀ 模型回、→ 请求工具、← 执行、✗ 拒绝、↻ 重试、■ 预算耗尽）。每步打印模型生成的文本、每个工具返回的结果（默认压缩成一行 200 字，`-v` 展开成缩进 JSON）、本步输入 / 输出 / 合计 token 和估算费用。
  - `build_registry(settings, scripted)`：**唯一决定用真的还是用替身的地方**。真实模式装 `DashScopeClient` + `ErpClient`；`--scripted` 装 `ScriptedModel` + `FakeERP.from_fixtures()`。两种模式都注册同样的两个工具。
  - `cmd_chat()`：读 Settings → 新建或 `--resume` 装入会话 → 建 TeeSink → 装配 → 组 Budget → 跑 Loop → 存 history.json → stderr 打五行摘要（会话、状态、事件、继续、回放）→ stdout 打答复。退出码 completed 为 0，否则 1。
  - `cmd_replay()`：调 `replay()`，按 Run 分组打印每步、工具结果、结束、缺损。有缺损退出码 1。
  - `main()`：argparse 两个子命令。`chat` 的参数：`--resume`、`--show-request`、`-v/--verbose`、`--max-steps`、`--tool-retries`、`--tool-timeout`、`--scripted`。
- **谁用它**：`pyproject.toml` 的 `[project.scripts]` 把 `agent-cli` 指到 `agent_app.cli:main`；Makefile 的 chat / replay 目标。
- **它依赖谁**：几乎所有层，这是它作为装配点的职责。

##### `__init__.py`
- 包 docstring 和 `__version__ = "0.1.0"`。

### 4.3 `tests/` 测试与 fixture

每个测试文件开头 docstring 标了测试计划里的 T 编号和对应 W1-AC。全部 37 个单测离线，本地 0.3 秒跑完。

**`unit/conftest.py`** 两个 fixture：`erp` 是从录制文件装好的 `FakeERP`；`fixtures_dir` 是 fixture 根目录。

| 文件 | T 编号 | 验证什么 |
|---|---|---|
| `test_loop.py` | T01–T04、T09、T10 | 模型直接答不执行工具；一次调用结果进下一轮；两轮保留全部历史；一次多调用每个 call_id 都配对；工具失败也配对回注且"错误不是事实"；步数耗尽不多发一次模型调用且停在完整边界；MALFORMED 是协议失败不是完成 |
| `test_tools.py` | T05–T08 | 未知工具不执行任何函数；缺字段 / 空串 / 类型错 / 多余字段 / 非法 JSON 六种坏参数都到不了 ERP；404 是业务无数据且回注内容里没有伪造的 data；读超时、504、非 JSON 分别映射到 timeout / timeout / malformed；默认不重试 |
| `test_budget.py` | T11 | 配置 1 次重试恰好多打 1 次；重试上限守得住；not_found 不重试；用量未知标 unknown 不当零；墙钟到期不再发模型请求（用注入时钟） |
| `test_events.py` | T12 | 事件序列精确匹配十个类型；第二步快照就是真正发给模型的 messages 且 tool_call_id 配对；用 `httpx.MockTransport` 证明请求头确实带了 Bearer Key 但事件文件里一个字都没有 |
| `test_replay.py` | T13 | 回放前后模型和 ERP 调用计数不变；文件被截断成半行时能报出 problems 和 gaps |
| `test_resume.py` | T14 | 存历史、新进程装历史、新 Run 第一次请求里是完整历史加新输入；旧工具请求没有被重新执行；未配对历史被裁回完整边界 |
| `test_model_parse.py` | w1.6b | 用真实录下的三份模型响应 JSON 验证 `parse_chat_completion`：final、单工具、多工具保持不同 id；空 content 是 MALFORMED |
| `test_doubles.py` | w1.5 | 替身本身可信：ScriptedModel 按序返回并记录请求、用尽报错；FakeERP 计数、注入、大小写不敏感、能装录制 fixture |

**`integration/test_erp_contract.py`** 契约测试：对四个录制 fixture 发真实请求，断言状态码和响应字段集合一致。ERP 9100 不可达时整个文件 skip，CI 不跑。它回答的问题是"ERP 改字段了没有"：改了就先重录 fixture 再改工具。

**`fixtures/erp/*.json`** 十二个文件，由 `scripts/record_fixtures.py` 录制，每个文件 = 录制时间、ERP 版本、ERP 当前时间、场景名、请求（method / path / query）、状态码、content_type、响应体。覆盖三个型号（X200、X200-Pro、T200）、两种数量的库存、一个运单、一个订单，以及四个 404 样本（X999、SF0000000000、ORD-99999）。文件名就是"资源_键_状态"。`FakeERP.from_fixtures` 只装 200 的。

**`fixtures/model/*.json`** 三个文件，由 `scripts/record_model_samples.py` 录制：`final_text`（模型直接回答）、`single_tool_call`（请求一个工具）、`multi_tool_call`（一次请求两个工具）。每个文件存请求体、原始响应和解析结果，用于离线解析课和 `test_model_parse.py`。

### 4.4 `runs/` 运行产物（不入库）
每次 `agent-cli chat` 产生 `runs/<8位会话id>/events.jsonl` 和 `history.json`。当前有两个真实会话：`753fecf8`（"查一下 X200 的规格和当前库存交期"，18 个事件）和 `8bcbd41a`（"ORD-10086 的运单 SF1234567890 现在到哪了"，8 个事件）。`agent-cli replay <id>` 读的就是这里。

### 4.5 `.pytest_cache/`
pytest 自己的缓存（`--lf`、`--ff` 用），已忽略，可以随时删。

---

## 5. `scripts/` 录制脚本

两个脚本都遵守同一条原则：**fixture 不手写，永远是真实系统的快照**。

- **`record_fixtures.py`**：连模拟 ERP（默认 9100，`X-Api-Key: east-demo-key`），先读 `/health` 拿版本和场景，再按 `CASES` 表逐个请求十二个端点，每个存成 `tests/fixtures/erp/<name>.json`。运行：`uv run --project apps/agent-python python scripts/record_fixtures.py`。
- **`record_model_samples.py`**：用 `Settings.from_env()` 和真实 `DashScopeClient`，带两个工具的 schema 发三条真实请求，把请求体、原始响应、解析结果存成 `tests/fixtures/model/<name>.json`。需要 `.env` 里有 Key。

---

## 6. `evals/graders/w01-manual-rubric.md`
真实模型冒烟的人工判定量表。W1-AC-06"最终答复中的规格与交期由有效工具结果支持"是模型质量，不能写成单测断言，所以走这里。五个判定项：事实来源（答复里的数字能在工具结果里找到）、失败措辞（说无法确认不说库存为零）、缺信息（追问不猜）、不必要调用（记录不扣分）、语言（中文简洁不贴 JSON）。测试计划提到的 `evals/datasets/w01-smoke.jsonl` 在 w1.8 还没有建。

---

## 7. 占位目录

- **`apps/platform-java/README.md`**：W0 的 Spring Boot 骨架位置，W1 不扩展，W5 起从 `spike-dualstack/platform-java` 搬入。
- **`apps/web/README.md`**：前端成品占位，W5 起接入，W1 只有终端。
- **`config/`**：空目录，后续周放配置。

---

## 8. 一条请求在这些文件之间怎么流

以 `uv run agent-cli chat "查一下 X200 的规格和当前库存交期"` 为例：

1. `cli.py` 的 `main()` 解析参数进 `cmd_chat()`。
2. `config.py` 从 `.env` 读出六个变量。
3. `conversation.py` 的 `ConversationStore` 生成会话 id，`events.py` 的 `JsonlSink` 在 `runs/<id>/events.jsonl` 准备追加。
4. `cli.py` 的 `build_registry()` 构造 `DashScopeClient`（`llm/`）、`ErpClient`（`tools/erp_client.py`），把 `GetProductSpec` 和 `GetAvailability` 注进 `ToolRegistry`（`tools/registry.py`）。
5. `loop.py` 的 `AgentLoop.run()`：`context.py` 组 system + user；发 `model.request` 快照；`DashScopeClient.generate()` 发 HTTP，`parse_chat_completion()` 归一化成 `ModelResponse`（`contracts/types.py`）。
6. 模型请求两个工具。Loop 把 assistant 消息追加，然后对每个 `ToolCall` 调 `ToolExecutor.execute()`：发 `tool.requested`；`guardrails/args.py` 校验参数；`GetProductSpec.run()` 调 `ErpClient.get_product()` 发 `GET /v1/products/X200`；结果包成 `ToolResult`，发 `tool.executed`，`to_message()` 变成 tool 消息追加回去。
7. 第二轮模型拿到两条 tool 消息，回最终文本。Loop 发 `run.completed`，返回 `RunResult`。
8. `cli.py` 把 `result.messages` 存成 `history.json`，stderr 打状态行，stdout 打答复。
9. 之后 `agent-cli replay <id>` 走 `replay.py`，只读 `events.jsonl`，不碰模型和 ERP。
10. 之后 `agent-cli chat --resume <id> "那它现在的库存呢"` 走 `conversation.py` 的 `load()`，裁到完整边界后作为 history 传给新的 Run。

离线时把第 4 步换成 `ScriptedModel` + `FakeERP.from_fixtures(tests/fixtures/erp)`，其它一行不变。这就是 `--scripted` 和全部单测的工作方式。

---

## 9. 建议阅读顺序

1. `README.md` → `docs/architecture.md`：五分钟知道全貌。
2. `docs/specs/w01-agent-loop.md` 的任务分解表和 W1-AC 表：知道要做成什么。
3. `contracts/types.py` → `contracts/protocols.py`：知道数据长什么样、边界在哪。
4. `agent/loop.py`：一百行，整个 W1 的控制流。
5. `tools/registry.py` → `guardrails/args.py` → `tools/erp_client.py`：工具怎么被查、验、执、回。
6. `tests/unit/test_loop.py` 和 `test_tools.py`：每条验收怎么被证明。
7. `cli.py`：真实与替身怎么装配。
8. 最后读 `AGENTS.md`：动手改之前的规矩。
