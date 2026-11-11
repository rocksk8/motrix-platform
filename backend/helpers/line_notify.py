# -*- coding: utf-8 -*-
"""LINE Messaging API 發送管道（2026-11-11，T79 候選票；信件通知的並行通道）。

[單位] helper:line_notify    [層] L1    [穩定度] 實作（已接事件通道；OAuth 綁定流程尚未接，等對外 callback 網址）
[公開介面] CALLBACK_PATH, HTTP_TIMEOUT, LINE_API_BASE, LINKS_KEY, LINK_PAGES, MAX_TEXT, MULTICAST_LIMIT, SEND_PERMANENT_FAIL, SEND_SENT, SEND_SKIPPED, SEND_TRANSIENT_FAIL, SETTING_KEY, WIRED_EVENTS, build_text, callback_url, enabled, event_enabled, events_view, ids_for, is_linked, link_user, links_enabled, mask, normalize_public_base, notify_users, public_base, push, push_async, quota, safe_link, set_event, unlink_user, verify_token
[契約題] tests/platform/test_line_notify_t79.py、modules/case/tests/test_line_review_edit_2026_11_11.py
[不變式]
  ⓪ 曝露面：`public_base_url`（Tunnel 公開網域，callback 用）與 `include_links`（訊息是否帶連結，預設關）是**兩個獨立設定**（2026-11-11 PM 裁示）。
     有公開網域 ≠ 訊息帶連結；帶連結要兩者都成立，且只限 `LINK_PAGES` 白名單頁面，其餘連結一律不帶（不改寫）。
  ① 本檔不 import 業務模組；對 `email_notify` 只在函式內惰性 import（`email_notify` 頂層 import 本檔，反過來不可循環）；寄不寄由 `email_notify.email_send_policy()`
     （環境變數／`.no_email_send`）決定——**開發機標記同時擋信件與 LINE**（開發機誤推真實同仁的事故同一類）。
  ② 唯一的對外呼叫是 `_http`（urllib）；測試只換 `_http`。conftest NETGUARD 擋 urllib.request.urlopen，所以測試沒換就連不出去。
  ③ 回傳值沿用信件的四種結果（字串值與 `email_notify.SEND_*` 相同）：sent／transient_fail／permanent_fail／skipped。永不拋例外。
  ④ channel access token 存 `system_settings.line_notify.channel_access_token`（admin 在設定頁輸入；與 SMTP 密碼同一慣例）。
     GET 一律遮罩、PUT 收到遮罩值＝保留原值；每日 JSON 匯出以 json_remove 挖掉（archive.py）；**不寫進 log**。
  ⑤ 內容只用呼叫端給的文字：信件現有規則是「外部系統不帶金額」，LINE 同一規則（呼叫端負責，本檔不判斷內容）。
"""
import json
import logging
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

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
    return _get_setting(SETTING_KEY, {}) or {}


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


def normalize_public_base(v) -> str:
    """對外基準網址（Tunnel 公開網域）：只收 `https://主機[:埠]`，不可有路徑、查詢、帳密；末尾斜線容忍。不合法 ⇒ `ValueError`。空字串 ⇒ ""。"""
    s = str(v or "").strip().rstrip("/")
    if not s:
        return ""
    if len(s) > 255 or not _PUBLIC_BASE_RE.match(s):
        raise ValueError("對外網址只能是 https://網域（可含埠號），不可含路徑、查詢或帳號")
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
        logger.warning("LINE push error: %s", exc)
        return SEND_TRANSIENT_FAIL


def push_async(user_ids, text: str) -> threading.Thread:
    """背景推播（不擋呼叫端）；回 daemon 執行緒（測試可 `.join()`）。結果只進 log——LINE 是附帶通道，失敗不影響信件與呼叫端的「已通知」記號。"""
    def _run():
        try:
            out = push(user_ids, text)
            if out != SEND_SENT:
                logger.info("LINE 推播結果：%s（對象 %d 人）", out, len(list(user_ids or [])))
        except Exception:                                       # push 本身不丟例外；這裡是最後一道
            logger.exception("LINE 背景推播的執行緒自己炸了")
    t = threading.Thread(target=_run, daemon=True, name="line-push")
    t.start()
    return t


# ── 事件開關：哪些信件類型「同時發 LINE」（公司層、預設全關、逐類由最高管理者勾選）──────────────────────────
#: 已接上 LINE 的信件類型（＝設定頁可勾選的清單）。**接一個事件就加一個**；沒接線的類型不開放勾選（勾了也不會有任何東西送出，只會誤導）。
#: 付款／薪資／獎金類（含金額或個資）先不開放——PM 裁示（2026-11-11）；要開放須逐類確認內容不含金額。
WIRED_EVENTS = ("approval_review_edit", "warranty_expiry")


def event_enabled(event_key: str) -> bool:
    """這種信件類型要不要同時發 LINE：LINE 已啟用（有 token）、類型已接線、管理者已勾選。"""
    try:
        c = _cfg()
        return bool(c.get("enabled") and c.get("channel_access_token") and event_key in WIRED_EVENTS
                    and (c.get("events") or {}).get(event_key) is True)
    except Exception:
        return False


def events_view() -> dict:
    """⇒ {key: bool}（只含已接線的類型；缺項＝關）。"""
    ev = _cfg().get("events") or {}
    return {k: ev.get(k) is True for k in WIRED_EVENTS}


def set_event(event_key: str, on: bool) -> None:
    """寫入單一類型的開關。不是已接線的類型 ⇒ `ValueError`（不留死開關）。"""
    if event_key not in WIRED_EVENTS:
        raise ValueError("這種通知尚未支援 LINE：%s" % event_key)
    if not isinstance(on, bool):
        raise ValueError("enabled 必須是 true 或 false")
    with _lock:
        c = dict(_cfg())
        ev = dict(c.get("events") or {})
        ev[event_key] = on
        c["events"] = ev
        _set_setting(SETTING_KEY, c)


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


def notify_users(event_key: str, usernames, title: str, rows=None, *, reason: str = "", link: str = ""):
    """信件寄出時同步發 LINE：類型沒勾選／LINE 未啟用／沒有人綁定 ⇒ 什麼都不做（回 None）；否則背景推播並回執行緒。**永不丟例外。**
    收件人由呼叫端給（＝信件解析出來的、已套過覆寫與個人退訂的帳號），這裡不再做第二次收件人解析。"""
    try:
        if not event_enabled(event_key):
            return None
        ids = ids_for(usernames)
        if not ids:
            logger.info("LINE：%r 沒有已綁定 LINE 的收件人（收件 %d 人）", event_key, len(list(usernames or [])))
            return None
        return push_async(ids, build_text(title, rows, reason=reason, link=link))
    except Exception:
        logger.exception("LINE notify_users 失敗（不影響信件；event=%r）", event_key)
        return None


def verify_token(token: str = None) -> dict:
    """驗證 channel access token（GET /v2/bot/info，不需要收件人）。回 `{ok, name, basicId, error}`；**永不丟例外**。
    `token` 沒給 ⇒ 用已存的設定。"""
    try:
        tk = token or _cfg().get("channel_access_token") or ""
        if not tk:
            return {"ok": False, "error": "尚未設定 channel access token"}
        status, body = _http("GET", "/v2/bot/info", tk)
        if status == 200:
            return {"ok": True, "name": body.get("displayName", ""), "basicId": body.get("basicId", "")}
        if status in (401, 403):
            return {"ok": False, "error": "token 無效或已過期（LINE 回 %s）" % status}
        return {"ok": False, "error": "LINE 回應 %s" % status}
    except Exception as exc:
        logger.warning("LINE verify error: %s", exc)
        return {"ok": False, "error": "連不到 LINE（%s）" % type(exc).__name__}


def quota(token: str = None) -> dict:
    """本月訊息額度與已用量（免費方案有月上限，推播每位收件人各算一則）。回 `{ok, type, limit, used}`；limit 為 None＝無上限。永不丟例外。"""
    try:
        tk = token or _cfg().get("channel_access_token") or ""
        if not tk:
            return {"ok": False, "error": "尚未設定 channel access token"}
        s1, b1 = _http("GET", "/v2/bot/message/quota", tk)
        s2, b2 = _http("GET", "/v2/bot/message/quota/consumption", tk)
        if s1 != 200 or s2 != 200:
            return {"ok": False, "error": "LINE 回應 %s／%s" % (s1, s2)}
        return {"ok": True, "type": b1.get("type", ""), "limit": b1.get("value") if b1.get("type") == "limited" else None,
                "used": b2.get("totalUsage", 0)}
    except Exception as exc:
        logger.warning("LINE quota error: %s", exc)
        return {"ok": False, "error": "連不到 LINE（%s）" % type(exc).__name__}
