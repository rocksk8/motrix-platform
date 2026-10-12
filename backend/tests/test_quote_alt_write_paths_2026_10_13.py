# -*- coding: utf-8 -*-
"""M3 T9：寫入路徑靜態守門。任何新增的 `UPDATE quotations` 字面或 `save_quotation_json(` 呼叫者（函式級）不在
tests/data/quote_write_paths.json 清單 ⇒ 紅：請先判斷它會不會動『已回簽擇一單』的鎖定本文（品項／金額／擇一鍵／備註），
會 ⇒ 要加守門（alt_sign.guard_update／guard_move_out_of_sent 或同等），不會 ⇒ 登記為 not-body 並寫明理由。"""
import ast
import json
import os
import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parents[1]
LIST = json.loads((pathlib.Path(__file__).parent / "data" / "quote_write_paths.json").read_text(encoding="utf-8"))["paths"]
_SQL = re.compile(r"UPDATE\s+quotations\b", re.I)


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
                       ("_append_items_to_quotation", "_ALT_SIGN.applies"), ("toggle_quotation_signed", "_toggle_alt_signed")):
        i = src.index("def %s(" % fn)
        j = src.find("\ndef ", i + 10)
        assert needle in src[i:j if j > 0 else None], "%s 沒有呼叫 %s" % (fn, needle)
    for k, v in LIST.items():
        if v["class"] == "guarded":
            assert v["note"], k


def test_scanner_positive_control():
    """掃描器本身要抓得到已知的寫入點（掃不到任何東西時『兩邊都空＝相等』會是假綠）。"""
    found = scan()
    assert "modules/case/api/quotations.py::update_quotation::sql" in found
    assert "modules/case/api/quotations.py::update_deal_tag::save" in found
    tree = ast.parse("def boom(c):\n    c.execute('UPDATE quotations SET x=1')\n    save_quotation_json(c, 'Q', {})\n")
    probe = {}
    _walk(tree, "probe.py", probe)
    assert probe == {"probe.py::boom::sql": 1, "probe.py::boom::save": 1}
