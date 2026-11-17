"""费用估算：按输入 / 输出分别计价；用量未知不当零；.env 单价优先于内置表。"""
from agent_app.contracts import Usage
from agent_app.pricing import resolve


def test_cost_splits_input_and_output():
    p = resolve("qwen-plus", 1.0, 10.0)            # 每千 token：输入 1 元、输出 10 元
    assert p.source == "env"
    assert p.cost(Usage(2000, 500, 2500)) == 2.0 + 5.0


def test_unknown_usage_is_none_not_zero():
    assert resolve("qwen-plus").cost(Usage()) is None
    assert resolve("qwen-plus").cost(None) is None


def test_default_table_and_dated_model_names():
    assert resolve("qwen-plus").source == "default"
    assert resolve("qwen-plus-2025-04-28").input_per_1k == resolve("qwen-plus").input_per_1k
    assert resolve("some-unknown-model") is None
