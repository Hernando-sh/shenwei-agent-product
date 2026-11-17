"""search_knowledge：知识证据。权威事实 = 知识服务 /v1/search 返回的切块（资料原文的副本，带出处与版本）。
工具只整理字段：有命中给证据，没命中给空证据和一句说明；不生成、不概括、不补内容（W2-AC-03）。"""
from __future__ import annotations

from agent_app.contracts import KnowledgeGateway, ToolSpec

DOMAINS = ["product", "maintenance", "policy", "parts", "records", "export"]

SPEC = ToolSpec(
    name="search_knowledge",
    description=("在深维资料库里检索依据（政策规程、产品手册、配件与报价算例、出海经营资料）。返回每条证据的出处"
                 "（doc_id、clause、locator 页码）与适用范围（version、status、applies_to）。处理订单相关政策时带 order_date，"
                 "服务按下单日期选政策版本。evidence 为空表示资料里没有依据，此时如实说没有依据，不要自行补写。只读。"),
    parameters={"type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索语句，1–500 字"},
                    "domain": {"type": "array", "items": {"type": "string", "enum": DOMAINS},
                               "description": "可选，知识域：product / maintenance / policy / parts / records / export"},
                    "doc_ids": {"type": "array", "items": {"type": "string"}, "description": "可选，只在这几份资料里查，如 [\"D37\"]"},
                    "order_date": {"type": "string", "description": "可选，订单下单日期 YYYY-MM-DD；给出时按它选政策版本"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "description": "返回几条，默认 5"}},
                "required": ["query"], "additionalProperties": False},
)

NO_EVIDENCE = "资料里没有找到相关依据。请如实告知没有依据，不要补写规程或条款内容。"


class SearchKnowledge:
    spec = SPEC

    def __init__(self, kb: KnowledgeGateway) -> None:
        self._kb = kb

    def run(self, args: dict, *, timeout_s: float) -> dict:
        res = self._kb.search(args["query"], top_k=int(args.get("top_k") or 5), domain=args.get("domain"),
                              doc_ids=args.get("doc_ids"), order_date=args.get("order_date"), timeout_s=timeout_s)
        evidence = [{
            "chunk_id": h.get("chunk_id"), "doc_id": h.get("doc_id"), "doc_title": h.get("doc_title"),
            "clause": h.get("clause"), "locator": h.get("locator"),
            "version": h.get("version"), "status": h.get("status"), "applies_to": h.get("applies_to"),
            "domain": h.get("domain"), "text": h.get("text"), "score": h.get("score"),
        } for h in res.get("hits", [])]
        return {"query": args["query"], "mode": res.get("mode"), "index_version": res.get("index_version"),
                "corpus_fingerprint": res.get("corpus_fingerprint"), "count": len(evidence), "evidence": evidence,
                "note": None if evidence else NO_EVIDENCE}
