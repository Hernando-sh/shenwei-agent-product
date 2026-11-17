"""mcp-erp-readonly：一个 stdio MCP 服务，把 ERP 的两个只读查询（规格、库存交期）作为能力对外提供。
它是"能力来源"的最小样本：独立进程、自己连 ERP、不知道调用方是谁；策略、确认、事件都在调用方（agent_app 的 ToolRuntime）。
启动：uv run --project apps/agent-python python apps/mcp-erp-readonly/server.py
环境：ERP_BASE_URL（默认 http://localhost:9100）、ERP_API_KEY（默认 east-demo-key）
错误：ERP 的失败以 isError=true 返回，正文是 {"category","code","message"} 的 JSON，调用方按类别处理。"""
from __future__ import annotations

import functools
import json
import os

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations

READ_ONLY = ToolAnnotations(readOnlyHint=True)

mcp = FastMCP("erp-readonly", instructions="深维 ERP 只读查询：产品规格、库存与交期。")
BASE = os.environ.get("ERP_BASE_URL", "http://localhost:9100")
KEY = os.environ.get("ERP_API_KEY", "east-demo-key")


class ToolError(Exception):
    def __init__(self, category: str, code: str, message: str) -> None:
        super().__init__(message)
        self.payload = {"category": category, "code": code, "message": message}


def _get(path: str, params: dict | None = None, timeout_s: float = 5.0) -> dict:
    try:
        r = httpx.get(BASE + path, params=params, headers={"X-Api-Key": KEY}, timeout=timeout_s)
    except httpx.TimeoutException as e:
        raise ToolError("timeout", "client_timeout", f"ERP 请求超时：{type(e).__name__}") from e
    except httpx.HTTPError as e:
        raise ToolError("upstream_error", "http_error", f"ERP 请求失败：{type(e).__name__}") from e
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code == 404:
        raise ToolError("not_found", body.get("code", "not_found"), body.get("detail", "不存在"))
    if r.status_code in (401, 403):
        raise ToolError("rejected", body.get("code", "unauthorized"), body.get("detail", "ERP 拒绝"))
    if r.status_code == 504 or body.get("code") == "gateway_timeout":
        raise ToolError("timeout", body.get("code", "gateway_timeout"), body.get("detail", "ERP 网关超时"))
    if r.status_code >= 400:
        raise ToolError("upstream_error", body.get("code", str(r.status_code)), body.get("detail", f"ERP 返回 {r.status_code}"))
    if not body:
        raise ToolError("malformed", "not_json", "ERP 返回的不是 JSON")
    return body


def _wrap(fn):
    """业务函数抛 ToolError → isError 结果；其余异常也不让进程死。functools.wraps 保住签名，FastMCP 据此生成 inputSchema。"""
    @functools.wraps(fn)
    def run(*a, **kw):
        try:
            return fn(*a, **kw)
        except ToolError as e:
            return _error(e.payload)
        except Exception as e:  # noqa: BLE001
            return _error({"category": "upstream_error", "code": "server_exception", "message": f"{type(e).__name__}: {e}"})
    return run


def _error(payload: dict) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))], isError=True)


@mcp.tool(name="get_product_spec", description="按型号查产品规格与主数据（名称、类别、结构化参数、挂牌价、生命周期、交期天数、手册编号）。只读。",
          annotations=READ_ONLY)
@_wrap
def get_product_spec(model: str) -> dict:
    p = _get(f"/v1/products/{model.strip()}")
    return {
        "model": p["sku"], "name": p.get("name_cn"), "name_en": p.get("name_en"),
        "category": (p.get("category") or {}).get("name_cn"), "key_spec": p.get("key_spec"),
        "specs": {k: v for k, v in (p.get("specs") or {}).items() if v is not None},
        "list_price": p.get("list_price"), "lifecycle": p.get("lifecycle"), "lead_time_days": p.get("lead_time_days"),
        "doc_ref": p.get("doc_ref"), "spec_source": p.get("spec_source"), "source_version": p.get("updated_at"),
    }


@mcp.tool(name="get_availability", description="按型号查当前库存与交期：可用量、在途、整单最早发运日（深圳发运，不含国际运输）、依据。只读，时点数据。",
          annotations=READ_ONLY)
@_wrap
def get_availability(model: str, qty: int = 1) -> dict:
    inv = _get(f"/v1/inventory/{model.strip()}", {"qty": int(qty or 1)})
    return {
        "model": inv["sku"], "warehouse": inv.get("warehouse"), "requested_qty": inv.get("requested_qty"),
        "on_hand": inv.get("on_hand"), "reserved": inv.get("reserved"), "available": inv.get("available"),
        "incoming": inv.get("incoming", []), "earliest_ship_date": inv.get("earliest_ship_date"),
        "complete_ship_date": inv.get("complete_ship_date"), "basis_code": inv.get("basis_code"),
        "basis_text": inv.get("basis_text"), "schedule_lines": inv.get("schedule_lines", []), "incoterm": inv.get("incoterm"),
        "observed_at": inv.get("as_of"),
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
