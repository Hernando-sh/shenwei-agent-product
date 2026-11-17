"""共享契约：类型与 Protocol。改这里要列出生产者、消费者与兼容策略（AGENTS.md）。"""
from .types import (Budget, Changeset, ConfirmToken, ModelResponse, PolicyDecision, ResponseKind, RunResult, RunStatus,
                    StopReason, ToolCall, ToolError, ToolKind, ToolResult, ToolSpec, Usage)
from .protocols import (ConfirmationAdapter, ErpGateway, EventSink, KnowledgeGateway, ModelClient, PolicyProtocol, Tool,
                        ToolFailure)

__all__ = ["Budget", "Changeset", "ConfirmToken", "ModelResponse", "PolicyDecision", "ResponseKind", "RunResult",
           "RunStatus", "StopReason", "ToolCall", "ToolError", "ToolKind", "ToolResult", "ToolSpec", "Usage",
           "ConfirmationAdapter", "ErpGateway", "EventSink", "KnowledgeGateway", "ModelClient", "PolicyProtocol", "Tool",
           "ToolFailure"]
