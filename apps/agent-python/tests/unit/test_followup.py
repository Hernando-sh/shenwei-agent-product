"""T33 · 独立变体：scrm_write_followup（内部写，另一个系统）。检验 2.2–2.6 的管线不是只为报价写死的。
先红：没有 tools.followup、tools.scrm_client、doubles.FakeScrm。"""
import json
import pathlib

from agent_app.contracts import Operation, ToolCall, ToolFailure
from agent_app.doubles import FakeScrm, ScriptedConfirm, approve, reject
from agent_app.observability import ListSink
from agent_app.ops import ListLedger
from agent_app.policy import Policy
from agent_app.tools import ToolRegistry, ToolRuntime
from agent_app.tools.followup import SPEC, WriteFollowup

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "agent_app"
BODY = "已出 2 台 X200 的报价 QT-000001，等客户确认。"
ARGS = {"customer_id": "C-E001", "body": BODY}


def _call(args=ARGS, cid="call_1"):
    return ToolCall(call_id=cid, name="scrm_write_followup", arguments=json.dumps(args))


def _runtime(scrm, *, mode="ask", confirmer=None):
    sink, ledger = ListSink(), ListLedger()
    rt = ToolRuntime(ToolRegistry([WriteFollowup(scrm)]), policy=Policy(), sink=sink, mode=mode,
                     confirmer=confirmer if confirmer is not None else ScriptedConfirm([approve()]), ledger=ledger)
    return rt, sink, ledger


def _op(run_id="r1", op_id="op1", attempt=1):
    return Operation(operation_id=op_id, run_id=run_id, idempotency_key=f"{run_id}:{op_id}", actor=f"agent:{run_id}",
                     digest="d", attempt=attempt)


class _Peek(ScriptedConfirm):
    """确认时偷看一眼 SCRM：未确认前不该有任何写请求。"""
    def __init__(self, scrm, decisions):
        super().__init__(decisions)
        self.scrm, self.seen = scrm, []

    def request(self, changeset, *, ttl_s):
        self.seen.append((self.scrm.calls["create_followup"], len(self.scrm.followups)))
        return super().request(changeset, ttl_s=ttl_s)


# 注册后可用：策略表里是内部写——询问模式确认、自动模式放行
def test_t33_registered_and_policy_is_internal_write():
    assert SPEC.name == "scrm_write_followup" and WriteFollowup.kind == "write_internal"
    assert set(SPEC.parameters["properties"]).isdisjoint({"message_to_customer", "source", "run_id", "owner"})
    p = Policy()
    ask, auto = p.decide(SPEC.name, ARGS, mode="ask"), p.decide(SPEC.name, ARGS, mode="auto")
    assert (ask.action, str(ask.kind)) == ("confirm", "write_internal") and auto.action == "allow"


# 询问模式：未确认时 SCRM 调用计数 0；确认后账本正好一条，键 / 操作者 / source / run_id 由程序填
def test_t33_ask_mode_writes_only_after_confirmation():
    scrm = FakeScrm.with_base()
    before = len(scrm.followups)
    peek = _Peek(scrm, [approve()])
    rt, sink, ledger = _runtime(scrm, confirmer=peek)
    r = rt.execute(_call(), timeout_s=1, run_id="run1")
    assert peek.seen == [(0, before)]
    assert r.ok and r.data["outcome"] == "saved" and r.data["recorded"] is True
    assert len(scrm.followups) == before + 1 and scrm.calls["create_followup"] == 1
    req = scrm.write_requests[0]
    cs = next(e for e in sink.events if e["type"] == "changeset.created")
    assert req["idempotency_key"] == f"run1:{cs['operation_id']}" and req["actor"] == "agent:run1"
    assert req["body"] == {"customer_id": "C-E001", "type": "note", "body": BODY, "next_action_at": None,
                           "source": "agent", "run_id": "run1"}
    assert r.data["owner"] == "sales:zhou"                      # agent:* 写入记到客户业务员名下
    assert r.data["id"] == r.data["followup_id"] == scrm.followups[-1]["id"]
    assert ledger.status(cs["operation_id"]) == "committed"
    types = [e["type"] for e in sink.events]
    assert types == ["tool.requested", "policy.decided", "changeset.created", "confirmation.requested", "confirmation.approved",
                     "operation.started", "tool.executed", "run.outcome"]
    assert sink.events[-1]["outcome"] == "resolved"


def test_t33_ask_mode_rejected_writes_nothing():
    scrm = FakeScrm.with_base()
    before = len(scrm.followups)
    rt, sink, _ = _runtime(scrm, confirmer=ScriptedConfirm([reject(note="先别记")]))
    r = rt.execute(_call(), timeout_s=1, run_id="run1")
    assert r.ok is False and r.error.code == "confirmation_rejected"
    assert len(scrm.followups) == before and scrm.calls["create_followup"] == 0
    assert sink.events[-1]["type"] == "run.outcome" and sink.events[-1]["outcome"] == "cancelled"


# 自动模式：不问直接写，但变更集 / 操作 / 结果事件照记
def test_t33_auto_mode_writes_without_asking_but_with_events():
    scrm = FakeScrm.with_base()

    class NeverAsk:
        def request(self, changeset, *, ttl_s):
            raise AssertionError("自动模式不该请求确认")

    rt, sink, ledger = _runtime(scrm, mode="auto", confirmer=NeverAsk())
    r = rt.execute(_call(), timeout_s=1, run_id="run2")
    assert r.ok and scrm.calls["create_followup"] == 1
    types = [e["type"] for e in sink.events]
    assert "confirmation.requested" not in types
    assert types == ["tool.requested", "policy.decided", "changeset.created", "operation.started", "tool.executed", "run.outcome"]
    assert sink.events[1]["action"] == "allow" and sink.events[1]["kind"] == "write_internal"
    assert ledger.rows[-1]["status"] == "committed" and ledger.rows[-1]["record_id"] == r.data["id"]


# 同键重放只有一条；换体冲突
def test_t33_same_key_replay_is_one_row():
    scrm = FakeScrm.with_base()
    before = len(scrm.followups)
    tool = WriteFollowup(scrm)
    first = tool.run(ARGS, timeout_s=1, operation=_op())
    second = tool.run(ARGS, timeout_s=1, operation=_op(attempt=2))
    assert len(scrm.followups) == before + 1 and first["id"] == second["id"]
    assert first["idempotent_replay"] is False and second["idempotent_replay"] is True
    try:
        tool.run({**ARGS, "body": BODY + " 另一句"}, timeout_s=1, operation=_op(attempt=2))
        raise AssertionError("应当冲突")
    except ToolFailure as f:
        assert f.error.code == "idempotency_conflict"


def test_t33_response_lost_is_verified_not_rewritten():
    scrm = FakeScrm.with_base()
    before = len(scrm.followups)
    scrm.response_lost("create_followup", times=1)
    rt, sink, ledger = _runtime(scrm)
    r = rt.execute(_call(), timeout_s=1, run_id="run3")
    types = [e["type"] for e in sink.events]
    assert types[-4:] == ["operation.unknown", "operation.verified", "tool.executed", "run.outcome"]
    assert r.ok and r.data["idempotent_replay"] is True and len(scrm.followups) == before + 1
    assert scrm.calls["create_followup"] == 2 and len({w["idempotency_key"] for w in scrm.write_requests}) == 1
    assert "ERP" not in sink.events[-3].get("message", "")


# 缺信息与上游失败
def test_t33_empty_body_is_input_error_and_scrm_not_called():
    scrm = FakeScrm.with_base()
    rt, sink, _ = _runtime(scrm)
    r = rt.execute(_call({"customer_id": "C-E001", "body": "   "}), timeout_s=1, run_id="r")
    assert r.ok is False and r.error.category == "input_error"
    assert scrm.calls["create_followup"] == 0 and scrm.calls["list_followups"] == 0


def test_t33_extra_field_message_to_customer_is_rejected_before_scrm():
    scrm = FakeScrm.with_base()
    rt, sink, _ = _runtime(scrm)
    r = rt.execute(_call({**ARGS, "message_to_customer": "Dear customer"}), timeout_s=1, run_id="r")
    assert r.ok is False and r.error.code == "unknown_field" and scrm.calls["create_followup"] == 0


def test_t33_unknown_customer_is_not_found_and_ledger_failed():
    scrm = FakeScrm.with_base()
    rt, sink, ledger = _runtime(scrm)
    r = rt.execute(_call({"customer_id": "C-E999", "body": BODY}), timeout_s=1, run_id="r")
    assert r.ok is False and r.error.category == "not_found"
    assert scrm.calls["create_followup"] == 0 and ledger.rows[-1]["status"] == "failed"


def test_t33_same_body_already_recorded_is_declined_duplicate():
    scrm = FakeScrm.with_base()
    existing = scrm.followups[0]
    rt, sink, ledger = _runtime(scrm)
    r = rt.execute(_call({"customer_id": existing["customer_id"], "body": existing["body"]}), timeout_s=1, run_id="r")
    assert r.ok and r.data["outcome"] == "declined" and r.data["rule"] == "duplicate_followup"
    assert r.data["facts"]["followup_id"] == existing["id"] and r.data["recorded"] is False
    assert scrm.calls["list_followups"] == 1 and scrm.calls["create_followup"] == 0
    assert sink.events[-1]["type"] == "run.outcome" and sink.events[-1]["outcome"] == "declined"
    assert ledger.rows[-1]["status"] == "declined"


# 设计检验：Loop / Runtime / 确认适配器没有业务特判
def test_t33_no_business_special_case_outside_the_tool():
    files = [SRC / "tools" / "runtime.py", SRC / "tools" / "registry.py", SRC / "agent" / "loop.py",
             *(SRC / "confirm").glob("*.py"), *(SRC / "ops").glob("*.py")]
    for f in files:
        text = f.read_text(encoding="utf-8")
        assert "scrm_write_followup" not in text and "followup" not in text.lower(), f
        assert 'if name ==' not in text and "if call.name ==" not in text, f
