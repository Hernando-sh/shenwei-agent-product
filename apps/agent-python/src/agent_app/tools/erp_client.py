"""真实 ERP 访问（httpx，公共部分在 http_json.JsonApiClient）。实现 ErpGateway；失败一律变成 ToolFailure 的分类，不让 httpx 异常漏到 Loop。
错误分层：调用 / 解析错误（malformed）、业务无数据（not_found）、被拒（rejected：401 / 403）、
上游临时故障（timeout / upstream_error）。空列表不是错误：{"data": []} 原样返回（W2-AC-01）。"""
from __future__ import annotations

from .http_json import JsonApiClient


class ErpClient(JsonApiClient):
    system = "ERP"

    def get_product(self, sku: str, *, timeout_s: float) -> dict:
        return self._get(f"/v1/products/{sku}", timeout_s=timeout_s)

    def get_inventory(self, sku: str, qty: int, *, timeout_s: float) -> dict:
        return self._get(f"/v1/inventory/{sku}", {"qty": qty}, timeout_s=timeout_s)

    def get_shipment(self, tracking_no: str, *, timeout_s: float) -> dict:
        return self._get(f"/v1/shipments/{tracking_no}", timeout_s=timeout_s)

    def get_order(self, order_id: str, *, timeout_s: float) -> dict:
        return self._get(f"/v1/orders/{order_id}", timeout_s=timeout_s)

    # ---- W2 · 2.1 客户 / 回款 / 台账（只读）----
    def search_customers(self, q: str | None, *, country_code: str | None = None, timeout_s: float) -> dict:
        params = {}
        if q:
            params["q"] = q
        if country_code:
            params["country_code"] = country_code
        return self._get("/v1/customers", params, timeout_s=timeout_s)

    def get_customer(self, customer_id: str, *, timeout_s: float) -> dict:
        return self._get(f"/v1/customers/{customer_id}", timeout_s=timeout_s)

    def get_receivables(self, customer_id: str, *, timeout_s: float) -> dict:
        return self._get(f"/v1/customers/{customer_id}/receivables", timeout_s=timeout_s)

    def list_quotes(self, customer_id: str, *, status: str | None = None, timeout_s: float) -> dict:
        params = {"customer_id": customer_id}
        if status:
            params["status"] = status
        return self._get("/v1/quotes", params, timeout_s=timeout_s)

    # ---- W2 · 2.4 算价 ----
    def price_quote(self, customer_id: str, lines: list[dict], *, timeout_s: float) -> dict:
        return self._get("/v1/quotes/price", {"customer_id": customer_id, "lines": lines_param(lines)}, timeout_s=timeout_s)

    # ---- W2 · 2.6 写台账 ----
    def create_quote(self, customer_id: str, lines: list[dict], *, idempotency_key: str, actor: str, timeout_s: float,
                     customer_reference: str | None = None, note: str | None = None) -> dict:
        body: dict = {"customer_id": customer_id, "lines": [{"sku": l["sku"], "qty": int(l["qty"])} for l in lines]}
        if customer_reference:
            body["customer_reference"] = customer_reference
        if note:
            body["note"] = note
        return self._post("/v1/quotes", body, idempotency_key=idempotency_key, actor=actor, timeout_s=timeout_s)

def lines_param(lines: list[dict]) -> str:
    """ERP 的行写法：X200:2,S10:4。"""
    return ",".join(f"{l['sku']}:{int(l['qty'])}" for l in lines)
