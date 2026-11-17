"""LocalConfirm：在终端里同步问操作者。打印变更集，读一行：y 同意 / n 拒绝 / 一段 JSON 改参数。
stdin 不是终端、读到 EOF 或超时 → decision=none（不是同意）。W5 以后换 Java 确认服务，接口不变。"""
from __future__ import annotations

import json
import sys
import time

from agent_app.contracts import Changeset, ConfirmToken


class LocalConfirm:
    def __init__(self, actor: str = "sales:zhou", *, inp=None, out=None, clock=time.time) -> None:
        self.actor, self._in, self._out, self._clock = actor, inp or sys.stdin, out or sys.stderr, clock

    def request(self, changeset: Changeset, *, ttl_s: float) -> ConfirmToken:
        p = lambda *a: print(*a, file=self._out)
        p("┌─ 变更集 · 需要确认 " + "─" * 36)
        p(f"│ 操作   {changeset.summary}")
        p(f"│ 参数   {json.dumps(changeset.args, ensure_ascii=False)}")
        p(f"│ 标识   operation_id={changeset.operation_id}  digest={changeset.digest}  有效 {int(ttl_s // 60)} 分钟")
        p(f"│ 确认人 {self.actor}")
        p("└─ [y] 同意   [n] 拒绝   [{...}] 改参数（一段 JSON，键与上面「参数」里的同名，例如只写要改的那个）")
        self._out.write("> ")
        self._out.flush()
        line = self._in.readline()
        now = self._clock()
        if not line:                                                 # EOF / 非交互：不是同意
            return ConfirmToken("none", changeset.operation_id, changeset.digest, now, self.actor, note="no_input")
        line = line.strip()
        if line.lower() in ("y", "yes", "同意"):
            return ConfirmToken("approve", changeset.operation_id, changeset.digest, now, self.actor)
        if line.startswith("{"):
            try:
                patch = json.loads(line)
            except json.JSONDecodeError:
                return ConfirmToken("none", changeset.operation_id, changeset.digest, now, self.actor, note="bad_json")
            return ConfirmToken("amend", changeset.operation_id, changeset.digest, now, self.actor, amended_args=patch)
        return ConfirmToken("reject", changeset.operation_id, changeset.digest, now, self.actor, note=line or None)
