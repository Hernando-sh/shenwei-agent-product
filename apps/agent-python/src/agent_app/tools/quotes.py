"""list_quotes：报价台账查询。权威事实 = ERP /v1/quotes?customer_id=。
发报价前先看有没有已出的；空列表 = 没有记录，是正常结果。有效期与是否过期由 ERP 按虚拟时钟派生。"""
from __future__ import annotations

from agent_app.contracts import ErpGateway, ToolSpec

SPEC = ToolSpec(
    name="list_quotes",
    description=("按客户编号查报价台账：每条带报价号、版本、状态（issued / accepted / expired …）、有效期、是否过期、"
                 "行（型号 + 数量）、总额与币种。空列表表示该客户没有报价记录。只读。"),
    parameters={"type": "object",
                "properties": {"customer_id": {"type": "string", "description": "客户编号，如 C-E001"},
                               "status": {"type": "string", "description": "可选，只看某个状态，如 issued"}},
                "required": ["customer_id"], "additionalProperties": False},
)


class ListQuotes:
    spec = SPEC

    def __init__(self, erp: ErpGateway) -> None:
        self._erp = erp

    def run(self, args: dict, *, timeout_s: float) -> dict:
        page = self._erp.list_quotes(args["customer_id"], status=args.get("status"), timeout_s=timeout_s)
        rows = [{"quote_id": q.get("id"), "revision": q.get("revision"), "status": q.get("status"),
                 "valid_until": q.get("valid_until"), "is_expired": q.get("is_expired"),
                 "lines": [{"sku": l.get("sku"), "qty": l.get("qty")} for l in q.get("lines", [])],
                 "total_amount": q.get("total_amount"), "currency": q.get("currency"),
                 "created_at": q.get("created_at"), "created_by": q.get("created_by")}
                for q in page.get("data", [])]
        return {"customer_id": args["customer_id"], "status_filter": args.get("status"), "count": len(rows),
                "quotes": rows, "has_more": bool(page.get("has_more"))}
