# -*- coding: utf-8 -*-
"""報價單「解鎖編輯」後通知已簽過的人（fix/unlock-edit-keep-requester，2026-11-13，使用者裁示）。

最高管理者解鎖編輯並存檔 ⇒ 簽核鏈重建、已簽的層全部清除重簽。以前這些人完全不知道自己簽過的單被改了；現在每位「已簽過、被清掉」的簽核人
收到：站內通知＋信件＋LINE（信件類型 `approval_content_edited`，登記在「報價單與簽核」群組；LINE 預設關、由最高管理者勾選）。
**預設只發給本人**（事件收件人＝被清掉的簽核人，不加群組）。信內不放金額（只放單號、客戶、修改人、原送審人）。
寄信／站內通知是**附帶動作**：任何例外只記 log，不可以讓存檔失敗——對外入口（`fire`）自己包 try。

[單位] case:quote_edit_notify    [層] L2（M01）    [穩定度] 實驗
[公開介面] signed_layers, fire
[契約題] tests/test_unlock_edit_keep_requester_2026_11_13.py
"""
import logging

from helpers import email_notify as _en
from helpers import mail_types as _mt

logger = logging.getLogger(__name__)

_mt.register("approval_content_edited", "報價單內容被修改，需重新簽核", "approval", "none", "已簽過、被清除的簽核人",
             "您先前簽核的報價單內容被最高管理者修改，您的簽核已被清除，在您重新簽核之前不會進入下一個流程。",
             "請登入系統，於「待我簽核」開啟該報價單確認修改後的內容，再重新簽核或退回。", owner="case")


def signed_layers(approval):
    """舊簽核物件 ⇒ 被清掉的已簽層清單 `[{"tier": 1 起算, "username", "displayName", "approvedAt"}]`（同一人在多層會多列）。
    看不懂的形狀（沒有 tiers、非 list、項目不是 dict）一律略過，不丟例外。"""
    out = []
    tiers = (approval or {}).get("tiers") if isinstance(approval, dict) else None
    if not isinstance(tiers, list):
        return out
    for i, t in enumerate(tiers, 1):
        for a in ((t or {}).get("approvers") or []) if isinstance(t, dict) else []:
            if isinstance(a, dict) and a.get("status") == "approved" and a.get("username"):
                out.append({"tier": i, "username": str(a["username"]), "displayName": str(a.get("displayName") or a["username"]),
                            "approvedAt": str(a.get("approvedAt") or "")})
    return out


def fire(quote_no, customer, cleared, *, editor, editor_display, requester_display):
    """通知被清掉的簽核人（排除修改人自己）。`cleared`＝`signed_layers()` 的結果。回傳實際通知的帳號清單；任何例外只記 log。"""
    try:
        users = [u for u in dict.fromkeys(c["username"] for c in (cleared or [])) if u and u != editor]
        if not users:
            return []
        from helpers import _notify
        msg = "報價單 %s（%s）的內容已被 %s 修改，您先前的簽核已清除，請重新簽核" % (quote_no, customer or "", editor_display or editor)
        for u in users:
            try:
                _notify(u, "approval_content_edited", quote_no, quote_no, msg)
            except Exception:                                    # noqa: BLE001 — 站內通知失敗不影響其他人
                logger.exception("解鎖編輯站內通知失敗（%s → %s）", quote_no, u)
        rows = [("單號", quote_no), ("客戶", customer or "—"), ("修改人", editor_display or editor), ("送審人", requester_display or "—")]
        _en.send_registered("approval_content_edited", title="報價單內容被修改，需重新簽核", rows=rows, usernames=users,
                            badge_text="需重新簽核", badge_color="#B45309", link="%s/pages/approval-queue.html" % _en._base_url(),
                            button_text="前往待我簽核", reason="報價單 %s 內容被修改，需重新簽核" % quote_no,
                            note="您好，您先前簽核的報價單內容已被最高管理者修改，您的簽核已清除，請重新確認後簽核。",
                            line_exclude=[editor])
        return users
    except Exception:                                            # noqa: BLE001 — 附帶動作：不可以讓存檔失敗
        logger.exception("解鎖編輯通知失敗（%s）", quote_no)
        return []
