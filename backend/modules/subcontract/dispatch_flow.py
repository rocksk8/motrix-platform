# -*- coding: utf-8 -*-
"""承攬商派發的狀態與審核規則（第 31 班 31-A；設計 docs/platform/plans/DISPATCH-APPROVAL-DESIGN.md）。

[單位] m04:dispatch_flow    [層] L2（M04 subcontract）    [穩定度] 實驗（31-A 逐切片補齊）
[公開介面] APPROVAL_STATUSES, STATUSES, display_status, is_legacy
[不變式] 作業狀態（contractor_dispatches.status）與審核狀態（approval_status／completion_status）分開；舊單（approval_status=''）不溯及既往
"""

#: 作業狀態（既有，下游讀者照舊讀這一欄）
STATUSES = ("draft", "sent", "confirmed", "pending_acceptance", "accepted", "completed", "cancelled")
STATUS_LABELS = {"draft": "草稿", "sent": "已送出", "confirmed": "已確認", "pending_acceptance": "待驗收",
                 "accepted": "已驗收", "completed": "完工", "cancelled": "已取消"}
#: 審核狀態（兩段各一欄；''＝舊單／尚未送審）
DRAFT, PENDING, IN_PROGRESS, APPROVED, RETURNED = "草稿", "待審核", "簽核中", "已核准", "已退回"
APPROVAL_STATUSES = ("", DRAFT, PENDING, IN_PROGRESS, APPROVED, RETURNED)


def _g(row, key, default=""):
    try:
        v = row[key]
    except (KeyError, IndexError):
        return default
    return default if v is None else v


def is_legacy(row) -> bool:
    """舊單＝第一段審核欄位為空字串（migration 預設）。新建的派發一律寫 `草稿` 以上的值，所以不會被誤認成舊單。"""
    return _g(row, "approval_status") == ""


def display_status(row) -> str:
    """畫面只顯示一個合併後的人話狀態（作業狀態＋兩段審核）。"""
    st = _g(row, "status", "draft") or "draft"
    label = STATUS_LABELS.get(st, st)
    if st == "cancelled" or st == "completed":
        return label
    comp = _g(row, "completion_status")
    if comp in (PENDING, IN_PROGRESS):
        return "完工審核中"
    if comp == RETURNED:
        return "完工被退回（%s）" % label
    ap = _g(row, "approval_status")
    if ap in (PENDING, IN_PROGRESS):
        return "派發審核中"
    if ap == RETURNED:
        return "派發被退回"
    if ap == DRAFT:
        return "草稿（尚未送審）"
    return label


# ── 狀態轉換：**唯一**寫 contractor_dispatches.status 的地方（守門 G-D1 掃描全模組）─────────────────────────────────

import hashlib
import json
from datetime import datetime


class FlowError(Exception):
    """規則違反 ⇒ 呼叫端轉 HTTPException(status_code, message)。"""

    def __init__(self, message, status_code=409):
        super().__init__(message)
        self.status_code = status_code


#: 作業狀態的合法轉換（只往前；沒有倒退——要退回請走審核的退回／撤回）。`completed` 只能由完工審核通過這個事件設定（via_completion）。
TRANSITIONS = {
    "draft": ("sent", "confirmed", "pending_acceptance", "cancelled"),
    "sent": ("confirmed", "pending_acceptance", "cancelled"),
    "confirmed": ("pending_acceptance", "cancelled"),
    "pending_acceptance": ("accepted", "cancelled"),
    "accepted": ("completed", "cancelled"),
    "completed": (),
    "cancelled": (),
}
#: 這些目標狀態要求第一段審核已核准（舊單 approval_status='' 照舊放行：不溯及既往）
GATED = ("sent", "confirmed", "pending_acceptance", "accepted")


def next_dispatch_code(conn, today=None) -> str:
    """`DP-{YYYYMMDD}-{NNNN}`（同 A2 費用單據單號作法）。呼叫端要已持有寫鎖（begin_write），否則兩個人同時開單會撞號（唯一索引是最後防線）。"""
    day = (today or datetime.now().strftime("%Y-%m-%d")).replace("-", "")
    stem = "DP-%s-" % day
    row = conn.execute("SELECT MAX(doc_code) FROM contractor_dispatches WHERE doc_code LIKE ? AND LENGTH(doc_code)=?",
                       (stem + "%", len(stem) + 4)).fetchone()
    last = int(row[0][-4:]) if row and row[0] else 0
    from helpers import recycle_bin as _rb                                   # 第 53 班：暫存區裡的派發單號不重發（已寄出／列印的單號不能被新單取代，還原也不必換號）
    taken = _rb.reserved_ids(conn, "contractor_dispatch")
    while "%s%04d" % (stem, last + 1) in taken:
        last += 1
    return "%s%04d" % (stem, last + 1)


def substantive_hash(vendor_id, items, personnel, tax_rate) -> str:
    """「實質欄位」（承攬商、品項、外包人員、稅率）的雜湊：核准當下存起來，之後不同 ⇒ 需重新送審（備註、日期、發票欄位不算）。"""
    def js(v):
        if isinstance(v, str):
            try:
                v = json.loads(v or "[]")
            except ValueError:
                pass
        return json.dumps(v if v is not None else [], ensure_ascii=False, sort_keys=True)
    try:
        rate = round(float(tax_rate if tax_rate is not None else 0.05), 6)
    except (TypeError, ValueError):
        rate = 0.05
    raw = "|".join([str(vendor_id or ""), js(items), js(personnel), str(rate)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def set_status(conn, row, target, user, *, reason="", via_completion=False, now=None) -> dict:
    """把一筆派發的作業狀態推到 `target`（含所有規則）。**不 commit**（呼叫端）。回 `{prev, new, note}`；違規 ⇒ FlowError。
    規則：①目標必須是合法轉換（TRANSITIONS）；②`completed` 只准 via_completion（完工審核通過）；③GATED 目標要第一段已核准（舊單放行）；
    ④確認驗收：操作人不可是建立者（最高管理者可例外，稽核標註）、驗收人姓名與時間必寫；⑤取消：已核准者要理由、已有匯款申請者僅最高管理者。"""
    now = now or datetime.now().isoformat()
    cur = _g(row, "status", "draft") or "draft"
    if target not in STATUSES:
        raise FlowError("不認得的狀態：%s" % str(target)[:40], 400)
    if target not in TRANSITIONS.get(cur, ()):
        raise FlowError("目前狀態「%s」無法改成「%s」" % (STATUS_LABELS.get(cur, cur), STATUS_LABELS.get(target, target)))
    if target == "completed" and not via_completion:
        raise FlowError("「完工」必須經完工審核通過才會設定，不能直接改狀態")
    ap = _g(row, "approval_status")
    if target in GATED and ap not in ("", APPROVED):
        raise FlowError("派發尚未核准（目前審核狀態：%s），不能改成「%s」" % (ap or "未送審", STATUS_LABELS[target]))
    username = user.get("username") or ""
    display = user.get("display_name") or username
    note = ""
    closed = []
    if target == "accepted":
        if username and username == (_g(row, "created_by") or ""):
            if user.get("role") != "superadmin":
                raise FlowError("驗收人不能是建立派發的人（職責分離）；請由其他管理員確認驗收")
            note = "同人驗收（最高管理者）"
        conn.execute("UPDATE contractor_dispatches SET status='accepted', accepted_by=?, accepted_at=?, updated_at=? WHERE id=?",
                     (display, now, now, row["id"]))
    elif target == "cancelled":
        reason = (reason or "").strip()
        needs_reason = ap == APPROVED or cur in ("accepted", "pending_acceptance")
        if needs_reason and not reason:
            raise FlowError("取消已核准或已進入驗收的派發要填寫理由", 400)
        if len(reason) > 500:
            raise FlowError("理由太長（上限 500 字）", 400)
        has_voucher = conn.execute("SELECT 1 FROM contractor_payment_vouchers WHERE dispatch_id=? AND voided_at=''", (row["id"],)).fetchone()
        if has_voucher and user.get("role") != "superadmin":
            raise FlowError("此派發已產生匯款申請，只有最高管理者可以取消（請先處理該申請）", 403)
        conn.execute("UPDATE contractor_dispatches SET status='cancelled', cancel_reason=?, cancelled_by=?, cancelled_at=?, updated_at=? WHERE id=?",
                     (reason, display, now, now, row["id"]))
        # 取消時**同一個交易**關閉還在審的階段（稽核 S-2）：待審核／簽核中 ⇒ 已退回（歷程記一筆 cancelled），
        # 否則簽核佇列／紅點還掛著一張已取消的派發、簽核人還能核准它。已核准／已退回的階段不動。
        for col, jcol, stage in (("approval_status", "approval_json", "approval"), ("completion_status", "completion_approval_json", "completion")):
            if _g(row, col) in (PENDING, IN_PROGRESS):
                try:
                    appr = json.loads(_g(row, jcol) or "{}")
                except ValueError:
                    appr = {}
                if not isinstance(appr, dict):
                    appr = {}
                appr.setdefault("history", []).append({"at": now, "by": username, "byDisplay": display, "action": "cancelled",
                                                       "tier": appr.get("currentTier") or 0, "comment": reason or "派發已取消"})
                appr["closedByCancel"] = now
                conn.execute("UPDATE contractor_dispatches SET %s=?, %s=? WHERE id=?" % (col, jcol),
                             (RETURNED, json.dumps(appr, ensure_ascii=False), row["id"]))
                closed.append({"stage": stage, "requestedBy": appr.get("requestedBy") or ""})
    elif target == "completed":
        conn.execute("UPDATE contractor_dispatches SET status='completed', completion_approved_at=?, updated_at=? WHERE id=?", (now, now, row["id"]))
    else:
        conn.execute("UPDATE contractor_dispatches SET status=?, updated_at=? WHERE id=?", (target, now, row["id"]))
    return {"prev": cur, "new": target, "note": note, "closed": closed}
