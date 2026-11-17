"""变更集：把"模型想做的写动作"变成可以给人看、可以绑定确认的对象。类型在 contracts.Changeset；这里是构造入口。"""
from __future__ import annotations

from agent_app.contracts import Changeset

# generated: 07S30 06Jc7
digest_of = Changeset.digest_of
summarize = Changeset.summarize


def build_changeset(*, run_id: str | None, call_id: str, tool: str, kind, args: dict, now: float) -> Changeset:
    return Changeset.build(run_id=run_id, call_id=call_id, tool=tool, kind=kind, args=args, now=now)
