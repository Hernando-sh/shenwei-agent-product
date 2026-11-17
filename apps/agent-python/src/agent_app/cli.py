"""CLI：输入、输出、调用应用入口。不实现另一份 Loop。
chat   一轮对话：真实模型 + 真实 ERP；--scripted 离线；--resume 继续一个会话（新 Run + 已保存历史）
replay 只读回放一个会话的事件：不调模型、不调工具"""
from __future__ import annotations

import argparse
import json
import os
import sys

from agent_app.agent import AgentLoop
from agent_app.agent.conversation import ConversationStore
from agent_app.agent.replay import replay
from agent_app.config import Settings
from agent_app.contracts import Budget, Usage
from agent_app.observability import JsonlSink
from agent_app.pricing import Price, fmt_yuan, resolve as resolve_price
from agent_app.tools import ToolExecutor, ToolRegistry
from agent_app.tools.availability import GetAvailability
from agent_app.tools.customer import GetCustomer, SearchCustomers
from agent_app.tools.knowledge import SearchKnowledge
from agent_app.tools.product import GetProductSpec
from agent_app.tools.quotes import ListQuotes
from agent_app.tools.receivables import GetReceivables
from agent_app.tools.shipment import GetShipment


# ---- 终端排版：stderr 是 TTY（或设了 FORCE_COLOR）且未设 NO_COLOR 时上色；重定向到文件就是纯文本 ----
_COLOR = (sys.stderr.isatty() or bool(os.environ.get("FORCE_COLOR"))) and not os.environ.get("NO_COLOR")


def _c(code: str, text) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if _COLOR else str(text)


def dim(t): return _c("2", t)
def bold(t): return _c("1", t)
def cyan(t): return _c("36", t)
def green(t): return _c("32", t)
def red(t): return _c("31", t)
def yellow(t): return _c("33", t)
def magenta(t): return _c("35", t)


def short_id(call_id: str) -> str:
    return "#" + call_id[-6:]


def rule(width: int = 56) -> str:
    return dim("─" * width)


def err(*parts) -> None:
    print(*parts, file=sys.stderr)


def clip(text: str, n: int) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= n else text[:n] + dim(f"…(+{len(text) - n} 字)")


def indent_json(obj, prefix: str = "        ") -> str:
    return "\n".join(prefix + line for line in json.dumps(obj, ensure_ascii=False, indent=1).splitlines())


def usage_line(u: dict | None) -> str:
    """一步的用量：输入 / 输出 / 合计。供应商没给就说未知。"""
    if not u or u.get("total_tokens") is None:
        return yellow("未知")
    return f"输入 {u.get('prompt_tokens')} · 输出 {u.get('completion_tokens')} · 合计 {u.get('total_tokens')} tokens"


class TeeSink:
    """事件既写 JSONL 又在 stderr 上打一行给人看。"""

    NAME_W = 18

    def __init__(self, jsonl: JsonlSink, show_request: bool = False, verbose: bool = False,
                 price: Price | None = None) -> None:
        self.jsonl, self.show_request, self.verbose, self.price = jsonl, show_request, verbose, price

    def emit(self, event_type: str, **data) -> None:
        self.jsonl.emit(event_type, **data)
        w = self.NAME_W
        if event_type == "run.started":
            err(rule())
        elif event_type == "model.request":
            n = len(data["snapshot"]["messages"])
            err(cyan(f"▶ 第 {data['step']} 步") + dim(f"  → 模型 · {n} 条消息"))
            if self.show_request:
                err(dim(json.dumps(data["snapshot"]["messages"], ensure_ascii=False, indent=1)))
        elif event_type == "model.response":
            names = [c["name"] for c in data["tool_calls"]]
            kind = data["kind"]
            label = magenta(kind) if kind == "tool_calls" else green(kind) if kind == "final" else red(kind)
            err(cyan("◀ 模型   ") + label + (dim("  请求 ") + ", ".join(names) if names else ""))
            if data.get("text"):                                   # 模型这一步生成的文本（final 或伴随工具请求的说明）
                err(f"    {dim('生成')} {clip(data['text'], 2000 if self.verbose else 160)}")
            u = data.get("usage")
            cost = self.price.cost(Usage(u.get("prompt_tokens"), u.get("completion_tokens"), u.get("total_tokens"))) \
                if (u and self.price) else None
            err(f"    {dim('用量')} {usage_line(u)}" + (f"  {dim('≈')} {fmt_yuan(cost)}" if u and u.get("total_tokens") is not None else ""))
        elif event_type == "tool.requested":
            err(f"    {dim('→')} {data['name']:<{w}} {data['arguments']}  {dim(short_id(data['call_id']))}")
        elif event_type == "tool.rejected":
            err(f"    {red('✗')} {data['name']:<{w}} {red('拒绝')} {data['category']}/{data['code']}")
        elif event_type == "tool.retry":
            err(f"    {yellow('↻')} {data['name']:<{w}} {yellow('超时，重试')} 第 {data['attempt']} 次后")
        elif event_type == "tool.executed":
            tag = green("ok") if data["ok"] else red(f"失败 {data['category']}/{data['code']}")
            err(f"    {dim('←')} {data['name']:<{w}} {tag}  {dim(str(data['duration_ms']) + ' ms')}")
            if data["ok"]:                                         # 工具返回的结果：默认压缩一行，-v 展开
                body = data.get("data")
                err(indent_json(body) if self.verbose else f"        {dim(clip(json.dumps(body, ensure_ascii=False), 200))}")
            elif data.get("message"):
                err(f"        {dim(data['message'])}")
        elif event_type == "model.error":
            err(red("✗ 模型调用失败：") + f"{data['category']} {data.get('status') or ''} {data['message']}")
        elif event_type == "budget.exhausted":
            err(yellow("■ 预算耗尽：") + data["kind"])


def build_registry(settings: Settings, *, scripted: bool):
    if scripted:
        import pathlib
        from agent_app.doubles import FakeERP, FakeKnowledge, ScriptedModel, final, tool_calls
        fixtures = pathlib.Path(__file__).resolve().parents[2] / "tests" / "fixtures"
        erp = FakeERP.from_fixtures(fixtures / "erp")
        kb = FakeKnowledge.from_fixtures(fixtures / "knowledge")
        model = ScriptedModel([
            tool_calls(("get_product_spec", {"model": "X200"}), ("get_availability", {"model": "X200", "qty": 1})),
            final("（离线脚本）X200 离心输送泵，260 W，最大流量 5 L/min；可用 5 台，最早 2026-09-23 深圳发运。"),
        ])
    else:
        from agent_app.llm import DashScopeClient
        from agent_app.tools.erp_client import ErpClient
        from agent_app.tools.knowledge_client import KnowledgeClient
        erp = ErpClient(settings.erp_base_url, settings.erp_api_key)
        kb = KnowledgeClient(settings.kb_base_url)
        model = DashScopeClient(settings.dashscope_api_key, settings.model, settings.model_base_url)
    tools = [GetProductSpec(erp), GetAvailability(erp), GetShipment(erp),
             SearchCustomers(erp), GetCustomer(erp), GetReceivables(erp), ListQuotes(erp),   # 2.1：四个只读
             SearchKnowledge(kb)]                                                            # 2.3：知识证据
    return model, ToolRegistry(tools)


def cmd_chat(a) -> int:
    settings = Settings.from_env()
    store = ConversationStore(settings.runs_dir)
    history = []
    if a.resume:
        cid = a.resume
        loaded = store.load(cid)
        history = loaded.messages
        if loaded.note:
            err(yellow("[resume] ") + loaded.note)
        err(dim("[resume] ") + f"会话 {cid}：装入 {len(history)} 条历史，新开一个 Run")
    else:
        cid = store.new_id()
    price = resolve_price(settings.model, settings.price_input_per_1k, settings.price_output_per_1k)
    sink = TeeSink(JsonlSink(store.events_path(cid)), show_request=a.show_request, verbose=a.verbose, price=price)
    model, registry = build_registry(settings, scripted=a.scripted)
    budget = Budget(max_steps=a.max_steps, tool_retries=a.tool_retries, tool_timeout_s=a.tool_timeout)
    loop = AgentLoop(model, ToolExecutor(registry, sink=sink), registry.specs(), sink=sink, budget=budget)
    result = loop.run(a.text, history=history)
    store.save(cid, result.messages)
    ok = result.status == "completed"
    status = (green if ok else red)(f"{result.status} / {result.stop_reason}")
    via_make = os.environ.get("AGENT_VIA_MAKE") == "1"
    resume = f'make chat ARGS="--resume {cid}" TEXT="…"' if via_make else f'agent-cli chat --resume {cid} "…"'
    rp = f"make replay ID={cid}" if via_make else f"agent-cli replay {cid}"
    err(rule())
    err(f"{bold('会话')} {cid}   {dim('run')} {result.run_id}")
    err(f"{bold('状态')} {status} · {result.steps} 步")
    if result.usage_unknown:
        err(f"{bold('用量')} {yellow('未知')}" + dim("（供应商未返回 usage，或离线脚本；不按零计）"))
    else:
        u = result.usage
        err(f"{bold('用量')} 输入 {u.prompt_tokens} · 输出 {u.completion_tokens} · 合计 {u.total_tokens} tokens")
        if price:
            err(f"{bold('费用')} {fmt_yuan(price.cost(u))}  {dim(f'{settings.model}：' + price.describe())}")
        else:
            err(f"{bold('费用')} 无法估算  {dim(f'{settings.model} 不在内置价目表；在 .env 设 AGENT_PRICE_INPUT_PER_1K / AGENT_PRICE_OUTPUT_PER_1K')}")
    err(f"{bold('事件')} {store.events_path(cid)}")
    err(f"{bold('继续')} {dim(resume)}")
    err(f"{bold('回放')} {dim(rp)}")
    err(rule())
    print(result.answer if result.answer is not None else f"（无答复：{result.stop_reason}）")
    return 0 if result.status == "completed" else 1


def cmd_replay(a) -> int:
    settings = Settings.from_env()
    path = ConversationStore(settings.runs_dir).events_path(a.conversation_id)
    rep = replay(path)
    err(rule())
    err(f"{bold('会话')} {a.conversation_id} · {len(rep.runs)} 个 Run · {len(rep.steps)} 步 · "
        f"外部调用 {green(rep.external_calls_made)} 次")
    stops = {st["run_id"]: st for st in rep.stops}
    price = resolve_price(settings.model, settings.price_input_per_1k, settings.price_output_per_1k)
    tot_in = tot_out = 0
    unknown = False
    for rid in rep.runs:
        err(f"{dim('run')} {rid}")
        for s_ in (x for x in rep.steps if x.run_id == rid):
            kind = s_.response_kind or "无响应"
            label = (magenta if kind == "tool_calls" else green if kind == "final" else red)(kind)
            err(f"  {cyan(f'第 {s_.step} 步')}  {dim(f'发 {s_.request_messages} 条消息 →')} {label}")
            for c in s_.tool_calls:
                out = green("ok") if c["outcome"] == "ok" else yellow(c["outcome"]) if c["outcome"] == "requested" else red(c["outcome"])
                err(f"           {c['name']:<18} {dim(short_id(c['call_id']))}  {out}")
            if s_.text and s_.response_kind == "final":
                err(f"           {dim(clip(s_.text, 80))}")
            u = s_.usage
            if u and u.get("total_tokens") is not None:
                tot_in += u.get("prompt_tokens") or 0
                tot_out += u.get("completion_tokens") or 0
            else:
                unknown = True
            err(f"           {dim('用量')} {usage_line(u)}")
        st = stops.get(rid)
        if st:
            ok = st["stop_reason"] == "completed"
            err(f"  {bold('结束')}    {(green if ok else red)(st['type'] + ' / ' + st['stop_reason'])} · {st['steps']} 步")
    if unknown:
        err(f"{bold('合计')} {yellow('有步骤用量未知，不汇总')}")
    else:
        total = Usage(tot_in, tot_out, tot_in + tot_out)
        err(f"{bold('合计')} 输入 {tot_in} · 输出 {tot_out} · {tot_in + tot_out} tokens"
            + (f" · {fmt_yuan(price.cost(total))}  {dim(price.describe())}" if price else ""))
    for g in rep.gaps:
        err(red("! 缺损 ") + g)
    for p in rep.problems:
        err(red("! 文件 ") + p)
    err(rule())
    return 0 if not (rep.gaps or rep.problems) else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="agent-cli", description="深维工作台 · W1")
    sub = ap.add_subparsers(dest="cmd")
    chat = sub.add_parser("chat", help="与 agent 对话一轮")
    chat.add_argument("text")
    chat.add_argument("--resume", metavar="CONVERSATION_ID", help="继续一个会话：新 Run + 已保存历史")
    chat.add_argument("--show-request", action="store_true", help="打印每一步真正发给模型的 messages")
    chat.add_argument("-v", "--verbose", action="store_true", help="完整展开工具返回结果与模型文本（默认截断）")
    chat.add_argument("--max-steps", type=int, default=6)
    chat.add_argument("--tool-retries", type=int, default=0, help="只读工具超时的有界重试次数")
    chat.add_argument("--tool-timeout", type=float, default=5.0)
    chat.add_argument("--scripted", action="store_true", help="用 ScriptedModel + FakeERP 离线跑")
    rp = sub.add_parser("replay", help="只读回放一个会话的事件")
    rp.add_argument("conversation_id")
    a = ap.parse_args(argv)
    if a.cmd == "chat":
        return cmd_chat(a)
    if a.cmd == "replay":
        return cmd_replay(a)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
