"""前置规则：程序执行，算价前按固定顺序判，只报第一条拦下的理由（周 spec 第 4 节；ADR-004）。
    blocked → credit_hold → overdue → duplicate → 算价
规则所需事实查不到时不在这里兜底：调用方把失败原样交回（不出草案，不默认放行）。"""
from __future__ import annotations

from dataclasses import dataclass

from .draft import canonical_lines

RULE_ORDER = ("blocked", "credit_hold", "overdue", "duplicate")


@dataclass(frozen=True)
class RuleHit:
    rule: str
    reason: str
    facts: dict


def check_customer_master(customer: dict) -> RuleHit | None:
    """只看主数据：blocked → credit_hold。命中就不必再查回款。"""
    credit = customer.get("credit") or {}
    blocked = customer.get("blocked") or "none"
    if blocked != "none":
        return RuleHit("blocked", f"客户 {customer.get('id')} 已冻结（blocked={blocked}），不出报价草案",
                       {"blocked": blocked})
    if credit.get("hold"):
        return RuleHit("credit_hold", f"客户 {customer.get('id')} 信用冻结（credit.hold），不出报价草案",
                       {"credit_status": credit.get("status"), "hold": True})
    return None


def check_overdue(customer: dict, receivables: dict) -> RuleHit | None:
    """应收账龄。逾期天数取 receivables.overdue_days，金额取 customer.credit.overdue_amount（周 spec 第 3 节口径）。"""
    credit = customer.get("credit") or {}
    overdue_days = receivables.get("overdue_days") or 0
    if receivables.get("credit_status") == "overdue" or overdue_days > 0:
        amount = credit.get("overdue_amount")
        if amount is None:
            amount = receivables.get("overdue_amount")
        return RuleHit("overdue", f"客户 {customer.get('id')} 有逾期回款：逾期 {overdue_days} 天，逾期金额 {amount} "
                                  f"{receivables.get('currency') or credit.get('currency') or ''}，不出报价草案",
                       {"credit_status": receivables.get("credit_status"), "overdue_days": overdue_days,
                        "overdue_amount": amount, "currency": receivables.get("currency") or credit.get("currency"),
                        "open_items": [i.get("id") for i in receivables.get("open_items", [])]})
    return None


def check_customer_status(customer: dict, receivables: dict) -> RuleHit | None:
    """主数据规则在前，逾期在后；只报第一条。"""
    return check_customer_master(customer) or check_overdue(customer, receivables)


def check_duplicate(existing_quotes: list[dict], customer_id: str, lines: list[dict]) -> RuleHit | None:
    """有效期内（status=issued 且 is_expired=false）同客户、同行集合（sku + qty）的报价已存在 → 不重复出。"""
    want = canonical_lines(lines)
    for q in existing_quotes:
        if q.get("customer_id") != customer_id or q.get("status") != "issued" or q.get("is_expired"):
            continue
        have = canonical_lines([{"sku": l.get("sku"), "qty": l.get("qty")} for l in q.get("lines", [])])
        if have == want:
            return RuleHit("duplicate", f"有效期内已有同内容报价 {q.get('id')}（有效至 {q.get('valid_until')}），不重复出",
                           {"existing_quote_id": q.get("id"), "valid_until": q.get("valid_until"),
                            "status": q.get("status"), "revision": q.get("revision")})
    return None
