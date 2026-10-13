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
REALTIME_ALLOW = {}


def realtime_hits(sources: dict) -> list:
    return sorted(rel for rel, s in sources.items() if _REALTIME.search(s) and rel not in REALTIME_ALLOW)


def test_no_websocket_or_sse_channel_without_a_strip_entry():
    assert realtime_hits(SRC) == [], "出現即時通道：HTTP 中介層不涵蓋 WebSocket／SSE，請先補剝除並登記允許清單"
    assert realtime_hits({"routers/x.py": "@router.websocket('/ws')\nasync def w(ws): ...\n"}) == ["routers/x.py"]            # 正對照
    assert realtime_hits({"routers/x.py": "return StreamingResponse(g(), media_type='text/event-stream')\n"}) == ["routers/x.py"]


# ── ② 動態 SET 組字串 ─────────────────────────────────────────────────────────────────
_SET_BUILDER = re.compile(r"UPDATE\s+\w+\s+SET\s*\{|SET\s+\"\s*\+\s*\",\s*\"\.join|\"UPDATE\s+\w+\s+SET\s+\"\s*\+|f\"UPDATE\s+\w+\s+SET\s+\{|\.join\(\s*[\"']%s\s*=\s*\?[\"']\s*%", re.I)


def set_builders(sources: dict) -> dict:
    out = {}
    for rel, s in sources.items():
        n = len(_SET_BUILDER.findall(s))
        if n:
            out[rel] = n
    return out


#: 目前已知的動態 SET 組字串（每個都已讀碼確認欄名來自固定白名單或 Pydantic 欄位）。只准縮小、不准新增。
SET_BUILDER_BASELINE = {
    "modules/accounting/api/vouchers.py": 1,
    "modules/case/api/case_extra_expenses.py": 2,
    "modules/case/api/quotations.py": 2,
    "modules/subcontract/api/contractors.py": 1,
    "modules/supply/api/suppliers.py": 1,
    "routers/auth.py": 1,
    "routers/system.py": 1,
}


def test_dynamic_update_builders_only_shrink():
    now = set_builders(SRC)
    grew = {k: (SET_BUILDER_BASELINE.get(k, 0), v) for k, v in now.items() if v > SET_BUILDER_BASELINE.get(k, 0)}
    assert grew == {}, "新增動態 UPDATE…SET 組字串（欄名必須白名單，且不可接受 owner_unit_id／unit_id／legal_entity_id）：%s" % grew
    assert set_builders({"a.py": 'conn.execute(f"UPDATE t SET {sets} WHERE id=?")\n'}) == {"a.py": 1}                    # 正對照


def test_internal_columns_are_never_whitelisted_for_writes():
    """任何產品碼不得在欄位白名單／allowed 集合裡出現內部欄位名（輸入側 mass-assignment）；基礎設施檔例外。"""
    ok_files = {"core/internal_cols.py", "core/upgrade.py"}
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
