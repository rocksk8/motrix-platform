# -*- coding: utf-8 -*-
"""U0a 洩漏防線的靜態守門（輸出出口與輸入出口）。

①即時通道（WebSocket／SSE）：目前產品碼沒有；一旦出現，HTTP 中介層管不到，必須先有剝除登記。
②動態 `UPDATE … SET` 組字串（輸入側 mass-assignment）：欄名必須來自白名單；基線登記現有的組字串處，只准縮小。
③整列序列化進通知／稽核／信件（輸出側）：`dict(row)` 或 `SELECT *` 直接餵進 json.dumps／通知／稽核者，基線只准縮小。
每個掃描器都有正對照（餵一段違規原始碼必須被抓到），避免掃描器本身假綠。
"""
import ast
import json
import re
from pathlib import Path

from core import source_tree

SRC = {source_tree.rel(p): p.read_text(encoding="utf-8") for p in source_tree.product_files()}

# ── ① 即時通道 ────────────────────────────────────────────────────────────────────────
_REALTIME = re.compile(r"WebSocket|EventSource|text/event-stream|\.websocket\(|@websocket|sse_starlette", re.I)
#: 允許清單：{路徑: 理由}。新增前必須先在 core/internal_cols 補上該通道的剝除並更新這裡。
REALTIME_ALLOW = {
    "core/loader.py": "docstring 提到 WebSocket（掛載說明），不是通道",
}


def realtime_hits(sources: dict) -> list:
    return sorted(rel for rel, s in sources.items() if _REALTIME.search(s) and rel not in REALTIME_ALLOW)


def test_no_websocket_or_sse_channel_without_a_strip_entry():
    assert realtime_hits(SRC) == [], "出現即時通道：HTTP 中介層不涵蓋 WebSocket／SSE，請先補剝除並登記允許清單"
    assert realtime_hits({"routers/x.py": "@router.websocket('/ws')\nasync def w(ws): ...\n"}) == ["routers/x.py"]            # 正對照
    assert realtime_hits({"routers/x.py": "return StreamingResponse(g(), media_type='text/event-stream')\n"}) == ["routers/x.py"]


# ── ② 動態 SET 組字串（AST）──────────────────────────────────────────────────────────
_UPDATE_SET = re.compile(r"UPDATE\s+\w+\s+SET", re.I)


def _flatten(node):
    """字串組裝運算式 → (常數文字, 是否動態)；不是字串組裝回 None。支援 f-string、`+` 串接、`%` 格式化、`.format()`。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value, False
    if isinstance(node, ast.JoinedStr):
        txt, dyn = "", False
        for v in node.values:
            if isinstance(v, ast.Constant):
                txt += str(v.value)
            else:
                dyn = True
        return txt, dyn
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = _flatten(node.left), _flatten(node.right)
        if a is None and b is None:
            return None
        return (a[0] if a else "") + (b[0] if b else ""), True if (a is None or b is None) else (a[1] or b[1])
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        a = _flatten(node.left)
        return (a[0], True) if a else None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        a = _flatten(node.func.value)
        return (a[0], True) if a else None
    return None


def set_builders(sources: dict) -> dict:
    """每個檔案裡『動態組出的 UPDATE <表> SET …』字串數（最大運算式算一個；純常數不算）。"""
    out = {}
    for rel, s in sources.items():
        try:
            tree = ast.parse(s)
        except SyntaxError:
            continue
        n = 0

        def visit(node):
            nonlocal n
            f = _flatten(node) if isinstance(node, (ast.JoinedStr, ast.BinOp, ast.Call)) else None
            if f and f[1] and _UPDATE_SET.search(f[0]):
                n += 1
                return
            for c in ast.iter_child_nodes(node):
                visit(c)
        visit(tree)
        if n:
            out[rel] = n
    return out


#: 目前已知的動態 SET 組字串（欄名來自固定白名單或程式內常數；0d／1c 逐處讀碼）。只准縮小、不准新增。
SET_BUILDER_BASELINE = {
    "db.py": 2,
    "helpers/audit.py": 1,
    "helpers/custom_builder_support.py": 1,
    "modules/accounting/api/ledger_reports.py": 1,
    "modules/accounting/api/ledger_settings.py": 1,
    "modules/accounting/api/vouchers.py": 3,
    "modules/case/api/case_extra_expenses.py": 1,
    "modules/case/api/quotations.py": 3,
    "modules/case/material_approval.py": 1,
    "modules/case/material_change.py": 1,
    "modules/case/material_payment.py": 1,
    "modules/case/payables.py": 1,
    "modules/payroll/api/payslip_approval.py": 1,
    "modules/payroll/bonus_vouchers.py": 1,
    "modules/subcontract/api/contractor_vouchers.py": 1,
    "modules/subcontract/api/contractors.py": 1,
    "modules/subcontract/api/dispatch_approval.py": 7,
    "modules/subcontract/dispatch_flow.py": 1,
    "modules/subcontract/remit.py": 1,
    "modules/supply/api/suppliers.py": 1,
    "routers/auth.py": 1,
    "routers/system.py": 1,
}


def test_dynamic_update_builders_only_shrink():
    now = set_builders(SRC)
    grew = {k: (SET_BUILDER_BASELINE.get(k, 0), v) for k, v in now.items() if v > SET_BUILDER_BASELINE.get(k, 0)}
    assert grew == {}, "新增動態 UPDATE…SET 組字串（欄名必須白名單，且不可接受 owner_unit_id／unit_id／legal_entity_id）：%s" % grew
    for src in ('conn.execute(f"UPDATE t SET {sets} WHERE id=?")\n',
                'sql = "UPDATE t SET " + ", ".join(f"{k}=?" for k in u) + " WHERE id=?"\n',
                'conn.execute("UPDATE t SET %s WHERE id=?" % ", ".join(sets), a)\n',
                'q = "UPDATE t SET {} WHERE id=?".format(sets)\n',
                'q = ("UPDATE t SET a=?" + "".join(", " + s for s in extra) + " WHERE id=?")\n'):
        assert set_builders({"a.py": src}) == {"a.py": 1}, src                                                         # 正對照：五種組字串寫法
    assert set_builders({"a.py": 'conn.execute("UPDATE t SET a=? WHERE id=?", (1, 2))\n'}) == {}                      # 純常數不算
    assert set_builders({"a.py": 'conn.execute("INSERT INTO t VALUES (1) ON CONFLICT(a) DO UPDATE SET b=excluded.b")\n'}) == {}


#: 唯一一份『允許在字串裡寫出內部欄位名』的檔案清單（遷移／健檢雜湊／剝除／匯出基礎設施）。c7 的 consistency 測試與本檔共用這份，不另立清單。
QUOTED_NAMES_ALLOW = frozenset({
    "core/internal_cols.py", "core/upgrade.py", "core/migrations.py", "core/spine.py",
    "archive.py", "helpers/xlsx_out.py", "modules/permmatrix/migrations/0002_scope_json.py",
})


def test_internal_columns_are_never_whitelisted_for_writes():
    """任何產品碼不得在欄位白名單／allowed 集合裡出現內部欄位名（輸入側 mass-assignment）；基礎設施檔例外。"""
    ok_files = QUOTED_NAMES_ALLOW
    bad = [rel for rel, s in SRC.items() if rel not in ok_files and re.search(r"[\"'](owner_unit_id|unit_id|legal_entity_id)[\"']", s)]
    assert bad == [], "內部欄位名出現在產品碼字串裡（寫入白名單？）：%s" % bad
    assert re.search(r"[\"']owner_unit_id[\"']", 'ALLOWED = {"owner_unit_id", "name"}')                                  # 正對照


# ── ③ 整列序列化進通知／稽核／信件 ────────────────────────────────────────────────────
def row_dump_sinks(sources: dict) -> dict:
    """AST：`json.dumps(dict(x))`／`json.dumps([dict(r) for r in …])` 形狀（整列直接序列化）。"""
    out = {}
    for rel, s in sources.items():
        try:
            tree = ast.parse(s)
        except SyntaxError:
            continue
        n = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "dumps" and node.args:
                a = node.args[0]
                if isinstance(a, ast.Call) and getattr(a.func, "id", None) == "dict":
                    n += 1
                elif isinstance(a, ast.ListComp) and isinstance(a.elt, ast.Call) and getattr(a.elt.func, "id", None) == "dict":
                    n += 1
        if n:
            out[rel] = n
    return out


def _baseline():
    p = Path(__file__).with_name("u0a_row_dump_baseline.json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def test_whole_row_json_dumps_only_shrink():
    base = _baseline()
    now = row_dump_sinks(SRC)
    assert base is not None, "缺 u0a_row_dump_baseline.json：以 `python -I -c` 呼叫 row_dump_sinks(SRC) 產生起始基線（機器空檔時）"
    grew = {k: (base.get(k, 0), v) for k, v in now.items() if v > base.get(k, 0)}
    assert grew == {}, "新增『整列直接 json.dumps』：單位鍵欄位會被序列化進通知／稽核／快照（請明列欄位或用 strip_row）：%s" % grew
    assert row_dump_sinks({"a.py": "import json\nx = json.dumps(dict(row))\n"}) == {"a.py": 1}                         # 正對照
    assert row_dump_sinks({"a.py": "import json\nx = json.dumps([dict(r) for r in rows])\n"}) == {"a.py": 1}
    assert row_dump_sinks({"a.py": "import json\nx = json.dumps({'a': row['a']})\n"}) == {}


# ── 中介層必須是最後一個 add_middleware（最外層）────────────────────────────────────────
def test_internal_cols_middleware_is_the_last_registered_middleware():
    src = SRC["main.py"]
    tree = ast.parse(src)
    regs = []                                           # (行號, 種類, 名稱)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "add_middleware" and node.args:
            regs.append((node.lineno, "add", getattr(node.args[0], "id", "?")))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in node.decorator_list:
                if isinstance(d, ast.Call) and getattr(d.func, "attr", None) == "middleware":
                    regs.append((d.lineno, "deco", node.name))
    regs.sort()
    assert regs and regs[-1][1:] == ("add", "InternalColsMiddleware"), "InternalColsMiddleware 必須是最後註冊的中介層（最外層）：%s" % regs[-3:]
    fake = "app.add_middleware(InternalColsMiddleware)\n@app.middleware('http')\nasync def later(r, n): ...\n"       # 正對照：後面再加任何中介層就紅
    t2 = ast.parse(fake)
    r2 = sorted((n.lineno, "add") for n in ast.walk(t2) if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "add_middleware") +         sorted((d.lineno, "deco") for n in ast.walk(t2) if isinstance(n, ast.AsyncFunctionDef) for d in n.decorator_list)
    assert sorted(r2)[-1][1] == "deco"


# ── 疑似有副作用的 GET 路由必須分類（記錄器拒絕清單）────────────────────────────────────
_SIDE_EFFECT_NAME = re.compile(r"send|notify|sync|geocode|lookup|mail", re.I)
#: 路徑樣板 → "deny"（記錄器不呼叫：會對外連線或寄信）｜"read"（純讀取，記錄器可以呼叫）。新增含上述字樣的 GET 路由時必須在這裡分類。
SIDE_EFFECT_GET_CLASSIFIED = {
    "/api/company/tax/{tax_id}": "deny",
    "/api/mail-types": "read",
    "/api/mail-types/receivable": "read",
    "/api/settings/email-notify": "read",
    "/api/settings/reminder-send-failures": "read",
}


def side_effect_gets(sources: dict) -> set:
    out = set()
    for rel, s in sources.items():
        try:
            tree = ast.parse(s)
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for d in n.decorator_list:
                    if (isinstance(d, ast.Call) and getattr(d.func, "attr", None) == "get" and d.args
                            and isinstance(d.args[0], ast.Constant) and isinstance(d.args[0].value, str)
                            and (_SIDE_EFFECT_NAME.search(d.args[0].value) or _SIDE_EFFECT_NAME.search(n.name))):
                        out.add(d.args[0].value)
    return out


def test_side_effect_looking_get_routes_are_classified_for_the_recorder():
    from tests.platform import _response_keys as RK
    new = side_effect_gets(SRC) - set(SIDE_EFFECT_GET_CLASSIFIED)
    assert new == set(), "新的疑似有副作用的 GET 路由（send／notify／sync／geocode／lookup／mail）未分類：%s——到 SIDE_EFFECT_GET_CLASSIFIED 標 deny（並讓 _response_keys.DENY 對得上）或 read" % sorted(new)
    stale = set(SIDE_EFFECT_GET_CLASSIFIED) - side_effect_gets(SRC)
    assert stale == set(), "分類表有已不存在的路由：%s" % sorted(stale)
    for path, kind in SIDE_EFFECT_GET_CLASSIFIED.items():
        assert (kind == "deny") == bool(RK.DENY.search(path)), "分類 %s 與記錄器拒絕清單不一致：%s" % (kind, path)
    # 正對照
    assert side_effect_gets({"routers/x.py": "@router.get('/api/x/send-test')\ndef f(): ...\n"}) == {"/api/x/send-test"}
    assert side_effect_gets({"routers/x.py": "@router.get('/api/x/list')\ndef list_x(): ...\n"}) == set()
