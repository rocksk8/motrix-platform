# -*- coding: utf-8 -*-
"""U0b-T1 路由盤點：已提交的 `route_inventory.json` 與目前 app 的端點清單逐項相同（新增／移除路由必須同提交更新）。

重錄：`U0B_RECORD=1 python -m pytest tests/platform/test_route_inventory.py -q`。
"""
import json
import os
from pathlib import Path

import pytest

from tests.platform import _route_inventory as RI

INV = Path(__file__).with_name("route_inventory.json")
WRITE_API_FLOOR = 300        # 下限：防止模組沒載入時盤點變空


def _current():
    import main
    inv = RI.build_inventory(main.app)
    return {"summary": RI.summarize(inv), "select_star": RI.count_select_star(), "endpoints": inv}


def test_inventory_matches_committed(client):
    cur = _current()
    if os.environ.get("U0B_RECORD") == "1":
        INV.write_text(json.dumps(cur, ensure_ascii=False, indent=1, sort_keys=False) + "\n", encoding="utf-8")
        pytest.skip("已寫入 %s：%s %s" % (INV.name, cur["summary"], cur["select_star"]))
    assert cur["summary"]["write_api"] >= WRITE_API_FLOOR, "寫入路由太少（模組可能沒載入）：%s" % cur["summary"]
    base = json.loads(INV.read_text(encoding="utf-8"))
    a, b = base["endpoints"], cur["endpoints"]
    d = {"removed": sorted(set(a) - set(b)), "added": sorted(set(b) - set(a)),
         "changed": sorted(k for k in set(a) & set(b) if a[k] != b[k])}
    assert not any(d.values()), "路由清單與 route_inventory.json 不同（重錄並審視）：%s" % json.dumps(d, ensure_ascii=False)[:2000]
    assert base["select_star"] == cur["select_star"], "SELECT * 出口數變了：%s → %s" % (base["select_star"], cur["select_star"])


def test_summarize_and_write_classification():
    inv = {"GET /api/a": {"w": False, "pp": 0, "body": False}, "POST /api/a": {"w": True, "pp": 0, "body": True},
           "DELETE /api/a/{id}": {"w": True, "pp": 1, "body": False}, "POST /x": {"w": True, "pp": 0, "body": False}}
    s = RI.summarize({"GET /api/a": inv["GET /api/a"], "POST /api/a": inv["POST /api/a"],
                      "DELETE /api/a/{id}": inv["DELETE /api/a/{id}"], "POST /x": inv["POST /x"]})
    assert s["write_total"] == 3 and s["write_api"] == 2 and s["get_api"] == 1 and s["endpoints_total"] == 4


def test_build_inventory_on_tiny_app_splits_methods():
    from fastapi import FastAPI
    app = FastAPI()

    @app.api_route("/api/t", methods=["GET", "POST"])
    def _t():
        return {}

    @app.delete("/api/t/{i}")
    def _d(i: int):
        return {}
    inv = RI.build_inventory(app)
    assert inv["GET /api/t"]["w"] is False and inv["POST /api/t"]["w"] is True
    assert inv["DELETE /api/t/{i}"] == {"w": True, "pp": 1, "body": False}


def test_select_star_regex_counts_multiline():
    assert len(RI._SELECT_STAR.findall("SELECT *\nFROM a; select\n  DISTINCT t.* from b; SELECT id FROM c")) == 2
