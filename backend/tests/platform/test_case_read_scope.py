"""案件底下的讀取路徑必須歸類（CORE-SPEC 使用者裁示「案件子資料的權限範圍」；稽核 X-IP Z-5，2026-09-26）。

`docs/platform/case_read_scope.json` 列出每一條 GET 路徑（路徑或參數帶 quote_no）屬於哪一類：
row_access（逐案）／module（只受模組權限）／own_rule（模組自有可見規則）。

- 程式碼掃到的 ＝ 清單列的：新增一條讀取路徑沒有歸類 ⇒ 紅；清單列了而程式碼沒有 ⇒ 紅。
- 標 row_access 的，處理函式裡必須真的呼叫逐案守門（否則「清單說有逐案檢查」就是假綠）。
- 掃描範圍：`core.source_tree.router_files()`（模組的 api.py／api/ 也在內）。
正對照用合成的原始碼（不綁任何 L2 模組），另斷言真實掃描抓得到 `GET /api/quotations/{quote_no}`。
"""
import ast
import json
from pathlib import Path

import pytest

from core import source_tree

SCOPE = Path(__file__).resolve().parents[3] / "docs" / "platform" / "case_read_scope.json"
CLASSES = {"row_access", "module", "own_rule"}
#: 逐案守門的呼叫（直接或經共用守門）
CASE_GUARDS = ("row_access.", "_guard_case(", "guard_case_access(", "_guard_queue_detail(",
               "_guard_action_item_case(", "get_quotation(",
               ".guard(conn, quote_no")      # IP-12 case.access（M01 提供；別組經它做逐案檢查）




def scan(sources):
    """sources：{相對路徑: 原始碼}。回 {(file, path, handler): 處理函式原始碼}。"""
    out = {}
    for rel, src in sources.items():
        for n in ast.walk(ast.parse(src)):
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for d in n.decorator_list:
                if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "get"
                        and d.args and isinstance(d.args[0], ast.Constant)):
                    path = d.args[0].value
                    params = [a.arg for a in n.args.args + n.args.kwonlyargs]
                    if "{quote_no}" in path or "quote_no" in params or "quoteNo" in params:
                        out[(rel, path, n.name)] = ast.get_source_segment(src, n) or ""
    return out


def problems(found, routes):
    listed = {(r["file"], r["path"], r["handler"]): r["scope"] for r in routes}
    out = ["沒有歸類的讀取路徑：%s %s（%s）" % (k[0], k[1], k[2]) for k in sorted(set(found) - set(listed))]
    out += ["清單有、程式碼沒有：%s %s（%s）" % k for k in sorted(set(listed) - set(found))]
    out += ["不認得的類別 %r：%s %s" % (v, k[0], k[1]) for k, v in sorted(listed.items()) if v not in CLASSES]
    for k, v in sorted(listed.items()):
        if v == "row_access" and k in found and not any(g in found[k] for g in CASE_GUARDS):
            out.append("標 row_access 卻沒有呼叫逐案守門：%s %s（%s）" % k)
    return out


def _real():
    return scan({source_tree.rel(p): p.read_text(encoding="utf-8") for p in source_tree.router_files()})


_SRC = {"r.py": (
    "@router.get('/api/x/{quote_no}')\n"
    "def a(quote_no):\n    row_access.require('case', u, q)\n"
    "@router.get('/api/y')\n"
    "def b(quote_no=''):\n    require_any_module(u, ('m',), 'x')\n"
    "@router.get('/api/z')\n"
    "def c():\n    pass\n")}
_ROUTES = [{"file": "r.py", "path": "/api/x/{quote_no}", "handler": "a", "scope": "row_access"},
           {"file": "r.py", "path": "/api/y", "handler": "b", "scope": "module"}]


def test_positive_control_scanner_and_rules():
    assert set(scan(_SRC)) == {("r.py", "/api/x/{quote_no}", "a"), ("r.py", "/api/y", "b")}   # /api/z 不帶 quote_no
    assert problems(scan(_SRC), _ROUTES) == []


def test_reverse_controls_each_drift_is_reported():
    extra = dict(_SRC, n="@router.get('/api/n/{quote_no}')\ndef n(quote_no):\n    pass\n")
    assert problems(scan(extra), _ROUTES) == ["沒有歸類的讀取路徑：n /api/n/{quote_no}（n）"]
    ghost = _ROUTES + [{"file": "r.py", "path": "/api/gone", "handler": "g", "scope": "module"}]
    assert problems(scan(_SRC), ghost) == ["清單有、程式碼沒有：r.py /api/gone（g）"]
    fake = [dict(_ROUTES[0]), dict(_ROUTES[1], scope="row_access")]
    assert problems(scan(_SRC), fake) == ["標 row_access 卻沒有呼叫逐案守門：r.py /api/y（b）"]
    bad = [dict(_ROUTES[0]), dict(_ROUTES[1], scope="public")]
    assert problems(scan(_SRC), bad) == ["不認得的類別 'public'：r.py /api/y"]


def installed_routes(routes, installed=source_tree.module_installed):
    """清單上屬於 `modules/<key>/` 而那個模組不在（選配、反向控制 PLAYBOOK §B-11）的路徑不比對；
    模組在就照比，不在 modules/ 底下的一律照比（主持裁示 2026-09-26，同 X-2 登記表的規則）。"""
    return [r for r in routes if installed(r["file"])]


def _scope_routes():
    return installed_routes(json.loads(SCOPE.read_text(encoding="utf-8"))["routes"])


def test_reverse_controls_absent_module_routes_are_exempt_present_ones_still_compared():
    mods = source_tree.module_dirs()
    assert mods, "沒有任何已安裝的模組 ⇒『模組在』那一半無對象"
    here = "modules/%s/api.py" % mods[0].name
    routes = [{"file": "modules/zz_absent/api/x.py", "path": "/api/zz/{quote_no}", "handler": "zz", "scope": "module"},
              {"file": here, "path": "/api/here/{quote_no}", "handler": "h", "scope": "module"},
              {"file": "routers/zz_gone.py", "path": "/api/old/{quote_no}", "handler": "o", "scope": "module"}]
    kept = installed_routes(routes)
    assert [r["handler"] for r in kept] == ["h", "o"]
    # 模組在、但程式碼沒有 ⇒ 照樣報；不在 modules/ 底下的 ⇒ 照樣報；模組不在的 ⇒ 不報
    assert problems([], kept) == ["清單有、程式碼沒有：%s /api/here/{quote_no}（h）" % here,
                                  "清單有、程式碼沒有：routers/zz_gone.py /api/old/{quote_no}（o）"]


def test_real_scan_sees_the_case_read():
    """真實掃描的正對照不綁特定 L2：取清單上第一個「提供者在安裝包裡」的路徑，掃描必須看得到它。"""
    routes = _scope_routes()
    if not routes:
        pytest.skip("安裝包裡沒有任何讀案件的路徑（例：只有核心）⇒ 無對象")
    r = routes[0]
    assert (r["file"], r["path"], r["handler"]) in _real(), r


def test_every_case_read_is_classified():
    routes = _scope_routes()
    bad = problems(_real(), routes)
    assert not bad, "docs/platform/case_read_scope.json 與程式碼不一致（MODULE-GUIDE §1.1）：\n  " + "\n  ".join(bad)
