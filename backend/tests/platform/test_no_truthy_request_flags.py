# -*- coding: utf-8 -*-
"""請求本文的旗標不可用真值判斷（第 49 班 W1c-P2；第 50 班 P2b 放寬）。

`bool(body.get("flag"))`、`1 if body.get("flag") else 0`、`if body.get("cascade")`、`x and body.get("cascade")` 都會把 JSON 字串 `"false"`／`"0"`／`""` 當成 true
（關卡被繞過：確認旗標、`accept_warnings`、`cascade` 替簽核人自動簽完剩下的層、緊急開關…）。請求本文的旗標一律用 `helpers.validation.body_flag`／`strict_bool`（非布林 ⇒ 422）。

範圍：①`routers/*.py`、各模組 `api.py`／`api/` 底下、`accounting/ledger/requests.py`——請求本文慣用名 body／b／payload／params／p／req／request_body；
②**全部非測試產品檔**（`modules/**`、`helpers/`、`routers/`，含 api 以外：`subcontract/remit.py` 曾漏網）——只認 body／payload／request_body／req。
DB 列（d／row）轉布林是輸出正規化，不在此限。偵測形狀：`bool(請求旗標)`、`1 if 請求旗標 else 0`，以及**真值使用**
（`if`／`and`／`or`／`not`／`assert`／三元式的條件直接就是 `body.get("旗標鍵")`）；旗標鍵以名稱判斷（cascade／enabled／active／is_*／has*／confirm*／force／reopen／
regenerate／accept_*／internal／done／received／*manual／skip*／dry_run／nondeductible／poe…），所以 `if body.get("comment")` 這類文字欄位的存在檢查不會誤殺。
已知限制：先 `x = body.get("hasFee")` 再 `if x:` 的間接形狀掃不到（remit.py 因此直接改成 body_flag）。
不用 regex：用 ast，註解／字串裡的字樣騙不了它；另附正對照（合成程式碼必須被抓到）與反對照（合法寫法不誤殺）。
"""
import ast
import glob
import os
import re

BE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REQ_NAMES = {"body", "b", "payload", "params", "req", "request_body"}      # p 太常是 DB 列／內部字典（dashboard、settlement_actuals）；只在 EXTRA 的 requests.py 才認
WIDE_NAMES = {"body", "payload", "request_body", "req"}
EXTRA = ["modules/accounting/ledger/requests.py"]
FLAG_KEY = re.compile(r"(?i)^(cascade|enabled?|active|is_\w+|has_?\w*|hasfee|confirm\w*|force|reopen|regenerate|accept_\w+|internal|done|received|\w*manual|skip\w*|dry_?run|nondeductible|poe|acked|acknowledged)$")


def _names(node):
    return {x.id for x in ast.walk(node) if isinstance(x, ast.Name)}


def _reads_request_flag(node, names=None) -> bool:
    """運算式裡有 `<請求本文變數>.get(...)` 或 `<請求本文變數>[...]`（任何鍵；給 bool()／1-0 三元式用）。"""
    for x in ast.walk(node):
        if isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) and x.func.attr == "get" and (_names(x.func.value) & (names or REQ_NAMES)):
            return True
        if isinstance(x, ast.Subscript) and (_names(x.value) & (names or REQ_NAMES)):
            return True
    return False


def _flag_read(node, names) -> bool:
    """運算式本身就是 `<請求本文變數>.get("旗標鍵"…)`／`(<變數> or {}).get(…)`／`<變數>["旗標鍵"]`。"""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args \
            and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str) and FLAG_KEY.match(node.args[0].value):
        return bool(_names(node.func.value) & names)
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str) and FLAG_KEY.match(node.slice.value):
        return bool(_names(node.value) & names)
    return False


def _truthy_uses(tree, names, rel):
    out = []
    for n in ast.walk(tree):
        tests = []
        if isinstance(n, (ast.If, ast.IfExp, ast.While, ast.Assert)):
            tests.append(n.test)
        elif isinstance(n, ast.BoolOp):
            tests.extend(n.values)
        elif isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not):
            tests.append(n.operand)
        for t in tests:
            if _flag_read(t, names):
                out.append("%s:%d  真值使用 %s" % (rel, getattr(t, "lineno", getattr(n, "lineno", 0)), ast.unparse(t)[:90]))
    return out


def violations(source: str, rel: str = "<src>", wide: bool = False, extra_names=()) -> list:
    out = []
    tree = ast.parse(source)
    names = (WIDE_NAMES if wide else REQ_NAMES) | set(extra_names)
    out += _truthy_uses(tree, names, rel)
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "bool" and n.args and _reads_request_flag(n.args[0], names):
            out.append("%s:%d  %s" % (rel, n.lineno, ast.unparse(n)[:100]))
        # 1 if body.get("x") else 0 ／ True if body.get("x") else False
        if isinstance(n, ast.IfExp) and _reads_request_flag(n.test, names) and isinstance(n.test, (ast.Call, ast.Subscript)) \
                and isinstance(n.body, ast.Constant) and isinstance(n.orelse, ast.Constant) \
                and {n.body.value, n.orelse.value} in ({1, 0}, {True, False}):
            out.append("%s:%d  %s" % (rel, n.lineno, ast.unparse(n)[:100]))
    return out


def _files():
    fs = glob.glob(os.path.join(BE, "routers", "*.py")) + glob.glob(os.path.join(BE, "modules", "*", "api.py")) \
        + glob.glob(os.path.join(BE, "modules", "*", "api", "*.py")) + [os.path.join(BE, e) for e in EXTRA]
    return sorted(f for f in fs if os.path.isfile(f))


def _wide_files():
    """全部非測試產品檔（modules／helpers／routers 底下所有層）。"""
    out = []
    for base in ("modules", "helpers", "routers"):
        for d, dirs, files in os.walk(os.path.join(BE, base)):
            dirs[:] = [x for x in dirs if x not in ("tests", "__pycache__", "migrations", "node_modules")]
            out += [os.path.join(d, f) for f in files if f.endswith(".py")]
    return sorted(out)


def _rel(f):
    return os.path.relpath(f, BE).replace("\\", "/")


def test_no_request_flag_is_read_with_truthiness():
    bad = []
    for f in _files():
        bad += violations(open(f, encoding="utf-8").read(), _rel(f), extra_names=("p",) if _rel(f) in EXTRA else ())
    for f in _wide_files():
        bad += violations(open(f, encoding="utf-8").read(), _rel(f), wide=True)
    bad = sorted(set(bad))
    assert not bad, "請求本文旗標不可用 bool()／真值判斷（字串 false 會變 true）；改用 helpers.validation.body_flag：" + chr(10) + "  " + (chr(10) + "  ").join(bad)


def test_scanner_positive_control_catches_the_known_bad_shapes():
    bool_shapes = [
        'x = bool(body.get("a"))', 'x = bool((body or {}).get("a"))', 'x = bool(b["a"])', 'x = bool(payload.get("a", False))',
        'x = 1 if body.get("a") else 0', 'x = True if (body or {}).get("a") else False', 'x = bool(p.get("accept_warnings"))',
    ]
    for s in bool_shapes:
        assert violations(s, extra_names=("p",)), "掃描器漏抓：" + s
    truthy_shapes = [
        'x = 1 if (tier_done and (body or {}).get("cascade")) else 0',      # 第50班：八個 approver 端點的形狀
        'if body.get("hasFee"):\n    pass', 'x = cond and body.get("cascade")', 'x = not body.get("enabled")', 'assert body["confirm"]',
    ]
    for s in truthy_shapes:
        assert violations(s) and violations(s, wide=True), "真值使用漏抓：" + s


def test_scanner_does_not_flag_legitimate_shapes():
    ok_shapes = [
        'x = body_flag(body, "a")', 'x = bool(row.get("a"))', 'x = bool(d.get("is_paid"))', 'x = 1 if row["a"] else 0',
        'x = body.get("comment") or ""', 'x = bool(len(body))', '# bool(body.get("a"))\nx = 1', 'x = "bool(body.get(1))"',
        'if body.get("comment"):\n    pass', 'x = body.get("note") or "x"', 'if row.get("cascade"):\n    pass', 'if body_flag(body, "cascade"):\n    pass',
        'if body.get("name") and body.get("customer"):\n    pass',
    ]
    for s in ok_shapes:
        assert not violations(s) and not violations(s, wide=True), "誤殺：" + s
