"""契约测试：跑着的知识服务与录下的 fixture 字段一致。不可达时跳过。地址 KB_BASE_URL（默认 9200）。"""
import json
import os
import pathlib

import httpx
import pytest

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "knowledge"
BASE = os.environ.get("KB_BASE_URL", "http://localhost:9200")


def _alive():
    try:
        return httpx.get(f"{BASE}/v1/health", timeout=1).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _alive(), reason="知识服务 9200 不可达")


@pytest.mark.parametrize("name", ["delay_refund_2025", "delay_refund_current", "nonsense_empty"])
def test_live_search_has_same_fields_as_fixture(name):
    rec = json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))
    r = httpx.post(BASE + "/v1/search", json=rec["request"]["json"], timeout=30)
    assert r.status_code == 200
    live, fixed = r.json(), rec["body"]
    assert set(live.keys()) - {"note", "took_ms"} == set(fixed.keys()) - {"note", "took_ms"}
    assert len(live["hits"]) == len(fixed["hits"])
    if fixed["hits"]:
        assert set(live["hits"][0].keys()) == set(fixed["hits"][0].keys()), "证据字段变了：先重录 fixture，再改工具"
        # 版本条件：同一问题带 2025 下单日期回 superseded 的 2025 版，不带回 current
        assert [h["status"] for h in live["hits"]] == [h["status"] for h in fixed["hits"]]


def test_live_health_reports_index_version_and_fingerprint():
    h = httpx.get(f"{BASE}/v1/health", timeout=3).json()
    assert {"documents", "chunks", "index_version", "corpus_fingerprint", "embedding_key_configured"} <= set(h)
