"""真实知识服务访问（httpx）。实现 KnowledgeGateway；失败一律变成 ToolFailure 的分类。
知识服务没有租户 key；向量检索用服务端自己的 DASHSCOPE_API_KEY，本客户端不带任何密钥。"""
from __future__ import annotations

import httpx

from agent_app.contracts import ToolFailure


class KnowledgeClient:
    def __init__(self, base_url: str, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(base_url=base_url, transport=transport)

    def search(self, query: str, *, top_k: int = 5, domain: list[str] | None = None, doc_ids: list[str] | None = None,
               order_date: str | None = None, timeout_s: float) -> dict:
        filters: dict = {}
        if domain:
            filters["domain"] = domain
        if doc_ids:
            filters["doc_ids"] = doc_ids
        if order_date:
            filters["order_date"] = order_date                 # 原样透传：版本由知识服务按下单日期选
        body = {"query": query, "top_k": top_k, "filters": filters}
        try:
            r = self._client.post("/v1/search", json=body, timeout=timeout_s)
        except httpx.TimeoutException as e:
            raise ToolFailure("timeout", "client_timeout", f"知识服务请求超时（{timeout_s}s）：{type(e).__name__}") from e
        except httpx.HTTPError as e:
            raise ToolFailure("upstream_error", "http_error", f"知识服务请求失败：{type(e).__name__}") from e
        try:
            data = r.json()
        except ValueError:
            data = None
        if r.status_code == 422:
            raise ToolFailure("input_error", "validation_error", "知识服务拒绝了检索参数")
        if r.status_code == 504:
            raise ToolFailure("timeout", "gateway_timeout", "知识服务网关超时")
        if r.status_code >= 400:
            code = (data or {}).get("detail", {}).get("error") if isinstance((data or {}).get("detail"), dict) else str(r.status_code)
            raise ToolFailure("upstream_error", code or str(r.status_code), f"知识服务返回 {r.status_code}")
        if not isinstance(data, dict) or "hits" not in data:
            raise ToolFailure("malformed", "not_json", "知识服务返回的不是检索结果，不能当依据")
        return data
