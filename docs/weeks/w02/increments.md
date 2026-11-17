# W2 红绿证据（T16–T32）

每节先提交红（测试文件 + 失败原因），再提交绿（最小实现），绿后打 `w2.k`。本周的红全部是"模块 / 类型不存在"（ImportError / ModuleNotFoundError）——因为每节都新开一层，不是改旧行为；2.2 与 2.6 各有一处旧测试因管线多了一步事件而更新预期（T12 加 `policy.decided`；T26 / T29 加 `operation.started`），在绿提交说明里写明。

提交序列（week/02，基线 main debbd70（w1 之后），单测 43）：

```
eb37465 w2.1 规格：周 spec w02-quote、测试计划 T16–T33、独立变体任务书、环境核实、冒烟数据集与量表
dd92267 w2.1a fixture 录制扩展：18 份 ERP 快照（含 401、404、422 样本）
282748f w2.1 红：T16（ModuleNotFoundError agent_app.tools.customer）
7e67ead w2.1 绿：四个只读工具、ErpGateway/ErpClient 四方法、401/403 → rejected、FakeERP 三张表、契约测试 T17        单测 61   tag w2.1
8dda8c7 w2.2 红：T18–T20（ModuleNotFoundError agent_app.policy）
b7b936e w2.2 绿：ToolRuntime 单一管线、表驱动 Policy、ToolKind/PolicyDecision；ToolExecutor 成为别名；T12 序列加 policy.decided   单测 69   tag w2.2
5cc7107 w2.3a 知识服务 fixture 录制脚本与 6 份快照
11a85d6 w2.3 红：T21–T22（ImportError FakeKnowledge）
74b0638 w2.3 绿：search_knowledge、KnowledgeClient、FakeKnowledge、知识契约测试                                         单测 77   tag w2.3
cd6881b w2.4 红：T23–T25（ModuleNotFoundError agent_app.quote）
5a0cc6d w2.4 绿：price_quote、QuoteDraft、规则层、guardrails 递归、422 → input_error；ADR-004                            单测 99   tag w2.4
e161dcd w2.5 红：T26–T29（ModuleNotFoundError agent_app.confirm）
88338a1 w2.5 绿：Changeset/ConfirmToken、确认环节、run.outcome、set_mode、LocalConfirm、ScriptedConfirm；ADR-005         单测 111  tag w2.5
b3a5dff w2.6 红：T30–T31（ImportError Operation）；2.5 替身接受 operation、预期加 operation.started
104e530 w2.6 绿：create_quote、写请求 unknown 分类、幂等表、ops 台账、核实；写契约测试；ADR-006                           单测 121  tag w2.6
f161345 w2.7 红：T32（ImportError FakeMcpClient）
86cadf1 w2.7 绿：mcp-erp-readonly 服务、McpToolSource/StdioMcpClient、FakeMcpClient；T32i；依赖 mcp 1.28                  单测 131  tag w2.7
0295234 w2 冒烟：smoke_w2.py 与十条记录；get_order 参考实现；q 可选、max_steps 12                                          单测 135
```

## 2.1 T16 红

```
ImportError while importing test module 'tests/unit/test_tools_w2.py'.
E   ModuleNotFoundError: No module named 'agent_app.tools.customer'
```

绿：`61 passed`。契约测试对私有 ERP 9177：`12 passed`（含 T17 五条：简表字段、credit 字段、空结果 200 + data=[]、401 problem+json）。

## 2.2 T18–T20 红

```
E   ModuleNotFoundError: No module named 'agent_app.policy'
```

绿：`69 passed`。期间 `test_t12_events_hold_actual_requests_and_pairings` 因事件序列多了 `policy.decided` 失败一次：

```
E       At index 4 diff: 'policy.decided' != 'tool.executed'
```

这是 W2-AC-02 管线要求的事件，更新了 T12 的序列预期（不是弱化：序列仍然逐项相等）。

## 2.3 T21–T22 红

```
E   ImportError: cannot import name 'FakeKnowledge' from 'agent_app.doubles'
```

绿：`77 passed`；知识契约测试对共享 9200：`4 passed`。

## 2.4 T23–T25 红

```
E   ModuleNotFoundError: No module named 'agent_app.quote'
```

绿过程中两处设计被测试纠正：（1）行顺序——`normalize_lines` 一开始按型号排序，导致发给 ERP 的 `lines=S10:4,X200:2` 和快照键对不上；改为保留用户顺序，另加 `canonical_lines` 供比较与摘要。（2）规则顺序——`blocked` 命中时测试要求不查回款（`get_receivables` 计数 0）；把 `check_customer_status` 拆成 `check_customer_master` 与 `check_overdue`。最终 `99 passed`。

## 2.5 T26–T29 红

```
E   ModuleNotFoundError: No module named 'agent_app.confirm'
```

绿过程中三处：`confirm.Changeset` 一开始是子类，`isinstance` 不成立 → 把 `build` 放回契约类；令牌校验顺序 operation → digest 改为 digest → operation（参数变了是业务员最该知道的原因）；拒绝路径的 `run.outcome` 应在 `tool.rejected` 之后。最终 `111 passed`。

## 2.6 T30–T31 红

```
E   ImportError: cannot import name 'Operation' from 'agent_app.contracts'
```

绿：`121 passed`；写契约测试（私有 ERP 9177）`4 passed`：同键重放带 replay 头、同键不同体 409、`unit_price` 进请求体 422 `lines.0.unit_price`、response_lost 已提交 / timeout 未提交。

## 2.7 T32 红

```
E   ImportError: cannot import name 'FakeMcpClient' from 'agent_app.doubles'
```

绿：`131 passed`；T32i 对真实 stdio 服务 `4 passed`（S01 两个工具结果与本地逐字段相等，事件序列相同，`policy.decided.source = mcp:erp-readonly`）。

## 冒烟后的两处修正（0295234）

- `search_customers` 的 `q` 改可选、q / country_code 至少一个：T16 新增「只按国家列候选」一条；`135 passed`。
- `max_steps` 8 → 12：CLI 默认值、冒烟脚本、周 spec §5 与 §8。
