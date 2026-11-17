"""SCRM 写契约测试：对一个私有 SCRM 实例验证写跟进、同键重放、422 多传字段、404 客户、response_lost 核实语义。
会写账本并 reset，所以只在显式指定 SCRM_WRITE_BASE_URL 时跑，别指向共享的 9300。
    SCRM_WRITE_BASE_URL=http://localhost:9377 uv run pytest tests/integration/test_scrm_write_contract.py -q"""
import os
import uuid

import httpx
import pytest

from agent_app.contracts import Operation, ToolFailure
from agent_app.tools.followup import WriteFollowup
from agent_app.tools.scrm_client import ScrmClient

BASE = os.environ.get("SCRM_WRITE_BASE_URL")
ADMIN = {"X-Admin-Token": "local-admin"}
pytestmark = pytest.mark.skipif(not BASE, reason="未设置 SCRM_WRITE_BASE_URL（需要私有 SCRM 实例）")


@pytest.fixture
def scrm():
    httpx.post(f"{BASE}/_admin/reset", headers=ADMIN, timeout=5).raise_for_status()
    return ScrmClient(BASE, "east-scrm-key")


def _scenario(faults):
    httpx.post(f"{BASE}/_admin/scenario", json={"case_id": "w2-followup-contract", "base": True, "faults": faults},
               headers=ADMIN, timeout=5).raise_for_status()


def _ledger():
    return httpx.get(f"{BASE}/_admin/ledger", headers=ADMIN, timeout=5).json()


def _op(run_id, op_id, attempt=1):
    return Operation(operation_id=op_id, run_id=run_id, idempotency_key=f"{run_id}:{op_id}", actor=f"agent:{run_id}",
                     digest="d", attempt=attempt)


def test_create_and_replay_same_key_is_one_followup(scrm):
    run = f"ct-{uuid.uuid4().hex[:6]}"
    body = f"契约测试 {run}：已出 2 台 X200 的报价，等确认。"
    first = scrm.create_followup("C-E001", body, run_id=run, idempotency_key=f"{run}:op1", actor=f"agent:{run}", timeout_s=5)
    second = scrm.create_followup("C-E001", body, run_id=run, idempotency_key=f"{run}:op1", actor=f"agent:{run}", timeout_s=5)
    assert first["id"] == second["id"] and first["idempotent_replay"] is False and second["idempotent_replay"] is True
    assert first["owner"] == "sales:zhou" and first["source"] == "agent" and first["run_id"] == run   # agent:* 记到客户业务员名下
    rows = [f for f in _ledger()["followups"] if f.get("run_id") == run]
    assert len(rows) == 1
    page = scrm.list_followups("C-E001", timeout_s=5)
    assert any(f["id"] == first["id"] for f in page["data"])


def test_extra_field_is_422_input_error(scrm):
    with pytest.raises(ToolFailure) as ei:
        scrm._post("/v1/followups", {"customer_id": "C-E001", "body": "x", "message_to_customer": "Dear customer"},
                   idempotency_key=f"ct:{uuid.uuid4().hex[:8]}", actor="agent:ct", timeout_s=5)
    assert ei.value.error.category == "input_error" and "message_to_customer" in ei.value.error.message


def test_unknown_customer_is_404_and_wrong_key_is_rejected(scrm):
    with pytest.raises(ToolFailure) as ei:
        scrm.create_followup("C-E999", "x", run_id="ct", idempotency_key=f"ct:{uuid.uuid4().hex[:8]}", actor="agent:ct", timeout_s=5)
    assert ei.value.error.category == "not_found" and ei.value.error.code == "customer_not_found"
    wrong = ScrmClient(BASE, "east-demo-key")                                      # 拿 ERP 的 key 来 → 401
    with pytest.raises(ToolFailure) as ei2:
        wrong.list_followups("C-E001", timeout_s=5)
    assert ei2.value.error.category == "rejected"


def test_response_lost_is_committed_and_tool_dedups_identical_body(scrm):
    _scenario([{"target": "POST /v1/followups", "mode": "response_lost", "times": 1}])
    run = f"ct-{uuid.uuid4().hex[:6]}"
    tool = WriteFollowup(scrm)
    args = {"customer_id": "C-E001", "body": f"契约测试 {run}：response_lost 后同键核实。"}
    with pytest.raises(ToolFailure) as ei:
        tool.run(args, timeout_s=5, operation=_op(run, "op1"))
    assert ei.value.error.category == "unknown"
    verified = tool.run(args, timeout_s=5, operation=_op(run, "op1", attempt=2))
    assert verified["idempotent_replay"] is True and verified["recorded"] is True
    assert len([f for f in _ledger()["followups"] if f.get("run_id") == run]) == 1
    again = tool.run(args, timeout_s=5, operation=_op(run, "op2"))                  # 新操作、同内容 → 工具自己拦
    assert again["outcome"] == "declined" and again["rule"] == "duplicate_followup" and again["facts"]["followup_id"] == verified["id"]
