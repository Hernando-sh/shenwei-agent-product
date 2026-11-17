"""ToolRegistry：按名字找工具。执行管线在 runtime.py（ToolRuntime）；ToolExecutor 是 W1 名字的兼容别名。"""
from __future__ import annotations

from agent_app.contracts import EventSink, Tool, ToolSpec


class NullSink:
    def emit(self, event_type: str, **data) -> None:
        pass


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for t in tools or []:
            self.register(t)

    def register(self, tool: Tool) -> None:
        self._tools[tool.spec.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    def __contains__(self, name: str) -> bool:
        return name in self._tools


def ToolExecutor(registry: ToolRegistry, sink: EventSink | None = None):
    """W1 的构造方式：ToolExecutor(registry, sink)。2.2 起返回带默认策略表、询问模式的 ToolRuntime——
    同一条管线，没有绕过策略的第二个执行器。"""
    from agent_app.policy import Policy
    from .runtime import ToolRuntime
    return ToolRuntime(registry, policy=Policy(), sink=sink)
