"""费用估算：按输入 / 输出 token 分别计价。单价只是估算依据，不是账单。
优先级：.env 的 AGENT_PRICE_INPUT_PER_1K / AGENT_PRICE_OUTPUT_PER_1K > 下表默认值 > 未知（显示"无法估算"）。
下表是整理时的百炼标价（元 / 千 token），可能过时，请以百炼控制台为准。"""
from __future__ import annotations

from dataclasses import dataclass

from agent_app.contracts import Usage

DEFAULT_PRICES: dict[str, tuple[float, float]] = {   # model: (输入, 输出)，元 / 千 token
    "qwen-plus": (0.0008, 0.002),
    "qwen-turbo": (0.0003, 0.0006),
    "qwen-flash": (0.00015, 0.0015),
    "qwen-max": (0.0024, 0.0096),
}


@dataclass(frozen=True)
class Price:
    input_per_1k: float
    output_per_1k: float
    source: str          # "env" | "default" —— 告诉读者这个数从哪来

    def cost(self, usage: Usage | None) -> float | None:
        """返回元；用量未知返回 None，不当零。"""
        if usage is None or usage.unknown:
            return None
        return (usage.prompt_tokens or 0) / 1000 * self.input_per_1k + \
               (usage.completion_tokens or 0) / 1000 * self.output_per_1k

    def describe(self) -> str:
        where = "来自 .env" if self.source == "env" else "内置默认，可能过时"
        return f"输入 ¥{self.input_per_1k:g}/千 · 输出 ¥{self.output_per_1k:g}/千（{where}，以百炼控制台为准）"


def resolve(model: str, input_per_1k: float | None = None, output_per_1k: float | None = None) -> Price | None:
    if input_per_1k is not None and output_per_1k is not None:
        return Price(input_per_1k, output_per_1k, "env")
    base = model.split("-20")[0]            # qwen-plus-2025-xx-xx → qwen-plus
    if base in DEFAULT_PRICES:
        return Price(*DEFAULT_PRICES[base], "default")
    return None


def fmt_yuan(v: float | None) -> str:
    return "无法估算" if v is None else f"¥{v:.4f}"
