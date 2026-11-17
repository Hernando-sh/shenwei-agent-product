# ADR-006 · 写操作的结果未知时同键核实一次，不重试、不换键

日期 2026-11-07 · 状态 accepted · 关联 2.6 · 补 ADR-002「W2 的写工具不能照搬」

## 场景

保存报价时 ERP 返回 502（response_lost：业务已提交，响应丢了）或 504 / 客户端超时（timeout：没提交）。调用方拿到的都是"没有结果"，但两种情况的事实相反。只读工具的做法（有界重试）在这里会写出第二条报价；什么都不做则业务员不知道有没有存上。

## 选择

1. 写请求的错误分类独立于读：5xx、超时、断连一律是 `unknown`（结果未知），不是 `timeout` / `upstream_error`。所以写永远进不了 ADR-002 的只读重试分支（T31：`retries=3` 也不会 `tool.retry`）。
2. 每个写操作有一个由运行时从变更集生成的 `Operation`：`Idempotency-Key = <run_id>:<operation_id>`、`X-Actor = agent:<run_id>`。同一个变更集不论重放几次，键不变。
3. 结果未知 → 事件 `operation.unknown` → 用同一个键再发一次（attempt 2）→ 事件 `operation.verified`：ERP 回 `Idempotent-Replay: true` 说明第一次已提交、拿回的是原结果；没有这个头说明第一次没提交、这次是新执行。两种情况台账都只有一条。
4. 只核实一次。核实仍未知 → 工具结果 `unknown / verify_failed`，业务结果 failed，回注模型「不要再次保存，需到 ERP 台账人工核对 Idempotency-Key …」。核实得到明确失败（404 / 422）→ 未提交，按失败处理。
5. 写工具第一次尝试前再执行一遍前置规则（防模型跳过算价直接保存）；核实时（attempt ≥ 2）跳过规则——否则 response_lost 之后的核实会被"已有同内容报价"拦住，拿不回原结果。
6. 操作台账 `runs/<会话>/operations.jsonl` 追加每一步状态：pending → committed / unknown / failed / declined。它回答"这次运行到底写了没有"，和事件文件互相印证。

## 不做

不做后台异步核实与人工待办队列（W6 挂起 / W8 运维）；不处理 `idempotency_in_progress`（409，并发写）的等待——本周串行执行不会出现。

## 证据

T30：同一 Operation 两次写台账一条、第二次带 replay 标记；同键不同体 409。T31：response_lost → unknown → verified committed=true replayed=true；timeout → verified replayed=false；核实再失败 → verify_failed、台账 0 条；明确失败不核实。
写契约测试 `tests/integration/test_erp_write_contract.py` 对私有 ERP 9177：四条全过（2026-11-07）。
