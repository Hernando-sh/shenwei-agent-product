"""QuoteDraft：报价草案。全部金额字段只从 ERP /v1/quotes/price 的返回里取（W2-AC-04）；
冻结数据类，没有改写金额的入口；没有 valid_until（有效期由 ERP 在保存时给，草案阶段没有这个事实）。"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field


def normalize_lines(lines: list[dict]) -> list[dict]:
    """型号大写、去空白，保留用户给的顺序（发给 ERP 的顺序就是它）。"""
    return [{"sku": str(l["sku"]).strip().upper(), "qty": int(l["qty"])} for l in lines]


def canonical_lines(lines: list[dict]) -> list[dict]:
    """按型号排序的规范形：比较"同内容"与算摘要用，不论书写顺序与大小写。"""
    return sorted(normalize_lines(lines), key=lambda r: r["sku"])


def lines_digest(customer_id: str, lines: list[dict]) -> str:
    payload = json.dumps({"customer_id": customer_id, "lines": canonical_lines(lines)}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class QuoteDraft:
    customer_id: str
    legal_name: str | None
    price_group: str | None
    lines: list[dict]                 # ERP 返回的行：line_no / sku / name_en / qty / uom / list_price / conditions / unit_price / amount
    total_amount: float
    currency: str
    incoterm: dict | None
    payment_terms_code: str | None
    payment_terms: str | None
    price_rule_ref: str | None
    fx_rate: dict | None
    price_date: str | None
    digest: str                       # 客户 + 行集合的摘要；2.5 的确认绑定它
    recorded: bool = False            # 草案不是台账记录
    validity_note: str = field(default="保存后 30 天有效；有效期日期由 ERP 在保存时给出，草案阶段没有这个日期")

    @classmethod
    def from_erp(cls, price: dict, *, legal_name: str | None) -> "QuoteDraft":
        lines = [json.loads(json.dumps(l)) for l in price.get("lines", [])]
        return cls(
            customer_id=price["customer_id"], legal_name=legal_name, price_group=price.get("price_group"),
            lines=lines, total_amount=price["total_amount"], currency=price["currency"],
            incoterm=price.get("incoterm"), payment_terms_code=price.get("payment_terms_code"),
            payment_terms=price.get("payment_terms"), price_rule_ref=price.get("price_rule_ref"),
            fx_rate=price.get("fx_rate"), price_date=price.get("price_date"),
            digest=lines_digest(price["customer_id"], [{"sku": l["sku"], "qty": l["qty"]} for l in lines]),
            recorded=bool(price.get("recorded", False)),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def request_lines(self) -> list[dict]:
        """写台账时发给 ERP 的行：只有 sku 与 qty，没有金额。"""
        return [{"sku": l["sku"], "qty": l["qty"]} for l in self.lines]
