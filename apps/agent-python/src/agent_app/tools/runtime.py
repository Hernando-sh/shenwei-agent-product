"""ToolRuntime：工具请求的唯一管线（W2-AC-02）。
    解析 → 校验 → 策略 → 确认决策 → 执行 → 结果
每个工具请求、不论来源，都从这里过；被拒绝的也留事件（I2）。Loop 只认 execute(...) 的签名，和 W1 的 ToolExecutor 相同。
2.2：策略 allow / reject；confirm 在没有确认通道时按拒绝处理（安全默认）。2.5 接确认适配器；2.6 接写入与未知结果。"""
from __future__ import annotations

import time

from agent_app.contracts import (EventSink, PolicyProtocol, Tool, ToolCall, ToolError, ToolFailure, ToolKind,
# generated: 0fUa1
                                 ToolResult)
from agent_app.guardrails import validate_args

from .registry import NullSink, ToolRegistry


class ToolRuntime:
    def __init__(self, registry: ToolRegistry, *, policy: PolicyProtocol, sink: EventSink | None = None,
                 mode: str = "ask") -> None:
        self._registry = registry
        self._policy = policy
        self._sink = sink or NullSink()
        self.mode = mode

    # ---- 管线 ----
    def execute(self, call: ToolCall, *, timeout_s: float, run_id: str | None = None, retries: int = 0) -> ToolResult:
        emit = self._sink.emit
        base = dict(run_id=run_id, call_id=call.call_id, name=call.name)
        emit("tool.requested", **base, arguments=call.arguments)                    # I2：先落日志再做任何事

        tool = self._registry.get(call.name)                                        # 解析
        if tool is None:
            return self._reject(base, "unknown_tool", ToolError("unknown_tool", "unknown_tool", f"工具 {call.name} 未注册"))
        try:                                                                        # 校验
            args = validate_args(tool.spec, call.arguments)
        except ToolFailure as f:
            return self._reject(base, "input", f.error)

        source = getattr(tool, "source", "local")                                   # 策略：按名字，不看来源宣告
        decision = self._policy.decide(call.name, args, mode=self.mode)
        emit("policy.decided", **base, action=decision.action, kind=decision.kind, reason=decision.reason,
             mode=self.mode, source=source)
        if decision.action == "reject":
            return self._reject(base, "policy", ToolError("rejected", decision.reason, decision.message))
        if decision.action == "confirm":                                            # 确认决策（2.5 接适配器）
            return self._reject(base, "policy", ToolError("rejected", "confirmation_required",
                                                          "写动作需要操作者确认，本运行时没有确认通道，不执行"))
        return self._run(tool, args, base, timeout_s=timeout_s,
                         retries=retries if decision.kind == ToolKind.READ else 0)   # ADR-002：只有只读才重试

    # ---- 分支 ----
    def _reject(self, base: dict, reason: str, err: ToolError) -> ToolResult:
        self._sink.emit("tool.rejected", **base, reason=reason, category=err.category, code=err.code, message=err.message)
        return ToolResult(base["call_id"], base["name"], ok=False, error=err)

    def _run(self, tool: Tool, args: dict, base: dict, *, timeout_s: float, retries: int) -> ToolResult:
        attempt = 0
        while True:
            attempt += 1
            t0 = time.monotonic()
            try:
                data = tool.run(args, timeout_s=timeout_s)
            except ToolFailure as f:
                ms = int((time.monotonic() - t0) * 1000)
                if f.error.category == "timeout" and attempt <= retries:
                    self._sink.emit("tool.retry", **base, attempt=attempt, code=f.error.code, duration_ms=ms)
                    continue
                self._sink.emit("tool.executed", **base, ok=False, category=f.error.category, code=f.error.code,
                                message=f.error.message, attempts=attempt, duration_ms=ms)
                return ToolResult(base["call_id"], base["name"], ok=False, error=f.error)
            self._sink.emit("tool.executed", **base, ok=True, data=data, attempts=attempt,
                            duration_ms=int((time.monotonic() - t0) * 1000))
            return ToolResult(base["call_id"], base["name"], ok=True, data=data)
