"""T18–T20 · W2-AC-02：所有工具请求经同一条管线 解析 → 校验 → 策略 → 确认决策 → 执行 → 结果。
先红：没有 ToolRuntime / Policy / 策略表；执行器里没有 policy.decided 事件。"""
import json

from agent_app.contracts import ToolCall, ToolSpec
from agent_app.observability import ListSink
from agent_app.policy import Policy, POLICY_TABLE
from agent_app.tools import ToolRegistry, ToolRuntime
from agent_app.tools.product import GetProductSpec


def _call(name, args, cid="call_1"):
    return ToolCall(call_id=cid, name=name, arguments=args if isinstance(args, str) else json.dumps(args))


class _Stub:
    """一个假工具：记录是否被执行。name / kind / source 可指定，用来模拟不同来源宣告同一个名字。"""

    def __init__(self, name, *, kind="read", source="local", params=None):
        self.spec = ToolSpec(name=name, description="stub", parameters=params or {
            "type": "object", "properties": {"x": {"type": "string"}}, "required": [], "additionalProperties": False})
        self.kind, self.source, self.runs = kind, source, 0

    def run(self, args, *, timeout_s):
        self.runs += 1
        return {"ran": True}


def _runtime(tools, sink=None, **kw):
    return ToolRuntime(ToolRegistry(tools), policy=Policy(POLICY_TABLE), sink=sink, **kw)


# T18 · 本地与远程来源同一策略：决定由策略表按名字给，不看来源自己宣告的类别
def test_t18_same_tool_name_from_two_sources_gets_same_decision():
    local = _Stub("create_quote", kind="write_external", source="local")
    remote = _Stub("create_quote", kind="read", source="mcp:erp-readonly")   # 远程来源谎称只读
    decisions = []
    for tool in (local, remote):
        sink = ListSink()
        r = _runtime([tool], sink).execute(_call("create_quote", {}), timeout_s=1, run_id="r1")
        decided = [e for e in sink.events if e["type"] == "policy.decided"]
        assert len(decided) == 1 and decided[0]["source"] == tool.source
        decisions.append((decided[0]["action"], decided[0]["kind"], r.ok, r.error.code if r.error else None))
        assert tool.runs == 0                                     # 2.2 还没有确认通道：需确认的写动作不执行
    assert decisions[0] == decisions[1] == ("confirm", "write_external", False, "confirmation_required")


def test_t18_read_tool_is_allowed_in_both_modes(erp):
    for mode in ("ask", "auto"):
        sink = ListSink()
        r = _runtime([GetProductSpec(erp)], sink, mode=mode).execute(_call("get_product_spec", {"model": "X200"}), timeout_s=1)
        assert r.ok and [e["action"] for e in sink.events if e["type"] == "policy.decided"] == ["allow"]


# T19 · 拒绝也有记录：注册了但策略表里没有的工具 → 拒绝、事件带 reason=policy、执行计数 0、拒绝结果回注模型
def test_t19_policy_rejection_is_logged_and_returned_to_model():
    tool = _Stub("delete_everything")
    sink = ListSink()
    r = _runtime([tool], sink).execute(_call("delete_everything", {"x": "all"}), timeout_s=1, run_id="r1")
    assert tool.runs == 0
    rejected = [e for e in sink.events if e["type"] == "tool.rejected"]
    assert len(rejected) == 1 and rejected[0]["reason"] == "policy" and rejected[0]["code"] == "not_in_policy"
    assert rejected[0]["run_id"] == "r1" and rejected[0]["call_id"] == "call_1"
    body = json.loads(r.content())
    assert body["ok"] is False and body["error"]["category"] == "rejected" and body["error"]["code"] == "not_in_policy"
    assert r.to_message()["tool_call_id"] == "call_1"


def test_t19_policy_table_covers_every_w2_tool_name():
    names = {"get_product_spec", "get_availability", "get_shipment", "get_order", "search_customers", "get_customer",
             "get_receivables", "list_quotes", "search_knowledge", "price_quote", "create_quote", "scrm_write_followup"}
    assert names <= set(POLICY_TABLE)
    assert POLICY_TABLE["create_quote"].kind == "write_external"
    assert POLICY_TABLE["scrm_write_followup"].kind == "write_internal"
    assert all(POLICY_TABLE[n].kind == "read" for n in names - {"create_quote", "scrm_write_followup"})


# T20 · 管线顺序：tool.requested → policy.decided → tool.executed；校验失败不产生 policy.decided 之后的事件
def test_t20_pipeline_event_order(erp):
    sink = ListSink()
    _runtime([GetProductSpec(erp)], sink).execute(_call("get_product_spec", {"model": "X200"}), timeout_s=1, run_id="r1")
    assert [e["type"] for e in sink.events] == ["tool.requested", "policy.decided", "tool.executed"]
    assert [e["seq"] for e in sink.events] == [1, 2, 3]


def test_t20_validation_failure_stops_before_policy(erp):
    sink = ListSink()
    r = _runtime([GetProductSpec(erp)], sink).execute(_call("get_product_spec", {"model": ""}), timeout_s=1)
    assert [e["type"] for e in sink.events] == ["tool.requested", "tool.rejected"]
    assert sink.events[1]["reason"] == "input" and r.error.category == "input_error"
    assert erp.calls["get_product"] == 0


def test_t20_unknown_tool_stops_before_policy():
    sink = ListSink()
    _runtime([], sink).execute(_call("nope", {}), timeout_s=1)
    assert [e["type"] for e in sink.events] == ["tool.requested", "tool.rejected"]
    assert sink.events[1]["reason"] == "unknown_tool"


def test_t20_loop_uses_runtime_without_changes(erp):
    """Loop 只认 execute(call, timeout_s=, run_id=, retries=)；换成 ToolRuntime 不改 Loop 一行。"""
    import inspect
    from agent_app.agent import AgentLoop
    from agent_app.doubles import ScriptedModel, final, tool_calls
    reg = ToolRegistry([GetProductSpec(erp)])
    sink = ListSink()
    model = ScriptedModel([tool_calls(("get_product_spec", {"model": "X200"})), final("X200 是 260 W 离心输送泵。")])
    r = AgentLoop(model, ToolRuntime(reg, policy=Policy(POLICY_TABLE), sink=sink), reg.specs(), sink=sink).run("X200 规格")
    assert r.status == "completed" and "policy.decided" in [e["type"] for e in sink.events]
    assert "policy" not in inspect.getsource(AgentLoop).lower()
