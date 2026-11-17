"""契约测试：跑着的 ERP 与录下的 fixture 字段一致。ERP 不可达时跳过（CI 里不跑）。
地址默认 9100，私有实例用 ERP_BASE_URL=http://localhost:9177 覆盖；W2 起列表接口比 data 第一条的字段。"""
import json
import os
import pathlib

import httpx
import pytest

# cache: 02Cbf 01Qae
FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "erp"
BASE = os.environ.get("ERP_BASE_URL", "http://localhost:9100")


def _alive():
    try:
        return httpx.get(f"{BASE}/health", timeout=1).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _alive(), reason="ERP 9100 不可达")


def _get(rec):
    headers = {"X-Api-Key": "east-demo-key", **rec["request"].get("headers", {})}
    return httpx.get(BASE + rec["request"]["path"], params=rec["request"]["query"], headers=headers, timeout=3)


@pytest.mark.parametrize("name", ["products_X200", "inventory_X200_qty2", "shipments_SF1234567890", "orders_ORD-10086",
                                  "customers_C-E001", "receivables_C-E003", "quotes_price_C-E001_X200x2"])
def test_live_erp_has_same_fields_as_fixture(name):
    rec = json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))
    r = _get(rec)
    assert r.status_code == rec["status"]
    assert set(r.json().keys()) == set(rec["body"].keys()), "ERP 字段变了：先重录 fixture，再改工具"


# T17 · W2-AC-01：列表接口比简表字段；credit 子对象字段；空结果与 401 的形状
@pytest.mark.parametrize("name", ["customers_q_Jakarta", "customers_q_Dusseldorf_DE"])
def test_t17_customer_search_rows_have_same_fields(name):
    rec = json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))
    r = _get(rec)
    assert r.status_code == 200 and set(r.json().keys()) == {"data", "has_more", "next_cursor"}
    assert r.json()["data"], "基础种子里该有这个客户"
    assert set(r.json()["data"][0].keys()) == set(rec["body"]["data"][0].keys())


def test_t17_customer_credit_fields():
    rec = json.loads((FIX / "customers_C-E001.json").read_text(encoding="utf-8"))
    assert set(_get(rec).json()["credit"].keys()) == set(rec["body"]["credit"].keys())


def test_t17_empty_search_and_empty_quotes_are_200_with_empty_data():
    for name in ("customers_q_Singapore_empty", "quotes_customer_C-E001_empty"):
        rec = json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))
        r = _get(rec)
        assert r.status_code == 200 and r.json()["data"] == [] and r.json()["has_more"] is False


def test_t17_unauthorized_is_401_problem_json():
    rec = json.loads((FIX / "customers_C-E001_401.json").read_text(encoding="utf-8"))
    r = _get(rec)
    assert r.status_code == 401 and r.json()["code"] == "unauthorized"
    assert r.headers["content-type"].startswith("application/problem+json")
