# 在仓库根目录统一起环境、跑测试、跑 agent。所有目标都不要求你 cd 到别处。
#   make help            看全部目标
#   make erp             起模拟 ERP（9100，Docker 后台运行；make erp-stop 停）
#   make sync test       装依赖、跑离线单测
#   make chat TEXT="查一下 X200 的规格和当前库存交期"
#
# 模拟 ERP 是课程环境，跑在 Docker 里（S6/环境/docker-compose.yml 的 shenwei-erp 服务），不复制进本仓库。
# 把它当黑盒：make erp 起、make erp-stop 停、make erp-check 看活没活、make erp-sql 查它的数据表。
# 前提只有一个：装好并打开 Docker Desktop。课程环境目录不在默认位置时：make erp ENV_DIR=/绝对路径/环境

APP      := apps/agent-python
ENV_DIR  ?= $(CURDIR)/../../环境
ERP_URL  ?= http://localhost:9100
ERP_SVC  := shenwei-erp
COMPOSE  := docker compose --project-directory "$(ENV_DIR)"
KB_URL   ?= http://localhost:9200
TEXT     ?= 查一下 X200 的规格和当前库存交期
ARGS     ?=

.PHONY: help sync test integration erp-env erp erp-stop erp-check erp-logs erp-sql erp-tables chat chat-offline replay fixtures kb-fixtures model-samples smoke-w2 clean

help:
	@echo "环境"
	@echo "  make erp              起模拟 ERP（Docker 后台运行，9100；课程环境 $(ENV_DIR)）"
	@echo "  make erp-stop         停掉模拟 ERP"
	@echo "  make erp-check        看 ERP 9100 是否活着"
	@echo "  make erp-logs         看 ERP 日志（Ctrl-C 退出）"
	@echo "  make erp-tables       列出 ERP 数据库里的表"
	@echo "  make erp-sql SQL=\"select * from shipments\"   只读查询 ERP 的数据表"
	@echo "  make sync             装 agent 依赖（Python 3.12 + uv）"
	@echo "测试"
	@echo "  make test             离线单测：ScriptedModel + FakeERP"
	@echo "  make integration      契约测试：需要 ERP 9100，不可达自动跳过"
	@echo "运行"
	@echo "  make chat TEXT=\"…\" [ARGS=\"-v\"]   真实模型 + 真实 ERP（需要 .env 里的 DASHSCOPE_API_KEY）；-v 展开工具结果"
	@echo "  make chat-offline     离线脚本跑一轮，不需要 Key 和 ERP（TEXT 含「报」走报价脚本，会在终端问确认）"
	@echo "  make chat ARGS=\"--source mcp\" TEXT=\"…\"   规格 / 库存两个只读工具改走 MCP 服务（apps/mcp-erp-readonly，stdio）"
	@echo "  make chat ARGS=\"--mode auto\" TEXT=\"…\"    自动模式（内部写不问；报价台账写入仍确认）"
	@echo "  make replay ID=<会话id>                       只读回放"
	@echo "录制"
	@echo "  make fixtures         从 ERP 9100 重录 tests/fixtures/erp/*.json（先 POST /_admin/reset）"
	@echo "  make kb-fixtures      从知识服务 9200 重录 tests/fixtures/knowledge/*.json"
	@echo "  make model-samples    从真实模型重录 tests/fixtures/model/*.json"
	@echo "冒烟"
	@echo "  make smoke-w2 ERP_URL=http://localhost:9177   十条真实模型案例（只对私有 ERP：会重置它的账本）"

# ---- 环境 ----
sync:
	cd $(APP) && uv sync

# 四个 ERP 目标共用的前置检查：课程环境目录在、Docker 在跑
erp-env:
	@test -f "$(ENV_DIR)/docker-compose.yml" || { echo "找不到课程环境：$(ENV_DIR)/docker-compose.yml（用 ENV_DIR=/绝对路径/环境 指定）"; exit 1; }
	@docker info >/dev/null 2>&1 || { echo "Docker 没有在运行：先打开 Docker Desktop，等它就绪后再试"; exit 1; }

erp: erp-env
	@$(COMPOSE) up -d $(ERP_SVC)
	@for i in $$(seq 1 30); do curl -sf -m 1 $(ERP_URL)/health >/dev/null 2>&1 && break; sleep 1; done; \
	  $(MAKE) -s erp-check

erp-stop: erp-env
	@$(COMPOSE) stop $(ERP_SVC)

erp-check:
	@curl -sf -m 2 $(ERP_URL)/health | python3 -c 'import json,sys; d=json.load(sys.stdin); print("ERP {status} · {service} {version} · 场景 {scenario} · 系统时间 {now} · $(ERP_URL)".format(**d))' \
	  || { echo "ERP $(ERP_URL) 不可达：先 make erp"; exit 1; }

erp-logs: erp-env
	@$(COMPOSE) logs -f --tail=100 $(ERP_SVC)

# 只读查询容器里的 ERP 数据库（/data/erp.db）。容器镜像没有 sqlite3 命令，用它自带的 python 查。
# 多列结果每列截到 60 字符；想看完整的长字段（如 shipments.events）就只选那一列，单列不截断、JSON 自动展开。
define ERP_SQL_PY
import json, os, sqlite3, sys
db = sqlite3.connect('file:' + os.environ['ERP_DB'] + '?mode=ro', uri=True)
cur = db.execute(sys.argv[1])
cols = [d[0] for d in (cur.description or [])]
rows = [['' if v is None else str(v) for v in r] for r in cur.fetchall()]
if not cols:
    print('（没有结果列）'); sys.exit()
def pretty(v):
    try:
        return json.dumps(json.loads(v), ensure_ascii=False, indent=2) if v[:1] in '[{' else v
    except ValueError:
        return v
if len(cols) == 1:
    # 单列：不截断；JSON 字段（如 shipments.events）按行展开
    print(cols[0]); print('-' * max(4, len(cols[0])))
    for r in rows: print(pretty(r[0]))
else:
    # 多列：每列最多 60 字符，方便对齐；要看长字段就只选那一列
    w = [min(60, max([len(c)] + [len(r[i]) for r in rows])) for i, c in enumerate(cols)]
    line = lambda r: '  '.join(v[:60].ljust(w[i]) for i, v in enumerate(r))
    print(line(cols)); print('  '.join('-' * x for x in w))
    for r in rows: print(line(r))
print('(' + str(len(rows)) + ' 行)')
endef
export ERP_SQL_PY

erp-sql: erp-env
	@test -n "$(SQL)" || { echo '用法：make erp-sql SQL="select tracking_no, order_id, ship_date from shipments"'; exit 1; }
	@$(COMPOSE) exec -T $(ERP_SVC) python -c "$$ERP_SQL_PY" "$(SQL)" \
	  || { echo "查询失败：ERP 容器在跑吗？先 make erp"; exit 1; }

erp-tables:
	@$(MAKE) -s erp-sql SQL="select name as 表名 from sqlite_master where type='table' order by name"

# ---- 测试 ----
test:
	@cd $(APP) && uv run -q pytest tests/unit -q

integration:
	@cd $(APP) && uv run -q pytest tests/integration -q

# ---- 运行 ----
# runs/ 落在 apps/agent-python/runs（AGENT_RUNS_DIR 相对于进程的 cwd）
chat:
	@cd $(APP) && AGENT_VIA_MAKE=1 uv run -q agent-cli chat $(ARGS) "$(TEXT)"

chat-offline:
	@cd $(APP) && AGENT_VIA_MAKE=1 uv run -q agent-cli chat --scripted $(ARGS) "$(TEXT)"

replay:
	@test -n "$(ID)" || { echo "用法：make replay ID=<会话id>（会话目录在 $(APP)/runs/）"; exit 1; }
	@cd $(APP) && uv run -q agent-cli replay $(ID)

# ---- 录制 ----
fixtures:
	uv run --project $(APP) python scripts/record_fixtures.py --base $(ERP_URL)

kb-fixtures:
	uv run --project $(APP) python scripts/record_knowledge_fixtures.py --base $(KB_URL)

model-samples:
	uv run --project $(APP) python scripts/record_model_samples.py

smoke-w2:
	ERP_BASE_URL=$(ERP_URL) uv run --project $(APP) python scripts/smoke_w2.py

clean:
	rm -rf $(APP)/.pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
