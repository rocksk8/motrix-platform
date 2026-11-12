# -*- coding: utf-8 -*-
"""員工（使用者帳號）批次匯入的規劃邏輯（T85 匯入精靈；端點 `POST /api/users/import-rows` 在 routers/auth.py）。

只做「檔案列 → 計畫」的純運算與臨時密碼產生，不寫任何資料表；寫入用 routers/auth.py 的 `_insert_new_user`（與 `create_user` 同一支）。
規則（PM 裁示 2026-11-13）：
- 只新增：已存在的帳號一律略過（也不看大小寫），不更新任何既有帳號；
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

# 密碼字母表：去掉容易看錯的 0O1lI
_PW_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


def _txt(v, limit=MAX_TEXT):
    return (unicodedata.normalize("NFKC", str(v)).strip() if v is not None else "")[:limit]


def _fold(u):
    """帳號比對用：全形半形（NFKC）＋大小寫不分。"""
    return unicodedata.normalize("NFKC", str(u or "")).strip().casefold()


def norm_role(text):
    """⇒ (角色鍵 或 None, 是否認得)。空白 ⇒ ('viewer', True)。"""
    s = _txt(text).replace(" ", "").casefold()
    if not s:
        return "viewer", True
    k = _ROLE_WORDS.get(s)
    return (k, True) if k else (None, False)


def new_password(min_len: int) -> str:
    """臨時密碼：至少 max(14, 最短長度) 碼、四類字元都有、不是弱密碼；`secrets` 產生。"""
    n = max(14, int(min_len or 0))
    while True:
        pw = "".join(secrets.choice(_PW_ALPHABET) for _ in range(n))
        if (any(c.isupper() for c in pw) and any(c.islower() for c in pw) and any(c.isdigit() for c in pw)):
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
        exist_fold.setdefault(_fold(u), u)
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
        if not r["username"]:
            item.update(action="error", reason="帳號不可空白")
        elif re.search(r"\s", r["username"]) or len(r["username"]) > 64 or any(ord(c) < 32 for c in r["username"]):
            item.update(action="error", reason="帳號不可含空白、不可超過 64 字")
        elif _fold(r["username"]) in seen:
            item.update(action="error", reason="同一個檔案裡帳號「%s」出現多次，這一列未匯入" % r["username"])
        elif r["username"] in exist_exact:
            item.update(action="skip", reason="帳號已存在，沒有更動")
        elif _fold(r["username"]) in exist_fold:
            item.update(action="skip", reason="已有帳號「%s」（只差大小寫或全形半形），沒有建立" % exist_fold[_fold(r["username"])])
        elif not r["displayName"]:
            item.update(action="error", reason="姓名不可空白")
        elif not known:
            item.update(action="error", reason="不認得的角色「%s」（可填：業務、工程師、檢視者，或留白）" % r["role"])
        elif role in MANUAL_ROLES:
            item.update(action="manual", reason="此角色需手動建立（請最高管理者到帳號頁建立）")
        else:
            item.update(action="create")
        if r["username"]:
            seen.add(_fold(r["username"]))
        if item["action"] == "create":
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
