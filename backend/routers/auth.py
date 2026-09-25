"""Auth + User management endpoints."""
import base64
import io
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, List

import pyotp
import qrcode
from fastapi import APIRouter, HTTPException, Header, Request, Depends
from pydantic import BaseModel
from webauthn import (
    generate_registration_options,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
    options_to_json,
)

from db import get_db, get_demo_db, reset_demo_db, demo_reset_lock
from helpers.module_registry import refuse_unknown_new_keys
from helpers import (
    _hash_pw, _verify_pw, _require_user, _tok, _audit, is_weak_password, MIN_PASSWORD_LEN, DEMO_TOKEN_PREFIX,
    notify_module_activity)

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Login rate limiting (per source IP) ───────────────────────────────────────

_LOGIN_MAX_FAILS = 5       # consecutive failures before lockout
_LOGIN_LOCKOUT_S = 900     # 15 minutes

_rl_lock = threading.Lock()
# ip -> {"fails": int, "locked_until": float (monotonic epoch)}
_rl_state: dict = {}


def _client_ip(request: Request) -> str:
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rl_db_write(ip: str, locked_until_mono: float) -> None:
    delta = locked_until_mono - time.monotonic()
    wall_until = datetime.now() + timedelta(seconds=max(delta, 0))
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO login_rate_limit (ip, locked_until) VALUES (?, ?) "
            "ON CONFLICT(ip) DO UPDATE SET locked_until=excluded.locked_until",
            (ip, wall_until.isoformat()),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _rl_db_clear(ip: str) -> None:
    try:
        conn = get_db()
        conn.execute("DELETE FROM login_rate_limit WHERE ip=?", (ip,))
        conn.commit()
        conn.close()
    except Exception:
        pass


def init_rate_limiting() -> None:
    """Reload persisted IP lockouts from DB into memory on startup."""
    try:
        conn = get_db()
        rows = conn.execute("SELECT ip, locked_until FROM login_rate_limit").fetchall()
        conn.close()
        now_wall = datetime.now()
        now_mono = time.monotonic()
        with _rl_lock:
            for row in rows:
                try:
                    wall_until = datetime.fromisoformat(row["locked_until"])
                    if wall_until > now_wall:
                        delta = (wall_until - now_wall).total_seconds()
                        _rl_state[row["ip"]] = {"fails": 0, "locked_until": now_mono + delta}
                except Exception:
                    pass
        try:
            conn2 = get_db()
            conn2.execute("DELETE FROM login_rate_limit WHERE locked_until <= ?", (now_wall.isoformat(),))
            conn2.commit()
            conn2.close()
        except Exception:
            pass
    except Exception:
        logger.warning("init_rate_limiting: could not load from DB")


def _rl_check(ip: str) -> None:
    """Raise 429 if IP is currently locked out."""
    now = time.monotonic()
    with _rl_lock:
        state = _rl_state.get(ip)
        if not state:
            return
        if now < state["locked_until"]:
            wait = int(state["locked_until"] - now)
            raise HTTPException(429, f"登入嘗試次數過多，請於 {wait} 秒後再試")
        if state["locked_until"] > 0:
            del _rl_state[ip]


def _rl_fail(ip: str, username: str) -> None:
    now = time.monotonic()
    lockout_until = 0.0
    with _rl_lock:
        state = _rl_state.setdefault(ip, {"fails": 0, "locked_until": 0.0})
        state["fails"] += 1
        if state["fails"] >= _LOGIN_MAX_FAILS:
            state["locked_until"] = now + _LOGIN_LOCKOUT_S
            lockout_until = state["locked_until"]
            state["fails"] = 0
            logger.warning("Login lockout: IP=%s username=%s locked for %ds", ip, username, _LOGIN_LOCKOUT_S)
    if lockout_until:
        _rl_db_write(ip, lockout_until)


def _rl_clear(ip: str) -> None:
    with _rl_lock:
        _rl_state.pop(ip, None)
    _rl_db_clear(ip)


# ── TOTP two-factor login (2026-09-07, self-service — see db.py::_m072_totp) ──
#
# Second-factor state for a login-in-progress lives only in-process memory
# (mirrors the pattern above), keyed by a random challenge token instead of
# IP — a wrong code from one teammate on a shared office IP must not lock out
# everyone else mid-login. Losing this dict on a dev-machine --reload restart
# just means "log in again from the top", which is an acceptable trade-off for
# a few minutes of state versus adding a DB table for something this short-lived.

_TOTP_CHALLENGE_TTL_S = 300    # 5 minutes to enter the code after password succeeds
_TOTP_MAX_FAILS       = 5      # wrong codes before the challenge itself is invalidated

_totp_lock: threading.Lock = threading.Lock()
# challenge_token -> {"user_id": int, "must_change": bool, "fails": int, "expires": monotonic}
_totp_pending: dict = {}


def _totp_sweep_expired() -> None:
    now = time.monotonic()
    with _totp_lock:
        for tok in [t for t, v in _totp_pending.items() if v["expires"] < now]:
            del _totp_pending[tok]


def _mask_username(name: str) -> str:
    """First + last character kept, middle replaced with '*' — just enough for
    the legitimate phone owner to recognise "yes that's my own login attempt"
    on the QR-approve page, without fully exposing the account name to anyone
    who merely sees the QR code on someone else's screen."""
    name = name or ""
    if len(name) <= 2:
        return "*" * len(name)
    return name[0] + "*" * (len(name) - 2) + name[-1]


# ── Models ────────────────────────────────────────────────────────────────────

class LoginIn(BaseModel):
    username: str
    password: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


class VerifyUnlockIn(BaseModel):
    password: str
    ref: str = ''


class TotpLoginVerifyIn(BaseModel):
    challenge_token: str
    code: str


class QrApproveIn(BaseModel):
    challenge_token: str
    password: Optional[str] = None
    # 2026-09-08 新增：手機瀏覽器如果自己已經是登入狀態，帶現有 session token
    # 免再輸入密碼一次核准（見 login_qr_approve() 內的分流邏輯）。
    session_token: Optional[str] = None


class TotpEnableIn(BaseModel):
    code: str


class TotpDisableIn(BaseModel):
    password: str


class TotpRegenRecoveryIn(BaseModel):
    """重新產生救援碼——比照 TotpDisableIn，用目前密碼確認身分。"""
    password: str


class SetUnlockPasswordIn(BaseModel):
    unlock_password: str


class VerifyDailyTaskUnlockIn(BaseModel):
    password: str


class SetDailyTaskPasswordIn(BaseModel):
    daily_task_password: str


class UserIn(BaseModel):
    username: Optional[str] = None
    display_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    modules: Optional[List[str]] = None
    notification_muted: Optional[List[str]] = None
    password: Optional[str] = None
    active: Optional[bool] = None
    department_id: Optional[int] = None


class WebauthnRegisterBeginIn(BaseModel):
    pass


class WebauthnRegisterCompleteIn(BaseModel):
    challengeToken: str
    id: str
    rawId: str
    response: dict
    # 2026-09-10：py_webauthn 的 parse_registration_credential_json() 會驗
    # `type` 必須是 PublicKeyCredentialType（也就是字串 "public-key"），沒有
    # 就丟 InvalidJSONStructure("Credential had unexpected type")。這個模型
    # 原本沒宣告這個欄位，所以就算前端有送，`body.dict()` 也不會帶過去——
    # 註冊必然失敗。給預設值是為了相容還沒更新的前端（規格上這個值恆為
    # "public-key"，WebAuthn 目前沒有第二種）。
    type: str = "public-key"


class WebauthnLoginBeginIn(BaseModel):
    username: str


class WebauthnLoginCompleteIn(BaseModel):
    challengeToken: str
    username: str
    id: str
    rawId: str
    response: dict
    # 同 WebauthnRegisterCompleteIn，登入這條路徑的
    # parse_authentication_credential_json() 有一模一樣的檢查。
    type: str = "public-key"


class WebauthnCredentialRenameIn(BaseModel):
    name: str


# ── Auth ──────────────────────────────────────────────────────────────────────

@router.get("/api/ping")
def ping():
    return {"ok": True, "time": datetime.now().isoformat()}


from core import paths as _paths
_MANIFEST_PATH = _paths.VERSION_MANIFEST
_VERSION_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})([a-z]*)$")


def _version_sort_key(version: str) -> tuple:
    """`YYYY-MM-DD` ＋ 字母序號的排序鍵（T10）。

    ⚠️ 不可以直接比字串：序號過了 `z` 是 `aa`，而字串比較下 `aa` < `z`。
    ⇒ (日期, 序號長度, 序號)。認不得的格式排最前面（不會被當成最新）。
    """
    m = _VERSION_RE.match(version or "")
    if not m:
        return ("", 0, "")
    return (m.group(1), len(m.group(2)), m.group(2))


@router.get("/api/system/version")
def system_version():
    """Latest overall system version (newest entry in version_manifest.json).
    Public — used by the login page footer, which has no session token yet.

    2026-09-10: read with `utf-8-sig`, not `utf-8`. The file currently has no
    BOM, but anything that rewrites it from PowerShell (`Set-Content -Encoding
    UTF8` adds one on PS 5.1) would BOM it, and plain `utf-8` then raises
    JSONDecodeError on the very first character — swallowed by the except below
    into a blank version on the login page, with nothing logged. That is exactly
    how `GET /api/system/deployed-version` broke (commit 1c8f2e8); `utf-8-sig`
    reads both forms, so there is no reason to leave the second copy of the same
    trap in place."""
    try:
        with open(_MANIFEST_PATH, encoding="utf-8-sig") as f:
            entries = json.load(f)
        # T10：取**最新**的一筆，不是第一筆——manifest 沒有排序保證（正式機曾回 22c 而最新是 22g）。
        latest = max(entries, key=lambda e: _version_sort_key(e.get("version", ""))) if entries else {}
    except Exception:
        latest = {}
    return {"version": latest.get("version", ""), "date": latest.get("date", "")}


@router.get("/api/system/branding")
def system_branding(authorization: str = Header(None)):
    """公司名稱（登入頁卡片、頁尾與首頁頁尾用；ROADMAP A8d：取代前端寫死的公司名與統編）。

    Public：登入頁還沒有 session。**統編只在帶有效登入時回傳**（登入頁用不到，不對外多給）。
    值取自公司資料設定（主要據點 ＞ company_profile），沒填就是空字串——前端照空的顯示，不補任何公司的名字。"""
    from helpers.company_identity import location_identity, short_name
    ident = location_identity()
    out = {"companyName": ident["company_name"], "companyNameEn": ident["company_name_en"],
           "shortName": short_name(ident["company_name"])}
    if authorization:
        try:
            _require_user(authorization)
            out["taxId"] = ident["tax_id"]
        except HTTPException:
            pass
    return out


_DEPLOYED_MARKER_PATH = _paths.DEPLOYED_COMMIT_FILE


@router.get("/api/system/deployed-version")
def system_deployed_version():
    """哪個 git commit 目前真正部署在這台機器上（apply_update.ps1 套用成功後
    寫入的 backend/.deployed_commit.json）。Public——供 2026-09-08 新增的
    deploy_dashboard.py 本機工具查詢正式機目前版本用，不需要密碼／session。
    這份檔案只存在正式機（開發機/測試環境從來沒套用過部署包，檔案不存在，
    回傳空物件是正常情況，不是錯誤）。模組層級變數（而非函式內即算）方便
    測試用 monkeypatch 導向暫存路徑，不用寫進真實的 backend/ 目錄。"""
    try:
        # utf-8-sig（不是 utf-8）：apply_update.ps1 用 PowerShell 5.1
        # `Set-Content -Encoding UTF8` 寫這個檔案會帶 BOM，純 utf-8 遇到
        # BOM 會讓 json.load 直接丟 JSONDecodeError，被下面 except 吞掉
        # 悄悄回傳空物件——2026-09-08 第一次真實成功套用後才發現這個檔案
        # 讀不到內容，見 MOTRIX-ERP-QUICK.md §12 同日條目。
        with open(_DEPLOYED_MARKER_PATH, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


@router.get("/api/build-info")
def build_info_endpoint(authorization: str = Header(None)):
    """**這個行程**載入的是哪一份程式碼（`BR1`）。

    ## 🔴 與上面那支 `deployed-version` **不是同一個問題**

    ```
    deployed-version  **磁碟上**被套用成哪一版（apply_update.ps1 寫的）
    本支              **這個行程啟動當下**載入的是哪一版
    ```
    ☠️ 2026-09-23 的事故正是這兩者不一致：磁碟新、行程舊，
       而 `deployed-version` 回的是**新的那個** ⇒ 它看起來一切正常。

    ## 🔑 真正有用的是 `stale`

    `commit`（啟動時定住）與 `disk_commit`（這次請求再抓）不同
    ⇒ **磁碟上比較新，要重新啟動**。
    ⚠️ `stale` 是 `null` 代表「至少一個 SHA 不可得」，**不是「沒有過期」** ——
       當成 `false` 的話，畫面會在「不知道」的時候說「是最新的」。

    ## ⚠️ 要登入才看得到，而**不需要任何模組**

    它不是某個功能的一部分，是**整個系統**的狀態 ⇒ 任何登入者都該看得到。
    📌 而沒有放進 `_PUBLIC_API_PATHS`：commit SHA 指得到確切的原始碼，
       沒有理由在登入前就給出去。
    """
    _require_user(authorization)
    from helpers.build_info import build_info
    return build_info()


@router.post("/api/auth/login")
def auth_login(body: LoginIn, request: Request):
    ip = _client_ip(request)
    _rl_check(ip)
    conn = get_db()
    row = conn.execute(
        "SELECT id, username, display_name, role, modules, password_hash, "
        "COALESCE(must_change_password, 0) AS must_change_password, "
        "COALESCE(totp_enabled, 0) AS totp_enabled "
        "FROM users WHERE username=? AND active=1",
        (body.username.strip(),)
    ).fetchone()
    if not row or not _verify_pw(body.password, row["password_hash"]):
        conn.close()
        _rl_fail(ip, body.username.strip())
        raise HTTPException(401, "帳號或密碼錯誤")
    must_change = bool(row["must_change_password"])
    # Legacy weak password still works once, but forces rotation
    if is_weak_password(body.password):
        must_change = True
        conn.execute(
            "UPDATE users SET must_change_password=1 WHERE id=?",
            (row["id"],),
        )
    if ":" not in row["password_hash"]:
        conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                     (_hash_pw(body.password), row["id"]))
    now = datetime.now().isoformat()

    if row["username"] == "demo":
        # Showcase account: never touches real data. Reset the isolated demo DB
        # to a fresh, fully-migrated, completely empty state and issue a
        # prefixed token whose session/user row lives ONLY in that demo DB —
        # auth_middleware detects the prefix and routes every subsequent
        # request (including _require_user()/_audit() lookups) there too.
        conn.commit()
        conn.close()
        token      = DEMO_TOKEN_PREFIX + secrets.token_hex(32)
        expires_at = (datetime.now() + timedelta(days=1)).isoformat()
        # Serialise reset+seed: two demo logins arriving at nearly the same
        # moment must not both wipe/re-seed the shared demo DB concurrently
        # (races on the fresh 'demo' user INSERT / VACUUM otherwise).
        with demo_reset_lock:
            reset_demo_db()
            dconn = get_demo_db()
            dconn.execute(
                "INSERT INTO users (username, password_hash, display_name, role, modules, "
                "active, created_at, must_change_password) VALUES ('demo',?,?,?,?,1,?,0)",
                (row["password_hash"], row["display_name"], row["role"], row["modules"], now),
            )
            demo_user_id = dconn.execute("SELECT last_insert_rowid()").fetchone()[0]
            dconn.execute(
                "INSERT INTO sessions (token, user_id, username, created_at, expires_at, last_active) "
                "VALUES (?,?,?,?,?,?)",
                (token, demo_user_id, "demo", now, expires_at, now),
            )
            dconn.execute(
                "INSERT INTO audit_log (at,user_id,username,display_name,action,target_type,target_id,target_label,detail) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (now, demo_user_id, "demo", row["display_name"], "auth.login", "user", "demo",
                 row["display_name"], json.dumps({"mustChangePassword": False}, ensure_ascii=False)),
            )
            dconn.commit()
            dconn.close()
        _rl_clear(ip)
        return {
            "token":              token,
            "userId":             demo_user_id,
            "username":           "demo",
            "displayName":        row["display_name"],
            "role":               row["role"],
            "modules":            json.loads(row["modules"] or "[]"),
            "loginAt":            now,
            "mustChangePassword": False,
        }

    if row["totp_enabled"]:
        # Password is correct but this account has TOTP enabled — don't issue a
        # session yet. Persist the must_change/password-hash-upgrade side effects
        # computed above, then hand back a short-lived challenge token instead of
        # a real token; the actual session is only created once the code checks
        # out in auth_login_totp() below.
        conn.commit()
        conn.close()
        _totp_sweep_expired()
        challenge_token = secrets.token_hex(24)
        with _totp_lock:
            _totp_pending[challenge_token] = {
                "user_id": row["id"], "must_change": must_change,
                "fails": 0, "expires": time.monotonic() + _TOTP_CHALLENGE_TTL_S,
                "approved": False,
            }
        # 2026-09-08 新增：手機相機掃 QR 核准登入，跟手動輸入驗證碼並行、互不影響
        # （見 login-qr-approve.html／qr-info／qr-approve／qr-status 四個新端點）。
        # QR 內容是指向確認頁面的完整網址，動態組出（不寫死 IP，比照既有「CORS
        # 白名單寫死 IP」的已知限制更穩健）。
        # 🔴 **用 `#` 不是 `?`**（2026-09-22，§8 FX22 的第三個洩漏點）。
        #
        # ☠️ FX22 只說了兩支 API，而 challenge **還有第三個地方會進 access log**：
        # 這個頁面網址本身。手機一掃就是
        # `GET /pages/login-qr-approve.html?challenge=xxx` ⇒ 照樣被記一筆。
        # 🔑 **只改 API 的話，我們會宣稱洩漏堵住了，而它沒有。**
        #
        # ⇒ 改成 URL fragment：**`#` 後面的東西瀏覽器不會送給伺服器**，
        # 所以它不可能出現在任何伺服器端的紀錄裡，而 JS 讀得到（`location.hash`）。
        # 📌 沒有留舊格式的相容路徑：QR 的有效期只有幾分鐘，
        # 不存在「已經印出去的舊 QR」，而**留一條相容路徑就是留著那個洩漏**。
        approve_url = (
            f"{request.url.scheme}://{request.headers.get('host', '')}"
            f"/pages/login-qr-approve.html#challenge={challenge_token}"
        )
        qr_img = qrcode.make(approve_url)
        qr_buf = io.BytesIO()
        qr_img.save(qr_buf, format="PNG")
        qr_b64 = base64.b64encode(qr_buf.getvalue()).decode()
        return {
            "totpRequired": True,
            "challengeToken": challenge_token,
            "qrCodePng": f"data:image/png;base64,{qr_b64}",
        }

    result = _issue_session(conn, row, must_change)
    conn.close()
    _rl_clear(ip)
    return result


def _issue_session(conn, row, must_change: bool) -> dict:
    """Create the real `sessions` row + build the standard login response.
    Shared by the direct (no-TOTP) login path and auth_login_totp() below —
    keeps both paths issuing identically-shaped sessions/responses. Caller
    commits/closes `conn` and clears the IP rate limit afterward."""
    now        = datetime.now().isoformat()
    token      = secrets.token_hex(32)
    expires_at = (datetime.now() + timedelta(days=30)).isoformat()
    conn.execute(
        "INSERT INTO sessions (token, user_id, username, created_at, expires_at, last_active) VALUES (?,?,?,?,?,?)",
        (token, row["id"], row["username"], now, expires_at, now)
    )
    conn.commit()
    _audit(token, 'auth.login', 'user', row['username'], row['display_name'] or row['username'],
           {'mustChangePassword': must_change})
    return {
        "token":              token,
        "userId":             row["id"],
        "username":           row["username"],
        "displayName":        row["display_name"],
        "role":               row["role"],
        "modules":            json.loads(row["modules"] or "[]"),
        "loginAt":            now,
        "mustChangePassword": must_change,
    }


@router.post("/api/auth/login/totp")
def auth_login_totp(body: TotpLoginVerifyIn, request: Request):
    """Second step of login for accounts with TOTP enabled — verifies the
    6-digit authenticator code (or an 8-hex-char one-time recovery code)
    against the challenge token issued by auth_login() above."""
    ip = _client_ip(request)
    _totp_sweep_expired()
    with _totp_lock:
        pending = _totp_pending.get(body.challenge_token)
    if not pending:
        raise HTTPException(400, "驗證逾時或工作階段無效，請重新登入")

    conn = get_db()
    row = conn.execute(
        "SELECT id, username, display_name, role, modules, active, "
        "totp_secret, totp_recovery_codes FROM users WHERE id=?",
        (pending["user_id"],),
    ).fetchone()
    if not row or not row["active"]:
        conn.close()
        with _totp_lock:
            _totp_pending.pop(body.challenge_token, None)
        raise HTTPException(401, "帳號不存在或已停用")

    code = (body.code or "").strip()
    ok = False
    used_recovery = False
    recovery_remaining = None   # 只有這次真的用掉救援碼時才有值
    if code.isdigit() and len(code) == 6:
        ok = pyotp.TOTP(row["totp_secret"]).verify(code, valid_window=1)
    else:
        codes = json.loads(row["totp_recovery_codes"] or "[]")
        for i, hashed in enumerate(codes):
            if _verify_pw(code, hashed):
                ok = True
                used_recovery = True
                codes.pop(i)
                recovery_remaining = len(codes)
                conn.execute("UPDATE users SET totp_recovery_codes=? WHERE id=?",
                             (json.dumps(codes, ensure_ascii=False), row["id"]))
                conn.commit()
                break

    if not ok:
        conn.close()
        _rl_fail(ip, row["username"])
        with _totp_lock:
            still = _totp_pending.get(body.challenge_token)
            if still:
                still["fails"] += 1
                if still["fails"] >= _TOTP_MAX_FAILS:
                    del _totp_pending[body.challenge_token]
                    raise HTTPException(401, "驗證碼錯誤次數過多，請重新登入")
        raise HTTPException(401, "驗證碼不正確")

    with _totp_lock:
        _totp_pending.pop(body.challenge_token, None)
    result = _issue_session(conn, row, pending["must_change"])
    conn.close()
    _rl_clear(ip)
    if used_recovery:
        _audit(result["token"], "auth.totp_recovery_used", "user", row["username"],
               f"{row['display_name'] or row['username']}：使用救援碼登入，剩餘 {recovery_remaining} 組")
        # 2026-09-11：把剩餘組數一起回給前端。救援碼用掉不會有任何提示，使用者
        # 通常是在最後一組也用完、驗證 App 又不在手邊時才發現被鎖在外面——那時
        # 已經來不及自助補救（重產端點要先登入）。登入當下就講，還有機會處理。
        result["recoveryCodesRemaining"] = recovery_remaining
    return result


#: 掃碼登入的 challenge 走哪個 header。
#:
#: ## 🔴 為什麼不走 query string（§8 FX22）
#: 它是「**拿到就能換到 session**」的秘密（`login_qr_status` 在 `approved`
#: 時直接發 session），而 `qr-status` 是**每 2 秒輪詢一次**的
#: ⇒ ☠️ 它在 uvicorn 的 access log 裡留下的不是一筆，**是一整串**。
#:
#: ⚠️ 嚴重度是**中不是高**，理由要寫出來不要只給一個形容詞：
#: 有效期很短（掃碼到核准之間）＋ 單次使用；讀得到 log 的人已經有伺服器權限；
#: `logs/` 不進每日備份（今天早上為了座標那件已經驗過）。
#: 🔑 **它是縱深防禦的問題，不是「現在就會被打」的問題。**
#: ☠️ 而它與座標那件是同一族：三張表都堵了，**漏的那一層在 web server 裡**。
LOGIN_CHALLENGE_HEADER = "X-Login-Challenge"


def _login_challenge(request: Request, header_value: str) -> str:
    """從 header 取 challenge。**放在 query string 就 422。**

    ## ⚠️ 拿掉參數宣告 ≠ 那條路被擋住
    FastAPI **會忽略沒有宣告的 query 參數** ⇒ 帶了它不會報錯
    ⇒ ☠️ 舊的前端會**靜靜地送、而伺服器靜靜地忽略**，
    而那個 challenge **仍然進了 access log**。
    🔑 〈守門守的對象被搬走〉：宣告拿掉了，而那條路還通。
    ⇒ 所以這裡**主動去看 query string**，看到就拒絕。

    📌 錯誤訊息要**指路**（該走 header 還是 body）——
    不指路的話下一個人會以為只是格式寫錯，然後再送一次。
    """
    if request.query_params.get("challenge") is not None:
        raise HTTPException(
            422,
            "challenge 不可以放在網址上：query string 會被寫進伺服器的 "
            f"access log。請改用 {LOGIN_CHALLENGE_HEADER} header。")
    value = (header_value or "").strip()
    if not value:
        raise HTTPException(
            422, f"缺少 {LOGIN_CHALLENGE_HEADER} header（challenge 走 header，不走網址）。")
    return value


@router.get("/api/auth/login/qr-info")
def login_qr_info(request: Request, x_login_challenge: str = Header(None)):
    """Public — the phone's camera opens login-qr-approve.html straight from
    the QR code, with no session token yet. Lets that page show a masked
    account name so the legitimate phone owner can recognise their own
    in-progress login before typing a password.

    2026-09-22（§8 FX22）：challenge 改走 `X-Login-Challenge` header。
    """
    challenge = _login_challenge(request, x_login_challenge)
    _totp_sweep_expired()
    with _totp_lock:
        pending = _totp_pending.get(challenge)
    if not pending:
        raise HTTPException(400, "此登入請求已逾時或無效，請回到電腦重新登入")
    conn = get_db()
    row = conn.execute(
        "SELECT username, display_name FROM users WHERE id=?", (pending["user_id"],)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(400, "此登入請求已逾時或無效")
    return {"maskedUsername": _mask_username(row["display_name"] or row["username"])}


@router.post("/api/auth/login/qr-approve")
def login_qr_approve(body: QrApproveIn, request: Request):
    """Public — phone approves the pending login here, either by password or
    (2026-09-08 新增) by an existing session token already held by that
    phone's browser. Does NOT issue a session for the phone itself (it
    shouldn't hold the desktop's token) — it just flips pending["approved"],
    which login_qr_status() below (polled by the desktop) picks up."""
    ip = _client_ip(request)
    _totp_sweep_expired()
    with _totp_lock:
        pending = _totp_pending.get(body.challenge_token)
    if not pending:
        raise HTTPException(400, "此登入請求已逾時或無效，請回到電腦重新登入")

    conn = get_db()
    row = conn.execute(
        "SELECT id, username, password_hash FROM users WHERE id=?",
        (pending["user_id"],),
    ).fetchone()

    if body.session_token:
        # 手機瀏覽器已經是登入狀態時免再輸入密碼——用手機現有 session 驗證
        # 身分，但仍要求 session 的帳號跟這次核准請求的目標帳號完全相同，
        # 不能拿「手機上隨便哪個已登入帳號」核准別人的登入請求。session
        # token 是 32-byte 隨機值，不像密碼/驗證碼可被暴力猜測，這條路徑
        # 刻意不計入共用的 fails 計數器（比照既有慣例：只有「猜測型」的
        # 失敗才計入 lockout）。
        sess = conn.execute(
            "SELECT user_id FROM sessions WHERE token=? AND expires_at > ?",
            (body.session_token, datetime.now().isoformat()),
        ).fetchone()
        conn.close()
        if not sess or not row or sess["user_id"] != row["id"]:
            raise HTTPException(401, "手機目前登入的帳號跟這次核准請求不符，請改用密碼核准")
        with _totp_lock:
            still = _totp_pending.get(body.challenge_token)
            if still:
                still["approved"] = True
        _audit(body.session_token, "auth.login_qr_approve", "user", row["username"], row["username"],
               {"method": "session", "ip": ip})
        return {"ok": True}

    conn.close()
    if not body.password:
        raise HTTPException(400, "請輸入密碼")

    if not row or not _verify_pw(body.password, row["password_hash"]):
        _rl_fail(ip, row["username"] if row else "")
        # 共用同一個 pending["fails"] 計數器（跟手動輸入驗證碼那條路徑同一組上限），
        # 不是另開一組獨立的失敗次數——避免同一張 challenge 變相有兩倍可猜次數。
        with _totp_lock:
            still = _totp_pending.get(body.challenge_token)
            if still:
                still["fails"] += 1
                if still["fails"] >= _TOTP_MAX_FAILS:
                    del _totp_pending[body.challenge_token]
                    raise HTTPException(401, "密碼錯誤次數過多，請回到電腦重新登入")
        raise HTTPException(401, "密碼不正確")

    with _totp_lock:
        still = _totp_pending.get(body.challenge_token)
        if still:
            still["approved"] = True
    _rl_clear(ip)
    # 密碼核准：呼叫端沒有 session ⇒ 以被核准的帳號記在 target（username 欄留空）。
    _audit(None, "auth.login_qr_approve", "user", row["username"], row["username"],
           {"method": "password", "ip": ip})
    return {"ok": True}


@router.get("/api/auth/login/qr-status")
def login_qr_status(request: Request, x_login_challenge: str = Header(None)):
    """Public — polled by the desktop login page every ~2s while showing the
    QR code. Only issues the real session once (single-use, mirrors the
    manual-code path), the first time it observes approved=True.

    ⚠️ **兩支要一起改**（§8 FX22b）：它們用的是**同一個** challenge
    ⇒ 只改一支的話，另一支照樣把它洩進 access log ——
    🔑 而這一支是**每 2 秒一次**的那一支。
    """
    challenge = _login_challenge(request, x_login_challenge)
    _totp_sweep_expired()
    with _totp_lock:
        pending = _totp_pending.get(challenge)
        if not pending:
            raise HTTPException(400, "此登入請求已逾時或無效，請重新登入")
        if not pending["approved"]:
            return {"pending": True}
        del _totp_pending[challenge]

    conn = get_db()
    row = conn.execute(
        "SELECT id, username, display_name, role, modules FROM users WHERE id=?",
        (pending["user_id"],),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(400, "帳號不存在或已停用")
    result = _issue_session(conn, row, pending["must_change"])
    conn.close()
    return result


@router.get("/api/auth/totp/status")
def totp_status(authorization: str = Header(None)):
    """2026-09-11 新增 `recoveryCodesRemaining`：救援碼是一次性的，用掉就從清單
    移除，但在這之前**沒有任何地方看得到還剩幾組**——使用者只會在最後一組也用完、
    驗證 App 又剛好不在手邊時，才發現自己被鎖在外面，而那時已經來不及自助補救
    （重產端點需要先登入）。回傳剩餘組數讓「修改密碼」頁能提早示警。

    只回組數、不回內容：DB 只存雜湊，明文從一開始就只在產生當下出現一次。"""
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT COALESCE(totp_enabled,0) AS totp_enabled, totp_recovery_codes "
        "FROM users WHERE id=?", (user["id"],)).fetchone()
    conn.close()
    if not row:
        return {"enabled": False, "recoveryCodesRemaining": 0}
    try:
        remaining = len(json.loads(row["totp_recovery_codes"] or "[]"))
    except Exception:
        # 這個欄位是自由格式 JSON，人工改過的資料不該讓整支狀態端點 500——
        # 回 0 會讓畫面示警「已用罄」，比整頁壞掉好判斷
        remaining = 0
    return {"enabled": bool(row["totp_enabled"]), "recoveryCodesRemaining": remaining}


@router.post("/api/auth/totp/setup")
def totp_setup(authorization: str = Header(None)):
    """產生新的 TOTP 密鑰（尚未生效，`totp_enabled` 仍是 0，需接著呼叫
    /api/auth/totp/enable 驗證一次正確的驗證碼才會真正切換過去）。任何角色
    皆可自助呼叫——採自助啟用而非強制，見 db.py::_m072_totp() docstring。
    重複呼叫會覆蓋掉尚未經 enable 確認的暫存密鑰，已啟用狀態下呼叫視同
    「重新設定」，在完成新一輪 enable 前，登入仍然驗證舊密鑰。"""
    user = _require_user(authorization)
    secret = pyotp.random_base32()
    conn = get_db()
    conn.execute("UPDATE users SET totp_secret=? WHERE id=?", (secret, user["id"]))
    conn.commit()
    conn.close()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user["username"], issuer_name="MOTRIX 專案管理系統")
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()
    _audit(_tok(authorization), 'auth.totp_setup', 'user', user['username'], user.get('display_name') or user['username'])
    return {"secret": secret, "otpauthUri": uri, "qrCodePng": f"data:image/png;base64,{qr_b64}"}


@router.post("/api/auth/totp/enable")
def totp_enable(body: TotpEnableIn, authorization: str = Header(None)):
    """驗證一次正確的驗證碼後才真正啟用，避免掃錯 QR code／密鑰輸入錯誤卻
    直接生效導致下次登入被鎖在外面。成功後產生 10 組一次性救援碼，明文只在
    這次回應裡出現一次，DB 只存雜湊（見 db.py::_m072_totp() docstring）。"""
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT totp_secret FROM users WHERE id=?", (user["id"],)).fetchone()
    if not row or not row["totp_secret"]:
        conn.close()
        raise HTTPException(400, "請先呼叫設定端點取得密鑰")
    if not pyotp.TOTP(row["totp_secret"]).verify((body.code or "").strip(), valid_window=1):
        conn.close()
        raise HTTPException(400, "驗證碼不正確，請確認驗證 App 時間與密鑰輸入無誤")
    recovery_plain  = [secrets.token_hex(4) for _ in range(10)]
    recovery_hashed = [_hash_pw(c) for c in recovery_plain]
    conn.execute(
        "UPDATE users SET totp_enabled=1, totp_recovery_codes=? WHERE id=?",
        (json.dumps(recovery_hashed, ensure_ascii=False), user["id"]),
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "auth.totp_enabled", "user", user["username"],
           user.get("display_name") or user["username"])
    return {"ok": True, "recoveryCodes": recovery_plain}


@router.post("/api/auth/totp/recovery-codes/regenerate")
def totp_regenerate_recovery_codes(body: TotpRegenRecoveryIn, authorization: str = Header(None)):
    """重新產生 10 組救援碼（2026-09-11 新增）。

    **為什麼需要**：救援碼是一次性的，用一組少一組，用完就再也沒有「驗證 App
    不在手邊」時的退路。先前唯一的補救方式是停用 TOTP 再重新啟用一輪——那會
    連帶把密鑰也換掉，等於要重掃一次 QR code，成本高到沒人會主動做，結果就是
    大家用到剩最後一組也不處理。這支端點讓補充救援碼跟密鑰脫鉤。

    **語意是「整組換掉」不是「補到 10 組」**：舊的救援碼在這次呼叫後全部失效。
    理由是印出來/存起來的那張舊清單，使用者無從知道其中哪幾組還有效——若採
    「補足」語意，新舊混在一起會讓人以為舊清單整張都還能用。回應會明講這件事。

    **要求目前密碼**：比照同檔 totp_disable()／verify-unlock 的敏感操作慣例。
    不另外要求驗證碼——會呼叫這支的情境正是「驗證 App 拿不到」，再要一次
    驗證碼等於把唯一的出口也堵住。已登入的 session ＋ 密碼是這裡的兩道。

    **必須已啟用 TOTP**：沒啟用時救援碼沒有任何意義，回 400 而不是默默產生一組
    永遠用不到的碼。
    """
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT password_hash, COALESCE(totp_enabled,0) AS totp_enabled FROM users WHERE id=?",
        (user["id"],)).fetchone()
    if not row or not _verify_pw(body.password, row["password_hash"]):
        conn.close()
        raise HTTPException(400, "密碼不正確")
    if not row["totp_enabled"]:
        conn.close()
        raise HTTPException(400, "尚未啟用兩步驟驗證，沒有救援碼可以重新產生")

    recovery_plain  = [secrets.token_hex(4) for _ in range(10)]
    recovery_hashed = [_hash_pw(c) for c in recovery_plain]
    conn.execute("UPDATE users SET totp_recovery_codes=? WHERE id=?",
                 (json.dumps(recovery_hashed, ensure_ascii=False), user["id"]))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "auth.totp_recovery_regenerated", "user", user["username"],
           f"{user.get('display_name') or user['username']}：重新產生 10 組救援碼，舊的全部失效")
    return {"ok": True, "recoveryCodes": recovery_plain, "replacedPrevious": True}


@router.post("/api/auth/totp/disable")
def totp_disable(body: TotpDisableIn, authorization: str = Header(None)):
    """停用需重新輸入目前密碼確認身分（比照本檔既有 verify-unlock 的敏感操作
    慣例），不需要再帶一次驗證碼——密碼本身就是這裡要求的第二重確認。"""
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT password_hash FROM users WHERE id=?", (user["id"],)).fetchone()
    if not row or not _verify_pw(body.password, row["password_hash"]):
        conn.close()
        raise HTTPException(400, "密碼不正確")
    conn.execute(
        "UPDATE users SET totp_enabled=0, totp_secret='', totp_recovery_codes='[]' WHERE id=?",
        (user["id"],),
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "auth.totp_disabled", "user", user["username"],
           user.get("display_name") or user["username"])
    return {"ok": True}


# ── WebAuthn/Passkey device binding (2026-09-09, self-service) ────────────────
#
# V1 design: already-logged-in users can register multiple devices; login path
# requires username first (not usernameless/resident-key mode). Follows same
# self-service model as TOTP — optional, not forced.
#
# ⚠️ Crucial safeguards (not negotiable — must ship with V1):
# - sign_count replay-attack detection (increment & verify on every login)
# - credential revocation (individual delete, no orphaned DB rows)
# These are security minimums, not future enhancements.

from webauthn.helpers.structs import PublicKeyCredentialDescriptor, PublicKeyCredentialType, AuthenticatorTransport

_webauthn_lock = threading.Lock()
# challenge_token -> {"user_id": int, "challenge": bytes, "expires": monotonic_time}
_webauthn_challenges: dict = {}
_WEBAUTHN_CHALLENGE_TTL_S = 600  # 10 minutes


def _require_passkey_enabled() -> None:
    """Passkey 功能總開關的守門（2026-09-16 起預設關閉，見 helpers/auth.py）。

    **必須掛成 route dependency（`dependencies=[Depends(...)]`），不能只在函式
    第一行呼叫**——這是實測踩到的：FastAPI 先解 dependencies，**之後**才驗
    Pydantic body。寫在函式裡的話，帶 body 的端點（register/complete、
    login/begin、login/complete、credential rename）在 body 不合格時會先回 422，
    連函式都沒進去，守門形同不存在。而那個 422 會把欄位名稱一併列出來：

        {"loc": ["body", "challengeToken"], "msg": "Field required"}, ...

    等於在功能「已經關掉」的情況下，對外確認了這支端點存在並公布它的介面。
    掛成 dependency 之後，四支帶 body 的端點才真的一律 404。

    **刻意讀模組屬性而不是 `from helpers.auth import PASSKEY_ENABLED`**：
    後者在 import 當下就把值綁死，測試沒辦法把功能暫時打開來驗證兩種狀態，
    而「停用真的生效」這件事只有兩種狀態都測過才算數
    （見 tests/test_passkey_disabled_2026_09_16.py 的反向驗證）。

    回 404 不回 403/503：503 會觸發前端「請聯繫管理員設定 WebAuthn 網域」
    那句話，把使用者引去要一個現在不該開的功能；404 等同「沒有這支端點」。
    """
    from helpers import auth as _auth_helpers
    if not _auth_helpers.PASSKEY_ENABLED:
        raise HTTPException(status_code=404, detail="Not Found")


def _webauthn_origin() -> str:
    """Get WebAuthn origin from system settings (key `webauthn_origin`).

    Returns "" when unconfigured — callers must treat that as "not set up yet"
    and raise 503, NOT fall back to a localhost default: a wrong origin makes
    the browser reject the credential with an opaque "invalid domain" error
    that looks like a client bug (2026-09-10, see §12)."""
    from helpers.settings import _get_setting
    val = _get_setting("webauthn_origin")
    return val if val else ""


def _b64url_decode(data: str) -> bytes:
    """解 WebAuthn 用的 base64url（沒有 padding）。

    2026-09-10：這裡原本用 `base64.b64decode()`，那是**標準** base64 解碼器——
    它不認得 base64url 的 `-` 和 `_`（預設當成非字母字元丟掉），又要求 padding
    長度正確，於是一律丟 `binascii.Error: Incorrect padding`。前端
    （change-password.html / login.html 的 `_uint8ArrayToB64`）產出的正是
    「base64url 且把 `=` 全部去掉」的格式，所以**每一次 Passkey 註冊與登入都
    必定失敗**，而且錯誤被上層的 `except Exception` 收斂成一句籠統的
    「認證器驗證失敗」，從畫面上完全看不出真正原因（實際是靠正式機 server.log
    裡的 `WebAuthn registration failed: Incorrect padding` 才找到）。

    這裡順便容忍標準 base64（`+/`）的輸入，避免日後換前端寫法又踩一次。
    """
    s = (data or "").strip().replace("+", "-").replace("/", "_")
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _webauthn_rp_id() -> str:
    """Get WebAuthn RP ID from system settings (key `webauthn_rp_id`).

    Returns "" when unconfigured — see `_webauthn_origin()` for why there is
    deliberately no localhost fallback."""
    from helpers.settings import _get_setting
    val = _get_setting("webauthn_rp_id")
    return val if val else ""


def _store_webauthn_challenge(challenge: bytes) -> str:
    """Store challenge server-side, return opaque token for client to pass back."""
    token = secrets.token_hex(16)
    now = time.monotonic()
    with _webauthn_lock:
        _webauthn_challenges[token] = {"challenge": challenge, "expires": now + _WEBAUTHN_CHALLENGE_TTL_S}
    return token


def _retrieve_webauthn_challenge(token: str) -> Optional[bytes]:
    """Retrieve and consume challenge (single-use). Return None if expired or not found."""
    with _webauthn_lock:
        data = _webauthn_challenges.pop(token, None)
        if not data:
            return None
        if time.monotonic() > data["expires"]:
            return None
        return data["challenge"]


@router.post("/api/auth/webauthn/register/begin", dependencies=[Depends(_require_passkey_enabled)])
def webauthn_register_begin(authorization: str = Header(None)):
    """已登入使用者開始 Passkey 註冊流程。回傳 W3C WebAuthn registration options
    JSON，以及 challenge_token 供前端在 complete 時回傳。"""
    rp_id = _webauthn_rp_id()
    origin = _webauthn_origin()
    if not rp_id or not origin:
        raise HTTPException(status_code=503, detail="尚未設定 WebAuthn 網域，請聯繫管理員")

    user = _require_user(authorization)
    conn = get_db()
    try:
        existing_creds = conn.execute(
            "SELECT credential_id FROM webauthn_credentials WHERE user_id=?",
            (user["id"],)
        ).fetchall()
    finally:
        conn.close()

    exclude_credentials = [
        PublicKeyCredentialDescriptor(
            type=PublicKeyCredentialType.PUBLIC_KEY,
            id=cred["credential_id"]
        )
        for cred in existing_creds
    ]

    options = generate_registration_options(
        rp_id=rp_id,
        rp_name="MOTRIX 專案管理系統",
        user_id=str(user["id"]).encode("utf-8"),
        user_name=user["username"],
        user_display_name=user.get("display_name") or user["username"],
        exclude_credentials=exclude_credentials,
    )
    challenge_token = _store_webauthn_challenge(options.challenge)
    options_json = options_to_json(options)
    return {
        "challengeToken": challenge_token,
        "options": json.loads(options_json) if isinstance(options_json, str) else options_json
    }


@router.post("/api/auth/webauthn/register/complete", dependencies=[Depends(_require_passkey_enabled)])
def webauthn_register_complete(body: WebauthnRegisterCompleteIn, authorization: str = Header(None)):
    """完成 Passkey 註冊：驗證認證器回應、儲存公鑰與 credential_id。"""
    user = _require_user(authorization)

    # Get challenge_token from request body (frontend should include it)
    challenge_token = body.dict().get("challengeToken")
    if not challenge_token:
        raise HTTPException(400, "缺少 challengeToken")

    challenge = _retrieve_webauthn_challenge(challenge_token)
    if not challenge:
        raise HTTPException(400, "Challenge 已過期或無效")

    conn = get_db()
    try:
        existing_creds = conn.execute(
            "SELECT credential_id FROM webauthn_credentials WHERE user_id=?",
            (user["id"],)
        ).fetchall()
        existing_ids = {cred["credential_id"] for cred in existing_creds}

        try:
            cred_raw_id = _b64url_decode(body.rawId)
            if cred_raw_id in existing_ids:
                conn.close()
                raise HTTPException(400, "此認證器已被註冊")

            verified = verify_registration_response(
                credential=body.dict(),
                expected_challenge=challenge,
                expected_origin=_webauthn_origin(),
                expected_rp_id=_webauthn_rp_id(),
            )
            public_key_bytes = verified.credential_public_key
            # 2026-09-11（DB v74）：記下這張憑證是在哪個 RP ID 底下註冊的。
            # 瀏覽器把憑證綁在註冊當下的 RP ID 上，日後 RP ID 一變更，沒存這個
            # 欄位就查不出哪幾張失效——只能對使用者說「全部都可能不能用了」。
            conn.execute(
                "INSERT INTO webauthn_credentials "
                "(user_id, credential_id, public_key, name, created_at, rp_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user["id"], cred_raw_id, public_key_bytes, "新Passkey",
                 datetime.now().isoformat(), _webauthn_rp_id()),
            )
            conn.commit()
        except HTTPException:
            conn.close()
            raise
        except Exception as e:
            conn.close()
            logger.error("WebAuthn registration failed: %s", str(e))
            raise HTTPException(400, f"認證器驗證失敗")
    finally:
        conn.close()

    _audit(_tok(authorization), "auth.webauthn_registered", "user", user["username"],
           user.get("display_name") or user["username"])
    return {"ok": True}


@router.post("/api/auth/webauthn/login/begin", dependencies=[Depends(_require_passkey_enabled)])
def webauthn_login_begin(body: WebauthnLoginBeginIn):
    """未登入時開始 Passkey 登入：查該帳號已註冊的 credential 清單、回傳
    authentication options JSON 與 challenge_token。統一錯誤響應避免用戶枚舉。"""
    rp_id = _webauthn_rp_id()
    if not rp_id:
        raise HTTPException(status_code=503, detail="尚未設定 WebAuthn 網域，請聯繫管理員")

    conn = get_db()
    try:
        user_row = conn.execute(
            "SELECT id FROM users WHERE username=? AND active=1",
            (body.username,)
        ).fetchone()
        if not user_row:
            raise HTTPException(404, "無法開始 Passkey 登入")

        creds = conn.execute(
            "SELECT credential_id, rp_id FROM webauthn_credentials WHERE user_id=?",
            (user_row["id"],)
        ).fetchall()

        # 只把「在現行 RP ID 下註冊的」憑證交給瀏覽器。rp_id='' 是 v74 之前
        # 留下的舊資料（來源不明），一律當成相符，以免把還能用的憑證擋掉。
        usable = [c for c in creds if c["rp_id"] in ("", rp_id)]

        if creds and not usable:
            # RP ID 變更後的典型狀況：憑證還在，但全部綁在舊網域上。
            # ⚠️ 對外仍回**同一句**錯誤——這裡若照實說「你的 Passkey 已失效」，
            # 等於確認了這個帳號存在而且有註冊過 Passkey（`0527524` 修掉的
            # 用戶枚舉漏洞就是這種洩漏）。真正要讓使用者看到的地方是登入後的
            # 裝置清單（有 stale 標記），那裡沒有枚舉風險。
            logger.warning(
                "WebAuthn login blocked: all %d credential(s) for user_id=%s were "
                "registered under a different RP ID (current=%s). RP ID 變更後既有 "
                "Passkey 無法救回，使用者需以密碼登入後重新註冊。",
                len(creds), user_row["id"], rp_id,
            )
            raise HTTPException(404, "無法開始 Passkey 登入")

        if not usable:
            raise HTTPException(404, "無法開始 Passkey 登入")

        creds = usable
        allow_credentials = [
            PublicKeyCredentialDescriptor(
                type=PublicKeyCredentialType.PUBLIC_KEY,
                id=cred["credential_id"],
                transports=[AuthenticatorTransport.INTERNAL, AuthenticatorTransport.USB]
            )
            for cred in creds
        ]

        options = generate_authentication_options(
            rp_id=rp_id,
            allow_credentials=allow_credentials,
        )
        challenge_token = _store_webauthn_challenge(options.challenge)
        options_json = options_to_json(options)
        return {
            "challengeToken": challenge_token,
            "options": json.loads(options_json) if isinstance(options_json, str) else options_json
        }
    finally:
        conn.close()


@router.post("/api/auth/webauthn/login/complete", dependencies=[Depends(_require_passkey_enabled)])
def webauthn_login_complete(body: WebauthnLoginCompleteIn, request: Request):
    """完成 Passkey 登入：驗證認證器簽名、檢查 sign_count 防重放、發行 session。"""
    # Get and consume challenge
    challenge_token = body.dict().get("challengeToken")
    if not challenge_token:
        _rl_fail(_client_ip(request), body.username)
        raise HTTPException(400, "缺少 challengeToken")

    challenge = _retrieve_webauthn_challenge(challenge_token)
    if not challenge:
        _rl_fail(_client_ip(request), body.username)
        raise HTTPException(401, "Challenge 已過期或無效")

    conn = get_db()
    try:
        user_row = conn.execute(
            "SELECT id, display_name FROM users WHERE username=? AND active=1",
            (body.username,)
        ).fetchone()
        if not user_row:
            conn.close()
            _rl_fail(_client_ip(request), body.username)
            raise HTTPException(401, "帳號不存在或已停用")

        cred_raw_id = _b64url_decode(body.rawId)
        cred_row = conn.execute(
            "SELECT id, public_key, sign_count, rp_id FROM webauthn_credentials "
            "WHERE user_id=? AND credential_id=?",
            (user_row["id"], cred_raw_id)
        ).fetchone()
        if not cred_row:
            conn.close()
            _rl_fail(_client_ip(request), body.username)
            raise HTTPException(401, "認證失敗")

        # 2026-09-11（DB v74）：這張憑證是在別的 RP ID 下註冊的 → 一定驗不過。
        # 走到這裡代表對方握有真實的 credential_id，不是枚舉探測，所以可以講清楚
        # 原因。少了這一段，py_webauthn 會丟一個關於 rpIdHash 不符的例外，被下面
        # 那個概括的 except 收斂成一句「認證失敗」——而 2026-09-11 那四個根因
        # 全都是被這種籠統錯誤蓋掉才拖了那麼久才找到的。
        if cred_row["rp_id"] and cred_row["rp_id"] != _webauthn_rp_id():
            conn.close()
            _rl_fail(_client_ip(request), body.username)
            logger.warning(
                "WebAuthn login rejected: credential id=%s registered under rp_id=%s, "
                "current rp_id=%s", cred_row["id"], cred_row["rp_id"], _webauthn_rp_id(),
            )
            raise HTTPException(
                401,
                "此 Passkey 是在舊的系統網域下註冊的，因網域變更已失效且無法復原。"
                "請改用密碼登入後，到「修改密碼」頁重新註冊一張。",
            )

        try:
            verified = verify_authentication_response(
                credential=body.dict(),
                expected_challenge=challenge,
                expected_origin=_webauthn_origin(),
                expected_rp_id=_webauthn_rp_id(),
                credential_public_key=cred_row["public_key"],
                credential_current_sign_count=cred_row["sign_count"],
            )

            # py_webauthn 的**認證**結果欄位叫 `new_sign_count`；只有**註冊**結果
            # （VerifiedRegistration）才叫 `sign_count`。2026-09-11：這裡原本寫
            # `verified.sign_count`，於是每次登入都丟 AttributeError，被下面那個
            # 概括的 `except Exception` 收斂成一句 401「認證失敗」——換句話說
            # Passkey 登入從來沒有成功過，而畫面上完全看不出原因，只有 server.log
            # 裡一行 `'VerifiedAuthentication' object has no attribute 'sign_count'`。
            new_count = verified.new_sign_count

            # W3C WebAuthn §7.2 step 21：只有在「新舊計數至少一邊不是 0」的前提下，
            # 計數沒有前進才算認證器被複製的徵兆。很多平台認證器根本不實作計數器
            # （Windows Hello、iCloud／Google 同步的 passkey 都是），永遠回 0；
            # 少了這個前提，那些認證器**每一次**登入都會被誤判成重放攻擊。
            if (new_count or cred_row["sign_count"]) and new_count <= cred_row["sign_count"]:
                conn.close()
                logger.warning("WebAuthn replay attack detected: user=%s cred_id=%d", body.username, cred_row["id"])
                _audit("", "auth.webauthn_replay_detected", "user", body.username, "重放攻擊被阻止")
                raise HTTPException(401, "認證失敗（重放攻擊偵測）")

            conn.execute(
                "UPDATE webauthn_credentials SET sign_count=?, last_used_at=? WHERE id=?",
                (new_count, datetime.now().isoformat(), cred_row["id"])
            )

            user_full = conn.execute(
                "SELECT id, username, display_name, role, modules FROM users WHERE id=?",
                (user_row["id"],)
            ).fetchone()
            result = _issue_session(conn, user_full, False)
            return result

        except HTTPException:
            conn.close()
            raise
        except Exception as e:
            conn.close()
            logger.error("WebAuthn authentication failed: %s", str(e))
            _rl_fail(_client_ip(request), body.username)
            raise HTTPException(401, "認證失敗")
    finally:
        if conn:
            conn.close()


@router.get("/api/auth/webauthn/credentials", dependencies=[Depends(_require_passkey_enabled)])
def webauthn_credentials_list(authorization: str = Header(None)):
    """已登入使用者的 Passkey 清單（名稱、建立日期、最後使用日期）。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, name, created_at, last_used_at, rp_id FROM webauthn_credentials "
            "WHERE user_id=? ORDER BY created_at DESC",
            (user["id"],)
        ).fetchall()
    finally:
        conn.close()

    # 2026-09-11（DB v74）：標出「因系統網域變更而失效」的憑證。
    # 這是使用者唯一能看懂「為什麼我的 Passkey 突然不能用」的地方——登入前的
    # 錯誤訊息刻意維持統一（避免用戶枚舉），所以真相只能在這裡講。
    # rp_id='' 是 v74 之前的舊資料，來源不明，一律不標成失效。
    current_rp = _webauthn_rp_id()
    out = []
    for row in rows:
        item = dict(row)
        item["stale"] = bool(current_rp and row["rp_id"] and row["rp_id"] != current_rp)
        out.append(item)
    return out


@router.patch("/api/auth/webauthn/credentials/{cred_id}", dependencies=[Depends(_require_passkey_enabled)])
def webauthn_credential_rename(cred_id: int, body: WebauthnCredentialRenameIn, authorization: str = Header(None)):
    """改名單個 Passkey（如「iPhone」、「Windows Hello」）。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        cred_row = conn.execute(
            "SELECT id FROM webauthn_credentials WHERE id=? AND user_id=?",
            (cred_id, user["id"])
        ).fetchone()
        if not cred_row:
            raise HTTPException(404, "認證器不存在或無存取權限")
        conn.execute(
            "UPDATE webauthn_credentials SET name=? WHERE id=?",
            (body.name, cred_id)
        )
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "auth.webauthn_renamed", "credential", str(cred_id),
           body.name)
    return {"ok": True}


@router.delete("/api/auth/webauthn/credentials/{cred_id}", dependencies=[Depends(_require_passkey_enabled)])
def webauthn_credential_delete(cred_id: int, authorization: str = Header(None)):
    """撤銷單個 Passkey。必須是可用功能——遺失裝置時使用者需要能自己補救。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        cred_row = conn.execute(
            "SELECT id FROM webauthn_credentials WHERE id=? AND user_id=?",
            (cred_id, user["id"])
        ).fetchone()
        if not cred_row:
            raise HTTPException(404, "認證器不存在或無存取權限")
        conn.execute("DELETE FROM webauthn_credentials WHERE id=?", (cred_id,))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "auth.webauthn_revoked", "credential", str(cred_id), "")
    return {"ok": True}


@router.post("/api/auth/logout")
def auth_logout(authorization: str = Header(None)):
    token = _tok(authorization)
    if token.startswith(DEMO_TOKEN_PREFIX):
        # _audit() looks the token up in the real sessions table, which a demo
        # token never touches — skip it rather than log a meaningless miss.
        dconn = get_demo_db()
        dconn.execute("DELETE FROM sessions WHERE token=?", (token,))
        dconn.commit()
        dconn.close()
        return {"ok": True}
    _audit(token, 'auth.logout', 'user', '', '登出')
    if authorization and authorization.startswith("Bearer "):
        conn = get_db()
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit()
        conn.close()
    return {"ok": True}


@router.get("/api/auth/me")
def auth_me(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "未登入")
    token = authorization[7:]
    conn = get_db()
    row = conn.execute("""
        SELECT u.id, u.username, u.display_name, u.role, u.modules,
               COALESCE(u.must_change_password, 0) AS must_change_password
        FROM sessions s JOIN users u ON s.user_id = u.id
        WHERE s.token=? AND u.active=1
          AND (s.expires_at IS NULL OR s.expires_at > datetime('now'))
    """, (token,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(401, "Session 已過期，請重新登入")
    return {
        "userId":             row["id"],
        "username":           row["username"],
        "displayName":        row["display_name"],
        "role":               row["role"],
        "modules":            json.loads(row["modules"] or "[]"),
        "mustChangePassword": bool(row["must_change_password"]),
    }


@router.patch("/api/auth/change-password")
def change_password(body: ChangePasswordIn, authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "未登入")
    token = authorization[7:]
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        row = conn.execute("""
            SELECT u.id, u.password_hash, u.display_name, u.username
            FROM sessions s JOIN users u ON s.user_id = u.id
            WHERE s.token=? AND u.active=1
              AND (s.expires_at IS NULL OR s.expires_at > ?)
        """, (token, now)).fetchone()
        if not row:
            raise HTTPException(401, "Session 已過期，請重新登入")
        if not _verify_pw(body.current_password, row["password_hash"]):
            raise HTTPException(400, "目前密碼不正確")
        if len(body.new_password) < MIN_PASSWORD_LEN:
            raise HTTPException(400, f"新密碼至少需要 {MIN_PASSWORD_LEN} 碼")
        if is_weak_password(body.new_password):
            raise HTTPException(400, "新密碼過於簡單或為已知弱密碼，請改用更強的密碼")
        if body.new_password == body.current_password:
            raise HTTPException(400, "新密碼不可與目前密碼相同")
        new_hash = _hash_pw(body.new_password)
        conn.execute(
            "UPDATE users SET password_hash=?, must_change_password=0 WHERE id=?",
            (new_hash, row["id"]),
        )
        conn.execute("DELETE FROM sessions WHERE user_id=? AND token!=?", (row["id"], token))
        conn.commit()
    finally:
        conn.close()
    _audit(token, 'auth.change_password', 'user', '', '修改密碼')
    notify_module_activity("使用者管理", "變更密碼", row["display_name"] or row["username"],
                            row["display_name"] or row["username"], "users.html")
    return {"ok": True, "mustChangePassword": False}


# ── User Management ───────────────────────────────────────────────────────────

@router.get("/api/users")
def list_users(authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    rows = conn.execute("""
        SELECT u.id, u.username, u.display_name, u.role, u.email, u.phone, u.modules,
               u.notification_muted, u.active, u.created_at,
               u.department_id, dep.name AS department_name,
               dep.division_id, dv.name AS division_name
        FROM users u
        LEFT JOIN departments dep ON dep.id = u.department_id
        LEFT JOIN divisions dv ON dv.id = dep.division_id
        ORDER BY u.id
    """).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["displayName"]        = d.pop("display_name")
        d["createdAt"]          = d.pop("created_at")
        d["modules"]             = json.loads(d["modules"] or "[]")
        d["notificationMuted"]   = json.loads(d.pop("notification_muted") or "[]")
        d["departmentId"]        = d.pop("department_id")
        d["departmentName"]      = d.pop("department_name")
        d["divisionId"]          = d.pop("division_id")
        d["divisionName"]        = d.pop("division_name")
        result.append(d)
    return result


@router.post("/api/users", status_code=201)
def create_user(body: UserIn, authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    if not body.username or not body.password:
        raise HTTPException(400, "缺少帳號或密碼")
    if len(body.password) < MIN_PASSWORD_LEN:
        raise HTTPException(400, f"密碼至少 {MIN_PASSWORD_LEN} 碼")
    if is_weak_password(body.password):
        raise HTTPException(400, "密碼過於簡單或為已知弱密碼，請改用更強的密碼")
    now = datetime.now().isoformat()
    refuse_unknown_new_keys(body.modules)
    from helpers import mail_types as _mt
    from helpers.notification_prefs import EVENT_KEYS as _EVENT_KEYS
    unknown = [k for k in (body.notification_muted or []) if _mt.get(k) is None and k not in _EVENT_KEYS]
    if unknown:
        raise HTTPException(400, "不認得的信件類型：%s" % "、".join(unknown))
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO users (username, password_hash, display_name, role, email, phone, modules,
                               notification_muted, active, created_at, must_change_password, department_id)
            VALUES (?,?,?,?,?,?,?,?,1,?,1,?)
        """, (
            body.username.strip(),
            _hash_pw(body.password),
            body.display_name or '',
            body.role or 'viewer',
            body.email or '',
            body.phone or '',
            json.dumps(body.modules or [], ensure_ascii=False),
            json.dumps(body.notification_muted or [], ensure_ascii=False),
            now,
            body.department_id or None,
        ))
        conn.commit()
        user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(409, "帳號已存在")
    conn.close()
    _audit(_tok(authorization), 'user.create', 'user', body.username, body.display_name or body.username)
    notify_module_activity("使用者管理", "建立帳號", actor.get("display_name") or actor["username"],
                            body.display_name or body.username, "users.html")
    return {"id": user_id, "created_at": now, "mustChangePassword": True}


@router.put("/api/users/{user_id}")
def update_user(user_id: int, body: UserIn, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    if not conn.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone():
        conn.close()
        raise HTTPException(404, "使用者不存在")
    if body.modules is not None:
        _old = conn.execute("SELECT modules FROM users WHERE id=?", (user_id,)).fetchone()
        try:
            refuse_unknown_new_keys(body.modules, json.loads((_old["modules"] if _old else None) or "[]"))
        except HTTPException:
            conn.close()
            raise
    sets, params = [], []
    if body.display_name is not None: sets.append("display_name=?"); params.append(body.display_name)
    if body.role         is not None: sets.append("role=?");         params.append(body.role)
    if body.email        is not None: sets.append("email=?");        params.append(body.email)
    if body.phone        is not None: sets.append("phone=?");        params.append(body.phone)
    if body.modules      is not None: sets.append("modules=?");      params.append(json.dumps(body.modules, ensure_ascii=False))
    if body.notification_muted is not None:
        # 個人退訂只接受登記過的信件類型（CORE-SPEC 信件收件人④）：打錯字或不存在的 key 存進去不會有任何效果，
        # 而畫面會以為已退訂。
        from helpers import mail_types as _mt
        from helpers.notification_prefs import EVENT_KEYS as _EVENT_KEYS   # 模組未載入時它的類型仍可保留在退訂清單
        unknown = [k for k in body.notification_muted if _mt.get(k) is None and k not in _EVENT_KEYS]
        if unknown:
            conn.close()
            raise HTTPException(400, "不認得的信件類型：%s" % "、".join(unknown))
        sets.append("notification_muted=?")
        params.append(json.dumps(body.notification_muted, ensure_ascii=False))
    if body.department_id is not None:
        sets.append("department_id=?")
        params.append(body.department_id or None)   # 0 -> 未分類（清空 NULL）
    if body.password:
        if len(body.password) < MIN_PASSWORD_LEN:
            conn.close()
            raise HTTPException(400, f"密碼至少 {MIN_PASSWORD_LEN} 碼")
        if is_weak_password(body.password):
            conn.close()
            raise HTTPException(400, "密碼過於簡單或為已知弱密碼，請改用更強的密碼")
        sets.append("password_hash=?")
        params.append(_hash_pw(body.password))
        sets.append("must_change_password=?")
        params.append(1)
    if sets:
        params.append(user_id)
        conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", params)
        conn.commit()
    conn.close()
    _audit(_tok(authorization), 'user.update', 'user', str(user_id), body.display_name or str(user_id))
    return {"ok": True}


# ── 個資蒐集告知（CUSTOMIZATION-SPEC §9.3，2026-09-26 擴大到使用者帳號）─────────────────
# 帳號的姓名、Email、電話是員工個資。紀錄存在 L1 設定鍵 `privacy_notice_acks`（`user:<id>`），
# 伺服器蓋時間與人員，已記錄的不覆蓋；沒有紀錄不擋存檔。

@router.get("/api/users/{user_id}/privacy-notice")
def get_user_privacy_ack(user_id: int, authorization: str = Header(None)):
    from helpers import privacy_notice as _pn
    _require_user(authorization, require_superadmin=True)
    return {"ack": _pn.get_ack("user", user_id)}


@router.post("/api/users/{user_id}/privacy-notice/ack")
def ack_user_privacy_notice(user_id: int, authorization: str = Header(None)):
    """記錄「已告知當事人」：時間與人員由伺服器決定；已記錄的不覆蓋。"""
    from helpers import privacy_notice as _pn
    actor = _require_user(authorization, require_superadmin=True)
    conn = get_db()
    row = conn.execute("SELECT username, display_name FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "使用者不存在")
    rec, created = _pn.record_purpose_ack("user", user_id, actor, "user")
    if created:
        _audit(_tok(authorization), 'user.privacy_notice_ack', 'user', str(user_id),
               row["display_name"] or row["username"], {"noticeHash": rec.get("noticeHash")})
    return {"ack": rec, "created": created}


@router.delete("/api/users/{user_id}")
def delete_user(user_id: int, authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    conn = get_db()
    row = conn.execute("SELECT username, display_name FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "使用者不存在")
    if row["username"] == "jeff":
        conn.close()
        raise HTTPException(400, "不可刪除超級管理員帳號")
    uname  = row["username"]
    ulabel = row["display_name"] or uname
    try:
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        conn.commit()
    except sqlite3.IntegrityError:
        # 2026-08-28（模組逐步檢查）：users.id 被多張表以 FK 引用（quotations.
        # sales_person_id／dev_cases.created_by／dev_logs 多欄／divisions／
        # departments.manager_user_id 等）且都沒定 ON DELETE 行為，硬刪除有
        # 關聯資料的帳號原本會被全域 exception handler 接成一個不明不白的
        # 500；改為友善提示——硬刪除本來就只適合沒有歷史資料的誤建/測試帳號，
        # 正式離職應改用 toggle_user_active() 停用。
        conn.rollback()
        conn.close()
        raise HTTPException(409, f"「{ulabel}」仍有關聯資料（如業務開發案件、報價單業務歸屬、部門/處主管等），無法刪除，請改用「停用」")
    conn.close()
    _audit(_tok(authorization), 'user.delete', 'user', str(user_id), ulabel)
    notify_module_activity("使用者管理", "刪除帳號", actor.get("display_name") or actor["username"],
                            ulabel, "users.html")
    return {"ok": True}


@router.patch("/api/users/{user_id}/active")
def toggle_user_active(user_id: int, authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    conn = get_db()
    row = conn.execute("SELECT username, display_name, active FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "使用者不存在")
    if row["username"] == "jeff":
        conn.close()
        raise HTTPException(400, "不可停用超級管理員帳號")
    new_active = 0 if row["active"] else 1
    conn.execute("UPDATE users SET active=? WHERE id=?", (new_active, user_id))
    conn.commit()
    conn.close()
    ulabel = row["display_name"] or row["username"]
    _audit(_tok(authorization), 'user.active', 'user', str(user_id),
           f"{ulabel}（{'啟用' if new_active else '停用'}帳號）", {'active': bool(new_active)})
    notify_module_activity("使用者管理", "啟用帳號" if new_active else "停用帳號",
                            actor.get("display_name") or actor["username"], ulabel, "users.html")
    return {"ok": True, "active": bool(new_active)}


@router.get("/api/users/selectable")
def users_selectable(authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    rows = conn.execute(
        "SELECT id, username, display_name, role FROM users WHERE active=1 ORDER BY display_name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Unlock password ───────────────────────────────────────────────────────────

@router.post("/api/auth/verify-unlock")
def verify_unlock(body: VerifyUnlockIn, authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT unlock_password_hash FROM users WHERE id=?", (user['id'],)
        ).fetchone()
    finally:
        conn.close()
    stored = (row['unlock_password_hash'] or '') if row else ''
    if not stored:
        raise HTTPException(500, "尚未設定解鎖密碼，請至使用者管理設定")
    if not _verify_pw(body.password, stored):
        raise HTTPException(403, "解鎖密碼不正確")
    _audit(_tok(authorization), 'quotation.unlock', 'quotation', body.ref, body.ref,
           {'unlocked_by': user['display_name']})
    return {"ok": True}


@router.patch("/api/users/{user_id}/unlock-password")
def set_unlock_password(user_id: int, body: SetUnlockPasswordIn, authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    if len(body.unlock_password) < MIN_PASSWORD_LEN:
        raise HTTPException(400, f"解鎖密碼至少 {MIN_PASSWORD_LEN} 碼")
    if is_weak_password(body.unlock_password):
        raise HTTPException(400, "解鎖密碼過於簡單或為已知弱密碼，請改用更強的密碼")
    conn = get_db()
    try:
        row = conn.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(404, "使用者不存在")
        if row['role'] != 'superadmin':
            raise HTTPException(400, "僅超級管理員帳號可設定解鎖密碼")
        conn.execute(
            "UPDATE users SET unlock_password_hash=? WHERE id=?",
            (_hash_pw(body.unlock_password), user_id)
        )
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), 'user.set_unlock_password', 'user', str(user_id), str(user_id))
    notify_module_activity("使用者管理", "設定解鎖密碼", actor.get("display_name") or actor["username"],
                            str(user_id), "users.html")
    return {"ok": True}


# ── Daily-task admin-view unlock ──────────────────────────────────────────────

@router.post("/api/auth/verify-daily-task-unlock")
def verify_daily_task_unlock(body: VerifyDailyTaskUnlockIn, authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT daily_task_pw_hash FROM users WHERE id=?", (user['id'],)
        ).fetchone()
    finally:
        conn.close()
    stored = (row['daily_task_pw_hash'] or '') if row else ''
    if not stored:
        raise HTTPException(428, "尚未設定每日工作事項密碼，請至使用者管理設定")
    if not _verify_pw(body.password, stored):
        raise HTTPException(403, "密碼不正確")
    _audit(_tok(authorization), 'daily_task.admin_unlock', 'daily_task', 'admin_view', 'admin_view')
    return {"ok": True}


@router.patch("/api/users/{user_id}/daily-task-password")
def set_daily_task_password(user_id: int, body: SetDailyTaskPasswordIn,
                             authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    if len(body.daily_task_password) < MIN_PASSWORD_LEN:
        raise HTTPException(400, f"密碼至少 {MIN_PASSWORD_LEN} 碼")
    if is_weak_password(body.daily_task_password):
        raise HTTPException(400, "密碼過於簡單，請改用更強的密碼")
    conn = get_db()
    try:
        row = conn.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(404, "使用者不存在")
        if row['role'] != 'superadmin':
            raise HTTPException(400, "僅超級管理員帳號可設定每日工作事項密碼")
        conn.execute(
            "UPDATE users SET daily_task_pw_hash=? WHERE id=?",
            (_hash_pw(body.daily_task_password), user_id)
        )
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), 'user.set_daily_task_password', 'user', str(user_id), str(user_id))
    notify_module_activity("使用者管理", "設定每日工作事項密碼", actor.get("display_name") or actor["username"],
                            str(user_id), "users.html")
    return {"ok": True}

