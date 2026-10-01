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
