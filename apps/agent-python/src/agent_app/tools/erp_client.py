"""真实 ERP 访问（httpx）。实现 ErpGateway；失败一律变成 ToolFailure 的分类，不让 httpx 异常漏到 Loop。
错误分层：调用 / 解析错误（malformed）、业务无数据（not_found）、被拒（rejected：401 / 403）、
上游临时故障（timeout / upstream_error）。空列表不是错误：{"data": []} 原样返回（W2-AC-01）。"""
from __future__ import annotations

import httpx

from agent_app.contracts import ToolFailure


class ErpClient:
    def __init__(self, base_url: str, api_key: str, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(base_url=base_url, headers={"X-Api-Key": api_key}, transport=transport)

    def _get(self, path: str, params: dict | None = None, *, timeout_s: float) -> dict:
        try:
            r = self._client.get(path, params=params, timeout=timeout_s)
        except httpx.TimeoutException as e:
            raise ToolFailure("timeout", "client_timeout", f"ERP 请求超时（{timeout_s}s）：{type(e).__name__}") from e
        except httpx.HTTPError as e:
            raise ToolFailure("upstream_error", "http_error", f"ERP 请求失败：{type(e).__name__}") from e
        body = _problem(r)
        if r.status_code == 404:
            raise ToolFailure("not_found", body.get("code", "not_found"), body.get("detail", "不存在"))
        if r.status_code in (401, 403):
            raise ToolFailure("rejected", body.get("code", "unauthorized"), body.get("detail", "ERP 拒绝了这次请求"))
        if r.status_code == 422:                                   # 参数不合法（含多传字段）：是输入错误，不是上游故障
            raise ToolFailure("input_error", body.get("code", "validation_error"),
                              body.get("detail", "ERP 拒绝了参数") + _errors(body))
        if r.status_code == 504 or body.get("code") == "gateway_timeout":
            raise ToolFailure("timeout", body.get("code", "gateway_timeout"), body.get("detail", "ERP 网关超时"))
        if r.status_code >= 400:
            raise ToolFailure("upstream_error", body.get("code", str(r.status_code)),
                              body.get("detail", f"ERP 返回 {r.status_code}"))
        if not body and r.content:
            raise ToolFailure("malformed", "not_json", "ERP 返回的不是 JSON，不能当结果")
        return body

    def get_product(self, sku: str, *, timeout_s: float) -> dict:
        return self._get(f"/v1/products/{sku}", timeout_s=timeout_s)

    def get_inventory(self, sku: str, qty: int, *, timeout_s: float) -> dict:
        return self._get(f"/v1/inventory/{sku}", {"qty": qty}, timeout_s=timeout_s)

    def get_shipment(self, tracking_no: str, *, timeout_s: float) -> dict:
        return self._get(f"/v1/shipments/{tracking_no}", timeout_s=timeout_s)

    def get_order(self, order_id: str, *, timeout_s: float) -> dict:
        return self._get(f"/v1/orders/{order_id}", timeout_s=timeout_s)

    # ---- W2 · 2.1 客户 / 回款 / 台账（只读）----
    def search_customers(self, q: str, *, country_code: str | None = None, timeout_s: float) -> dict:
        params = {"q": q}
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

    def _post(self, path: str, body: dict, *, idempotency_key: str, actor: str, timeout_s: float) -> dict:
        """写请求。与 _get 的差别：5xx、超时、断连都是「结果未知」（category=unknown），由运行时同键核实，不在这里重试。"""
        headers = {"Idempotency-Key": idempotency_key, "X-Actor": actor}
        try:
            r = self._client.post(path, json=body, headers=headers, timeout=timeout_s)
        except httpx.TimeoutException as e:
            raise ToolFailure("unknown", "client_timeout", f"ERP 写请求超时（{timeout_s}s），结果未知：{type(e).__name__}") from e
        except httpx.HTTPError as e:
            raise ToolFailure("unknown", "connection_error", f"ERP 写请求断连，结果未知：{type(e).__name__}") from e
        data = _problem(r)
        if r.status_code in (200, 201):
            if not data:
                raise ToolFailure("unknown", "not_json", "ERP 写请求返回了非 JSON，结果未知")
            data["idempotent_replay"] = r.headers.get("idempotent-replay", "").lower() == "true"
            data["original_request_id"] = r.headers.get("idempotent-original-request-id")
            return data
        code, detail = data.get("code", str(r.status_code)), data.get("detail", f"ERP 返回 {r.status_code}")
        if r.status_code >= 500:
            raise ToolFailure("unknown", code, f"{detail}（结果未知，需同键核实）")
        if r.status_code == 404:
            raise ToolFailure("not_found", code, detail)
        if r.status_code in (401, 403):
            raise ToolFailure("rejected", code, detail)
        if r.status_code == 409:
            raise ToolFailure("rejected", code, detail)                     # idempotency_conflict / in_progress
        if r.status_code in (400, 422):
            raise ToolFailure("input_error", code, detail + _errors(data))
        raise ToolFailure("upstream_error", code, detail)


def lines_param(lines: list[dict]) -> str:
    """ERP 的行写法：X200:2,S10:4。"""
    return ",".join(f"{l['sku']}:{int(l['qty'])}" for l in lines)


def _errors(body: dict) -> str:
    errs = body.get("errors") or []
    return ("；" + "，".join(f"{e.get('field')}: {e.get('problem')}" for e in errs)) if errs else ""


def _problem(r: httpx.Response) -> dict:
    try:
        return r.json()
    except ValueError:
        return {}
