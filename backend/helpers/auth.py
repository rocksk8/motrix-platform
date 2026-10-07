"""Password hashing, session validation, weak-password detection."""

#: G1（MODULE-GUIDE §2）：底線開頭但屬於 L1 公開介面的名稱——改簽章或刪除照介面變更升版。
#: L1 以外只可以用這裡列出的底線名稱（守門：test_l1_interface_snapshot::test_l2_uses_only_declared_l1_underscore_names）。
__l1_public__ = (
    "_CREDENTIALS_FILE",
    "_LEGACY_WEAK_PASSWORDS",
    "_SUPERADMIN_MODULES",
    "_hash",
    "_hash_pw",
    "_require_user",
    "_tok",
    "_verify_pw",
    "_write_initial_credentials",
)

import hashlib
import hmac
import os
import json
import logging
from datetime import datetime

from fastapi import HTTPException

from db import get_db

logger = logging.getLogger(__name__)

# 首次安裝時建立的管理員帳號拿到的模組清單（helpers/startup.py）。
#
# 2026-09-13（模組權限稽核）：這份清單長期與 `users.html` 的 superadmin 樣板不同步
# ——缺 `case_manage`／`reports`／`cashier`／`work_log`／`daily_task` 與七個選型導覽，
# 卻多一個全系統沒有任何地方會讀的死 key `sales`。superadmin 在側欄與後端幾乎都走
# 角色直通，所以看不出症狀，但「第一個管理員帳號的模組清單」本來就該是那份樣板的
# 鏡像，不同步只是等著誤導下一個人。兩邊要一起改。
# 2026-09-24（B7）：清單本身移到 `helpers/module_registry.py`（唯一來源），這裡只留名稱
# 給既有呼叫端；值與順序不變（test_module_registry 的 golden 題守著）。
from helpers.module_registry import SUPERADMIN_DEFAULT as _SUPERADMIN_DEFAULT
_SUPERADMIN_MODULES = list(_SUPERADMIN_DEFAULT)

_LEGACY_WEAK_PASSWORDS = (
    "rock1125",
    "miac@60575481",
    "password",
    "123456",
    "admin",
    "motrix",
    "motrix123",
)

from core import paths as _paths
_CREDENTIALS_FILE = _paths.INITIAL_ADMIN_CREDENTIALS
MIN_PASSWORD_LEN = 8

# Session tokens issued to the 'demo' showcase account are prefixed so
# auth_middleware can flip db.set_demo_mode(True) BEFORE looking the session up
# (the session itself only exists in the isolated demo DB, not the real one).
DEMO_TOKEN_PREFIX = "DEMO_"

# ── Passkey / WebAuthn 總開關（2026-09-16，使用者裁示「先暫緩不使用」）─────────
#
# **這是暫停，不是移除**：程式碼、資料表、既有憑證列全部原樣保留。要恢復功能
# 只要把這一個值改回 True，不必改動其他任何地方——所有進入點都讀這個常數：
#
#   後端  routers/auth.py    8 支 /api/auth/webauthn/* 端點 → 停用時 404
#         routers/system.py  /api/settings/webauthn-config（GET/PATCH）→ 404
#                            /api/system/webauthn-config-status → enabled:false
#   前端  login.html                  「或使用 Passkey 登入」按鈕
#         change-password.html        整張「Passkey 設備」卡片
#         company-profile-settings.html  整張「Passkey / WebAuthn 網域設定」卡片
#         （三處都吃 /api/system/webauthn-config-status，不必各自寫死）
#   測試  tests/test_webauthn_*.py、tests/test_e2e_passkey_*.py 整檔 skipif，
#         恢復時測試自動跟著回來（不是刪掉，也不是永久 xfail）
#
# 端點回 **404 而不是 403/503**：503「尚未設定」會讓前端顯示「請聯繫管理員設定」
# 那句話，引導使用者去要一個現在不該被打開的功能；404 則是「這裡沒有這支端點」，
# 與功能未上線時的外觀一致。
#
# ⚠️ 停用期間，原本用 Passkey 登入的人只能改用密碼——恢復前請確認他們知道自己的
# 密碼。已綁定的憑證列**不會被刪**，但若停用期間變更過 WebAuthn RP ID，
# 那些憑證在恢復後仍然是失效的（RP ID 綁定在瀏覽器端，見 db.py::_m074）。
PASSKEY_ENABLED = False


# ── Hashing ───────────────────────────────────────────────────────────────────

def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _hash_pw(password: str) -> str:
    salt = os.urandom(16)
    dk   = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 260_000)
    return salt.hex() + ":" + dk.hex()


def _verify_pw(password: str, stored: str) -> bool:
    if ":" not in stored:
        return hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(), stored)
    salt_hex, dk_hex = stored.split(":", 1)
    salt = bytes.fromhex(salt_hex)
    dk   = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 260_000)
    return hmac.compare_digest(dk.hex(), dk_hex)


# ── Weak-password policy ──────────────────────────────────────────────────────

def is_weak_password(password: str) -> bool:
    if not password or len(password) < MIN_PASSWORD_LEN:
        return True
    low = password.lower().strip()
    if low in {p.lower() for p in _LEGACY_WEAK_PASSWORDS}:
        return True
    if low in {"password1", "passw0rd", "admin123", "qwerty123"}:
        return True
    return False


def _write_initial_credentials(username: str, password: str, path: str = None) -> str:
    """Write one-time bootstrap credentials to the backend directory.

    `path` defaults to `_CREDENTIALS_FILE`（既有 jeff 呼叫端零改動）。
    ⚠️ `IA2`：demo 帳號的隨機密碼**不可以**也寫進 `_CREDENTIALS_FILE`——
    `init_default_admin()` 與 `init_demo_account()` 在全新安裝的同一次
    啟動裡都會跑，若共用同一個檔案，後跑的那個會把先跑的那個直接覆蓋掉
    （這支是 `"w"` 覆寫，不是附加），jeff 的臨時密碼就再也拿不回來了。
    """
    if path is None:
        path = _CREDENTIALS_FILE
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                "MOTRIX ERP — 首次安裝管理員帳號（請登入後立即修改密碼，並刪除此檔）\n"
                f"建立時間: {datetime.now().isoformat()}\n"
                f"帳號: {username}\n"
                f"臨時密碼: {password}\n"
                "注意: 此檔僅出現在本機 backend 目錄，請勿分享或備份到公開位置。\n"
            )
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
    except Exception as e:
        logger.warning("無法寫入初始憑證檔: %s", e)
    return path


# ── Session helpers ───────────────────────────────────────────────────────────

#: 2026-10-05（第42班，使用者裁示）：財務／出納能力只屬於「財務」角色與 superadmin。
#: 這三個模組鍵（出納、財務、財務金額可視）不再由 `users.modules` 的勾選決定——
#: `user_has_module(user, <這三個鍵>)` 改成**由角色推導**；既有 admin／sales 帳號 DB 裡的勾選
#: 原封不動（惰性，不刪，回滾即還原），只是程式不再認。
FINANCE_ROLE = "finance"
FINANCE_ROLES = ("superadmin", FINANCE_ROLE)
FINANCE_MODULE_KEYS = ("cashier", "finance", "financial_view")
VALID_ROLES = ("superadmin", "admin", "sales", "engineer", "viewer", FINANCE_ROLE)


# ── R2 第1步 D5：財務三鍵改讀生效權限（影子模式；設計 docs/platform/plans/R2-STEP1-EQUIV-ROLLBACK-T45.md §10.2）──────────
#: `system_settings` 旗標值：缺／其他＝`off`（舊規則，只看基礎類別）；`shadow`＝回傳舊規則、同時算新規則、不同時寫限速稽核；`on`＝回傳新規則（本班不開，需使用者核准）。
FINANCE_FLAG_KEY = "finance_via_effective"
_FIN_MODE_TTL = 15.0           # 旗標讀取快取（秒）：每 15 秒（每程序）最多查一次 DB，其餘呼叫只讀記憶體；改旗標最多 15 秒後生效（測試用 reset_finance_mode_cache）
#: ⚠ 切 `on` 的前置條件：`on` 模式每次判斷都查 DB（不快取，扣項要立即生效）；一次請求會呼叫多次 ⇒ 切 `on` 前須先加「每請求備忘」或 ≤10 秒 TTL（已列入 core CHANGELOG）。
_FIN_GRANT_TTL = 10.0          # 影子模式下每人的「角色給的財務鍵／扣項」快取（秒）；`on` 模式不快取（扣項要立即生效）
_FIN_ALERT_SECONDS = 3600      # 同一人同一鍵的影子差異告警：每小時至多 1 筆
_fin_mode = {"at": -1e9, "mode": "off"}
_fin_grants = {}               # user_id -> (monotonic, granted_keys, subtract_keys)
_fin_alerted = {}              # (user_id, key) -> monotonic
_fin_threads = []              # 影子稽核的背景執行緒（測試用 _join_shadow_threads 等它們寫完）


def reset_finance_mode_cache() -> None:
    """測試與維運用：丟掉旗標與影子快取，下一次呼叫重讀。"""
    _fin_mode.update(at=-1e9, mode="off")
    _fin_grants.clear()
    _fin_alerted.clear()
    del _fin_threads[:]


def _join_shadow_threads() -> None:
    for t in list(_fin_threads):
        t.join(5)
    del _fin_threads[:]


def _finance_mode() -> str:
    """旗標值（`off`／`shadow`／`on`）。讀取失敗 ⇒ **沿用上一次讀到的值**（從沒讀到過才是 `off`），3 秒後重試——
    避免 `on` 時資料庫一時讀不到就悄悄退回舊規則（扣項失效＝多給權限）。"""
    import time
    now = time.monotonic()
    if now - _fin_mode["at"] < _FIN_MODE_TTL:
        return _fin_mode["mode"]
    try:
        c = get_db()
        try:
            row = c.execute("SELECT value_json FROM system_settings WHERE key=?", (FINANCE_FLAG_KEY,)).fetchone()
        finally:
            c.close()
        v = json.loads(row[0]) if row else "off"
        _fin_mode.update(at=now, mode=v if v in ("shadow", "on") else "off")
    except Exception:                                   # noqa: BLE001  讀不到旗標＝沿用最後一次的值，稍後重試
        logger.warning("finance flag read failed; keeping last-known-good mode %s", _fin_mode["mode"])
        _fin_mode["at"] = now - _FIN_MODE_TTL + 3.0
    return _fin_mode["mode"]


def _finance_grants(user_id, cache: bool):
    """某人「已啟用職責角色給的財務鍵」與「財務鍵扣項」。表不存在（migration 未跑）⇒ 空。"""
    import time
    now = time.monotonic()
    hit = _fin_grants.get(user_id) if cache else None
    if hit and now - hit[0] < _FIN_GRANT_TTL:
        return hit[1], hit[2]
    granted, subs = set(), set()
    c = get_db()
    try:
        try:
            for (perms,) in c.execute("SELECT r.permissions FROM user_duty_roles b JOIN duty_roles r ON r.id=b.role_id"
                                      " WHERE b.user_id=? AND r.active=1", (user_id,)).fetchall():
                try:
                    granted |= {k for k in json.loads(perms or "[]") if k in FINANCE_MODULE_KEYS}
                except (TypeError, ValueError):
                    pass
            subs = {r[0] for r in c.execute("SELECT perm_key FROM user_perm_subtracts WHERE user_id=?", (user_id,)).fetchall()
                    if r[0] in FINANCE_MODULE_KEYS}
        except Exception:                               # noqa: BLE001  表不存在等
            granted, subs = set(), set()
    finally:
        c.close()
    if cache:
        _fin_grants[user_id] = (now, granted, subs)
    return granted, subs


def finance_effective_keys(user: dict, cache: bool = False) -> frozenset:
    """財務三鍵的「生效」集合（新規則）：superadmin ⇒ 三鍵全有；其餘 ＝（基礎類別 `finance` 隱含三鍵 ∪ 已啟用職責角色的財務鍵）− 個人扣項。
    **原始勾選 `users.modules` 的財務鍵不計**（第42班：admin／sales 的惰性勾選不生效）。沒有 `id` 的 dict ⇒ 只看基礎類別。"""
    role = (user or {}).get("role")
    if role == "superadmin":
        return frozenset(FINANCE_MODULE_KEYS)
    keys = set(FINANCE_MODULE_KEYS) if role == FINANCE_ROLE else set()
    uid = (user or {}).get("id")
    if uid is not None:
        granted, subs = _finance_grants(uid, cache)
        keys = (keys | granted) - subs
    return frozenset(keys)


def _finance_base_has(user: dict, key: str) -> bool:
    """只看基礎類別的財務鍵（不查庫）：新規則算不出來時，與舊規則取較嚴者（AND）——不因錯誤多給。"""
    role = (user or {}).get("role")
    return role == "superadmin" or (role == FINANCE_ROLE and key in FINANCE_MODULE_KEYS)


def _finance_shadow_report(user: dict, key: str, old: bool, new: bool) -> None:
    import time
    k = ((user or {}).get("id"), key)
    now = time.monotonic()
    if now - _fin_alerted.get(k, -1e9) < _FIN_ALERT_SECONDS:
        return
    _fin_alerted[k] = now
    logger.warning("finance shadow diff: user=%s key=%s old=%s new=%s", k[0], key, old, new)
    try:                                                # 權限判斷路徑內不同步寫庫：丟背景執行緒（帶 demo 脈絡）；寫不進去不可影響判斷
        import db as _db
        from helpers.audit import _audit
        args = ("", "permission.finance_shadow_diff", "user", str((user or {}).get("id") or ""), (user or {}).get("username") or "",
                {"key": key, "old": old, "new": new, "role": (user or {}).get("role")})
        _fin_threads[:] = [t for t in _fin_threads if t.is_alive()][-20:]
        _fin_threads.append(_db.spawn_bg_thread(_audit, args))
    except Exception:                                   # noqa: BLE001
        pass


def _finance_cap(user: dict, key: str) -> bool:
    """財務三鍵單一縫。`off`＝舊規則；`shadow`＝回傳舊規則（新規則不同時寫限速稽核）；`on`＝新規則。新規則算不出來⇒ 一律退回舊規則（不因此多給或少給）。"""
    old = (user or {}).get("role") in FINANCE_ROLES
    mode = _finance_mode()
    if mode == "off":
        return old
    try:
        new = key in finance_effective_keys(user, cache=(mode == "shadow"))
    except Exception:                                   # noqa: BLE001
        logger.exception("finance_effective_keys failed; falling back to the stricter of old/new")
        return old and _finance_base_has(user, key)
    if mode == "shadow":
        if new != old:
            _finance_shadow_report(user, key, old, new)
        return old
    return new


def finance_duty_person(user: dict) -> bool:
    """「財務角色（非 superadmin）」這個寫死 `role == "finance"` 的判斷點改走這一支（D5 附2：只改含 finance 字面值的點）。
    `off`／`shadow`：`role == "finance"`；`on`：生效權限含 `finance` 鍵的非 superadmin。"""
    old = (user or {}).get("role") == FINANCE_ROLE
    mode = _finance_mode()
    if mode == "off":
        return old
    try:
        new = (user or {}).get("role") != "superadmin" and "finance" in finance_effective_keys(user, cache=(mode == "shadow"))
    except Exception:                                   # noqa: BLE001
        return old and _finance_base_has(user, "finance")
    if mode == "shadow":
        if new != old:
            _finance_shadow_report(user, "finance_duty_person", old, new)
        return old
    return new


def has_finance_access(user: dict) -> bool:
    """財務金額可見／財務操作：只有 superadmin 與「財務」角色（不看 `modules` 勾選、不看 admin／sales）。
    **superadmin 不變式（2026-10-03）**：本函式必含 superadmin 直通（守門：test_finance_role 靜態題）。

    R2 第1步 D5（2026-10-07）：旗標 `finance_via_effective`＝`off`（預設）時就是下面這一行；`shadow` 回傳同一個舊結果並比對新規則；
    `on`（本班不開）才改看生效權限。見 `finance_effective_keys`。"""
    if _finance_mode() == "off":
        return (user or {}).get("role") in FINANCE_ROLES
    return _finance_cap(user, "finance")


def has_cashier_access(user: dict) -> bool:
    """出納（登錄付款／標記已匯款／銀行對帳）：與財務同一條規則（使用者 2026-10-05 裁示合併）；D5 之後可個別被扣（旗標 `on` 時）。"""
    if _finance_mode() == "off":
        return has_finance_access(user)
    return _finance_cap(user, "cashier")


def finance_usernames(conn=None) -> list:
    """在職的「財務」角色＋superadmin 帳號（依 id）。付款／匯款／出納類通知的收件人來源
    （取代各檔自己掃 `users.modules` 找 `cashier` 的寫法）。要信箱＋退訂判斷用
    `helpers.email_notify.finance_recipient_emails(event_key)`。"""
    own = conn is None
    c = conn or get_db()
    try:
        return [r["username"] for r in c.execute(
            "SELECT username FROM users WHERE active=1 AND role IN ('finance','superadmin') ORDER BY id")]
    finally:
        if own:
            c.close()


def effective_modules(role: str, modules, user_id=None, conn=None) -> list:
    """給前端／選單用的「有效模組清單」：財務三鍵由角色決定（財務角色與 superadmin 補上、其他角色一律拿掉）；
    其餘鍵照原樣。`modules` 可為 list 或 JSON 字串。DB 內的原始勾選不動。

    職責角色化 R1（單一縫，DUTY-ROLES-DESIGN §2.2）：給 `user_id` 時，先把該人的職責角色與個人扣項套到原始勾選上
    （`helpers.duty_roles.resolve_raw_modules`；沒有綁定也沒有扣項 ⇒ 原樣，與 R1 之前逐字相同），再套下面的財務規則。
    **superadmin 不經過角色／扣項**（R1 維持原狀，資料不可能降低它）。`conn` 省略時自行開關連線。"""
    if isinstance(modules, str):
        try:
            modules = json.loads(modules or "[]")
        except Exception:
            modules = []
    if user_id is not None and role != "superadmin":
        from helpers import duty_roles as _dr
        if conn is not None:
            modules = _dr.resolve_raw_modules(conn, user_id, modules)
        else:
            _c = get_db()
            try:
                modules = _dr.resolve_raw_modules(_c, user_id, modules)
            finally:
                _c.close()
    mods = [m for m in (modules or []) if m not in FINANCE_MODULE_KEYS]
    if role in FINANCE_ROLES:
        mods += [k for k in FINANCE_MODULE_KEYS]
    return mods


def user_has_module(user: dict, key: str) -> bool:
    """`user["modules"]` 是 _require_user() 回傳的原始 JSON 字串（未解析），
    這裡統一解析比對——供「admin+ 或具備特定模組」這類判斷共用（2026-08-31
    財務/出納權限分工新增），取代散落在各檔案裡各自重寫一次 role 判斷式的
    寫法：`if user["role"] not in ("superadmin","admin") and not user_has_module(user,"cashier"): raise ...`

    2026-10-05：`FINANCE_MODULE_KEYS`（cashier／finance／financial_view）改由角色推導（見上），不看勾選。"""
    if (user or {}).get("role") == "superadmin":          # R2 第1步 D4（選項 B）：守門層對 superadmin 明確「全部鍵」；`user["modules"]`／`effective_modules` 不動
        return True
    if key in FINANCE_MODULE_KEYS:
        return _finance_cap(user, key) if _finance_mode() != "off" else has_finance_access(user)
    try:
        return key in json.loads(user.get("modules") or "[]")
    except Exception:
        return False


def require_any_module(user: dict, keys, label: str) -> None:
    """模組層級的存取檢查：**只有 superadmin 直通**，其餘一律必須持有 `keys`
    其中一個——包含 admin。

    2026-09-14 使用者裁示：「管理者一樣依據有開權限的內容去顯示，沒開的就不顯示，
    包含模組名稱。超級管理者預設全開，使用者部分看模組內容去檢核，未開啟的直接
    不顯示」。在此之前 admin 跟 superadmin 一樣直通所有模組檢查，結果是**沒有人
    發現既有 admin 帳號的模組清單早就過時了**——2026-08／09 陸續新增的模組
    （監控／門禁／閘道器／自動化選型導覽、出納、網路架構規劃書）加進了角色樣板，
    但既有帳號從來沒有回填，只是因為 admin 直通所以完全看不出來。
    DB v84 已把那批帳號補到 admin 角色樣板，取消直通才不會讓人憑空少掉功能。

    2026-09-13（模組權限稽核第二輪，使用者裁示「逐一補後端檢查」）：在此之前
    35 個可授權模組裡有 16 個**後端完全沒有讀**，等於只是側欄的顯示開關——
    勾掉只是看不到入口，手打網址與直接打 API 完全不受影響。

    `keys` 收多個值是因為同一批資料常被好幾個模組的頁面共用（實測結果，見
    MODULE-AUDIT-2026-09-13.md §3.8 的消費者對照表）：例如 `/api/parts` 同時被
    料號主檔（`procurement`）與案件管理的叫料（`case_manage`）呼叫，只認一個
    模組會把另一邊打死。規則是「該 API 的所有消費頁面所屬模組的聯集」——比
    現況（誰登入都能打）嚴格，又不會擋掉任何一條既有的使用路徑。

    ⚠️ **最危險的失敗模式不是「該擋沒擋」，是「擋錯人」**（MODULE-AUDIT §5）：
    某模組的頁面呼叫到一支不接受該模組的 API，使用者看到一片 403，而後端測試
    全綠——因為**測試多半用 admin 帳號，而 admin 以前直通**。這次取消直通之後
    那層遮蔽消失了，`test_module_keys_consistency_2026_09_13.py` 的第 ⑦ 題
    （側欄承諾的模組必須打得開該頁的 API）才真正有意義。
    """
    if user["role"] == "superadmin":
        return
    if any(user_has_module(user, k) for k in keys):
        return
    raise HTTPException(403, f"權限不足：需要「{label}」模組")


def can_see_financial(user: dict) -> bool:
    """能不能看到案件層級的財務金額（成本、毛利、應收應付總覽）。

    2026-09-13（模組權限稽核第二輪）：`financial_view` 在此之前**只是前端的顯示
    偏好**——`case-management.js::canSeeFinancial()` 拿它藏 KPI 金額、財務分頁與
    額外支出分頁，但後端照樣把金額回給任何打得到那支 API 的人。使用者裁示
    「viewer／engineer 不該看到」，所以把同一條規則搬到後端成為真的權限。

    規則與前端逐字相同（`superadmin`／`admin`／`sales` 三種角色，或持有
    `financial_view` 模組），兩邊不一致的話使用者會看到「畫面有欄位、值卻是錯誤」
    這種更難查的狀態。

    ⚠️ 目前施加在**案件財務總覽**那幾支（成本精算、應收應付總覽、銷售訂單清單）。
    額外支出與三種憑證流（承攬商付款／開票／請款）仍是角色＋簽核流程把關——那些
    端點上有非管理員的簽核人，直接套這條規則會把簽核人擋在門外，要動得先理清
    「簽核人是否一定看得到金額」，見 MODULE-AUDIT-2026-09-13.md §4。
    """
    # 2026-10-05（第42班，使用者裁示）：只剩 superadmin 與「財務」角色；admin／sales 直通與 financial_view 勾選都拿掉。
    if _finance_mode() == "off":
        return has_finance_access(user)
    return _finance_cap(user, "financial_view")


def _require_user(authorization: str, require_superadmin: bool = False, module: str = None) -> dict:
    """Validate session and check role/module permissions.

    module: if provided alongside require_superadmin=True, superadmin OR users
            with that module key in their modules list are permitted.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "未登入")
    token = authorization[7:]
    conn  = get_db()
    now   = datetime.now().isoformat()
    try:
        row = conn.execute("""
            SELECT u.id, u.username, u.display_name, u.role, u.active, u.modules
            FROM sessions s JOIN users u ON s.user_id = u.id
            WHERE s.token=? AND u.active=1
              AND (s.expires_at IS NULL OR s.expires_at > ?)
        """, (token, now)).fetchone()
        if row and row["role"] != "superadmin":
            # 職責角色化 R1：有綁定／扣項的人，`user["modules"]` 改成套用後的原始勾選（沒有的人原樣，物件都不換）
            from helpers import duty_roles as _dr
            try:
                _raw = json.loads(row["modules"] or "[]")
            except Exception:
                _raw = None
            if isinstance(_raw, list):
                _res = _dr.resolve_raw_modules(conn, row["id"], _raw)
                if _res is not _raw:
                    row = dict(row)
                    row["modules"] = json.dumps(_res, ensure_ascii=False)
    finally:
        conn.close()
    if not row:
        raise HTTPException(401, "Session 已過期，請重新登入")
    if require_superadmin and row["role"] != "superadmin":
        if module:
            user_mods = effective_modules(row["role"], row["modules"], user_id=row["id"])
            if module not in user_mods:
                raise HTTPException(403, "僅超級管理員或具授權模組的使用者可執行此操作")
        else:
            raise HTTPException(403, "僅超級管理員可執行此操作")
    return dict(row)


def _tok(auth: str) -> str:
    if auth and auth.startswith("Bearer "):
        return auth[7:]
    return auth or ""
