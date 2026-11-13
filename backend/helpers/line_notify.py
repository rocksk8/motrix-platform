# -*- coding: utf-8 -*-
"""LINE Messaging API 發送管道（2026-11-11，T79 候選票；信件通知的並行通道）。

[單位] helper:line_notify    [層] L1    [穩定度] 實作（事件通道＋綁定儲存；OAuth 綁定流程在 helper:line_login）
[公開介面] AUDIENCE_MODES, BATCH_MAX_KEYS, BatchConflict, CALLBACK_PATH, CriticalConfirmRequired, DEFAULT_EVENT_SPEC, HTTP_TIMEOUT, LINE_API_BASE, LINE_EVENTS, LINKS_KEY, LINK_PAGES, MARKS_KEY, MARK_KEEP_DAYS, MAX_AUDIENCE_USERS, MAX_TEXT, MONTHLY_LIMIT_FALLBACK, MULTICAST_LIMIT, PENDING_KEY, PENDING_TTL_DAYS, SEND_PERMANENT_FAIL, SEND_SENT, SEND_SKIPPED, SEND_TRANSIENT_FAIL, SETTING_KEY, USAGE_DAILY_KEEP_DAYS, USAGE_KEY, WIRED_EVENTS, audience_view, binding_view, build_text, callback_url, deliver_event, enabled, event_enabled, event_roles_view, event_spec, events_view, ids_for, is_linked, is_wired, link_user, links_enabled, login_credentials, mask, month_cap_percent, normalize_public_base, notify_event, notify_users, preview_events_batch, public_base, push, push_async, quota, restore_events_batch, retry_pending, safe_link, set_audience, set_confirmed, set_event, set_event_roles, set_events_batch, settings_lock, unlink_user, usage_daily_view, valid_login_id, valid_login_secret, valid_token, verify_token, wired_events
[契約題] tests/platform/test_line_notify_t79.py、modules/case/tests/test_line_review_edit_2026_11_11.py
[不變式]
  ⓪ 曝露面：`public_base_url`（Tunnel 公開網域，callback 用）與 `include_links`（訊息是否帶連結，預設關）是**兩個獨立設定**（2026-11-11 PM 裁示）。
     有公開網域 ≠ 訊息帶連結；帶連結要兩者都成立，且只限 `LINK_PAGES` 白名單頁面，其餘連結一律不帶（不改寫）。
  ① 本檔不 import 業務模組；對 `email_notify` 只在函式內惰性 import（`email_notify` 頂層 import 本檔，反過來不可循環）；寄不寄由 `email_notify.email_send_policy()`
     （環境變數／`.no_email_send`）決定——**開發機標記同時擋信件與 LINE**（開發機誤推真實同仁的事故同一類）。
     ⚠️ 被擋的只有「推播」（`push`）；`verify_token`／`quota` 是唯讀 GET（不發訊息、不耗額度）**刻意不受開發機標記影響**，讓部署前能先確認 token——不是漏掉，不要「補」。
     若 PM 要「開發機完全不對外」，那是 PM 的決定，不是審查項目。
  ② 唯一的對外呼叫是 `_http`（urllib）；測試只換 `_http`。conftest NETGUARD 擋 urllib.request.urlopen，所以測試沒換就連不出去。
  ③ 回傳值沿用信件的四種結果（字串值與 `email_notify.SEND_*` 相同）：sent／transient_fail／permanent_fail／skipped。永不拋例外。
  ④ channel access token 存 `system_settings.line_notify.channel_access_token`（admin 在設定頁輸入；與 SMTP 密碼同一慣例）。
     GET 一律遮罩、PUT 收到遮罩值＝保留原值；每日 JSON 匯出以 json_remove 挖掉（archive.py）；**不寫進 log**。
  ⑤ 內容只用呼叫端給的文字：信件現有規則是「外部系統不帶金額」，LINE 同一規則（呼叫端負責，本檔不判斷內容）。
  ⑥ LINE Login channel 的 secret（`login_channel_secret`）與 token 同一慣例：GET 遮罩、PUT 遮罩值＝保留、每日 JSON 匯出挖掉、不寫 log；
     `login_channel_id`（純數字）不是祕密。兩者格式不合一律不收、不用（`login_credentials()` 回 ("", "")）。
  ⑦ 綁定紀錄 `line_links[username] = {userId, linkedAt[, confirmed]}`；`confirmed` 是綁定後推確認訊息的結果（True／False／None＝沒驗），只由
     `set_confirmed` 寫；重新綁定（`link_user`）會清掉舊的 `confirmed`。
  ⑧ 收件人（2026-11-12 改寫；**LINE 不再依附 Email**）：單一入口 `deliver_event`／`notify_event` 把「事件業務收件人」（`helpers.event_audience`：事件收件人＋T80 收件設定，
     不看 Email、不看信件退訂／關閉、只收在職）再經 `helpers.line_recipients.filter_usernames`（LINE 角色允許清單∩個人沒退訂 LINE）才轉成 userId（只收已綁定的）。
     角色允許清單 `line_notify.event_roles` 的寫入在本檔 `set_event_roles`（與事件開關共用 `_lock`），讀取與過濾在 `line_recipients`。
     `notify_users`（舊入口：收件人由呼叫端給、不做業務收件人解析）**只剩相容與測試用，業務碼不可再呼叫**——新程式一律走 `deliver_event`／`notify_event`／`email_notify.send_registered`。
  ⑨ 額度：推播成功後呼叫 `helpers.line_quota.after_push()`（背景、去抖動、永不丟例外）；用量判斷與告警在 `line_quota`。
  ⑩ 額度保留與每月上限（2026-11-12 使用者裁示）：用量 ≥ `line_quota.RESERVE_PERCENT`（90%）時非 critical 事件暫停；**帶 `month_cap_percent` 的事件**（登入失敗鎖定告警＝25%）
     本月累計推播則數（每位收件人算一則，記在 `system_settings.line_event_usage`）超過「月上限（LINE 回報的上限）× 百分比」後，**LINE 回報無上限（付費方案）時沒有每月上限**（`_monthly_limit()` 回 None）；
     本月狀態讀不到時才保守用 `MONTHLY_LIMIT_FALLBACK`＝200（免費方案）。超過後
     LINE 不再發（`deliver_event` 回 "monthly_cap"），Email 照寄。百分比可在 `system_settings.line_notify.month_cap_percent = {事件: 整數}` 覆寫（0＝完全不發 LINE；設定頁沒有欄位）。
  ⑪ 補發佇列（同樣 2026-11-12）：帶 `dedupe_key` 的呼叫（每日檢查型，如保固到期）若 LINE 因額度保留／暫時失敗／token 失效（skipped）沒送出，
     連同參數記進 `system_settings.line_pending`；每日檢查（`system_checks._check_line_pending` → `retry_pending`）重送，成功／永久失敗就移除，超過 `PENDING_TTL_DAYS` 天放棄。
     收件人在**重送當下**才重新解析（成員／綁定可能已變）。⇒ LINE 的送達狀態與 Email 分開記錄：Email 寄成功不代表 LINE 完成。
  ⑫ 接線單位是信件登記表（2026-11-13）：`wired_events()`＝已登記的信件類型（扣掉 `line_catalog` 的排除清單：獎金／薪資／勞報單等）＋LINE-only／細項事件；
     `LINE_EVENTS` 只是「覆寫表」（priority／digest／line_group／mail_key），沒列的事件用 `DEFAULT_EVENT_SPEC`（normal、不彙整、LINE 群組同信件）。
     `WIRED_EVENTS` 是相容名稱：惰性序列，每次迭代／`in` 都讀 `wired_events()`（模組在 import 之後才登記信件類型，靜態 tuple 會漏）。
  ⑬ 「誰要發」三層（`line_recipients.resolve_audience`）：業務收件人 ∩ 角色允許清單（`event_roles`）→（可選）管理員指定的角色與個人（`audiences`，本檔 `set_audience`）→ 個人退訂最後；
     預設 `business`＝與 2026-11-12 行為逐位元相同。
  ⑭ 批次與預設（2026-11-13，LINE 事件矩陣票；使用者裁示）：`set_events_batch` 一次改多個事件（開關／誰要發／角色篩選）——**全部驗證通過才寫、整批只寫一次 `_set_setting`**
     （任何一項不合法＝整批不改）。`_lock` 是**不可重入**的 `threading.Lock`：批次函式**不可以**在鎖內再呼叫 `set_event`／`set_audience`／`set_event_roles`
     （會死結）——驗證（含 `ineligible_users` 的資料庫查詢）全在進鎖前做完，進鎖後只重做「純計算」的部分（開關現況、是否已接線、重要告警的確認）。
     **事件從關切到開、而且沒有指定收件對象時，伺服器套用預設「只發給我」**（`default_user`＝操作者；批次與單項端點都一樣，由 router 傳入；helper 直接呼叫不帶 `default_user`＝不套用）；
     已經有 `audiences` 設定的事件不覆蓋。批次**關閉**「重要」告警（`priority=critical`）的事件要帶 `confirm_critical=True`，否則 `CriticalConfirmRequired`（router 回 400）。
  ⑮ 按日計數：`line_event_usage_daily(day, event_key, n)`（core 未取號 migration）記每天每事件推出幾則（台灣時區的日期）；保留 `USAGE_DAILY_KEEP_DAYS`（31）天，超過的在寫入時清掉
     （每行程每天最多清一次）。與舊的「本月」計數 `line_event_usage = {month, events}` **並存**（額度保留與每月上限仍用舊的，格式不變）。
     `usage_daily_view` 回近 30 天合計與 `accumulated_days`（從 `system_settings.line_event_usage_since` 起算；未滿 30 天 ⇒ `complete=False`，畫面標「已累積 N 天」）。
"""
import json
import logging
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from .settings import _get_setting, _set_setting

logger = logging.getLogger(__name__)

SETTING_KEY = "line_notify"
LINE_API_BASE = "https://api.line.me"

SEND_SENT = "sent"
SEND_TRANSIENT_FAIL = "transient_fail"
SEND_PERMANENT_FAIL = "permanent_fail"
SEND_SKIPPED = "skipped"

#: LINE 文字訊息上限 5000 字；留餘裕，且手機上太長的通知沒人看
MAX_TEXT = 1000
#: multicast 一次最多 500 人
MULTICAST_LIMIT = 500
HTTP_TIMEOUT = 10
_MASK = "••••••••"


def _cfg() -> dict:
    v = _get_setting(SETTING_KEY, {}) or {}
    return v if isinstance(v, dict) else {}          # 手改壞（不是物件）⇒ 當成沒設定，不丟例外


def _events() -> dict:
    ev = _cfg().get("events")
    return ev if isinstance(ev, dict) else {}


#: LINE channel access token 是 base64url 風格的長字串；格式不合（含換行、中文、過長）一律不收、不送：
#: 壞字元會讓 http.client 丟出「Invalid header value b'Bearer <整串 token>'」，例外訊息會把 token 帶進 log（K 審 S2）。
_TOKEN_RE = re.compile(r"^[A-Za-z0-9+/=._-]{20,512}$")


def valid_token(tk) -> bool:
    return isinstance(tk, str) and bool(_TOKEN_RE.match(tk))


#: LINE Login channel：Channel ID 是純數字；Channel secret 是 32 位十六進位。
_LOGIN_ID_RE = re.compile(r"^[0-9]{6,20}$")
_LOGIN_SECRET_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def valid_login_id(v) -> bool:
    return isinstance(v, str) and bool(_LOGIN_ID_RE.match(v))


def valid_login_secret(v) -> bool:
    return isinstance(v, str) and bool(_LOGIN_SECRET_RE.match(v))


def login_credentials() -> tuple:
    """`(channel_id, channel_secret)`；任一個沒設或格式不合 ⇒ `("", "")`（LINE Login 視為沒設好）。"""
    c = _cfg()
    cid, sec = c.get("login_channel_id"), c.get("login_channel_secret")
    if valid_login_id(cid) and valid_login_secret(sec):
        return cid, sec
    return "", ""


def settings_lock():
    """讀改寫 `system_settings.line_notify` 的行程內鎖（PUT 主設定與 `set_event` 共用，避免互相蓋掉）。"""
    return _lock


def mask(token) -> str:
    """設定頁顯示用：有值＝固定遮罩字串（不洩漏長度與尾碼），沒值＝空字串。"""
    return _MASK if token else ""


def enabled() -> bool:
    c = _cfg()
    return bool(c.get("enabled") and c.get("channel_access_token"))


#: LINE 訊息允許帶連結的頁面（B 案才會用到；A 案 `include_links` 預設關）。不在這裡的頁面，連結一律拿掉（不改寫成別的網址）。
#: ⚠️ 加頁面＝擴大對外曝露面（Tunnel ingress 要同步放行該頁面與它依賴的 static／API），要走 PM 與正式機確認。
LINK_PAGES = ("quotation-form.html", "approval-queue.html", "case-management.html", "cashier.html")
CALLBACK_PATH = "/api/line/callback"

_PUBLIC_BASE_RE = re.compile(r"^https://[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?(:[0-9]{1,5})?$")


_LABEL_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def normalize_public_base(v) -> str:
    """對外基準網址（Tunnel 公開網域）：只收 `https://主機[:埠]`，不可有路徑、查詢、帳密；末尾斜線容忍。不合法 ⇒ `ValueError`。空字串 ⇒ ""。
    主機的每一段（以 `.` 分隔）都要是合法標籤（不可有空段如 `a..b`）；埠號 1～65535。內網／私有位址不擋（管理者自己的決定）。"""
    s = str(v or "").strip().rstrip("/")
    if not s:
        return ""
    bad = ValueError("對外網址只能是 https://網域（可含埠號 1～65535），不可含路徑、查詢或帳號")
    if len(s) > 255 or not _PUBLIC_BASE_RE.match(s):
        raise bad
    hostport = s[len("https://"):]
    host, _, port = hostport.partition(":")
    if port and not (1 <= int(port) <= 65535):
        raise bad
    if not all(_LABEL_RE.match(x) for x in host.split(".")):
        raise bad
    return s


def public_base() -> str:
    """設定的對外網址；設定值壞掉（手改資料庫）也回 ""，不丟例外。"""
    try:
        return normalize_public_base(_cfg().get("public_base_url"))
    except ValueError:
        return ""


def callback_url() -> str:
    """LINE Login 的 Callback URL（要與 LINE Developers Console 登記的逐字相同）；沒有對外網址 ⇒ ""。
    ⚠️ 只代表「回調那一條路徑」的公開位置，**不代表訊息會帶連結**——連結由 `include_links` 另外控制。"""
    b = public_base()
    return b + CALLBACK_PATH if b else ""


def links_enabled() -> bool:
    """訊息是否帶連結：`include_links` 開 **且** 有對外網址。與「callback 要不要公開」是兩個獨立開關（預設關）。"""
    c = _cfg()
    return bool(c.get("include_links") is True and public_base())


def safe_link(link: str) -> str:
    """把信件用的連結轉成 LINE 可用的連結，或 ""（不帶）。
    ⇒ 連結關閉／沒有對外網址／不是 `/pages/<白名單頁面>`／不是 http(s)：一律 ""。
    通過時只取原連結的 path＋query，接在對外網址後面（內網網址不會外流）；其餘一律不帶。"""
    try:
        if not link or not links_enabled():
            return ""
        u = urllib.parse.urlsplit(str(link).strip())
        if u.scheme not in ("", "http", "https") or not u.path.startswith("/pages/"):
            return ""
        if u.path[len("/pages/"):] not in LINK_PAGES:
            return ""
        return public_base() + u.path + ("?" + u.query if u.query else "")
    except Exception:
        return ""


def build_text(title: str, rows=None, *, reason: str = "", link: str = "") -> str:
    """把一則通知排成純文字：標題、事由、`欄位：值` 逐行、連結（經 `safe_link`，預設不帶）。控制字元收成空白，過長截斷。"""
    def _one(s):
        return " ".join(str(s).replace("\r", " ").replace("\n", " ").split())
    lines = ["【MOTRIX】" + _one(title)]
    if reason:
        lines.append(_one(reason))
    for r in rows or []:
        try:
            k, v = r
        except Exception:
            continue
        lines.append("%s：%s" % (_one(k), _one(v)))
    sl = safe_link(link)
    if sl:
        lines.append(sl)
    text = "\n".join(lines)
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT - 1] + "…"


def _http(method: str, path: str, token: str, payload=None):
    """唯一的對外呼叫。回 `(status, body_dict)`；HTTP 錯誤也回（不拋）；連線層錯誤拋 URLError／OSError。測試換掉這支。"""
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(LINE_API_BASE + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + token)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8", "replace") or "{}")
        except Exception:
            body = {}
        return e.code, body


def _machine_may_send() -> bool:
    try:
        from .email_notify import email_send_policy     # 惰性 import：避免循環
        allowed, why = email_send_policy()
    except Exception:
        return True      # 讀不到政策＝維持預設「寄」（與 email_notify 同一理由：正式機誤停是看不見的那一側）
    if not allowed:
        logger.warning("LINE BLOCKED（%s）", why)
    return allowed


def _classify(status: int) -> str:
    if 200 <= status < 300:
        return SEND_SENT
    if status in (429,) or status >= 500:
        return SEND_TRANSIENT_FAIL          # 額度／限流／對方故障：之後重試有意義
    if status in (401, 403):
        return SEND_SKIPPED                 # token 失效或沒權限＝整台機器的設定問題，修好後要補寄（比照 SMTP 未設定）
    return SEND_PERMANENT_FAIL              # 400 等：這一則本身不可能成功（對象不合法、格式錯）


def push(user_ids, text: str) -> str:
    """推一則文字訊息給 `user_ids`（LINE userId 清單）。回 `SEND_*`；沒有對象＝permanent_fail。**永不丟例外。**

    一人用 push、多人用 multicast（每 500 人一批；任一批暫時失敗 ⇒ 整體 transient，其次 permanent，其次 skipped，全成功才 sent）。
    未啟用或沒有 token ⇒ skipped（機器層級；不 log token）。"""
    try:
        ids = [u for u in dict.fromkeys(user_ids or []) if isinstance(u, str) and u.strip()]
        c = _cfg()
        if not (c.get("enabled") and c.get("channel_access_token")):
            logger.info("LINE skipped — 未啟用或沒有 channel access token")
            return SEND_SKIPPED
        if not _machine_may_send():
            return SEND_SKIPPED
        if not ids:
            logger.warning("LINE skipped — 收件人（已綁定的 userId）為空")
            return SEND_PERMANENT_FAIL
        token = c["channel_access_token"]
        if not valid_token(token):
            logger.warning("LINE skipped — channel access token 格式不正確（請在設定頁重新貼上）")
            return SEND_SKIPPED
        text = str(text or "")[:MAX_TEXT]
        outcomes = []
        for i in range(0, len(ids), MULTICAST_LIMIT):
            chunk = ids[i:i + MULTICAST_LIMIT]
            msgs = [{"type": "text", "text": text}]
            if len(chunk) == 1:
                status, body = _http("POST", "/v2/bot/message/push", token, {"to": chunk[0], "messages": msgs})
            else:
                status, body = _http("POST", "/v2/bot/message/multicast", token, {"to": chunk, "messages": msgs})
            out = _classify(status)
            if out != SEND_SENT:
                logger.warning("LINE push failed: HTTP %s %s", status, (body or {}).get("message", ""))
            outcomes.append(out)
        for pick in (SEND_TRANSIENT_FAIL, SEND_PERMANENT_FAIL, SEND_SKIPPED):
            if pick in outcomes:
                return pick
        return SEND_SENT
    except Exception as exc:       # 連線層錯誤（逾時／DNS／TLS）一律暫時性：往「會重試」那一側倒
        logger.warning("LINE push error: %s", type(exc).__name__)      # 只記型別：例外訊息可能帶整串 token（K 審 S2）
        return SEND_TRANSIENT_FAIL


def push_async(user_ids, text: str) -> threading.Thread:
    """背景推播（不擋呼叫端）；回 daemon 執行緒（測試可 `.join()`）。結果只進 log——LINE 是附帶通道，失敗不影響信件與呼叫端的「已通知」記號。"""
    def _run():
        try:
            out = push(user_ids, text)
            if out != SEND_SENT:
                logger.info("LINE 推播結果：%s（對象 %d 人）", out, len(list(user_ids or [])))
            else:
                from . import line_quota as _lq            # 推成功＝額度可能變了：去抖動後刷新用量、跨門檻就告警（永不丟例外）
                _lq.after_push()
        except Exception as exc:                                # push 本身不丟例外；這裡是最後一道
            logger.warning("LINE 背景推播的執行緒自己炸了：%s", type(exc).__name__)
    t = threading.Thread(target=_run, daemon=True, name="line-push")
    t.start()
    return t


# ── 事件開關：哪些信件類型「同時發 LINE」（公司層、預設全關、逐類由最高管理者勾選）──────────────────────────
#: 已接上 LINE 的事件（＝設定頁可勾選的清單）＝信件登記表扣掉排除清單，加上 LINE-only／細項事件（見不變式 ⑫、`line_catalog`）；沒接線的不開放勾選。
#: 獎金、薪資、勞報單類**永遠排除**（使用者裁示 2026-11-13，`line_catalog.exclusion_reason`）；付款類（請款單、付款日提醒…）已開放，內容一律不帶金額（不變式 ⑤，呼叫端負責）。
#: 事件登記字典（單一來源）：每個已接線事件的屬性。
#:   priority   "critical"＝系統／資安告警，**永不因額度保留而暫停**；"normal"＝一般事件，本月用量達 `line_quota.RESERVE_PERCENT`（90%）後自動暫停（記 log）。
#:   digest     False＝逐則發送；（保留欄位：之後的批次用 "daily" 表示每日彙整，彙整事件在**發送當下**才解析收件人——`deliver_event` 本來就是發送當下才解析）。
#:   line_group "inherit"＝LINE 的群組收件人與信件相同（登記的預設群組）；None＝LINE 只發給事件收件人（不加群組）；或 `mail_types.GROUPS` 的鍵＝LINE 用另一個群組。
#:   audience   "any"＝所有角色都可能是收件人（本人設定頁列出該事件）；"group"＝只有群組收件人（管理者）才會收到，不是收件人的同仁在「我要收的 LINE 通知」看不到這個事件。
#:   month_cap_percent  None＝沒有每月上限；整數＝本月這個事件累計推播則數最多佔 LINE 月額度的幾 %（超過只發 Email；見不變式 ⑩）。
#:   mail_key  （選填）收件人設定（覆寫）借用哪個信件類型；沒給＝自己。LINE-only／細項事件由 `line_catalog` 帶入。
#: 這張表只列「與預設不同」的事件；其餘一律用 `DEFAULT_EVENT_SPEC`（見 `event_spec`）。
LINE_EVENTS = {
    "approval_review_edit": {"priority": "normal", "digest": False, "line_group": "inherit", "audience": "any", "month_cap_percent": None},
    "warranty_expiry": {"priority": "normal", "digest": False, "line_group": "inherit", "audience": "any", "month_cap_percent": None},
    "auth_lockout": {"priority": "critical", "digest": False, "line_group": "inherit", "audience": "group", "month_cap_percent": 25},
    # 系統告警（critical：永不因額度保留而暫停）
    "backup_error": {"priority": "critical", "digest": False, "line_group": "inherit"},
    "backup_stale": {"priority": "critical", "digest": False, "line_group": "inherit"},
    "heartbeat_stale": {"priority": "critical", "digest": False, "line_group": "inherit"},
    "disk_space_low": {"priority": "critical", "digest": False, "line_group": "inherit"},
    "cert_expiry": {"priority": "critical", "digest": False, "line_group": "inherit"},
    "license_expiry": {"priority": "critical", "digest": False, "line_group": "inherit"},       # 授權即將到期（30／14／7 天；最高管理者群組；T83 授權匯入票提供信件類型與每日檢查）
    "company_setup_alert": {"priority": "critical", "digest": False, "line_group": "inherit"},
    # 「核准完成」LINE 預設只給申請人（信件另寄管理員群組；PM 2026-11-13）
    "approved": {"priority": "normal", "digest": False, "line_group": None},
    # 量大的事件（模組動態、工作事項、CRM 拜訪／進度）：每月最多佔 LINE 月額度 15%（PM 裁示，審查 h8 L2；超過只發 Email，LINE 預設無上限方案不套）
    "module_activity": {"priority": "normal", "digest": False, "line_group": "inherit", "audience": "any", "month_cap_percent": 15},
    "daily_task_assigned": {"priority": "normal", "digest": False, "line_group": "inherit", "audience": "any", "month_cap_percent": 15},
    "daily_task_completed": {"priority": "normal", "digest": False, "line_group": "inherit", "audience": "any", "month_cap_percent": 15},
    "daily_task_overdue": {"priority": "normal", "digest": False, "line_group": "inherit", "audience": "any", "month_cap_percent": 15},
    "daily_task_overdue_manager": {"priority": "normal", "digest": False, "line_group": "inherit", "audience": "any", "month_cap_percent": 15},
    "daily_task_edited": {"priority": "normal", "digest": False, "line_group": "inherit", "audience": "any", "month_cap_percent": 15},
    "crm_visit_logged": {"priority": "normal", "digest": False, "line_group": None, "audience": "any", "month_cap_percent": 15},
    "crm_case_progress": {"priority": "normal", "digest": False, "line_group": None, "audience": "any", "month_cap_percent": 15},
}
#: 沒列在 `LINE_EVENTS` 的事件的預設屬性（簽核與指派類都是一般）
DEFAULT_EVENT_SPEC = {"priority": "normal", "digest": False, "line_group": "inherit", "audience": "any", "month_cap_percent": None}


def _cat_kind(event_key: str) -> str:
    from . import line_catalog as _cat
    return _cat.kind_of(event_key)


def event_spec(event_key: str) -> dict:
    """事件的完整屬性（預設 ＜ LINE-only／細項事件的目錄資料 ＜ `LINE_EVENTS` 覆寫）。回新的 dict（呼叫端改它不影響表）。"""
    from . import line_catalog as _cat
    spec = dict(DEFAULT_EVENT_SPEC)
    extra = _cat.LINE_ONLY_EVENTS.get(event_key)
    if extra:
        spec["line_group"] = extra.get("line_group", spec["line_group"])
        spec["mail_key"] = extra["mail_key"]
    ov = LINE_EVENTS.get(event_key)
    if isinstance(ov, dict):
        spec.update(ov)
    return spec


def is_wired(event_key) -> bool:
    """這個 key 有沒有接上 LINE（O(1)；不建清單）。"""
    from . import line_catalog as _cat
    return _cat.is_known(event_key)


def wired_events() -> tuple:
    """所有已接線的事件 key：信件登記表（扣掉排除清單）＋LINE-only／細項事件；依「分組順序、登記順序」排列。"""
    from . import line_catalog as _cat
    from . import mail_types as _mt
    keys = [t.key for t in _mt.all_types() if not _cat.exclusion_reason(t.key, t)]
    keys += [k for k in _cat.LINE_ONLY_EVENTS if k not in keys and not _cat.exclusion_reason(k)]
    order = {g: i for i, g in enumerate(_cat.GROUP_ORDER)}
    return tuple(sorted(keys, key=lambda k: order.get(_cat.group_of(k), len(order))))        # sorted 是穩定排序：同組維持登記順序


class _WiredEvents:
    """`WIRED_EVENTS` 的相容外殼：看起來像 tuple，但每次都讀 `wired_events()`（見不變式 ⑩）。"""
    def __iter__(self):
        return iter(wired_events())

    def __contains__(self, key):
        return is_wired(key)

    def __len__(self):
        return len(wired_events())

    def __getitem__(self, i):
        return wired_events()[i]

    def __repr__(self):
        return "WIRED_EVENTS%r" % (wired_events(),)


WIRED_EVENTS = _WiredEvents()
#: ⚠️ 2026-11-12（使用者裁示「全部改獨立」）：LINE **不再依附 Email**。收件人由 `helpers.event_audience` 直接依事件的業務收件人＋T80 收件設定解析成帳號，
#: 再 ⇒ LINE 角色允許清單 ⇒ 本人 LINE 勾選 ⇒ 已綁定（`deliver_event`）。沒有 Email、Email 退訂、信件類型被整個關掉，都不影響 LINE；
#: LINE 有自己的公司開關（`event_enabled`）與個人勾選，Email 退訂與 LINE 勾選互不影響。


def event_enabled(event_key: str) -> bool:
    """這種信件類型要不要同時發 LINE：LINE 已啟用（有 token）、類型已接線、管理者已勾選。"""
    try:
        c = _cfg()
        return bool(c.get("enabled") and c.get("channel_access_token") and event_key in WIRED_EVENTS
                    and _events().get(event_key) is True)
    except Exception:
        return False


def event_roles_view() -> dict:
    """⇒ {key: [role…]|None}（只含已接線的類型；None＝所有角色，沿用現行行為）。壞值照 `line_recipients.allowed_roles` 的規則（[]＝fail-closed）。"""
    from . import line_recipients as _lr
    return _lr.allowed_roles_view(wired_events())


def set_event_roles(event_key: str, roles) -> None:
    """設定單一類型「允許哪些角色收」。`roles=None` ⇒ 移除限制（所有角色）；list ⇒ 只收這些角色（可為空＝沒有角色）。
    不是已接線的類型、角色不在 `mail_types.ROLES`、不是 list／None ⇒ `ValueError`。"""
    if event_key not in WIRED_EVENTS:
        raise ValueError("這種通知尚未支援 LINE：%s" % event_key)
    if roles is not None:
        from .mail_types import ROLES
        if not isinstance(roles, list) or not all(isinstance(r, str) and r in ROLES for r in roles):
            raise ValueError("roles 必須是角色清單（%s）或 null" % "、".join(ROLES))
        roles = list(dict.fromkeys(roles))
    with _lock:
        c = dict(_cfg())
        er = dict(c.get("event_roles") if isinstance(c.get("event_roles"), dict) else {})
        if roles is None:
            if event_key not in er:
                return
            er.pop(event_key)
        else:
            if er.get(event_key) == roles:
                return
            er[event_key] = roles
        c["event_roles"] = er
        _set_setting(SETTING_KEY, c)


def events_view() -> dict:
    """⇒ {key: bool}（只含已接線的類型；缺項＝關）。"""
    ev = _events()
    return {k: ev.get(k) is True for k in WIRED_EVENTS}


def set_event(event_key: str, on: bool, default_user: str = None) -> bool:
    """寫入單一類型的開關。不是已接線的類型 ⇒ `ValueError`（不留死開關）。

    `default_user`（操作者帳號；router 傳入）：事件從關切到開、而且還沒有指定收件對象時，套用預設「只發給我」（見不變式 ⑭）。
    ⇒ 是否套用了預設對象（True／False）。不帶 `default_user`＝與過去逐位元相同。"""
    if event_key not in WIRED_EVENTS:
        raise ValueError("這種通知尚未支援 LINE：%s" % event_key)
    if not isinstance(on, bool):
        raise ValueError("enabled 必須是 true 或 false")
    with _lock:
        c, _changed, defaulted, _crit = _plan_batch(_cfg(), [event_key], on, None, False, None, default_user)
        _set_setting(SETTING_KEY, c)
    return bool(defaulted)


# ── 管理員指定「誰要發」（2026-11-13）：每個事件一份 {mode, roles, users}，存 `system_settings.line_notify.audiences` ──────────────────
#: mode：`business`（預設，不存＝此模式）＝業務收件人∩角色允許清單；`business_plus`＝再加上指定的角色與個人；`only`＝只發指定的角色與個人。
#: 讀取與套用在 `line_recipients.resolve_audience`；這裡只負責寫入與驗證（與事件開關、角色允許清單共用 `_lock`）。
AUDIENCE_MODES = ("business", "business_plus", "only")
MAX_AUDIENCE_USERS = 200


def audience_view() -> dict:
    """⇒ {key: {"mode", "roles", "users"}}（只含已接線事件；沒設定＝`business`、空清單）。壞值照 `line_recipients.audience_of` 的規則。"""
    from . import line_recipients as _lr
    return _lr.audience_view(wired_events())


def _check_audience(event_key: str, mode: str, roles=None, users=None):
    """驗證並整理一份「誰要發」⇒ `(roles, users)`（去重、strip）。**不碰 `_lock`**（含資料庫查詢）。
    不是已接線事件、mode 不合法、角色不在 `mail_types.ROLES`、帳號不存在、指定的人沒有該事件所屬模組權限 ⇒ `ValueError`。"""
    if not is_wired(event_key):
        raise ValueError("這種通知尚未支援 LINE：%s" % event_key)
    if mode not in AUDIENCE_MODES:
        raise ValueError("mode 必須是 %s" % "、".join(AUDIENCE_MODES))
    from .mail_types import ROLES
    roles = [] if roles is None else roles
    users = [] if users is None else users
    if not isinstance(roles, list) or not all(isinstance(r, str) and r in ROLES for r in roles):
        raise ValueError("roles 必須是角色清單（%s）" % "、".join(ROLES))
    if not isinstance(users, list) or not all(isinstance(u, str) and u.strip() for u in users):
        raise ValueError("users 必須是帳號清單")
    roles = list(dict.fromkeys(roles))
    users = list(dict.fromkeys(u.strip() for u in users))
    if len(users) > MAX_AUDIENCE_USERS:
        raise ValueError("指定的人員最多 %d 位" % MAX_AUDIENCE_USERS)
    if mode != "business" and not roles and not users:
        raise ValueError("「%s」模式至少要指定一個角色或一位人員" % ("另外加上" if mode == "business_plus" else "只發給"))
    if mode == "business" and (roles or users):
        raise ValueError("「照原本的收件人」模式不需要指定角色或人員（要加人請選「另外加上」）")
    if users:                                                                     # 帳號必須存在（停用的也可以存；發送時才濾掉）
        from db import get_db
        conn = get_db()
        try:
            known = set()
            for i in range(0, len(users), 400):
                chunk = users[i:i + 400]
                known |= {r["username"] for r in conn.execute("SELECT username FROM users WHERE username IN (%s)" % ",".join("?" * len(chunk)), chunk).fetchall()}
        finally:
            conn.close()
        missing = [u for u in users if u not in known]
        if missing:
            raise ValueError("找不到帳號：%s" % "、".join(missing[:5]))
        from . import line_recipients as _lr2
        denied = _lr2.ineligible_users(event_key, users)                              # 審查 h8 M1：指定的人要有該事件所屬模組的權限
        if denied:
            raise ValueError("這些人沒有這種通知所屬模組的使用權限，不能指定：%s" % "、".join(denied[:5]))
    return roles, users


def set_audience(event_key: str, mode: str, roles=None, users=None) -> None:
    """寫入單一事件的「誰要發」。驗證見 `_check_audience`（不合法 ⇒ `ValueError`）。
    `business` 模式且沒有角色與個人 ⇒ 把該事件的設定拿掉（設定值不會越長越大）；`business_plus`／`only` 至少要有一個角色或個人。"""
    roles, users = _check_audience(event_key, mode, roles, users)
    with _lock:
        c = dict(_cfg())
        aud = dict(c.get("audiences") if isinstance(c.get("audiences"), dict) else {})
        if mode == "business":
            if event_key not in aud:
                return
            aud.pop(event_key)
        else:
            new = {"mode": mode, "roles": roles, "users": users}
            if aud.get(event_key) == new:
                return
            aud[event_key] = new
        c["audiences"] = aud
        _set_setting(SETTING_KEY, c)


# ── 批次設定（2026-11-13，LINE 事件矩陣票；不變式 ⑭）──────────────────────────────────────────────────────
BATCH_MAX_KEYS = 100
_UNSET = object()          # `roles` 參數：沒帶（不動角色篩選）≠ None（移除角色篩選＝所有角色）


class BatchConflict(ValueError):
    """「復原這一批」時，有事件在套用之後被別人（或別的視窗）改過 ⇒ 整批拒絕復原（不蓋掉別人的修改）。`.keys`＝被改過的事件。"""

    def __init__(self, keys):
        super().__init__("這些事件在你套用之後又被改過：%s" % "、".join(keys[:5]))
        self.keys = list(keys)


class CriticalConfirmRequired(ValueError):
    """批次關閉了「重要」告警的事件，卻沒有帶確認旗標。`keys`＝需要確認的事件。"""

    def __init__(self, keys):
        self.keys = list(keys)
        super().__init__("要關閉的事件包含「重要」系統告警（%s），必須明確確認" % "、".join(self.keys[:5]))


def _is_critical(event_key: str) -> bool:
    return event_spec(event_key).get("priority") == "critical"


def _state_token(cfg: dict, k: str) -> str:
    """事件 k 目前「開關＋誰要發＋角色篩選」的短指紋（給「復原這一批」比對：套用後記下、復原時比、不一樣 ⇒ 被改過）。"""
    import hashlib
    ev = cfg.get("events") if isinstance(cfg.get("events"), dict) else {}
    aud = cfg.get("audiences") if isinstance(cfg.get("audiences"), dict) else {}
    er = cfg.get("event_roles") if isinstance(cfg.get("event_roles"), dict) else {}
    raw = json.dumps([ev.get(k) is True, aud.get(k), er.get(k, "∅")], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _plan_batch(cfg: dict, keys, enabled, audience, roles_given: bool, event_roles, default_user):
    """**純函式**（不讀寫設定、不碰資料庫）：把批次套在 `cfg` 的副本上 ⇒ `(新設定, changed, defaulted, critical_off)`。
    `audience`＝None（不動）或已驗證的 `{"mode", "roles", "users"}`；`event_roles` 只在 `roles_given` 時有意義（None＝移除角色篩選）。
    mode=`business` 會拿掉 `audiences[key]`，但**保留** `event_roles`（兩者是不同的概念，見不變式 ⑬）。"""
    c = dict(cfg)
    ev = dict(c.get("events") if isinstance(c.get("events"), dict) else {})
    aud = dict(c.get("audiences") if isinstance(c.get("audiences"), dict) else {})
    er = dict(c.get("event_roles") if isinstance(c.get("event_roles"), dict) else {})
    changed, defaulted, critical_off = [], [], []
    for k in keys:
        was_on = ev.get(k) is True
        before = (was_on, aud.get(k), er.get(k, _UNSET))
        if enabled is not None:
            if enabled and not was_on and audience is None and default_user and k not in aud:
                aud[k] = {"mode": "only", "roles": [], "users": [default_user]}        # 新預設：只發給操作者本人
                defaulted.append(k)
            if enabled is False and was_on and _is_critical(k):
                critical_off.append(k)
            ev[k] = enabled
        if audience is not None:
            if audience["mode"] == "business":
                aud.pop(k, None)
            else:
                aud[k] = {"mode": audience["mode"], "roles": list(audience["roles"]), "users": list(audience["users"])}
        if roles_given:
            if event_roles is None:
                er.pop(k, None)
            else:
                er[k] = list(event_roles)
        if (ev.get(k) is True, aud.get(k), er.get(k, _UNSET)) != before:
            changed.append(k)
    c["events"] = ev
    if audience is not None or defaulted:
        c["audiences"] = aud
    if roles_given:
        c["event_roles"] = er
    return c, changed, defaulted, critical_off


def _batch_inputs(keys, enabled, audience, roles, confirm_critical):
    """批次輸入的整理與驗證（進鎖前；含資料庫查詢）⇒ `(keys, roles_given, ev_roles, norm_aud)`。`set_events_batch` 與 `preview_events_batch` 共用，規則只有一份。"""
    if not isinstance(keys, (list, tuple)) or not all(isinstance(k, str) for k in keys):
        raise ValueError("keys 必須是事件代碼的清單")
    keys = list(dict.fromkeys(keys))
    if not keys or len(keys) > BATCH_MAX_KEYS:
        raise ValueError("一次要選 1～%d 個事件" % BATCH_MAX_KEYS)
    unknown = [k for k in keys if k not in WIRED_EVENTS]
    if unknown:
        raise ValueError("這些通知尚未支援 LINE：%s" % "、".join(unknown[:5]))
    if enabled is not None and not isinstance(enabled, bool):
        raise ValueError("enabled 必須是 true 或 false")
    if not isinstance(confirm_critical, bool):
        raise ValueError("confirm_critical 必須是 true 或 false")
    roles_given = roles is not _UNSET
    if roles_given and roles is not None:
        from .mail_types import ROLES
        if not isinstance(roles, list) or not all(isinstance(r, str) and r in ROLES for r in roles):
            raise ValueError("roles 必須是角色清單（%s）或 null" % "、".join(ROLES))
        roles = list(dict.fromkeys(roles))
    ev_roles = roles if roles_given else None
    norm_aud = None
    if audience is not None:
        if not isinstance(audience, dict) or "mode" not in audience:
            raise ValueError("audience 必須是 {mode, roles, users}")
        # ⚠️ 全部在進鎖前驗證（含 ineligible_users 的資料庫查詢）：`_lock` 不可重入，鎖內不能再呼叫 set_audience／set_event
        r0, u0 = None, None
        for k in keys:
            r0, u0 = _check_audience(k, audience["mode"], audience.get("roles"), audience.get("users"))
        norm_aud = {"mode": audience["mode"], "roles": r0, "users": u0}
    if enabled is None and norm_aud is None and not roles_given:
        raise ValueError("沒有要改的項目（enabled／audience／roles 至少要有一個）")
    return keys, roles_given, ev_roles, norm_aud


def set_events_batch(keys, enabled=None, audience=None, roles=_UNSET, confirm_critical: bool = False, default_user: str = None) -> dict:
    """一次改多個事件的 開關／誰要發／角色篩選；**全部成功或全部不改**（整批只寫一次 `_set_setting`）。

    keys：1～`BATCH_MAX_KEYS` 個事件 key（去重、保持順序），必須全是已接線事件。
    enabled：None（不動）／True／False（嚴格布林）。audience：None（不動）／`{"mode", "roles"?, "users"?}`（規則同 `set_audience`，含「指定的人要有該事件所屬模組的權限」）。
    roles：沒帶＝不動；None＝移除角色篩選（所有角色）；list＝只收這些角色。confirm_critical：要關閉「重要」告警時必須為 True。
    default_user：事件從關切到開、且沒有指定對象時套用「只發給我」（不變式 ⑭）。
    ⇒ `{"changed", "unchanged", "defaulted", "critical_off"}`（事件 key 清單）。不合法 ⇒ `ValueError`；缺確認 ⇒ `CriticalConfirmRequired`（是 ValueError 的子類）。"""
    keys, roles_given, ev_roles, norm_aud = _batch_inputs(keys, enabled, audience, roles, confirm_critical)
    crit0 = _plan_batch(_cfg(), keys, enabled, norm_aud, roles_given, ev_roles, default_user)[3]
    if crit0 and not confirm_critical:
        raise CriticalConfirmRequired(crit0)
    with _lock:
        if any(k not in WIRED_EVENTS for k in keys):                                  # 進鎖後複查：驗證到寫入之間模組可能被停用
            raise ValueError("有事件已不在支援 LINE 的清單內，請重新整理")
        c, changed, defaulted, crit = _plan_batch(_cfg(), keys, enabled, norm_aud, roles_given, ev_roles, default_user)
        if crit and not confirm_critical:                                             # 驗證到寫入之間別人把事件打開了
            raise CriticalConfirmRequired(crit)
        if changed or enabled is not None:
            _set_setting(SETTING_KEY, c)
        after = {k: _state_token(c, k) for k in keys}
    return {"changed": changed, "unchanged": [k for k in keys if k not in changed], "defaulted": defaulted, "critical_off": crit, "after": after}


def preview_events_batch(keys, enabled=None, audience=None, roles=_UNSET, default_user: str = None) -> dict:
    """批次預覽（**不寫入、不記稽核**）：同 `set_events_batch` 的輸入與驗證，回每個事件套用前後的開關、可能收件人數與每月則數估算。
    ⇒ `{"events": [{key, enabled_before, enabled_after, n_before, n_after, exact_after, sent30, est_after, changed, defaulted, critical_off}], "total": {...}}`。
    估算：以該事件近 30 天實際推播數（`sent30`）按「可能收件人數」的比例推算套用後的每月則數（`est_after`）；沒有歷史（sent30＝0）或套用前人數為 0 ⇒ `None`（無法估算）。
    關閉事件 ⇒ 0。人數是上限（見 `line_recipients.potential_counts`）。`total` 把能估算的相加，`unknown`＝無法估算的事件數。"""
    from . import line_recipients as _lr
    keys, roles_given, ev_roles, norm_aud = _batch_inputs(keys, enabled, audience, roles, False)
    cfg = _cfg()
    new_cfg, changed, defaulted, crit = _plan_batch(cfg, keys, enabled, norm_aud, roles_given, ev_roles, default_user)
    before = _lr.potential_counts(keys, roles_map=cfg.get("event_roles") if isinstance(cfg.get("event_roles"), dict) else {},
                                  aud_map=cfg.get("audiences") if isinstance(cfg.get("audiences"), dict) else {})
    after = _lr.potential_counts(keys, roles_map=new_cfg.get("event_roles") if isinstance(new_cfg.get("event_roles"), dict) else {},
                                 aud_map=new_cfg.get("audiences") if isinstance(new_cfg.get("audiences"), dict) else {})
    sent = usage_daily_view(30)["by_event"]
    ev0 = cfg.get("events") if isinstance(cfg.get("events"), dict) else {}
    ev1 = new_cfg.get("events") if isinstance(new_cfg.get("events"), dict) else {}
    rows, tot_now, tot_after, unknown = [], 0, 0, 0
    for k in keys:
        on0, on1 = ev0.get(k) is True, ev1.get(k) is True
        s30 = int(sent.get(k, 0) or 0)
        n0, n1 = before[k]["n"], after[k]["n"]
        if not on1:
            est = 0
        elif s30 > 0 and n0 > 0:
            est = int(round(s30 * n1 / n0))
        else:
            est = None
        tot_now += s30
        if est is None:
            unknown += 1
        else:
            tot_after += est
        rows.append({"key": k, "enabled_before": on0, "enabled_after": on1, "n_before": n0, "n_after": n1, "exact_after": after[k]["exact"],
                     "sent30": s30, "est_after": est, "changed": k in changed, "defaulted": k in defaulted, "critical_off": k in crit})
    return {"events": rows, "total": {"sent30": tot_now, "est_after": tot_after, "unknown": unknown}}


def restore_events_batch(states, expect) -> dict:
    """「復原這一批」：把每個事件寫回套用前的狀態，**前提是它們從套用到現在都沒被別人改過**。
    states：`{key: {"enabled": bool, "audience": {"mode","roles","users"}, "roles": None|[角色…]}}`；expect：`{key: 套用後的指紋}`（`set_events_batch` 回的 `after`）。
    全部成功或全部不改（一次 `_set_setting`）；任何一個事件的指紋與現在不同 ⇒ `BatchConflict`（整批不復原）；內容不合法 ⇒ `ValueError`。
    ⇒ `{"restored": [key…], "after": {key: 指紋}}`。不要求 confirm_critical：復原只是把事件寫回使用者自己先前的狀態。"""
    if not isinstance(states, dict) or not isinstance(expect, dict) or not states or len(states) > BATCH_MAX_KEYS:
        raise ValueError("states／expect 必須是 {事件代碼: …}（1～%d 個）" % BATCH_MAX_KEYS)
    if set(states) != set(expect):
        raise ValueError("states 與 expect 的事件代碼必須一致")
    keys = list(states)
    unknown = [k for k in keys if not isinstance(k, str) or k not in WIRED_EVENTS]
    if unknown:
        raise ValueError("這些通知尚未支援 LINE：%s" % "、".join(str(x) for x in unknown[:5]))
    if not all(isinstance(expect[k], str) for k in keys):
        raise ValueError("expect 的值必須是字串")
    from .mail_types import ROLES
    plan = {}
    for k in keys:                                                      # 全部在進鎖前驗證（`_lock` 不可重入）
        st = states[k]
        if not isinstance(st, dict) or not isinstance(st.get("enabled"), bool) or not isinstance(st.get("audience"), dict) or "mode" not in st["audience"]:
            raise ValueError("%s 的狀態格式不正確（要有 enabled、audience）" % k)
        rl = st.get("roles")
        if rl is not None and (not isinstance(rl, list) or not all(isinstance(r, str) and r in ROLES for r in rl)):
            raise ValueError("%s 的 roles 必須是角色清單或 null" % k)
        a = st["audience"]
        r0, u0 = _check_audience(k, a["mode"], a.get("roles"), a.get("users"))
        plan[k] = (st["enabled"], {"mode": a["mode"], "roles": r0, "users": u0}, None if rl is None else list(dict.fromkeys(rl)))
    with _lock:
        cfg = _cfg()
        stale = [k for k in keys if _state_token(cfg, k) != expect[k]]
        if stale:
            raise BatchConflict(stale)
        c = cfg
        for k in keys:
            en, aud, rl = plan[k]
            c = _plan_batch(c, [k], en, aud, True, rl, None)[0]
        _set_setting(SETTING_KEY, c)
        after = {k: _state_token(c, k) for k in keys}
    return {"restored": keys, "after": after}


# ── 綁定：系統帳號 ⇄ LINE userId ──────────────────────────────────────────────────────────────────────────
#: 存 `system_settings.line_links = {username: {"userId", "linkedAt"}}`。⚠️ 刻意不動資料庫 schema：核心 migration 已凍結在基準 118，
#: 新增核心表／欄位要走列車編號且與別的分支撞號；使用者數是幾十人、綁定／解除很少發生，一個 JSON 設定值足夠。
#: 讀改寫用行程內的鎖保護（單一伺服器行程；若改多 worker 要換成資料表）。
LINKS_KEY = "line_links"
_USER_ID_RE = re.compile(r"^U[0-9a-f]{32}$")
_lock = threading.Lock()


def _links() -> dict:
    v = _get_setting(LINKS_KEY, {}) or {}
    return v if isinstance(v, dict) else {}


def link_user(username: str, line_user_id: str) -> None:
    """綁定。userId 格式不對 ⇒ `ValueError`；這個 LINE 帳號已綁在**別的**系統帳號 ⇒ `ValueError`（不讓通知送錯人）；同一帳號重綁＝換成新的。"""
    uid = str(line_user_id or "").strip()
    if not username or not _USER_ID_RE.match(uid):
        raise ValueError("LINE userId 格式不正確")
    with _lock:
        links = dict(_links())
        for other, rec in links.items():
            if other != username and isinstance(rec, dict) and rec.get("userId") == uid:
                raise ValueError("這個 LINE 帳號已綁定給其他系統帳號")
        links[username] = {"userId": uid, "linkedAt": datetime.now().isoformat(timespec="seconds")}
        _set_setting(LINKS_KEY, links)


def unlink_user(username: str) -> bool:
    """解除綁定；原本就沒綁 ⇒ False。"""
    with _lock:
        links = dict(_links())
        if username not in links:
            return False
        links.pop(username)
        _set_setting(LINKS_KEY, links)
        return True


def is_linked(username: str) -> bool:
    rec = _links().get(username)
    return isinstance(rec, dict) and bool(_USER_ID_RE.match(str(rec.get("userId") or "")))


def set_confirmed(username: str, ok) -> None:
    """記下「綁定後確認訊息」的結果：True＝推送成功、False＝LINE 回永久失敗（常見：Login 與 Messaging channel 不在同一 Provider）、None＝沒驗。沒綁定 ⇒ 什麼都不做。"""
    with _lock:
        links = dict(_links())
        rec = links.get(username)
        if not isinstance(rec, dict):
            return
        rec = dict(rec)
        if ok is None:
            rec.pop("confirmed", None)
        else:
            rec["confirmed"] = bool(ok)
        links[username] = rec
        _set_setting(LINKS_KEY, links)


def binding_view(username: str) -> dict:
    """給使用者自己看的綁定狀態；**不含 userId**（那是 LINE 端的識別碼，沒必要回到瀏覽器）。"""
    rec = _links().get(username)
    if not (isinstance(rec, dict) and _USER_ID_RE.match(str(rec.get("userId") or ""))):
        return {"linked": False, "linkedAt": "", "confirmed": None}
    c = rec.get("confirmed")
    return {"linked": True, "linkedAt": str(rec.get("linkedAt") or ""), "confirmed": c if isinstance(c, bool) else None}


def ids_for(usernames) -> list:
    """帳號 ⇒ 已綁定者的 LINE userId（保持順序、去重；沒綁的略過）。"""
    links = _links()
    out = []
    for u in dict.fromkeys(usernames or []):
        rec = links.get(u)
        uid = str((rec or {}).get("userId") or "") if isinstance(rec, dict) else ""
        if _USER_ID_RE.match(uid) and uid not in out:
            out.append(uid)
    return out


MARKS_KEY = "line_push_marks"
#: 「已推播」記號的保存天數（超過就清掉；每日檢查型事件最多隔天重試，14 天綽綽有餘）
MARK_KEEP_DAYS = 14
USAGE_KEY = "line_event_usage"
PENDING_KEY = "line_pending"
#: 補發佇列：超過這麼多天還沒送出就放棄（記 log）
PENDING_TTL_DAYS = 3
#: LINE 讀不到月上限時，每月上限的假設值（正式機已確認是免費方案：每月 200 則）
MONTHLY_LIMIT_FALLBACK = 200
_marks_lock = threading.Lock()
_pending_lock = threading.Lock()
#: 鑰匙以「|YYYY-MM-DD」結尾＝每日告警（沒有特定對象）：隔天的檢查會自己重新評估，**不進補發佇列**（補發昨天的只會讓隔天雙推；審查 h8 L4）
_DAY_SUFFIX_RE = re.compile(r"\|\d{4}-\d{2}-\d{2}$")
_key_locks = {}                       # dedupe_key -> Lock（每把鑰匙一個：「查已推播→推播→寫記號」不可並發）
_key_locks_guard = threading.Lock()
_KEY_LOCKS_MAX = 512


def _key_lock(key: str):
    """這把 dedupe_key 專用的鎖（同一把鑰匙的並發呼叫——當日發送與補發佇列、多執行緒——串行化，第二個進來時記號已寫好 ⇒ `already_pushed`）。
    字典過大時順手丟掉目前沒人持有的鎖（鑰匙只會越用越多；丟掉的鎖若剛好被人拿在手上，最壞＝那一瞬間同鑰匙多一把鎖，機率極低）。"""
    with _key_locks_guard:
        lk = _key_locks.get(key)
        if lk is None:
            if len(_key_locks) >= _KEY_LOCKS_MAX:
                for k in [k for k, v in _key_locks.items() if not v.locked()]:
                    del _key_locks[k]
            lk = _key_locks[key] = threading.Lock()
        return lk


def _mark_seen(key: str) -> bool:
    try:
        v = _get_setting(MARKS_KEY, {}) or {}
        return isinstance(v, dict) and key in v
    except Exception:  # noqa: BLE001
        return False


def _mark_write(key: str) -> None:
    """記下「這一則已經推過了」（只在有 `dedupe_key` 且結果不是暫時失敗時才寫；順手清掉過期的）。永不丟例外。"""
    try:
        now = datetime.now()
        with _marks_lock:
            v = _get_setting(MARKS_KEY, {}) or {}
            v = dict(v) if isinstance(v, dict) else {}
            cut = (now - timedelta(days=MARK_KEEP_DAYS)).isoformat(timespec="seconds")
            v = {k: t for k, t in v.items() if isinstance(t, str) and t >= cut}
            v[key] = now.isoformat(timespec="seconds")
            _set_setting(MARKS_KEY, v)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LINE 已推播記號寫入失敗：%s", type(exc).__name__)


def month_cap_percent(event_key: str):
    """這個事件的每月上限（佔月額度的整數百分比）；沒有上限＝None。設定 `line_notify.month_cap_percent[事件]`（整數 0～100）優先於字典預設。"""
    try:
        ov = _cfg().get("month_cap_percent")
        if isinstance(ov, dict) and event_key in ov:
            v = ov[event_key]
            if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 100:
                return v
        v = (LINE_EVENTS.get(event_key) or {}).get("month_cap_percent")
        return v if isinstance(v, int) and not isinstance(v, bool) else None
    except Exception:  # noqa: BLE001
        return None


def _month_now() -> str:
    from . import line_quota as _lq
    return _lq.month_key()


def _usage_of(event_key: str) -> int:
    """這個事件本月累計推播則數（換月歸零）。"""
    try:
        v = _get_setting(USAGE_KEY, {}) or {}
        if not isinstance(v, dict) or v.get("month") != _month_now():
            return 0
        n = (v.get("events") or {}).get(event_key)
        return n if isinstance(n, int) and n >= 0 else 0
    except Exception:  # noqa: BLE001
        return 0


def _usage_add(event_key: str, n: int) -> None:
    try:
        with _marks_lock:
            v = _get_setting(USAGE_KEY, {}) or {}
            m = _month_now()
            ev = dict(v.get("events") or {}) if isinstance(v, dict) and v.get("month") == m else {}
            ev[event_key] = (ev.get(event_key) if isinstance(ev.get(event_key), int) else 0) + int(n)
            _set_setting(USAGE_KEY, {"month": m, "events": ev})
            _usage_daily_add(event_key, int(n))            # 按日計數（不變式 ⑮）；失敗只記 log，不影響上面的本月計數
    except Exception as exc:  # noqa: BLE001
        logger.warning("LINE 事件用量記錄寫入失敗：%s", type(exc).__name__)


# ── 按日計數（不變式 ⑮）：日期一律台灣時區 ──
try:
    from zoneinfo import ZoneInfo
    _TW = ZoneInfo("Asia/Taipei")
except Exception:  # noqa: BLE001 — 環境沒有時區資料庫（Windows 常見）⇒ 固定 +8（台灣沒有日光節約）
    from datetime import timezone
    _TW = timezone(timedelta(hours=8))
USAGE_DAILY_KEEP_DAYS = 31
USAGE_SINCE_KEY = "line_event_usage_since"
_usage_pruned_day = ""


def _tw_today(now: datetime = None):
    """台灣時區的今天（date）。`now`＝帶時區的時間（測試用）；沒帶時區的當成已經是台灣時間。"""
    if now is None:
        return datetime.now(_TW).date()
    return (now.astimezone(_TW) if now.tzinfo else now).date()


def _usage_daily_add(event_key: str, n: int, now: datetime = None) -> None:
    """今天（台灣）的事件則數 +n；順手清掉超過 `USAGE_DAILY_KEEP_DAYS` 天的（每行程每天最多清一次）。呼叫端持有 `_marks_lock`。永不丟例外。"""
    global _usage_pruned_day
    try:
        from db import get_db
        today = _tw_today(now)
        day = today.isoformat()
        conn = get_db()
        try:
            conn.execute("INSERT INTO line_event_usage_daily (day, event_key, n) VALUES (?, ?, ?) "
                         "ON CONFLICT(day, event_key) DO UPDATE SET n = n + excluded.n", (day, event_key, int(n)))
            if _usage_pruned_day != day:
                conn.execute("DELETE FROM line_event_usage_daily WHERE day < ?", ((today - timedelta(days=USAGE_DAILY_KEEP_DAYS - 1)).isoformat(),))
                _usage_pruned_day = day
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("LINE 按日用量寫入失敗：%s", type(exc).__name__)


def usage_daily_view(days: int = 30, now: datetime = None) -> dict:
    """近 `days` 天（含今天，台灣時區）各事件推出幾則 ⇒ `{"days", "accumulated_days", "complete", "total", "by_event"}`。
    `accumulated_days`＝已經累積了幾天（從 `line_event_usage_since` 起算，最多 `days`）；`complete`＝滿 `days` 天。讀不到（表不存在）⇒ 全 0、`complete=False`。永不丟例外。"""
    out = {"days": days, "accumulated_days": 0, "complete": False, "total": 0, "by_event": {}}
    try:
        from db import get_db
        today = _tw_today(now)
        start = (today - timedelta(days=days - 1)).isoformat()
        conn = get_db()
        try:
            rows = conn.execute("SELECT event_key, SUM(n) AS n FROM line_event_usage_daily WHERE day >= ? AND day <= ? GROUP BY event_key",
                                (start, today.isoformat())).fetchall()
        finally:
            conn.close()
        by = {r["event_key"]: int(r["n"] or 0) for r in rows}
        since = _get_setting(USAGE_SINCE_KEY, "") or ""
        try:
            first = datetime.strptime(since, "%Y-%m-%d").date()
            acc = max(1, min(days, (today - first).days + 1))
        except (ValueError, TypeError):
            acc = 1
        out.update(accumulated_days=acc, complete=acc >= days, total=sum(by.values()), by_event=by)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LINE 按日用量讀取失敗：%s", type(exc).__name__)
    return out


def _monthly_limit():
    """LINE 月額度上限（整數），或 `None`＝**LINE 回報無上限（付費方案）⇒ 每月上限不適用**。
    本月狀態有讀到用量但沒有上限 ⇒ `None`（只剩 `auth_alert` 的每小時／每日上限）；有上限 ⇒ 該值；
    **讀不到／不是本月的狀態**（沒讀過、讀取失敗）⇒ 保守用 `MONTHLY_LIMIT_FALLBACK`（免費方案 200）。"""
    try:
        from . import line_quota as _lq
        st = _lq._state()
        if st.get("month") == _lq.month_key():
            lim = st.get("limit")
            if isinstance(lim, int) and not isinstance(lim, bool) and lim > 0:
                return lim
            used = st.get("used")
            if lim is None and isinstance(used, int) and not isinstance(used, bool):
                return None
    except Exception:  # noqa: BLE001
        pass
    return MONTHLY_LIMIT_FALLBACK


def _pending_add(key: str, payload: dict) -> None:
    try:
        with _pending_lock:
            v = _get_setting(PENDING_KEY, {}) or {}
            v = dict(v) if isinstance(v, dict) else {}
            if key not in v:                                   # 第一次失敗的時間才算數（TTL 從這裡起算）
                v[key] = {"created": datetime.now().isoformat(timespec="seconds"), "args": payload}
                _set_setting(PENDING_KEY, v)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LINE 補發佇列寫入失敗：%s", type(exc).__name__)


def _pending_remove(key: str) -> None:
    try:
        with _pending_lock:
            v = _get_setting(PENDING_KEY, {}) or {}
            if isinstance(v, dict) and key in v:
                v = dict(v)
                v.pop(key)
                _set_setting(PENDING_KEY, v)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LINE 補發佇列移除失敗：%s", type(exc).__name__)


def deliver_event(event_key: str, *, usernames=None, to_group: bool = False, title: str, rows=None, reason: str = "", link: str = "",
                  exclude=None, dedupe_key: str = "", group: str = None) -> str:
    """獨立通道的**單一入口（同步）**：事件業務收件人 ⇒ LINE 角色允許清單／個人勾選 ⇒ 已綁定 ⇒ 推播（成功後觸發額度刷新與 T80 額度告警）。
    回傳：`"off"`（LINE 未啟用／類型沒接線或沒勾選）、`"already_pushed"`（同 `dedupe_key` 已推過）、`"paused_quota"`（額度保留：非 critical 且本月用量已達 90%）、
    `"monthly_cap"`（這個事件的每月上限已滿，只發 Email）、`"no_recipient"`（沒有可推播的人）、或 `SEND_*`。**永不丟例外。**
    `usernames`／`to_group`／`group`（呼叫端指定群組，優先於字典 `line_group`）／`exclude`（要排除的帳號，例如操作者本人）見 `helpers.event_audience.resolve_usernames`；
    LINE-only／細項事件的收件人設定借用 `mail_key`（`event_spec`）。
    `dedupe_key`（選填，給每日檢查型、會被重試的呼叫端）：LINE 自己的「已推播」記號——同一把鑰匙只推一次，**結果不是暫時失敗（sent／permanent）就記**，
    與 Email 的重試脫鉤（Email 暫時失敗隔天重試時，LINE 不會天天重推）。記號存在 `system_settings.line_push_marks`，保存 `MARK_KEEP_DAYS` 天。
    鑰匙的第一段必須是事件 key（`<event_key>|…`，補發佇列靠它找回事件）。
    帶 `dedupe_key` 且這次因額度保留／暫時失敗／token 失效（skipped）沒送出 ⇒ 記進補發佇列（不變式 ⑪），由每日檢查重送——Email 寄成功不會讓 LINE 被當成完成。
    **同一把 `dedupe_key` 的並發呼叫串行化**（per-key 鎖包住「查記號→推播→寫記號」；暫時失敗不寫記號，所以之後仍可重試）。"""
    if dedupe_key:
        try:
            lk = _key_lock(dedupe_key)
        except Exception:  # noqa: BLE001
            lk = None
        if lk is not None:
            with lk:
                return _deliver_unlocked(event_key, usernames=usernames, to_group=to_group, title=title, rows=rows,
                                         reason=reason, link=link, exclude=exclude, dedupe_key=dedupe_key, group=group)
    return _deliver_unlocked(event_key, usernames=usernames, to_group=to_group, title=title, rows=rows,
                             reason=reason, link=link, exclude=exclude, dedupe_key=dedupe_key, group=group)


def _deliver_unlocked(event_key: str, *, usernames=None, to_group: bool = False, title: str, rows=None, reason: str = "", link: str = "",
                      exclude=None, dedupe_key: str = "", group: str = None) -> str:
    """`deliver_event` 的本體（呼叫端負責 per-key 鎖）。永不丟例外。"""
    try:
        if not event_enabled(event_key):
            return "off"
        spec = event_spec(event_key)
        if dedupe_key and _mark_seen(dedupe_key):
            _pending_remove(dedupe_key)
            return "already_pushed"
        payload = dict(usernames=list(usernames or []), to_group=bool(to_group), title=title,
                       rows=[list(r) for r in (rows or []) if isinstance(r, (list, tuple)) and len(r) == 2],
                       reason=reason, link=link, exclude=list(exclude or []), group=group)

        def _park(outcome):
            if dedupe_key and not _DAY_SUFFIX_RE.search(dedupe_key) and outcome in ("paused_quota", SEND_TRANSIENT_FAIL, SEND_SKIPPED):
                _pending_add(dedupe_key, payload)
            return outcome

        if spec.get("priority") != "critical":
            from . import line_quota as _lq
            if _lq.reserve_paused():
                logger.warning("LINE 額度保留：本月用量已達 %d%%，暫停非 critical 事件 %r（critical 照發）", _lq.RESERVE_PERCENT, event_key)
                return _park("paused_quota")
        from . import event_audience as _ea
        from . import line_recipients as _lr
        lg = group or spec.get("line_group", "inherit")            # 呼叫端指定的群組（例如財務類的 module_activity）優先於事件字典
        given = _ea.resolve_usernames(event_key, usernames, bool(to_group) and lg is not None,
                                      group=lg if lg not in (None, "inherit") else None, exclude=exclude,
                                      own=(_cat_kind(event_key) != "mail"))     # LINE-only／細項事件：依事件本身語意（不借信件類型的覆寫；審查 h8 M3）
        allowed = _lr.resolve_audience(event_key, given)             # 業務收件人 ∩ 角色允許清單 →（可選）管理員指定 → 個人退訂（見 line_recipients）
        ids = ids_for(allowed)
        if not ids:
            logger.info("LINE：%r 沒有可推播的收件人（業務收件人 %d 人；角色／個人勾選後 %d 人；已綁定 0 人）", event_key, len(given), len(allowed))
            return "no_recipient"
        cap = month_cap_percent(event_key)
        lim = _monthly_limit() if cap is not None else None            # None＝無上限方案 ⇒ 沒有每月上限
        if cap is not None and lim is not None and _usage_of(event_key) + len(ids) > lim * cap // 100:
            logger.warning("LINE 每月上限：%r 本月已推 %d 則，達月額度 %d%% 的上限，這一則只發 Email", event_key, _usage_of(event_key), cap)
            return "monthly_cap"
        out = push(ids, build_text(title, rows, reason=reason, link=link))
        if out != SEND_SENT:
            logger.info("LINE 推播結果：%s（對象 %d 人）", out, len(ids))
        else:
            from . import line_quota as _lq            # 推成功＝額度可能變了：去抖動後刷新用量、跨門檻就告警（永不丟例外）
            _lq.after_push()
            if cap is not None:
                _usage_add(event_key, len(ids))
        if dedupe_key and out in (SEND_SENT, SEND_PERMANENT_FAIL):
            _mark_write(dedupe_key)
            _pending_remove(dedupe_key)
        return _park(out)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LINE deliver_event 失敗（event=%r）：%s", event_key, type(exc).__name__)
        return SEND_TRANSIENT_FAIL


def retry_pending() -> dict:
    """每日檢查呼叫：重送補發佇列。成功／永久失敗／已推過／沒有收件人／已關閉／每月上限已滿就移除（終態）；仍是暫時失敗／額度保留／token 失效就留著；
    超過 `PENDING_TTL_DAYS` 天放棄。回 `{retried, sent, dropped, left}`。永不丟例外。"""
    out = {"retried": 0, "sent": 0, "dropped": 0, "left": 0}
    try:
        v = _get_setting(PENDING_KEY, {}) or {}
        if not isinstance(v, dict) or not v:
            return out
        cut = (datetime.now() - timedelta(days=PENDING_TTL_DAYS)).isoformat(timespec="seconds")
        for key, rec in list(v.items()):
            try:
                args = (rec or {}).get("args") or {}
                created = str((rec or {}).get("created") or "")
                if not created or created < cut:
                    logger.warning("LINE 補發佇列：%r 超過 %d 天仍沒送出，放棄", key, PENDING_TTL_DAYS)
                    _pending_remove(key)
                    out["dropped"] += 1
                    continue
                ev = key.split("|", 1)[0]
                r = deliver_event(ev, usernames=args.get("usernames"), to_group=args.get("to_group", False), title=args.get("title", ""),
                                  rows=args.get("rows"), reason=args.get("reason", ""), link=args.get("link", ""),
                                  exclude=args.get("exclude"), dedupe_key=key, group=args.get("group"))
                out["retried"] += 1
                if r in ("paused_quota", SEND_TRANSIENT_FAIL, SEND_SKIPPED):
                    out["left"] += 1
                else:
                    _pending_remove(key)          # 終態（送出／永遠送不出去／沒人可送／已關閉／本月上限已滿）：不再補
                    out["sent"] += 1 if r == SEND_SENT else 0
            except Exception as exc:  # noqa: BLE001
                logger.warning("LINE 補發佇列：%r 重送失敗：%s", key, type(exc).__name__)
                out["left"] += 1
    except Exception as exc:  # noqa: BLE001
        logger.warning("LINE retry_pending 失敗：%s", type(exc).__name__)
    return out


def notify_event(event_key: str, *, usernames=None, to_group: bool = False, title: str, rows=None, reason: str = "", link: str = "",
                 exclude=None, dedupe_key: str = "", group: str = None):
    """獨立通道的**背景**發送（不擋呼叫端；收件人解析的資料庫查詢也在背景執行緒）。LINE 未啟用／類型沒勾選 ⇒ 回 None（不開執行緒）；否則回 daemon 執行緒。永不丟例外。"""
    try:
        if not event_enabled(event_key):
            return None
        t = threading.Thread(target=deliver_event, args=(event_key,), name="line-event", daemon=True,
                             kwargs=dict(usernames=usernames, to_group=to_group, title=title, rows=rows, reason=reason, link=link,
                                         exclude=exclude, dedupe_key=dedupe_key, group=group))
        t.start()
        return t
    except Exception as exc:  # noqa: BLE001
        logger.warning("LINE notify_event 失敗（event=%r）：%s", event_key, type(exc).__name__)
        return None


def notify_users(event_key: str, usernames, title: str, rows=None, *, reason: str = "", link: str = ""):
    """⚠️ 舊入口（相容與測試用；**業務碼不可呼叫**，見不變式 ⑧）：收件人由呼叫端給（不做業務收件人解析、不套額度保留／每月上限／已推播記號），
    只套 LINE 角色允許清單與個人勾選。類型沒勾選／LINE 未啟用／沒有人綁定 ⇒ 什麼都不做（回 None）；否則背景推播並回執行緒。**永不丟例外。**
    新程式一律用 `deliver_event`／`notify_event`／`email_notify.send_registered`。"""
    try:
        if not event_enabled(event_key):
            return None
        given = list(dict.fromkeys(usernames or []))
        from . import line_recipients as _lr            # 惰性 import：line_recipients 不 import 本檔於模組層
        allowed = _lr.filter_usernames(event_key, given)
        ids = ids_for(allowed)
        if not ids:
            logger.info("LINE：%r 沒有可推播的收件人（收件 %d 人；角色／個人勾選後 %d 人；已綁定 0 人）", event_key, len(given), len(allowed))
            return None
        return push_async(ids, build_text(title, rows, reason=reason, link=link))
    except Exception as exc:
        logger.warning("LINE notify_users 失敗（不影響信件；event=%r）：%s", event_key, type(exc).__name__)
        return None


def verify_token(token: str = None) -> dict:
    """驗證 channel access token（GET /v2/bot/info，不需要收件人）。回 `{ok, name, basicId, error}`；**永不丟例外**。
    `token` 沒給 ⇒ 用已存的設定。"""
    try:
        tk = token or _cfg().get("channel_access_token") or ""
        if not tk:
            return {"ok": False, "error": "尚未設定 channel access token"}
        if not valid_token(tk):
            return {"ok": False, "error": "channel access token 格式不正確（只能是英數與 + / = . _ -，20～512 字元），請重新貼上"}
        status, body = _http("GET", "/v2/bot/info", tk)
        if status == 200:
            return {"ok": True, "name": body.get("displayName", ""), "basicId": body.get("basicId", "")}
        if status in (401, 403):
            return {"ok": False, "error": "token 無效或已過期（LINE 回 %s）" % status}
        return {"ok": False, "error": "LINE 回應 %s" % status}
    except Exception as exc:
        logger.warning("LINE verify error: %s", type(exc).__name__)
        return {"ok": False, "error": "連不到 LINE（%s）" % type(exc).__name__}


def quota(token: str = None) -> dict:
    """本月訊息額度與已用量（免費方案有月上限，推播每位收件人各算一則）。回 `{ok, type, limit, used}`；limit 為 None＝無上限。永不丟例外。"""
    try:
        tk = token or _cfg().get("channel_access_token") or ""
        if not tk:
            return {"ok": False, "error": "尚未設定 channel access token"}
        if not valid_token(tk):
            return {"ok": False, "error": "channel access token 格式不正確"}
        s1, b1 = _http("GET", "/v2/bot/message/quota", tk)
        s2, b2 = _http("GET", "/v2/bot/message/quota/consumption", tk)
        if s1 != 200 or s2 != 200:
            return {"ok": False, "error": "LINE 回應 %s／%s" % (s1, s2)}
        # 欄位缺失或型別不對＝讀不到（不補 0、不當無上限）：補 0 會讓額度告警誤判「用量歸零」而清掉已警示紀錄、重寄同一門檻的信（K 審 F2）
        used, qtype, value = b2.get("totalUsage"), b1.get("type"), b1.get("value")
        if isinstance(used, bool) or not isinstance(used, int) or used < 0:
            return {"ok": False, "error": "LINE 回傳的本月用量欄位缺失或格式不對"}
        if qtype == "limited":
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return {"ok": False, "error": "LINE 回傳的訊息上限欄位缺失或格式不對"}
            return {"ok": True, "type": qtype, "limit": value, "used": used}
        if qtype == "none":
            return {"ok": True, "type": qtype, "limit": None, "used": used}
        return {"ok": False, "error": "LINE 回傳了不認得的額度類型（%r）" % (qtype,)}
    except Exception as exc:
        logger.warning("LINE quota error: %s", type(exc).__name__)
        return {"ok": False, "error": "連不到 LINE（%s）" % type(exc).__name__}
