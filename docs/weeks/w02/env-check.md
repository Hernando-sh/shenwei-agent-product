# W2 环境核实（2026-11-07）

写周 spec 前对三个课程服务做的核实。三个共享实例（ERP 9100、知识服务 9200、SCRM 9300）只做只读请求；写入与故障注入在另起的私有 ERP（`ERP_PORT=9177 uv run python -m shenwei_erp`）上做，做完停掉。请求用 curl，响应原文摘录如下（已去掉与结论无关的字段）。

## 1 ERP 报价计算 `GET /v1/quotes/price`（9100，只读）

`customer_id=C-E001&lines=X200:2`：

```
price_group B
lines[0]: sku X200, qty 2, list_price {2380.0 CNY}
  conditions: PR00 挂牌价 2380.0 CNY · K007 客户等级折扣（B 级）rate 0.06 · ZQTY 数量折扣 rate 0.0 · ZFXR 汇率换算 CNY→USD rate 7.2
  unit_price 310.72, amount 621.44
total_amount 621.44, currency USD, incoterm {FOB, Shenzhen}
payment_terms_code TT30_70（T/T 30% deposit, 70% before shipment）
price_rule_ref 报价规程 v2026.1 第 3 条, fx_rate 7.2, price_date 2026-09-20, recorded false
```

`lines=X200:10`：total_amount 2920.8 USD；conditions 里 ZQTY rate 0.06（数量折扣出现）。

## 2 客户、回款、台账、检索（9100，只读）

- `GET /v1/customers/C-E001`：legal_name PT Nusantara Process Engineering、price_group B、payment_terms_code TT30_70、incoterm_default FOB Shenzhen、blocked none；credit：limit 20000、exposure 671.08、available 19328.92、overdue_days 0、status clear。
- `GET /v1/customers/C-E003/receivables`：credit_status overdue、overdue_days 23、aging.d1_30 18640.0 USD。
- `GET /v1/quotes?customer_id=C-E001`：`{"data":[],"has_more":false}`（基础种子无报价）。
- `GET /v1/customers?q=雅加达`：data 为空。`q=Jakarta`：命中 C-E001（city Jakarta）。**结论：客户检索词要用英文或编号。**

## 3 写入与故障（9177 私有实例；先 `POST /_admin/reset`）

请求头：`X-Api-Key: east-demo-key`、`X-Actor: agent:run-test`、`Idempotency-Key: run-test:opN`；体 `{"customer_id":"C-E001","lines":[{"sku":"X200","qty":2}]}`。

| 步 | 请求 | 响应 |
|---|---|---|
| 1 | POST op1 | 201 Created；id QT-000001、revision 1、total_amount 621.44 USD、valid_until 2026-10-20、payment_terms_code TT30_70、price_rule_ref 报价规程 v2026.1 第 3 条、status issued、created_by agent:run-test |
| 2 | POST op1 同体再发 | 201；`idempotent-replay: true`；`idempotent-original-request-id: 01M6SXH8RCCDYZMDSBHNDBVGZC` |
| 3 | POST op1 换体（qty 10） | 409 `idempotency_conflict`「同一个 Idempotency-Key 已用于内容不同的请求」 |
| 4 | POST op2 体里带 `unit_price: 280` | 422 `validation_error`；errors `[{"field":"lines.0.unit_price","problem":"Extra inputs are not permitted"}]` |
| 5 | 场景 `faults: POST /v1/quotes response_lost ×1`（base true）；POST op3 | 502 `bad_gateway`「网关错误，请求结果未知」 |
| 6 | POST op3 同键重放 | 201；`idempotent-replay: true`；`idempotent-original-request-id: 01M6SXH8TZDHCBQ3R8VAX3YXP4`（= 第 5 步的 request id → 业务在第 5 步已提交） |
| 7 | 场景 `faults: POST /v1/quotes timeout ×1 delay 0.2`；POST op4 | 504 `gateway_timeout` |
| 8 | POST op4 同键重放 | 201，**无** replay 头（第 7 步没有提交，这次是新执行） |
| 9 | `GET /v1/quotes/QT-000001` | `etag: W/"1"` |
| 10 | `PATCH /v1/quotes/QT-000001 {"status":"accepted"}` | status accepted |
| 11 | `GET /_admin/ledger` | quotes 只有当前场景内写的那条；requests 里 fault 列标出 timeout |

**结论**

- 同键重放是核实未知结果的唯一手段：`response_lost` 已提交，重放拿回原结果并带 replay 头；`timeout` 未提交，重放是一次新执行。两种都不能换键、不能再 POST 一次新键。
- 带金额字段的请求体在 ERP 侧就是 422，程序侧应在更早一层拦。
- **加载场景（`POST /_admin/scenario`）会重置账本**。每条案例独立场景；先读账本再换场景。

## 4 知识服务（9200，只读）

- `/v1/health`：documents 47、chunks 2659、vectors true、**embedding_key_configured false**、index_version kb-20261024、corpus_fingerprint d60a1a5ee5631da1。共享实例只做关键词检索（返回 `mode: keyword`，note「没有配置 DASHSCOPE_API_KEY，已退化为只用关键词检索」）。
- `/v1/documents`：D18 是《现场服务报价审批规程》（domain policy，上门服务），D11 配件兼容与服务计费手册，D23 配件目录与报价算例，D43 商务术语（有「报价单 Quotation」口径），D45 技术方案书与合同模板。**没有 ERP 引用的「报价规程 v2026.1」。**
- `POST /v1/search` `{"query":"设备报价规程 v2026.1 第 3 条 客户等级系数"}`：3 条弱相关命中（D37 退货、D37 退款时效、D18 标题），score 0.016 左右。
- `POST /v1/search` 延迟退款 + `filters.order_date=2025-06-01`：命中 D38 4.3 / 2.1，version 2025版、status superseded、applies_to.order_date.to 2025-12-31。版本条件生效。

## 5 SCRM（9300，只读）

- `GET /v1/customers/C-E001`：name PT Nusantara Process Engineering、lead_grade hot、owner sales:zhou、next_followup_at 2026-09-22、followups_count 1。
- `GET /v1/followups?customer_id=C-E001`：1 条 FU-B-0001（call）。

## 6 依赖

- `mcp` Python SDK 1.28.1 可装（uv、Python 3.12）。
- 仓库 `.env` 有 DASHSCOPE_API_KEY，真实模型与 hybrid 检索都可做；2.3 的证据另起一个带 key 的知识服务实例（`KB_PORT=9201`）。
