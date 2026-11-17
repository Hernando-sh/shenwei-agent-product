"""search_customers / get_customer：客户检索与主数据。权威事实 = ERP /v1/customers、/v1/customers/{id}。
检索落不到唯一客户时，工具只给候选，澄清是模型的事；主数据里的 credit 是信用事实，供算价前的规则使用。"""
from __future__ import annotations

from agent_app.contracts import ErpGateway, ToolSpec

SEARCH_SPEC = ToolSpec(
    name="search_customers",
    description=("按关键词找客户，返回候选简表（编号、法定名称、城市、国家代码、价格组）。"
                 "q 用英文公司名、英文城市名或客户编号（ERP 的城市与公司名是英文，如 Jakarta、Dubai、Riyadh）；"
                 "按国家找用 country_code（ISO 两位，如 ID、DE、SA）。空列表表示没有匹配，不是查询失败。只读。"),
    parameters={"type": "object",
                "properties": {"q": {"type": "string", "description": "英文公司名 / 英文城市 / 客户编号"},
                               "country_code": {"type": "string", "description": "可选，ISO 两位国家代码"}},
                "required": ["q"], "additionalProperties": False},
)

GET_SPEC = ToolSpec(
    name="get_customer",
    description=("按客户编号查主数据与信用：法定名称、国家、价格组、付款条件、默认贸易术语、冻结状态、"
                 "信用额度 / 敞口 / 可用额度 / 逾期金额 / 逾期天数 / 信用状态 / 是否信用冻结。只读。"),
    parameters={"type": "object",
                "properties": {"customer_id": {"type": "string", "description": "客户编号，如 C-E001"}},
                "required": ["customer_id"], "additionalProperties": False},
)


class SearchCustomers:
    spec = SEARCH_SPEC

    def __init__(self, erp: ErpGateway) -> None:
        self._erp = erp

    def run(self, args: dict, *, timeout_s: float) -> dict:
        page = self._erp.search_customers(args["q"], country_code=args.get("country_code"), timeout_s=timeout_s)
        rows = [{"id": c.get("id"), "legal_name": c.get("legal_name"), "short_name": c.get("short_name"),
                 "city": c.get("city"), "country_code": c.get("country_code"), "country": c.get("country"),
                 "price_group": c.get("price_group"), "salesperson": c.get("salesperson"), "lifecycle": c.get("lifecycle")}
                for c in page.get("data", [])]
        return {"query": args["q"], "country_code": args.get("country_code"), "count": len(rows), "customers": rows,
                "has_more": bool(page.get("has_more"))}


class GetCustomer:
    spec = GET_SPEC

    def __init__(self, erp: ErpGateway) -> None:
        self._erp = erp

    def run(self, args: dict, *, timeout_s: float) -> dict:
        c = self._erp.get_customer(args["customer_id"], timeout_s=timeout_s)
        credit = c.get("credit") or {}
        return {
            "customer_id": c["id"], "legal_name": c.get("legal_name"), "short_name": c.get("short_name"),
            "country_code": c.get("country_code"), "city": c.get("city"), "price_group": c.get("price_group"),
            "salesperson": c.get("salesperson"), "lifecycle": c.get("lifecycle"),
            "payment_terms_code": c.get("payment_terms_code"), "payment_terms": c.get("payment_terms"),
            "incoterm_default": c.get("incoterm_default"), "currency": c.get("currency"), "blocked": c.get("blocked"),
            "credit": {k: credit.get(k) for k in ("currency", "credit_limit", "exposure", "available_credit", "ar_balance",
                                                   "overdue_amount", "overdue_days", "status", "hold")},
            "source_version": c.get("updated_at"),
        }
