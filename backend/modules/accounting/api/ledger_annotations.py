# -*- coding: utf-8 -*-
"""總帳：來源憑證補登（`gl_source_annotations`）的輸入 API（旗標 `source_annotations`）。

會計在這裡補登來源模組沒有的憑證資料，補登值優先於來源值，來源模組不必加欄位、不必 migration：
- `input_tax`（非負整數）：承攬商發票 E04、進貨發票 E08b 的實際進項稅額；『未拆稅』的額外支出 E11、叫料 E12 拆出的進項稅額；
- `invoice_date`（YYYY-MM-DD）：承攬商發票 E04、進貨發票 E08b 的入帳日。
補登只影響**之後**引擎產生的草稿：內容變了 ⇒ 未過帳草稿重建；已過帳者走 drift（舊傳票不動，另產反向草稿與新草稿）。
讀取＝cashier／finance；寫入（新增、修改、刪除）＝finance，每筆寫稽核（含舊值）。
"""
import datetime as _dt
import json

from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
from helpers import _audit, _require_user, _tok, require_any_module
from modules.accounting.ledger import features as _features

router = APIRouter(prefix="/api/ledger", tags=["ledger"])

_READ = ("cashier", "finance")
_WRITE = ("finance",)

#: 可補登的來源類型 ⇒ 允許的欄位（與 contract.apply_annotations 認得的一致）
ALLOWED = {
    "contractor_dispatch": ("input_tax", "invoice_date"),          # E04 承攬商發票
    "stock_batch_invoice": ("input_tax", "invoice_date"),          # E08b 進貨發票（E09 付款跟著調整）
    "case_extra_expense": ("input_tax",),                          # E11 額外支出（未拆稅）
    "case_material_order": ("input_tax",),                         # E12 叫料（未拆稅）
}
#: 畫面用名稱（不要讓使用者看到 contractor_dispatch／E04 這種代碼）
SOURCE_LABEL = {"contractor_dispatch": "承攬商派工", "stock_batch_invoice": "進貨發票", "case_extra_expense": "案件額外支出", "case_material_order": "案件叫料"}
EVENT_LABEL = {"E04": "承攬商發票", "E08b": "進貨發票進項稅", "E09": "進貨付款", "E11": "額外支出", "E12": "叫料"}
_MAX_LIST = 500


def _require_read(authorization):
    user = _require_user(authorization)
    require_any_module(user, _READ, "總帳")
    return user


def _require_write(authorization):
    user = _require_user(authorization)
    require_any_module(user, _WRITE, "總帳結帳")
    return user


def _flag(conn):
    if not _features.flags(conn).get("source_annotations"):
        raise HTTPException(409, "來源憑證補登功能尚未開啟（最高管理者在「總帳作業」開啟）。")


def _clean(source_type, source_key, field, value):
    if source_type not in ALLOWED:
        raise HTTPException(400, "不支援的來源類型：%s（可補登：%s）。" % (source_type, "、".join(ALLOWED)))
    key = str(source_key or "").strip()
    if not key or len(key) > 120:
        raise HTTPException(400, "來源鍵不可空白（最長 120 字）。")
    if field not in ALLOWED[source_type]:
        raise HTTPException(400, "%s 只能補登：%s。" % (source_type, "、".join(ALLOWED[source_type])))
    v = str(value if value is not None else "").strip()
    if field == "input_tax":
        if not v.isdigit() or int(v) > 999999999:
            raise HTTPException(400, "進項稅額要是不小於 0 的整數。")
        v = str(int(v))
    else:
        try:
            v = _dt.date.fromisoformat(v).isoformat()
        except ValueError:
            raise HTTPException(400, "日期格式要是 YYYY-MM-DD。")
    return source_type, key, field, v


@router.get("/annotations")
def list_annotations(source_type: str = None, source_key: str = None, authorization: str = Header(None)):
    _require_read(authorization)
    conn = get_db()
    try:
        _flag(conn)
        q, args = "SELECT * FROM gl_source_annotations WHERE 1=1", []
        if source_type:
            q, args = q + " AND source_type=?", args + [source_type]
        if source_key:
            q, args = q + " AND source_key=?", args + [source_key]
        rows = [dict(r) for r in conn.execute(q + " ORDER BY id DESC LIMIT %d" % (_MAX_LIST + 1), args)]
        return {"annotations": rows[:_MAX_LIST], "truncated": len(rows) > _MAX_LIST, "allowed": {k: list(v) for k, v in ALLOWED.items()}}
    finally:
        conn.close()


@router.get("/annotations/pending")
def pending_annotations(authorization: str = Header(None)):
    """待補登清單：目前有效的事件（草稿／已過帳／來源變動）裡，稅額是估計（`tax_estimated`）或來源未拆稅（`tax_unsplit`）的，附已有的補登值。"""
    _require_read(authorization)
    conn = get_db()
    try:
        _flag(conn)
        have = {(r["source_type"], r["source_key"], r["field"]): (r["value"], r["id"]) for r in conn.execute("SELECT id, source_type, source_key, field, value FROM gl_source_annotations")}
        out = []
        for r in conn.execute("SELECT id, source_type, source_key, event_code, event_date, status, amount, payload_json FROM gl_source_events "
                              "WHERE status IN ('drafted','posted','drift') AND (payload_json LIKE '%\"tax_estimated\": true%' OR payload_json LIKE '%\"tax_unsplit\": true%' "
                              "OR payload_json LIKE '%\"tax_annotated\": true%') ORDER BY event_date DESC, id DESC LIMIT ?", (_MAX_LIST + 1,)):
            try:
                ev = json.loads(r["payload_json"] or "{}")
            except ValueError:
                continue
            meta = ev.get("meta") or {}
            st = r["source_type"] if r["source_type"] != "stock_batch_payment" else "stock_batch_invoice"
            if st not in ALLOWED or "input_tax" not in ALLOWED[st]:
                continue
            out.append({"event_id": r["id"], "source_type": st, "source_key": r["source_key"], "event_code": r["event_code"], "event_date": r["event_date"],
                        "source_label": "%s %s" % (SOURCE_LABEL.get(st, st), r["source_key"]), "event_label": EVENT_LABEL.get(r["event_code"], r["event_code"]),
                        "status": r["status"], "doc_no": ev.get("doc_no") or "", "amount": r["amount"],
                        "kind": "estimated" if meta.get("tax_estimated") else ("unsplit" if meta.get("tax_unsplit") else "annotated"),
                        "input_tax": have.get((st, r["source_key"], "input_tax"), ("", None))[0], "input_tax_id": have.get((st, r["source_key"], "input_tax"), ("", None))[1],
                        "invoice_date": have.get((st, r["source_key"], "invoice_date"), ("", None))[0], "invoice_date_id": have.get((st, r["source_key"], "invoice_date"), ("", None))[1],
                        "can_date": "invoice_date" in ALLOWED[st]})
        seen, uniq = set(), []
        for x in out[:_MAX_LIST]:                                    # E08b 與 E09 共用同一補登鍵 ⇒ 只列一次
            k = (x["source_type"], x["source_key"])
            if k not in seen:
                seen.add(k)
                uniq.append(x)
        return {"items": uniq, "truncated": len(out) > _MAX_LIST}
    finally:
        conn.close()


@router.put("/annotations")
def put_annotation(body: dict = Body(...), authorization: str = Header(None)):
    """新增或修改一筆補登（同來源同欄位只有一筆）；寫稽核（含舊值）。"""
    user = _require_write(authorization)
    b = body or {}
    st, key, field, value = _clean(b.get("source_type"), b.get("source_key"), b.get("field"), b.get("value"))
    conn = get_db()
    try:
        _flag(conn)
        old = conn.execute("SELECT value FROM gl_source_annotations WHERE source_type=? AND source_key=? AND field=?", (st, key, field)).fetchone()
        now = _dt.datetime.now().isoformat(timespec="seconds")
        conn.execute("INSERT INTO gl_source_annotations(source_type, source_key, field, value, updated_by, updated_at) VALUES (?,?,?,?,?,?) "
                     "ON CONFLICT(source_type, source_key, field) DO UPDATE SET value=excluded.value, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
                     (st, key, field, value, (user or {}).get("username") or "", now))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.annotation.put", "gl_source_annotations", "%s/%s/%s" % (st, key, field),
           "補登 %s＝%s（原值：%s）" % (field, value, old[0] if old else "無"))
    return {"ok": True, "source_type": st, "source_key": key, "field": field, "value": value, "previous": old[0] if old else None}


@router.delete("/annotations/{annotation_id}")
def delete_annotation(annotation_id: int, authorization: str = Header(None)):
    _require_write(authorization)
    conn = get_db()
    try:
        _flag(conn)
        row = conn.execute("SELECT * FROM gl_source_annotations WHERE id=?", (annotation_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "找不到這筆補登。")
        conn.execute("DELETE FROM gl_source_annotations WHERE id=?", (annotation_id,))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.annotation.delete", "gl_source_annotations", "%s/%s/%s" % (row["source_type"], row["source_key"], row["field"]),
           "刪除補登 %s＝%s" % (row["field"], row["value"]))
    return {"ok": True}
