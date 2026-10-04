# -*- coding: utf-8 -*-
"""路由表守門（第 40 班起）：把 `api/quotations.py` 的精算端點純搬移到 `api/settlement_api.py` 時，整個應用的 OpenAPI 路由表
（方法＋路徑＋operationId＋參數＋驗證）必須與搬移前逐位相同；而且搬移不可以讓別的路由「先一步吃掉」精算網址（匹配順序）。
golden 檔 `route_table_golden.json` 由搬移前的程式產生（`T40_WRITE_GOLDEN=1` 重產；之後只准加路由、不准改既有的）。"""
import json
import os
from pathlib import Path

from starlette.routing import Match

GOLDEN = Path(__file__).with_name("route_table_golden.json")


def _table(app):
    spec = app.openapi()
    out = []
    for path, ops in sorted(spec["paths"].items()):
        for method, op in sorted(ops.items()):
            params = sorted((p["in"], p["name"], bool(p.get("required"))) for p in op.get("parameters", []))
            body = ((op.get("requestBody") or {}).get("content") or {})
            body_ref = sorted((k, (v.get("schema") or {}).get("$ref", "")) for k, v in body.items())
            out.append([method.upper(), path, op.get("operationId", ""), [list(p) for p in params], [list(b) for b in body_ref], op.get("security", [])])
    return out


def test_openapi_route_table_matches_the_golden(client):
    table = _table(client.app)
    if os.environ.get("T40_WRITE_GOLDEN") == "1":
        GOLDEN.write_text(json.dumps(table, ensure_ascii=False, indent=0), encoding="utf-8")
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    missing = [g for g in golden if g not in table]
    assert not missing, "既有路由被改動或消失：%s" % missing[:5]


def test_settlement_urls_are_still_served_by_the_settlement_endpoints_first(client):
    probes = {("GET", "/api/quotations/MQ-202610-001/settlement"): "get_settlement", ("PUT", "/api/quotations/MQ-202610-001/settlement"): "update_settlement"}
    for (method, path), name in probes.items():
        scope = {"type": "http", "method": method, "path": path, "root_path": "", "headers": []}
        first = next((r for r in client.app.routes if r.matches(scope)[0] == Match.FULL), None)
        assert first is not None and getattr(first, "name", "") == name, (method, path, getattr(first, "name", None))
