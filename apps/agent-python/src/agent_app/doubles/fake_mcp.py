"""FakeMcpClient：假的 MCP 服务——宣告任意工具、按名字给结果、可模拟断开与畸形返回。实现 McpClient。"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field

from agent_app.tools.mcp_source import McpUnavailable


@dataclass
class FakeMcpClient:
    name: str
    tools: list[dict]
    handlers: dict = field(default_factory=dict)         # name → fn(args) -> dict（正常业务结果）
    raw_handlers: dict = field(default_factory=dict)     # name → fn(args) -> 任意原始返回（覆盖 handlers）
    connected: bool = True
    calls: Counter = field(default_factory=Counter)

    def on(self, name: str, fn) -> None:
        self.handlers[name] = fn

    def on_raw(self, name: str, fn) -> None:
        self.raw_handlers[name] = fn

    def disconnect(self) -> None:
        self.connected = False

    def list_tools(self) -> list[dict]:
        if not self.connected:
            raise McpUnavailable("server closed")
        return [dict(t) for t in self.tools]

    def call_tool(self, name: str, arguments: dict, *, timeout_s: float) -> dict:
        if not self.connected:
            raise McpUnavailable("server closed")
        self.calls[name] += 1
        if name in self.raw_handlers:
            return self.raw_handlers[name](arguments)
        data = self.handlers[name](arguments)
        return {"isError": False, "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
                "structuredContent": data}
