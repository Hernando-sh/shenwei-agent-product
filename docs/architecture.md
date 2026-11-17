# 架构

最终（W12）的一张图在课件 `S6/课件/W01-从需求到AgentLoop/arch.html`。W1 只做高亮部分：

```
CLI ──▶ AgentLoop ──▶ ModelClient（百炼 OpenAI 兼容）
            │  ├──▶ ContextBuilder（指令 + 历史 + 工具结果）
            │  ├──▶ ToolRegistry / Executor ──▶ guardrails（参数校验）──▶ tools/*（ERP 只读）──▶ ERP 9100
            │  └──▶ EventSink（JSONL 事件：请求快照、工具请求/结果、停止原因）
            └──▶ RunResult（状态、停止原因、答复）
```

| 组件 | 负责 | 不负责 |
|---|---|---|
| ModelClient | 请求与响应适配、协议错误 | 决定业务动作是否获准 |
| ToolRegistry / Executor | 查工具、验证参数、执行、返回带 call_id 的结果 | 生成最终答复 |
| AgentLoop | 推进一次执行、配对结果、判断继续 / 停止 | 知道某型号的价格与规格 |
| ContextBuilder | 指令、历史和工具结果的组装 | 保存权威库存 |
| EventSink | 记录执行事实与请求快照 | 生成模型内部推理 |
| CLI | 输入、输出、调用应用入口 | 实现另一份 Loop |

W2 在工具一侧展开（Loop 未改一行）：

```
AgentLoop ──▶ ToolRuntime（唯一管线）
                 解析 ──▶ 校验 guardrails（递归到报价行）──▶ 策略 policy/table（按名字；来源不参与）
                 ──▶ 确认决策：confirm → Changeset → ConfirmationAdapter（终端 LocalConfirm / 测试 ScriptedConfirm）→ 令牌校验（digest + 有效期）
                 ──▶ 执行：只读 tools/*（ERP、知识服务、MCP 来源 McpTool）有界重试；写 create_quote 带 Operation（幂等键）→ 未知结果同键核实一次
                 ──▶ 结果回注；事件：policy.decided / changeset.created / confirmation.* / operation.* / run.outcome；操作台账 ops/ledger
```

| 组件 | 负责 | 不负责 |
|---|---|---|
| policy.Policy / POLICY_TABLE | 按工具名给档位（read / write_internal / write_external）与两种模式下的动作 | 看参数内容；看来源宣告 |
| ToolRuntime | 管线顺序、确认环节、写操作标识与核实、业务结果事件 | 知道任何工具的业务含义（无 `if name ==`） |
| quote.rules / QuoteDraft | 算价前规则（blocked → credit_hold → overdue → duplicate）；草案只从 ERP 返回构造 | 算价、换算、折扣 |
| confirm.* | 变更集、令牌、终端确认 | 持久化与跨进程核验（W5） |
| ops.ledger | 写操作状态的追加记录 | 重试 |
| tools.mcp_source / apps/mcp-erp-readonly | 把 MCP 服务的工具变成本地 Tool；stdio 服务样本 | 策略、确认（都在调用方） |

对象语义（W1 最小）：Conversation 一段对话历史，可含多个 Run；Run 对一次新输入的执行（running / completed / failed / stopped）；Step 一次模型请求及其响应；Event 追加的执行记录。
