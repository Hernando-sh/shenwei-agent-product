"""T32i · W2-AC-11：起真实的 stdio MCP 服务（apps/mcp-erp-readonly），W1 主案例的两个工具结果与本地来源一致。
需要 ERP（ERP_BASE_URL，默认 9100）；ERP 不可达自动跳过。服务进程由客户端拉起并在测试结束时关闭。"""
import json
import os
import pathlib
import sys

import httpx
import pytest

from agent_app.contracts import ToolCall
from agent_app.doubles import FakeERP
from agent_app.observability import ListSink
from agent_app.policy import Policy
from agent_app.tools import ToolRegistry, ToolRuntime
from agent_app.tools.availability import GetAvailability
from agent_app.tools.erp_client import ErpClient
from agent_app.tools.mcp_source import McpToolSource, StdioMcpClient
from agent_app.tools.product import GetProductSpec

ROOT = pathlib.Path(__file__).resolve().parents[4]
SERVER = ROOT / "apps/mcp-erp-readonly/server.py"
ERP = os.environ.get("ERP_BASE_URL", "http://localhost:9100")


def _alive():
    try:
        return httpx.get(f"{ERP}/health", timeout=1).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _alive(), reason="ERP 不可达")


@pytest.fixture
def client():
    c = StdioMcpClient(sys.executable, [str(SERVER)], name="erp-readonly", env={"ERP_BASE_URL": ERP, "ERP_API_KEY": "east-demo-key"})
    yield c
    c.close()


def _call(name, args, cid="c1"):
    return ToolCall(call_id=cid, name=name, arguments=json.dumps(args))


def test_t32i_server_declares_two_readonly_tools(client):
    tools = {t["name"]: t for t in client.list_tools()}
    assert set(tools) == {"get_product_spec", "get_availability"}
    assert tools["get_product_spec"]["inputSchema"]["required"] == ["model"]
    assert tools["get_product_spec"]["annotations"]["readOnlyHint"] is True


def test_t32i_s01_results_match_local_source(client):
    erp = ErpClient(ERP, "east-demo-key")
    local = ToolRegistry([GetProductSpec(erp), GetAvailability(erp)])
    remote = ToolRegistry(McpToolSource(client).tools())
    sink_l, sink_r = ListSink(), ListSink()
    rt_l = ToolRuntime(local, policy=Policy(), sink=sink_l)
    rt_r = ToolRuntime(remote, policy=Policy(), sink=sink_r)
    for name, args in (("get_product_spec", {"model": "X200"}), ("get_availability", {"model": "X200", "qty": 1})):
        a = rt_l.execute(_call(name, args), timeout_s=5, run_id="L")
        b = rt_r.execute(_call(name, args), timeout_s=5, run_id="R")
        assert a.ok and b.ok and a.data == b.data, name
    assert [e["type"] for e in sink_l.events] == [e["type"] for e in sink_r.events]
    assert {e["source"] for e in sink_r.events if e["type"] == "policy.decided"} == {"mcp:erp-readonly"}


def test_t32i_business_error_keeps_category_through_mcp(client):
    rt = ToolRuntime(ToolRegistry(McpToolSource(client).tools()), policy=Policy(), sink=ListSink())
    r = rt.execute(_call("get_product_spec", {"model": "X999"}), timeout_s=5)
    assert r.ok is False and r.error.category == "not_found" and r.error.code == "product_not_found"


def test_t32i_closed_server_is_source_unavailable(client):
    tools = McpToolSource(client).tools()
    client.close()
    rt = ToolRuntime(ToolRegistry(tools), policy=Policy(), sink=ListSink())
    r = rt.execute(_call("get_product_spec", {"model": "X200"}), timeout_s=2)
    assert r.ok is False and r.error.category == "source_unavailable"
