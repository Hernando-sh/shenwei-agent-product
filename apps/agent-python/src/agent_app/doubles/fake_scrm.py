"""FakeScrm：客户 + 跟进 + 幂等表 + 故障开关。实现 ScrmGateway，和真实 ScrmClient 可互换。
owner 规则照 SCRM：X-Actor 是 sales:* 记本人，agent:* 记到客户的 owner 名下。"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field

from agent_app.contracts import ToolFailure


@dataclass
class FakeScrm:
    customers: dict[str, dict] = field(default_factory=dict)       # id → {id, name, owner}
    followups: list[dict] = field(default_factory=list)
    idempotency: dict[str, tuple[str, dict]] = field(default_factory=dict)
    write_requests: list[dict] = field(default_factory=list)
    lost_times: dict[str, int] = field(default_factory=dict)
    now: str = "2026-09-20T10:00:00+08:00"
    faults: dict[str, ToolFailure] = field(default_factory=dict)
    fault_times: dict[str, int] = field(default_factory=dict)
    calls: Counter = field(default_factory=Counter)

    def inject(self, method: str, failure: ToolFailure, times: int | None = None) -> None:
        self.faults[method] = failure
        if times is not None:
            self.fault_times[method] = times

    def response_lost(self, method: str, times: int = 1) -> None:
        self.lost_times[method] = times

    def _maybe_fail(self, method: str) -> None:
        if method not in self.faults:
            return
        left = self.fault_times.get(method)
        if left is not None:
            if left <= 0:
                return
            self.fault_times[method] = left - 1
        raise self.faults[method]

    def _customer(self, customer_id: str) -> dict:
        cu = self.customers.get(customer_id)
        if cu is None:
            raise ToolFailure("not_found", "customer_not_found", f"客户 {customer_id} 不存在")
        return cu

    def list_followups(self, customer_id: str, *, timeout_s: float) -> dict:
        self.calls["list_followups"] += 1
        self._maybe_fail("list_followups")
        self._customer(customer_id)
        rows = sorted((f for f in self.followups if f["customer_id"] == customer_id),
                      key=lambda f: (f["occurred_at"], f["id"]), reverse=True)
        return {"data": [dict(r) for r in rows], "has_more": False}

    def create_followup(self, customer_id: str, body: str, *, type: str = "note", next_action_at: str | None = None,
                        run_id: str | None, idempotency_key: str, actor: str, timeout_s: float) -> dict:
        self.calls["create_followup"] += 1
        payload = {"customer_id": customer_id, "type": type, "body": body, "next_action_at": next_action_at,
                   "source": "agent", "run_id": run_id}
        self.write_requests.append({"idempotency_key": idempotency_key, "actor": actor, "body": payload})
        self._maybe_fail("create_followup")
        digest = json.dumps(payload, sort_keys=True)
        if idempotency_key in self.idempotency:
            seen, original = self.idempotency[idempotency_key]
            if seen != digest:
                raise ToolFailure("rejected", "idempotency_conflict", "同一个 Idempotency-Key 已用于内容不同的请求")
            return {**json.loads(json.dumps(original)), "idempotent_replay": True}
        cu = self._customer(customer_id)
        if not body:
            raise ToolFailure("input_error", "validation_error", "body: String should have at least 1 character")
        owner = actor if actor.startswith("sales:") else (cu.get("owner") or actor)
        fid = f"FU-{len(self.followups) + 1:06d}"
        row = {"id": fid, "customer_id": customer_id, "contact_id": None, "type": type, "occurred_at": self.now, "owner": owner,
               "body": body, "next_action_at": next_action_at, "source": "agent", "run_id": run_id, "created_at": self.now}
        self.followups.append(row)
        self.idempotency[idempotency_key] = (digest, row)
        left = self.lost_times.get("create_followup", 0)
        if left > 0:
            self.lost_times["create_followup"] = left - 1
            raise ToolFailure("unknown", "bad_gateway", "网关错误，请求结果未知")
        return {**json.loads(json.dumps(row)), "idempotent_replay": False}

    @classmethod
    def with_base(cls) -> "FakeScrm":
        """测试用的小种子：三个与 ERP 共用编号的客户、一条历史跟进（内容与真实种子无关）。"""
        scrm = cls()
        scrm.customers = {
            "C-E001": {"id": "C-E001", "name": "PT Nusantara Process Engineering", "owner": "sales:zhou"},
            "C-E003": {"id": "C-E003", "name": "Rheinwerk Anlagenbau GmbH", "owner": "sales:lin"},
            "C-E007": {"id": "C-E007", "name": "Penang Water Solutions Sdn Bhd", "owner": "sales:zhou"},
        }
        scrm.followups = [{"id": "FU-T-0001", "customer_id": "C-E001", "contact_id": None, "type": "call",
                           "occurred_at": "2026-09-18T15:00:00+08:00", "owner": "sales:zhou",
                           "body": "电话确认备件需求，客户要 9 月底前拿到报价。", "next_action_at": "2026-09-22T10:00:00+08:00",
                           "source": "manual", "run_id": None, "created_at": "2026-09-18T15:00:00+08:00"}]
        return scrm
