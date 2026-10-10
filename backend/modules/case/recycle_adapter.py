# -*- coding: utf-8 -*-
"""M01 案件的刪除暫存區 adapter（第 53 班 P1；契約 helpers/recycle_bin.py、IP-RB1／IP-RB2；進度 docs/platform/plans/RECYCLE-BIN-P1-CASE-T53.md）。

四種單據：`quotation`（報價單＋它名下的階段／拜訪／進度更新／行動事項）、`extra_expense`（額外支出；含請購單／採購單／費用單據，同一張表）、
`completion_note`（完工單）、`material_order`（材料申請＝`quotations.data_json` 的 materialOrders 一列＋審核疊加列）。
規則（使用者 D1）：**不放寬**現行刪除條件——`can_delete` 逐字沿用各端點原本的規則（只有草稿／草稿與已駁回…）；已核可的只走 superadmin 的
『刪除已核可』（`can_delete_approved`＋`impact`），有下游紀錄（已付款、已被引用、有匯款申請、報價單底下還掛著其他單據）就**明確拒絕**並說明，不連帶刪別的單據。
本檔名為 `recycle_adapter.py`：裡面的 `DELETE FROM`／刪檔免進三道守門基線（它們就是 `delete_in_tx`；刪檔實際由 recyclebin 搬走，不在這裡）。
"""
import json
import sqlite3
from datetime import datetime
from typing import List, Tuple

from helpers import recycle_bin as RB
from helpers.uploads import canonical_upload_path

#: 暫存區模組不在時，刪除端點的明說（IP-RB2「對方不在時」）：照舊硬刪、附件不留
BIN_ABSENT_NOTICE = "刪除暫存區模組未安裝：這張單據已直接刪除，無法還原"


# ── 共用小工具（本檔內用；不 import 其他模組）────────────────────────────────────
def _cols(conn, table) -> List[str]:
    return [r[1] for r in conn.execute("PRAGMA table_info(%s)" % table).fetchall()]


def _rows(conn, table, where, args=()) -> List[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM %s WHERE %s" % (table, where), tuple(args)).fetchall()]


def _insert(conn, table, row: dict, drop_id: bool = False) -> int:
    """依『現在的欄位』插入一列（快照裡有、現在已不存在的欄位略過）。回 lastrowid。主鍵／唯一鍵衝突 ⇒ `BinError('conflict: …')`。"""
    have = set(_cols(conn, table))
    cols = [k for k in row if k in have and not (drop_id and k == "id")]
    try:
        cur = conn.execute("INSERT INTO %s (%s) VALUES (%s)" % (table, ",".join(cols), ",".join("?" * len(cols))), [row[k] for k in cols])
    except sqlite3.IntegrityError as e:
        raise RB.BinError("conflict: 還原時資料衝突（%s：%s）" % (table, e))
    return cur.lastrowid


def _jload(raw, default):
    try:
        v = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return default
    return v if isinstance(v, type(default)) else default


def _walk_paths(obj, out: list) -> None:
    """遞迴找出所有 `{"path": "<uploads 相對路徑>"}` 的附件項目（只收正規的上傳路徑）。"""
    if isinstance(obj, dict):
        p = obj.get("path")
        if isinstance(p, str):
            rel = canonical_upload_path(p)
            if rel:
                out.append(rel)
        for v in obj.values():
            _walk_paths(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_paths(v, out)


def _paths_of(*raws) -> List[str]:
    """JSON 字串（或已解析的物件）裡所有附件的正規 uploads 路徑（去重、保序）。"""
    out: list = []
    for raw in raws:
        if isinstance(raw, str):
            try:
                raw = json.loads(raw) if raw else None
            except ValueError:
                raw = None
        _walk_paths(raw, out)
    return list(dict.fromkeys(out))


def reserved(conn, entity_type) -> set:
    """暫存區裡（還在、或還原失敗）的單據編號——產生新編號的地方要跳過它們，否則刪掉最新一張後下一張會重用同一個號碼、還原就撞號（也避免已寄出的單號被重發）。
    暫存區模組不在 ⇒ 空集合。在呼叫端自己的交易內讀（與產號同一個寫鎖）。"""
    return set(RB.reserved_ids(conn, entity_type) or ())            # 暫存區模組不在 ⇒ 空集合（IP-RB3）


def _rm_empty_dirs(rels) -> None:
    """附件被搬進暫存區後，原本單據專屬的資料夾若已空就拿掉（與原本 purge_document_files 的行為相同；有別的檔就保留；還原時由 recyclebin 重建）。"""
    import os
    from helpers.uploads import UPLOADS_ROOT
    for d in {os.path.dirname(os.path.join(UPLOADS_ROOT, *r.split("/"))) for r in rels or []}:
        try:
            os.rmdir(d)
        except OSError:
            pass


def _files(rels) -> List[dict]:
    return [{"root": "uploads", "rel": r} for r in rels]


def _remap_paths(obj, ctx):
    """還原時把附件路徑換成『實際搬回的路徑』（被占用時不同）。回新物件。"""
    if isinstance(obj, dict):
        out = {k: _remap_paths(v, ctx) for k, v in obj.items()}
        p = out.get("path")
        if isinstance(p, str) and ("uploads", p) in ctx.files:
            out["path"] = ctx.file_path("uploads", p)
        return out
    if isinstance(obj, list):
        return [_remap_paths(v, ctx) for v in obj]
    return obj


def _remap_json_cols(row: dict, ctx, *cols) -> dict:
    row = dict(row)
    for c in cols:
        if c in row and isinstance(row[c], str) and row[c]:
            try:
                row[c] = json.dumps(_remap_paths(json.loads(row[c]), ctx), ensure_ascii=False)
            except ValueError:
                pass
    return row


def _quote_exists(conn, quote_no) -> bool:
    return conn.execute("SELECT 1 FROM quotations WHERE quote_no=?", (quote_no,)).fetchone() is not None


def _need_parent(conn, quote_no) -> None:
    if quote_no and not _quote_exists(conn, quote_no):
        raise RB.BinError("parent_missing: 報價單 %s 不在了（可能也在暫存區）：請先還原報價單" % quote_no)


# ── 額外支出（請購單／採購單／費用單據同一張表）─────────────────────────────────────
class ExtraExpenseAdapter(RB.Adapter):
    entity_type = "extra_expense"
    label = "額外支出／請購單／採購單"
    EDITABLE = ("草稿", "已駁回")                         # 現行 DELETE 規則（case_extra_expenses.py::EDITABLE_STATUSES）

    def _row(self, conn, entity_id):
        try:
            eid = int(entity_id)
        except (TypeError, ValueError):
            return None
        return conn.execute("SELECT * FROM case_extra_expenses WHERE id=?", (eid,)).fetchone()

    def can_delete(self, conn, entity_id, user) -> Tuple[bool, str]:
        r = self._row(conn, entity_id)
        if r is None:
            return False, "找不到這筆額外支出"
        if r["status"] not in self.EDITABLE:
            return False, "「%s」狀態不可刪除（僅草稿與已駁回可刪）" % r["status"]
        return True, ""

    def can_delete_approved(self, conn, entity_id, user) -> Tuple[bool, str]:
        r = self._row(conn, entity_id)
        if r is None:
            return False, "找不到這筆額外支出"
        for it in self.impact(conn, entity_id):
            if it.get("blocking"):
                return False, it["label"]
        return True, ""

    def impact(self, conn, entity_id) -> List[dict]:
        r = self._row(conn, entity_id)
        if r is None:
            return []
        out = []
        keys = r.keys()
        if (r["paid_date"] or "").strip():
            out.append({"kind": "paid", "label": "已登錄付款（%s）：請先由最高管理員更正付款日（退回待付款）再刪除" % r["paid_date"][:10], "blocking": True})
        if "kind" in keys and (r["kind"] or "") == "purchase_req" and (r["doc_code"] or ""):
            used = [x["doc_code"] for x in conn.execute(
                "SELECT doc_code, data_json FROM case_extra_expenses WHERE quote_no=? AND kind='purchase_order' AND status NOT IN ('草稿','已駁回','已作廢')", (r["quote_no"],)).fetchall()
                if r["doc_code"] in (x["data_json"] or "")]
            if used:
                out.append({"kind": "referenced", "label": "請購單 %s 已被採購單 %s 引用：請先處理那些採購單" % (r["doc_code"], "、".join(used)), "blocking": True})
        code = (r["doc_code"] if "doc_code" in keys else "") or ""
        if code:
            qd = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (r["quote_no"],)).fetchone()
            orders = (_jload(qd["data_json"], {}).get("caseRecord") or {}).get("materialOrders") or [] if qd is not None else []
            used = [str(o.get("itemName") or o.get("itemId")) for o in orders if isinstance(o, dict) and str(o.get("poDocCode") or "").strip() == code]
            if used:
                out.append({"kind": "linked_material_orders", "label": "採購單 %s 已被材料申請對應（%s）：刪除會讓連結失效、成本口徑改變；請先處理那些材料申請" % (code, "、".join(used[:5])), "blocking": True})
        if r["status"] == "已核准":
            out.append({"kind": "approved_cost", "label": "已核准、已計入成本與報表；刪除後總帳來源事件消失（對應傳票由總帳引擎產生反向草稿）", "blocking": False})
        return out

    def snapshot(self, conn, entity_id) -> dict:
        r = self._row(conn, entity_id)
        if r is None:
            raise RB.BinError("找不到這筆額外支出")
        row = dict(r)
        label = "額外支出 #%s「%s」%s" % (row["id"], row.get("description") or "", ("（案件 %s）" % row["quote_no"]) if row.get("quote_no") else "（無案件）")
        return {"rows": {"case_extra_expenses": [row]}, "files": _files(_paths_of(row.get("files_json"), row.get("change_json"))), "label": label,
                "parent": ("quotation", row["quote_no"]) if row.get("quote_no") else None,
                "meta": {"quote_no": row.get("quote_no") or "", "status": row.get("status") or "", "codes": [c for c in (row.get("doc_code"),) if c]}}

    def delete_in_tx(self, conn, entity_id) -> None:
        r = self._row(conn, entity_id)
        rels = _paths_of(r["files_json"], r["change_json"]) if r is not None else []
        conn.execute("DELETE FROM case_extra_expenses WHERE id=?", (int(entity_id),))
        _rm_empty_dirs(rels)

    def restore_in_tx(self, conn, snap, ctx) -> dict:
        row = snap["rows"]["case_extra_expenses"][0]
        _need_parent_if_live(conn, row.get("quote_no"))
        row = _remap_json_cols(row, ctx, "files_json", "change_json")
        notes = []
        if conn.execute("SELECT 1 FROM case_extra_expenses WHERE id=?", (row["id"],)).fetchone():
            raise RB.BinError("conflict: 編號 #%s 已被占用" % row["id"])
        _insert(conn, "case_extra_expenses", row)
        return {"entity_id": str(row["id"]), "renumbered": False, "notes": notes}


def _need_parent_if_live(conn, quote_no) -> None:
    """額外支出可以沒有案件（quote_no=''）；有案件才要求報價單在（它可能在暫存區，要先還原）。"""
    if quote_no:
        _need_parent(conn, quote_no)


# ── 完工單 ──────────────────────────────────────────────────────────────────────
class CompletionNoteAdapter(RB.Adapter):
    entity_type = "completion_note"
    label = "完工單"

    def _row(self, conn, entity_id):
        return conn.execute("SELECT * FROM completion_notes WHERE note_no=?", (str(entity_id),)).fetchone()

    def can_delete(self, conn, entity_id, user) -> Tuple[bool, str]:
        r = self._row(conn, entity_id)
        if r is None:
            return False, "完工單不存在"
        return (True, "") if r["status"] == "草稿" else (False, "僅草稿狀態可刪除")

    def can_delete_approved(self, conn, entity_id, user) -> Tuple[bool, str]:
        r = self._row(conn, entity_id)
        if r is None:
            return False, "完工單不存在"
        for it in self.impact(conn, entity_id):
            if it.get("blocking"):
                return False, it["label"]
        return True, ""

    def impact(self, conn, entity_id) -> List[dict]:
        r = self._row(conn, entity_id)
        if r is None:
            return []
        out = []
        if r["is_signed"]:
            out.append({"kind": "signed_back", "label": "客戶已回簽（%s）；回簽檔會一併進暫存區" % (r["signed_at"] or "")[:10], "blocking": False})
        if r["status"] in ("已核准", "已完成") or (r["completion_date"] or ""):
            out.append({"kind": "warranty", "label": "完工日 %s：保固起算與工期以它為準，刪除後案件頁不再有這張完工單" % ((r["completion_date"] or "")[:10] or "—"), "blocking": False})
        return out

    def snapshot(self, conn, entity_id) -> dict:
        r = self._row(conn, entity_id)
        if r is None:
            raise RB.BinError("完工單不存在")
        row = dict(r)
        return {"rows": {"completion_notes": [row]}, "files": _files(_paths_of(row.get("signed_files_json"), row.get("data_json"))),
                "label": "完工單 %s（%s）" % (row["note_no"], row.get("customer_name") or ""), "parent": ("quotation", row["quote_no"]) if row.get("quote_no") else None,
                "meta": {"quote_no": row.get("quote_no") or "", "status": row.get("status") or "", "codes": [row["note_no"]]}}

    def delete_in_tx(self, conn, entity_id) -> None:
        r = self._row(conn, entity_id)
        rels = _paths_of(r["signed_files_json"], r["data_json"]) if r is not None else []
        conn.execute("DELETE FROM completion_notes WHERE note_no=?", (str(entity_id),))
        _rm_empty_dirs(rels)

    def restore_in_tx(self, conn, snap, ctx) -> dict:
        row = snap["rows"]["completion_notes"][0]
        _need_parent_if_live(conn, row.get("quote_no"))
        if self._row(conn, row["note_no"]) is not None:
            raise RB.BinError("conflict: 完工單號 %s 已被占用" % row["note_no"])
        _insert(conn, "completion_notes", _remap_json_cols(row, ctx, "signed_files_json", "data_json"), drop_id=_id_taken(conn, "completion_notes", row))
        return {"entity_id": row["note_no"], "renumbered": False, "notes": []}


def _id_taken(conn, table, row) -> bool:
    """列的整數主鍵 `id` 已被別的列用掉（本表非 AUTOINCREMENT 時可能被重用）⇒ 還原時改配新 id（其他欄位不變）。"""
    return "id" in row and conn.execute("SELECT 1 FROM %s WHERE id=?" % table, (row["id"],)).fetchone() is not None


# ── 報價單（連同它名下的階段／拜訪／進度更新／行動事項）──────────────────────────────────
#: 報價單被刪時『隨它走』的名下資料（目前的硬刪只刪 quotations 一列、這些成了孤兒；進暫存區後一起搬走、一起還原）
_OWNED = (("case_stages", "quote_no"), ("case_updates", "quote_no"), ("case_action_items", "quote_no"))
#: 其他『單獨存在的單據』：報價單被刪時**不連帶刪**；『刪除已核可』時只要還有就明確拒絕（要先處理那些單據）
_DEPENDENTS = (("case_extra_expenses", "額外支出／請購單／採購單"), ("completion_notes", "完工單"), ("shipping_notes", "出貨單"), ("contractor_dispatches", "承攬商派發"),
               ("payment_requests", "請款單"), ("invoice_vouchers", "收款憑據"), ("contractor_payment_vouchers", "承攬商匯款申請"), ("bonus_case_awards", "獎金分潤"),
               ("case_change_requests", "變更申請"), ("case_material_approvals", "材料申請審核"), ("case_material_payments", "材料匯款申請"),
               ("case_material_changes", "材料申請變更申請"), ("stock_items", "已出貨的庫存序號"))
#: 上面某些表只算『特定狀態』的列（stock_items 只有 shipped 才是下游紀錄）
_DEPENDENT_WHERE = {"stock_items": " AND status='shipped'"}


class QuotationAdapter(RB.Adapter):
    entity_type = "quotation"
    label = "報價單／案件"

    def _row(self, conn, entity_id):
        return conn.execute("SELECT * FROM quotations WHERE quote_no=?", (str(entity_id),)).fetchone()

    def can_delete(self, conn, entity_id, user) -> Tuple[bool, str]:
        r = self._row(conn, entity_id)
        if r is None:
            return False, "報價單 %s 不存在" % entity_id
        return (True, "") if r["status"] == "草稿" else (False, "只有草稿狀態的報價單可以刪除（目前狀態：%s）" % r["status"])

    def _dependents(self, conn, quote_no) -> List[Tuple[str, int]]:
        out = []
        for table, label in _DEPENDENTS:
            try:
                n = conn.execute("SELECT COUNT(*) FROM %s WHERE quote_no=?%s" % (table, _DEPENDENT_WHERE.get(table, "")), (quote_no,)).fetchone()[0]
            except sqlite3.OperationalError:                   # 該表不存在（模組未裝）＝沒有
                continue
            if n:
                out.append((label, n))
        return out

    def can_delete_approved(self, conn, entity_id, user) -> Tuple[bool, str]:
        r = self._row(conn, entity_id)
        if r is None:
            return False, "報價單 %s 不存在" % entity_id
        dep = self._dependents(conn, str(entity_id))
        if dep:
            return False, "這個案件底下還有其他單據，不連帶刪除（請先逐張處理）：" + "、".join("%s %d 張" % d for d in dep)
        if (r["deal_tag"] or "") == "已結案" or (r["settle_status"] or "") == "finalized":
            return False, "已結案（精算已定稿）的案件不能刪除"
        return True, ""

    def impact(self, conn, entity_id) -> List[dict]:
        r = self._row(conn, entity_id)
        if r is None:
            return []
        out = []
        if r["is_signed"]:
            out.append({"kind": "signed_back", "label": "客戶已回簽；回簽檔會一併進暫存區", "blocking": False})
        for label, n in self._dependents(conn, str(entity_id)):
            out.append({"kind": "dependents", "label": "底下還有 %s %d 張（不連帶刪除；刪除已核可會被拒絕）" % (label, n), "blocking": True})
        if (r["deal_tag"] or "") == "已結案" or (r["settle_status"] or "") == "finalized":
            out.append({"kind": "settled", "label": "已結案（精算已定稿）", "blocking": True})
        if (r["deal_tag"] or "") == "已成案":
            out.append({"kind": "deal", "label": "已成案：案件頁、報表與業績都會少這張", "blocking": False})
        return out

    def snapshot(self, conn, entity_id) -> dict:
        r = self._row(conn, entity_id)
        if r is None:
            raise RB.BinError("報價單 %s 不存在" % entity_id)
        qn = str(entity_id)
        row = dict(r)
        rows = {"quotations": [row]}
        stages = _rows(conn, "case_stages", "quote_no=?", (qn,))
        rows["case_stages"] = stages
        ids = [s["id"] for s in stages]
        rows["case_stage_visits"] = _rows(conn, "case_stage_visits", "stage_id IN (%s)" % ",".join("?" * len(ids)), ids) if ids else []
        for table, col in _OWNED[1:]:
            try:
                rows[table] = _rows(conn, table, "%s=?" % col, (qn,))
            except sqlite3.OperationalError:
                rows[table] = []
        rels = _paths_of(row.get("signed_files_json"), row.get("data_json"))
        for u in rows["case_updates"]:
            rels += _paths_of(u.get("files_json"))
        seen, files = set(), []
        for p in rels:
            if p not in seen:
                seen.add(p)
                files.append(p)
        return {"rows": rows, "files": _files(files), "label": "報價單 %s（%s）" % (qn, row.get("customer_name") or ""), "parent": None,
                "meta": {"status": row.get("status") or "", "crm_unlink": "業務開發案件的轉建連結不會自動恢復", "codes": [qn]}}

    def delete_in_tx(self, conn, entity_id) -> None:
        qn = str(entity_id)
        rels = [f["rel"] for f in (self.snapshot(conn, qn)["files"] if self._row(conn, qn) is not None else [])]
        ids = [r[0] for r in conn.execute("SELECT id FROM case_stages WHERE quote_no=?", (qn,)).fetchall()]
        if ids:
            conn.execute("DELETE FROM case_stage_visits WHERE stage_id IN (%s)" % ",".join("?" * len(ids)), ids)
        for table, col in _OWNED:
            try:
                conn.execute("DELETE FROM %s WHERE %s=?" % (table, col), (qn,))
            except sqlite3.OperationalError:
                pass
        conn.execute("DELETE FROM quotations WHERE quote_no=?", (qn,))
        _rm_empty_dirs(rels)

    def restore_in_tx(self, conn, snap, ctx) -> dict:
        rows = snap["rows"]
        q = rows["quotations"][0]
        qn = q["quote_no"]
        notes = ["業務開發案件的轉建連結沒有自動恢復（若有，請到業務開發頁重新連結）"]
        renumbered = False
        if self._row(conn, qn) is not None:
            # 單號被占用：只有『草稿』可以改用新單號還原（還沒對外發出）；已核准／已成案的單號可能已寄給客戶或寫進別處，不改號、不覆蓋 ⇒ 衝突
            if (q.get("status") or "") != "草稿":
                raise RB.BinError("conflict: 報價單號 %s 已被占用，且這張不是草稿，不能改號還原（請先處理現有那張）" % qn)
            new_qn = _next_quote_no(conn)
            q = dict(q, quote_no=new_qn)
            q["data_json"] = _renumber_json(q.get("data_json"), qn, new_qn)
            for table in ("case_stages", "case_updates", "case_action_items"):
                rows[table] = [dict(r, quote_no=new_qn) for r in rows.get(table, [])]
            notes.insert(0, "原單號 %s 已被占用，這張草稿改用新單號 %s 還原" % (qn, new_qn))
            qn, renumbered = new_qn, True
        _insert(conn, "quotations", _remap_json_cols(q, ctx, "signed_files_json", "data_json"), drop_id=_id_taken(conn, "quotations", q))
        idmap = {}
        for s in rows.get("case_stages", []):
            new = _insert(conn, "case_stages", s, drop_id=_id_taken(conn, "case_stages", s))
            idmap[s["id"]] = new
        for v in rows.get("case_stage_visits", []):
            v = dict(v)
            v["stage_id"] = idmap.get(v["stage_id"], v["stage_id"])
            _insert(conn, "case_stage_visits", v, drop_id=_id_taken(conn, "case_stage_visits", v))
        for table in ("case_updates", "case_action_items"):
            for r in rows.get(table, []):
                _insert(conn, table, _remap_json_cols(r, ctx, "files_json"), drop_id=_id_taken(conn, table, r))
        return {"entity_id": qn, "renumbered": renumbered, "notes": notes}


# ── 材料申請（quotations.data_json 的 materialOrders 一列＋審核疊加列）─────────────────────────
def _split_mid(entity_id):
    quote_no, _, item_id = str(entity_id).partition("|")
    return quote_no, item_id


class MaterialOrderAdapter(RB.Adapter):
    """`entity_id` ＝ `<報價單號>|<材料申請 itemId>`。材料申請沒有自己的資料表：本體是報價單 JSON 裡的一列，審核狀態在 `case_material_approvals`。"""
    entity_type = "material_order"
    label = "材料申請"
    DELETABLE = ("草稿", "已退回")                         # 現行規則（material_guard 的『被刪掉的列』）：草稿／已退回連審核單一起刪

    def _approval(self, conn, qn, iid):
        try:
            return conn.execute("SELECT * FROM case_material_approvals WHERE quote_no=? AND item_id=?", (qn, iid)).fetchone()
        except sqlite3.OperationalError:
            return None

    def _order_of(self, conn, qn, iid):
        r = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (qn,)).fetchone()
        if r is None:
            return None
        cr = (_jload(r["data_json"], {}).get("caseRecord") or {})
        for o in (cr.get("materialOrders") or []):
            if isinstance(o, dict) and str(o.get("itemId")) == iid:
                return o
        return None

    def _has_payments(self, conn, qn, iid) -> bool:
        try:
            return conn.execute("SELECT 1 FROM case_material_payments WHERE quote_no=? AND item_id=? LIMIT 1", (qn, iid)).fetchone() is not None
        except sqlite3.OperationalError:
            return False

    def can_delete(self, conn, entity_id, user) -> Tuple[bool, str]:
        qn, iid = _split_mid(entity_id)
        if self._order_of(conn, qn, iid) is None:
            return False, "找不到這筆材料申請"
        if self._has_payments(conn, qn, iid):
            return False, "這張材料申請有匯款申請紀錄，不可刪除"
        a = self._approval(conn, qn, iid)
        st = a["status"] if a is not None else ""
        if a is not None and st not in self.DELETABLE:
            return False, "審核中或已核准的材料申請不可刪除（請先撤回，或改用取消）"
        return True, ""

    def can_delete_approved(self, conn, entity_id, user) -> Tuple[bool, str]:
        qn, iid = _split_mid(entity_id)
        if self._order_of(conn, qn, iid) is None:
            return False, "找不到這筆材料申請"
        for it in self.impact(conn, entity_id):
            if it.get("blocking"):
                return False, it["label"]
        a = self._approval(conn, qn, iid)
        if a is not None and a["status"] in ("待審核", "簽核中"):
            return False, "簽核中的材料申請請先撤回，再刪除"
        return True, ""

    def impact(self, conn, entity_id) -> List[dict]:
        qn, iid = _split_mid(entity_id)
        out = []
        if self._has_payments(conn, qn, iid):
            out.append({"kind": "paid", "label": "有匯款申請紀錄（含已付款／作廢）：紀錄要留，請先處理匯款申請，不能刪除", "blocking": True})
        r = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (qn,)).fetchone()
        if r is not None:
            cr = _jload(r["data_json"], {}).get("caseRecord") or {}
            linked = [m for m in (cr.get("materials") or []) if isinstance(m, dict) and str(m.get("orderItemId") or "") == iid]
            if linked:
                out.append({"kind": "linked_materials", "label": "有 %d 筆材料清單項目對應到這張材料申請（刪除後連結會失效，已申購／已到料的勾選仍留著）" % len(linked), "blocking": False})
        a = self._approval(conn, qn, iid)
        if a is not None and a["status"] == "已核准":
            out.append({"kind": "approved", "label": "已核准的材料申請（%s）" % (a["doc_code"] or "—"), "blocking": False})
        return out

    def snapshot(self, conn, entity_id) -> dict:
        qn, iid = _split_mid(entity_id)
        order = self._order_of(conn, qn, iid)
        if order is None:
            raise RB.BinError("找不到這筆材料申請")
        a = self._approval(conn, qn, iid)
        rows = {"case_material_approvals": [dict(a)] if a is not None else []}
        # files 刻意為空：材料申請這一列本身沒有附件（附件在材料清單與匯款申請上）；若附件先搬進隔離區而存檔隨後中止，列還在、檔卻要等每小時 reconcile 才搬回
        return {"rows": rows, "order": order, "files": [], "label": "材料申請 %s「%s」（案件 %s）" % ((a["doc_code"] if a is not None and a["doc_code"] else iid), order.get("itemName") or "", qn),
                "parent": ("quotation", qn), "meta": {"quote_no": qn, "item_id": iid, "status": a["status"] if a is not None else "",
                                                 "codes": [a["doc_code"]] if a is not None and a["doc_code"] else []}}

    def delete_in_tx(self, conn, entity_id) -> None:
        qn, iid = _split_mid(entity_id)
        conn.execute("DELETE FROM case_material_approvals WHERE quote_no=? AND item_id=?", (qn, iid))
        # 本體（報價單 JSON 的那一列）：存檔流程之內呼叫時，存檔自己就會把它拿掉（這裡再拿一次是冪等的）；『刪除已核可』直接呼叫時由這裡拿掉
        r = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (qn,)).fetchone()
        if r is None:
            return
        data = _jload(r["data_json"], {})
        cr = data.get("caseRecord")
        if isinstance(cr, dict) and isinstance(cr.get("materialOrders"), list):
            kept = [o for o in cr["materialOrders"] if not (isinstance(o, dict) and str(o.get("itemId")) == iid)]
            if len(kept) != len(cr["materialOrders"]):
                cr["materialOrders"] = kept
                # updated_at 要跟著動：存檔流程之外（刪除已核可、還原）改了 JSON，舊畫面的 _expectedUpdatedAt 才會對不上而得到 409（否則舊畫面存檔會把這一列救活／再丟進暫存區）
                conn.execute("UPDATE quotations SET data_json=?, updated_at=? WHERE quote_no=?", (json.dumps(data, ensure_ascii=False), datetime.now().isoformat(), qn))

    def restore_in_tx(self, conn, snap, ctx) -> dict:
        meta = snap.get("meta") or {}
        qn, iid = meta.get("quote_no", ""), str(meta.get("item_id", ""))
        r = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (qn,)).fetchone()
        if r is None:
            raise RB.BinError("parent_missing: 報價單 %s 不在了（可能也在暫存區）：請先還原報價單" % qn)
        data = _jload(r["data_json"], {})
        cr = data.setdefault("caseRecord", {}) if isinstance(data.get("caseRecord", {}), dict) else None
        if cr is None:
            raise RB.BinError("conflict: 這張報價單的案件資料格式不對，無法放回材料申請")
        orders = cr.setdefault("materialOrders", [])
        if any(isinstance(o, dict) and str(o.get("itemId")) == iid for o in orders):
            raise RB.BinError("conflict: 材料申請編號 %s 已存在於這張報價單" % iid)
        a_rows = (snap.get("rows") or {}).get("case_material_approvals") or []
        for a in a_rows:
            if self._approval(conn, qn, iid) is not None:
                raise RB.BinError("conflict: 這筆材料申請的審核單已存在")
            _insert(conn, "case_material_approvals", a)
        orders.append(_remap_paths(snap["order"], ctx))
        conn.execute("UPDATE quotations SET data_json=?, updated_at=? WHERE quote_no=?", (json.dumps(data, ensure_ascii=False), datetime.now().isoformat(), qn))
        return {"entity_id": "%s|%s" % (qn, iid), "renumbered": False, "notes": ["材料清單裡原本對應到它的項目，連結需到案件頁重新確認"]}


def _renumber_json(raw, old, new):
    """報價單 data_json 裡自帶的單號欄位跟著換（找得到才換；其餘內容不動）。"""
    try:
        d = json.loads(raw) if isinstance(raw, str) and raw else None
    except ValueError:
        return raw
    if isinstance(d, dict) and d.get("quoteNo") == old:
        d["quoteNo"] = new
        return json.dumps(d, ensure_ascii=False)
    return raw


def _next_quote_no(conn) -> str:
    """改號還原用：取下一個可用的報價單號並登記進 quote_seq（與建立報價單同一條規則；暫存區裡的號碼不重發）。"""
    from modules.case.api.quotations import _peek_next_no
    month = datetime.now().strftime("%Y%m")
    conn.execute("INSERT INTO quote_seq (month, seq) VALUES (?, 0) ON CONFLICT(month) DO NOTHING", (month,))
    qn = _peek_next_no(conn, month)
    conn.execute("INSERT INTO quote_seq (month, seq) VALUES (?, ?) ON CONFLICT(month) DO UPDATE SET seq=MAX(seq, excluded.seq)", (month, int(qn.split("-")[-1])))
    return qn


def legacy_delete_quotation(conn, quote_no) -> None:
    """暫存區模組不在時的舊行為：只刪報價單本體那一列（名下資料維持原樣成孤兒，與暫存區上線前相同）。"""
    conn.execute("DELETE FROM quotations WHERE quote_no=?", (str(quote_no),))


def adapters() -> dict:
    """`{entity_type: Adapter 類別}`——module 的 ModuleSpec.providers 用。"""
    return {a.entity_type: a for a in (QuotationAdapter, ExtraExpenseAdapter, CompletionNoteAdapter, MaterialOrderAdapter)}
