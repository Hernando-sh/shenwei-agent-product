---
spec: w02-followup
week: W2
covers: [US-02 的内部写部分；v3.0 W2 独立变体「跟进记录写入」]
---

# 独立变体 · scrm_write_followup（写跟进记录）— 任务书

在你自己的 w2.6 或 w2.7 上做。它是本周第二个写工具，但写的是另一个系统（SCRM）、另一种档位（内部写），用来检验 2.2–2.6 的管线是不是只为报价写死的。

- 业务场景：业务员让系统在客户档案下记一条跟进，例如「给雅加达客户记一条跟进：已出 2 台 X200 的报价 QT-000001，等确认」。内容是给业务员和主管看的工作记录，不是发给客户的消息。
- 权威事实：SCRM `POST /v1/followups`（身份 `X-Api-Key: east-scrm-key`，和 ERP 的 key 不同；写操作带 `X-Actor` 与 `Idempotency-Key`）。客户编号与 ERP 共用（C-E001）。
- 输入：`customer_id`（必填）、`type`（note / call / email / meeting / task，默认 note）、`body`（非空，≤ 64 KB）、`next_action_at`（可选，RFC 3339）。`source` 固定 agent，`run_id` 由程序填。
- 输出：id、customer_id、occurred_at、owner、next_action_at。
- 档位：内部写。询问模式下先以变更集请求确认；自动模式下按策略放行，不问，但事件照记。
- 缺信息：客户落不到唯一编号 → 澄清；body 为空 → 输入错误，不调 SCRM。
- 上游失败：404 客户不存在；422 多传字段（例如 message_to_customer）是输入错误；502 / 超时 = 结果未知，同键核实。
- 重复：同客户同 body 五分钟内再写一条，SCRM 不拦但记 duplicate_followup；系统应先查近期跟进（`GET /v1/followups?customer_id=`），已有同内容就不再写。
- 设计检验：理想变化集中在新工具文件、SCRM 客户端、注册、策略表一行、测试、文档；ToolRuntime、确认适配器、Loop 不应出现 `if name == "scrm_write_followup"`。
- 验收 T33：注册后可用；询问模式未确认时 SCRM 调用计数 0，确认后账本 followups 正好一条；自动模式下不问直接写且有事件；同键重放只有一条；旧测试全过。另交三条预测轨迹与一条真实模型冒烟（账本原文）。
- 不要做的：替业务员给客户写消息（SCRM 没有发消息接口，请求体多字段会 422）；改客户字段（lead_grade 等归 W8）。

---

## 实现记录（2026-11-07，分支 task/w2-followup，tag w2.8）

已实现，见 `docs/weeks/w02/followup.md`：改动集中在新工具、SCRM 客户端、替身、注册与测试；策略表 2.2 已预留；ToolRuntime 与确认适配器各改了一句写死「报价」的措辞，没有业务特判。去重放在工具里意味着它在确认之后执行（操作者可能白确认一次）——写工具的确认前预检归 W5。一条真实模型冒烟过；单测 146。
