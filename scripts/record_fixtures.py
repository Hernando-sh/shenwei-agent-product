"""从跑着的模拟 ERP 录 fixture：fixture 不手写，永远是 ERP 数据的快照。
用法：uv run --project apps/agent-python python scripts/record_fixtures.py [--base http://localhost:9100]
输出：apps/agent-python/tests/fixtures/erp/<name>.json，每个文件 = 请求 + 状态 + 响应体。
录制要对着基础种子（先 POST /_admin/reset）；W2 起每条可带第四项：覆盖请求头（录 401 样本用）。"""
import argparse
import datetime as dt
import json
import pathlib
import sys

import httpx

CASES = [  # (文件名, 路径, 查询)
    ("products_X200", "/v1/products/X200", {}),
    ("products_X200-Pro", "/v1/products/X200-Pro", {}),
    ("products_T200", "/v1/products/T200", {}),
    ("products_X999_404", "/v1/products/X999", {}),
    ("inventory_X200_qty1", "/v1/inventory/X200", {"qty": 1}),
    ("inventory_X200_qty2", "/v1/inventory/X200", {"qty": 2}),
    ("inventory_T200_qty1", "/v1/inventory/T200", {"qty": 1}),
    ("inventory_X999_404", "/v1/inventory/X999", {"qty": 1}),
    ("shipments_SF1234567890", "/v1/shipments/SF1234567890", {}),
    ("shipments_SF0000000000_404", "/v1/shipments/SF0000000000", {}),
    ("orders_ORD-10086", "/v1/orders/ORD-10086", {}),
    ("orders_ORD-99999_404", "/v1/orders/ORD-99999", {}),
    # ---- W2（2.1 四个只读工具；2.4 算价）----
    ("products_S10", "/v1/products/S10", {}),
    ("products_X300", "/v1/products/X300", {}),
    ("customers_q_Jakarta", "/v1/customers", {"q": "Jakarta"}),
    ("customers_q_Dusseldorf_DE", "/v1/customers", {"q": "Rheinwerk", "country_code": "DE"}),
    ("customers_q_Singapore_empty", "/v1/customers", {"q": "Singapore"}),
    ("customers_C-E001", "/v1/customers/C-E001", {}),
    ("customers_C-E003", "/v1/customers/C-E003", {}),
    ("customers_C-E999_404", "/v1/customers/C-E999", {}),
    ("customers_C-E001_401", "/v1/customers/C-E001", {}, {"X-Api-Key": "wrong-key"}),
    ("receivables_C-E001", "/v1/customers/C-E001/receivables", {}),
    ("receivables_C-E003", "/v1/customers/C-E003/receivables", {}),
    ("quotes_customer_C-E001_empty", "/v1/quotes", {"customer_id": "C-E001"}),
    ("quotes_price_C-E001_X200x2", "/v1/quotes/price", {"customer_id": "C-E001", "lines": "X200:2"}),
    ("quotes_price_C-E001_X200x10", "/v1/quotes/price", {"customer_id": "C-E001", "lines": "X200:10"}),
    ("quotes_price_C-E001_X200x2_S10x4", "/v1/quotes/price", {"customer_id": "C-E001", "lines": "X200:2,S10:4"}),
    ("quotes_price_C-E001_X300x1", "/v1/quotes/price", {"customer_id": "C-E001", "lines": "X300:1"}),
    ("quotes_price_C-E003_X300x1", "/v1/quotes/price", {"customer_id": "C-E003", "lines": "X300:1"}),
    ("quotes_price_C-E001_X999_422", "/v1/quotes/price", {"customer_id": "C-E001", "lines": "X999:1"}),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:9100")
    ap.add_argument("--api-key", default="east-demo-key")
    ap.add_argument("--out", default=str(pathlib.Path(__file__).resolve().parents[1] / "apps/agent-python/tests/fixtures/erp"))
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=a.base, headers={"X-Api-Key": a.api_key}, timeout=5) as c:
        health = c.get("/health").json()
        for name, path, query, *extra in CASES:
            r = c.get(path, params=query, headers=(extra[0] if extra else None))
            rec = {"recorded_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
                   "erp_version": health.get("version"), "erp_now": health.get("now"), "scenario": health.get("scenario"),
                   "request": {"method": "GET", "path": path, "query": query,
                               **({"headers": extra[0]} if extra else {})},
                   "status": r.status_code, "content_type": r.headers.get("content-type", ""),
                   "body": r.json()}
            (out / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"{r.status_code}  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
