"""T23–T25 · W2-AC-04 / 05：价格只由 ERP 算；草案字段可核对；前置规则（逾期 / 冻结 / 重复）由程序在算价前按固定顺序执行。
先红：没有 tools.price_quote / quote 包；FakeERP 没有 price_quote；guardrails 不检查嵌套对象的多余字段。"""
import json

import pytest

from agent_app.contracts import ToolCall, ToolFailure
from agent_app.doubles import FakeERP
from agent_app.quote import QuoteDraft, RULE_ORDER
from agent_app.tools import ToolExecutor, ToolRegistry
from agent_app.tools.price_quote import PriceQuote, SPEC as PRICE_SPEC

MONEY = {"unit_price", "amount", "discount", "total_amount", "price", "rate", "fx_rate"}
LINES_2 = [{"sku": "X200", "qty": 2}]


def _call(args, cid="call_1"):
    return ToolCall(call_id=cid, name="price_quote", arguments=args if isinstance(args, str) else json.dumps(args))


def _exec(erp, args):
    return ToolExecutor(ToolRegistry([PriceQuote(erp)])).execute(_call(args), timeout_s=1)


def _price_fixture(erp, customer_id, lines_key):
    rows = [{"sku": p.split(":")[0], "qty": p.split(":")[1]} for p in lines_key.split(",")]
    return erp.prices[(customer_id, FakeERP._lines_key(rows))]


# T23 · 报价工具没有自由金额参数；模型传金额 → guardrails unknown_field，ERP 计数 0
def _all_property_names(schema: dict) -> set[str]:
    names = set()
    for k, v in schema.get("properties", {}).items():
        names.add(k)
        if v.get("type") == "object":
            names |= _all_property_names(v)
        if v.get("type") == "array" and isinstance(v.get("items"), dict):
            names |= _all_property_names(v["items"])
    return names


def test_t23_price_quote_schema_has_no_money_fields():
    assert _all_property_names(PRICE_SPEC.parameters).isdisjoint(MONEY)
    assert PRICE_SPEC.parameters["additionalProperties"] is False
    assert PRICE_SPEC.parameters["properties"]["lines"]["items"]["additionalProperties"] is False


@pytest.mark.parametrize("args", [
    {"customer_id": "C-E001", "lines": LINES_2, "unit_price": 280},
    {"customer_id": "C-E001", "lines": [{"sku": "X200", "qty": 2, "unit_price": 280}]},
    {"customer_id": "C-E001", "lines": [{"sku": "X200", "qty": 2, "discount": 0.1}]},
    {"customer_id": "C-E001", "lines": LINES_2, "total_amount": 560},
])
def test_t23_money_in_arguments_is_rejected_before_erp(erp, args):
    r = _exec(erp, args)
    assert r.ok is False and r.error.category == "input_error" and r.error.code == "unknown_field"
    assert sum(erp.calls.values()) == 0


@pytest.mark.parametrize("args, code", [
    ({"customer_id": "C-E001"}, "missing_field"),
    ({"customer_id": "C-E001", "lines": []}, "empty_field"),
    ({"customer_id": "C-E001", "lines": [{"sku": "X200"}]}, "missing_field"),
    ({"customer_id": "C-E001", "lines": [{"sku": "X200", "qty": 0}]}, "out_of_range"),
    ({"customer_id": "C-E001", "lines": [{"sku": "X200", "qty": "2"}]}, "wrong_type"),
])
def test_t23_bad_lines_never_reach_erp(erp, args, code):
    r = _exec(erp, args)
    assert r.ok is False and r.error.category == "input_error" and r.error.code == code
    assert sum(erp.calls.values()) == 0


# T24 · 草案字段可核对：五类金额字段逐一等于 FakeERP price 返回；草案没有可被改写的金额入口
def test_t24_draft_money_fields_equal_erp_response(erp):
    r = _exec(erp, {"customer_id": "C-E001", "lines": LINES_2})
    assert r.ok and r.data["outcome"] == "draft" and r.data["rule"] is None
    d = r.data["draft"]
    p = _price_fixture(erp, "C-E001", "X200:2")
    assert d["total_amount"] == p["total_amount"] == 621.44 and d["currency"] == p["currency"] == "USD"
    assert d["payment_terms_code"] == p["payment_terms_code"] == "TT30_70" and d["incoterm"] == p["incoterm"]
    assert d["price_rule_ref"] == p["price_rule_ref"] and d["fx_rate"] == p["fx_rate"] and d["price_date"] == p["price_date"]
    for dl, pl in zip(d["lines"], p["lines"], strict=True):
        assert (dl["sku"], dl["qty"], dl["unit_price"], dl["amount"]) == (pl["sku"], pl["qty"], pl["unit_price"], pl["amount"])
        assert dl["conditions"] == pl["conditions"] and dl["list_price"] == pl["list_price"]
    assert d["recorded"] is False and "valid_until" not in d          # 草案阶段没有有效期日期（周 spec 第 3 节口径）
    assert erp.calls == {"get_customer": 1, "get_receivables": 1, "list_quotes": 1, "price_quote": 1}


def test_t24_multi_line_draft_total_comes_from_erp_not_from_summing(erp):
    r = _exec(erp, {"customer_id": "C-E001", "lines": [{"sku": "X200", "qty": 2}, {"sku": "S10", "qty": 4}]})
    d = r.data["draft"]
    p = _price_fixture(erp, "C-E001", "X200:2,S10:4")
    assert len(d["lines"]) == 2 and d["total_amount"] == p["total_amount"] == 861.68


def test_t24_quantity_discount_is_an_erp_condition_not_our_math(erp):
    r = _exec(erp, {"customer_id": "C-E001", "lines": [{"sku": "X200", "qty": 10}]})
    d = r.data["draft"]
    zqty = next(c for c in d["lines"][0]["conditions"] if c["type"] == "ZQTY")
    assert zqty["rate"] == 0.06 and d["total_amount"] == 2920.8


def test_t24_quote_draft_is_frozen_and_only_built_from_erp():
    import dataclasses
    assert dataclasses.is_dataclass(QuoteDraft) and QuoteDraft.__dataclass_params__.frozen
    assert hasattr(QuoteDraft, "from_erp") and not hasattr(QuoteDraft, "set_price")
    with pytest.raises(dataclasses.FrozenInstanceError):
        d = QuoteDraft.from_erp({"customer_id": "C-E001", "lines": [], "total_amount": 1.0, "currency": "USD"}, legal_name="x")
        d.total_amount = 0.5


def test_t24_draft_digest_changes_with_lines_not_with_wording(erp):
    a = _exec(erp, {"customer_id": "C-E001", "lines": LINES_2}).data["draft"]
    b = _exec(erp, {"customer_id": "C-E001", "lines": [{"sku": "X200", "qty": 10}]}).data["draft"]
    c = _exec(erp, {"customer_id": "C-E001", "lines": [{"sku": "x200", "qty": 2}]}).data["draft"]
    assert a["digest"] != b["digest"] and a["digest"] == c["digest"]


# T25 · 前置规则由程序执行：逾期 → 拦；有效期内同内容已有报价 → 拦；顺序固定；事实查不到 → 不出草案
def test_t25_rule_order_is_customer_status_then_duplicate_then_price():
    assert RULE_ORDER == ("blocked", "credit_hold", "overdue", "duplicate")


def test_t25_overdue_customer_gets_no_draft_with_days_and_amount(erp):
    r = _exec(erp, {"customer_id": "C-E003", "lines": [{"sku": "X300", "qty": 1}]})
    assert r.ok and r.data["outcome"] == "declined" and r.data["rule"] == "overdue" and r.data["draft"] is None
    assert r.data["facts"]["overdue_days"] == 23 and r.data["facts"]["overdue_amount"] == 18640.0
    assert erp.calls["price_quote"] == 0 and erp.calls["create_quote"] == 0


def test_t25_blocked_or_credit_hold_is_checked_before_overdue(erp):
    erp.customers["C-E001"] = {**erp.customers["C-E001"], "blocked": "all"}
    r = _exec(erp, {"customer_id": "C-E001", "lines": LINES_2})
    assert r.data["outcome"] == "declined" and r.data["rule"] == "blocked"
    assert erp.calls["get_receivables"] == 0 and erp.calls["price_quote"] == 0
    erp.customers["C-E001"] = {**erp.customers["C-E001"], "blocked": "none",
                               "credit": {**erp.customers["C-E001"]["credit"], "hold": True}}
    r = _exec(erp, {"customer_id": "C-E001", "lines": LINES_2})
    assert r.data["rule"] == "credit_hold"


def test_t25_valid_same_content_quote_blocks_duplicate_with_existing_id(erp):
    erp.quotes["QT-SEED-01"] = {"id": "QT-SEED-01", "customer_id": "C-E001", "revision": 1, "status": "issued",
                                "valid_until": "2026-10-18", "is_expired": False, "total_amount": 621.44, "currency": "USD",
                                "created_at": "2026-09-18T10:00:00+08:00",
                                "lines": [{"line_no": 1, "sku": "X200", "qty": 2}]}
    r = _exec(erp, {"customer_id": "C-E001", "lines": LINES_2})
    assert r.data["outcome"] == "declined" and r.data["rule"] == "duplicate"
    assert r.data["facts"]["existing_quote_id"] == "QT-SEED-01" and r.data["facts"]["valid_until"] == "2026-10-18"
    assert erp.calls["price_quote"] == 0
    # 行集合不同（10 台）不算重复；过期或改版的也不算
    assert _exec(erp, {"customer_id": "C-E001", "lines": [{"sku": "X200", "qty": 10}]}).data["outcome"] == "draft"
    erp.quotes["QT-SEED-01"]["is_expired"] = True
    assert _exec(erp, {"customer_id": "C-E001", "lines": LINES_2}).data["outcome"] == "draft"


def test_t25_overdue_wins_over_duplicate_only_first_reason_reported(erp):
    erp.quotes["QT-X"] = {"id": "QT-X", "customer_id": "C-E003", "status": "issued", "is_expired": False,
                          "valid_until": "2026-10-18", "lines": [{"sku": "X300", "qty": 1}]}
    r = _exec(erp, {"customer_id": "C-E003", "lines": [{"sku": "X300", "qty": 1}]})
    assert r.data["rule"] == "overdue" and erp.calls["list_quotes"] == 0


def test_t25_missing_rule_facts_means_no_draft_not_default_allow(erp):
    erp.inject("get_receivables", FakeERP.timeout("get_receivables"))
    r = _exec(erp, {"customer_id": "C-E001", "lines": LINES_2})
    assert r.ok is False and r.error.category == "timeout" and "不出草案" in r.error.message
    assert erp.calls["price_quote"] == 0
    erp2 = FakeERP.from_fixtures(__import__("pathlib").Path(__file__).resolve().parents[1] / "fixtures" / "erp")
    erp2.inject("list_quotes", ToolFailure("upstream_error", "internal_error", "场景注入"))
    r = _exec(erp2, {"customer_id": "C-E001", "lines": LINES_2})
    assert r.ok is False and r.error.category == "upstream_error" and erp2.calls["price_quote"] == 0


def test_t25_unknown_customer_is_not_found_and_no_price_call(erp):
    r = _exec(erp, {"customer_id": "C-E999", "lines": LINES_2})
    assert r.ok is False and r.error.category == "not_found" and erp.calls["price_quote"] == 0
