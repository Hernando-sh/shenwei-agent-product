"""从跑着的知识服务录 fixture：apps/agent-python/tests/fixtures/knowledge/<name>.json = 请求体 + 状态 + 响应体。
用法：uv run --project apps/agent-python python scripts/record_knowledge_fixtures.py [--base http://localhost:9200]
共享实例没有 Key 时是 keyword 模式；字段形状与 hybrid 相同，FakeKnowledge 只用字段，不用分数。"""
import argparse
import datetime as dt
import json
import pathlib
import sys

import httpx

CASES = [  # (文件名, 请求体)
    ("delay_refund_2025", {"query": "配送延迟多久可以申请全额退款", "top_k": 3,
                           "filters": {"domain": ["policy"], "order_date": "2025-06-01"}}),
    ("delay_refund_current", {"query": "配送延迟多久可以申请全额退款", "top_k": 3, "filters": {"domain": ["policy"]}}),
    ("quote_rule_v2026_1", {"query": "报价规程 v2026.1 第 3 条 客户等级系数", "top_k": 3}),
    ("quote_rule_parts", {"query": "报价规程 v2026.1 第 3 条", "top_k": 3, "filters": {"domain": ["parts"]}}),
    ("nonsense_empty", {"query": "qzxv", "top_k": 3}),
    ("empty_query_422", {"query": ""}),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:9200")
    ap.add_argument("--out", default=str(pathlib.Path(__file__).resolve().parents[1] / "apps/agent-python/tests/fixtures/knowledge"))
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=a.base, timeout=30) as c:
        health = c.get("/v1/health").json()
        (out / "health.json").write_text(json.dumps(health, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for name, body in CASES:
            r = c.post("/v1/search", json=body)
            rec = {"recorded_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
                   "index_version": health.get("index_version"), "corpus_fingerprint": health.get("corpus_fingerprint"),
                   "embedding_key_configured": health.get("embedding_key_configured"),
                   "request": {"method": "POST", "path": "/v1/search", "json": body},
                   "status": r.status_code, "body": r.json()}
            (out / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            hits = len(r.json().get("hits", [])) if r.status_code == 200 else "-"
            print(f"{r.status_code}  {name}  hits={hits}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
