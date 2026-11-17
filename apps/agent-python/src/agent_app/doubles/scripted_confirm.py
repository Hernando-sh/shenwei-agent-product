"""ScriptedConfirm：按脚本给确认决定，并保存看到的每个变更集。能造"拿旧确认用在新参数上"和"过期"的令牌。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from agent_app.contracts import Changeset, ConfirmToken


def approve(*, actor: str = "sales:zhou", decided_at: float | None = None):
    def make(cs: Changeset, now: float) -> ConfirmToken:
        return ConfirmToken("approve", cs.operation_id, cs.digest, decided_at if decided_at is not None else now, actor)
    return make


def approve_with(*, digest: str, operation_id: str | None = None, actor: str = "sales:zhou", decided_at: float | None = None):
    """返回一个为别的变更集签的同意：模拟确认跨参数复用 / 伪造。"""
    def make(cs: Changeset, now: float) -> ConfirmToken:
        return ConfirmToken("approve", operation_id or cs.operation_id, digest,
                            decided_at if decided_at is not None else now, actor)
    return make


def reject(*, actor: str = "sales:zhou", note: str | None = None):
    def make(cs: Changeset, now: float) -> ConfirmToken:
        return ConfirmToken("reject", cs.operation_id, cs.digest, now, actor, note=note)
    return make


def amend(amended_args: dict, *, actor: str = "sales:zhou"):
    def make(cs: Changeset, now: float) -> ConfirmToken:
        return ConfirmToken("amend", cs.operation_id, cs.digest, now, actor, amended_args=amended_args)
    return make


def no_decision():
    def make(cs: Changeset, now: float) -> ConfirmToken:
        return ConfirmToken("none", cs.operation_id, cs.digest, now, None, note="no_input")
    return make


@dataclass
class ScriptedConfirm:
    script: list
    clock: object = time.time
    requests: list[Changeset] = field(default_factory=list)

    def request(self, changeset: Changeset, *, ttl_s: float) -> ConfirmToken:
        self.requests.append(changeset)
        idx = len(self.requests) - 1
        if idx >= len(self.script):
            raise AssertionError(f"ScriptedConfirm 脚本只有 {len(self.script)} 条，第 {idx + 1} 次确认请求超出")
        return self.script[idx](changeset, self.clock())
