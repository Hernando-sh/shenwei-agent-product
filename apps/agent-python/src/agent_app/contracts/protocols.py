"""四个边界。换模型只改 ModelClient 的实现；换 ERP 只改 ErpGateway 的实现；
CLI 换网页只换调用方；不联网测 Loop 用 doubles 里的替身实现同一组 Protocol。"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .types import Changeset, ConfirmToken, ModelResponse, Operation, PolicyDecision, ToolError, ToolSpec


class ToolFailure(Exception):
    """工具内部用来向执行层报告失败；执行层把它变成 ToolResult(ok=False)。"""

    def __init__(self, category: str, code: str, message: str) -> None:
        super().__init__(message)
        self.error = ToolError(category=category, code=code, message=message)


@runtime_checkable
class ModelClient(Protocol):
    def generate(self, messages: list[dict], tools: list[ToolSpec], *, timeout_s: float) -> ModelResponse: ...


@runtime_checkable
class ErpGateway(Protocol):
    """ERP 访问。真实实现走 HTTP；FakeERP 读 fixture。失败抛 ToolFailure。
    W1 四个只读；W2 加客户 / 回款 / 台账三类只读（2.1）。生产者：ErpClient、FakeERP；消费者：tools/*。"""
    def get_product(self, sku: str, *, timeout_s: float) -> dict: ...
    def get_inventory(self, sku: str, qty: int, *, timeout_s: float) -> dict: ...
    def get_shipment(self, tracking_no: str, *, timeout_s: float) -> dict: ...
    def get_order(self, order_id: str, *, timeout_s: float) -> dict: ...
    # ---- W2 · 2.1 ----
    def search_customers(self, q: str, *, country_code: str | None = None, timeout_s: float) -> dict: ...
    def get_customer(self, customer_id: str, *, timeout_s: float) -> dict: ...
    def get_receivables(self, customer_id: str, *, timeout_s: float) -> dict: ...
    def list_quotes(self, customer_id: str, *, status: str | None = None, timeout_s: float) -> dict: ...
    # ---- W2 · 2.4 算价（只算不记，recorded=false）----
    def price_quote(self, customer_id: str, lines: list[dict], *, timeout_s: float) -> dict: ...
    # ---- W2 · 2.6 写台账。返回体多一个 idempotent_replay 布尔；5xx / 超时 / 断连 → ToolFailure("unknown", …) ----
    def create_quote(self, customer_id: str, lines: list[dict], *, idempotency_key: str, actor: str,
                     timeout_s: float, customer_reference: str | None = None, note: str | None = None) -> dict: ...


@runtime_checkable
class KnowledgeGateway(Protocol):
    """知识服务访问（2.3）。返回 /v1/search 的原始响应体；失败抛 ToolFailure。生产者：KnowledgeClient、FakeKnowledge。"""
    def search(self, query: str, *, top_k: int = 5, domain: list[str] | None = None, doc_ids: list[str] | None = None,
               order_date: str | None = None, timeout_s: float) -> dict: ...


@runtime_checkable
class Tool(Protocol):
    """spec 给模型看；可选属性 source（缺省 local）只用于记录，策略不看它。"""
    spec: ToolSpec
    def run(self, args: dict, *, timeout_s: float) -> dict: ...


@runtime_checkable
class WriteTool(Protocol):
    """写工具：多收一个 Operation（幂等键、操作者、尝试次数）。运行时按策略表的档位决定调哪种签名。"""
    spec: ToolSpec
    def run(self, args: dict, *, timeout_s: float, operation: Operation) -> dict: ...


@runtime_checkable
class OperationLedger(Protocol):
    """操作台账：每个写操作的状态变化追加一行（pending → committed / unknown / failed）。"""
    def record(self, **row) -> None: ...


@runtime_checkable
class PolicyProtocol(Protocol):
    """对一次已通过校验的工具请求做决定。输入只有名字、参数与当前模式；来源与来源宣告的类别不参与决定。"""
    def decide(self, name: str, args: dict, *, mode: str) -> PolicyDecision: ...


@runtime_checkable
class ConfirmationAdapter(Protocol):
    """把变更集交给操作者、拿回决定。2.5 本地终端同步问；W5 换成 Java 确认服务，管线不变（ADR-005）。"""
    def request(self, changeset: Changeset, *, ttl_s: float) -> ConfirmToken: ...


@runtime_checkable
class EventSink(Protocol):
    def emit(self, event_type: str, **data) -> None: ...
