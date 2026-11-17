# PR · week/02 → main（本地审查记录）

解决的问题与规格链接：W2 工具工程与受控业务执行；`docs/specs/w02-quote.md`（W2-AC-01–12）、独立变体任务书 `w02-followup.md`（实现在分支 task/w2-followup，tag w2.8，不并入 main）。

关键修改及为什么：
- tools/runtime + policy：所有工具请求走同一条管线（解析 → 校验 → 策略 → 确认 → 执行 → 结果），策略按名字查表，来源宣告不参与；被拒绝的也留事件（W2-AC-02 / 03）。Loop 没改。
- tools/customer · receivables · quotes · knowledge：只读工具四种结果可区分（空 ≠ 不存在、401 ≠ 不存在）；知识证据带出处与版本，空命中不编造（W2-AC-01 / 04）。
- quote + tools/price_quote：规则 blocked → credit_hold → overdue → duplicate 由程序在算价前判；草案金额只从 ERP 取；参数没有金额字段，嵌套也拦（W2-AC-05 / 06 / 07；ADR-004）。
- confirm + contracts.Changeset / ConfirmToken：确认绑定摘要与有效期，同意 / 拒绝 / 改参数三种决定；没有确认通道就不写；自动模式报价仍确认（W2-AC-07 / 10；ADR-005）。
- tools/create_quote + ops：写带幂等键与 X-Actor；结果未知同键核实一次；核实仍失败 → failed 并点名需人工核对的键；写不进只读重试（W2-AC-08 / 09；ADR-006）。
- tools/mcp_source + apps/mcp-erp-readonly：两个只读换成 MCP 来源，策略与事件不变（W2-AC-11）。
- 周 spec 两处复核改动：max_steps 8 → 12；search_customers 的 q 改可选（冒烟 Q04 / Q07 的证据在 smoke-20261107.md）。

验证命令、结果与证据位置：`make test` → 135 passed；契约 12 + 知识 4 + 写契约 4（私有 9177）+ MCP 4；冒烟 `docs/weeks/w02/smoke-20261107.md` 十条过（Q04 轨迹差异已记）；红绿 `increments.md`；故障卡 `faults.md`；`scripts/release_check.py --week w2` 通过。

已知限制或未覆盖情况：确认同步阻塞、不持久化、无跨进程核验（W5 / W6）；并发写 409 不处理；知识库无「报价规程 v2026.1」；W2-AC-12m 只有人工判定；Q04 类场景模型可能自行判定逾期不调 price_quote（规则结果一致，无 run.outcome）；MCP 只做了只读两工具，无凭据治理（W8）；独立变体发现写工具的业务去重只能在确认之后执行（预检归 W5）。

自审结论：合并。
