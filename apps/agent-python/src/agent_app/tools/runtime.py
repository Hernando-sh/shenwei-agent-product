"""ToolRuntime：工具请求的唯一管线（W2-AC-02）。
    解析 → 校验 → 策略 → 确认决策 → 执行 → 结果
每个工具请求、不论来源，都从这里过；被拒绝的也留事件（I2）。Loop 只认 execute(...) 的签名，和 W1 的 ToolExecutor 相同。
2.2：策略 allow / reject。2.5：confirm → 变更集 → 确认适配器 → 令牌校验（绑定摘要与有效期）→ 执行；没有适配器按拒绝处理。
2.6：写入带 Operation（幂等键 <run_id>:<operation_id>、X-Actor agent:<run_id>）；结果未知（502 / 超时）→ operation.unknown →
同键核实一次 → operation.verified；核实仍失败 → failed，需人工核对台账。写不进只读重试（ADR-002 / ADR-006）。
业务结果（周 spec §5）由运行时在能判定时写进独立事件 run.outcome：resolved / declined / cancelled；没有该事件且 run 非 completed → failed。"""
from __future__ import annotations

import json
import time

from agent_app.confirm import build_changeset, validate_token
from agent_app.contracts import (ConfirmationAdapter, EventSink, Operation, OperationLedger, PolicyProtocol, Tool,
                                 ToolCall, ToolError, ToolFailure, ToolKind, ToolResult)
from agent_app.guardrails import validate_args
from agent_app.ops.ledger import NullLedger

from .registry import NullSink, ToolRegistry

MODES = ("ask", "auto")
WRITE_KINDS = (ToolKind.WRITE_INTERNAL, ToolKind.WRITE_EXTERNAL)


class ToolRuntime:
    def __init__(self, registry: ToolRegistry, *, policy: PolicyProtocol, sink: EventSink | None = None,
                 mode: str = "ask", confirmer: ConfirmationAdapter | None = None, confirm_ttl_s: float = 600.0,
                 clock=time.time, ledger: OperationLedger | None = None) -> None:
        self._registry = registry
        self._policy = policy
        self._sink = sink or NullSink()
        self.mode = mode
        self._confirmer = confirmer
        self.confirm_ttl_s = confirm_ttl_s      # 周 spec §5：确认有效期 10 分钟，真实时钟
        self._clock = clock
        self._ledger = ledger or NullLedger()

    def set_mode(self, mode: str, *, by: str, run_id: str | None = None) -> None:
        if mode not in MODES:
            raise ValueError(f"未知模式 {mode}")
        self._sink.emit("mode.changed", run_id=run_id, **{"from": self.mode, "to": mode}, by=by)
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
        if decision.action == "confirm":                                            # 确认决策
            return self._confirm_and_run(tool, args, base, decision.kind, timeout_s=timeout_s)
        if decision.kind in WRITE_KINDS:                                            # 放行的写（自动模式下的内部写）
            cs = build_changeset(run_id=base["run_id"], call_id=base["call_id"], tool=base["name"], kind=decision.kind,
                                 args=args, now=self._clock())
            emit("changeset.created", **base, **cs.to_event())
            return self._write(tool, args, base, decision.kind, cs)
        result = self._run(tool, args, base, timeout_s=timeout_s, retries=retries)  # 只读：ADR-002 有界重试
        self._outcome_from_result(base, decision.kind, result)
        return result

    # ---- 确认 ----
    def _confirm_and_run(self, tool: Tool, args: dict, base: dict, kind, *, timeout_s: float) -> ToolResult:
        emit = self._sink.emit
        now = self._clock()
        cs = build_changeset(run_id=base["run_id"], call_id=base["call_id"], tool=base["name"], kind=kind, args=args, now=now)
        emit("changeset.created", **base, **cs.to_event())
        if self._confirmer is None:
            return self._reject(base, "policy", ToolError("rejected", "confirmation_required",
                                                          "写动作需要操作者确认，本运行时没有确认通道，不执行"))
        emit("confirmation.requested", **base, operation_id=cs.operation_id, digest=cs.digest, mode=self.mode,
             ttl_s=self.confirm_ttl_s)
        token = self._confirmer.request(cs, ttl_s=self.confirm_ttl_s)
        if token.decision == "reject":
            emit("confirmation.rejected", **base, operation_id=cs.operation_id, actor=token.actor, note=token.note)
            res = self._reject(base, "confirmation", ToolError(
                "rejected", "confirmation_rejected", f"操作者拒绝了这次写入{('：' + token.note) if token.note else ''}。"
                "已取消，不要再次请求同一写入；如实告知业务员已取消。"))
            self._outcome(base, "cancelled", f"操作者拒绝了 {cs.summary}")
            return res
        if token.decision == "amend":
            emit("confirmation.amended", **base, operation_id=cs.operation_id, actor=token.actor, amended_args=token.amended_args)
            return self._reject(base, "confirmation", ToolError(
                "rejected", "confirmation_amended",
                f"操作者在确认时要求修改参数：{json.dumps(token.amended_args, ensure_ascii=False)}。原变更集已作废；"
                "请按修改后的参数重新算价出草案，再重新请求保存（会再次确认）。"))
        reason = validate_token(token, cs, now=self._clock(), ttl_s=self.confirm_ttl_s)
        if reason is not None:
            emit("confirmation.invalid", **base, operation_id=cs.operation_id, digest=cs.digest, reason=reason,
                 token_operation_id=token.operation_id, token_digest=token.digest, decision=token.decision)
            if token.decision == "none":
                return self._reject(base, "confirmation", ToolError(
                    "rejected", "confirmation_missing", "没有拿到操作者的决定（非交互或超时），不执行写入；需要重新确认。"))
            return self._reject(base, "confirmation", ToolError(
                "rejected", "confirmation_invalid", f"确认无效（{reason}）：确认绑定变更集的摘要与有效期，不能跨参数复用或过期使用。"
                "需要重新确认。"))
        emit("confirmation.approved", **base, operation_id=cs.operation_id, digest=cs.digest, actor=token.actor,
             decided_at=token.decided_at)
        return self._write(tool, args, base, kind, cs, timeout_s=timeout_s)

    # ---- 写：带操作标识；未知结果同键核实一次（ADR-006）----
    def _write(self, tool: Tool, args: dict, base: dict, kind, cs, *, timeout_s: float = 5.0) -> ToolResult:
        emit, ledger = self._sink.emit, self._ledger
        run_id = base["run_id"] or "-"
        op = Operation(operation_id=cs.operation_id, run_id=base["run_id"], idempotency_key=f"{run_id}:{cs.operation_id}",
                       actor=f"agent:{run_id}", digest=cs.digest)
        row = dict(operation_id=op.operation_id, run_id=op.run_id, tool=base["name"], idempotency_key=op.idempotency_key,
                   digest=op.digest)
        ledger.record(**row, status="pending", attempt=1)
        emit("operation.started", **base, operation_id=op.operation_id, idempotency_key=op.idempotency_key, actor=op.actor,
             kind=kind)
        t0 = time.monotonic()
        try:
            data = tool.run(args, timeout_s=timeout_s, operation=op)
        except ToolFailure as f:
            ms = int((time.monotonic() - t0) * 1000)
            if f.error.category != "unknown":                                      # 明确失败：没写进去，不核实
                ledger.record(**row, status="failed", attempt=1, code=f.error.code, message=f.error.message)
                emit("tool.executed", **base, ok=False, category=f.error.category, code=f.error.code,
                     message=f.error.message, attempts=1, duration_ms=ms)
                return ToolResult(base["call_id"], base["name"], ok=False, error=f.error)
            ledger.record(**row, status="unknown", attempt=1, code=f.error.code, message=f.error.message)
            emit("operation.unknown", **base, operation_id=op.operation_id, idempotency_key=op.idempotency_key,
                 code=f.error.code, message=f.error.message, attempt=1, duration_ms=ms)
            return self._verify(tool, args, base, kind, op, row, timeout_s=timeout_s)
        ms = int((time.monotonic() - t0) * 1000)
        return self._written(base, kind, op, row, data, ms, attempts=1)

    def _verify(self, tool: Tool, args: dict, base: dict, kind, op: Operation, row: dict, *, timeout_s: float) -> ToolResult:
        """同一个幂等键再发一次（attempt 2）：已提交 → 拿回原结果（replay）；未提交 → 这次是新执行。只核实一次。"""
        emit, ledger = self._sink.emit, self._ledger
        op2 = op.next_attempt()
        t0 = time.monotonic()
        try:
            data = tool.run(args, timeout_s=timeout_s, operation=op2)
        except ToolFailure as f:
            ms = int((time.monotonic() - t0) * 1000)
            still_unknown = f.error.category == "unknown"
            ledger.record(**row, status="unknown" if still_unknown else "failed", attempt=2, code=f.error.code,
                          message=f.error.message)
            emit("operation.verified", **base, operation_id=op.operation_id, committed=None if still_unknown else False,
                 replayed=None, record_id=None, code=f.error.code, attempt=2, duration_ms=ms)
            err = ToolError("unknown" if still_unknown else f.error.category,
                            "verify_failed" if still_unknown else f.error.code,
                            (f"保存结果仍未知（核实也失败：{f.error.message}）。不要再次保存；需到 ERP 报价台账人工核对 "
                             f"Idempotency-Key {op.idempotency_key}。") if still_unknown else
                            f"核实表明未保存：{f.error.message}")
            emit("tool.executed", **base, ok=False, category=err.category, code=err.code, message=err.message,
                 attempts=2, duration_ms=ms)
            self._outcome(base, "failed", err.message, operation_id=op.operation_id)
            return ToolResult(base["call_id"], base["name"], ok=False, error=err)
        ms = int((time.monotonic() - t0) * 1000)
        emit("operation.verified", **base, operation_id=op.operation_id, committed=True,
             replayed=bool(data.get("idempotent_replay")) if isinstance(data, dict) else None,
             record_id=data.get("id") if isinstance(data, dict) else None, attempt=2, duration_ms=ms)
        return self._written(base, kind, op, row, data, ms, attempts=2)

    def _written(self, base: dict, kind, op: Operation, row: dict, data, ms: int, *, attempts: int) -> ToolResult:
        record_id = data.get("id") if isinstance(data, dict) else None
        declined = isinstance(data, dict) and data.get("outcome") == "declined"
        self._ledger.record(**row, status="declined" if declined else "committed", attempt=attempts, record_id=record_id)
        self._sink.emit("tool.executed", **base, ok=True, data=data, attempts=attempts, duration_ms=ms)
        result = ToolResult(base["call_id"], base["name"], ok=True, data=data)
        self._outcome_from_result(base, kind, result, operation_id=op.operation_id)
        return result

    # ---- 业务结果 ----
    def _outcome(self, base: dict, outcome: str, detail: str, **extra) -> None:
        self._sink.emit("run.outcome", run_id=base["run_id"], call_id=base["call_id"], name=base["name"],
                        outcome=outcome, detail=detail, **extra)

    def _outcome_from_result(self, base: dict, kind, result: ToolResult, **extra) -> None:
        if not result.ok or not isinstance(result.data, dict):
            return
        if result.data.get("outcome") == "declined":                               # 规则拦下（约定字段，不认工具名）
            self._outcome(base, "declined", result.data.get("reason") or "被规则拦下", rule=result.data.get("rule"), **extra)
        elif kind in WRITE_KINDS:
            self._outcome(base, "resolved", f"{base['name']} 已写入", record_id=result.data.get("id"), **extra)

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
