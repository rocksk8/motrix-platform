# -*- coding: utf-8 -*-
"""LINE Messaging API 發送管道（2026-11-11，T79 候選票；信件通知的並行通道）。

[單位] helper:line_notify    [層] L1    [穩定度] 實作（階段 1：封裝＋設定；綁定與事件接線在後續 commit）
[公開介面] LINE_API_BASE, SEND_*, enabled, build_text, push, verify_token, quota, mask
[不變式]
  ① 本檔不 import 業務模組、不 import email_notify（email_notify 之後會呼叫本檔，不可循環）；寄不寄由 `email_notify.email_send_policy()`
     （環境變數／`.no_email_send`）決定——**開發機標記同時擋信件與 LINE**（惰性 import，開發機誤推真實同仁的事故同一類）。
  ② 唯一的對外呼叫是 `_http`（urllib）；測試只換 `_http`。conftest NETGUARD 擋 urllib.request.urlopen，所以測試沒換就連不出去。
  ③ 回傳值沿用信件的四種結果（字串值與 `email_notify.SEND_*` 相同）：sent／transient_fail／permanent_fail／skipped。永不拋例外。
  ④ channel access token 存 `system_settings.line_notify.channel_access_token`（admin 在設定頁輸入；與 SMTP 密碼同一慣例）。
     GET 一律遮罩、PUT 收到遮罩值＝保留原值；每日 JSON 匯出以 json_remove 挖掉（archive.py）；**不寫進 log**。
  ⑤ 內容只用呼叫端給的文字：信件現有規則是「外部系統不帶金額」，LINE 同一規則（呼叫端負責，本檔不判斷內容）。
"""
import json
import logging
import urllib.error
import urllib.request

from .settings import _get_setting

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


def build_text(title: str, rows=None, *, reason: str = "", link: str = "") -> str:
    """把一則通知排成純文字：標題、事由、`欄位：值` 逐行、連結。控制字元收成空白，過長截斷。"""
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
    if link:
        lines.append(str(link))
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
