"""create_quote：把通过规则与确认的草案写进 ERP 报价台账。权威事实 = ERP POST /v1/quotes 的返回。
写请求没有金额字段（ERP 自己按规程算并记台账）；Idempotency-Key 与 X-Actor 由运行时的 Operation 给。
第一次尝试前再执行一遍前置规则（防模型跳过 price_quote 直接保存）；核实（attempt ≥ 2）不再判规则——同键重放要拿回原结果。"""
from __future__ import annotations

from agent_app.contracts import ErpGateway, Operation, ToolFailure, ToolSpec
from agent_app.quote import check_customer_master, check_duplicate, check_overdue, normalize_lines

SPEC = ToolSpec(
    name="create_quote",
    description=("把报价草案保存进 ERP 报价台账（写操作，需操作者确认）。参数只有客户编号与行（型号 + 数量），价格由 ERP 按"
                 "报价规程算并记录；不能传单价、折扣或金额。成功返回报价号、版本、有效期、金额与条件；保存结果未知时由系统核实，"
                 "不要再次调用。"),
    parameters={"type": "object",
                "properties": {
                    "customer_id": {"type": "string", "description": "客户编号，如 C-E001"},
                    "lines": {"type": "array", "description": "报价行：型号与数量，应与已确认的草案一致",
                              "items": {"type": "object",
                                        "properties": {"sku": {"type": "string"}, "qty": {"type": "integer", "minimum": 1}},
                                        "required": ["sku", "qty"], "additionalProperties": False}},
                    "customer_reference": {"type": "string", "description": "可选，客户方的参考号"}},
                "required": ["customer_id", "lines"], "additionalProperties": False},
)


class CreateQuote:
    spec = SPEC
    kind = "write_external"

    def __init__(self, erp: ErpGateway) -> None:
        self._erp = erp

    def run(self, args: dict, *, timeout_s: float, operation: Operation) -> dict:
        customer_id, lines = args["customer_id"], normalize_lines(args["lines"])
        if operation.attempt == 1:
            hit = self._rules(customer_id, lines, timeout_s=timeout_s)
            if hit is not None:
                return {"customer_id": customer_id, "lines": lines, "outcome": "declined", "rule": hit.rule,
                        "reason": hit.reason, "facts": hit.facts, "recorded": False}
        q = self._erp.create_quote(customer_id, lines, idempotency_key=operation.idempotency_key, actor=operation.actor,
                                   timeout_s=timeout_s, customer_reference=args.get("customer_reference"))
        return {
            "outcome": "saved", "id": q["id"], "quote_id": q["id"], "revision": q.get("revision"), "status": q.get("status"),
            "customer_id": q.get("customer_id"), "valid_until": q.get("valid_until"),
            "lines": [{"line_no": l.get("line_no"), "sku": l.get("sku"), "qty": l.get("qty"), "unit_price": l.get("unit_price"),
                       "amount": l.get("amount"), "conditions": l.get("conditions")} for l in q.get("lines", [])],
            "total_amount": q.get("total_amount"), "currency": q.get("currency"), "incoterm": q.get("incoterm"),
            "payment_terms_code": q.get("payment_terms_code"), "payment_terms": q.get("payment_terms"),
            "price_rule_ref": q.get("price_rule_ref"), "fx_rate": q.get("fx_rate"), "price_date": q.get("price_date"),
            "created_by": q.get("created_by"), "created_at": q.get("created_at"),
            "idempotent_replay": bool(q.get("idempotent_replay")), "recorded": True,
        }

    def _rules(self, customer_id: str, lines: list[dict], *, timeout_s: float):
        customer = self._erp.get_customer(customer_id, timeout_s=timeout_s)
        hit = check_customer_master(customer)
        if hit is None:
            receivables = self._fact("回款", self._erp.get_receivables, customer_id, timeout_s=timeout_s)
            hit = check_overdue(customer, receivables)
        if hit is None:
            page = self._fact("报价台账", self._erp.list_quotes, customer_id, timeout_s=timeout_s)
            hit = check_duplicate(page.get("data", []), customer_id, lines)
        return hit

    @staticmethod
    def _fact(what: str, fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except ToolFailure as f:
            raise ToolFailure(f.error.category, f.error.code,
                              f"规则所需事实查不到（{what}：{f.error.message}）：不保存，不默认放行") from f
