"""令牌校验：approve 只在三件事都对时成立——同一个 operation_id、同一个 digest、在有效期内（真实时钟）。"""
from __future__ import annotations

from agent_app.contracts import Changeset, ConfirmToken


def validate_token(token: ConfirmToken, changeset: Changeset, *, now: float, ttl_s: float) -> str | None:
    """返回失效原因；None 表示有效。"""
    if token.decision != "approve":
        return "not_approved"
    if token.digest != changeset.digest:
        return "digest_mismatch"            # 参数变了：先报这个，它是业务员最该知道的原因
    if token.operation_id != changeset.operation_id:
        return "operation_mismatch"
    if token.decided_at is None or now - token.decided_at > ttl_s or token.decided_at - now > ttl_s:
        return "expired"
    return None
