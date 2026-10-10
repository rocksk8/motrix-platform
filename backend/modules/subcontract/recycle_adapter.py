# -*- coding: utf-8 -*-
"""外包工班的刪除暫存區 adapter（第 53 班 P1；契約 helpers/recycle_bin.py，IP-RB1／IP-RB2）：承攬商派發、承攬商匯款申請。

- 刪除條件**沿用現行規則，不放寬**（使用者 D1）：派發＝審核中／已核准不可刪、已有匯款申請不可刪；匯款申請＝只有草稿、分期草稿守 LIFO。
  已核准的單據只能走最高管理者的『刪除已核可』入口（`can_delete_approved`＋`impact`）。
- 快照＝單據列＋子表列（派發：勞報單連結、附件刪除申請）＋附件清單；還原放回**原值**（同欄位、同主鍵）；單號被占用 ⇒ 換新單號並回報。
- 遮罩：用 L1 預設 `mask_obj`（會展開 JSON 字串欄位再遮罩帳號類欄位）；還原用未遮罩原文。
- 這個檔案內的 `DELETE FROM` 是 `delete_in_tx` 的實作（暫存區守門免登記）；刪除端點在暫存區模組缺席時也呼叫它（照舊刪資料列、不刪檔，並明說）。
"""
import json
import sqlite3
import time

from db import get_db, spawn_bg_thread as _spawn
from helpers import recycle_bin as RB

ET_DISPATCH = "contractor_dispatch"
ET_VOUCHER = "contractor_voucher"
_DISPATCH_TBL = "contractor_dispatches"
_VOUCHER_TBL = "contractor_payment_vouchers"
_LINK_TBL = "payslip_dispatch_links"
_REQ_TBL = "dispatch_file_delete_requests"


def _has_table(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _columns(conn, table):
    return [r[1] for r in conn.execute("PRAGMA table_info(%s)" % table).fetchall()]


def _dicts(rows):
    return [{k: r[k] for k in r.keys()} for r in rows]


def _insert(conn, table, row, drop=()):
    """依快照的欄位放回一列（只放現在表裡還有的欄位——欄位在快照之後被拿掉也能還原）。回 lastrowid。"""
    have = set(_columns(conn, table))
    cols = [c for c in row if c in have and c not in drop]
    cur = conn.execute("INSERT INTO %s (%s) VALUES (%s)" % (table, ",".join(cols), ",".join("?" * len(cols))), [row[c] for c in cols])
    return cur.lastrowid


def _json_list(text):
    try:
        v = json.loads(text or "[]")
    except (TypeError, ValueError):
        return []
    return v if isinstance(v, list) else []


def _file_rels(*json_texts):
    """附件欄位（`save_document_files` 的 metadata 陣列）→ uploads 下的相對路徑清單（去重、保序）。"""
    out = []
    for t in json_texts:
        for f in _json_list(t):
            p = f.get("path") if isinstance(f, dict) else None
            if p and p not in out:
                out.append(p)
    return out


def _rewrite_paths(json_text, ctx):
    """還原後附件實際路徑可能不同（原路徑被占用）⇒ 改寫 metadata 的 path；其餘欄位原樣。"""
    items = _json_list(json_text)
    changed = False
    for f in items:
        if isinstance(f, dict) and f.get("path"):
            new = ctx.file_path("uploads", f["path"])
            if new != f["path"]:
                f["path"] = new
                changed = True
    return json.dumps(items, ensure_ascii=False) if changed else json_text


def _when_committed(check, action, tries=75, delay=0.2):
    """交易 commit 之後才做的副作用（行事曆事件、站內通知清理）。暫存區的刪除／還原由 recyclebin 在『呼叫端的交易』內呼叫 adapter、之後才 commit，
    而 L1 契約沒有 commit 之後的掛鉤——所以這裡背景輪詢『已提交的狀態』（`check()` 用自己的連線讀，看到新狀態＝已 commit）再做 `action()`。
    交易回滾／逾時（約 15 秒）⇒ 什麼都不做；動作本身都是『依現況對齊』（冪等），多做一次無害。"""
    def run():
        for _ in range(tries):
            try:
                if check():
                    break
            except Exception:                                  # noqa: BLE001
                pass
            time.sleep(delay)
        else:
            return
        try:
            action()
        except Exception:                                      # noqa: BLE001 — 副作用失敗不影響已完成的刪除／還原
            pass
    return _spawn(run)


def _exists(table, col, val):
    c = get_db()
    try:
        return c.execute("SELECT 1 FROM %s WHERE %s=?" % (table, col), (val,)).fetchone() is not None
    finally:
        c.close()


def _gl_note(conn, source_type, source_key):
    try:
        from helpers.gl_status import gl_posted_warning
        return gl_posted_warning(conn, source_type, source_key)
    except Exception:                                          # noqa: BLE001 — 提示失敗不擋刪除
        return None


# ── 派發 ──────────────────────────────────────────────────────────────────────
class DispatchBinAdapter(RB.Adapter):
    entity_type = ET_DISPATCH
    label = "承攬商派發"

    def _row(self, conn, entity_id):
        return conn.execute("SELECT * FROM %s WHERE id=?" % _DISPATCH_TBL, (int(entity_id),)).fetchone()

    def _vouchers(self, conn, did):
        return conn.execute("SELECT voucher_no, voided_at, is_paid FROM %s WHERE dispatch_id=?" % _VOUCHER_TBL, (int(did),)).fetchall()

    def _voucher_block(self, conn, did):
        vs = self._vouchers(conn, did)
        if not vs:
            return ""
        active = [v["voucher_no"] for v in vs if not v["voided_at"]]
        if active:
            return "此派發已產生匯款申請（%s），請先處理該申請後再刪除" % active[0]
        return "此派發有已作廢的匯款申請（%s）留存紀錄，不能刪除" % vs[0]["voucher_no"]

    def can_delete(self, conn, entity_id, user):
        row = self._row(conn, entity_id)
        if row is None:
            return False, "派發紀錄不存在"
        why = self._voucher_block(conn, entity_id)
        if why:
            return False, why
        if row["approval_status"] in ("待審核", "簽核中", "已核准"):
            return False, "審核中或已核准的派發不能刪除，請改用「取消」並填理由"
        return True, ""

    def can_delete_approved(self, conn, entity_id, user):
        if self._row(conn, entity_id) is None:
            return False, "派發紀錄不存在"
        why = self._voucher_block(conn, entity_id)
        return (False, why) if why else (True, "")

    def impact(self, conn, entity_id):
        row = self._row(conn, entity_id)
        if row is None:
            return []
        out = []
        why = self._voucher_block(conn, entity_id)
        if why:
            out.append({"kind": "voucher", "label": why, "blocking": True})
        if row["approval_status"] in ("待審核", "簽核中", "已核准"):
            out.append({"kind": "approved", "label": "派發審核狀態：%s" % row["approval_status"], "blocking": False})
        if row["completion_status"]:
            out.append({"kind": "completion", "label": "完工審核狀態：%s" % row["completion_status"], "blocking": False})
        if row["status"] in ("accepted", "completed"):
            out.append({"kind": "status", "label": "作業狀態：%s" % row["status"], "blocking": False})
        if _has_table(conn, _LINK_TBL):
            n = conn.execute("SELECT COUNT(*) FROM %s WHERE dispatch_id=?" % _LINK_TBL, (int(entity_id),)).fetchone()[0]
            if n:
                out.append({"kind": "payslip_link", "label": "已關聯 %d 張勞報單（連結隨派發進暫存區，還原時復原）" % n, "blocking": False})
        gl = _gl_note(conn, "contractor_dispatch", str(entity_id))
        if gl:
            out.append({"kind": "gl", "label": gl, "blocking": False})
        return out

    def snapshot(self, conn, entity_id):
        row = self._row(conn, entity_id)
        if row is None:
            raise RB.BinError("派發紀錄不存在")
        d = {k: row[k] for k in row.keys()}
        rows = {_DISPATCH_TBL: [d]}
        if _has_table(conn, _LINK_TBL):
            rows[_LINK_TBL] = _dicts(conn.execute("SELECT * FROM %s WHERE dispatch_id=? ORDER BY id" % _LINK_TBL, (d["id"],)).fetchall())
        if _has_table(conn, _REQ_TBL):
            rows[_REQ_TBL] = _dicts(conn.execute("SELECT * FROM %s WHERE dispatch_id=? ORDER BY id" % _REQ_TBL, (d["id"],)).fetchall())
        quote_exists = bool(_has_table(conn, "quotations") and conn.execute("SELECT 1 FROM quotations WHERE quote_no=?", (d["quote_no"],)).fetchone())
        files = [{"root": "uploads", "rel": p} for p in _file_rels(d.get("files_json"), d.get("invoice_files_json"))]
        return {"rows": rows, "files": files, "label": "派發 %s（%s）" % (d.get("doc_code") or "#%s" % d["id"], d["quote_no"]),
                "parent": None, "meta": {"quote_exists": quote_exists, "vendor_id": d.get("vendor_id")}}

    def delete_in_tx(self, conn, entity_id):
        did = int(entity_id)
        row = self._row(conn, did)
        if row is not None and (row["approval_status"] in ("待審核", "簽核中") or row["completion_status"] in ("待審核", "簽核中")):
            from helpers import _purge_notifications               # 審核中的派發（走『刪除已核可』入口）⇒ 清掉簽核人手上的待辦通知（commit 之後）
            _when_committed(lambda: not _exists(_DISPATCH_TBL, "id", did),
                            lambda: _purge_notifications(str(did), ["dispatch_approval_request", "dispatch_completion_request"]))
        if _has_table(conn, _LINK_TBL):
            conn.execute("DELETE FROM payslip_dispatch_links WHERE dispatch_id=?", (did,))
        if _has_table(conn, _REQ_TBL):
            conn.execute("DELETE FROM dispatch_file_delete_requests WHERE dispatch_id=?", (did,))
        conn.execute("DELETE FROM contractor_dispatches WHERE id=?", (did,))

    def restore_in_tx(self, conn, snap, ctx):
        d = dict(snap["rows"][_DISPATCH_TBL][0])
        meta = snap.get("meta") or {}
        if self._row(conn, d["id"]) is not None:
            raise RB.BinError("conflict: 派發 #%s 已存在，不覆蓋既有資料" % d["id"])
        if d.get("vendor_id") and not conn.execute("SELECT 1 FROM vendor_contractors WHERE id=?", (d["vendor_id"],)).fetchone():
            raise RB.BinError("parent_missing: 承攬商 #%s 已不存在，請先還原該承攬商" % d["vendor_id"])
        if meta.get("quote_exists") and not conn.execute("SELECT 1 FROM quotations WHERE quote_no=?", (d["quote_no"],)).fetchone():
            raise RB.BinError("parent_missing: 報價單 %s 已不存在（可能在暫存區），請先還原報價單" % d["quote_no"])
        notes, renumbered = [], False
        if d.get("doc_code") and conn.execute("SELECT 1 FROM %s WHERE doc_code=?" % _DISPATCH_TBL, (d["doc_code"],)).fetchone():
            from modules.subcontract import dispatch_flow as _flow
            new = _flow.next_dispatch_code(conn)
            notes.append("單號 %s 已被占用，改用 %s" % (d["doc_code"], new))
            d["doc_code"], renumbered = new, True
        for col in ("files_json", "invoice_files_json"):
            if col in d:
                d[col] = _rewrite_paths(d[col], ctx)
        try:
            _insert(conn, _DISPATCH_TBL, d)
        except sqlite3.IntegrityError as e:
            raise RB.BinError("conflict: %s" % e)
        for r in snap["rows"].get(_LINK_TBL) or []:
            if not _has_table(conn, _LINK_TBL):
                break
            if not conn.execute("SELECT 1 FROM payslips WHERE slip_no=?", (r["slip_no"],)).fetchone():
                notes.append("勞報單 %s 已不存在，未恢復與它的連結" % r["slip_no"])
                continue
            if conn.execute("SELECT 1 FROM %s WHERE slip_no=? AND dispatch_id=?" % _LINK_TBL, (r["slip_no"], d["id"])).fetchone():
                notes.append("勞報單 %s 已經連到這張派發，略過重複的連結" % r["slip_no"])
                continue
            try:
                _insert(conn, _LINK_TBL, r, drop=("id",) if conn.execute("SELECT 1 FROM %s WHERE id=?" % _LINK_TBL, (r["id"],)).fetchone() else ())
            except sqlite3.IntegrityError as e:
                raise RB.BinError("conflict: 勞報單連結 %s 無法放回（%s）" % (r["slip_no"], e))
        for r in snap["rows"].get(_REQ_TBL) or []:
            if not _has_table(conn, _REQ_TBL):
                break
            try:
                _insert(conn, _REQ_TBL, r, drop=() if not conn.execute("SELECT 1 FROM %s WHERE id=?" % _REQ_TBL, (r["id"],)).fetchone() else ("id",))
            except sqlite3.IntegrityError as e:
                raise RB.BinError("conflict: 附件刪除申請無法放回（%s）" % e)
        return {"entity_id": d["id"], "renumbered": renumbered, "notes": notes}


# ── 匯款申請 ──────────────────────────────────────────────────────────────────
class VoucherBinAdapter(RB.Adapter):
    entity_type = ET_VOUCHER
    label = "承攬商匯款申請"

    def _row(self, conn, voucher_no):
        return conn.execute("SELECT * FROM %s WHERE voucher_no=?" % _VOUCHER_TBL, (str(voucher_no),)).fetchone()

    def _lifo(self, conn, row):
        if not row["kind"]:
            return ""
        from modules.subcontract import remit_create as _rc
        return _rc.void_blocker(conn, row) or ""

    def can_delete(self, conn, entity_id, user):
        row = self._row(conn, entity_id)
        if row is None:
            return False, "申請不存在"
        if row["status"] != "草稿":
            return False, "僅草稿狀態可刪除" + ("（已送審的分期申請請用「作廢」）" if row["kind"] else "")
        why = self._lifo(conn, row)
        return (False, why) if why else (True, "")

    def can_delete_approved(self, conn, entity_id, user):
        row = self._row(conn, entity_id)
        if row is None:
            return False, "申請不存在"
        if row["is_paid"]:
            return False, "這張申請已標記匯款，請先撤銷付款"
        why = self._lifo(conn, row) if row["kind"] and not row["voided_at"] else ""
        return (False, why) if why else (True, "")

    def impact(self, conn, entity_id):
        row = self._row(conn, entity_id)
        if row is None:
            return []
        out = []
        if row["is_paid"]:
            out.append({"kind": "paid", "label": "已標記匯款（%s）" % (row["paid_at"] or "")[:10], "blocking": True})
        why = self._lifo(conn, row) if row["kind"] and not row["voided_at"] and not row["is_paid"] else ""
        if why:
            out.append({"kind": "lifo", "label": why, "blocking": True})
        if row["status"] != "草稿":
            out.append({"kind": "approved", "label": "申請狀態：%s" % row["status"], "blocking": False})
        if row["inv_no"] or row["inv_date"]:
            out.append({"kind": "invoice", "label": "已登錄發票 %s %s" % (row["inv_no"], row["inv_date"]), "blocking": False})
        gl = _gl_note(conn, "contractor_voucher", row["voucher_no"]) or _gl_note(conn, "contractor_voucher_invoice", row["voucher_no"])
        if gl:
            out.append({"kind": "gl", "label": gl, "blocking": False})
        return out

    def snapshot(self, conn, entity_id):
        row = self._row(conn, entity_id)
        if row is None:
            raise RB.BinError("申請不存在")
        d = {k: row[k] for k in row.keys()}
        files = [{"root": "uploads", "rel": p} for p in _file_rels(d.get("inv_files_json"))]
        return {"rows": {_VOUCHER_TBL: [d]}, "files": files, "label": "匯款申請 %s（%s）" % (d["voucher_no"], d["quote_no"]),
                "parent": (ET_DISPATCH, str(d["dispatch_id"])), "meta": {"dispatch_id": d["dispatch_id"], "kind": d.get("kind") or ""}}

    def delete_in_tx(self, conn, entity_id):
        no = str(entity_id)
        conn.execute("DELETE FROM contractor_payment_vouchers WHERE voucher_no=?", (no,))
        _when_committed(lambda: not _exists(_VOUCHER_TBL, "voucher_no", no), lambda: self._after_delete(no))

    @staticmethod
    def _after_delete(no):
        """commit 之後：收回『付款待辦』行事曆事件（已核准的申請才有）、清掉簽核通知（與端點的一般刪除同一份清單）。"""
        from helpers import _purge_notifications
        from modules.subcontract import payable_due as _PD
        _PD.fire(no)
        _purge_notifications(no, ["contractor_voucher_approval_request", "contractor_voucher_approved", "contractor_voucher_returned", "approval_reminder"])

    def restore_in_tx(self, conn, snap, ctx):
        d = dict(snap["rows"][_VOUCHER_TBL][0])
        if not conn.execute("SELECT 1 FROM %s WHERE id=?" % _DISPATCH_TBL, (d["dispatch_id"],)).fetchone():
            raise RB.BinError("parent_missing: 所屬派發 #%s 已不存在（可能在暫存區），請先還原派發" % d["dispatch_id"])
        notes, renumbered = [], False
        if conn.execute("SELECT 1 FROM %s WHERE id=?" % _VOUCHER_TBL, (d["id"],)).fetchone():
            raise RB.BinError("conflict: 申請 id #%s 已存在，不覆蓋既有資料" % d["id"])
        if self._row(conn, d["voucher_no"]) is not None:
            from db import next_entity_code
            new = next_entity_code(conn, _VOUCHER_TBL, "PV", code_col="voucher_no")
            notes.append("單號 %s 已被占用，改用 %s" % (d["voucher_no"], new))
            d["voucher_no"], renumbered = new, True
        if "inv_files_json" in d:
            d["inv_files_json"] = _rewrite_paths(d["inv_files_json"], ctx)
        try:
            _insert(conn, _VOUCHER_TBL, d)
        except sqlite3.IntegrityError as e:
            raise RB.BinError("conflict: 同派發同款別同期別已有有效申請（%s）" % e)
        no = d["voucher_no"]
        _when_committed(lambda: _exists(_VOUCHER_TBL, "voucher_no", no), lambda: self._after_restore(no))     # commit 之後：依現況重建『付款待辦』事件
        return {"entity_id": no, "renumbered": renumbered, "notes": notes}

    @staticmethod
    def _after_restore(no):
        from modules.subcontract import payable_due as _PD
        _PD.fire(no)
