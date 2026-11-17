# ADR-004 · 报价前置规则放在算价工具内部，由程序执行

日期 2026-11-07 · 状态 accepted · 关联 2.4 · 回答周 spec w02-quote §8 第一条待澄清

## 场景

出报价前要判三件事：客户是否冻结 / 信用冻结、是否有逾期回款、有效期内是否已有同内容报价。两种放法：
（a）让模型先调 get_customer / get_receivables / list_quotes，自己看结果再决定要不要算价；
（b）把判定放进 price_quote 工具内部，程序按固定顺序查事实、判规则，拦下时返回 declined 与理由。

## 选择

（b）。依据：总 spec 第 2 节「报价规则由业务系统确定；模型负责澄清和建议」；W2-AC-05 要求「靠模型自觉」是禁止项。
规则顺序固定 blocked → credit_hold → overdue → duplicate → 算价，只报第一条理由；blocked / credit_hold 只看主数据，命中就不再查回款。
规则所需事实查不到（回款或台账接口失败）→ 工具失败原样交回，不出草案、不默认放行（「不把失败当事实」）。
草案 QuoteDraft 是冻结数据类，只能从 ERP 算价返回构造；参数 schema 里没有金额字段，guardrails 递归校验到报价行。

## 代价与不做

- 轨迹里不再有模型发起的 get_receivables / list_quotes 请求（它们在工具内部发生，出现在 ERP 请求账本与 tool.executed 的 facts 里）；案例集 must_call 的判法在 W4 判定器里按此调整。
- 四个只读工具仍注册给模型：业务员单独问「这家客户有没有逾期」时模型直接用。
- 不做：规则可配置化、按租户的规则差异（W8）。

## 证据

T25：逾期客户 price_quote 计数 0、理由 overdue 带天数与金额；冻结客户不查回款；同内容有效报价 → duplicate 带已有报价号；回款接口超时 → ok=false、不出草案。
