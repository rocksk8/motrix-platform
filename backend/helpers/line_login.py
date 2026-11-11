# -*- coding: utf-8 -*-
"""LINE Login 綁定流程（2026-11-11，T79；「電腦發起、手機授權」）。

[單位] helper:line_login    [層] L1    [穩定度] 實作
[公開介面] AUTHORIZE_URL, CALLBACK_RATE_LIMIT, CALLBACK_RATE_WINDOW, MAX_PENDING_PER_USER, MAX_PENDING_TOTAL, RESULT_DENIED, RESULT_EXPIRED, RESULT_FAILED, RESULT_INVALID, RESULT_LINKED, RESULT_SESSION_ENDED, STATE_TTL, TOKEN_PATH, VERIFY_PATH, authorize_url_for, complete, pending_count, rate_ok, reset_for_tests, start
[契約題] tests/platform/test_line_login_t79.py
[不變式]
  ① 流程：已登入的使用者在電腦按「綁定 LINE」→ `start()` 產生一次性 state（綁定發起人的登入 session）→ 電腦顯示 QR → 手機掃碼授權 →
     LINE 把瀏覽器導回 `GET /api/line/callback?code&state`（**這一條是 Tunnel 唯一對外的路徑，沒有登入 session**）→ `complete()`。
  ② state：隨機 32 位元組、**單次使用**（不論成敗，一查就銷毀）、有效 `STATE_TTL` 秒、只存雜湊；每人最多 `MAX_PENDING_PER_USER` 筆（新的擠掉最舊的），
     全域最多 `MAX_PENDING_TOTAL` 筆（滿了拒絕新的）。存在行程記憶體，重啟即失效（使用者重按一次即可；單一伺服器行程，多 worker 要改資料表）。
  ③ 綁定對象＝**發起人**：`complete()` 要求發起時的登入 session 仍然有效（已登出／過期 ⇒ 不綁），且帳號仍存在並啟用。LINE 回來的瀏覽器本身不帶任何身分。
  ④ LINE 端的驗證：用 code 換 id_token（需 channel secret），再交給 LINE 的 verify 端點確認簽章／aud／nonce；userId＝id_token 的 `sub`。
     只要 `openid` scope，不取個資（不拿暱稱、頭像）。
  ⑤ 回傳純結果代碼，**不含任何 ERP 資料**；`complete()` 永不丟例外，也不把 code／state／secret／id_token 寫進 log（只記結果與例外型別）。
  ⑥ 唯一的對外呼叫是 `_post_form`（urllib）；測試只換它。conftest NETGUARD 擋 urllib.request.urlopen。
  ⑦ 綁定完成後推一則「綁定完成」確認訊息（不含 ERP 資料）：成功 ⇒ `confirmed=True`；LINE 回永久失敗（常見原因：Login channel 與 Messaging channel
     不在同一個 Provider，userId 對不上）⇒ `confirmed=False`，設定頁要顯示警告；LINE 通知沒啟用／開發機標記 ⇒ `confirmed=None`（沒驗）。
"""
import hashlib
import json
import logging
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from . import line_notify as _ln

logger = logging.getLogger(__name__)

AUTHORIZE_URL = "https://access.line.me/oauth2/v2.1/authorize"
TOKEN_PATH = "/oauth2/v2.1/token"
VERIFY_PATH = "/oauth2/v2.1/verify"

STATE_TTL = 600
MAX_PENDING_PER_USER = 3
MAX_PENDING_TOTAL = 200
#: 公開路徑的總量保護：每 CALLBACK_RATE_WINDOW 秒最多 CALLBACK_RATE_LIMIT 次（不依 IP——X-Forwarded-For 可偽造，見 PM 另開的票）
CALLBACK_RATE_LIMIT = 60
CALLBACK_RATE_WINDOW = 60

RESULT_LINKED = "linked"
RESULT_DENIED = "denied"            # 使用者在 LINE 按了「取消」
RESULT_EXPIRED = "expired"          # state 過期
RESULT_INVALID = "invalid"          # state 不存在／格式不對／已用過
RESULT_SESSION_ENDED = "session_ended"   # 發起人已登出或帳號停用
RESULT_FAILED = "failed"            # LINE 端驗證失敗、連不到 LINE、這個 LINE 帳號已綁別人

_STATE_RE = re.compile(r"^[A-Za-z0-9_-]{20,128}$")
_CODE_RE = re.compile(r"^[A-Za-z0-9._~-]{1,512}$")

_now = time.monotonic               # 測試換掉這個來快轉時間
_lock = threading.Lock()
_pending = {}                       # sha256(state) → {username, token, nonce, at}
_hits = []                          # callback 的時間戳（總量保護）


def _h(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def reset_for_tests() -> None:
    with _lock:
        _pending.clear()
        del _hits[:]


def pending_count() -> int:
    with _lock:
        return len(_pending)


def _purge_locked(now: float) -> None:
    for k in [k for k, v in _pending.items() if now - v["at"] > STATE_TTL]:
        _pending.pop(k, None)


def rate_ok() -> bool:
    """公開 callback 的總量保護；超過 ⇒ False（呼叫端回 429）。"""
    now = _now()
    with _lock:
        _hits[:] = [t for t in _hits if now - t < CALLBACK_RATE_WINDOW]
        if len(_hits) >= CALLBACK_RATE_LIMIT:
            return False
        _hits.append(now)
        return True


def authorize_url_for(client_id: str, redirect_uri: str, state: str, nonce: str) -> str:
    q = urllib.parse.urlencode({"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
                                "state": state, "scope": "openid", "nonce": nonce,
                                # 同意後接著問「要不要加官方帳號為好友」（沒加好友就收不到推播）；Login channel 沒連結官方帳號時 LINE 會忽略
                                "bot_prompt": "aggressive"})
    return AUTHORIZE_URL + "?" + q


def start(username: str, session_token: str) -> dict:
    """發起綁定。回 `{"authorizeUrl", "expiresIn"}`；LINE Login 沒設好／沒有對外網址／太多進行中 ⇒ `ValueError`（訊息可直接給使用者看）。"""
    cid, secret = _ln.login_credentials()
    cb = _ln.callback_url()
    if not (cid and secret):
        raise ValueError("管理員尚未設定 LINE Login（channel ID 與 secret）")
    if not cb:
        raise ValueError("管理員尚未設定對外網址（public_base_url），無法綁定 LINE")
    if not username or not session_token:
        raise ValueError("需要登入狀態才能綁定")
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(16)
    now = _now()
    with _lock:
        _purge_locked(now)
        mine = sorted((v["at"], k) for k, v in _pending.items() if v["username"] == username)
        while len(mine) >= MAX_PENDING_PER_USER:
            _pending.pop(mine.pop(0)[1], None)
        if len(_pending) >= MAX_PENDING_TOTAL:
            raise ValueError("目前綁定要求太多，請稍後再試")
        _pending[_h(state)] = {"username": username, "token": session_token, "nonce": nonce, "at": now}
    return {"authorizeUrl": authorize_url_for(cid, cb, state, nonce), "expiresIn": STATE_TTL}


def _post_form(path: str, fields: dict):
    """唯一的對外呼叫。回 `(status, body_dict)`；HTTP 錯誤也回（不拋）；連線層錯誤拋。測試換掉這支。"""
    data = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(_ln.LINE_API_BASE + path, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=_ln.HTTP_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8", "replace") or "{}")
        except Exception:
            body = {}
        return e.code, body


def _initiator_ok(username: str, token: str) -> bool:
    """發起人的登入 session 還有效、帳號還在且啟用。"""
    try:
        from db import get_db           # 惰性 import（同 email_notify）
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT u.active FROM sessions s JOIN users u ON s.user_id=u.id "
                "WHERE s.token=? AND u.username=? AND s.expires_at>?",
                (token, username, datetime.now().isoformat())).fetchone()
        finally:
            conn.close()
        return bool(row and row["active"])
    except Exception as exc:
        logger.warning("LINE bind：查發起人 session 失敗：%s", type(exc).__name__)
        return False


def _exchange(code: str, cid: str, secret: str, redirect_uri: str, nonce: str):
    """code → userId。失敗回 None。"""
    s1, b1 = _post_form(TOKEN_PATH, {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                                     "client_id": cid, "client_secret": secret})
    id_token = b1.get("id_token") if s1 == 200 and isinstance(b1, dict) else None
    if not isinstance(id_token, str) or not id_token:
        return None
    s2, b2 = _post_form(VERIFY_PATH, {"id_token": id_token, "client_id": cid})
    if s2 != 200 or not isinstance(b2, dict):
        return None
    if str(b2.get("aud") or "") != cid or b2.get("nonce") != nonce:
        return None
    sub = str(b2.get("sub") or "")
    return sub if re.match(r"^U[0-9a-f]{32}$", sub) else None


def complete(code, state, error=None):
    """LINE 導回後的收尾。回 `(result, session_token_or_None, username_or_None)`（後兩者只給稽核用，不回給手機）。**永不丟例外。**"""
    try:
        if not isinstance(state, str) or not _STATE_RE.match(state):
            return RESULT_INVALID, None, None
        with _lock:
            rec = _pending.pop(_h(state), None)         # 不論成敗都銷毀：單次使用
        if rec is None:
            return RESULT_INVALID, None, None
        username, token = rec["username"], rec["token"]
        if _now() - rec["at"] > STATE_TTL:
            return RESULT_EXPIRED, token, username
        if error:
            return RESULT_DENIED, token, username
        if not isinstance(code, str) or not _CODE_RE.match(code):
            return RESULT_FAILED, token, username
        if not _initiator_ok(username, token):
            return RESULT_SESSION_ENDED, token, username
        cid, secret = _ln.login_credentials()
        cb = _ln.callback_url()
        if not (cid and secret and cb):
            return RESULT_FAILED, token, username
        uid = _exchange(code, cid, secret, cb, rec["nonce"])
        if not uid:
            return RESULT_FAILED, token, username
        try:
            _ln.link_user(username, uid)
        except ValueError:
            return RESULT_FAILED, token, username       # 這個 LINE 帳號已綁在別的系統帳號
        res = _ln.push([uid], "MOTRIX 通知已綁定完成，之後會在這裡收到您勾選的通知。")
        _ln.set_confirmed(username, True if res == _ln.SEND_SENT else False if res == _ln.SEND_PERMANENT_FAIL else None)
        return RESULT_LINKED, token, username
    except Exception as exc:
        logger.warning("LINE bind complete 失敗：%s", type(exc).__name__)
        return RESULT_FAILED, None, None
