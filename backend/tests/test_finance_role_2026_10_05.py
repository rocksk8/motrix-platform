"""第42班「財務角色」（使用者 2026-10-05 裁示）：財務／出納能力只屬於 `finance` 角色與 superadmin。

1. 單元：`has_finance_access`／`has_cashier_access`／`can_see_financial`／`user_has_module(財務三鍵)` 由角色推導，勾選不算；
   `effective_modules`；收件人 helper。
2. 矩陣（由下面的 F 類端點清單產生）：superadmin（modules=[]）與 finance 通過；admin（持有惰性勾選）、sales、engineer、viewer ⇒ 403。
   superadmin 不變式：沒有任何模組勾選也全通過。新增 F 類端點請加進 `F_ENDPOINTS`。
3. 靜態守門：F 類檔案裡 `"admin"` 字面值的出現次數只准減少（基線），helper 本體必含 superadmin 直通。
4. 角色驗證／角色變更稽核／影響報表。
"""
import json
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


# ── 1. 單元 ─────────────────────────────────────────────────────────────────────
ROLES = ("superadmin", "finance", "admin", "sales", "engineer", "viewer")
ALLOWED = {"superadmin", "finance"}


@pytest.mark.parametrize("role", ROLES)
def test_helpers_follow_role_not_flags(role):
    from helpers.auth import has_finance_access, has_cashier_access, can_see_financial, user_has_module
    flagged = {"role": role, "modules": json.dumps(["cashier", "finance", "financial_view"])}   # 惰性勾選：持有也不算
    bare = {"role": role, "modules": "[]"}
    for u in (flagged, bare):
        assert has_finance_access(u) == (role in ALLOWED)
        assert has_cashier_access(u) == (role in ALLOWED)
        assert can_see_financial(u) == (role in ALLOWED)
        for k in ("cashier", "finance", "financial_view"):
            assert user_has_module(u, k) == (role in ALLOWED), (role, k)


def test_non_finance_keys_still_follow_the_modules_json():
    from helpers.auth import user_has_module
    assert user_has_module({"role": "sales", "modules": json.dumps(["quotation"])}, "quotation")
    assert not user_has_module({"role": "superadmin", "modules": "[]"}, "quotation")      # 其餘鍵不變（superadmin 走 require_any_module 直通）


def test_effective_modules():
    from helpers.auth import effective_modules
    raw = json.dumps(["dashboard", "cashier", "finance", "financial_view", "reports"])
    assert effective_modules("admin", raw) == ["dashboard", "reports"]
    assert effective_modules("sales", raw) == ["dashboard", "reports"]
    for r in ("finance", "superadmin"):
        e = effective_modules(r, raw)
        assert {"cashier", "finance", "financial_view", "dashboard", "reports"} <= set(e)
    assert effective_modules("admin", "壞掉的 json") == []


def test_helper_bodies_keep_the_superadmin_passthrough():
    src = (BACKEND / "helpers" / "auth.py").read_text(encoding="utf-8")
    assert re.search(r'FINANCE_ROLES\s*=\s*\("superadmin"', src)
    body = src[src.index("def has_finance_access"):src.index("def has_cashier_access")]
    assert 'return (user or {}).get("role") in FINANCE_ROLES' in body


def test_finance_recipients(client, make_user):
    import db
    from helpers.auth import finance_usernames
    from helpers.email_notify import finance_recipient_emails
    make_user("fin1", role="finance")
    make_user("fin_off", role="finance")
    make_user("adm1", role="admin")
    make_user("boss", role="superadmin")
    conn = db.get_db()
    try:
        for u in ("fin1", "fin_off", "adm1", "boss"):
            conn.execute("UPDATE users SET email=? WHERE username=?", (u + "@example.com", u))
        conn.execute("UPDATE users SET notification_muted=? WHERE username='fin_off'", (json.dumps(["module_activity"]),))
        conn.execute("UPDATE users SET active=0 WHERE username='nobody'")
        conn.commit()
        names = finance_usernames(conn)
    finally:
        conn.close()
    assert {"fin1", "fin_off", "boss"} <= set(names) and "adm1" not in names
    mails = finance_recipient_emails("module_activity")
    assert "fin1@example.com" in mails and "boss@example.com" in mails
    assert "fin_off@example.com" not in mails and "adm1@example.com" not in mails      # 退訂的、admin 都不收


# ── 2. 矩陣 ─────────────────────────────────────────────────────────────────────
#: F 類（財務／出納／匯款／付款／T100／年度目標／獎金金額）端點：守門在 handler 最前面（先於驗證與查詢），
#: 所以用不存在的單號就能分辨「被擋（403）」與「放行（其他狀態）」。(方法, 路徑, JSON 本文)
F_ENDPOINTS = [
    ("GET",    "/api/cashier/remit-reviews", None),
    ("POST",   "/api/cashier/remit-reviews/x/y/decision", {}),
    ("GET",    "/api/settings/t100-export-config", None),
    ("GET",    "/api/settings/operating-targets", None),
    ("GET",    "/api/remit-kinds", None),
    ("DELETE", "/api/contractor-vouchers/NOPE", None),
    ("POST",   "/api/contractor-vouchers/NOPE/submit", {}),
    ("POST",   "/api/contractor-vouchers/NOPE/paid-toggle", {}),
    ("GET",    "/api/contractor-vouchers/NOPE/personnel-links", None),
    ("DELETE", "/api/invoice-vouchers/NOPE", None),
    ("POST",   "/api/invoice-vouchers/NOPE/submit", {}),
    ("DELETE", "/api/payment-requests/NOPE", None),
    ("POST",   "/api/payment-requests/NOPE/submit", {}),
    ("GET",    "/api/bonus/base/NOPE", None),
]


def _call(client, h, method, path, body):
    kw = {"headers": h}
    if body is not None:
        kw["json"] = body
    return client.request(method, path, **kw)


@pytest.fixture()
def accounts(client, make_user):
    out = {"superadmin": make_user("m_super", role="superadmin", modules=[])}      # 不變式：沒有任何勾選
    for r in ("finance", "admin", "sales", "engineer", "viewer"):
        out[r] = make_user("m_" + r, role=r)                                       # admin／sales 帶著惰性的財務勾選樣板
    return {r: _login(client, *cred) for r, cred in out.items()}


@pytest.mark.parametrize("method,path,body", F_ENDPOINTS, ids=lambda v: v if isinstance(v, str) else None)
def test_matrix_allowed_roles_pass_and_others_are_403(client, accounts, method, path, body):
    for role, h in accounts.items():
        r = _call(client, h, method, path, body)
        if role in ALLOWED:
            assert r.status_code not in (401, 403), "%s %s 應放行 %s，卻 %s：%s" % (method, path, role, r.status_code, r.text[:120])
        else:
            assert r.status_code == 403, "%s %s 應擋 %s，卻 %s：%s" % (method, path, role, r.status_code, r.text[:120])


def test_superadmin_without_any_module_flag_still_sees_finance_menu_keys(client, accounts):
    me = client.get("/api/auth/me", headers=accounts["superadmin"]).json()
    assert {"cashier", "finance", "financial_view"} <= set(me["modules"])


def test_admin_login_modules_hide_the_inert_flags(client, accounts):
    me = client.get("/api/auth/me", headers=accounts["admin"]).json()
    assert not ({"cashier", "finance", "financial_view"} & set(me["modules"]))
    fin = client.get("/api/auth/me", headers=accounts["finance"]).json()
    assert {"cashier", "finance", "financial_view"} <= set(fin["modules"])


def test_inert_flags_stay_in_the_database(make_user):
    import db
    make_user("keeper", role="admin")
    conn = db.get_db()
    try:
        mods = json.loads(conn.execute("SELECT modules FROM users WHERE username='keeper'").fetchone()["modules"])
    finally:
        conn.close()
    assert "cashier" in mods and "financial_view" in mods      # 回滾（舊版程式）會重新生效


# ── 3. 靜態守門 ─────────────────────────────────────────────────────────────────
#: F 類檔案裡 `"admin"` 字面值的出現次數基線（2026-10-05 第42班後）：只准減少。
#: 剩下的都是一般管理（M 類）：派工／案件編輯／留言／儀表板待辦等，見 docs/platform/plans/USER-PERMISSIONS-PROPOSAL.md。
ADMIN_LITERAL_BASELINE = {
    "modules/subcontract/api/contractor_vouchers.py": 1,
    "modules/arap/api/invoice_vouchers.py": 0,
    "modules/arap/api/payment_requests.py": 0,
    "modules/arap/api/cashier.py": 0,
    "modules/accounting/api/accounting_export.py": 0,
    "modules/subcontract/api/remit_kinds.py": 0,
    "modules/case/material_guard.py": 1,    # can_edit_orders（Q6：叫料建立／送審／到貨確認維持 admin）
    "modules/case/material_payment.py": 0,
    "helpers/financial_mask.py": 2,          # quote_money_visible／material_money_visible（拆開、Q6：報價單層級與材料申請日常作業維持 admin）
}


@pytest.mark.parametrize("rel,limit", sorted(ADMIN_LITERAL_BASELINE.items()))
def test_admin_literal_baseline_only_decreases(rel, limit):
    src = (BACKEND / rel).read_text(encoding="utf-8")
    n = len(re.findall(r"""["']admin["']""", src))
    assert n <= limit, "%s 出現 %d 次 \"admin\" 字面值（基線 %d）：財務／出納守門不可以再放 admin 直通" % (rel, n, limit)


def test_no_f_class_guard_uses_a_raw_cashier_or_finance_module_check_without_the_helper():
    """財務三鍵的勾選不再被任何地方直接讀（`"cashier" in mods` 這類）——一律走 helper／user_has_module（角色推導）。"""
    bad = []
    for rel in ("modules/case/expense_notify.py", "modules/payroll/bonus_payouts.py", "helpers/expense_types.py",
                "routers/platform_menu.py", "modules/analytics/api/dashboard.py"):
        for i, line in enumerate((BACKEND / rel).read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"""["'](cashier|finance|financial_view)["']\s+(not\s+)?in\s""", line):
                bad.append("%s:%d %s" % (rel, i, line.strip()))
    assert not bad, "\n".join(bad)


# ── 4. 角色驗證／稽核／報表 ──────────────────────────────────────────────────────
def test_role_validation_and_audit(client, make_user):
    make_user("root", role="superadmin", modules=[])
    h = _login(client, "root", "Test-Pass-123")
    body = {"username": "newfin", "password": "Zx9-strong-Pass!", "display_name": "財務甲", "role": "finance", "modules": []}
    r = client.post("/api/users", json=body, headers=h)
    assert r.status_code in (200, 201), r.text
    uid = r.json()["id"]
    assert client.post("/api/users", json={**body, "username": "bad1", "role": "root2"}, headers=h).status_code == 400
    assert client.put("/api/users/%d" % uid, json={**body, "role": "nope"}, headers=h).status_code == 400
    assert client.put("/api/users/%d" % uid, json={**body, "role": "sales"}, headers=h).status_code == 200
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT * FROM audit_log WHERE action='user.role_change' ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    assert row is not None and "finance" in json.dumps(dict(row), ensure_ascii=False) and "sales" in json.dumps(dict(row), ensure_ascii=False)


def test_impact_report_lists_who_loses_access_and_warns_without_finance_account(make_user):
    import db
    from tools import finance_role_impact_report as R
    make_user("boss", role="superadmin", modules=[])
    make_user("adm_a", role="admin")
    make_user("sales_b", role="sales")
    make_user("eng_c", role="engineer", modules=["dashboard"])
    make_user("eng_flag", role="engineer", modules=["dashboard"])
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET modules=? WHERE username='eng_flag'", (json.dumps(["dashboard", "cashier"]),))     # 惰性勾選（不經 make_user 的相容轉換）
        conn.commit()
        rep = R.build_report(conn)
    finally:
        conn.close()
    lose = {i["username"] for i in rep["loseAccess"]}
    assert {"adm_a", "sales_b", "eng_flag"} <= lose and "eng_c" not in lose and "boss" not in lose
    assert any(p["level"] == "warn" and "財務" in p["message"] for p in rep["problems"])
    assert R.exit_code(rep) == 1
    make_user("fin", role="finance")
    conn = db.get_db()
    try:
        rep2 = R.build_report(conn)
    finally:
        conn.close()
    assert [i["username"] for i in rep2["keepFinance"]] == ["fin"]
    assert "財務角色上線影響報表" in R.format_text(rep2)


def test_report_script_is_read_only():
    src = (BACKEND / "tools" / "finance_role_impact_report.py").read_text(encoding="utf-8")
    assert not re.search(r"\b(INSERT|UPDATE|DELETE)\b\s", src.split('"""', 2)[2])
    assert "commit(" not in src


def test_t100_confirm_and_unconfirm_are_superadmin_only():
    """預設 Q7：匯出＝財務角色；confirm／unconfirm（寫入總帳狀態）＝僅 superadmin。"""
    src = (BACKEND / "modules" / "accounting" / "api" / "accounting_export.py").read_text(encoding="utf-8")
    for fn in ("t100_export_confirm", "t100_export_unconfirm"):
        start = src.index("def %s(" % fn)
        nxt = src.find("@router", start)
        body = src[start:nxt if nxt != -1 else len(src)]
        assert "_require_t100_superadmin(authorization)" in body, fn
    assert 'u["role"] != "superadmin"' in src[src.index("def _require_t100_superadmin"):]
