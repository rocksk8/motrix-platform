# -*- coding: utf-8 -*-
"""請求本文的旗標不可用真值判斷（第 49 班 W1c-P2）。

`bool(body.get("flag"))`、`bool((body or {}).get("flag"))`、`1 if body.get("flag") else 0` 會把 JSON 字串 `"false"`／`"0"`／`""` 當成 true
（關卡被繞過：確認旗標、`accept_warnings`、緊急開關…）。請求本文的旗標一律用 `helpers.validation.body_flag`／`strict_bool`（非布林 ⇒ 422）。

範圍：`routers/*.py`、各模組 `api.py`／`api/` 底下、以及接收請求參數的 `accounting/ledger/requests.py`；
變數名限定為請求本文慣用名（body／b／payload／params／p／req／request_body）——DB 列（d／row）轉布林是輸出正規化，不在此限。
不用 regex：用 ast，註解／字串裡的字樣騙不了它；另附正對照（合成程式碼必須被抓到）與反對照（合法寫法不誤殺）。
"""
import ast
import glob
import os

BE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REQ_NAMES = {"body", "b", "payload", "params", "p", "req", "request_body"}
EXTRA = ["modules/accounting/ledger/requests.py"]


def _names(node):
    return {x.id for x in ast.walk(node) if isinstance(x, ast.Name)}


def _reads_request_flag(node) -> bool:
    """運算式裡有 `<請求本文變數>.get(...)` 或 `<請求本文變數>[...]`。"""
    for x in ast.walk(node):
        if isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) and x.func.attr == "get" and (_names(x.func.value) & REQ_NAMES):
            return True
        if isinstance(x, ast.Subscript) and (_names(x.value) & REQ_NAMES):
            return True
    return False


def violations(source: str, rel: str = "<src>") -> list:
    out = []
    for n in ast.walk(ast.parse(source)):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "bool" and n.args and _reads_request_flag(n.args[0]):
            out.append("%s:%d  %s" % (rel, n.lineno, ast.unparse(n)[:100]))
        # 1 if body.get("x") else 0 ／ True if body.get("x") else False
        if isinstance(n, ast.IfExp) and _reads_request_flag(n.test) and isinstance(n.test, (ast.Call, ast.Subscript)) \
                and isinstance(n.body, ast.Constant) and isinstance(n.orelse, ast.Constant) \
                and {n.body.value, n.orelse.value} in ({1, 0}, {True, False}):
            out.append("%s:%d  %s" % (rel, n.lineno, ast.unparse(n)[:100]))
    return out


def _files():
    fs = glob.glob(os.path.join(BE, "routers", "*.py")) + glob.glob(os.path.join(BE, "modules", "*", "api.py")) \
        + glob.glob(os.path.join(BE, "modules", "*", "api", "*.py")) + [os.path.join(BE, e) for e in EXTRA]
    return sorted(f for f in fs if os.path.isfile(f))


def test_no_request_flag_is_read_with_truthiness():
    bad = []
    for f in _files():
        bad += violations(open(f, encoding="utf-8").read(), os.path.relpath(f, BE).replace("\\", "/"))
    assert not bad, "請求本文旗標不可用 bool()／真值三元式（字串 \"false\" 會變 true）；改用 helpers.validation.body_flag：\n  " + "\n  ".join(bad)


def test_scanner_positive_control_catches_the_known_bad_shapes():
    bad_snippets = [
        'x = bool(body.get("a"))', 'x = bool((body or {}).get("a"))', 'x = bool(b["a"])', 'x = bool(payload.get("a", False))',
        'x = 1 if body.get("a") else 0', 'x = True if (body or {}).get("a") else False', 'x = bool(p.get("accept_warnings"))',
    ]
    for s in bad_snippets:
        assert violations(s), "掃描器漏抓：" + s


def test_scanner_does_not_flag_legitimate_shapes():
    ok_snippets = [
        'x = body_flag(body, "a")', 'x = bool(row.get("a"))', 'x = bool(d.get("is_paid"))', 'x = 1 if row["a"] else 0',
        'x = body.get("comment") or ""', 'x = bool(len(body))', '# bool(body.get("a"))\nx = 1', 'x = "bool(body.get(1))"',
    ]
    for s in ok_snippets:
        assert not violations(s), "誤殺：" + s
