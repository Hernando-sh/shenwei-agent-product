"""W2 真实模型冒烟：十条案例（evals/datasets/w02-smoke.jsonl）。每条：按 seed 加载 ERP 场景（会重置账本）→ 跑 → 读账本 → 落盘。
确认用脚本化适配器（approve / reject / amend:qty=N），确认请求到来时先读一次账本（证明未确认前账本为空）。
人工判定另填 docs/weeks/w02/smoke-<date>.md。不混进单测。
用法：ERP_BASE_URL=http://localhost:9177 uv run --project apps/agent-python python scripts/smoke_w2.py [--only Q01,Q08] [--out …]
只对私有 ERP 实例跑：加载场景会重置它的账本。"""
import argparse
import datetime as dt
import json
import pathlib
import sys
import time

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/agent-python/src"))
from agent_app.agent import AgentLoop  # noqa: E402
from agent_app.config import Settings  # noqa: E402
from agent_app.contracts import Budget, Changeset, ConfirmToken  # noqa: E402
from agent_app.llm import DashScopeClient  # noqa: E402
from agent_app.observability import JsonlSink, read_events  # noqa: E402
from agent_app.ops import JsonlLedger  # noqa: E402
from agent_app.policy import Policy  # noqa: E402
from agent_app.tools import ToolRegistry, ToolRuntime  # noqa: E402
from agent_app.tools.availability import GetAvailability  # noqa: E402
from agent_app.tools.create_quote import CreateQuote  # noqa: E402
from agent_app.tools.customer import GetCustomer, SearchCustomers  # noqa: E402
from agent_app.tools.erp_client import ErpClient  # noqa: E402
from agent_app.tools.knowledge import SearchKnowledge  # noqa: E402
from agent_app.tools.knowledge_client import KnowledgeClient  # noqa: E402
from agent_app.tools.order import GetOrder  # noqa: E402
from agent_app.tools.price_quote import PriceQuote  # noqa: E402
from agent_app.tools.product import GetProductSpec  # noqa: E402
from agent_app.tools.quotes import ListQuotes  # noqa: E402
from agent_app.tools.receivables import GetReceivables  # noqa: E402
from agent_app.tools.shipment import GetShipment  # noqa: E402

ADMIN = {"X-Admin-Token": "local-admin"}
KEY = {"X-Api-Key": "east-demo-key"}


def ledger(base):
    d = httpx.get(f"{base}/_admin/ledger", headers=ADMIN, timeout=5).json()
    return {"quotes": [{"id": q.get("id"), "customer_id": q.get("customer_id"), "lines": [{"sku": l["sku"], "qty": l["qty"]} for l in q.get("lines", [])],
                        "total_amount": q.get("total_amount"), "currency": q.get("currency"), "valid_until": q.get("valid_until"),
                        "status": q.get("status"), "created_by": q.get("created_by")} for q in d.get("quotes", [])],
            "violations": d.get("violations", []),
            "write_requests": [{"path": r.get("path"), "status": r.get("status"), "fault": r.get("fault"), "actor": r.get("actor")}
                               for r in d.get("requests", []) if r.get("method") == "POST"]}


class SmokeConfirm:
    """按案例给决定；每次确认请求先快照账本。amend 只用一次，之后同意。"""

    def __init__(self, base, decision: str | None, actor="sales:zhou"):
        self.base, self.decision, self.actor = base, decision, actor
        self.snapshots, self.changesets, self.amended = [], [], False

    def request(self, cs: Changeset, *, ttl_s: float) -> ConfirmToken:
        self.snapshots.append(ledger(self.base)["quotes"])
        self.changesets.append(cs.to_event())
        now = time.time()
        d = self.decision or "approve"
        if d.startswith("amend:") and not self.amended:
            self.amended = True
            k, v = d.split(":", 1)[1].split("=")
            lines = [{**l, "qty": int(v)} for l in cs.args.get("lines", [])] if k == "qty" else cs.args.get("lines")
            return ConfirmToken("amend", cs.operation_id, cs.digest, now, self.actor, amended_args={"lines": lines})
        if d == "reject":
            return ConfirmToken("reject", cs.operation_id, cs.digest, now, self.actor, note="业务员取消")
        return ConfirmToken("approve", cs.operation_id, cs.digest, now, self.actor)


def load_scenario(base, case):
    seed = case.get("seed") or {}
    body = {"case_id": f"w2-smoke-{case['id']}", "base": True}
    if "fault" in seed:
        body["faults"] = [seed["fault"]]
    if "quotes" in seed:
        body["quotes"] = seed["quotes"]
    if "orders" in seed:                                               # 部分字段覆盖会丢掉其余字段：先取基础对象再改
        full = []
        for o in seed["orders"]:
            cur = httpx.get(f"{base}/v1/orders/{o['id']}", headers=KEY, timeout=5).json()
            full.append({**cur, **o})
        body["orders"] = full
    httpx.post(f"{base}/_admin/reset", headers=ADMIN, timeout=5).raise_for_status()
    httpx.post(f"{base}/_admin/scenario", json=body, headers=ADMIN, timeout=10).raise_for_status()


def build_tools(s, erp, kb, source):
    if source == "mcp":
        from agent_app.tools.mcp_source import McpToolSource, StdioMcpClient
        client = StdioMcpClient(sys.executable, [str(ROOT / "apps/mcp-erp-readonly/server.py")], name="erp-readonly",
                                env={"ERP_BASE_URL": s.erp_base_url, "ERP_API_KEY": s.erp_api_key})
        read = McpToolSource(client).tools(only=["get_product_spec", "get_availability"])
    else:
        client, read = None, [GetProductSpec(erp), GetAvailability(erp)]
    return client, [*read, GetShipment(erp), GetOrder(erp), SearchCustomers(erp), GetCustomer(erp), GetReceivables(erp),
                    ListQuotes(erp), SearchKnowledge(kb), PriceQuote(erp), CreateQuote(erp)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "evals/runs" / f"w02-smoke-{dt.date.today():%Y%m%d}"))
    ap.add_argument("--only", default="")
    ap.add_argument("--max-steps", type=int, default=12)
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    s = Settings.from_env()
    if s.erp_base_url.endswith(":9100"):
        print("拒绝对共享实例 9100 跑冒烟（会重置账本）；设 ERP_BASE_URL 指向私有实例", file=sys.stderr)
        return 2
    cases = [json.loads(l) for l in (ROOT / "evals/datasets/w02-smoke.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    only = {x for x in a.only.split(",") if x}
    budget = Budget(max_steps=a.max_steps)
    config = {"model": s.model, "budget": budget.__dict__, "erp": s.erp_base_url, "kb": s.kb_base_url,
              "erp_health": httpx.get(f"{s.erp_base_url}/health", timeout=3).json(),
              "kb_health": httpx.get(f"{s.kb_base_url}/v1/health", timeout=3).json(),
              "ran_at": dt.datetime.now().astimezone().isoformat(timespec="seconds")}
    (out / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    results = []
    for c in cases:
        if only and c["id"] not in only:
            continue
        load_scenario(s.erp_base_url, c)
        for f in (out / f"{c['id']}.events.jsonl", out / f"{c['id']}.operations.jsonl"):
            f.unlink(missing_ok=True)                                   # 事件文件是追加写：同目录重跑先清旧的
        erp = ErpClient(s.erp_base_url, s.erp_api_key)
        kb = KnowledgeClient(s.kb_base_url)
        model = DashScopeClient(s.dashscope_api_key, s.model, s.model_base_url)
        mcp_client, tools = build_tools(s, erp, kb, c.get("source", "local"))
        reg = ToolRegistry(tools)
        sink = JsonlSink(out / f"{c['id']}.events.jsonl")
        confirm = SmokeConfirm(s.erp_base_url, c.get("confirm"))
        rt = ToolRuntime(reg, policy=Policy(), sink=sink, mode=c.get("mode", "ask"), confirmer=confirm,
                         ledger=JsonlLedger(out / f"{c['id']}.operations.jsonl"))
        loop = AgentLoop(model, rt, reg.specs(), sink=sink, budget=budget)
        t0 = time.time()
        r = loop.run(c["input"], run_id=c["id"])
        elapsed = round(time.time() - t0, 1)
        if mcp_client:
            mcp_client.close()
        events, _ = read_events(sink.path)
        traj = [{"name": e["name"], "arguments": e["arguments"]} for e in events if e["type"] == "tool.requested"]
        outcomes = [{"name": e["name"], "type": e["type"], "ok": e.get("ok"), "category": e.get("category"), "code": e.get("code"),
                     "reason": e.get("reason")} for e in events if e["type"] in ("tool.executed", "tool.rejected")]
        requests_text = json.dumps([e for e in events if e["type"] == "tool.requested"], ensure_ascii=False)
        rec = {"id": c["id"], "case_ref": c.get("case_ref"), "kind": c["kind"], "mode": c.get("mode"), "source": c.get("source", "local"),
               "input": c["input"], "confirm": c.get("confirm"),
               "status": r.status, "stop_reason": r.stop_reason, "steps": r.steps, "elapsed_s": elapsed,
               "usage": r.usage.__dict__, "trajectory": traj, "outcomes": outcomes,
               "events_of_interest": [e["type"] for e in events if e["type"].startswith(("policy.", "changeset.", "confirmation.", "operation.", "run.outcome", "mode."))],
               "run_outcome": next((e["outcome"] for e in events if e["type"] == "run.outcome"), None),
               "changesets": confirm.changesets, "ledger_before_confirm": confirm.snapshots,
               "ledger_after": ledger(s.erp_base_url), "answer": r.answer,
               "forbidden_hits": [x for x in c["expect"].get("forbidden_in_requests", []) if x in requests_text],
               "expect": c["expect"], "judgement": None}
        results.append(rec)
        print(f"{c['id']} {c['kind']}: {r.status} {r.steps} 步 {elapsed}s outcome={rec['run_outcome']} "
              f"{[t['name'] for t in traj]} 账本 {len(rec['ledger_after']['quotes'])} 条 → {(r.answer or '')[:80]}")
    (out / "results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in results), encoding="utf-8")
    httpx.post(f"{s.erp_base_url}/_admin/reset", headers=ADMIN, timeout=5)
    print(f"写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
