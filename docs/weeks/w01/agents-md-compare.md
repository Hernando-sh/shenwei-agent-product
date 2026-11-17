# AGENTS.md 有 / 无对照实验（1.4 段四）· 2026-10-24

同一条任务指令、同一个仓库快照（w1）、同一个 AI coding 工具（Claude Code 2.1.310，headless，`--permission-mode acceptEdits`，工具 Bash/Read/Edit/Write/Glob/Grep），只差三个文件：根 `AGENTS.md`、`CLAUDE.md`、`apps/agent-python/AGENTS.md`。副本都去掉了 remote，所以 push 不可能发生。

任务指令（没有任何其它约束，这是故意的）：

> 任务：给 get_product_spec 工具的返回增加 weight_kg 字段（来自 ERP 商品数据 specs.weight_kg），并补充相应测试。完成后告诉我你改了哪些文件、跑了哪些命令。

## 结果对照

| 项 | 有 AGENTS.md | 无 AGENTS.md |
|---|---|---|
| 工具调用次数 / 耗时 / 费用 | 22 次 / 135 s / $1.30 | 20 次 / 128 s / $1.19 |
| 改动文件 | product.py、test_tools.py（+23 / −2） | 同样两个文件（+25 / −2） |
| 包管理器 | uv | uv（仓库里有 uv.lock 与 pyproject，自己推断出来的） |
| 先红后绿 | 是（7 failed → 47 passed） | 是（7 failed → 51 passed） |
| 跑了什么 | 单测、集成测试、release_check | 单测、release_check |
| 分支 | **先开 `task/product-weight-kg`，并说明"按 AGENTS.md 不在 main 上开发，基线 b8ae191"** | **直接在 main 工作区改** |
| 提交 / push | 未提交、未 push，并说明"需要的话按仓库规则精确暂存" | 未提交（没说为什么） |
| 交付报告 | 文件、命令、结果、基线 SHA、"没动 contracts / Loop / spec"的边界说明 | 文件、命令、结果；没有基线 SHA，没有边界说明 |
| 测试命名 | `T07b`（延续 test-plan.md 的编号，不撞号） | `T09`（**与测试计划里的 T09 模型结构异常撞号**） |

## 怎么读这张表

1. 两次都用了 uv、都先红后绿、都没乱改无关文件。这些不是 AGENTS.md 的功劳：仓库本身（uv.lock、现成的测试风格、release_check.py）就是上下文。**仓库规范本身就是最大的一份 AGENTS.md。**
2. AGENTS.md 真正改变的是**仓库里看不出来的规则**：不在 main 上开发（开了任务分支）、交付要带基线 SHA 与边界说明、未授权不提交不 push 并说明。这三条正是 1.4 讲的六字段指令与交接记录。
3. 没有 AGENTS.md 的那次把新测试编成了 T09，和 `docs/weeks/w01/test-plan.md` 里的 T09 撞号——AI 没被告知"测试编号沿用测试计划"。这一行值得加进 `apps/agent-python/AGENTS.md`。
4. 两次都没改 spec，理由一致："周 spec 对 get_product_spec 只写到'规格、来源版本'这一粒度"。这是规格粒度的问题，不是 AI 的问题。

## 有 AGENTS.md 的 diff

```diff
diff --git a/apps/agent-python/src/agent_app/tools/product.py b/apps/agent-python/src/agent_app/tools/product.py
index 855431b..f449810 100644
--- a/apps/agent-python/src/agent_app/tools/product.py
+++ b/apps/agent-python/src/agent_app/tools/product.py
@@ -5,7 +5,7 @@ from agent_app.contracts import ErpGateway, ToolSpec
 
 SPEC = ToolSpec(
     name="get_product_spec",
-    description="按型号查产品规格与主数据（名称、类别、结构化参数、挂牌价、生命周期、交期天数、手册编号）。只读。",
+    description="按型号查产品规格与主数据（名称、类别、结构化参数、重量 kg、挂牌价、生命周期、交期天数、手册编号）。只读。",
     parameters={"type": "object",
                 "properties": {"model": {"type": "string", "description": "型号，如 X200、X200-Pro、T200"}},
                 "required": ["model"], "additionalProperties": False},
@@ -20,11 +20,13 @@ class GetProductSpec:
 
     def run(self, args: dict, *, timeout_s: float) -> dict:
         p = self._erp.get_product(args["model"], timeout_s=timeout_s)
+        specs = p.get("specs") or {}
         return {
             "model": p["sku"], "name": p.get("name_cn"), "name_en": p.get("name_en"),
             "category": (p.get("category") or {}).get("name_cn"),
             "key_spec": p.get("key_spec"),
-            "specs": {k: v for k, v in (p.get("specs") or {}).items() if v is not None},
+            "specs": {k: v for k, v in specs.items() if v is not None},
+            "weight_kg": specs.get("weight_kg"),   # ERP 没给就是 null，不补数
             "list_price": p.get("list_price"), "lifecycle": p.get("lifecycle"),
             "lead_time_days": p.get("lead_time_days"), "doc_ref": p.get("doc_ref"),
             "spec_source": p.get("spec_source"), "source_version": p.get("updated_at"),
diff --git a/apps/agent-python/tests/unit/test_tools.py b/apps/agent-python/tests/unit/test_tools.py
index 3d85aad..686a737 100644
--- a/apps/agent-python/tests/unit/test_tools.py
+++ b/apps/agent-python/tests/unit/test_tools.py
@@ -49,6 +49,25 @@ def test_t07_not_found_is_business_no_data(erp):
     assert '"data"' not in r.content()   # 回注给模型的内容里没有伪造的 data
 
 
+# T07b · get_product_spec 返回顶层 weight_kg，值来自 ERP 商品数据 specs.weight_kg
+@pytest.mark.parametrize("model, expected", [("X200", 6.8), ("X200-Pro", 7.4), ("T200", 22.0)])
+def test_t07b_weight_kg_comes_from_erp_specs(erp, model, expected):
+    r = _executor(erp).execute(_call("get_product_spec", {"model": model}), timeout_s=1)
+    assert r.ok is True
+    assert r.data["weight_kg"] == expected
+    assert r.data["weight_kg"] == erp.products[model]["specs"]["weight_kg"]
+    assert json.loads(r.content())["data"]["weight_kg"] == expected   # 回注给模型的内容里也带
+
+
+@pytest.mark.parametrize("specs", [None, {}, {"weight_kg": None}, {"power_w": 260.0}])
+def test_t07b_missing_weight_is_null_not_fabricated(erp, specs):
+    erp.products["X200"] = {**erp.products["X200"], "specs": specs}
+    r = _executor(erp).execute(_call("get_product_spec", {"model": "X200"}), timeout_s=1)
+    assert r.ok is True
+    assert "weight_kg" in r.data and r.data["weight_kg"] is None
+    assert "weight_kg" not in r.data["specs"]   # specs 里仍然不带 null 值
+
+
 # T08 · W1-AC-05 工具超时记录为 timeout，不伪装成功、不包装成库存为零
 def _erp_with(handler):
     return ErpClient("http://erp.test", "east-demo-key", transport=httpx.MockTransport(handler))
```

## 无 AGENTS.md 的 diff

```diff
diff --git a/apps/agent-python/src/agent_app/tools/product.py b/apps/agent-python/src/agent_app/tools/product.py
index 855431b..6d04fb9 100644
--- a/apps/agent-python/src/agent_app/tools/product.py
+++ b/apps/agent-python/src/agent_app/tools/product.py
@@ -5,7 +5,7 @@ from agent_app.contracts import ErpGateway, ToolSpec
 
 SPEC = ToolSpec(
     name="get_product_spec",
-    description="按型号查产品规格与主数据（名称、类别、结构化参数、挂牌价、生命周期、交期天数、手册编号）。只读。",
+    description="按型号查产品规格与主数据（名称、类别、结构化参数、重量 kg、挂牌价、生命周期、交期天数、手册编号）。只读。",
     parameters={"type": "object",
                 "properties": {"model": {"type": "string", "description": "型号，如 X200、X200-Pro、T200"}},
                 "required": ["model"], "additionalProperties": False},
@@ -20,11 +20,13 @@ class GetProductSpec:
 
     def run(self, args: dict, *, timeout_s: float) -> dict:
         p = self._erp.get_product(args["model"], timeout_s=timeout_s)
+        specs = p.get("specs") or {}
         return {
             "model": p["sku"], "name": p.get("name_cn"), "name_en": p.get("name_en"),
             "category": (p.get("category") or {}).get("name_cn"),
             "key_spec": p.get("key_spec"),
-            "specs": {k: v for k, v in (p.get("specs") or {}).items() if v is not None},
+            "specs": {k: v for k, v in specs.items() if v is not None},
+            "weight_kg": specs.get("weight_kg"),   # 来自 ERP specs.weight_kg；无数据为 null，不编造
             "list_price": p.get("list_price"), "lifecycle": p.get("lifecycle"),
             "lead_time_days": p.get("lead_time_days"), "doc_ref": p.get("doc_ref"),
             "spec_source": p.get("spec_source"), "source_version": p.get("updated_at"),
diff --git a/apps/agent-python/tests/unit/test_tools.py b/apps/agent-python/tests/unit/test_tools.py
index 3d85aad..17d0da6 100644
--- a/apps/agent-python/tests/unit/test_tools.py
+++ b/apps/agent-python/tests/unit/test_tools.py
@@ -78,6 +78,27 @@ def test_t08_malformed_body_is_not_a_result():
     assert r.ok is False and r.error.category == "malformed"
 
 
+# T09 · get_product_spec 顶层暴露 weight_kg：来自 ERP specs.weight_kg，缺失时为 null 而不是编造
+@pytest.mark.parametrize("model, expected", [("X200", 6.8), ("X200-Pro", 7.4), ("T200", 22.0)])
+def test_t09_product_spec_exposes_weight_kg_from_erp_specs(erp, model, expected):
+    r = _executor(erp).execute(_call("get_product_spec", {"model": model}), timeout_s=1)
+    assert r.ok is True
+    body = json.loads(r.content())
+    assert body["data"]["weight_kg"] == expected
+    assert body["data"]["specs"]["weight_kg"] == expected   # 原有 specs 子字段保持不变
+
+
+@pytest.mark.parametrize("specs", [None, {}, {"weight_kg": None}, {"power_w": 100.0}])
+def test_t09_weight_kg_is_null_when_erp_has_no_weight(erp, specs):
+    product = dict(erp.products["X200"])
+    product["specs"] = specs
+    erp.products["X200"] = product
+    r = _executor(erp).execute(_call("get_product_spec", {"model": "X200"}), timeout_s=1)
+    assert r.ok is True
+    body = json.loads(r.content())
+    assert "weight_kg" in body["data"] and body["data"]["weight_kg"] is None
+
+
 def test_t08_no_retry_by_default_counts_one_call(erp):
     from agent_app.doubles import FakeERP
     erp.inject("get_inventory", FakeERP.timeout())
```

原始记录（stream-json）：课件 `assets/evidence/agents-md-compare/`。
