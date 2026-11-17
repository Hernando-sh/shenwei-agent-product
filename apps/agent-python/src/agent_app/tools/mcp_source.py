"""MCP 能力来源：把一个 MCP 服务宣告的工具变成本地 Tool 对象，注册进同一个 ToolRegistry，走同一条 ToolRuntime 管线。
来源只提供 spec 与执行；档位由策略表按名字给，来源自己的 readOnlyHint 不参与决定（W2-AC-11）。
失败类别：来源断开 / 进程不在 → source_unavailable；返回形状不对 → protocol_error；工具自己报的业务错误按它给的类别透传。
StdioMcpClient 用官方 SDK（mcp 1.28，stdio）；同步调用方通过一个后台事件循环线程使用它。"""
from __future__ import annotations

import asyncio
import json
import os
import threading
from contextlib import AsyncExitStack
from typing import Protocol

from agent_app.contracts import ToolFailure, ToolSpec


class McpUnavailable(Exception):
    """来源不可用：进程没起来、断开、超时。"""


class McpClient(Protocol):
    name: str
    def list_tools(self) -> list[dict]: ...                       # [{name, description, inputSchema, annotations?}]
    def call_tool(self, name: str, arguments: dict, *, timeout_s: float) -> dict: ...   # {isError, content[], structuredContent?}


class McpTool:
    def __init__(self, client: McpClient, spec: ToolSpec, declared: dict) -> None:
        self._client, self.spec, self.declared = client, spec, declared
        self.source = f"mcp:{client.name}"

    def run(self, args: dict, *, timeout_s: float, operation=None) -> dict:
        try:
            raw = self._client.call_tool(self.spec.name, args, timeout_s=timeout_s)
        except McpUnavailable as e:
            raise ToolFailure("source_unavailable", "mcp_unavailable", f"MCP 来源 {self._client.name} 不可用：{e}") from e
        except ToolFailure:
            raise
        except Exception as e:  # noqa: BLE001  SDK 的协议异常
            raise ToolFailure("protocol_error", "mcp_error", f"MCP 来源 {self._client.name} 协议错误：{type(e).__name__}: {e}") from e
        return parse_result(raw, source=self._client.name)


def parse_result(raw, *, source: str) -> dict:
    if not isinstance(raw, dict) or not isinstance(raw.get("content"), list):
        raise ToolFailure("protocol_error", "bad_result", f"MCP 来源 {source} 返回的不是 CallToolResult")
    texts = [c.get("text") for c in raw["content"] if isinstance(c, dict) and c.get("type") == "text"]
    if raw.get("isError"):
        payload = _json_or_none(texts[0]) if texts else None
        if isinstance(payload, dict) and {"category", "code", "message"} <= set(payload):
            raise ToolFailure(payload["category"], payload["code"], payload["message"])      # 业务错误按类别透传
        raise ToolFailure("upstream_error", "tool_error", texts[0] if texts else "MCP 工具报错但没有说明")
    structured = raw.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    if not texts:
        raise ToolFailure("protocol_error", "empty_content", f"MCP 来源 {source} 返回了空内容")
    payload = _json_or_none(texts[0])
    if not isinstance(payload, dict):
        raise ToolFailure("protocol_error", "not_json_object", f"MCP 来源 {source} 返回的正文不是 JSON 对象")
    return payload


def _json_or_none(text):
    try:
        return json.loads(text) if isinstance(text, str) else None
    except json.JSONDecodeError:
        return None


class McpToolSource:
    def __init__(self, client: McpClient) -> None:
        self._client = client

    def tools(self, only: list[str] | None = None) -> list[McpTool]:
        try:
            declared = self._client.list_tools()
        except McpUnavailable as e:
            raise ToolFailure("source_unavailable", "mcp_unavailable", f"MCP 来源 {self._client.name} 不可用：{e}") from e
        out = []
        for d in declared:
            if only and d["name"] not in only:
                continue
            schema = d.get("inputSchema") or {"type": "object", "properties": {}}
            schema = {**schema, "additionalProperties": schema.get("additionalProperties", False)}   # 来源没说就按严格
            out.append(McpTool(self._client, ToolSpec(d["name"], d.get("description") or "", schema), d))
        return out


class StdioMcpClient:
    """起一个 stdio MCP 服务子进程并保持会话。SDK 是 async 的，这里用一个后台事件循环线程把它变成同步调用。"""

    def __init__(self, command: str, args: list[str], *, name: str = "server", env: dict | None = None,
                 connect_timeout_s: float = 20.0) -> None:
        self.name = name
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name=f"mcp-{name}", daemon=True)
        self._thread.start()
        self._stack: AsyncExitStack | None = None
        self._session = None
        full_env = {**os.environ, **(env or {})}
        try:
            self._run(self._connect(command, args, full_env), timeout_s=connect_timeout_s)
        except Exception as e:
            self.close()
            raise McpUnavailable(f"连接 MCP 服务失败：{type(e).__name__}: {e}") from e

    async def _connect(self, command, args, env):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        self._stack = AsyncExitStack()
        read, write = await self._stack.enter_async_context(
            stdio_client(StdioServerParameters(command=command, args=args, env=env)))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()

    def _run(self, coro, *, timeout_s: float):
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return fut.result(timeout=timeout_s)
        except TimeoutError as e:
            fut.cancel()
            raise McpUnavailable(f"MCP 调用超时（{timeout_s}s）") from e

    def list_tools(self) -> list[dict]:
        if self._session is None:
            raise McpUnavailable("没有会话")
        try:
            res = self._run(self._session.list_tools(), timeout_s=10)
        except McpUnavailable:
            raise
        except Exception as e:  # noqa: BLE001
            raise McpUnavailable(f"{type(e).__name__}: {e}") from e
        return [{"name": t.name, "description": t.description, "inputSchema": t.inputSchema,
                 "annotations": (t.annotations.model_dump() if t.annotations else None)} for t in res.tools]

    def call_tool(self, name: str, arguments: dict, *, timeout_s: float) -> dict:
        if self._session is None:
            raise McpUnavailable("没有会话")
        import datetime as dt
        try:
            res = self._run(self._session.call_tool(name, arguments, read_timeout_seconds=dt.timedelta(seconds=timeout_s)),
                            timeout_s=timeout_s + 1)
        except McpUnavailable:
            raise
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if "closed" in msg.lower() or "broken" in msg.lower() or "EOF" in msg:
                raise McpUnavailable(f"{type(e).__name__}: {msg}") from e
            raise                                                     # 其余按协议错误交给 McpTool
        return {"isError": bool(res.isError), "content": [c.model_dump() for c in res.content],
                "structuredContent": res.structuredContent}

    def close(self) -> None:
        if self._stack is not None:
            try:
                self._run(self._stack.aclose(), timeout_s=5)
            except Exception:  # noqa: BLE001
                pass
            self._stack, self._session = None, None
        self._loop.call_soon_threadsafe(self._loop.stop)
