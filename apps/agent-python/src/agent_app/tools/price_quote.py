"""price_quote：算价出草案。权威事实 = ERP /v1/quotes/price（只算不记）。
顺序固定：查客户主数据 → 查应收账龄 → 规则（blocked / credit_hold / overdue）→ 查台账 → 规则（duplicate）→ ERP 算价 → 草案。
规则所需事实查不到 → 失败原样交回（不出草案、不默认放行）。参数里没有任何金额字段，也进不来（guardrails 递归校验）。"""
from __future__ import annotations

from agent_app.contracts import ErpGateway, ToolFailure, ToolSpec
from agent_app.quote import QuoteDraft, check_customer_master, check_duplicate, check_overdue, normalize_lines

SPEC = ToolSpec(
    name="price_quote",
    description=("按 ERP 报价规程为一个客户的若干型号算价并生成报价草案（不保存）。程序先查客户冻结 / 信用 / 逾期回款与"
                 "有效期内的同内容报价，被规则拦下时返回 outcome=declined 与原因；通过则返回 outcome=draft，草案的单价、金额、"
                 "合计、币种、付款条件、贸易术语全部来自 ERP。价格不能指定：没有单价、折扣、金额参数。只读。"),
    parameters={"type": "object",
                "properties": {
                    "customer_id": {"type": "string", "description": "客户编号，如 C-E001（先用 search_customers 落实）"},
                    "lines": {"type": "array", "description": "报价行：型号与数量",
                              "items": {"type": "object",
                                        "properties": {"sku": {"type": "string", "description": "型号，如 X200"},
                                                       "qty": {"type": "integer", "minimum": 1, "description": "数量"}},
                                        "required": ["sku", "qty"], "additionalProperties": False}}},
                "required": ["customer_id", "lines"], "additionalProperties": False},
)


class PriceQuote:
    spec = SPEC

    def __init__(self, erp: ErpGateway) -> None:
        self._erp = erp

    def run(self, args: dict, *, timeout_s: float) -> dict:
        customer_id, lines = args["customer_id"], normalize_lines(args["lines"])
        customer = self._erp.get_customer(customer_id, timeout_s=timeout_s)        # 不存在 → not_found 原样交回
        receivables, page = {}, {}
        hit = check_customer_master(customer)                                       # blocked / credit_hold
        if hit is None:
            receivables = self._fact("回款", self._erp.get_receivables, customer_id, timeout_s=timeout_s)
            hit = check_overdue(customer, receivables)                              # overdue
        if hit is None:
            page = self._fact("报价台账", self._erp.list_quotes, customer_id, timeout_s=timeout_s)
            hit = check_duplicate(page.get("data", []), customer_id, lines)         # duplicate
        base = {"customer_id": customer_id, "legal_name": customer.get("legal_name"), "lines": lines}
        if hit is not None:
            return {**base, "outcome": "declined", "rule": hit.rule, "reason": hit.reason, "facts": hit.facts, "draft": None}
        price = self._erp.price_quote(customer_id, lines, timeout_s=timeout_s)
        draft = QuoteDraft.from_erp(price, legal_name=customer.get("legal_name"))
        return {**base, "outcome": "draft", "rule": None, "reason": None,
                "facts": {"credit_status": receivables.get("credit_status"), "overdue_days": receivables.get("overdue_days"),
                          "existing_quotes": len(page.get("data", []))},
                "draft": draft.to_dict()}

    @staticmethod
    def _fact(what: str, fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except ToolFailure as f:
            raise ToolFailure(f.error.category, f.error.code,
                              f"规则所需事实查不到（{what}：{f.error.message}）：不出草案，不默认放行") from f
