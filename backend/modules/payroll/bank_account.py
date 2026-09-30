# -*- coding: utf-8 -*-
"""員工收款帳號（`user_bank_accounts`，payroll v3）：驗證、遮蔽、讀寫、提供者 `payee.bank_profile`。

設計：D:\\開發測試檔\\expense-forms-design-ae.md 切片 1；A2 收款人（plan-expense-a2 §6 #12）。

## 遮蔽規則（個資：銀行帳號）
| 檢視者 | 帳號 |
|---|---|
| 本人 | 完整 |
| 超級管理員、財務（`finance`）、出納（`cashier`，付款需要） | 預設遮蔽（`****1234`）；明確要求 `reveal` 才回完整，**每次都寫稽核** |
| 其他所有人（簽核人、一般使用者、提供者查詢） | 遮蔽（銀行名稱＋戶名＋末四碼） |
遮蔽是**換成字串**，不是拿掉欄位（拿掉像「沒有帳號」，更容易被誤判）。
稽核 detail／日誌／錯誤訊息**永不含帳號全碼**（只記末四碼的前後變化與變動的欄位名稱）。

## 編輯權限
- 本人：只能改自己的（端點不收 user_id ⇒ 沒有 IDOR）。
- 改別人的：超級管理員或財務（`finance`）。出納只能看（付款用），不能改。
"""
import re
from datetime import datetime

from helpers.auth import user_has_module

_SPACE = re.compile(r"[\s\-]")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
NUMBER_MIN, NUMBER_MAX = 6, 16

FIELDS = ("bankCode", "bankName", "bankBranch", "accountName", "accountNumber")
_COLS = {"bankCode": "bank_code", "bankName": "bank_name", "bankBranch": "bank_branch",
         "accountName": "account_name", "accountNumber": "account_number"}


def _now():
    return datetime.now().isoformat(timespec="seconds")


class Invalid(ValueError):
    """輸入不合法；訊息給使用者看（不含帳號值）。"""


def clean_number(raw) -> str:
    """帳號：去空白與連字號後必須全是數字、6–16 碼。"""
    s = _SPACE.sub("", str(raw or ""))
    if not s:
        raise Invalid("請填寫帳號。")
    if not s.isdigit():
        raise Invalid("帳號只能是數字（可含空白或連字號）。")
    if not (NUMBER_MIN <= len(s) <= NUMBER_MAX):
        raise Invalid("帳號長度要 %d～%d 碼。" % (NUMBER_MIN, NUMBER_MAX))
    return s


def _text(raw, label, maxlen, required=False):
    s = str(raw or "").strip()
    if _CTRL.search(s):
        raise Invalid("%s含有不合法的字元。" % label)
    if required and not s:
        raise Invalid("請填寫%s。" % label)
    if len(s) > maxlen:
        raise Invalid("%s太長（最多 %d 字）。" % (label, maxlen))
    return s


def validate(body: dict) -> dict:
    """⇒ 正規化後的欄位（內部欄名 bank_code…）。不合法 ⇒ Invalid。"""
    code = _text(body.get("bankCode"), "銀行代碼", 3, required=True)
    if not (code.isdigit() and len(code) == 3):
        raise Invalid("銀行代碼是 3 位數字。")
    return {
        "bank_code": code,
        "bank_name": _text(body.get("bankName"), "銀行名稱", 40),
        "bank_branch": _text(body.get("bankBranch"), "分行", 40),
        "account_name": _text(body.get("accountName"), "戶名", 40, required=True),
        "account_number": clean_number(body.get("accountNumber")),
    }


def mask_number(number) -> str:
    n = str(number or "")
    return "" if not n else ("****" + n[-4:] if len(n) > 4 else "****")


def is_owner(viewer, username) -> bool:
    return bool(viewer) and viewer.get("username") == username


def may_see_full(viewer, username) -> bool:
    """這個人**有資格**看完整帳號（仍要明確 reveal 才回；本人直接回）。"""
    return bool(viewer) and (is_owner(viewer, username) or viewer.get("role") == "superadmin"
                             or user_has_module(viewer, "finance") or user_has_module(viewer, "cashier"))


def may_edit_others(viewer) -> bool:
    return bool(viewer) and (viewer.get("role") == "superadmin" or user_has_module(viewer, "finance"))


def may_list_users(viewer) -> bool:
    return may_edit_others(viewer) or (bool(viewer) and user_has_module(viewer, "cashier"))


def _row_out(r, *, full: bool) -> dict:
    return {"bankCode": r["bank_code"], "bankName": r["bank_name"], "bankBranch": r["bank_branch"], "accountName": r["account_name"],
            "accountNumber": r["account_number"] if full else "", "accountNumberMasked": mask_number(r["account_number"]),
            "last4": (r["account_number"] or "")[-4:], "masked": not full,
            "updatedAt": r["updated_at"], "updatedBy": r["updated_by"], "verifiedBy": r["verified_by"], "verifiedAt": r["verified_at"]}


def get_active(conn, user_id):
    return conn.execute("SELECT * FROM user_bank_accounts WHERE user_id=? AND active=1", (user_id,)).fetchone()


def get_active_by_username(conn, username):
    return conn.execute("SELECT * FROM user_bank_accounts WHERE username=? AND active=1", (username,)).fetchone()


def profile(conn, row, viewer, username, *, reveal=False) -> dict:
    """⇒ 給 API／提供者的 dict。本人直接完整；有資格者要 `reveal=True` 才完整；其餘遮蔽。`row` 為 None ⇒ status none。"""
    if row is None:
        return {"status": "none"}
    full = is_owner(viewer, username) or (reveal and may_see_full(viewer, username))
    out = _row_out(row, full=full)
    out["status"] = "ok"
    return out


def save(conn, user_id, username, fields: dict, actor_username) -> dict:
    """舊的有效列標 inactive、插入新的有效列（同一交易由呼叫端 commit）。⇒ {changed: [欄位名], before_last4, after_last4}。"""
    old = get_active(conn, user_id)
    changed = []
    if old is not None:
        for api_name, col in _COLS.items():
            if (old[col] or "") != fields[col]:
                changed.append(api_name)
        if not changed:
            return {"changed": [], "before_last4": (old["account_number"] or "")[-4:], "after_last4": fields["account_number"][-4:], "noop": True}
        conn.execute("UPDATE user_bank_accounts SET active=0, replaced_at=? WHERE id=?", (_now(), old["id"]))
    else:
        changed = list(FIELDS)
    now = _now()
    conn.execute("INSERT INTO user_bank_accounts (user_id, username, bank_code, bank_name, bank_branch, account_name, account_number, active,"
                 " created_by, created_at, updated_by, updated_at) VALUES (?,?,?,?,?,?,?,1,?,?,?,?)",
                 (user_id, username, fields["bank_code"], fields["bank_name"], fields["bank_branch"], fields["account_name"],
                  fields["account_number"], actor_username, now, actor_username, now))
    return {"changed": changed, "before_last4": (old["account_number"] or "")[-4:] if old is not None else "",
            "after_last4": fields["account_number"][-4:], "noop": False}


def history(conn, user_id):
    rows = conn.execute("SELECT * FROM user_bank_accounts WHERE user_id=? ORDER BY id DESC LIMIT 50", (user_id,)).fetchall()
    return [{"bankCode": r["bank_code"], "bankName": r["bank_name"], "accountName": r["account_name"], "last4": (r["account_number"] or "")[-4:],
             "active": bool(r["active"]), "createdBy": r["created_by"], "createdAt": r["created_at"], "replacedAt": r["replaced_at"]} for r in rows]


def snapshot(conn, username, viewer) -> dict:
    """單據送審時凍結用的收款資訊快照（之後使用者改帳號不影響已送審單據）。**快照只存遮蔽版＋雜湊指向**：
    付款需要完整帳號的人在付款時讀 `payee.bank_profile`（有資格者 reveal）；快照本身不含完整帳號，避免帳號散落在單據 JSON。"""
    p = profile(conn, get_active_by_username(conn, username), viewer, username, reveal=False)
    if p.get("status") != "ok":
        return {"status": "none"}
    return {"status": "ok", "bankCode": p["bankCode"], "bankName": p["bankName"], "bankBranch": p["bankBranch"],
            "accountName": p["accountName"], "last4": p["last4"], "frozenAt": _now()}


def payee_bank_profile(conn, username, viewer, reveal=False, audit_token=None, purpose=""):
    """提供者 `payee.bank_profile`（IP-BK1）：`(conn, username, viewer, reveal=False, audit_token=None, purpose="")` ⇒ dict。
    `status`: none（沒登錄）／ok。`masked`: True 時 `accountNumber` 為空、`accountNumberMasked` 有值。
    **要完整帳號必須同時 `reveal=True` 且帶 `audit_token`（呼叫端手上的登入 token）**：每次完整回傳都寫稽核
    `user.bank_account.reveal`（記誰、看誰、為什麼 `purpose`、末四碼；不記全碼）；沒帶 token ⇒ 照遮蔽回（`revealRefused`），
    不會「靜默給出全碼又沒留紀錄」。本人看自己的不需 reveal、不寫稽核。"""
    row = get_active_by_username(conn, username)
    want_full = bool(reveal) and not is_owner(viewer, username) and may_see_full(viewer, username)
    if want_full and not audit_token:
        out = profile(conn, row, viewer, username, reveal=False)
        out["revealRefused"] = "沒有稽核 token：不回完整帳號"
        return out
    out = profile(conn, row, viewer, username, reveal=reveal)
    if want_full and row is not None and not out.get("masked", True):
        audit_reveal(audit_token, username, row["account_number"][-4:], purpose)
    return out


def audit_reveal(token, username, last4, purpose=""):
    from helpers import _audit
    _audit(token, "user.bank_account.reveal", "user", username, username, {"last4": last4, "purpose": str(purpose or "")[:40]})
