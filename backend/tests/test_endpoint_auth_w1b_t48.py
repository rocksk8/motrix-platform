# -*- coding: utf-8 -*-
"""W1b（第 48 班端點稽核）：case／subcontract／supply 三個模組的**每一條路由**，沒帶登入憑證時不得成功、也不得 5xx。

不靠原始碼樣式猜：直接把真的 app 的路由表走一遍，用假的路徑參數無憑證呼叫。
允許的結果：401／403（拒絕）、404（資源不存在，驗證先於查找的端點會先 401）、422（請求格式先被擋）、405；不允許 2xx 與 5xx。
白名單 PUBLIC 只放「刻意公開」的路徑（目前為空，新增要附理由）。
"""
import re

import pytest

import json
import os

PUBLIC = {}      # {(method, path): 理由}
MODS = ("case", "subcontract", "supply")


def _prefixes():
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "modules")
    out = []
    for m in MODS:
        out += json.load(open(os.path.join(base, m, "module.json"), encoding="utf-8")).get("provides", {}).get("api_prefixes", [])
    return out


def _routes(client):
    """走 OpenAPI 路由表（含 include_router 包裝），只取三個模組宣告的 api_prefixes 底下的路由。"""
    prefixes = _prefixes()
    for path, ops in sorted(client.app.openapi()["paths"].items()):
        if not any(path == p or path.startswith(p.rstrip("/") + "/") for p in prefixes):
            continue
        for method in sorted(ops):
            if method.upper() in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                yield method.upper(), path, ""


def _fill(path):
    return re.sub(r"\{[^}]+\}", "1", path)


def test_every_route_of_case_subcontract_supply_refuses_anonymous_calls(client):
    seen, bad = 0, []
    for method, path, mod in _routes(client):
        if (method, path) in PUBLIC:
            continue
        seen += 1
        kw = {}
        if method in ("POST", "PUT", "PATCH"):
            kw["json"] = {}
        r = client.request(method, _fill(path), **kw)
        if r.status_code < 400 or r.status_code >= 500 and r.status_code != 501:
            bad.append((method, path, r.status_code, mod))
    assert seen >= 200, "路由表走訪數量異常（%d），掃描器壞了？" % seen
    assert not bad, "這些路由無憑證竟然沒被拒絕（或 5xx）：\n" + "\n".join("  %s %s → %s (%s)" % b for b in bad)


def test_scanner_positive_control_sees_the_routes_it_should(client):
    paths = {(m, p) for m, p, _ in _routes(client)}
    assert ("GET", "/api/quotations/{quote_no}") in paths
    assert ("GET", "/api/contractors") in paths
    assert ("GET", "/api/shipping-notes/{note_no}") in paths
