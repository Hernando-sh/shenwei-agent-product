"""scrm_write_followup：在 SCRM 客户档案下记一条跟进（内部写）。权威事实 = SCRM POST /v1/followups 的返回。
与 create_quote 同一条管线、同一种写签名（run(args, *, timeout_s, operation)）；不同的只有系统、档位与前置规则：
第一次尝试前先查该客户的跟进，已有同内容就不再写（SCRM 自己不拦，只记 duplicate_followup）；核实（attempt ≥ 2）不再查。
source=agent、run_id 由程序填；owner 由 SCRM 按 X-Actor 定（agent:* 记到客户业务员名下）。"""
from __future__ import annotations

from agent_app.contracts import Operation, ScrmGateway, ToolFailure, ToolSpec

TYPES = ("note", "call", "email", "meeting", "task")

SPEC = ToolSpec(
    name="scrm_write_followup",
    description=("在 SCRM 的客户档案下记一条跟进（写操作，内部系统；询问模式需操作者确认）。内容是给业务员和主管看的工作记录，"
                 "不是发给客户的消息——SCRM 没有发消息接口。客户编号与 ERP 共用，先用 search_customers 落到唯一编号。"
                 "同客户已有同内容的跟进时不再写，返回 outcome=declined。"),
    parameters={"type": "object",
                "properties": {
                    "customer_id": {"type": "string", "description": "客户编号，如 C-E001"},
                    "type": {"type": "string", "description": "note / call / email / meeting / task，默认 note"},
                    "body": {"type": "string", "description": "跟进内容（给业务员看），非空"},
                    "next_action_at": {"type": "string", "description": "可选，下次动作时间，RFC 3339，如 2026-09-23T10:00:00+08:00"}},
                "required": ["customer_id", "body"], "additionalProperties": False},
)


class WriteFollowup:
    spec = SPEC
    kind = "write_internal"

    def __init__(self, scrm: ScrmGateway) -> None:
        self._scrm = scrm

    def run(self, args: dict, *, timeout_s: float, operation: Operation) -> dict:
        customer_id, body = args["customer_id"], str(args["body"]).strip()
        ftype = args.get("type") or "note"
        if not body:
            raise ToolFailure("input_error", "empty_body", "跟进内容不能为空：不调 SCRM")
        if ftype not in TYPES:
            raise ToolFailure("input_error", "bad_type", f"type 只能是 {' / '.join(TYPES)}，收到 {ftype!r}")
        if operation.attempt == 1:
            page = self._fact("该客户的跟进", self._scrm.list_followups, customer_id, timeout_s=timeout_s)
            dup = next((f for f in page.get("data", []) if str(f.get("body", "")).strip() == body), None)
            if dup is not None:
                return {"customer_id": customer_id, "body": body, "outcome": "declined", "rule": "duplicate_followup",
                        "reason": f"该客户已有同内容的跟进 {dup.get('id')}（{dup.get('occurred_at')}），不再重复记录",
                        "facts": {"followup_id": dup.get("id"), "occurred_at": dup.get("occurred_at"), "owner": dup.get("owner")},
                        "recorded": False}
        f = self._scrm.create_followup(customer_id, body, type=ftype, next_action_at=args.get("next_action_at"),
                                       run_id=operation.run_id, idempotency_key=operation.idempotency_key,
                                       actor=operation.actor, timeout_s=timeout_s)
        return {"outcome": "saved", "id": f["id"], "followup_id": f["id"], "customer_id": f.get("customer_id"),
                "type": f.get("type"), "occurred_at": f.get("occurred_at"), "owner": f.get("owner"),
                "next_action_at": f.get("next_action_at"), "body": f.get("body"), "source": f.get("source"),
                "run_id": f.get("run_id"), "idempotent_replay": bool(f.get("idempotent_replay")), "recorded": True}

    @staticmethod
    def _fact(what: str, fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except ToolFailure as f:
            raise ToolFailure(f.error.category, f.error.code,
                              f"前置事实查不到（{what}：{f.error.message}）：不写入，不默认放行") from f
