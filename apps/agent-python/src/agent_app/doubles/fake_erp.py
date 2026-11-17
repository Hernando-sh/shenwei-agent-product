"""FakeERP：固定数据 + 调用计数 + 故障开关。实现 ErpGateway，和真实 ErpClient 可互换。"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
from collections import Counter
from dataclasses import dataclass, field

from agent_app.contracts import ToolFailure


@dataclass
class FakeERP:
    products: dict[str, dict] = field(default_factory=dict)
    inventory: dict[str, dict] = field(default_factory=dict)
    shipments: dict[str, dict] = field(default_factory=dict)
    orders: dict[str, dict] = field(default_factory=dict)
    customers: dict[str, dict] = field(default_factory=dict)      # 2.1：主数据（含 credit）
    receivables: dict[str, dict] = field(default_factory=dict)    # 2.1：按客户编号
    quotes: dict[str, dict] = field(default_factory=dict)         # 2.1：台账，按报价号；测试可直接预置
    prices: dict[tuple[str, str], dict] = field(default_factory=dict)  # 2.4：(customer_id, "X200:2,S10:4") → 录制的算价结果
    idempotency: dict[str, tuple[str, dict]] = field(default_factory=dict)  # 2.6：Idempotency-Key → (请求体摘要, 原响应)
    write_requests: list[dict] = field(default_factory=list)              # 2.6：每次写请求的头与体
    lost_times: dict[str, int] = field(default_factory=dict)              # 2.6：response_lost：提交后再报 502
    now: str = "2026-09-20T10:00:00+08:00"                                # ERP 虚拟时钟
    faults: dict[str, ToolFailure] = field(default_factory=dict)   # 按方法名注入：{"get_inventory": ToolFailure(...)}
    fault_times: dict[str, int] = field(default_factory=dict)      # 注入几次；缺省一直
    calls: Counter = field(default_factory=Counter)

    def inject(self, method: str, failure: ToolFailure, times: int | None = None) -> None:
        self.faults[method] = failure
        if times is not None:
            self.fault_times[method] = times

    def _maybe_fail(self, method: str) -> None:
        if method not in self.faults:
            return
        left = self.fault_times.get(method)
        if left is not None:
            if left <= 0:
                return
            self.fault_times[method] = left - 1
        raise self.faults[method]

    def _lookup(self, method: str, table: dict, key: str, code: str, what: str) -> dict:
        self.calls[method] += 1
        self._maybe_fail(method)
        if key.upper() not in {k.upper() for k in table}:
            raise ToolFailure("not_found", code, f"{what} {key} 不存在")
        return next(v for k, v in table.items() if k.upper() == key.upper())

    def get_product(self, sku: str, *, timeout_s: float) -> dict:
        return self._lookup("get_product", self.products, sku, "product_not_found", "型号")

    def get_inventory(self, sku: str, qty: int, *, timeout_s: float) -> dict:
        data = dict(self._lookup("get_inventory", self.inventory, sku, "product_not_found", "型号"))
        data["requested_qty"] = qty
        return data

    def get_shipment(self, tracking_no: str, *, timeout_s: float) -> dict:
        return self._lookup("get_shipment", self.shipments, tracking_no, "shipment_not_found", "运单")

    def get_order(self, order_id: str, *, timeout_s: float) -> dict:
        return self._lookup("get_order", self.orders, order_id, "order_not_found", "订单")

    # ---- W2 · 2.1 ----
    _SUMMARY = ("id", "number", "legal_name", "short_name", "country_code", "country", "city", "price_group",
                "salesperson", "lifecycle")

    def search_customers(self, q: str | None, *, country_code: str | None = None, timeout_s: float) -> dict:
        """按公司名 / 城市 / 编号 / 国家子串匹配（不区分大小写），可只按 country_code；返回 ERP 简表形状；空结果是 data=[]。"""
        self.calls["search_customers"] += 1
        self._maybe_fail("search_customers")
        needle = (q or "").lower()
        hits = []
        for c in self.customers.values():
            if country_code and c.get("country_code") != country_code.upper():
                continue
            hay = " ".join(str(c.get(k) or "") for k in ("id", "legal_name", "short_name", "city", "country")).lower()
            if needle in hay:
                hits.append({k: c.get(k) for k in self._SUMMARY})
        return {"data": hits, "has_more": False, "next_cursor": None}

    def get_customer(self, customer_id: str, *, timeout_s: float) -> dict:
        return self._lookup("get_customer", self.customers, customer_id, "customer_not_found", "客户")

    def get_receivables(self, customer_id: str, *, timeout_s: float) -> dict:
        return self._lookup("get_receivables", self.receivables, customer_id, "customer_not_found", "客户")

    def list_quotes(self, customer_id: str, *, status: str | None = None, timeout_s: float) -> dict:
        self.calls["list_quotes"] += 1
        self._maybe_fail("list_quotes")
        rows = [q for q in self.quotes.values() if q.get("customer_id") == customer_id
                and (status is None or q.get("status") == status)]
        rows.sort(key=lambda q: q.get("created_at") or "", reverse=True)
        return {"data": rows, "has_more": False, "next_cursor": None}

    @staticmethod
    def _lines_key(lines: list[dict]) -> str:
        """快照键：按型号排序，和书写顺序无关。"""
        rows = sorted(({"sku": str(l["sku"]).upper(), "qty": int(l["qty"])} for l in lines), key=lambda r: r["sku"])
        return ",".join(f"{r['sku']}:{r['qty']}" for r in rows)

    def price_quote(self, customer_id: str, lines: list[dict], *, timeout_s: float) -> dict:
        """不实现报价规程：只回放录制的算价快照。没录过的组合明确报错，不要悄悄算。"""
        self.calls["price_quote"] += 1
        self._maybe_fail("price_quote")
        if customer_id not in self.customers:
            raise ToolFailure("not_found", "customer_not_found", f"客户 {customer_id} 不存在")
        for l in lines:
            if str(l["sku"]).upper() not in {k.upper() for k in self.products}:
                raise ToolFailure("input_error", "unknown_sku", f"型号 {l['sku']} 不存在或已停售")
        key = (customer_id, self._lines_key(lines))
        if key not in self.prices:
            raise ToolFailure("upstream_error", "no_fixture", f"FakeERP 没有 {key} 的算价快照：先对 ERP 录制（make fixtures）")
        return json.loads(json.dumps(self.prices[key]))

    # ---- W2 · 2.6 写台账 ----
    def response_lost(self, method: str, times: int = 1) -> None:
        """模拟 ERP 的 response_lost：业务已提交，但调用方只收到 502。"""
        self.lost_times[method] = times

    def create_quote(self, customer_id: str, lines: list[dict], *, idempotency_key: str, actor: str, timeout_s: float,
                     customer_reference: str | None = None, note: str | None = None) -> dict:
        self.calls["create_quote"] += 1
        body = {"customer_id": customer_id, "lines": [{"sku": str(l["sku"]).upper(), "qty": int(l["qty"])} for l in lines]}
        self.write_requests.append({"idempotency_key": idempotency_key, "actor": actor, "body": body})
        self._maybe_fail("create_quote")                                   # 注入的失败在提交之前（timeout / error）
        body_digest = json.dumps(body, sort_keys=True)
        if idempotency_key in self.idempotency:                            # 同键重放
            seen_digest, original = self.idempotency[idempotency_key]
            if seen_digest != body_digest:
                raise ToolFailure("rejected", "idempotency_conflict", "同一个 Idempotency-Key 已用于内容不同的请求")
            return {**json.loads(json.dumps(original)), "idempotent_replay": True}
        price = self.price_quote(customer_id, body["lines"], timeout_s=timeout_s)   # 用录制的算价结果填台账
        self.calls["price_quote"] -= 1                                      # 内部算价不算一次工具调用
        qid = f"QT-{len(self.quotes) + 1:06d}"
        valid_until = (dt.date.fromisoformat(price["price_date"]) + dt.timedelta(days=30)).isoformat()
        quote = {"id": qid, "revision": 1, "supersedes_quote_id": None, "customer_id": customer_id,
                 "status": "issued", "valid_until": valid_until, "is_expired": False,
                 "lines": price["lines"], "total_amount": price["total_amount"], "currency": price["currency"],
                 "incoterm": price.get("incoterm"), "payment_terms_code": price.get("payment_terms_code"),
                 "payment_terms": price.get("payment_terms"), "price_rule_ref": price.get("price_rule_ref"),
                 "fx_rate": price.get("fx_rate"), "price_date": price.get("price_date"),
                 "customer_reference": customer_reference, "note": note,
                 "created_by": actor, "created_at": self.now, "updated_at": self.now}
        self.quotes[qid] = quote
        self.idempotency[idempotency_key] = (body_digest, quote)
        left = self.lost_times.get("create_quote", 0)
        if left > 0:                                                        # 已提交，但响应丢了
            self.lost_times["create_quote"] = left - 1
            raise ToolFailure("unknown", "bad_gateway", "网关错误，请求结果未知")
        return {**json.loads(json.dumps(quote)), "idempotent_replay": False}

    @classmethod
    def from_fixtures(cls, fixtures_dir: str | pathlib.Path) -> "FakeERP":
        """读 scripts/record_fixtures.py 录下的 *.json；只装 200 的，404 样本留给契约测试用。"""
        erp = cls()
        for f in sorted(pathlib.Path(fixtures_dir).glob("*.json")):
            rec = json.loads(f.read_text(encoding="utf-8"))
            if rec["status"] != 200:
                continue
            body, path = rec["body"], rec["request"]["path"]
            if path.startswith("/v1/products/"):
                erp.products[body["sku"]] = body
            elif path.startswith("/v1/inventory/"):
                erp.inventory.setdefault(body["sku"], body)  # 同型号多份只留第一份；qty 由 get_inventory 覆盖
            elif path.startswith("/v1/shipments/"):
                erp.shipments[body["tracking_no"]] = body
            elif path.startswith("/v1/orders/"):
                erp.orders[body["id"]] = body
            elif path.startswith("/v1/customers/") and path.endswith("/receivables"):
                erp.receivables[body["customer_id"]] = body
            elif path.startswith("/v1/customers/"):
                erp.customers[body["id"]] = body
            elif path == "/v1/quotes":
                for q in body.get("data", []):                  # 基础种子没有报价；录到就装
                    erp.quotes[q["id"]] = q
            elif path == "/v1/quotes/price":
                q = rec["request"]["query"]
                rows = [{"sku": p.split(":")[0], "qty": p.split(":")[1]} for p in q["lines"].split(",")]
                erp.prices[(q["customer_id"], cls._lines_key(rows))] = body
            # /v1/customers?q= 简表由 search_customers 从主数据现算，不在这里
        return erp

    @staticmethod
    def timeout(method: str = "get_inventory") -> ToolFailure:
        return ToolFailure("timeout", "gateway_timeout", f"ERP {method} 超时")
