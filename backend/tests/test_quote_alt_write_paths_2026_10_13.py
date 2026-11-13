# -*- coding: utf-8 -*-
"""M3 T9：寫入路徑靜態守門。任何新增的 `UPDATE quotations` 字面或 `save_quotation_json(` 呼叫者（函式級）不在
tests/data/quote_write_paths.json 清單 ⇒ 紅：請先判斷它會不會動『已回簽擇一單』的鎖定本文（品項／金額／擇一鍵／備註），
會 ⇒ 要加守門（alt_sign.guard_update／guard_move_out_of_sent 或同等），不會 ⇒ 登記為 not-body 並寫明理由。

T83（2026-11-13）：附件清單改經 L1 `helpers.uploads.append_json_list／remove_json_item` 寫回，呼叫端不再出現 `UPDATE quotations` 字面。
掃描器因此也認這兩支 helper 的呼叫，**表名是字面 "quotations"** 的算一處寫入，key＝`<檔>::<函式>::helper:<欄>[<extra_set 的欄>]`；
表名不是字面常數（無法判斷會不會是 quotations）也算（`helper:<dynamic-table>`）。允許經 helper 寫的欄位只有 `signed_files_json`（extra_set 只准 `updated_at`）——
有人改成寫別的欄位（例如 data_json）⇒ key 變了＝清單對不上，而且 `test_helper_writes_to_quotations_only_touch_signed_files` 獨立判斷、不能靠補清單過關。"""
import ast
import json
import os
import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parents[1]
LIST = json.loads((pathlib.Path(__file__).parent / "data" / "quote_write_paths.json").read_text(encoding="utf-8"))["paths"]
_SQL = re.compile(r"UPDATE\s+quotations\b", re.I)
#: 經 L1 helper 寫「表.欄」的函式（簽章：helper(conn, table, col, where_col, key, …, extra_set=None)）
#: ⚠️ 限制（審查 hichan-12 Q3）：以呼叫名稱比對——`import … as 別名` 的呼叫認不出來；只檢查 table 實參是字面常數（col／extra_set 不是字面 ⇒ 另判為違規）。
#:    要替 helper 取別名請先來改這份掃描器。
_HELPERS = ("append_json_list", "remove_json_item")
#: 經 helper 寫 quotations 時，唯一允許的欄位與 extra_set 欄位
_HELPER_OK_COLS = {"signed_files_json"}
_HELPER_OK_EXTRA = {"updated_at"}


def scan(root=BACKEND):
    found = {}
    for d, _, fs in os.walk(root):
        rel_d = os.path.relpath(d, root).replace(os.sep, "/")
        if any(p in rel_d.split("/") for p in ("__pycache__", "tests", "tools", "migrations", "migrations_frozen", "node_modules", ".git")):
            continue
        for f in fs:
            if not f.endswith(".py"):
                continue
            path = os.path.join(d, f)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            try:
                tree = ast.parse(open(path, encoding="utf-8").read())
            except (SyntaxError, UnicodeDecodeError):
                continue
            _walk(tree, rel, found)
    return found


def _helper_key(call, rel, top):
    """append_json_list／remove_json_item 的呼叫 ⇒ 寫 quotations（或表名看不出來）才回 key，否則 None。"""
    kw = {k.arg: k.value for k in call.keywords if k.arg}
    table = call.args[1] if len(call.args) > 1 else kw.get("table")
    col = call.args[2] if len(call.args) > 2 else kw.get("col")
    if not (isinstance(table, ast.Constant) and isinstance(table.value, str)):
        return "%s::%s::helper:<dynamic-table>" % (rel, top or "<module>")        # 看不出是哪張表 ⇒ 不放行
    if table.value != "quotations":
        return None
    col_s = col.value if isinstance(col, ast.Constant) and isinstance(col.value, str) else "<dynamic-col>"
    extra = kw.get("extra_set")
    if extra is None:
        extra_s = ""
    elif isinstance(extra, ast.Dict) and all(isinstance(x, ast.Constant) and isinstance(x.value, str) for x in extra.keys):
        extra_s = ",".join(sorted(x.value for x in extra.keys))
    else:
        extra_s = "<dynamic-extra>"
    return "%s::%s::helper:%s[%s]" % (rel, top or "<module>", col_s, extra_s)


def helper_violations(found):
    """經 helper 寫 quotations 的 key 之中，欄位或 extra_set 超出允許範圍的（不看清單，獨立判斷）。"""
    bad = []
    for k in found:
        if "::helper:" not in k:
            continue
        spec = k.split("::helper:", 1)[1]
        if spec == "<dynamic-table>":
            bad.append(k)
            continue
        col, _, rest = spec.partition("[")
        extra = {x for x in rest.rstrip("]").split(",") if x}
        if col not in _HELPER_OK_COLS or not extra <= _HELPER_OK_EXTRA:
            bad.append(k)
    return sorted(bad)


def _walk(tree, rel, found):
    def visit(node, top):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and top is None:
            top = node.name
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and _SQL.search(node.value):
            k = "%s::%s::sql" % (rel, top or "<module>")
            found[k] = found.get(k, 0) + 1
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            if name == "save_quotation_json":
                k = "%s::%s::save" % (rel, top or "<module>")
                found[k] = found.get(k, 0) + 1
            if name in _HELPERS:
                k = _helper_key(node, rel, top)
                if k:
                    found[k] = found.get(k, 0) + 1
        for c in ast.iter_child_nodes(node):
            visit(c, top)
    visit(tree, None)


def _expected():
    return {k: v["count"] for k, v in LIST.items()}


def _db_migrations_excluded(found):
    return {k: v for k, v in found.items() if not (k.startswith("db.py::_m") and re.match(r"db\.py::_m\d+", k))}


def test_every_quotation_writer_is_listed_and_classified():
    found = _db_migrations_excluded(scan())
    new = sorted(set(found) - set(LIST))
    gone = sorted(set(LIST) - set(found))
    changed = sorted(k for k in set(found) & set(LIST) if found[k] != LIST[k]["count"])
    assert not new, "新增了寫 quotations 的函式（先判斷會不會動已回簽擇一單的鎖定本文，再登記到 tests/data/quote_write_paths.json）：%s" % new
    assert not gone, "清單裡的函式已不存在（請同步清單）：%s" % gone
    assert not changed, "寫入次數變了（新增了一處寫入？）：%s" % changed


def test_guarded_writers_actually_call_their_guard():
    src = (BACKEND / "modules" / "case" / "api" / "quotations.py").read_text(encoding="utf-8")
    for fn, needle in (("update_quotation", "_ALT_SIGN.guard_update"), ("update_status", "_ALT_SIGN.guard_move_out_of_sent"),
                       ("recall_quotation", "_ALT_SIGN.guard_move_out_of_sent"), ("reject_quotation", "_ALT_SIGN.guard_move_out_of_sent"),
                       ("_append_items_to_quotation", "_ALT_SIGN.applies"), ("toggle_quotation_signed", "_toggle_alt_signed"),
                       ("review_edit_quotation", 'row["is_signed"]')):
        i = src.index("def %s(" % fn)
        j = src.find("\ndef ", i + 10)
        assert needle in src[i:j if j > 0 else None], "%s 沒有呼叫 %s" % (fn, needle)
    for k, v in LIST.items():
        assert v["note"].strip(), "%s 沒有說明（每一筆都要一句話寫明為什麼守門或為什麼不碰鎖定本文）" % k
        assert v["class"] in ("guarded", "not-body"), k


def test_scanner_positive_control():
    """掃描器本身要抓得到已知的寫入點（掃不到任何東西時『兩邊都空＝相等』會是假綠）。"""
    found = scan()
    assert "modules/case/api/quotations.py::update_quotation::sql" in found
    assert "modules/case/api/quotations.py::update_deal_tag::save" in found
    tree = ast.parse("def boom(c):\n    c.execute('UPDATE quotations SET x=1')\n    save_quotation_json(c, 'Q', {})\n")
    probe = {}
    _walk(tree, "probe.py", probe)
    assert probe == {"probe.py::boom::sql": 1, "probe.py::boom::save": 1}


def test_helper_writes_to_quotations_only_touch_signed_files():
    """經 L1 helper 寫 quotations（附件清單）只准動 signed_files_json（extra_set 只准 updated_at）；超出就紅，不能靠補清單過關。"""
    found = _db_migrations_excluded(scan())
    assert any("::helper:signed_files_json[updated_at]" in k for k in found), "掃描器沒有抓到已知的經 helper 寫入點（假綠）"
    assert helper_violations(found) == []


def test_scanner_sees_helper_writes_and_flags_other_columns():
    """正對照＋反例：合成原始碼——寫 signed_files_json 的被登記為允許；改寫 data_json／extra_set 夾帶 data_json／表名動態 ⇒ 判為違規；其他表不算。"""
    def run(src):
        out = {}
        _walk(ast.parse(src), "probe.py", out)
        return out

    ok = run("def f(c):\n    append_json_list(c, 'quotations', 'signed_files_json', 'quote_no', 'Q', [], extra_set={'updated_at': 1})\n")
    assert ok == {"probe.py::f::helper:signed_files_json[updated_at]": 1} and helper_violations(ok) == []
    rm = run("def g(c):\n    remove_json_item(c, 'quotations', 'signed_files_json', 'quote_no', 'Q', 'fid')\n")
    assert rm == {"probe.py::g::helper:signed_files_json[]": 1} and helper_violations(rm) == []
    body = run("def h(c):\n    append_json_list(c, 'quotations', 'data_json', 'quote_no', 'Q', [])\n")
    assert helper_violations(body) == ["probe.py::h::helper:data_json[]"]
    extra = run("def i(c):\n    append_json_list(c, 'quotations', 'signed_files_json', 'quote_no', 'Q', [], extra_set={'data_json': 1})\n")
    assert helper_violations(extra) == ["probe.py::i::helper:signed_files_json[data_json]"]
    dyn = run("def j(c, t):\n    append_json_list(c, t, 'signed_files_json', 'quote_no', 'Q', [])\n")
    assert helper_violations(dyn) == ["probe.py::j::helper:<dynamic-table>"]
    kwcall = run("def k(c):\n    remove_json_item(c, table='quotations', col='data_json', where_col='quote_no', key='Q', file_id='x')\n")
    assert helper_violations(kwcall) == ["probe.py::k::helper:data_json[]"]
    other = run("def m(c):\n    append_json_list(c, 'shipping_notes', 'signed_files_json', 'note_no', 'N', [])\n")
    assert other == {}
