"""FakeKnowledge：按 (query, order_date) 返回录好的检索响应；记录每次请求体；可注入故障。实现 KnowledgeGateway。"""
from __future__ import annotations

import json
import pathlib
from collections import Counter
from dataclasses import dataclass, field

from agent_app.contracts import ToolFailure


def _key(query: str, order_date: str | None) -> tuple[str, str | None]:
    return (query, order_date)


@dataclass
class FakeKnowledge:
    responses: dict[tuple[str, str | None], dict] = field(default_factory=dict)
    index_version: str = "kb-fake"
    corpus_fingerprint: str = "fake"
    faults: dict[str, ToolFailure] = field(default_factory=dict)
    requests: list[dict] = field(default_factory=list)      # 每次 search 收到的请求体（和真实客户端发出的形状一致）
    calls: Counter = field(default_factory=Counter)

    def inject(self, method: str, failure: ToolFailure) -> None:
        self.faults[method] = failure

    def search(self, query: str, *, top_k: int = 5, domain: list[str] | None = None, doc_ids: list[str] | None = None,
               order_date: str | None = None, timeout_s: float) -> dict:
        self.calls["search"] += 1
        filters: dict = {}
        if domain:
            filters["domain"] = domain
        if doc_ids:
            filters["doc_ids"] = doc_ids
        if order_date:
            filters["order_date"] = order_date
        self.requests.append({"query": query, "top_k": top_k, "filters": filters})
        if "search" in self.faults:
            raise self.faults["search"]
        rec = self.responses.get(_key(query, order_date))
        if rec is None:                                   # 没录过的问题：如实空命中
            return {"query": query, "mode": "fake", "hits": [], "index_version": self.index_version,
                    "corpus_fingerprint": self.corpus_fingerprint}
        return json.loads(json.dumps(rec))

    @classmethod
    def from_fixtures(cls, fixtures_dir: str | pathlib.Path) -> "FakeKnowledge":
        """读 scripts/record_knowledge_fixtures.py 录下的 *.json；只装 200 的。"""
        kb = cls()
        for f in sorted(pathlib.Path(fixtures_dir).glob("*.json")):
            rec = json.loads(f.read_text(encoding="utf-8"))
            if "request" not in rec or rec["status"] != 200:
                continue
            body = rec["request"]["json"]
            kb.responses[_key(body["query"], (body.get("filters") or {}).get("order_date"))] = rec["body"]
            kb.index_version = rec["body"].get("index_version", kb.index_version)
            kb.corpus_fingerprint = rec["body"].get("corpus_fingerprint", kb.corpus_fingerprint)
        return kb
