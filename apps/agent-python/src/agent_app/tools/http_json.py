"""JSON 接口客户端的公共部分（httpx）：请求、problem+json、失败分类。ERP 与 SCRM 客户端都从这里继承，
两边的错误分层一致：调用 / 解析错误（malformed）、业务无数据（not_found）、被拒（rejected：401 / 403 / 409）、
参数不合法（input_error：400 / 422）、上游临时故障（timeout / upstream_error）；写请求的 5xx / 超时 / 断连 = 结果未知（unknown）。"""
from __future__ import annotations

import httpx

from agent_app.contracts import ToolFailure


class JsonApiClient:
    system = "上游"           # 出现在错误信息里的系统名；子类覆盖

    def __init__(self, base_url: str, api_key: str, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(base_url=base_url, headers={"X-Api-Key": api_key}, transport=transport)

    def _get(self, path: str, params: dict | None = None, *, timeout_s: float) -> dict:
        try:
            r = self._client.get(path, params=params, timeout=timeout_s)
        except httpx.TimeoutException as e:
            raise ToolFailure("timeout", "client_timeout", f"{self.system} 请求超时（{timeout_s}s）：{type(e).__name__}") from e
        except httpx.HTTPError as e:
            raise ToolFailure("upstream_error", "http_error", f"{self.system} 请求失败：{type(e).__name__}") from e
        body = _problem(r)
        if r.status_code == 404:
            raise ToolFailure("not_found", body.get("code", "not_found"), body.get("detail", "不存在"))
        if r.status_code in (401, 403):
            raise ToolFailure("rejected", body.get("code", "unauthorized"), body.get("detail", f"{self.system} 拒绝了这次请求"))
        if r.status_code == 422:                                   # 参数不合法（含多传字段）：是输入错误，不是上游故障
            raise ToolFailure("input_error", body.get("code", "validation_error"),
                              body.get("detail", f"{self.system} 拒绝了参数") + _errors(body))
        if r.status_code == 504 or body.get("code") == "gateway_timeout":
            raise ToolFailure("timeout", body.get("code", "gateway_timeout"), body.get("detail", f"{self.system} 网关超时"))
        if r.status_code >= 400:
            raise ToolFailure("upstream_error", body.get("code", str(r.status_code)),
                              body.get("detail", f"{self.system} 返回 {r.status_code}"))
        if not body and r.content:
            raise ToolFailure("malformed", "not_json", f"{self.system} 返回的不是 JSON，不能当结果")
        return body

    def _post(self, path: str, body: dict, *, idempotency_key: str, actor: str, timeout_s: float) -> dict:
        """写请求。与 _get 的差别：5xx、超时、断连都是「结果未知」（category=unknown），由运行时同键核实，不在这里重试。"""
        headers = {"Idempotency-Key": idempotency_key, "X-Actor": actor}
        try:
            r = self._client.post(path, json=body, headers=headers, timeout=timeout_s)
        except httpx.TimeoutException as e:
            raise ToolFailure("unknown", "client_timeout", f"{self.system} 写请求超时（{timeout_s}s），结果未知：{type(e).__name__}") from e
        except httpx.HTTPError as e:
            raise ToolFailure("unknown", "connection_error", f"{self.system} 写请求断连，结果未知：{type(e).__name__}") from e
        data = _problem(r)
        if r.status_code in (200, 201):
            if not data:
                raise ToolFailure("unknown", "not_json", f"{self.system} 写请求返回了非 JSON，结果未知")
            data["idempotent_replay"] = r.headers.get("idempotent-replay", "").lower() == "true"
            data["original_request_id"] = r.headers.get("idempotent-original-request-id")
            return data
        code, detail = data.get("code", str(r.status_code)), data.get("detail", f"{self.system} 返回 {r.status_code}")
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


def _errors(body: dict) -> str:
    errs = body.get("errors") or []
    return ("；" + "，".join(f"{e.get('field')}: {e.get('problem')}" for e in errs)) if errs else ""


def _problem(r: httpx.Response) -> dict:
    try:
        return r.json()
    except ValueError:
        return {}
