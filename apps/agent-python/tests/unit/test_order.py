"""1.9 独立变体 get_order 的参考实现（任务书 docs/specs/w01-order.md）：注册后可用、Loop 不加特判、note 是数据。"""
import inspect

from agent_app.agent import AgentLoop
from agent_app.contracts import ToolCall
from agent_app.doubles import ScriptedModel, final, tool_calls
from agent_app.tools import ToolExecutor, ToolRegistry
from agent_app.tools.order import GetOrder


def test_order_tool_answers_status_promised_date_and_shipments(erp):
    reg = ToolRegistry([GetOrder(erp)])
    model = ScriptedModel([tool_calls(("get_order", {"order_id": "ORD-10086"})), final("已发运，运单 SF1234567890。")])
    r = AgentLoop(model, ToolExecutor(reg), reg.specs()).run("ORD-10086 到哪了")
    assert r.status == "completed" and erp.calls["get_order"] == 1
    content = model.requests[1]["messages"][3]["content"]
    assert '"status": "shipped"' in content and '"promised_delivery_date"' in content and "SF1234567890" in content
    assert '"note": "' in content                                   # 备注原样返回，是数据


def test_order_not_found_and_loop_has_no_special_case(erp):
    r = ToolExecutor(ToolRegistry([GetOrder(erp)])).execute(ToolCall("c", "get_order", '{"order_id": "ORD-99999"}'), timeout_s=1)
    assert r.error.category == "not_found" and r.error.code == "order_not_found"
    assert "get_order" not in inspect.getsource(AgentLoop)
