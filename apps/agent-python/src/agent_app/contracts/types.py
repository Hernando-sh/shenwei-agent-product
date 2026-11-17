"""W1 的最小类型。消息本身用 OpenAI chat 格式的 dict（role / content / tool_calls / tool_call_id），
这样在事件快照里看到的就是真正发给模型的东西。"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from enum import StrEnum


class ResponseKind(StrEnum):
    FINAL = "final"            # 有效最终文本
    TOOL_CALLS = "tool_calls"  # 至少一个工具请求（可能伴随文本，先处理工具请求）
    MALFORMED = "malformed"    # 无文本也无工具请求、或无法解析：协议失败，不是"完成"


class StopReason(StrEnum):
    COMPLETED = "completed"            # 得到有效最终答复
    MAX_STEPS = "max_steps"            # 步数耗尽，不再发起新的模型请求
    WALL_CLOCK = "wall_clock"          # 墙钟耗尽
    PROTOCOL_ERROR = "protocol_error"  # 模型响应结构异常
    MODEL_ERROR = "model_error"        # 模型调用 / 网络失败


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"  # 只表示循环得到有效结束响应，不证明业务内容正确
    STOPPED = "stopped"
    FAILED = "failed"


class ToolKind(StrEnum):
    """工具的动作档位（总 spec 第 3 节）。由策略表按名字给，不由来源自己宣告。"""
    READ = "read"                      # 只读：自动放行；超时可有界重试（ADR-002）
    WRITE_INTERNAL = "write_internal"  # 内部写（跟进记录）：询问模式确认，自动模式放行
    WRITE_EXTERNAL = "write_external"  # 对外写（报价台账）：两种模式都确认


@dataclass(frozen=True)
class PolicyDecision:
    """策略对一次工具请求的决定。action：allow / confirm / reject。reason 是程序分支依据，给人看的解释在 message。"""
    action: str
    kind: ToolKind | None
    reason: str
    message: str = ""


@dataclass(frozen=True)
class Changeset:
    """一次写动作在执行前的样子：工具、档位、校验后的参数、摘要。确认绑定 digest；写请求的幂等键用 operation_id。
    digest 只由 tool + 参数算出（和 run / call 无关）；operation_id 每个变更集唯一。"""
    operation_id: str
    run_id: str | None
    call_id: str
    tool: str
    kind: ToolKind | str
    args: dict
    digest: str
    summary: str
    created_at: float            # 真实时钟（time.time）
    requested_by: str            # agent:<run_id>
    version: int = 1

    def to_event(self) -> dict:
        return {"operation_id": self.operation_id, "digest": self.digest, "tool": self.tool, "kind": self.kind,
                "args": self.args, "summary": self.summary, "requested_by": self.requested_by, "version": self.version}

    @staticmethod
    def digest_of(tool: str, args: dict) -> str:
        payload = json.dumps({"tool": tool, "args": args}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def summarize(tool: str, kind: str, args: dict) -> str:
        """给操作者看的一行摘要：工具 + 关键参数。不解释业务，不替业务员拟话。"""
        parts = []
        for k, v in args.items():
            if k == "lines" and isinstance(v, list):
                parts.append("lines=" + ", ".join(f"{l.get('sku')}×{l.get('qty')}" for l in v))
            elif isinstance(v, str) and len(v) > 60:
                parts.append(f"{k}={v[:57]}…")
            else:
                parts.append(f"{k}={json.dumps(v, ensure_ascii=False)}")
        return f"{tool}（{kind}）" + (" · " + " · ".join(parts) if parts else "")

    @classmethod
    def build(cls, *, run_id: str | None, call_id: str, tool: str, kind, args: dict, now: float) -> "Changeset":
        return cls(operation_id=uuid.uuid4().hex[:12], run_id=run_id, call_id=call_id, tool=tool, kind=kind,
                   args=json.loads(json.dumps(args)), digest=cls.digest_of(tool, args),
                   summary=cls.summarize(tool, str(kind), args), created_at=now, requested_by=f"agent:{run_id or '-'}")


@dataclass(frozen=True)
class Operation:
    """一次写操作的标识，由运行时从变更集生成、交给写工具。Idempotency-Key = <run_id>:<operation_id>，X-Actor = agent:<run_id>。
    attempt 从 1 起；核实（同键重放）是 attempt 2，写工具据此跳过已经判过的前置规则。"""
    operation_id: str
    run_id: str | None
    idempotency_key: str
    actor: str
    digest: str
    attempt: int = 1

    def next_attempt(self) -> "Operation":
        return Operation(self.operation_id, self.run_id, self.idempotency_key, self.actor, self.digest, self.attempt + 1)


@dataclass(frozen=True)
class ConfirmToken:
    """操作者对一个变更集的决定。decision：approve / reject / amend / none（没有拿到决定：EOF、超时）。
    approve 只在 operation_id 与 digest 都对、且在有效期内才算数（W2-AC-07）。"""
    decision: str
    operation_id: str | None
    digest: str | None
    decided_at: float | None
    actor: str | None
    amended_args: dict | None = None
    note: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    """给模型看的工具说明。parameters 是 JSON Schema（object）。"""
    name: str
    description: str
    parameters: dict

    def to_openai(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": self.parameters}}


@dataclass(frozen=True)
class ToolCall:
    """模型提出的一个工具请求。arguments 保留模型给的原始字符串：解析与校验是宿主的事。"""
    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ToolError:
    """工具失败的分类。category 是程序分支依据，code 是上游机器码，message 给模型 / 人看。"""
    category: str  # unknown_tool | input_error | rejected | not_found | timeout | upstream_error | malformed | unknown（写：结果未知）
    code: str
    message: str


@dataclass
class ToolResult:
    """带着同一个 call_id 回去的结果。ok=False 时 data 为空、error 必填；错误不是事实。"""
    call_id: str
    name: str
    ok: bool
    data: dict | None = None
    error: ToolError | None = None

    def content(self) -> str:
        body = {"ok": self.ok, "data": self.data} if self.ok else \
               {"ok": False, "error": {"category": self.error.category, "code": self.error.code,
                                       "message": self.error.message}}
        return json.dumps(body, ensure_ascii=False)

    def to_message(self) -> dict:
        return {"role": "tool", "tool_call_id": self.call_id, "name": self.name, "content": self.content()}


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    @property
    def unknown(self) -> bool:
        return self.total_tokens is None


@dataclass
class ModelResponse:
    """归一化后的模型响应。raw 保留原始 JSON 用于事件快照。"""
    kind: ResponseKind
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage | None = None
    finish_reason: str | None = None
    raw: dict | None = None

    def to_assistant_message(self) -> dict:
        msg: dict = {"role": "assistant", "content": self.text or ""}
        if self.tool_calls:
            msg["tool_calls"] = [{"id": c.call_id, "type": "function",
                                  "function": {"name": c.name, "arguments": c.arguments}} for c in self.tool_calls]
        return msg


@dataclass(frozen=True)
class Budget:
    max_steps: int = 6            # 模型请求次数上限
    model_timeout_s: float = 60.0
    tool_timeout_s: float = 5.0
    wall_clock_s: float = 120.0
    tool_retries: int = 0         # 只读工具超时的有界重试；重试计入预算（1.8 起）


@dataclass
class RunResult:
    run_id: str
    status: RunStatus
    stop_reason: StopReason | None
    answer: str | None
    steps: int
    messages: list[dict]
    usage: Usage = field(default_factory=Usage)
    usage_unknown: bool = False
