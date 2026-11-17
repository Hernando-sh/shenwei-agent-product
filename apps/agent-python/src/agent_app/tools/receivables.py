"""get_receivables：应收账龄。权威事实 = ERP /v1/customers/{id}/receivables。
逾期天数取最老一张未清发票；这是算价前规则（逾期不出草案）的事实来源，时点数据带观测时间。"""
from __future__ import annotations

from agent_app.contracts import ErpGateway, ToolSpec

SPEC = ToolSpec(
    name="get_receivables",
    description=("按客户编号查应收账龄：信用状态（clear / open / overdue）、逾期天数、逾期金额、账龄分桶、"
                 "未清发票明细。只读，时点数据。"),
    parameters={"type": "object",
                "properties": {"customer_id": {"type": "string", "description": "客户编号，如 C-E003"}},
                "required": ["customer_id"], "additionalProperties": False},
)


class GetReceivables:
    spec = SPEC

    def __init__(self, erp: ErpGateway) -> None:
        self._erp = erp

    def run(self, args: dict, *, timeout_s: float) -> dict:
        r = self._erp.get_receivables(args["customer_id"], timeout_s=timeout_s)
        return {
            "customer_id": r["customer_id"], "legal_name": r.get("legal_name"), "currency": r.get("currency"),
            "credit_status": r.get("credit_status"), "overdue_days": r.get("overdue_days"),
            "overdue_amount": r.get("overdue_amount"), "ar_balance": r.get("ar_balance"),
            "credit_limit": r.get("credit_limit"), "exposure": r.get("exposure"),
            "aging": r.get("aging"),
            "open_items": [{"id": i.get("id"), "due_date": i.get("due_date"), "open_amount": i.get("open_amount"),
                            "overdue_days": i.get("overdue_days")} for i in r.get("open_items", [])],
            "payment_terms_code": r.get("payment_terms_code"), "last_payment_at": r.get("last_payment_at"),
            "observed_at": r.get("as_of"),
        }
