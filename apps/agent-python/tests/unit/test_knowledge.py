"""T21–T22 · W2-AC-03：知识证据带出处与版本；空命中返回空证据不生成内容；order_date 原样透传。
先红：没有 KnowledgeClient / SearchKnowledge / FakeKnowledge。"""
import json
import pathlib

import httpx
import pytest

from agent_app.contracts import ToolCall
from agent_app.doubles import FakeKnowledge
from agent_app.tools import ToolExecutor, ToolRegistry
from agent_app.tools.knowledge import SearchKnowledge
from agent_app.tools.knowledge_client import KnowledgeClient

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "knowledge"


@pytest.fixture
def kb() -> FakeKnowledge:
    return FakeKnowledge.from_fixtures(FIX)


def _call(args, cid="call_1"):
    return ToolCall(call_id=cid, name="search_knowledge", arguments=json.dumps(args, ensure_ascii=False))


def _exec(kb, args):
    return ToolExecutor(ToolRegistry([SearchKnowledge(kb)])).execute(_call(args), timeout_s=1)


# T21 · 空证据不编造：hits 为空 → ok=True、evidence=[]、note 说明无依据；工具不调模型、不补内容
def test_t21_empty_hits_is_ok_with_empty_evidence_and_a_note(kb):
    r = _exec(kb, {"query": "qzxv"})
    assert r.ok is True and r.data["evidence"] == [] and r.data["count"] == 0
    assert "没有找到" in r.data["note"]
    body = json.loads(r.content())
    assert body["ok"] is True and body["data"]["evidence"] == [] and "error" not in body
    assert kb.calls["search"] == 1


def test_t21_tool_never_adds_text_that_is_not_in_a_hit(kb):
    r = _exec(kb, {"query": "配送延迟多久可以申请全额退款", "domain": ["policy"]})
    assert r.ok and r.data["count"] == 3
    for ev in r.data["evidence"]:
        assert ev["text"] and ev["doc_id"].startswith("D") and ev["chunk_id"]
    # 证据之外没有别的正文字段
    assert set(r.data) == {"query", "mode", "index_version", "corpus_fingerprint", "count", "evidence", "note"}


def test_t21_evidence_carries_source_and_version_fields(kb):
    r = _exec(kb, {"query": "配送延迟多久可以申请全额退款", "domain": ["policy"]})
    ev = r.data["evidence"][0]
    assert {"chunk_id", "doc_id", "doc_title", "clause", "locator", "version", "status", "applies_to", "domain", "text",
            "score"} <= set(ev)
    assert ev["doc_id"] == "D37" and ev["version"] == "2026版" and ev["status"] == "current"
    assert ev["applies_to"] == {"order_date": {"from": "2026-01-01"}} and ev["locator"]["page"] == 8
    assert r.data["index_version"] == "kb-20261024" and r.data["corpus_fingerprint"] == "d60a1a5ee5631da1"


# T22 · 版本条件透传：参数 order_date 原样进请求体 filters；返回的是对该日期有效的那一版
def test_t22_order_date_is_passed_through_to_filters(kb):
    r = _exec(kb, {"query": "配送延迟多久可以申请全额退款", "domain": ["policy"], "order_date": "2025-06-01"})
    assert kb.requests[-1]["filters"]["order_date"] == "2025-06-01"
    assert kb.requests[-1]["filters"]["domain"] == ["policy"] and kb.requests[-1]["query"] == "配送延迟多久可以申请全额退款"
    ev = r.data["evidence"][0]
    assert (ev["doc_id"], ev["version"], ev["status"]) == ("D38", "2025版", "superseded")
    assert ev["applies_to"] == {"order_date": {"to": "2025-12-31"}}


def test_t22_without_order_date_filters_has_no_order_date_key(kb):
    _exec(kb, {"query": "配送延迟多久可以申请全额退款", "domain": ["policy"]})
    assert "order_date" not in kb.requests[-1]["filters"]


def test_t22_real_client_sends_documented_body():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"query": "q", "mode": "hybrid", "hits": [], "index_version": "kb-x",
                                         "corpus_fingerprint": "f"})
    c = KnowledgeClient("http://kb.test", transport=httpx.MockTransport(handler))
    c.search("退款", top_k=3, domain=["policy"], doc_ids=["D37", "D38"], order_date="2026-09-12", timeout_s=1)
    assert seen == [{"query": "退款", "top_k": 3, "filters": {"domain": ["policy"], "doc_ids": ["D37", "D38"],
                                                                "order_date": "2026-09-12"}}]


# 失败分类：超时 / 5xx / 非 JSON 都不是"没有依据"
def test_t22_failures_are_not_empty_evidence():
    def timeout(request):
        raise httpx.ReadTimeout("t", request=request)
    r = ToolExecutor(ToolRegistry([SearchKnowledge(KnowledgeClient("http://kb.test", transport=httpx.MockTransport(timeout)))])) \
        .execute(_call({"query": "退款"}), timeout_s=0.5)
    assert r.ok is False and r.error.category == "timeout" and "evidence" not in r.content()

    def malformed(request):
        return httpx.Response(200, content=b"<html>", headers={"content-type": "application/json"})
    r = ToolExecutor(ToolRegistry([SearchKnowledge(KnowledgeClient("http://kb.test", transport=httpx.MockTransport(malformed)))])) \
        .execute(_call({"query": "退款"}), timeout_s=0.5)
    assert r.ok is False and r.error.category == "malformed"


def test_t22_bad_input_never_reaches_service(kb):
    for args in ({}, {"query": ""}, {"query": "退款", "top_k": 0}, {"query": "退款", "unit_price": 1}):
        r = _exec(kb, args)
        assert r.ok is False and r.error.category == "input_error"
    assert kb.calls["search"] == 0
