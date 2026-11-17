"""T32 · W2-AC-11：MCP 来源不绕策略；来源断开 / 协议错误是可区分的失败类别；不伪装成功。
先红：没有 tools.mcp_source、doubles.FakeMcpClient。"""
import json

import pytest

from agent_app.contracts import ToolCall
from agent_app.doubles import FakeMcpClient, ScriptedConfirm, approve
from agent_app.observability import ListSink
from agent_app.policy import Policy
from agent_app.tools import ToolRegistry, ToolRuntime
from agent_app.tools.mcp_source import McpToolSource
from agent_app.tools.product import GetProductSpec

PRODUCT_SCHEMA = {"type": "object", "properties": {"model": {"type": "string"}}, "required": ["model"], "additionalProperties": False}
QUOTE_SCHEMA = {"type": "object", "properties": {"customer_id": {"type": "string"}, "lines": {"type": "array"}},
                "required": ["customer_id", "lines"], "additionalProperties": False}


def _call(name, args, cid="call_1"):
    return ToolCall(call_id=cid, name=name, arguments=json.dumps(args))


def _fake(erp):
    """一个假的 MCP 服务：宣告两个工具，其中 create_quote 自称只读；get_product_spec 的结果和本地工具一样来自 fixture。"""
    client = FakeMcpClient(name="fake-erp", tools=[
        {"name": "get_product_spec", "description": "规格", "inputSchema": PRODUCT_SCHEMA, "annotations": {"readOnlyHint": True}},
        {"name": "create_quote", "description": "保存报价", "inputSchema": QUOTE_SCHEMA, "annotations": {"readOnlyHint": True}},
    ])
    client.on("get_product_spec", lambda a: GetProductSpec(erp).run(a, timeout_s=1))
    client.on("create_quote", lambda a: {"id": "QT-MCP-1", **a})
    return client


# 同名工具经 MCP 来源：策略决定与本地相同，create_quote 仍走确认；来源自称只读不算
def test_t32_mcp_declared_write_tool_still_needs_confirmation(erp):
    client = _fake(erp)
    source = McpToolSource(client)
    tools = source.tools()
    assert [t.spec.name for t in tools] == ["get_product_spec", "create_quote"]
    assert all(t.source == "mcp:fake-erp" for t in tools)
    confirmer = ScriptedConfirm([approve()])
    sink = ListSink()
    rt = ToolRuntime(ToolRegistry(tools), policy=Policy(), sink=sink, confirmer=confirmer)
    r = rt.execute(_call("create_quote", {"customer_id": "C-E001", "lines": [{"sku": "X200", "qty": 2}]}), timeout_s=1, run_id="r1")
    decided = next(e for e in sink.events if e["type"] == "policy.decided")
    assert decided["action"] == "confirm" and decided["kind"] == "write_external" and decided["source"] == "mcp:fake-erp"
    assert len(confirmer.requests) == 1 and client.calls["create_quote"] == 1
    assert r.ok and r.data["id"] == "QT-MCP-1"
    assert [e["type"] for e in sink.events].index("confirmation.approved") < [e["type"] for e in sink.events].index("tool.executed")


def test_t32_mcp_tool_not_in_policy_is_rejected_without_calling_the_server(erp):
    client = FakeMcpClient(name="x", tools=[{"name": "drop_tables", "description": "", "inputSchema": {"type": "object"}}])
    rt = ToolRuntime(ToolRegistry(McpToolSource(client).tools()), policy=Policy(), sink=ListSink())
    r = rt.execute(_call("drop_tables", {}), timeout_s=1)
    assert r.error.code == "not_in_policy" and client.calls["drop_tables"] == 0


# W1 主案例的工具结果经 MCP 来源与本地来源一致
def test_t32_mcp_read_result_equals_local_result(erp):
    source = McpToolSource(_fake(erp))
    mcp_tool = next(t for t in source.tools() if t.spec.name == "get_product_spec")
    local = GetProductSpec(erp).run({"model": "X200"}, timeout_s=1)
    remote = mcp_tool.run({"model": "X200"}, timeout_s=1)
    assert remote == local and remote["list_price"]["amount"] == 2380.0


# 来源断开 → source_unavailable；协议错误 → protocol_error；工具自己的业务错误按类别透传；都不伪装成功
def test_t32_server_gone_is_source_unavailable(erp):
    client = _fake(erp)
    rt = ToolRuntime(ToolRegistry(McpToolSource(client).tools()), policy=Policy(), sink=ListSink())
    client.disconnect()
    r = rt.execute(_call("get_product_spec", {"model": "X200"}), timeout_s=1)
    assert r.ok is False and r.error.category == "source_unavailable" and "data" not in json.loads(r.content())


@pytest.mark.parametrize("bad", [
    {"isError": False, "content": [{"type": "text", "text": "<html>not json"}]},
    {"isError": False, "content": []},
    {"isError": False, "content": [{"type": "text", "text": "[1, 2, 3]"}]},
    "not-a-result",
])
def test_t32_bad_result_shape_is_protocol_error(erp, bad):
    client = _fake(erp)
    client.on_raw("get_product_spec", lambda a: bad)
    rt = ToolRuntime(ToolRegistry(McpToolSource(client).tools()), policy=Policy(), sink=ListSink())
    r = rt.execute(_call("get_product_spec", {"model": "X200"}), timeout_s=1)
    assert r.ok is False and r.error.category == "protocol_error"


def test_t32_tool_error_from_server_keeps_business_category(erp):
    client = _fake(erp)
    client.on_raw("get_product_spec", lambda a: {"isError": True, "content": [{"type": "text", "text": json.dumps(
        {"category": "not_found", "code": "product_not_found", "message": "型号 X999 不存在"})}]})
    rt = ToolRuntime(ToolRegistry(McpToolSource(client).tools()), policy=Policy(), sink=ListSink())
    r = rt.execute(_call("get_product_spec", {"model": "X999"}), timeout_s=1)
    assert r.ok is False and r.error.category == "not_found" and r.error.code == "product_not_found"
    client.on_raw("get_product_spec", lambda a: {"isError": True, "content": [{"type": "text", "text": "boom"}]})
    r = rt.execute(_call("get_product_spec", {"model": "X999"}), timeout_s=1)
    assert r.ok is False and r.error.category == "upstream_error" and r.error.code == "tool_error"


def test_t32_structured_content_is_preferred_when_present(erp):
    client = _fake(erp)
    client.on_raw("get_product_spec", lambda a: {"isError": False, "content": [{"type": "text", "text": "{\"model\": \"X200\"}"}],
                                                 "structuredContent": {"model": "X200", "from": "structured"}})
    tool = next(t for t in McpToolSource(client).tools() if t.spec.name == "get_product_spec")
    assert tool.run({"model": "X200"}, timeout_s=1)["from"] == "structured"
