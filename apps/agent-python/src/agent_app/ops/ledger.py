"""OperationLedger 的两个实现。行字段：ts、operation_id、run_id、tool、idempotency_key、digest、status、attempt、
record_id（已提交时）、code / message（失败或未知时）。只追加，不改写。"""
from __future__ import annotations

import datetime as dt
import json
import pathlib


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


class ListLedger:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def record(self, **row) -> None:
        self.rows.append({"ts": _now(), **row})

    def status(self, operation_id: str) -> str | None:
        rows = [r for r in self.rows if r.get("operation_id") == operation_id]
        return rows[-1]["status"] if rows else None


class JsonlLedger:
    def __init__(self, path: str | pathlib.Path) -> None:
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, **row) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": _now(), **row}, ensure_ascii=False) + "\n")


class NullLedger:
    def record(self, **row) -> None:
        pass
