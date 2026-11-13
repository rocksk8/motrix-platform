# -*- coding: utf-8 -*-
"""審核中簽核人改了報價單內容的通知信（2026-11-11，業主需求；POST /api/quotations/{no}/review-edit 存檔成功後）。

[單位] case:review_edit_notify    [層] L2（M01）    [穩定度] 實作
[公開介面] fire_edited(quote_no, *, customer, editor, requester, fields, chain_reset) → bool；永不丟例外
[收件人] 信件類型 `approval_review_edit`（群組＝superadmins、事件＝送審人）＝**送審人（`approval.requestedBy`）＋全部最高管理者**
         （在職、有 Email、未退訂該類型者才收；最高管理者可在「信件與通知收件設定」頁覆寫）。編輯者本人若也是收件人（例如是超管）照寄，不特別排除。
[內容] 單號、客戶、編輯人、變動的**欄位名稱**；**不帶新舊值與金額**（收件人不一定有金額檢視權限，信走外部郵件系統）。
       第 3 層（含）以後的編輯會多一行「已回到第 1 層、整條簽核鏈重新進行」。
[失敗] 寄信是附帶動作：任何例外只記 log，絕不讓已存檔的編輯失敗；沒有收件人只記 warning。
"""
import logging
from urllib.parse import quote

from helpers import doc_type as _DT
from helpers import email_notify as _en
from helpers import mail_types as _mt

logger = logging.getLogger(__name__)

_mt.register("approval_review_edit", "報價單審核中被簽核人編輯", "approval", "superadmins", "送審人",
             "報價單內容在審核中被修改；已簽核的層需要重新簽核（第 3 層以後的編輯，將從第 1 層重新簽核）。",
             "請登入系統開啟該報價單，確認修改內容與目前的簽核進度。", owner="case")


def fire_edited(quote_no, *, customer: str = "", editor: str = "", requester: str = "", fields=None, chain_reset: bool = False) -> bool:
    """寄「報價單審核中被編輯」。回 True＝有收件人、已排入寄送；其餘（含任何例外）回 False。**永不丟例外**。"""
    try:
        no = str(quote_no or "").strip()
        names = [str(f) for f in dict.fromkeys(fields or []) if f]
        _r = lambda t: _DT.relabel(t, _DT.doc_type_of_no(no))   # noqa: E731  估價單走同一條審核流程：信裡的用語隨單據類型（報價單 ⇒ 逐位元不變）
        rows = [(_r("報價單號"), no), ("客戶名稱", (customer or "").strip() or "—"), ("編輯人", (editor or "").strip() or "—")]
        if names:
            rows.append(("變動項目", "、".join(names[:20])))
        if chain_reset:
            rows.append(("簽核進度", "已回到第 1 層，整條簽核鏈重新進行"))
        return _en.send_registered("approval_review_edit", title=_r("報價單審核中被編輯"),
                                   usernames=[requester] if requester else None, to_group=True,
                                   rows=rows, reason=_r("報價單 %s 在審核中被 %s 修改了內容") % (no, (editor or "簽核人").strip() or "簽核人"),
                                   badge_text="內容已變更", badge_color="#D97706",
                                   link="%s/pages/quotation-form.html?no=%s" % (_en._base_url(), quote(no, safe="")),
                                   button_text=_r("前往查看報價單"),
                                   note="您好，請留意目前的簽核進度；已簽核的層需重新簽核。")
    except Exception:
        logger.exception("報價單審核中被編輯的通知信寄送失敗（不影響已存檔的編輯；quote_no=%r）", quote_no)
        return False
