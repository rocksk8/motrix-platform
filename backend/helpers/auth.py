"""Password hashing, session validation, weak-password detection."""
import hashlib
import hmac
import os
import json
import logging
import secrets
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
_SUPERADMIN_MODULES = [
    "dashboard", "quotation", "case_manage", "customer",
    "procurement", "inventory", "equipment", "finance", "reports", "cashier",
    "settings", "project_approve_eng", "project_approve_biz", "financial_view",
    "work_log", "daily_task",
    "env_guide", "netarch_guide", "switch_guide", "monitor_guide",
    "access_guide", "gateway_guide", "automation_guide",
    # 2026-09-14：原本沒有 key、只能靠角色寫死的項目——四個稽核／維運頁，
    # 以及網路架構規劃書的「檢視」（原本只有 netplan_edit）
    "netplan",
    "audit_log", "shipping_export_log", "module_versions", "selection_overview",
]

_LEGACY_WEAK_PASSWORDS = (
    "rock1125",
    "miac@60575481",
    "password",
    "123456",
    "admin",
    "motrix",
    "motrix123",
)

_CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "..", ".initial_admin_credentials.txt")
MIN_PASSWORD_LEN = 8

# Session tokens issued to the 'demo' showcase account are prefixed so
# auth_middleware can flip db.set_demo_mode(True) BEFORE looking the session up
# (the session itself only exists in the isolated demo DB, not the real one).
DEMO_TOKEN_PREFIX = "DEMO_"


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


def _write_initial_credentials(username: str, password: str) -> str:
    """Write one-time bootstrap credentials to the backend directory."""
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

def user_has_module(user: dict, key: str) -> bool:
    """`user["modules"]` 是 _require_user() 回傳的原始 JSON 字串（未解析），
    這裡統一解析比對——供「admin+ 或具備特定模組」這類判斷共用（2026-08-31
    財務/出納權限分工新增），取代散落在各檔案裡各自重寫一次 role 判斷式的
    寫法：`if user["role"] not in ("superadmin","admin") and not user_has_module(user,"cashier"): raise ...`"""
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
    return (user["role"] in ("superadmin", "admin", "sales")
            or user_has_module(user, "financial_view"))


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
    finally:
        conn.close()
    if not row:
        raise HTTPException(401, "Session 已過期，請重新登入")
    if require_superadmin and row["role"] != "superadmin":
        if module:
            user_mods = json.loads(row["modules"] or "[]")
            if module not in user_mods:
                raise HTTPException(403, "僅超級管理員或具授權模組的使用者可執行此操作")
        else:
            raise HTTPException(403, "僅超級管理員可執行此操作")
    return dict(row)


def _tok(auth: str) -> str:
    if auth and auth.startswith("Bearer "):
        return auth[7:]
    return auth or ""
