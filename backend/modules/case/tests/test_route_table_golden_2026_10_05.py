# -*- coding: utf-8 -*-
"""路由表守門（第 40 班起；第 52 班改為雙向嚴格相等）。

第 40 班：把 `api/quotations.py` 的精算端點純搬移到 `api/settlement_api.py` 時，整個應用的 OpenAPI 路由表
（方法＋路徑＋operationId＋參數＋驗證）必須與搬移前逐位相同；而且搬移不可以讓別的路由「先一步吃掉」精算網址（匹配順序）。

第 52 班（GOLDEN-DRIFT-T52）：原本只檢查「golden 有、現況沒有」，**新增的路由永遠不會紅**，於是第 46～50 班新增的 30 條路由
沒有人補 golden。現在 golden 是整個應用的**路由登記簿**：現況與 golden **逐筆相等**——新增、消失、內容改變都紅，
失敗訊息分三組各列前 20 筆並直接寫出重產指令。

golden 檔 `route_table_golden.json` 的格式（合併友善）：**一行一筆**、依（路徑, 方法）排序、每行是一個 JSON 陣列、檔尾有換行、LF。
兩個分支各加路由時只會在不同行新增；若同時改到相鄰行而衝突 ⇒ 兩邊的行都留著、不要手排，重跑重產指令即可。
重產：`T40_WRITE_GOLDEN=1 pytest backend/modules/case/tests/test_route_table_golden_2026_10_05.py -q`
（PowerShell：`$env:T40_WRITE_GOLDEN='1'`），檢視 `git diff` 只該有你的路由，再把 golden 和程式碼放在**同一個 commit**。"""
import json
import os
from pathlib import Path

from starlette.routing import Match

GOLDEN = Path(__file__).with_name("route_table_golden.json")
_TEST_NAME = "backend/modules/case/tests/test_route_table_golden_2026_10_05.py"
_FIELDS = ("operationId", "parameters", "requestBody", "security")      # 對應 entry[2:6]
_MAX_SHOWN = 20


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


def _sort_key(entry):
    return (entry[1], entry[0].lower())                                  # 路徑、方法（與 OpenAPI 走訪順序一致）


def _dump_line(entry):
    return json.dumps(entry, ensure_ascii=False)


def _serialize(entries):
    """golden 檔的唯一寫法：排序、一行一筆、LF、檔尾換行。"""
    return "".join(_dump_line(e) + "\n" for e in sorted(entries, key=_sort_key))


def _parse(text):
    return [json.loads(line) for line in text.split("\n") if line.strip()]


def canonical_problems(text):
    """golden 檔本身是否為規範寫法（防止手動編輯、衝突解錯、CRLF 讓下一個人的 diff 全紅）。回傳問題清單，空＝規範。"""
    problems = []
    if "\r" in text:
        problems.append("含 CR（CRLF 換行）；golden 一律 LF")
    if text and not text.endswith("\n"):
        problems.append("檔尾沒有換行")
    lines = text.replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    entries, keys = [], set()
    for i, line in enumerate(lines, 1):
        if not line.strip():
            problems.append("第 %d 行是空行" % i)
            continue
        try:
            e = json.loads(line)
        except ValueError as ex:
            problems.append("第 %d 行不是 JSON：%s" % (i, ex))
            continue
        if not (isinstance(e, list) and len(e) == 6):
            problems.append("第 %d 行不是 6 欄陣列" % i)
            continue
        if _dump_line(e) != line:
            problems.append("第 %d 行不是規範寫法（請用重產指令，不要手改）：%s %s" % (i, e[0], e[1]))
        k = (e[0], e[1])
        if k in keys:
            problems.append("第 %d 行重複：%s %s" % (i, e[0], e[1]))
        keys.add(k)
        entries.append(e)
    if [ _sort_key(e) for e in entries ] != sorted(_sort_key(e) for e in entries):
        problems.append("沒有依（路徑, 方法）排序（衝突解完後請重跑重產指令）")
    return problems


def diff_tables(golden, table):
    """以（方法, 路徑）為鍵比對：added＝現況有、golden 沒有；missing＝golden 有、現況沒有；changed＝同鍵但其餘欄位不同。"""
    g = {(e[0], e[1]): e for e in golden}
    t = {(e[0], e[1]): e for e in table}
    added = sorted(k for k in t if k not in g)
    missing = sorted(k for k in g if k not in t)
    changed = sorted(k for k in g if k in t and g[k] != t[k])
    detail = {}
    for k in changed:
        detail[k] = [name for name, a, b in zip(_FIELDS, g[k][2:], t[k][2:]) if a != b]
    return {"added": added, "missing": missing, "changed": changed, "changed_fields": detail}


def _fmt_group(title, keys, extra=None):
    if not keys:
        return ""
    shown = keys[:_MAX_SHOWN]
    lines = ["%s（%d 筆）：" % (title, len(keys))]
    for m, p in shown:
        lines.append("  %-6s %s%s" % (m, p, ("  ← 改了：" + "、".join(extra[(m, p)])) if extra else ""))
    if len(keys) > len(shown):
        lines.append("  …另有 %d 筆" % (len(keys) - len(shown)))
    return "\n".join(lines) + "\n"


def report(d):
    """失敗訊息：三組各列前 20 筆，結尾直接寫怎麼修。"""
    body = (_fmt_group("新增（現況有、golden 沒有）", d["added"])
            + _fmt_group("消失（golden 有、現況沒有）", d["missing"])
            + _fmt_group("內容改變（operationId／參數／requestBody／security）", d["changed"], d["changed_fields"]))
    tail = ("\n⇒ 這是路由表守門：golden 是整個應用的路由登記簿，現況必須與它逐筆相等。\n"
            "   新增／刪除／改動路由，要和程式碼放在**同一個 commit** 更新 golden：\n"
            "     T40_WRITE_GOLDEN=1 pytest %s -q\n"
            "   （PowerShell：$env:T40_WRITE_GOLDEN='1'；用專案 .venv312 的 python -m pytest）→ 檢視 git diff 只該有你的路由 → 把 golden 和程式碼一起 commit。\n"
            "   不是你改的路由也在清單裡 ⇒ 有人漏更新了 golden，照樣重產（那是別人漏的，不是你多了）。" % _TEST_NAME)
    return body + tail


def regen_refused_reason(env):
    """閘門／列車（`MOTRIX_TRAIN=1`）上不得重產 golden：否則設錯環境變數的一輪閘門會默默把漂移寫進 golden 然後綠燈。回傳拒絕原因或 None。"""
    if env.get("T40_WRITE_GOLDEN") == "1" and env.get("MOTRIX_TRAIN") == "1":
        return "T40_WRITE_GOLDEN=1 不可與 MOTRIX_TRAIN=1 並用（閘門／列車上不重產 golden；請在分支上用重產指令，並把 golden 和程式碼一起 commit）"
    return None


def test_openapi_route_table_matches_the_golden(client):
    table = _table(client.app)
    refused = regen_refused_reason(os.environ)
    assert refused is None, refused
    if os.environ.get("T40_WRITE_GOLDEN") == "1":
        with open(GOLDEN, "w", encoding="utf-8", newline="\n") as f:
            f.write(_serialize(table))
    golden = _parse(GOLDEN.read_text(encoding="utf-8"))
    d = diff_tables(golden, table)
    assert not (d["added"] or d["missing"] or d["changed"]), "\n" + report(d)


def test_regeneration_is_refused_on_a_gate_or_train_run():
    assert regen_refused_reason({"T40_WRITE_GOLDEN": "1", "MOTRIX_TRAIN": "1"}), "閘門上要求重產 ⇒ 必須拒絕"
    assert regen_refused_reason({"T40_WRITE_GOLDEN": "1"}) is None, "分支上正常重產不受影響"
    assert regen_refused_reason({"MOTRIX_TRAIN": "1"}) is None, "閘門上沒要求重產 ⇒ 照常比對"
    assert regen_refused_reason({"T40_WRITE_GOLDEN": "0", "MOTRIX_TRAIN": "1"}) is None
    assert "MOTRIX_TRAIN=1" in regen_refused_reason({"T40_WRITE_GOLDEN": "1", "MOTRIX_TRAIN": "1"})


def test_golden_file_is_canonical_one_entry_per_line_sorted():
    problems = canonical_problems(GOLDEN.read_bytes().decode("utf-8"))
    assert not problems, "route_table_golden.json 不是規範寫法：\n  " + "\n  ".join(problems[:20]) + "\n⇒ 用重產指令寫，不要手改（見檔頭）。"


# ── 守門自己的正對照／反向控制／突變（合成資料，不載入 app）──
_A = ["GET", "/api/a", "list_a", [["header", "authorization", False]], [], []]
_B = ["POST", "/api/b", "make_b", [], [["application/json", "#/components/schemas/B"]], []]
_C = ["GET", "/api/c/{id}", "get_c", [["path", "id", True]], [], []]


def test_diff_identical_tables_is_clean():
    d = diff_tables([_A, _B, _C], [_C, _A, _B])
    assert not (d["added"] or d["missing"] or d["changed"])


def test_diff_reports_an_added_route():
    """正對照（這次漏掉 30 條的情境）：現況多了一條，舊的單向比對不會紅，新的必須紅。"""
    live = [_A, _B, _C, ["GET", "/api/new", "new_op", [], [], []]]
    assert not [g for g in [_A, _B, _C] if g not in live], "舊的單向比對對『新增』是瞎的（這就是被取代的做法）"
    d = diff_tables([_A, _B, _C], live)
    assert d["added"] == [("GET", "/api/new")] and not d["missing"] and not d["changed"]


def test_diff_reports_a_missing_route():
    d = diff_tables([_A, _B, _C], [_A, _C])
    assert d["missing"] == [("POST", "/api/b")] and not d["added"] and not d["changed"]


def test_diff_reports_a_changed_route_and_names_the_field():
    b2 = list(_B)
    b2[3] = [["header", "authorization", False]]                         # 多一個參數
    d = diff_tables([_A, _B, _C], [_A, b2, _C])
    assert d["changed"] == [("POST", "/api/b")] and d["changed_fields"][("POST", "/api/b")] == ["parameters"]
    c2 = list(_C)
    c2[2] = "renamed_op"
    d2 = diff_tables([_A, _B, _C], [_A, _B, c2])
    assert d2["changed_fields"][("GET", "/api/c/{id}")] == ["operationId"]


def test_report_names_the_regeneration_command_and_the_same_commit_rule():
    msg = report(diff_tables([_A], [_A, _B]))
    assert "T40_WRITE_GOLDEN=1 pytest" in msg and "test_route_table_golden_2026_10_05.py" in msg
    assert "同一個 commit" in msg and "POST" in msg and "/api/b" in msg


def test_report_caps_each_group_at_twenty_and_says_how_many_more():
    live = [["GET", "/api/x%03d" % i, "op%d" % i, [], [], []] for i in range(45)]
    msg = report(diff_tables([], live))
    assert msg.count("/api/x") == 20 and "另有 25 筆" in msg and "新增（現況有、golden 沒有）（45 筆）" in msg


def test_canonical_check_accepts_the_writer_output_and_rejects_hand_edits():
    good = _serialize([_C, _A, _B])
    assert canonical_problems(good) == []
    assert _parse(good) == sorted([_A, _B, _C], key=_sort_key)
    assert canonical_problems(good.replace("\n", "\r\n")), "CRLF 要被抓到"
    assert canonical_problems(good.rstrip("\n")), "缺檔尾換行要被抓到"
    lines = good.split("\n")
    assert canonical_problems("\n".join([lines[1], lines[0]] + lines[2:])), "沒排序要被抓到"
    assert canonical_problems(good + good), "重複要被抓到"
    assert canonical_problems(good.replace('", "', '","', 1)), "非規範寫法（空白不同）要被抓到"
    assert canonical_problems(good + "\n"), "空行要被抓到"


def _first_endpoint_name(routes, scope):
    """依註冊順序找第一個完全匹配的路由名稱（新版 FastAPI 的 include_router 會留 `_IncludedRouter` 包裝，要往裡面找）。"""
    for r in routes:
        if r.matches(scope)[0] != Match.FULL:
            continue
        inner = getattr(r, "original_router", None)
        if inner is not None:
            name = _first_endpoint_name(inner.routes, scope)
            if name:
                return name
            continue
        return getattr(r, "name", "")
    return None


def test_settlement_urls_are_still_served_by_the_settlement_endpoints_first(client):
    probes = {("GET", "/api/quotations/MQ-202610-001/settlement"): "get_settlement", ("PUT", "/api/quotations/MQ-202610-001/settlement"): "update_settlement"}
    for (method, path), name in probes.items():
        scope = {"type": "http", "method": method, "path": path, "root_path": "", "headers": []}
        assert _first_endpoint_name(client.app.routes, scope) == name, (method, path)
