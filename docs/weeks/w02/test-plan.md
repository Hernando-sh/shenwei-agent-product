# W2 测试计划（2.1 定，2.1–2.7 逐条变绿，2.8 作业 T33）

行为覆盖点，不规定测试函数数量；每条能追到周 spec `w02-quote.md` 的 W2-AC。编号接 W1 的 T15。

| ID | 验证行为 | 关键断言 | W2-AC | 节 | 测试位置 |
|---|---|---|---|---|---|
| T16 | 只读工具四种结果可区分 | 正常 ok=True；空列表 ok=True 且 data 为空（不是 not_found）；401 → rejected/unauthorized；跨租户 404 → not_found；504 → timeout；5xx → upstream_error | 01 | 2.1 | tests/unit/test_tools_w2.py |
| T17 | 契约测试对真实 ERP | 四个接口的字段名与接口说明一致；ERP 不可达自动跳过 | 01 | 2.1 | tests/integration/test_erp_contract.py |
| T18 | 本地与远程来源同一策略 | 同名工具两种来源，Policy 的决定（allow / confirm / reject）相同 | 02 | 2.2 | tests/unit/test_runtime.py |
| T19 | 拒绝也有记录 | 策略拒绝 → 事件 tool.rejected 带 reason=policy；工具执行计数 0；拒绝结果回注模型 | 02 | 2.2 | test_runtime.py |
| T20 | 管线顺序 | 事件顺序 tool.requested → policy.decided → tool.executed；校验失败不产生 policy.decided 之后的事件 | 02 | 2.2 | test_runtime.py |
| T21 | 空证据不编造 | hits 为空 → ok=True、evidence=[]、note 说明无依据；不调模型补内容 | 03 | 2.3 | tests/unit/test_knowledge.py |
| T22 | 版本条件透传 | 参数 order_date 原样进请求体 filters；返回每条带 version / status / applies_to / locator | 03 | 2.3 | test_knowledge.py |
| T23 | 报价工具无自由金额参数 | price_quote 与 create_quote 的 schema 里没有 unit_price / amount / discount / total_amount；模型传入这些字段 → guardrails unknown_field，ERP 计数 0 | 04 | 2.4 | tests/unit/test_quote.py |
| T24 | 草案字段可核对 | QuoteDraft 的 unit_price / amount / total_amount / currency / payment_terms_code / incoterm 逐一等于 FakeERP price 返回；草案没有可被模型改写的金额入口 | 04 | 2.4 | test_quote.py |
| T25 | 前置规则由程序执行 | 客户 overdue → 草案被拦、理由 overdue；有效期内同内容报价存在 → 理由 duplicate；两种情况 create_quote 计数 0 | 05 | 2.4 | test_quote.py |
| T26 | 未确认不写 | 询问模式：确认适配器未返回同意前 FakeERP.create_quote 计数 0；同意后计数 1 | 06 | 2.5 | tests/unit/test_confirm.py |
| T27 | 改参数使确认失效 | 2 台令牌 → 参数改 10 台 → 摘要不同 → 令牌校验失败事件 → 不写；重新确认后写的是 10 台 | 07 | 2.5 | test_confirm.py |
| T28 | 拒绝与过期 | 拒绝 → 计数 0、outcome=cancelled；过期令牌（可注入时钟）→ 不写、要求重新确认 | 06 / 07 | 2.5 | test_confirm.py |
| T29 | 模式切换 | set_mode 写 mode.changed；auto 下内部写工具不请求确认直接执行；auto 下 create_quote 仍请求确认 | 10 | 2.5 | test_confirm.py |
| T30 | 重复请求只有一份 | 同一 operation_id 两次确认 → 两次请求同一 Idempotency-Key → FakeERP 台账一条；第二次返回 replay 标记 | 08 | 2.6 | tests/unit/test_write.py |
| T31 | 未知结果不盲重试 | 注入 502 → 事件 operation.unknown → 同键核实一次 → 已提交则取回原结果、未提交则一次新执行；写工具 timeout 不进 retries；两种情况台账都只有一条 | 09 | 2.6 | test_write.py |
| T32 | MCP 来源不绕策略 | MCP 来源宣告的 create_quote 仍走确认；server 断开 → category=source_unavailable；协议错误 → protocol_error；不伪装成功 | 11 | 2.7 | tests/unit/test_mcp.py |
| T32i | MCP 集成 | 起真实 stdio server，S01 原题的工具结果与本地来源一致；server 不可用自动跳过 | 11 | 2.7 | tests/integration/test_mcp_live.py |
| T33 | 独立变体：写跟进 | 询问模式未确认计数 0、确认后 SCRM 账本一条；自动模式不问直接写有事件；同键重放一条；Loop / Runtime 无业务特判 | 06 / 10 | 2.8 作业 | tests/unit/test_followup.py |

替身：`agent_app.doubles.ScriptedModel`（W1）、`agent_app.doubles.FakeERP`（扩展：客户 / 回款 / 台账读写、价格用录制 fixture 不实现规则、幂等键表、502 / 超时注入）、`agent_app.doubles.FakeKnowledge`（固定 hits）、`agent_app.doubles.ScriptedConfirm`（脚本化的同意 / 拒绝 / 改参数）、`agent_app.doubles.FakeScrm`（T33）。
真实模型冒烟十条在 `evals/datasets/w02-smoke.jsonl`，人工判定量表在 `evals/graders/w02-manual-rubric.md`，不混进单测。
