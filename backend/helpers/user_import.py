# -*- coding: utf-8 -*-
"""員工（使用者帳號）批次匯入的規劃邏輯（T85 匯入精靈；端點 `POST /api/users/import-rows` 在 routers/auth.py）。

只做「檔案列 → 計畫」的純運算與臨時密碼產生，不寫任何資料表；寫入用 routers/auth.py 的 `_insert_new_user`（與 `create_user` 同一支）。
規則（PM 裁示 2026-11-13）：
- 只新增：已存在的帳號一律略過（也不看大小寫），不更新任何既有帳號；
- 帳號（M1）：NFKC 正規化＋轉小寫後必須符合 `^[a-z0-9._-]{3,32}$`；含零寬、方向控制、控制字元一律拒絕；和既有帳號用同一套正規化比對
  （長得像的寫法不能繞過「既有帳號略過」）；建立時存的就是正規化後的值（預覽會寫「將建立為 xxx」）；
- 角色只允許業務／工程師／檢視者（空白＝檢視者）；最高管理者、管理員、財務屬高權限角色，必須由最高管理者到帳號頁一個一個建立 ⇒
  列在預覽「此角色需手動建立」，不建立；
- 檔案不收密碼（有密碼欄＝忽略並警告）；臨時密碼由伺服器在寫入時產生，只在該次回應出現，不進計畫雜湊、不進日誌、不進稽核；
- 模組勾選一律空（匯入後到權限頁設定）；部門以名稱對應，對不上＝警告並留空。
"""
import hashlib
import json
import re
import secrets
import unicodedata

IMPORT_MAX_ROWS = 300
MAX_TEXT = 100

#: 可由匯入建立的角色（鍵）與接受的寫法（中文名稱、英文鍵）；空白＝viewer
ALLOWED_ROLES = ("sales", "engineer", "viewer")
#: 高權限角色：認得、但不由匯入建立
MANUAL_ROLES = ("superadmin", "admin", "finance")
_ROLE_WORDS = {
    "sales": "sales", "業務": "sales", "業務員": "sales",
    "engineer": "engineer", "工程師": "engineer",
    "viewer": "viewer", "檢視者": "viewer", "唯讀": "viewer", "檢視": "viewer",
    "superadmin": "superadmin", "最高管理者": "superadmin", "超級管理員": "superadmin", "最高管理員": "superadmin",
    "admin": "admin", "管理員": "admin", "管理者": "admin",
    "finance": "finance", "財務": "finance", "財務角色": "finance",
}
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_USERNAME_OK = re.compile(r"^[a-z0-9._-]{3,32}$")
USERNAME_RULE = "帳號只能用英文字母、數字、點、底線、連字號（. _ -），長度 3～32 個字"

# 密碼字母表：去掉容易看錯的 0O1lI
_PW_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


def _txt(v, limit=MAX_TEXT):
    return (unicodedata.normalize("NFKC", str(v)).strip() if v is not None else "")[:limit]


def _invisible(ch):
    """零寬、方向控制、格式／控制字元、私用區等「看不見」的字元（unicode 類別 Cc／Cf／Co／Cs／Zl／Zp）。"""
    return unicodedata.category(ch) in ("Cc", "Cf", "Co", "Cs", "Zl", "Zp")


def _fold(u):
    """帳號比對用：全形半形（NFKC）＋大小寫不分＋去掉看不見的字元（新帳號與既有帳號用同一套，長得像的寫法不能繞過）。"""
    s = unicodedata.normalize("NFKC", str(u or ""))
    return "".join(ch for ch in s if not _invisible(ch)).strip().casefold()


def canon_username(u):
    """⇒ (正規化後的帳號, 問題訊息 或 None)。NFKC＋小寫；看不見的字元、空白、不在 `[a-z0-9._-]`、長度不在 3～32 都回問題訊息。"""
    raw = str(u or "")
    if any(_invisible(ch) for ch in raw):
        return "", "帳號裡有看不見的字元（零寬字元、方向控制字元或控制字元），請重新輸入"
    c = unicodedata.normalize("NFKC", raw).strip().casefold()
    if any(_invisible(ch) for ch in c):                       # NFKC 之後才冒出來的（相容字元展開）
        return "", "帳號裡有看不見的字元（零寬字元、方向控制字元或控制字元），請重新輸入"
    if not _USERNAME_OK.match(c):
        return "", USERNAME_RULE
    return c, None


def norm_role(text):
    """⇒ (角色鍵 或 None, 是否認得)。空白 ⇒ ('viewer', True)。"""
    s = _txt(text).replace(" ", "").casefold()
    if not s:
        return "viewer", True
    k = _ROLE_WORDS.get(s)
    return (k, True) if k else (None, False)


def new_password(min_len: int, problem=None) -> str:
    """臨時密碼：至少 max(14, 最短長度) 碼、含大寫、小寫、數字（字母表不含容易看錯的 0O1lI）；`secrets` 產生。
    `problem(pw)` ＝呼叫端傳入的密碼規則檢查（回 None 才算過；端點傳 `create_user` 同一支：最短長度＋弱密碼清單），不過就重產。
    注意：不含符號（臨時密碼要能口頭／手抄轉交，同仁第一次登入就必須改掉）；『不是弱密碼』靠 `problem`，不是靠這支自己判斷。"""
    n = max(14, int(min_len or 0))
    while True:
        pw = "".join(secrets.choice(_PW_ALPHABET) for _ in range(n))
        if (any(c.isupper() for c in pw) and any(c.islower() for c in pw) and any(c.isdigit() for c in pw)
                and (problem is None or problem(pw) is None)):
            return pw


def _norm_row(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {"row": raw.get("row"), "username": _txt(raw.get("username"), 200), "displayName": _txt(raw.get("displayName")),
            "role": _txt(raw.get("role"), 40), "email": _txt(raw.get("email"), 200), "phone": _txt(raw.get("phone"), 60),
            "department": _txt(raw.get("department"), 100), "hadPassword": raw.get("hadPassword") is True}


def plan_users_import(conn, rows: list) -> list:
    """每列 ⇒ {row, username, displayName, role, action: create|skip|manual|error, reason?, warnings[], departmentId?}。唯讀；預覽與寫入用同一份。"""
    exist = [r["username"] for r in conn.execute("SELECT username FROM users").fetchall()]
    exist_exact = set(exist)
    exist_fold = {}
    for u in exist:
        exist_fold.setdefault(_fold(u), u)               # 既有帳號也走同一套正規化（含去掉看不見的字元）
    deps = {}
    try:
        for r in conn.execute("SELECT id, name FROM departments").fetchall():
            deps.setdefault((r["name"] or "").strip(), []).append(r["id"])
    except Exception:                                      # noqa: BLE001 — 組織表讀不到只是沒有部門可對
        deps = {}
    seen, plan = set(), []
    for raw in rows:
        r = _norm_row(raw)
        item = {"row": r["row"], "username": r["username"], "displayName": r["displayName"], "in": r, "warnings": []}
        role, known = norm_role(r["role"])
        item["role"] = role
        if r["hadPassword"]:
            item["warnings"].append("檔案裡的密碼欄不會使用，系統會自己產生臨時密碼")
        canon, bad = canon_username(r["username"]) if r["username"] else ("", None)
        key = _fold(r["username"])
        if not r["username"]:
            item.update(action="error", reason="帳號不可空白")
        elif key in seen:
            item.update(action="error", reason="同一個檔案裡帳號「%s」出現多次，這一列未匯入" % r["username"])
        elif r["username"] in exist_exact:
            item.update(action="skip", reason="帳號已存在，沒有更動")
        elif key in exist_fold:
            item.update(action="skip", reason="已有帳號「%s」（只差大小寫、全形半形或看不見的字元），沒有建立" % exist_fold[key])
        elif bad:
            item.update(action="error", reason=bad)
        elif not r["displayName"]:
            item.update(action="error", reason="姓名不可空白")
        elif not known:
            item.update(action="error", reason="不認得的角色「%s」（可填：業務、工程師、檢視者，或留白）" % r["role"])
        elif role in MANUAL_ROLES:
            item.update(action="manual", reason="此角色需手動建立（請最高管理者到帳號頁建立）")
        else:
            item.update(action="create")
        if r["username"]:
            seen.add(key)
        if item["action"] == "create":
            item["username"] = canon                      # 存的就是正規化後的帳號
            if canon != r["username"]:
                item["warnings"].append("將建立為「%s」（英文字母一律轉小寫、全形字轉半形）" % canon)
            if r["email"] and not _EMAIL.match(r["email"]):
                item["warnings"].append("Email 格式看起來不對（%s）" % r["email"])
            if r["department"]:
                ids = deps.get(r["department"], [])
                if len(ids) == 1:
                    item["departmentId"] = ids[0]
                else:
                    item["warnings"].append("部門「%s」%s，帳號先不分部門" % (r["department"], "對不到" if not ids else "有多個同名"))
        plan.append(item)
    return plan


def plan_hash(plan: list) -> str:
    """預覽與寫入之間這份計畫有沒有變。不含任何密碼（密碼在寫入時才產生）。"""
    sig = [{"in": p["in"], "a": p["action"], "d": p.get("departmentId")} for p in plan]
    return hashlib.sha256(json.dumps(sig, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:32]


def plan_summary(plan: list) -> dict:
    count = lambda a: sum(1 for p in plan if p["action"] == a)                # noqa: E731
    return {"created": count("create"), "skipped": [{"row": p["row"], "username": p["username"], "reason": p["reason"]} for p in plan if p["action"] == "skip"],
            "manual": [{"row": p["row"], "username": p["username"], "displayName": p["displayName"], "reason": p["reason"]} for p in plan if p["action"] == "manual"],
            "failed": count("error"), "errors": ["第 %s 行：%s" % (p["row"], p["reason"]) for p in plan if p["action"] == "error"],
            "warnings": [{"row": p["row"], "username": p["username"], "message": w} for p in plan if p["action"] in ("create", "skip", "manual") for w in p["warnings"]],
            "willCreate": [{"row": p["row"], "username": p["username"], "displayName": p["displayName"], "role": p["role"]} for p in plan if p["action"] == "create"][:200],
            "planHash": plan_hash(plan)}
