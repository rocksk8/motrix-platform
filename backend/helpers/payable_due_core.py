# -*- coding: utf-8 -*-
"""預定付款日提醒的共用純函式庫（第 45 班；使用者 2026-10-07 Q8＝方案 B：L1 純函式庫＋各模組薄接線）。

[單位] helper:payable_due_core    [層] L1    [穩定度] 實作
[公開介面] CALENDAR_SOURCES、EVENT_CODE、GUARD_PREFIX、INAPP_PREFIX、MAIL_KEYS、MAX_WAIT_SECONDS_PER_RUN、SOON_DAYS、candidate_planned_dates、due_kind、effective_send_day、next_working_day、notify_finance、prune_guards、run_scan、sync_event、sync_lock、sync_lock
[不變式] 提醒的日期規則、guard、寄送迴圈、站內通知只有這一份；各模組只查自己的待付款列、整理成 items 交進來；信件與通知內容不放金額、受款人、廠商名、付款條件，只放單號、名目、預定付款日、關聯案件；guard 先寄、結果確定才寫；每封與每次掃描都有等待上限。
[契約題] tests/test_payable_due_core_t45.py
[注意] 信件類型 payable_due_soon／payable_due_today／payable_due_overdue 由 M01 登記，M01 不在時寄信 fail-closed；站內通知有自己的一次性 guard（INAPP_PREFIX），不依賴信件是否寄出。

為什麼放 L1：預定付款日有四個來源（案件額外支出、叫料匯款、承攬商匯款、勞報單），提醒的「日期規則、guard、寄送迴圈、站內通知」必須只有一份。
  各模組只負責「查自己的待付款列」＋整理成 `items` 交進來（薄接線）；模組之間不互相 import，也不必複製一整套（會各自演進）。
時機規則（與 M01 第 42 班 `payable_reminders` 原樣相同，只是搬到這裡）：
  名義日：預定日 − 3 天 ⇒ `soon`；預定日當天 ⇒ `today`；**名義日不是工作日就提前到前一個工作日寄**；兩封折到同一天只寄當天那封。
  **逾期（Q2）**：預定日之後**第 1 個工作日**寄 1 封 `overdue`（名義日＝預定日 + 1，不是工作日就**往後**找第一個工作日）；不週提、每筆最多 1 封。
  只有「寄信日＝今天」的候選才處理；寄信日已過的不補發（每日 08:00 與啟動補跑兩次機會）。工作日＝`helpers.business_days.is_working_day`（呼叫端傳入）。
冪等：先寄、結果確定才寫 guard（`SEND_SENT`／`SEND_UNKNOWN`／`SEND_PERMANENT_FAIL` 寫；`SEND_TRANSIENT_FAIL`／`SEND_SKIPPED`／沒有收件人不寫，之後重試）。
  guard key＝`payable_due_notif.<guard_id>.<kind>.<預定日>.<寄信日>`（寫進 system_settings）；`guard_id` 由呼叫端決定：**案件額外支出沿用舊格式（純 id）**，
  其他來源用 `<來源>.<key>`，同一個 key 在不同來源互不擋；改了預定日 ⇒ key 變、重新計算；寄信日早於今天 7 天以上的 key 每次掃描順手清掉。
等待上限：每封最多等 `SEND_WAIT_TIMEOUT_SECONDS`；一次掃描總共最多等 `MAX_WAIT_SECONDS_PER_RUN`；出現 `SEND_UNKNOWN` 立刻停止本次掃描。
收件人：信件類型由 M01 登記在「財務」群組（`to_group=True`，不另帶 usernames）；站內通知寫給在職的財務角色＋superadmin，尊重個人對該信件類型的退訂（`notification_muted`）。
  M01 不在 ⇒ 類型未登記 ⇒ 寄信 fail-closed（只給超級管理員）；這是已知取捨：承攬商匯款本來就綁案件，沒有 M01 的安裝包不會有待付款可提醒。
內容：不放金額、受款人、廠商名、付款條件（使用者 Q4）：只放單號、名目、預定付款日、關聯案件。
"""
import logging
import time
from datetime import date, timedelta

from helpers import email_notify as _en
from helpers.settings import _get_setting, _set_setting

logger = logging.getLogger(__name__)

SOON_DAYS = 3
MAX_WAIT_SECONDS_PER_RUN = 120
GUARD_PREFIX = "payable_due_notif."
INAPP_PREFIX = "payable_due_inapp."       # 站內通知自己的一次性 guard（不依賴信件是否寄出）
#: 寄信日種類 ⇒ 信件類型代號（類型由 M01 登記；這裡用變數取值，不是 `send_registered` 的字面 key）
MAIL_KEYS = {"soon": "payable_due_soon", "today": "payable_due_today", "overdue": "payable_due_overdue"}
_LABEL = {"soon": "預定付款日將到（3 天後）", "today": "預定付款日當天", "overdue": "預定付款日已逾期"}
_LIMIT = 14


def effective_send_day(nominal: date, is_wd, limit: int = _LIMIT) -> date:
    """名義日 ⇒ 實際寄信日：本身是工作日就是它，否則往前找最近的工作日（`limit` 天內找不到 ⇒ 原日期，不無窮迴圈）。"""
    d = nominal
    for _ in range(limit):
        if is_wd(d):
            return d
        d -= timedelta(days=1)
    return nominal


def next_working_day(nominal: date, is_wd, limit: int = _LIMIT) -> date:
    """逾期用：名義日往**後**找第一個工作日（`limit` 天內找不到 ⇒ 原日期）。"""
    d = nominal
    for _ in range(limit):
        if is_wd(d):
            return d
        d += timedelta(days=1)
    return nominal


def due_kind(planned: str, today: date, is_wd) -> tuple:
    """⇒ (今天要寄哪一封 '' ／soon／today／overdue, 要寫 guard 的 [(kind, 寄信日)])。soon 與 today 折到同一天 ⇒ 只回 today，但兩把 guard 都要寫。"""
    p = date.fromisoformat(planned)
    e_soon, e_today = effective_send_day(p - timedelta(days=SOON_DAYS), is_wd), effective_send_day(p, is_wd)
    e_over = next_working_day(p + timedelta(days=1), is_wd)
    if e_soon == e_today and e_today == today:
        return "today", [("soon", e_soon), ("today", e_today)]
    if e_today == today and e_soon != e_today:
        return "today", [("today", e_today)]
    if e_soon == today and e_soon != e_today:
        return "soon", [("soon", e_soon)]
    if e_over == today:
        return "overdue", [("overdue", e_over)]
    return "", []


def candidate_planned_dates(today: date, is_wd) -> list:
    """今天可能要寄的預定日（含逾期）：寄信日＝今天的名義日（今天＋其後連續的非工作日）及其 +3 天，加上「預定日之後第 1 個工作日＝今天」的那幾天。今天不是工作日 ⇒ []。"""
    if not is_wd(today):
        return []
    span = [today]
    d = today + timedelta(days=1)
    while not is_wd(d) and len(span) < _LIMIT:
        span.append(d)
        d += timedelta(days=1)
    out = {(x + timedelta(days=k)).isoformat() for x in span for k in (0, SOON_DAYS)}
    d = today - timedelta(days=1)                       # 逾期：預定日 d 的 d+1 到今天之間沒有別的工作日
    for _ in range(_LIMIT):
        out.add(d.isoformat())
        if is_wd(d):
            break
        d -= timedelta(days=1)
    return sorted(out)


def notify_finance(kind, source, key, ident, planned, link="cashier.html?tab=payreq") -> int:
    """站內通知寫給財務收件人（在職的財務角色＋superadmin，尊重對該信件類型的退訂）。文字不含金額。⇒ 寫了幾則。失敗只記 log。"""
    n = 0
    try:
        from db import get_db
        from helpers import _notify
        conn = get_db()
        try:
            rows = conn.execute("SELECT username, notification_muted FROM users WHERE active=1 AND role IN ('finance','superadmin') ORDER BY id").fetchall()
        finally:
            conn.close()
        ev = MAIL_KEYS[kind]
        msg = "%s：%s（預定 %s）" % (_LABEL[kind], ident, planned)
        for r in rows:
            if not _en._pref_enabled(r["notification_muted"], ev):
                continue
            _notify(r["username"], "payable_due_" + kind, "%s:%s:%s:%s" % (source, key, kind, planned), ident, msg, link)
            n += 1
    except Exception as exc:                                              # noqa: BLE001
        logger.warning("payable_due_core.notify_finance 失敗：%s", exc)
    return n


#: 哪些來源建行事曆「付款待辦」事件（Q3，使用者 2026-10-07）：案件額外支出、承攬商匯款、叫料匯款；**勞報單不進行事曆**（提醒信與站內通知仍涵蓋）。
CALENDAR_SOURCES = ("case", "subcontract_voucher", "case_material")
EVENT_CODE = "payable_due"


def sync_lock(source: str, key):
    """同一筆（來源＋key）的「讀現況→upsert／delete」要序列化：兩個很快連續的 fire 各自開背景執行緒，後讀到的現況可能先寫、先讀到的後寫 ⇒ 事件停在舊狀態（稽核 S4）。
    用法：`with sync_lock(來源, key): <讀現況>; sync_event(...)`（讀現況一定要在鎖內）。沿用 google_calendar 的 per-key 鎖表。"""
    from helpers.google_calendar import _merge_lock
    return _merge_lock("payable_due_sync:%s:%s" % (source, key))


def sync_event(source: str, key, item=None) -> bool:
    """對齊一筆的「付款待辦」事件：`item`＝(標題, 說明, 預定日) ⇒ upsert；`None` ⇒ delete。事件識別＝(payable_due, `<來源>:<key>`)。
    來源不在 `CALENDAR_SOURCES`（例如勞報單）⇒ 一律零呼叫、回 False。**不放金額**由呼叫端組文字時保證。失敗只記 log。
    寫鎖內不要呼叫（commit 之後；呼叫端自己 `spawn_bg_thread`）。事件種類開關關閉時 L1 不碰 Google。"""
    if source not in CALENDAR_SOURCES:
        return False
    try:
        from helpers import push_event_delete_for_module, push_event_upsert_for_module
        ek = "%s:%s" % (source, key)
        if item is None:
            push_event_delete_for_module(EVENT_CODE, ek)
        else:
            title, desc, day = item
            push_event_upsert_for_module(EVENT_CODE, title, desc, day, ek)
        return True
    except Exception as exc:                                              # noqa: BLE001
        logger.warning("payable_due_core.sync_event(%s:%s) failed: %s", source, key, exc)
        return False


def prune_guards(today: date) -> None:
    """清掉寄信日早於今天 7 天以上的 guard key（信件與站內通知兩種；key 最後一段是實際寄信日）。"""
    from db import get_db
    cutoff = (today - timedelta(days=7)).isoformat()
    conn = get_db()
    try:
        stale = [r["key"] for p in (GUARD_PREFIX, INAPP_PREFIX)
                 for r in conn.execute("SELECT key FROM system_settings WHERE key LIKE ?", (p + "%",)).fetchall()
                 if r["key"].rsplit(".", 1)[-1] < cutoff]
        if stale:
            conn.executemany("DELETE FROM system_settings WHERE key=?", [(k,) for k in stale])
            conn.commit()
    finally:
        conn.close()


def _scan_item(it, today, t0, *, is_wd, send, link, app_only=False) -> tuple:
    """一筆的處理 ⇒ (寄出封數, 要不要停止本次掃描: None／'wait'／'unknown')。例外由呼叫端接。
    `app_only`＝本次掃描已因等待上限／SMTP 無回應而停止寄信：只補站內通知、不寄信、不寫信件 guard（信件語意不變：未寄出就不寫，下次重試）。"""
    kind, guards = due_kind(it["planned"], today, is_wd)
    if not kind:
        return 0, None
    tail = [(k, e) for k, e in guards]
    mail_keys = ["%s%s.%s.%s.%s" % (GUARD_PREFIX, it["guard_id"], k, it["planned"], e.isoformat()) for k, e in tail]
    app_keys = ["%s%s.%s.%s.%s" % (INAPP_PREFIX, it["guard_id"], k, it["planned"], e.isoformat()) for k, e in tail]
    mail_done = any(_get_setting(k) for k in mail_keys if k.split(".")[-3] == kind)
    app_done = any(_get_setting(k) for k in app_keys if k.split(".")[-3] == kind)
    if mail_done and app_done:
        return 0, None
    # 站內通知有自己的一次性 guard，**不依賴信件是否寄出**（沒有財務信箱、SMTP 關閉、信件類型被關掉時，站內提醒照樣出現一次）
    if not app_done and notify_finance(kind, it.get("source") or "", it.get("key") or it["guard_id"], it["ident"], it["planned"]) >= 1:
        for k in app_keys:
            _set_setting(k, t0)
    if mail_done or app_only:
        return 0, None
    res = {}
    if send(kind, it["rows"], link, it["ident"], res):
        for k in mail_keys:                                     # 先寄、結果確定才寫 guard（SENT／UNKNOWN／PERMANENT_FAIL）
            _set_setting(k, t0)
    else:
        logger.warning("payable_due_core: %s 的預定付款日提醒未寄出（%s；不寫 guard，下次重試）", it["guard_id"], res.get("outcome") or "?")
    stop = "unknown" if res.get("outcome") == _en.SEND_UNKNOWN else None
    return (1 if res.get("outcome") == _en.SEND_SENT else 0), stop


def run_scan(items, today: date, *, is_wd, send, monotonic=time.monotonic, link=None, max_wait=None) -> int:
    """對 `items` 逐筆判斷今天該不該寄、寄、寫 guard、寫站內通知。⇒ 這次寄出幾封（測試用）。
    每一筆各自隔離（一筆出錯只記 log、繼續下一筆）；清舊 guard 一定會做。

    `items`：已篩過「合格」（已核准、未付款、未作廢、預定日合法）的列表，每筆 dict：
      `guard_id`（guard key 的識別段；不含空白）、`planned`（YYYY-MM-DD）、`ident`（單號）、`rows`（信件內容列 [(欄, 值)]，不放金額）、
      `source`／`key`（站內通知的去重識別）。
    `send(kind, rows, link, ident, out)`＝呼叫端提供的寄信函式（**必填**；寄信一律用字面 key 呼叫 `send_registered`，守門 `test_mail_registry`
    逐一核對，所以不放在 L1）；`link` 預設 `<系統網址>/pages/cashier.html`。"""
    sent = 0
    try:
        max_wait = MAX_WAIT_SECONDS_PER_RUN if max_wait is None else max_wait
        link = link or "%s/pages/cashier.html" % _en._base_url()
        t0 = today.isoformat()
        t_start = monotonic()
        items = list(items)
        rest = []                                               # 因等待上限／SMTP 無回應而沒輪到寄信的那些筆：仍要補站內通知（只有「寄信日＝今天」的候選，錯過就永遠沒有）
        for pos, it in enumerate(items):
            if monotonic() - t_start >= max_wait:
                logger.warning("payable_due_core: 本次掃描等待寄送已達 %s 秒上限，其餘提醒的信件留待下次（不寫信件 guard）；站內通知照補", max_wait)
                rest = items[pos:]
                break
            try:
                n, stop = _scan_item(it, today, t0, is_wd=is_wd, send=send, link=link)
            except Exception as exc:                            # noqa: BLE001 — 一筆壞掉不能讓其餘提醒全丟
                logger.warning("payable_due_core: %s 處理失敗（略過、繼續下一筆）：%s", it.get("guard_id"), exc)
                continue
            sent += n
            if stop == "unknown":
                logger.error("payable_due_core: SMTP 沒有在時限內回應，停止本次寄信（避免每封都卡住）；其餘提醒的站內通知照補")
                rest = items[pos + 1:]
                break
        for it in rest:                                         # 只補站內通知，不寄信
            try:
                _scan_item(it, today, t0, is_wd=is_wd, send=send, link=link, app_only=True)
            except Exception as exc:                            # noqa: BLE001
                logger.warning("payable_due_core: %s 站內通知補寫失敗（略過）：%s", it.get("guard_id"), exc)
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("payable_due_core.run_scan failed: %s", exc)
    finally:
        try:
            prune_guards(today)
        except Exception as exc:                                # noqa: BLE001
            logger.warning("payable_due_core.prune_guards failed: %s", exc)
    return sent
