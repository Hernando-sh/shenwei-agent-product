# 独立变体 · scrm_write_followup（2.8 作业参考，分支 task/w2-followup，tag w2.8）

任务书：`docs/specs/w02-followup.md`。目的：用另一个系统（SCRM）、另一种档位（内部写）检验 2.2–2.6 的管线不是为报价写死的。

## 改了哪些文件（设计检验）

| 文件 | 为什么 |
|---|---|
| `tools/followup.py`（新） | 工具本体：参数、前置去重、返回字段 |
| `tools/scrm_client.py`（新） | SCRM 两个接口；身份是 SCRM 自己的 key |
| `tools/http_json.py`（新）+ `tools/erp_client.py`（瘦身） | 把 `_get / _post` 与失败分类抽成 `JsonApiClient`，ERP 与 SCRM 客户端共用；错误信息里的系统名随子类 |
| `contracts/protocols.py` | 加 `ScrmGateway` |
| `doubles/fake_scrm.py`（新） | 替身：客户 / 跟进 / 幂等表 / response_lost |
| `policy/table.py` | 没改——2.2 就按总 spec 预留了 `scrm_write_followup: write_internal（ask confirm / auto allow）` |
| `cli.py`、`config.py`、`.env.example` | 注册；`SCRM_BASE_URL` / `SCRM_API_KEY`；离线脚本含「跟进」时走真实确认 |
| `agent/context.py` | 系统提示加一句跟进 |
| `tools/runtime.py` | 两行措辞：核实失败的提示原来写死「ERP 报价台账」，改为目标系统 + 工具名 |
| `confirm/local.py` | 一行措辞：改参数的示例原来写死 `lines`，改为通用说明 |
| 测试 | `tests/unit/test_followup.py`（T33 十一条）、`tests/integration/test_scrm_write_contract.py`（四条） |

ToolRuntime、确认适配器、Loop 没有 `if name == ...`（T33 最后一条用源码检查守住）。两处措辞改动恰好说明 2.6 时有两句话默认了「写 = 报价」，这是本变体最值的收获。

## 规则

- 前置去重：第一次尝试前 `GET /v1/followups?customer_id=`，同客户已有**同内容**的跟进 → `outcome=declined / duplicate_followup`，不写（SCRM 自己不拦只记 `duplicate_followup`，而且只看 5 分钟窗口；工具更严：只要已有同内容就不写）。核实（attempt ≥ 2）不再查。
- 缺信息：`body` 空 → `input_error / empty_body`，不调 SCRM；多传 `message_to_customer` → guardrails `unknown_field`，不调 SCRM。
- 上游：404 `customer_not_found`；502 / 超时 → unknown → 同键核实；拿 ERP 的 key 来 → 401 rejected。
- `source=agent`、`run_id` 由程序填；`owner` 由 SCRM 按 `X-Actor` 定（`agent:*` → 记到客户业务员名下）。

## 三条预测轨迹（写在跑之前）

| # | 输入 | 模式 | 预测 |
|---|---|---|---|
| A | 给雅加达客户记一条跟进：已出 2 台 X200 的报价 QT-000001，等客户确认。 | ask | search_customers(Jakarta) → scrm_write_followup → confirmation.requested → 同意 → 一条 FU；答复带跟进编号 |
| B | 同 A | auto | search_customers → scrm_write_followup 直接写（policy allow，changeset.created 与 operation.* 事件照记，没有 confirmation.*）→ 一条 FU |
| C | 同 A，再说一次 | ask | search_customers → scrm_write_followup → **工具在确认前**就返回 declined / duplicate_followup（去重在 attempt 1 的 run 里，而 run 在确认之后——所以实际会先问确认、同意后才发现重复）。预测修正：确认 → 执行 → declined，账本不变；模型如实说已有同内容 |

C 的预测在写的时候就暴露了一个顺序问题：去重是业务规则，放在工具里就只能在确认之后执行，操作者会白确认一次。报价的 duplicate 没有这个问题，因为它先在只读的 price_quote 里拦。跟进没有「算草案」这一步。要在确认前拦，得让工具提供一个只读的「预检」或让运行时支持写工具的 pre-check 钩子——归 W5 再定，本周记下。

## 真实模型冒烟（2026-11-07）

配置：qwen-plus、max_steps 12、ask 模式、确认人 sales:zhou（终端确认由管道回 y）；ERP 私有 9177（base，已 reset）、SCRM 私有 9377（base，已 reset）。记录：`evals/runs/w02-followup-smoke-20261107/`（`terminal.txt`、`d8383be0/events.jsonl`、`operations.jsonl`、`scrm_ledger.json`）。

轨迹 A，实际：

```
tool.requested      search_customers {"q": "Jakarta"}        policy allow → ok
tool.requested      scrm_write_followup {"customer_id": "C-E001", "body": "已出 2 台 X200 的报价 QT-000001，等客户确认。"}
policy.decided      confirm  write_internal · ask · local
changeset.created   op=0336bb2a29de digest=7d6994e9aa111df0
confirmation.requested → confirmation.approved sales:zhou
operation.started   Idempotency-Key=29eb0cfb77bf:0336bb2a29de  agent:29eb0cfb77bf
tool.executed ok    id FU-000012 owner sales:zhou source agent run_id 29eb0cfb77bf
run.outcome         resolved
```

3 步、9418 tokens、completed。SCRM 账本（`GET /_admin/ledger`，只摘 agent 写的）：

```json
{"id": "FU-000012", "customer_id": "C-E001", "type": "note", "occurred_at": "2026-09-20T10:00:00+08:00",
 "owner": "sales:zhou", "body": "已出 2 台 X200 的报价 QT-000001，等客户确认。", "next_action_at": null,
 "source": "agent", "run_id": "29eb0cfb77bf", "tenant": "east", "idem_key": "29eb0cfb77bf:0336bb2a29de"}
violations: []        requests(POST): [{"path": "/v1/followups", "status": 201, "actor": "agent:29eb0cfb77bf"}]
```

答复：

> 已为雅加达客户 PT Nusantara Process Engineering（C-E001）记录跟进：「已出 2 台 X200 的报价 QT-000001，等客户确认。」跟进编号：FU-000012。

判定：过。账本一条、确认前无写请求、owner 记到客户业务员、body 原样、编号来自返回；没有替业务员写给客户的话。与预测 A 一致。B 与 C 由单测覆盖（`test_t33_auto_mode_*`、`test_t33_same_body_*`），没有再花模型调用。

## 测试

单测 135 → 146（T33 十一条）；SCRM 写契约 4 条对私有 9377 通过（同键重放、422 多传字段、404 / 401、response_lost 核实 + 工具去重）。

```
SCRM_WRITE_BASE_URL=http://localhost:9377 uv run pytest tests/integration/test_scrm_write_contract.py -q   # 4 passed
```
