# -*- coding: utf-8 -*-
"""M07 薪資獎金的刪除暫存區 adapter（第 53 班 P1；IP-RB1，契約 `helpers/recycle_bin.py`）：勞報單。

- 一般刪除：沿用現行規則——`_LOCKED_STATUSES`（待審核／已核准／已匯出／已簽回／已付款／已作廢）一律不可刪（須保留備查）；
  只有草稿（與退回後的未鎖定狀態）進暫存區。
- 『刪除已核可』：**不開放**（已核准之後的勞報單牽涉出納待付款、總帳 E06、簽回檔、獎金／匯款連結；要撤銷請走『作廢』）。
  影響清單仍可查（資訊用）。
- 快照：勞報單本體 + `payslip_dispatch_links` 連結列；沒有附件（簽回檔／匯出存檔只在鎖定狀態才出現）。
  列表／詳情用預設 `mask()`（L1 `mask_obj` 會展開 JSON 字串再遮罩銀行帳號等）；還原用原文。
- 還原：單號被占用 ⇒ `conflict:`；受領人（外包名冊）不在 ⇒ `parent_missing:`；`contractor_guess_id` 指向的人不在 ⇒ 清成 NULL 並註記
  （推測值，不擋還原）；派發已不存在的連結 ⇒ 略過並註記；`contractor_guess_id` 與 `contractor_id` 分開還原，不互相升格。
本檔只 import L1 契約 `helpers.recycle_bin`，不 import `modules.recyclebin`。
"""
import json

from core import registry
from helpers import recycle_bin as RB

_TABLE = "payslips"
_LINKS = "payslip_dispatch_links"
_NOTICE_TYPES = ("payslip_submitted", "payslip_next_tier", "payslip_approved", "payslip_returned", "payslip_payable", "payslip_paid", "approval_reminder")


def _locked():
    from modules.payroll.api.payslips import _LOCKED_STATUSES      # 晚綁定：與端點用同一份常數（避免兩處各改一半）
    return _LOCKED_STATUSES


def _cols(conn, table):
    return [r[1] for r in conn.execute("PRAGMA table_info(%s)" % table).fetchall()]


def _insert(conn, table, row):
    cols = set(_cols(conn, table))
    row = {k: v for k, v in row.items() if k in cols}
    if "id" in row and conn.execute("SELECT 1 FROM %s WHERE id=?" % table, (row["id"],)).fetchone():
        row.pop("id")                                              # id 被占用 ⇒ 另給（單號才是對外的鍵）
    names = list(row)
    conn.execute("INSERT INTO %s (%s) VALUES (%s)" % (table, ",".join(names), ",".join("?" * len(names))), [row[n] for n in names])


class PayslipBinAdapter(RB.Adapter):
    entity_type = "payslip"
    label = "勞報單"

    def _status(self, conn, slip_no):
        r = conn.execute("SELECT status FROM payslips WHERE slip_no=?", (slip_no,)).fetchone()
        return None if r is None else r["status"]

    def can_delete(self, conn, entity_id, user):
        st = self._status(conn, entity_id)
        if st is None:
            return False, "找不到此勞報單"
        if st in _locked():
            return False, "%s的勞報單須保留備查，不可刪除" % st
        return True, ""

    def can_delete_approved(self, conn, entity_id, user):
        st = self._status(conn, entity_id)
        if st is None:
            return False, "找不到此勞報單"
        if st not in _locked():
            return False, "未鎖定的勞報單請用一般刪除"
        return False, "已核准之後的勞報單須保留備查，不開放『刪除已核可』；要撤銷請使用『作廢』"

    def impact(self, conn, entity_id):
        r = conn.execute("SELECT status, planned_pay_date, payment_date, signed_files_json, export_count FROM payslips WHERE slip_no=?", (entity_id,)).fetchone()
        if r is None:
            return []
        out = []
        if r["status"] in ("已付款",) or (r["payment_date"] or ""):
            out.append({"kind": "paid", "label": "已付款（付款日 %s）" % (r["payment_date"] or "—"), "blocking": True})
        if r["status"] == "已簽回" or _json_list(r["signed_files_json"]):
            out.append({"kind": "signed_back", "label": "已有簽回檔", "blocking": True})
        if (r["export_count"] or 0) > 0:
            out.append({"kind": "exported", "label": "已匯出 %d 次" % r["export_count"], "blocking": True})
        n = conn.execute("SELECT COUNT(*) FROM payslip_dispatch_links WHERE slip_no=?", (entity_id,)).fetchone()[0]
        if n:
            out.append({"kind": "dispatch_links", "label": "已連結 %d 筆派發" % n, "blocking": False})
        if r["status"] in _locked():
            out.append({"kind": "locked", "label": "狀態「%s」須保留備查，不可刪除" % r["status"], "blocking": True})
        return out

    def snapshot(self, conn, entity_id):
        r = conn.execute("SELECT * FROM payslips WHERE slip_no=?", (entity_id,)).fetchone()
        if r is None:
            raise RB.BinError("找不到此勞報單")
        links = [{k: l[k] for k in l.keys()} for l in conn.execute("SELECT * FROM payslip_dispatch_links WHERE slip_no=? ORDER BY id", (entity_id,)).fetchall()]
        return {"rows": {_TABLE: [{k: r[k] for k in r.keys()}], _LINKS: links}, "files": [], "label": "勞報單 %s" % entity_id,
                "parent": None, "meta": {"status": r["status"], "key": entity_id}}

    def delete_in_tx(self, conn, entity_id):
        placeholders = ",".join("?" * len(_locked()))
        conn.execute("DELETE FROM payslip_dispatch_links WHERE slip_no=?", (entity_id,))
        cur = conn.execute("DELETE FROM payslips WHERE slip_no=? AND status NOT IN (%s)" % placeholders, (entity_id, *_locked()))
        if cur.rowcount != 1:                                      # 防禦（同端點原本的條件式刪除）：狀態剛被改 ⇒ 整個動作回滾
            raise RB.BinError("勞報單狀態剛被改變，請重新整理後再試")
        # 退回後回到草稿的單可能還留著『已送審／已退回』通知（指向剛刪掉的單號）⇒ 同一個交易內清掉
        conn.execute("DELETE FROM notifications WHERE ref_id=? AND type IN (%s)" % ",".join("?" * len(_NOTICE_TYPES)), [str(entity_id), *_NOTICE_TYPES])

    def restore_in_tx(self, conn, snap, ctx):
        rows = (snap.get("rows") or {}).get(_TABLE) or []
        if len(rows) != 1:
            raise RB.BinError("快照內容不完整（找不到勞報單本體）")
        row = dict(rows[0])
        slip_no = row["slip_no"]
        if conn.execute("SELECT 1 FROM payslips WHERE slip_no=?", (slip_no,)).fetchone():
            raise RB.BinError("conflict: 勞報單號 %s 已被占用，不覆蓋" % slip_no)
        notes = []
        has_roster = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='contractors'").fetchone() is not None
        cid = row.get("contractor_id")
        if cid is not None and has_roster and conn.execute("SELECT 1 FROM contractors WHERE id=?", (cid,)).fetchone() is None:
            raise RB.BinError("parent_missing: 受領人（外包名冊 #%s）已不存在，無法還原" % cid)
        gid = row.get("contractor_guess_id")
        if gid is not None and has_roster and conn.execute("SELECT 1 FROM contractors WHERE id=?", (gid,)).fetchone() is None:
            row["contractor_guess_id"] = None                      # 推測值指向的人不在 ⇒ 清掉（推測不是權威資料）；不會升格成 contractor_id
            notes.append("推測的受領人（外包名冊 #%s）已不存在，已清除推測" % gid)
        _insert(conn, _TABLE, row)
        brief = registry.single_provider("dispatch.brief")
        kept = skipped = 0
        for l in (snap.get("rows") or {}).get(_LINKS) or []:
            if brief is not None and brief(conn, l.get("dispatch_id")) is None:
                skipped += 1
                continue
            _insert(conn, _LINKS, dict(l, slip_no=slip_no))
            kept += 1
        if skipped:
            notes.append("%d 筆派發連結因派發已不存在而略過" % skipped)
        return {"entity_id": slip_no, "renumbered": False, "notes": notes}


def _json_list(raw):
    try:
        v = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return v if isinstance(v, list) else []
