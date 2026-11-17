"""T16 · W2-AC-01：四个只读工具（search_customers / get_customer / get_receivables / list_quotes）的结果可区分：
正常 / 空结果 / 拒绝 / 失败。先红：工具模块不存在，FakeERP 没有客户与台账表，ErpClient 把 401 归成 upstream_error。"""
import json

import httpx
import pytest

from agent_app.contracts import ToolCall, ToolFailure
from agent_app.doubles import FakeERP
from agent_app.tools import ToolExecutor, ToolRegistry
from agent_app.tools.customer import GetCustomer, SearchCustomers
from agent_app.tools.erp_client import ErpClient
from agent_app.tools.quotes import ListQuotes
from agent_app.tools.receivables import GetReceivables


def _executor(erp):
    return ToolExecutor(ToolRegistry([SearchCustomers(erp), GetCustomer(erp), GetReceivables(erp), ListQuotes(erp)]))


def _call(name, args, cid="call_1"):
    return ToolCall(call_id=cid, name=name, arguments=args if isinstance(args, str) else json.dumps(args))


def _problem(status, code, detail="x"):
    return httpx.Response(status, json={"code": code, "detail": detail, "status": status, "title": "t"},
                          headers={"content-type": "application/problem+json"})


def _erp_with(handler):
    return ErpClient("http://erp.test", "east-demo-key", transport=httpx.MockTransport(handler))


# ---- 正常：四个工具都返回 ok=True，字段来自 fixture ----
def test_t16_search_customers_returns_candidates_from_fixture(erp):
    r = _executor(erp).execute(_call("search_customers", {"q": "Jakarta"}), timeout_s=1)
    assert r.ok and r.data["count"] == 1
    c = r.data["customers"][0]
    assert (c["id"], c["legal_name"], c["city"], c["country_code"], c["price_group"]) == \
           ("C-E001", "PT Nusantara Process Engineering", "Jakarta", "ID", "B")
    assert erp.calls["search_customers"] == 1


def test_t16_search_by_country_code_only_lists_that_country(erp):
    """冒烟 Q04 的教训：业务员说「杜塞尔多夫」，ERP 存的是 Düsseldorf；按国家列候选不依赖拼写。"""
    r = _executor(erp).execute(_call("search_customers", {"country_code": "DE"}), timeout_s=1)
    assert r.ok and [c["id"] for c in r.data["customers"]] == ["C-E003"] and r.data["query"] is None


def test_t16_search_customers_filters_by_country_code(erp):
    r = _executor(erp).execute(_call("search_customers", {"q": "Rheinwerk", "country_code": "DE"}), timeout_s=1)
    assert r.ok and [c["id"] for c in r.data["customers"]] == ["C-E003"]
    r = _executor(erp).execute(_call("search_customers", {"q": "Rheinwerk", "country_code": "ID"}), timeout_s=1)
    assert r.ok and r.data["customers"] == []


def test_t16_get_customer_carries_credit_and_terms(erp):
    r = _executor(erp).execute(_call("get_customer", {"customer_id": "C-E001"}), timeout_s=1)
    assert r.ok
    d = r.data
    assert d["customer_id"] == "C-E001" and d["payment_terms_code"] == "TT30_70"
    assert d["incoterm_default"] == {"code": "FOB", "location": "Shenzhen"} and d["blocked"] == "none"
    assert d["credit"]["status"] == "clear" and d["credit"]["hold"] is False and d["credit"]["overdue_amount"] == 0
    assert d["credit"]["available_credit"] == 19328.92


def test_t16_get_receivables_overdue_customer(erp):
    r = _executor(erp).execute(_call("get_receivables", {"customer_id": "C-E003"}), timeout_s=1)
    assert r.ok
    d = r.data
    assert d["credit_status"] == "overdue" and d["overdue_days"] == 23 and d["overdue_amount"] == 18640.0
    assert d["currency"] == "USD" and d["aging"]["d1_30"] == 18640.0 and len(d["open_items"]) == 2
    assert d["observed_at"] == "2026-09-20T10:00:00+08:00"


# ---- 空结果是成功且数据为空，不是 not_found ----
def test_t16_empty_search_is_ok_with_empty_list_not_not_found(erp):
    r = _executor(erp).execute(_call("search_customers", {"q": "Singapore"}), timeout_s=1)
    assert r.ok is True and r.data["customers"] == [] and r.data["count"] == 0
    body = json.loads(r.content())
    assert body["ok"] is True and "error" not in body


def test_t16_no_quotes_is_ok_with_empty_list(erp):
    r = _executor(erp).execute(_call("list_quotes", {"customer_id": "C-E001"}), timeout_s=1)
    assert r.ok is True and r.data["quotes"] == [] and r.data["count"] == 0
    assert erp.calls["list_quotes"] == 1


def test_t16_seeded_quote_is_listed_with_validity_fields(erp):
    erp.quotes["QT-SEED-01"] = {"id": "QT-SEED-01", "customer_id": "C-E001", "revision": 1, "status": "issued",
                                "valid_until": "2026-10-18", "is_expired": False, "total_amount": 621.44,
                                "currency": "USD", "created_at": "2026-09-18T10:00:00+08:00",
                                "lines": [{"line_no": 1, "sku": "X200", "qty": 2, "unit_price": 310.72, "amount": 621.44}]}
    r = _executor(erp).execute(_call("list_quotes", {"customer_id": "C-E001"}), timeout_s=1)
    assert r.ok and r.data["count"] == 1
    q = r.data["quotes"][0]
    assert (q["quote_id"], q["status"], q["valid_until"], q["is_expired"]) == ("QT-SEED-01", "issued", "2026-10-18", False)
    assert q["lines"] == [{"sku": "X200", "qty": 2}]
    r = _executor(erp).execute(_call("list_quotes", {"customer_id": "C-E003"}), timeout_s=1)
    assert r.ok and r.data["quotes"] == []


# ---- 拒绝：401 是 rejected/unauthorized，不是客户不存在；跨租户 404 是 not_found ----
def test_t16_unauthorized_is_rejected_not_not_found():
    def handler(request):
        return _problem(401, "unauthorized", "缺少或无效的 X-Api-Key")
    r = _executor(_erp_with(handler)).execute(_call("get_customer", {"customer_id": "C-E001"}), timeout_s=1)
    assert r.ok is False and r.error.category == "rejected" and r.error.code == "unauthorized"


def test_t16_cross_tenant_404_is_not_found(erp):
    r = _executor(erp).execute(_call("get_customer", {"customer_id": "C-E999"}), timeout_s=1)
    assert r.ok is False and r.error.category == "not_found" and r.error.code == "customer_not_found"
    r = _executor(erp).execute(_call("get_receivables", {"customer_id": "C-E999"}), timeout_s=1)
    assert r.error.category == "not_found"


def test_t16_fake_erp_can_inject_rejection(erp):
    erp.inject("get_customer", ToolFailure("rejected", "unauthorized", "缺少或无效的 X-Api-Key"))
    r = _executor(erp).execute(_call("get_customer", {"customer_id": "C-E001"}), timeout_s=1)
    assert r.error.category == "rejected" and erp.calls["get_customer"] == 1


# ---- 失败：504 → timeout；5xx → upstream_error；都不伪装成空结果 ----
def test_t16_gateway_timeout_on_list_is_timeout_not_empty_list():
    def handler(request):
        return _problem(504, "gateway_timeout", "场景注入超时")
    r = _executor(_erp_with(handler)).execute(_call("list_quotes", {"customer_id": "C-E001"}), timeout_s=1)
    assert r.ok is False and r.error.category == "timeout"
    assert "quotes" not in r.content()


def test_t16_server_error_is_upstream_error():
    def handler(request):
        return _problem(500, "internal_error", "场景注入错误")
    r = _executor(_erp_with(handler)).execute(_call("search_customers", {"q": "Jakarta"}), timeout_s=1)
    assert r.ok is False and r.error.category == "upstream_error" and r.error.code == "internal_error"


# ---- 输入边界：空参数不触发 ERP ----
@pytest.mark.parametrize("name, args", [
    ("search_customers", {}), ("search_customers", {"q": " "}), ("search_customers", {"country_code": ""}),
    ("get_customer", {"customer_id": ""}), ("get_receivables", {}), ("list_quotes", {"customer_id": 1}),
])
def test_t16_bad_input_never_reaches_erp(erp, name, args):
    r = _executor(erp).execute(_call(name, args), timeout_s=1)
    assert r.ok is False and r.error.category == "input_error"
    assert sum(erp.calls.values()) == 0


# ---- 真实客户端的请求形状：查询串与路径按接口说明 ----
def test_t16_client_sends_documented_paths_and_params():
    seen = []

    def handler(request):
        seen.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, json={"data": [], "has_more": False, "next_cursor": None})
    c = _erp_with(handler)
    c.search_customers("Jakarta", country_code="ID", timeout_s=1)
    c.search_customers(None, country_code="DE", timeout_s=1)
    c.list_quotes("C-E001", timeout_s=1)
    assert seen == [("/v1/customers", {"q": "Jakarta", "country_code": "ID"}), ("/v1/customers", {"country_code": "DE"}),
                    ("/v1/quotes", {"customer_id": "C-E001"})]
