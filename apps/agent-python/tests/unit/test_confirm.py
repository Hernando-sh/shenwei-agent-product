"""T26–T29 · W2-AC-06 / 07 / 10：写动作先以变更集出现并等待确认；确认绑定变更集摘要与有效期；模式切换记事件。
先红：没有 confirm 包、ScriptedConfirm、Changeset / ConfirmToken 契约；ToolRuntime 不接确认适配器。
本节用一个记录参数的写工具替身（create_quote 的真实实现与幂等在 2.6）。"""
import json

from agent_app.confirm import Changeset
from agent_app.contracts import ToolCall, ToolSpec
from agent_app.doubles import ScriptedConfirm, approve, approve_with, reject, amend
from agent_app.observability import ListSink
from agent_app.policy import Policy
from agent_app.tools import ToolRegistry, ToolRuntime

LINES_2 = [{"sku": "X200", "qty": 2}]
LINES_10 = [{"sku": "X200", "qty": 10}]


class _WriteStub:
    def __init__(self, name):
        self.spec = ToolSpec(name=name, description="stub write", parameters={
            "type": "object",
            "properties": {"customer_id": {"type": "string"},
                           "lines": {"type": "array", "items": {"type": "object", "properties": {
                               "sku": {"type": "string"}, "qty": {"type": "integer", "minimum": 1}},
                               "required": ["sku", "qty"], "additionalProperties": False}},
                           "body": {"type": "string"}},
            "required": ["customer_id"], "additionalProperties": False})
        self.written: list[dict] = []

    def run(self, args, *, timeout_s, operation=None):
        self.written.append(args)
        return {"id": f"QT-{len(self.written):06d}", **args}


def _call(name, args, cid="call_1"):
    return ToolCall(call_id=cid, name=name, arguments=json.dumps(args))


def _runtime(tool, confirmer, *, sink=None, mode="ask", clock=None, ttl=600.0):
    sink = sink or ListSink()
    kw = {"clock": clock} if clock else {}
    rt = ToolRuntime(ToolRegistry([tool]), policy=Policy(), sink=sink, mode=mode, confirmer=confirmer,
                     confirm_ttl_s=ttl, **kw)
    return rt, sink


def _types(sink):
    return [e["type"] for e in sink.events]


# T26 · 未确认不写：确认适配器未返回同意前写工具计数 0；同意后计数 1
def test_t26_write_waits_for_confirmation_then_executes_once():
    tool = _WriteStub("create_quote")
    confirmer = ScriptedConfirm([approve()])
    rt, sink = _runtime(tool, confirmer)
    assert tool.written == [] and confirmer.requests == []
    r = rt.execute(_call("create_quote", {"customer_id": "C-E001", "lines": LINES_2}), timeout_s=1, run_id="r1")
    assert r.ok and len(tool.written) == 1 and tool.written[0]["lines"] == LINES_2
    # 适配器看到的是变更集，不是原始字符串；适配器收到请求之前工具没有被执行（由事件顺序证明）
    assert len(confirmer.requests) == 1 and isinstance(confirmer.requests[0], Changeset)
    assert _types(sink) == ["tool.requested", "policy.decided", "changeset.created", "confirmation.requested",
                            "confirmation.approved", "operation.started", "tool.executed", "run.outcome"]
    assert sink.events[-1]["outcome"] == "resolved"
    cs = sink.events[2]
    assert cs["operation_id"] and cs["digest"] and cs["tool"] == "create_quote" and cs["kind"] == "write_external"
    assert cs["args"] == {"customer_id": "C-E001", "lines": LINES_2}


def test_t26_no_confirmer_means_no_write():
    tool = _WriteStub("create_quote")
    rt, sink = _runtime(tool, None)
    r = rt.execute(_call("create_quote", {"customer_id": "C-E001", "lines": LINES_2}), timeout_s=1)
    assert r.ok is False and r.error.code == "confirmation_required" and tool.written == []
    assert "confirmation.requested" not in _types(sink)


# T27 · 改参数使确认失效：2 台的确认不能用于 10 台；操作者在确认时改参数 → 原变更集作废 → 重新确认后写的是 10 台
def test_t27_token_for_other_digest_is_invalid_and_nothing_is_written():
    tool = _WriteStub("create_quote")
    stale = Changeset.build(run_id="r0", call_id="c0", tool="create_quote", kind="write_external",
                            args={"customer_id": "C-E001", "lines": LINES_2}, now=1000.0)
    confirmer = ScriptedConfirm([approve_with(digest=stale.digest, operation_id=stale.operation_id)])  # 拿 2 台的确认
    rt, sink = _runtime(tool, confirmer, clock=lambda: 1000.0)
    r = rt.execute(_call("create_quote", {"customer_id": "C-E001", "lines": LINES_10}), timeout_s=1, run_id="r1")  # 写 10 台
    assert r.ok is False and r.error.code == "confirmation_invalid" and tool.written == []
    inv = next(e for e in sink.events if e["type"] == "confirmation.invalid")
    assert inv["reason"] == "digest_mismatch" and inv["token_digest"] == stale.digest and inv["digest"] != stale.digest


def test_t27_amend_voids_changeset_and_new_confirmation_writes_new_args():
    tool = _WriteStub("create_quote")
    confirmer = ScriptedConfirm([amend({"lines": LINES_10}), approve()])
    rt, sink = _runtime(tool, confirmer)
    r1 = rt.execute(_call("create_quote", {"customer_id": "C-E001", "lines": LINES_2}), timeout_s=1, run_id="r1")
    assert r1.ok is False and r1.error.code == "confirmation_amended" and tool.written == []
    assert '"qty": 10' in r1.error.message                         # 回注给模型：按新参数重出草案、重新请求
    amended = next(e for e in sink.events if e["type"] == "confirmation.amended")
    assert amended["amended_args"] == {"lines": LINES_10}
    r2 = rt.execute(_call("create_quote", {"customer_id": "C-E001", "lines": LINES_10}, "call_2"), timeout_s=1, run_id="r1")
    assert r2.ok and tool.written == [{"customer_id": "C-E001", "lines": LINES_10}]
    created = [e for e in sink.events if e["type"] == "changeset.created"]
    assert len(created) == 2 and created[0]["digest"] != created[1]["digest"]
    assert created[0]["operation_id"] != created[1]["operation_id"]


def test_t27_digest_depends_on_tool_and_args_not_on_ids():
    a = Changeset.build(run_id="r1", call_id="c1", tool="create_quote", kind="write_external",
                        args={"customer_id": "C-E001", "lines": LINES_2}, now=1.0)
    b = Changeset.build(run_id="r2", call_id="c9", tool="create_quote", kind="write_external",
                        args={"lines": LINES_2, "customer_id": "C-E001"}, now=2.0)
    c = Changeset.build(run_id="r1", call_id="c1", tool="create_quote", kind="write_external",
                        args={"customer_id": "C-E001", "lines": LINES_10}, now=1.0)
    assert a.digest == b.digest != c.digest and a.operation_id != b.operation_id


# T28 · 拒绝与过期：拒绝 → 计数 0、outcome=cancelled；过期令牌（注入时钟）→ 不写、要求重新确认
def test_t28_reject_writes_nothing_and_outcome_is_cancelled():
    tool = _WriteStub("create_quote")
    rt, sink = _runtime(tool, ScriptedConfirm([reject(note="客户还没回")]))
    r = rt.execute(_call("create_quote", {"customer_id": "C-E001", "lines": LINES_2}), timeout_s=1, run_id="r1")
    assert r.ok is False and r.error.code == "confirmation_rejected" and tool.written == []
    assert _types(sink)[-4:] == ["confirmation.requested", "confirmation.rejected", "tool.rejected", "run.outcome"]
    assert sink.events[-1]["outcome"] == "cancelled" and sink.events[-3]["note"] == "客户还没回"
    assert sink.events[-2]["reason"] == "confirmation"
    body = json.loads(r.content())
    assert body["ok"] is False and body["error"]["category"] == "rejected"


def test_t28_expired_token_is_invalid():
    tool = _WriteStub("create_quote")
    now = {"t": 1000.0}
    confirmer = ScriptedConfirm([approve(decided_at=1000.0)])
    rt, sink = _runtime(tool, confirmer, clock=lambda: now["t"], ttl=600.0)
    now["t"] = 1000.0 + 601.0                                        # 操作者 601 秒后才回来（令牌有效期 10 分钟）
    r = rt.execute(_call("create_quote", {"customer_id": "C-E001", "lines": LINES_2}), timeout_s=1, run_id="r1")
    assert r.ok is False and r.error.code == "confirmation_invalid" and tool.written == []
    inv = next(e for e in sink.events if e["type"] == "confirmation.invalid")
    assert inv["reason"] == "expired" and "重新确认" in r.error.message


def test_t28_token_within_ttl_is_valid():
    tool = _WriteStub("create_quote")
    now = {"t": 1000.0}
    rt, _ = _runtime(tool, ScriptedConfirm([approve(decided_at=1000.0)]), clock=lambda: now["t"], ttl=600.0)
    now["t"] = 1000.0 + 599.0
    assert rt.execute(_call("create_quote", {"customer_id": "C-E001", "lines": LINES_2}), timeout_s=1).ok


# T29 · 模式切换：set_mode 写 mode.changed；自动模式下内部写不问直接执行；自动模式下 create_quote 仍确认
def test_t29_set_mode_emits_event():
    tool = _WriteStub("scrm_write_followup")
    rt, sink = _runtime(tool, ScriptedConfirm([]))
    rt.set_mode("auto", by="sales:zhou", run_id="r1")
    assert sink.events[-1]["type"] == "mode.changed" and (sink.events[-1]["from"], sink.events[-1]["to"]) == ("ask", "auto")
    assert sink.events[-1]["by"] == "sales:zhou" and rt.mode == "auto"


def test_t29_auto_mode_internal_write_runs_without_asking_but_with_events():
    tool = _WriteStub("scrm_write_followup")
    confirmer = ScriptedConfirm([])                                   # 没有任何脚本：一旦被问就会炸
    rt, sink = _runtime(tool, confirmer, mode="auto")
    r = rt.execute(_call("scrm_write_followup", {"customer_id": "C-E001", "body": "已出报价"}), timeout_s=1, run_id="r1")
    assert r.ok and len(tool.written) == 1 and confirmer.requests == []
    assert _types(sink) == ["tool.requested", "policy.decided", "changeset.created", "operation.started", "tool.executed",
                            "run.outcome"]
    assert sink.events[1]["action"] == "allow" and sink.events[1]["kind"] == "write_internal"


def test_t29_ask_mode_internal_write_asks():
    tool = _WriteStub("scrm_write_followup")
    rt, sink = _runtime(tool, ScriptedConfirm([approve()]), mode="ask")
    r = rt.execute(_call("scrm_write_followup", {"customer_id": "C-E001", "body": "已出报价"}), timeout_s=1)
    assert r.ok and "confirmation.requested" in _types(sink)


def test_t29_auto_mode_external_write_still_asks():
    tool = _WriteStub("create_quote")
    confirmer = ScriptedConfirm([approve()])
    rt, sink = _runtime(tool, confirmer, mode="auto")
    r = rt.execute(_call("create_quote", {"customer_id": "C-E001", "lines": LINES_2}), timeout_s=1)
    assert r.ok and len(confirmer.requests) == 1 and "confirmation.requested" in _types(sink)
    assert next(e for e in sink.events if e["type"] == "policy.decided")["action"] == "confirm"
