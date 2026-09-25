# -*- coding: utf-8 -*-
"""M11 標案雷達的通知信（2026-09-25 自 helpers/email_notify.py 搬入）。

L1 寄信原語（收件人、版面、寄送）一律經 `_en.<name>` 取用：晚綁定，
測試對 `helpers.email_notify` 的 patch 照樣生效；本檔不另寫一套寄信邏輯。
"""
from helpers import email_notify as _en
from helpers import mail_types as _mt

# 信件類型（CORE-SPEC「信件與通知的收件人、用語」）：模組載入時登記；模組不在 ⇒ 類型不存在
_mt.register("tender_found", "標案雷達新標案", "business", "admins", "",
             "有符合關鍵字的新標案，截止日前未處理將錯過投標。",
             "請登入系統，於標案雷達頁檢視標案內容並決定是否投標。", owner="tender_radar")
_mt.register("tender_fetch_failed", "標案雷達無法連線來源網站", "system", "superadmins", "",
             "本次排程沒有取得任何標案；連線恢復前，新標案不會通知。",
             "系統會於下次排程自動重試。若連續多日沒有收到標案彙總信，請至標案雷達頁查看「雷達健康狀態」。",
             owner="tender_radar")
_mt.register("tender_source_changed", "標案雷達來源網站格式異動", "system", "superadmins", "",
             "大部分資料無法解析；解析器調整之前，標案雷達每日結果為 0 筆，而頁面不會顯示錯誤。",
             "請通知系統維護人員依來源網站的新格式調整解析器。", owner="tender_radar")


# ── 標案雷達（2026-09-21，細線 6 第 5 步）────────────────────────────────────
#
# ⚠️ **三支獨立函式，event key 寫在函式內部，不是一支帶參數的。**
# 既有 44 支 `notify_*` 零支把 key 當參數，而這不只是慣例問題：
# `tests/test_notification_prefs_coverage.py` 是**掃本檔的 `_en._admin_emails(...)`
# 呼叫端**來比對 `EVENT_GROUPS`——一支函式帶參數的話，守門掃不出那三個 key，
# **漏登記不會紅**。慣例跟守門是綁在一起的。
#
# ⚠️ 三個 key 也刻意分開：「抓不到」與「疑似改版」的**處置相反**
# （掛掉等它好、改版要改解析器）。共用一個 key 的話，使用者關掉吵的那個，
# 就同時關掉了他其實想留的那個。
#
# ⚠️⚠️ **三支都走 `_send_raising` 而不是 `_async_send`。**
# `_async_send` 是**射後不理**（只開一條執行緒），而 `_send` 裡有**五個安靜的 return**
# （功能未啟用／非正式機被擋／收件人空／SMTP 未設定／SMTP 例外），**一個都傳不回來**。
# 後果分兩種，而第二種更嚴重：
#   `notify_tender_found`        → 標案被標記「已通知」而信沒出去 ⇒ **永遠不會再寄**
#   `notify_tender_fetch_failed` → 邊緣被消耗掉而信沒出去 ⇒ **雷達從此瞎著且沒人會知道**
# 🔑 前者是漏掉幾筆標案，**後者是漏掉「雷達壞了」這件事本身**。
# ⚠️ 最可能的觸發是「SMTP 還沒設定」——**使用者第一次啟用的那一天**。
# 📌 它們跑在排程的 Timer 執行緒裡，同步阻塞 15 秒無害。

_TENDER_SOURCE_NOTE = (
    "資料來源：政府電子採購網（依其著作權聲明重製，已註明出處）。"
    "本信由標案雷達每日彙總自動寄出，可在「通知設定」關閉。"
)


def notify_tender_found(tenders: list, watch_names: list = None,
                        announce_quiet_period: bool = False,
                        no_watches: bool = False) -> None:
    """標案雷達命中新標案 → 所有 admin/superadmin。

    ⚠️ **每日一封彙總，不是每筆一封**：命中 40 筆就是信裡 40 列。
    40 封信會讓收件人把整個事件 key 關掉，**而他關掉之後就再也收不到真正重要的那一筆**。

    `announce_quiet_period`：這一封寄完之後就要進入 7 天純記錄期時才給 True。
    ⚠️ **寄一封然後安靜一週，從收件人的角度跟「壞掉了」完全一樣**，
    而這條線的全部價值就是「不會漏掉標案」——讓收件人懷疑它壞了等於毀掉它。
    ⚠️ 但這句話**只能出現在那一封**：每封都寫的話，第 8 天恢復後的信也會這樣說，
    收件人會第二次以為它壞了。判斷在呼叫端（`_quiet_period_starts_after_this_mail`）。
    """
    to = _en._admin_emails("tender_found")
    if not to:
        return
    def _dash(v):
        """⚠️ `NULL` 一律顯示「—」，**不可以是空白或 `None`**。
        空白讓收件人分不出「沒有這個欄位」與「這一頁沒載好」；
        `None` 則是直接把 Python 的內部值漏到信裡。
        🔑 「沒有」要看得見，才知道那是**沒有**不是**漏掉**。"""
        if v is None or str(v).strip() == "":
            return "—"
        return str(v)

    from datetime import date as _date
    today = _date.today()
    due_soon = 0
    rows = []
    for t in (tenders or [])[:50]:
        budget = t.get("budget")
        budget_s = "—" if budget is None else f"{budget:,}"
        deadline = t.get("deadline")
        if deadline:
            try:
                if 0 <= (_date.fromisoformat(deadline) - today).days <= 7:
                    due_soon += 1
            except ValueError:
                pass
        # 七個欄位（D9）：標案名稱／機關／地點／採購性質／招標方式／預算／截止日
        rows.append((
            _dash(t.get("name")),
            f"機關 {_dash(t.get('org'))}　地點 {_dash(t.get('location'))}<br>"
            f"採購性質 {_dash(t.get('procurement_type'))}　"
            f"招標方式 {_dash(t.get('tender_method'))}<br>"
            f"預算 {budget_s}　截止 {_dash(deadline)}",
        ))
    more = len(tenders or []) - len(rows)
    if no_watches:
        # N17b：一條搜尋條件都沒有時，這封信的意義不是「幫你篩到了什麼」，
        # 而是「雷達開始跑了，但它還不知道你要找什麼」。
        # ⚠️ 講成「找到 N 筆符合條件」是**騙人的**——那是未經篩選的全部。
        intro = (
            f"<b>共 {len(tenders or [])} 筆</b>標案（<b>其中 {due_soon} 筆七日內截止</b>）。"
            "標案雷達已開始運作。"
            "<b>目前尚未設定任何搜尋條件，以下為未經篩選的清單。</b>"
            "請至標案雷達頁面新增關鍵字與<b>排除詞</b>；未設定排除詞時，每日彙總的筆數可能過多。"
        )
    else:
        # D11：開頭先給大綱，不是直接進清單。
        # ⚠️ 收件人每天打開這封信，第一眼要能判斷「今天需不需要花時間」——
        # 直接是一張表的話，他每天都得讀完才知道。
        # ⚠️ 粗體要包**整句**不要包數字：`共 <b>5</b> 筆` 會被標籤切開，
        # 而下游（信件、測試、任何掃內容的東西）看到的是「共 」與「 筆」中間夾標籤。
        # 🔑 這正是列表頁 `截止<br>投標` 那個坑，只是這次是我自己製造的。
        intro = (f"<b>共 {len(tenders or [])} 筆</b>符合條件的新標案，"
                 f"<b>其中 {due_soon} 筆七日內截止</b>。")
    if more > 0:
        intro += f"（信中只列前 {len(rows)} 筆，其餘 {more} 筆請進系統查看）"
    if watch_names:
        intro += "　命中條件：" + "、".join(sorted(set(watch_names)))
    note = _TENDER_SOURCE_NOTE
    if announce_quiet_period:
        note = (
            "本信為標案雷達的第一封通知。<b>接下來 7 天為純記錄模式，不再寄信</b>："
            "系統照常每日抓取並記錄。"
            "請於此期間至畫面確認關鍵字與排除詞的設定，"
            "第 8 天起恢復每日彙總。<br>" + note
        )
    html = _en._build_html(
        "tender_found", "標案雷達：新標案", f"{len(tenders or [])} 筆", "#1D4ED8",
        rows, "", _en._base_url(), note=note, intro=intro,
        button_text="前往標案雷達",
    )
    _en._send_raising(to, _mt.subject("tender_found", f"標案雷達新標案 {len(tenders or [])} 筆"), html)


def notify_tender_fetch_failed(error: str, since: str = "") -> None:
    """標案雷達**抓不到對方網站** → 所有 admin/superadmin。

    ⚠️ **只在「進入異常」那一次寄**（邊緣觸發，不是準位觸發）。
    站台掛一週寄七封信的話，第八天真的壞掉時沒有人會看——
    **狼來了的告警等於沒有告警。**

    ⚠️ 跟 `notify_tender_source_changed` 是**不同的事件 key**：
    抓不到只要等它好，改版要改解析器。
    """
    to = _en._admin_emails("tender_fetch_failed")
    if not to:
        return
    rows = [("失敗原因", error or "（未記錄）")]
    if since:
        rows.append(("上次成功", since))
    intro = (
        "標案雷達本次無法連線政府電子採購網，未取得任何標案。"
        "可能原因為來源網站維護或網路中斷。本通知僅於狀態由正常轉為異常時發送一次，連續失敗不重複發送。"
    )
    note = _TENDER_SOURCE_NOTE
    html = _en._build_html("tender_fetch_failed", "標案雷達：無法連線來源網站", "連線失敗", "#B91C1C",
                       rows, "", _en._base_url(), note=note, intro=intro,
                       button_text="前往標案雷達")
    _en._send_raising(to, _mt.subject("tender_fetch_failed", "標案雷達無法連線政府電子採購網"), html)


def notify_tender_source_changed(parsed: int, dropped: int) -> None:
    """標案雷達**疑似對方改版** → 所有 admin/superadmin。

    解析大量失敗（丟掉的比解出來的多）代表對方頁面結構變了，**解析器要改**。
    ⚠️ 這跟「抓不到」是兩件事：那邊等它好就行，**這邊不動手就永遠抓不到東西**，
    而且畫面上看起來一切正常（雷達還在跑、只是每天都 0 筆）。
    """
    to = _en._admin_emails("tender_source_changed")
    if not to:
        return
    total = parsed + dropped
    rows = [("成功解析", f"{parsed} 筆"), ("解析失敗", f"{dropped} 筆"),
            ("本次總筆數", f"{total} 筆")]
    intro = (
        "標案雷達可以連線政府電子採購網，但大部分資料無法解析，研判來源網站已變更頁面格式。"
        "此狀況需要調整解析器，不會自行恢復。"
    )
    html = _en._build_html("tender_source_changed", "標案雷達：來源網站格式異動", f"無法解析 {dropped} 筆", "#92400E",
                       rows, "", _en._base_url(), note=_TENDER_SOURCE_NOTE, intro=intro,
                       button_text="前往標案雷達")
    _en._send_raising(to, _mt.subject("tender_source_changed", "標案雷達來源網站格式異動"), html)
