# -*- coding: utf-8 -*-
"""案件發票上傳通知（2026-11-07，使用者需求經 MOTRIX-ERP 模組結構圖窗口轉達；設計 CASE-INVOICE-UPLOAD-NOTIFY-DESIGN.md）。

[單位] case:invoice_notify    [層] L2（M01）    [穩定度] 實作
[公開介面] fire_uploaded(quote_no, *, kind, item_label, uploader, file_count, customer="", project="") → bool；
           notice(quote_no, data, *, kind, item_label, uploader, file_count) → dict｜None（組成「待寄通知」，供半解鎖套用路徑 commit 後再寄；永不丟例外）；send_notice(n) → bool（n 為 None ⇒ False）
[對象] 案件管理的兩種發票上傳成功：款項明細發票（`kind="payment"`）、材料申請發票（`kind="material"`）。
       **不含**：額外支出（費用單據）的發票（本版不通知，草稿階段會反覆上傳）、材料申請到貨憑證附件、任何刪除。
[收件人] 信件類型 `case_invoice_uploaded` 登記在「財務」群組（`mail_types` group `finance`）＝財務角色＋最高管理者；
         `to_group=True`、不另帶 usernames。在職、有 Email、**未退訂該類型**者才收；最高管理者可在「信件與通知收件設定」頁覆寫。
         退訂以信件類型 key 為單位（`users.notification_muted`，opt-out）——新類型預設人人都收，不會繼承別的類型（例如 `module_activity`）的退訂。
         上傳人自己是財務／最高管理者也照寄（不特別排除）。
[頻率] 一個上傳請求（可多檔）＝一封信；**不跨請求合併／節流**——逐檔分次上傳仍一檔一封（端點任何登入使用者皆可傳），可能連發而觸發 SMTP 限流（失敗不重送）。是否加合併是產品決定。
[內容] 案件編號、客戶／專案、項目、上傳人、檔案數；**不放檔名與金額**（檔名常含金額，信走外部郵件系統）。
[時機] 直接路徑：資料存妥、commit 之後。半解鎖暫存（`pending`）**不寄**（發票還沒進案件）；核准套用後才寄（commit 之後，與稽核同一個延後點）。
[失敗] 寄信是附帶動作：任何例外只記 log（含原因），絕不讓上傳或核准失敗；沒有收件人只記 warning。
"""
import logging

from helpers import email_notify as _en
from helpers import mail_types as _mt

logger = logging.getLogger(__name__)

_mt.register("case_invoice_uploaded", "案件發票已上傳（財務）", "business", "finance", "財務",
             "案件的款項或材料申請有人上傳了發票。", "請登入系統，於案件管理查看發票並核對、登錄。", owner="case")

KIND_LABEL = {"payment": "款項發票", "material": "材料申請發票"}


def _link(quote_no: str) -> str:
    from urllib.parse import quote
    return "%s/pages/case-management.html?q=%s" % (_en._base_url(), quote(quote_no or "", safe=""))


def notice(quote_no: str, data: dict, *, kind: str, item_label: str, uploader: str, file_count: int):
    """把「要寄的內容」收成一個 dict（不查資料庫、不寄信）。客戶／專案名取自案件 JSON（`customerName`／`projectName`）。
    **永不丟例外**（呼叫端在 commit 之前／交易內呼叫它）：組裝失敗 ⇒ 記 log、回 None，`send_notice(None)` 直接回 False。"""
    try:
        d = data if isinstance(data, dict) else {}
        return {"quote_no": quote_no, "kind": kind, "item_label": item_label, "uploader": uploader,
                "file_count": file_count, "customer": d.get("customerName") or "", "project": d.get("projectName") or ""}
    except Exception:
        logger.exception("案件發票上傳通知組裝失敗（不影響上傳／核准；quote_no=%r kind=%r）", quote_no, kind)
        return None


def send_notice(n) -> bool:
    """寄 `notice()` 組好的內容；`None`（組裝失敗）或任何例外 ⇒ False，永不丟例外。"""
    if not n:
        return False
    try:
        return fire_uploaded(n.get("quote_no"), kind=n.get("kind"), item_label=n.get("item_label"), uploader=n.get("uploader"),
                             file_count=n.get("file_count"), customer=n.get("customer") or "", project=n.get("project") or "")
    except Exception:
        logger.exception("案件發票上傳通知寄送失敗（不影響上傳／核准）")
        return False


def fire_uploaded(quote_no, *, kind, item_label, uploader, file_count, customer: str = "", project: str = "") -> bool:
    """寄「案件有新上傳的發票」。回 True＝有收件人、已排入寄送；其餘（含任何例外）回 False。**永不丟例外**。"""
    try:
        no = str(quote_no or "").strip()
        who = (customer or "").strip()
        if (project or "").strip():
            who = ("%s／%s" % (who, project.strip())) if who else project.strip()
        rows = [("案件編號", no), ("客戶／專案", who or "—"), ("類別", KIND_LABEL.get(kind, "發票")),
                ("項目", str(item_label or "—")), ("上傳人", str(uploader or "—")), ("檔案數量", "%s 個" % (file_count or 0))]
        return _en.send_registered("case_invoice_uploaded", title="案件有新上傳的發票", rows=rows, to_group=True,
                                   reason="案件 %s 有新上傳的發票" % no, badge_text="新發票", badge_color="#2F6FD6",
                                   link=_link(no), button_text="前往案件管理",
                                   note="您好，以下案件有人上傳了發票，請登入系統查看並核對。")
    except Exception:
        logger.exception("案件發票上傳通知寄送失敗（不影響上傳；quote_no=%r kind=%r）", quote_no, kind)
        return False
