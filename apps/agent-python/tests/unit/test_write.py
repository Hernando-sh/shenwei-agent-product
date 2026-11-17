"""T30–T31 · W2-AC-08 / 09：重复请求只有一份业务记录；未知结果不盲重试——同键核实一次再决定；写工具不进只读重试。
先红：没有 tools.create_quote、contracts.Operation、ops 包；FakeERP 没有 create_quote / 幂等表 / response_lost。"""
import json

from agent_app.contracts import Operation, ToolCall, ToolFailure
from agent_app.doubles import FakeERP, ScriptedConfirm, approve
from agent_app.observability import ListSink
from agent_app.ops import ListLedger
from agent_app.policy import Policy
from agent_app.tools import ToolRegistry, ToolRuntime
from agent_app.tools.create_quote import CreateQuote, SPEC as CREATE_SPEC

LINES_2 = [{"sku": "X200", "qty": 2}]
ARGS = {"customer_id": "C-E001", "lines": LINES_2}


def _call(args=ARGS, cid="call_1"):
    return ToolCall(call_id=cid, name="create_quote", arguments=json.dumps(args))


def _runtime(erp, *, confirmer=None, sink=None, ledger=None):
    sink, ledger = sink or ListSink(), ledger or ListLedger()
    rt = ToolRuntime(ToolRegistry([CreateQuote(erp)]), policy=Policy(), sink=sink,
                     confirmer=confirmer or ScriptedConfirm([approve()]), ledger=ledger)
    return rt, sink, ledger


def _op(run_id="r1", op_id="op1", attempt=1):
    return Operation(operation_id=op_id, run_id=run_id, idempotency_key=f"{run_id}:{op_id}", actor=f"agent:{run_id}",
                     digest="d", attempt=attempt)


# T30 · 同一 operation_id 两次写 → 同一 Idempotency-Key → FakeERP 台账一条；第二次返回 replay 标记
def test_t30_same_operation_twice_is_one_ledger_row_with_replay_marker(erp):
    tool = CreateQuote(erp)
    first = tool.run(ARGS, timeout_s=1, operation=_op())
    second = tool.run(ARGS, timeout_s=1, operation=_op(attempt=2))
    assert len(erp.quotes) == 1 and first["quote_id"] == second["quote_id"] == "QT-000001"
    assert first["idempotent_replay"] is False and second["idempotent_replay"] is True
    assert [r["idempotency_key"] for r in erp.write_requests] == ["r1:op1", "r1:op1"]
    assert all(r["actor"] == "agent:r1" for r in erp.write_requests)
    assert first["recorded"] is True and first["valid_until"] == "2026-10-20" and first["total_amount"] == 621.44


def test_t30_same_key_different_body_is_a_conflict_not_a_second_quote(erp):
    tool = CreateQuote(erp)
    tool.run(ARGS, timeout_s=1, operation=_op())
    try:
        tool.run({"customer_id": "C-E001", "lines": [{"sku": "X200", "qty": 10}]}, timeout_s=1, operation=_op(attempt=2))
        raise AssertionError("应当冲突")
    except ToolFailure as f:
        assert f.error.category == "rejected" and f.error.code == "idempotency_conflict"
    assert len(erp.quotes) == 1


def test_t30_runtime_uses_run_and_operation_id_as_key_and_actor(erp):
    rt, sink, ledger = _runtime(erp)
    r = rt.execute(_call(), timeout_s=1, run_id="run77")
    assert r.ok and len(erp.quotes) == 1
    cs = next(e for e in sink.events if e["type"] == "changeset.created")
    req = erp.write_requests[0]
    assert req["idempotency_key"] == f"run77:{cs['operation_id']}" and req["actor"] == "agent:run77"
    assert ledger.status(cs["operation_id"]) == "committed" and ledger.rows[-1]["record_id"] == "QT-000001"
    started = next(e for e in sink.events if e["type"] == "operation.started")
    assert started["idempotency_key"] == req["idempotency_key"]
    assert r.data["quote_id"] == "QT-000001" and r.data["idempotent_replay"] is False


def test_t30_schema_has_no_money_fields_and_money_is_rejected(erp):
    names = set(CREATE_SPEC.parameters["properties"]) | set(CREATE_SPEC.parameters["properties"]["lines"]["items"]["properties"])
    assert names.isdisjoint({"unit_price", "amount", "discount", "total_amount"})
    rt, sink, _ = _runtime(erp)
    r = rt.execute(_call({"customer_id": "C-E001", "lines": [{"sku": "X200", "qty": 2, "unit_price": 280}]}), timeout_s=1)
    assert r.error.code == "unknown_field" and erp.calls["create_quote"] == 0 and len(erp.quotes) == 0


def test_t30_create_quote_reruns_rules_before_writing(erp):
    """模型若跳过 price_quote 直接保存，规则仍由程序在写之前执行：逾期客户不写。"""
    rt, sink, _ = _runtime(erp, confirmer=ScriptedConfirm([approve()]))
    r = rt.execute(_call({"customer_id": "C-E003", "lines": [{"sku": "X300", "qty": 1}]}), timeout_s=1, run_id="r1")
    assert r.ok and r.data["outcome"] == "declined" and r.data["rule"] == "overdue"
    assert len(erp.quotes) == 0 and sink.events[-1]["type"] == "run.outcome" and sink.events[-1]["outcome"] == "declined"


# T31 · 未知结果不盲重试：502 → operation.unknown → 同键核实一次 → 已提交取回原结果 / 未提交一次新执行；台账都只有一条
def test_t31_response_lost_is_unknown_then_verified_as_committed(erp):
    erp.response_lost("create_quote", times=1)                       # ERP 已提交，但返回 502
    rt, sink, ledger = _runtime(erp)
    r = rt.execute(_call(), timeout_s=1, run_id="r1")
    types = [e["type"] for e in sink.events]
    assert types[-4:] == ["operation.unknown", "operation.verified", "tool.executed", "run.outcome"]
    unk = sink.events[-4]
    assert unk["code"] == "bad_gateway" and unk["attempt"] == 1
    ver = sink.events[-3]
    assert ver["committed"] is True and ver["replayed"] is True and ver["record_id"] == "QT-000001"
    assert r.ok and r.data["quote_id"] == "QT-000001" and r.data["idempotent_replay"] is True
    assert len(erp.quotes) == 1 and erp.calls["create_quote"] == 2
    assert [x["idempotency_key"] for x in erp.write_requests] == [erp.write_requests[0]["idempotency_key"]] * 2
    assert ledger.status(unk["operation_id"]) == "committed"
    assert [row["status"] for row in ledger.rows] == ["pending", "unknown", "committed"]


def test_t31_timeout_is_unknown_then_verified_as_fresh_execution(erp):
    erp.inject("create_quote", ToolFailure("unknown", "gateway_timeout", "ERP 网关超时"), times=1)   # 没提交
    rt, sink, ledger = _runtime(erp)
    r = rt.execute(_call(), timeout_s=1, run_id="r1")
    ver = next(e for e in sink.events if e["type"] == "operation.verified")
    assert ver["committed"] is True and ver["replayed"] is False
    assert r.ok and r.data["idempotent_replay"] is False and len(erp.quotes) == 1
    assert "tool.retry" not in [e["type"] for e in sink.events]       # 写工具不进只读重试


def test_t31_write_timeout_never_enters_readonly_retry_even_if_retries_requested(erp):
    erp.inject("create_quote", ToolFailure("unknown", "gateway_timeout", "ERP 网关超时"), times=1)
    rt, sink, _ = _runtime(erp)
    rt.execute(_call(), timeout_s=1, run_id="r1", retries=3)
    assert "tool.retry" not in [e["type"] for e in sink.events] and erp.calls["create_quote"] == 2


def test_t31_verify_failing_again_is_failed_not_a_new_quote(erp):
    erp.inject("create_quote", ToolFailure("unknown", "bad_gateway", "网关错误"), times=2)   # 核实也未知
    rt, sink, ledger = _runtime(erp)
    r = rt.execute(_call(), timeout_s=1, run_id="r1")
    assert r.ok is False and r.error.category == "unknown" and r.error.code == "verify_failed"
    assert "人工核对" in r.error.message
    assert erp.calls["create_quote"] == 2 and len(erp.quotes) == 0    # 没有第三次、没有换键
    ver = next(e for e in sink.events if e["type"] == "operation.verified")
    assert ver["committed"] is None
    assert sink.events[-1]["type"] == "run.outcome" and sink.events[-1]["outcome"] == "failed"
    assert ledger.status(ver["operation_id"]) == "unknown"


def test_t31_definite_failure_is_not_verified(erp):
    erp.inject("create_quote", ToolFailure("input_error", "unknown_sku", "型号不存在"), times=1)
    rt, sink, ledger = _runtime(erp)
    r = rt.execute(_call(), timeout_s=1, run_id="r1")
    assert r.ok is False and r.error.code == "unknown_sku" and erp.calls["create_quote"] == 1
    assert "operation.unknown" not in [e["type"] for e in sink.events]
    assert ledger.rows[-1]["status"] == "failed"
