"""写契约测试：对一个私有 ERP 实例验证幂等重放、422 金额字段、response_lost 与 timeout 的核实语义。
会写台账并加载场景（场景加载会重置账本），所以只在显式指定 ERP_WRITE_BASE_URL 时跑，别指向共享的 9100。
    ERP_WRITE_BASE_URL=http://localhost:9177 uv run pytest tests/integration/test_erp_write_contract.py -q"""
import os
import uuid

import httpx
import pytest

from agent_app.contracts import ToolFailure
from agent_app.tools.erp_client import ErpClient

BASE = os.environ.get("ERP_WRITE_BASE_URL")
ADMIN = {"X-Admin-Token": "local-admin"}
pytestmark = pytest.mark.skipif(not BASE, reason="未设置 ERP_WRITE_BASE_URL（需要私有 ERP 实例）")


@pytest.fixture
def erp():
    httpx.post(f"{BASE}/_admin/reset", headers=ADMIN, timeout=5).raise_for_status()
    return ErpClient(BASE, "east-demo-key")


def _scenario(faults):
    httpx.post(f"{BASE}/_admin/scenario", json={"case_id": "w2-write-contract", "base": True, "faults": faults},
               headers=ADMIN, timeout=5).raise_for_status()


def _ledger_quotes():
    return httpx.get(f"{BASE}/_admin/ledger", headers=ADMIN, timeout=5).json()["quotes"]


def _key():
    return f"test-{uuid.uuid4().hex[:8]}:op1"


def test_same_key_replays_original_and_ledger_has_one_row(erp):
    k = _key()
    a = erp.create_quote("C-E001", [{"sku": "X200", "qty": 2}], idempotency_key=k, actor="agent:test", timeout_s=5)
    b = erp.create_quote("C-E001", [{"sku": "X200", "qty": 2}], idempotency_key=k, actor="agent:test", timeout_s=5)
    assert a["idempotent_replay"] is False and b["idempotent_replay"] is True and a["id"] == b["id"]
    assert a["total_amount"] == 621.44 and a["valid_until"] == "2026-10-20" and a["status"] == "issued"
    assert len(_ledger_quotes()) == 1
    with pytest.raises(ToolFailure) as e:
        erp.create_quote("C-E001", [{"sku": "X200", "qty": 10}], idempotency_key=k, actor="agent:test", timeout_s=5)
    assert e.value.error.code == "idempotency_conflict" and e.value.error.category == "rejected"


def test_money_in_body_is_422_input_error(erp):
    c = erp._client
    r = c.post("/v1/quotes", json={"customer_id": "C-E001", "lines": [{"sku": "X200", "qty": 2, "unit_price": 280}]},
               headers={"Idempotency-Key": _key(), "X-Actor": "agent:test"}, timeout=5)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "lines.0.unit_price"
    assert _ledger_quotes() == []


def test_response_lost_is_committed_and_same_key_replay_returns_it(erp):
    _scenario([{"target": "POST /v1/quotes", "mode": "response_lost", "times": 1}])
    k = _key()
    with pytest.raises(ToolFailure) as e:
        erp.create_quote("C-E001", [{"sku": "X200", "qty": 2}], idempotency_key=k, actor="agent:test", timeout_s=5)
    assert e.value.error.category == "unknown" and e.value.error.code == "bad_gateway"
    assert len(_ledger_quotes()) == 1                                   # 业务已经提交
    again = erp.create_quote("C-E001", [{"sku": "X200", "qty": 2}], idempotency_key=k, actor="agent:test", timeout_s=5)
    assert again["idempotent_replay"] is True and again["original_request_id"]
    assert len(_ledger_quotes()) == 1


def test_timeout_is_not_committed_and_same_key_replay_is_a_fresh_execution(erp):
    _scenario([{"target": "POST /v1/quotes", "mode": "timeout", "times": 1, "delay_s": 0.2}])
    k = _key()
    with pytest.raises(ToolFailure) as e:
        erp.create_quote("C-E001", [{"sku": "X200", "qty": 2}], idempotency_key=k, actor="agent:test", timeout_s=5)
    assert e.value.error.category == "unknown" and e.value.error.code == "gateway_timeout"
    assert _ledger_quotes() == []                                        # 没提交
    again = erp.create_quote("C-E001", [{"sku": "X200", "qty": 2}], idempotency_key=k, actor="agent:test", timeout_s=5)
    assert again["idempotent_replay"] is False and len(_ledger_quotes()) == 1
