"""真实 SCRM 访问（httpx）。实现 ScrmGateway。身份是 SCRM 自己的 key（与 ERP 不同，拿错 401 → rejected）。
只做本周需要的两件事：列某客户的跟进（只读）、写一条跟进（写，带 Idempotency-Key 与 X-Actor）。"""
from __future__ import annotations

from .http_json import JsonApiClient


class ScrmClient(JsonApiClient):
    system = "SCRM"

    def list_followups(self, customer_id: str, *, timeout_s: float) -> dict:
        return self._get("/v1/followups", {"customer_id": customer_id}, timeout_s=timeout_s)

    def create_followup(self, customer_id: str, body: str, *, type: str = "note", next_action_at: str | None = None,
                        run_id: str | None, idempotency_key: str, actor: str, timeout_s: float) -> dict:
        payload: dict = {"customer_id": customer_id, "type": type, "body": body, "source": "agent", "run_id": run_id}
        if next_action_at:
            payload["next_action_at"] = next_action_at
        return self._post("/v1/followups", payload, idempotency_key=idempotency_key, actor=actor, timeout_s=timeout_s)
