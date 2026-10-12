# -*- coding: utf-8 -*-
"""擇一方案的回簽選定與取消回簽（M3 T9；T57）。端點 `toggle_quotation_signed` 只剩呼叫點，規則都在這裡。

不變式（寫死）：
- H1 一律以**已存列**為準，不信用戶端旗標；picks 驗證對象是資料庫讀出的品項。
- H2 任何清除都在**同一個寫交易**內：清 is_signed／signed_by／signed_at＋altPicks（含 altPickedAt／altPickedBy）＋tot 回暫估＋SQL 四欄＋寫稽核（含被清除的內容與前後金額）；全部或全無。
- H5 只有『擇一方案已啟用（`totalsByAlt` 為 true）且有擇一組別』或『已存有 altPicks』的單才走這裡；其他單完全維持今日行為。
- H8 所有清除路徑走同一函式 `clear_signed_selection`；守門鏈固定順序 P8（已精算）→ P7（未匯出的開票單／請款單）→ P6（已匯出）→ P2（已成案）。
  每層是不是擋下由設定中心群組 `quote_alt` 的政策決定（`alt_policy.policy`）；預設一律擋下（409）。
- 讀 arap 表遵守 L1 直讀規則：arap 沒載入、缺表或 OperationalError ⇒ 視為沒有下游單據，**絕不 500、也絕不造成永久 409**。
  『有效單據』＝狀態不是草稿的開票單／請款單（草稿尚未開立，可直接刪除）；不寫死核准狀態集合。
- 本檔的 `recompute_tot` 永遠在伺服器端重算 tot（不論管銷口徑是 legacy 或 v2）：回簽／取消回簽不能只靠用戶端送來的金額。"""
import json
import sqlite3

from fastapi import HTTPException

from modules.case import alt_lock, alt_options, alt_policy
from modules.case import profit_guard as PG

#: 取消回簽允許的單據狀態（沒有進行中的簽核）；待審核／簽核中一律 409（H4）
UNSIGN_STATES = ("已送出", "草稿", "已取消", "已拒絕")
IN_APPROVAL_MSG = "簽核中，請先收回或退回，再取消回簽"
MSG_P8 = "已精算，請先重開精算再取消回簽"
MSG_P7 = "已開票／已請款，請先撤回該單據再取消回簽"
MSG_P6 = "已開立並匯出的憑據／請款單，方案選定不能再更改；如需更正，請財務先作廢該憑據"
MSG_P2 = "案件已成案，請先把案件改回未成案再取消回簽"
WARN_P2 = "下游金額可能與報價不一致，請確認開票、請款與採購金額"
NEED_PICK_MSG = "請先選擇客戶採用的方案"


def applies(data: dict) -> bool:
    """H5：這張單適用擇一回簽規則。"""
    if not isinstance(data, dict):
        return False
    if isinstance(data.get("altPicks"), dict) and data["altPicks"]:
        return True
    return PG.alt_active(data) and bool(PG.alt_groups(data))


def validate_picks(data: dict, picks) -> dict:
    """回簽選定（422，白話）：涵蓋全部擇一組別、每組一個且屬於該組；驗證對象是已存品項。"""
    groups = PG.alt_groups(data)
    if not isinstance(picks, dict):
        raise HTTPException(422, NEED_PICK_MSG)
    norm = {str(k).strip(): ("" if v is None else str(v)) for k, v in picks.items()}
    if any(not v for v in norm.values()) or any(g not in norm for g in groups):
        raise HTTPException(422, NEED_PICK_MSG)
    for g, v in norm.items():
        if g not in groups:
            raise HTTPException(422, "客戶選定的方案與報價單品項不一致")
        if not any(str(m.get("id")) == v for m in groups[g]):
            raise HTTPException(422, "客戶選定的方案與報價單品項不一致")
    return {g: norm[g] for g in groups}


def recompute_tot(data: dict) -> dict:
    """依目前選定重算 tot（沿用單上的口徑與比率戳記，只換基數；H6）。就地改 data['tot']，回傳 tot。"""
    tot = dict(data.get("tot") if isinstance(data.get("tot"), dict) else {})
    pct, ver, basis = alt_options.stamps(dict(data, tot=tot), settled=True)
    t = PG.server_totals(data, tot)
    tot.update(t)
    tot.update(PG.server_profit(data, pct, ver, pretax=t["pretax"], total=t["total"], charity_basis=basis))
    data["tot"] = tot
    return tot


def _audit_in_txn(conn, user: dict, action: str, quote_no: str, label: str, detail: dict, now: str):
    """稽核與狀態變更同一交易（H2）：中途失敗一起回滾。"""
    conn.execute(
        "INSERT INTO audit_log (at, username, display_name, action, target_type, target_id, target_label, detail) VALUES (?,?,?,?,?,?,?,?)",
        (now, user.get("username", ""), user.get("display_name") or user.get("username", ""), action, "quotation", quote_no, label,
         json.dumps(detail, ensure_ascii=False)))


def _sql_cols(tot: dict):
    return (tot.get("total", 0), tot.get("pretax", 0), tot.get("directMarginPct", 0), tot.get("netMarginPct", 0))


def _arap_counts(conn, quote_no: str):
    """(未匯出的有效單據數, 已匯出的有效單據數)。arap 沒載入／缺表／OperationalError ⇒ (0, 0)。"""
    try:
        from core import registry
        if not registry.is_loaded("arap"):
            return 0, 0
        unexported = exported = 0
        for table in ("invoice_vouchers", "payment_requests"):
            rows = conn.execute("SELECT COALESCE(export_count,0) AS n FROM %s WHERE quote_no=? AND COALESCE(status,'') NOT IN ('草稿','')" % table,
                                (quote_no,)).fetchall()
            for r in rows:
                if (r["n"] or 0) > 0:
                    exported += 1
                else:
                    unexported += 1
        return unexported, exported
    except sqlite3.OperationalError:
        return 0, 0


def check_downstream(conn, quote_no: str, row, data: dict) -> list:
    """守門鏈（H3／H8）：P8 → P7 → P6 → P2。被擋 ⇒ 409（白話）；通過回提醒文字清單（可能為空）。"""
    warnings = []
    if PG.is_settled(row) and alt_policy.policy("cancel_after_settle") == 1:
        raise HTTPException(409, MSG_P8)
    unexported, exported = _arap_counts(conn, quote_no)
    if unexported and alt_policy.policy("cancel_after_invoice") == 1:
        raise HTTPException(409, MSG_P7)
    if exported and alt_policy.policy("cancel_after_export") == 1:
        raise HTTPException(409, MSG_P6)
    deal = (row["deal_tag"] or "") or str(data.get("dealTag") or "")
    if deal == "已成案":
        if alt_policy.policy("cancel_after_deal") == 1:
            raise HTTPException(409, MSG_P2)
        warnings.append(WARN_P2)               # 3：允許，只提醒
    return warnings


def sign(conn, quote_no: str, row, data: dict, picks, user: dict, signed_log: list, now: str) -> dict:
    """回簽並寫入選定（呼叫端已在寫交易內，且 row／data 是鎖內讀出的已存值）。"""
    if PG.is_settled(row):
        raise HTTPException(409, "已精算或已結案的報價單，不能再回簽擇一方案")
    chosen = validate_picks(data, picks)
    old_tot = data.get("tot") if isinstance(data.get("tot"), dict) else {}
    before = {"total": old_tot.get("total"), "pretax": old_tot.get("pretax")}
    who = user.get("display_name") or user["username"]
    data["altPicks"], data["altPickedAt"], data["altPickedBy"] = chosen, now, who
    tot = recompute_tot(data)
    conn.execute(
        "UPDATE quotations SET is_signed=1, signed_by=?, signed_at=?, signed_log=?, data_json=?, total=?, pretax=?, direct_margin_pct=?, net_margin_pct=?, updated_at=? WHERE quote_no=?",
        (who, now, json.dumps(signed_log, ensure_ascii=False), json.dumps(data, ensure_ascii=False)) + _sql_cols(tot) + (now, quote_no))
    groups = PG.alt_groups(data)
    picked = {g: next((m.get("description") or str(m.get("id")) for m in groups[g] if str(m.get("id")) == v), v) for g, v in chosen.items()}
    after = {"total": tot.get("total"), "pretax": tot.get("pretax")}
    _audit_in_txn(conn, user, "quotation.sign_alt", quote_no, "%s 回簽並選定擇一方案" % quote_no,
                  {"picks": chosen, "picked": picked, "before": before, "after": after}, now)
    return {"picks": chosen, "tot": after}


def clear_signed_selection(conn, quote_no: str, user: dict, now: str, reason: str, signed_log: list = None) -> dict:
    """**唯一的清除入口**（H8）：取消回簽、以及日後任何會清除選定的路徑都呼叫它。呼叫端已在寫交易內。
    讀已存列 → 守門鏈（可能 409）→ 清 is_signed／altPicks／tot 回暫估／SQL 四欄 → 稽核（記錄被清除的內容與前後金額）。回 `{cleared, warnings, tot}`。"""
    row = conn.execute("SELECT status, is_signed, signed_log, deal_tag, settle_status, data_json, total, pretax FROM quotations WHERE quote_no=?",
                       (quote_no,)).fetchone()
    if not row:
        raise HTTPException(404, "報價單不存在")
    try:
        data = json.loads(row["data_json"] or "{}") or {}
    except (TypeError, ValueError):
        raise HTTPException(409, "報價單資料無法解析")
    warnings = check_downstream(conn, quote_no, row, data)
    cleared = dict(data.get("altPicks")) if isinstance(data.get("altPicks"), dict) else {}
    before = {"total": row["total"], "pretax": row["pretax"]}
    for k in PG.ALT_SERVER_KEYS:
        data.pop(k, None)
    tot = recompute_tot(data)
    log = signed_log if signed_log is not None else json.loads(row["signed_log"] or "[]")
    conn.execute(
        "UPDATE quotations SET is_signed=0, signed_by='', signed_at='', signed_log=?, data_json=?, total=?, pretax=?, direct_margin_pct=?, net_margin_pct=?, updated_at=? WHERE quote_no=?",
        (json.dumps(log, ensure_ascii=False), json.dumps(data, ensure_ascii=False)) + _sql_cols(tot) + (now, quote_no))
    after = {"total": tot.get("total"), "pretax": tot.get("pretax")}
    _audit_in_txn(conn, user, "quotation.unsign_alt", quote_no, "%s 取消回簽，清除擇一選定" % quote_no,
                  {"reason": reason, "cleared": cleared, "before": before, "after": after, "warnings": warnings}, now)
    return {"cleared": cleared, "warnings": warnings, "tot": after}


def guard_update(new: dict, old: dict, is_unlock_edit: bool) -> None:
    """整份存檔（PUT）對『已回簽的擇一單』的守門（H1／P1／P4）：呼叫端已確認該列 `is_signed=1`，並傳入**資料庫已存**的 `old`。
    P4＝拒絕（預設）⇒ 不論用戶端旗標，一律 409；P4＝允許 ⇒ 進入解鎖修改，但 P1 的鎖定比對持續生效。無擇一資料的單不受影響（H5）。"""
    if not applies(old):
        return
    if is_unlock_edit and alt_policy.policy("unlock_edit_signed") == 1:
        raise HTTPException(409, alt_lock.LOCKED_MSG)
    if alt_lock.changed(new, old, alt_policy.policy("lock_scope")):
        raise HTTPException(409, alt_lock.LOCKED_MSG)


def guard_move_out_of_sent(is_signed, data: dict, target_status: str) -> None:
    """P3：已回簽的擇一單不可被改成草稿／待審核／已取消／已拒絕（`update_status`、`recall`、`reject`）。
    預設（①）一律 409『請管理員取消回簽』；目標仍是『已送出』不算離開。選項②（自動清除）尚未提供（沒有消費者前不開放）。
    拒絕結案（P3b）預設『終局保留』＝不動任何東西，所以沒有對應的守門呼叫。無擇一資料的單不受影響（H5）。"""
    if is_signed and applies(data) and target_status != "已送出":
        if alt_policy.policy("move_out_of_sent") == 1:
            raise HTTPException(409, alt_lock.LOCKED_MSG)
