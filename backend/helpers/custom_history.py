# -*- coding: utf-8 -*-
"""自訂模組單據的送簽修訂紀錄（建構器第三輪 S5，2026-09-30；使用者：單據送簽→退回→修改重送，單號加 -R1、-R2 並保留各版內容，可比對差異）。

[單位] plat:custom-history    [層] L1    [穩定度] 契約（只增）
[公開介面] diff_revisions, display_no, list_revisions, on_decided, on_submitted
[不變式]
  - `record_no` 本身不變（外部參照、附件、簽核歷史都綁它）；顯示單號＝`<record_no>-R<n>`，**首次送簽不帶尾碼**，被退回後重送＝-R1、再退回再送＝-R2
  - 每次「送簽」（進入有簽核的狀態、且真的展開了簽核層）寫一列快照（該次送出的欄位值＋所用定義版本）；決定（核可／退回＋原因）回填同一列
  - `custom_records.revision`＝目前修訂號＝已寫的快照數 − 1（0＝首次送簽或還沒送簽）；快照不可變
  - 讀取修訂與讀單同權限：快照與差異一律經欄位可見遮蔽（看不到的欄位不出現、也不出現在差異裡）
  - 差異依「單據自己那一版的定義」逐欄位比：明細表逐列逐欄比對
[契約題] tests/test_builder3_history_2026_09_30.py
"""
import json
from datetime import datetime

from . import custom_builder_support as _S


def _now():
    return datetime.now().isoformat(timespec="seconds")


def display_no(rec) -> str:
    """顯示單號：首次送簽不帶尾碼；修訂號 n＞0 ⇒ `-R<n>`。"""
    n = int(rec.get("revision") or 0)
    return "%s-R%d" % (rec["record_no"], n) if n > 0 else rec["record_no"]


def on_submitted(conn, rec, user) -> int:
    """送簽（同一個交易內）：寫快照、更新目前修訂號。回這次的修訂號。"""
    n = conn.execute("SELECT COUNT(*) FROM custom_record_snapshots WHERE record_id=?", (rec["id"],)).fetchone()[0]
    conn.execute("INSERT INTO custom_record_snapshots (record_id, module_key, revision, data_json, def_version, submitted_by, submitted_at) "
                 "VALUES (?,?,?,?,?,?,?)", (rec["id"], rec["module_key"], n, json.dumps(rec.get("data") or {}, ensure_ascii=False, allow_nan=False),
                                            rec["def_version"], user["username"], _now()))
    conn.execute("UPDATE custom_records SET revision=? WHERE id=?", (n, rec["id"]))
    rec["revision"] = n
    return n


def on_decided(conn, rec, result, user, note="") -> None:
    """離開簽核狀態時（核可／自動通過／退回）：回填最新一列尚未決定的快照。沒有未決定的快照（舊資料、無簽核層）⇒ 略過。"""
    r = conn.execute("SELECT id FROM custom_record_snapshots WHERE record_id=? AND decision='' ORDER BY revision DESC LIMIT 1",
                     (rec["id"],)).fetchone()
    if r is not None:
        conn.execute("UPDATE custom_record_snapshots SET decision=?, decided_by=?, decided_at=?, note=? WHERE id=?",
                     (result, user["username"], _now(), note or "", r["id"]))


def list_revisions(conn, rec, body, user) -> list:
    """`[{revision, displayNo, defVersion, submittedBy, submittedAt, decision, decidedBy, decidedAt, note}]`（新的在前；最後一筆＝目前內容不算，
    前端另把「目前」放在最上面）。快照內容不在這裡（要看差異走 `diff_revisions`）。"""
    rows = conn.execute("SELECT revision, def_version, submitted_by, submitted_at, decision, decided_by, decided_at, note "
                        "FROM custom_record_snapshots WHERE record_id=? ORDER BY revision DESC", (rec["id"],)).fetchall()
    return [{"revision": r["revision"], "displayNo": display_no({"record_no": rec["record_no"], "revision": r["revision"]}),
             "defVersion": r["def_version"], "submittedBy": r["submitted_by"], "submittedAt": r["submitted_at"],
             "decision": r["decision"], "decidedBy": r["decided_by"], "decidedAt": r["decided_at"], "note": r["note"]} for r in rows]


def _side(conn, rec, which):
    """`'current'` ⇒ 目前內容；數字 ⇒ 該修訂的快照（沒有 ⇒ None）。回 (data, 標籤)。"""
    if which == "current":
        return (rec.get("data") or {}), "目前"
    r = conn.execute("SELECT data_json, revision FROM custom_record_snapshots WHERE record_id=? AND revision=?", (rec["id"], int(which))).fetchone()
    if r is None:
        return None, ""
    return json.loads(r["data_json"] or "{}"), "R%d" % r["revision"] if r["revision"] else "首次送簽"


def _norm(v):
    return None if v in (None, "", [], {}) else v


def diff_revisions(conn, rec, body, a, b, user) -> dict:
    """兩份內容的逐欄位差異：`{a, b, changes: [{key, label, type, op, old, new, rows?}]}`。
    a／b＝`'current'` 或修訂號（整數字串）；不存在 ⇒ ValueError。看不到的欄位不出現。
    明細表：`rows`＝逐列逐欄 `[{index, op: add|remove|change, cols: {欄: {old, new}}}]`（列以順序對應）。公式欄照比（值是算出來的）。"""
    da, la = _side(conn, rec, a if a == "current" else int(a))
    db_, lb = _side(conn, rec, b if b == "current" else int(b))
    if da is None or db_ is None:
        raise ValueError("找不到這個修訂")
    changes = []
    for f in body.get("fields", []):
        if not isinstance(f, dict) or not f.get("key") or not _S.can_see_field(f, user):
            continue
        k, old, new = f["key"], _norm(da.get(f["key"])), _norm(db_.get(f["key"]))
        if old == new:
            continue
        item = {"key": k, "label": f.get("label") or k, "type": f.get("type"), "old": old, "new": new,
                "op": "add" if old is None else ("remove" if new is None else "change")}
        if f.get("type") == "table":
            item["rows"] = _table_rows(old or [], new or [], f)
        changes.append(item)
    return {"a": la, "b": lb, "changes": changes}


def _table_rows(old, new, f) -> list:
    cols = [c["key"] for c in f.get("columns", []) if isinstance(c, dict) and c.get("key")]
    out = []
    for i in range(max(len(old), len(new))):
        o, n = (old[i] if i < len(old) else None), (new[i] if i < len(new) else None)
        if o is None:
            out.append({"index": i, "op": "add", "cols": {c: {"old": None, "new": n.get(c)} for c in cols if _norm(n.get(c)) is not None}})
        elif n is None:
            out.append({"index": i, "op": "remove", "cols": {c: {"old": o.get(c), "new": None} for c in cols if _norm(o.get(c)) is not None}})
        else:
            ch = {c: {"old": o.get(c), "new": n.get(c)} for c in cols if _norm(o.get(c)) != _norm(n.get(c))}
            if ch:
                out.append({"index": i, "op": "change", "cols": ch})
    return out
