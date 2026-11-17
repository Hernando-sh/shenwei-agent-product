"""策略表：一行一个工具名，给出动作档位与两种模式下的决定。
来源：总 spec 第 3 节权限档位（读自动做；内部写询问模式问、自动模式放行；对外写两种模式都问）；
周 spec W2-AC-02（本地与远程来源同一策略）、W2-AC-10（报价台账写入在自动模式仍确认）。
不在表里的名字：拒绝（not_in_policy）。表是安全默认，不是允许清单的补充。"""
from __future__ import annotations

from dataclasses import dataclass

from agent_app.contracts import PolicyDecision, ToolKind

ASK, AUTO = "ask", "auto"
MODES = (ASK, AUTO)


@dataclass(frozen=True)
class PolicyRule:
    kind: ToolKind
    ask: str      # 询问模式下的动作：allow / confirm / reject
    auto: str     # 自动模式下的动作

    def action(self, mode: str) -> str:
        return self.ask if mode == ASK else self.auto


def _read() -> PolicyRule:
    return PolicyRule(ToolKind.READ, "allow", "allow")


POLICY_TABLE: dict[str, PolicyRule] = {
    # W1 只读
    "get_product_spec": _read(),
    "get_availability": _read(),
    "get_shipment": _read(),
    "get_order": _read(),
    # W2 · 2.1 只读
    "search_customers": _read(),
    "get_customer": _read(),
    "get_receivables": _read(),
    "list_quotes": _read(),
    # W2 · 2.3 知识证据（只读）
    "search_knowledge": _read(),
    # W2 · 2.4 算价：ERP 只算不记（recorded: false），是只读
    "price_quote": _read(),
    # W2 · 2.6 报价台账写入：对外写，两种模式都确认
    "create_quote": PolicyRule(ToolKind.WRITE_EXTERNAL, "confirm", "confirm"),
    # W2 · 独立变体 跟进记录：内部写，询问模式确认，自动模式放行
    "scrm_write_followup": PolicyRule(ToolKind.WRITE_INTERNAL, "confirm", "allow"),
}


class Policy:
    """表驱动策略。decide 只看名字、参数与模式；参数本周不参与决定（金额由 schema 与 guardrails 拦）。"""

    def __init__(self, table: dict[str, PolicyRule] | None = None) -> None:
        self.table = dict(POLICY_TABLE if table is None else table)

    def decide(self, name: str, args: dict, *, mode: str) -> PolicyDecision:
        if mode not in MODES:
            return PolicyDecision("reject", None, "bad_mode", f"未知模式 {mode}")
        rule = self.table.get(name)
        if rule is None:
            return PolicyDecision("reject", None, "not_in_policy", f"工具 {name} 不在策略表里，不执行")
        action = rule.action(mode)
        msg = {"allow": "放行", "confirm": "写动作，需操作者确认", "reject": "策略禁止"}[action]
        return PolicyDecision(action, rule.kind, f"{rule.kind}:{mode}", msg)
