# shenwei-agent-product

深维工作台（你的跨境数字员工）的课程参考实现。S6 十二周按周推进，一周一个大 tag `wN`，有代码增量的节一个小 tag `wN.k`。

本周（W1）：一条业务话推到一个运行时。CLI → AgentLoop → 模型 / 工具 / 上下文 → 两个 ERP 只读工具 → 事件日志。

## 起步

所有命令都在本仓库根目录执行，不用 cd 到别处（`make help` 看全部目标）。

```bash
cp .env.example .env            # 填 DASHSCOPE_API_KEY；离线用法不需要
make sync                       # 装 agent 依赖（Python 3.12 + uv）
make test                       # 离线单测：ScriptedModel + FakeERP，不需要 Key 和 ERP
make chat-offline               # 离线跑一轮，看 CLI 长什么样
```

接真实模型与 ERP（模拟 ERP 跑在 Docker 里，先装好并打开 Docker Desktop）：

```bash
make erp                        # 起模拟 ERP（9100，后台运行；make erp-stop 停）
make erp-check                  # 确认 9100 活着
make chat TEXT="查一下 X200 的规格和当前库存交期"
make replay ID=0ff66e93           # 上一步输出里 [conversation xxxxxxxx · run …] 的 xxxxxxxx
make integration                # 契约测试：需要 ERP，不可达自动跳过
```

模拟 ERP 是课程环境，不复制进本仓库，`make erp` 只是把 `S6/环境/docker-compose.yml`（即本仓库的 `../../环境`）里的 `shenwei-erp` 服务起起来。把它当黑盒用就行：接口文档在 http://localhost:9100/docs ，请求头带 `X-API-Key: east-demo-key`；想看它的数据表用 `make erp-tables` 和 `make erp-sql SQL="select * from shipments"`。课程环境目录不在默认位置时：`make erp ENV_DIR=/绝对路径/环境`。

不用 make 的话，等价的原始命令：`cd apps/agent-python && uv sync && uv run pytest tests/unit -q`，对话是 `uv run agent-cli chat "…"`，ERP 是 `cd ../../环境 && docker compose up -d shenwei-erp`。

完整命令、配置与已知限制见 `docs/releases/w1.md`；证据在 `docs/weeks/w01/`。

## 结构

见 `docs/architecture.md`。规格在 `docs/specs/`：`product.md` 是总 spec（PRD 的工程版），`w01-*.md` 是周 spec。AI coding 规则在 `AGENTS.md`。

## 本周 tag

| tag | 内容 |
|---|---|
| w1.4 | 仓库骨架、总 spec + 周 spec、ADR-001、AGENTS.md、CI 最小 |
| w1.5 | 契约类型、ScriptedModel、FakeERP、测试计划 |
| w1.6 | ModelClient、get_product_spec、get_availability、fixture 录制 |
| w1.7 | AgentLoop 增量 A–F |
| w1.8 | 预算、事件、回放、继续会话 |
| w1.9 | get_shipment、Release |
| w1 | 本周合并点 |
