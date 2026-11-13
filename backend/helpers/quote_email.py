# -*- coding: utf-8 -*-
"""報價用公司信箱（2026-11-13，使用者需求）：有些人用私人信箱註冊帳號，但報價單要用公司信箱。

[單位] helper:quote_email    [層] L1    [穩定度] 實驗
[公開介面] valid, domain_hint, resolve, resolve_for_user_id, resolve_for_row, company_external_email, enforce_sales_email, reply_to_for_quote, PROFILE_KEY
[契約題] tests/test_quote_email_2026_11_13.py
[不變式] ①**只影響「填入」那一刻**：報價單的業務員資料在填表時就快照進 quotations.data_json，已開出的單不被追溯改（本模組不讀寫報價單內容）。
    ②格式不合法的信箱視為沒填（不會被當成有效值帶進單據）；網域提醒只是提示，不阻擋儲存（domain_hint 只回文字）。
    ③寄信只加 Reply-To，SMTP 寄件者（From）不變（寄件帳號是系統層設定，不跟人走）。

取值優先順序（`resolve`）：①該使用者的「報價用公司信箱」`users.quote_email`（只有最高管理者能設）
②公司層「公司對外信箱」`company_profile.external_email`
③個人信箱 `users.email`（沿用現況；此時畫面提示「尚未設定公司信箱」）
都沒有 ⇒ 空字串。
"""
import re

PROFILE_KEY = "external_email"

_EMAIL_RE = re.compile(r"^[^@\s,;<>()\[\]\\\"]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+$")

#: 一看就是私人信箱的網域（只用來提醒，不阻擋）
_PERSONAL_DOMAINS = {
    "gmail.com", "yahoo.com", "yahoo.com.tw", "hotmail.com", "outlook.com", "live.com", "icloud.com",
    "msn.com", "me.com", "qq.com", "163.com", "proton.me", "protonmail.com", "pchome.com.tw", "seed.net.tw",
}


def valid(email) -> bool:
    """合法信箱：只接受 ASCII 可列印字元（\x21-\x7e）。全形空白、零寬字元、中文字等一律不合（避免看起來像信箱、實際寄不到或夾帶不可見字元）。"""
    e = str(email or "").strip()
    return bool(e) and len(e) <= 254 and all(0x21 <= ord(c) <= 0x7e for c in e) and bool(_EMAIL_RE.match(e))


def _domain(email) -> str:
    return str(email or "").strip().lower().rpartition("@")[2]


def domain_hint(email, company_email="") -> str:
    """只回提醒文字（空字串＝沒有疑慮）；呼叫端**不可**因此拒絕儲存。"""
    e = str(email or "").strip()
    if not e or not valid(e):
        return ""
    d = _domain(e)
    cd = _domain(company_email) if valid(company_email) else ""
    if cd and d == cd:
        return ""
    if d in _PERSONAL_DOMAINS:
        return "這看起來是私人信箱的網域（%s），報價單上通常要用公司信箱，請確認。" % d
    if cd and d != cd:
        return "這個信箱的網域（%s）和公司對外信箱的網域（%s）不同，請確認填寫無誤。" % (d, cd)
    return ""


def _clean(v) -> str:
    v = str(v or "").strip()
    return v if valid(v) else ""


def resolve(user_quote_email, company_external_email, personal_email) -> dict:
    """純函式：三層取第一個合法的。回 {email, source}；source＝user｜company｜personal｜none。"""
    for src, v in (("user", user_quote_email), ("company", company_external_email), ("personal", personal_email)):
        c = _clean(v)
        if c:
            return {"email": c, "source": src}
    return {"email": "", "source": "none"}


def company_external_email() -> str:
    try:
        from helpers.settings import _get_setting
        prof = _get_setting("company_profile", {}) or {}
        return _clean(prof.get(PROFILE_KEY))
    except Exception:  # noqa: BLE001 — 設定讀不到不擋報價流程，當沒設
        return ""


def resolve_for_user_id(user_id) -> dict:
    from db import get_db
    conn = get_db()
    try:
        row = conn.execute("SELECT email, quote_email FROM users WHERE id=?", (int(user_id),)).fetchone()
    except Exception:  # noqa: BLE001
        row = None
    finally:
        conn.close()
    if not row:
        return {"email": "", "source": "none"}
    return resolve(row["quote_email"], company_external_email(), row["email"])


def resolve_for_row(row) -> dict:
    """已經查出 users 列（要有 email、quote_email 欄）時用，省一次查詢；公司信箱每次呼叫讀一次設定。"""
    return resolve(row["quote_email"], company_external_email(), row["email"])


def reply_to_for_quote(quote_no) -> str:
    """報價單相關通知信的 Reply-To：用該單開單當下快照的業務員信箱（已是三層解析後的值）；沒有或不合法 ⇒ 空字串（不加 Reply-To）。"""
    try:
        import json
        from db import get_db
        from helpers.case_access import case_data_json     # L1 讀 quotations 只准經 case_access（DEPENDENCY-MAP §3.2）
        conn = get_db()
        try:
            raw = case_data_json(conn, str(quote_no))
        finally:
            conn.close()
        if raw is None:
            return ""
        return _clean((json.loads(raw or "{}")).get("salesEmail"))
    except Exception:  # noqa: BLE001
        return ""


def enforce_sales_email(conn, q: dict, old_data=None) -> None:
    """儲存報價單時，在伺服器端驗證 `salesEmail`（Reply-To 與 PDF 都讀這個快照，不能信任客戶端寫入）。
    規則：①和資料庫現值相同（`old_data` 有值且沒改）⇒ 不動，舊單維持原樣；②否則必須等於 `salesPersonUsername` 這個人三層解析（報價用信箱／公司對外信箱／個人信箱）
    的其中一個合法值，不符合就用解析結果覆寫（解析不出來＝空字串）。只改 `q["salesEmail"]`，不丟例外（驗證出錯不擋儲存）。"""
    try:
        username = str(q.get("salesPersonUsername") or "").strip()
        incoming = str(q.get("salesEmail") or "").strip()
        if old_data is not None:
            # 信箱沒改、而且業務員也沒換 ⇒ 舊單維持原樣；換了業務員但信箱還是舊的 ⇒ 要重新驗證（舊信箱可能是前一位業務員的）
            if (incoming == str((old_data or {}).get("salesEmail") or "").strip()
                    and username == str((old_data or {}).get("salesPersonUsername") or "").strip()):
                return
        elif "salesEmail" not in q and not username:
            return
        row = None
        if username:
            row = conn.execute("SELECT email, quote_email FROM users WHERE username=?", (username,)).fetchone()
        if not row:
            q["salesEmail"] = ""
            return
        allowed = {_clean(row["quote_email"]).lower(), _clean(company_external_email()).lower(), _clean(row["email"]).lower()} - {""}
        if incoming and valid(incoming) and incoming.lower() in allowed:
            q["salesEmail"] = incoming
            return
        q["salesEmail"] = resolve_for_row(row)["email"]
    except Exception:  # noqa: BLE001
        pass
