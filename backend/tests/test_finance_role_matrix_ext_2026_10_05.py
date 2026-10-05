"""第42班「財務角色」矩陣擴充（獨立審查補洞；只有測試，不動產品程式）。

`test_finance_role_2026_10_05.py` 的 F_ENDPOINTS 只有 14 條；審查（AST 掃描）找出 51 條帶財務守門的端點，其中 40 條沒有矩陣。本檔補：

1. **矩陣擴充**：下面的 `EXT_ENDPOINTS`（守門都在 handler 最前面，用不存在的單號即可分辨）。
   admin（持有惰性勾選）／sales／engineer／viewer ⇒ 403；superadmin（modules=[]）與 finance ⇒ **不是 401／403，也不是 5xx**
   （比原矩陣的「不是 401／403」更嚴：400／404 可以，500 不行）。新增 F 類端點請加進來。
2. **超管不變式的 PDF／匯出煙霧題**：superadmin（modules=[]）與 finance 打得進所有 Excel／PDF／匯出端點。
3. **通知收件人**：財務事件只寄「財務角色＋superadmin」、不寄 admin；一般事件仍寄 admin＋superadmin、不寄 finance；
   每個財務通知呼叫點都帶 `audience="finance"`（靜態）；站內通知收件人 helper 也是財務角色＋superadmin。
4. **財務角色對別人的案件**（擁有者範圍）：額外支出登錄日期、叫料發票日、材料付款清單。
5. **業務／管理員的報價單編輯與金額**不受財務角色改動影響。

4、5 兩組原本是 bfe6eb36 上的紅燈探針（審查發現 #1／#2：財務角色不在案件擁有者範圍 ⇒ 404；money_visible 收窄 ⇒ 業務／管理員不能編輯報價單、金額被遮）；
22753d76 修好（`require_case_money`／`quote_money_visible`）後 xfail 標記已拿掉，現在是一般回歸題。對照組（superadmin 通過）用來證明夾具本身是對的。
6. 22753d76 的裁示對照：材料申請日常作業維持 admin（財務角色也可）、發票日／匯款申請／改成本單價＝財務角色、T100 確認／取消確認＝僅 superadmin、
   成本精算與財務彙總維持財務專屬、`receivable()` 認得 finance 群組與 module_activity 的財務受眾。

⚠️ 建帳號：`conftest.make_user` 從 22753d76 起，明確傳入含 cashier／finance／financial_view 的 modules 的非財務帳號會被**悄悄換成 finance 角色**。
要建「持有惰性勾選的 admin／sales」請用本檔 `_db_user`（直接寫表）。
"""
import ast
import json
from pathlib import Path

import pytest

from modules.case.tests.test_material_change_core_2026_10_03 import _setup as _material_setup  # noqa: F401
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W, _ln, _login, _mk  # noqa: F401

BACKEND = Path(__file__).resolve().parent.parent
ALLOWED = ("superadmin", "finance")
DENIED = ("admin", "sales", "engineer", "viewer")
INERT_FLAGS = ["cashier", "finance", "financial_view"]


def _db_user(username, role, modules, password="Test-Pass-123"):
    """直接寫入 users（不經 conftest.make_user）。🔴 `make_user` 在 22753d76 起有相容替身：明確傳入的 modules 含
    cashier／finance／financial_view 的非財務帳號會被**悄悄換成 finance 角色**——要建「持有惰性勾選的 admin／sales」
    只能直接寫表，否則測的其實是財務角色（本檔第一版就因此整批誤判）。"""
    import db
    from helpers.auth import _hash_pw
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO users (username, password_hash, display_name, role, modules, active, created_at, must_change_password)"
                     " VALUES (?,?,?,?,?,1,?,0)", (username, _hash_pw(password), username, role, json.dumps(modules), "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()
    return username, password


# ── 帳號：superadmin modules=[]；其餘用真實角色樣板（admin／sales 另帶惰性的財務勾選） ──────────────
@pytest.fixture()
def accounts(client, make_user):
    from helpers.module_registry import ROLE_TEMPLATES
    out = {"superadmin": make_user("x_super", role="superadmin", modules=[])}
    for r in ("finance", "admin", "sales", "engineer", "viewer"):
        mods = list(ROLE_TEMPLATES[r])
        if r in ("admin", "sales"):
            out[r] = _db_user("x_" + r, r, mods + [k for k in INERT_FLAGS if k not in mods])
        else:
            out[r] = make_user("x_" + r, role=r, modules=mods)
    assert out["admin"] and _role_of("x_admin") == "admin" and _role_of("x_sales") == "sales", "帳號角色被改掉了（見 _db_user 說明）"
    return {r: _login(client, *cred) for r, cred in out.items()}


def _role_of(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT role FROM users WHERE username=?", (username,)).fetchone()["role"]
    finally:
        conn.close()


def _call(client, h, method, path, body=None, files=None):
    kw = {"headers": h}
    if files is not None:
        kw["files"] = files
    elif body is not None:
        kw["json"] = body
    return client.request(method, path, **kw)


def _assert_gate(client, accounts, method, path, body=None, files=None):
    for role, h in accounts.items():
        r = _call(client, h, method, path, body, files)
        if role in ALLOWED:
            assert r.status_code not in (401, 403) and r.status_code < 500, \
                "%s %s 應放行 %s，卻 %s：%s" % (method, path, role, r.status_code, r.text[:160])
        elif role in DENIED:
            assert r.status_code == 403, "%s %s 應擋 %s，卻 %s：%s" % (method, path, role, r.status_code, r.text[:160])


# ── 1. 矩陣擴充 ───────────────────────────────────────────────────────────────
_D = "?start=2026-10-01&end=2026-10-31"
EXT_ENDPOINTS = [
    # 承攬商匯款申請
    ("POST",   "/api/contractor-vouchers", {"dispatch_id": 999999}),
    ("POST",   "/api/contractor-vouchers/preview", {"dispatch_id": 999999}),
    ("POST",   "/api/contractor-vouchers/NOPE/export", {}),
    ("POST",   "/api/contractor-vouchers/NOPE/revoke-approval", {}),
    ("POST",   "/api/contractor-vouchers/NOPE/void", {"reason": "x"}),
    ("PATCH",  "/api/contractor-vouchers/NOPE/invoice", {}),
    ("POST",   "/api/contractor-vouchers/NOPE/personnel-link", {"payslipNo": ""}),
    # 開票申請憑據／請款單
    ("POST",   "/api/invoice-vouchers", {"quote_no": "NOPE", "scope": "amount", "amount": 1}),
    ("POST",   "/api/invoice-vouchers/NOPE/export", {}),
    ("POST",   "/api/invoice-vouchers/NOPE/revoke-approval", {}),
    ("POST",   "/api/payment-requests", {"quote_no": "NOPE", "scope": "amount", "stage": "full", "amount": 1}),
    ("PUT",    "/api/payment-requests/NOPE", {"scope": "amount", "stage": "full", "amount": 1}),
    ("POST",   "/api/payment-requests/NOPE/export", {}),
    ("POST",   "/api/payment-requests/NOPE/revoke-approval", {}),
    # 出納
    ("GET",    "/api/cashier/pending-payables", None),
    ("GET",    "/api/cashier/pending-payables/x/y/payee-bank", None),
    ("POST",   "/api/cashier/pending-payables/x/y/pay", {"paidDate": "2026-10-05"}),
    ("GET",    "/api/cashier/payable-queue", None),
    ("GET",    "/api/cashier/receivable-queue", None),
    ("GET",    "/api/cashier/payslip-queue", None),
    ("GET",    "/api/cashier/bonus-queue", None),
    ("GET",    "/api/cashier/execution-history", None),
    ("GET",    "/api/cashier/export", None),
    # 案件財務
    ("GET",    "/api/quotations/last-received-bank-account?customerName=x", None),
    ("GET",    "/api/sales-orders", None),
    ("PATCH",  "/api/quotations/NOPE/payment/0", {"received": True}),
    ("POST",   "/api/quotations/NOPE/payment/0/request-writeoff", {"reason": "x"}),
    ("POST",   "/api/quotations/NOPE/payment/0/cancel-writeoff", None),
    # 獎金／勞報單
    ("GET",    "/api/bonus/awards/999999/preview", None),
    ("GET",    "/api/bonus/awards/999999/pdf-download", None),
    ("POST",   "/api/bonus/awards/plan/NOPE", {}),
    ("POST",   "/api/bonus/cases/NOPE/mark-paid", {}),
    ("GET",    "/api/bonus/corrections", None),
    ("POST",   "/api/bonus/corrections/NOPE/mark-paid", {}),
    ("GET",    "/api/payslips/NOPE/signed-files/x", None),
    # 進貨批次
    ("POST",   "/api/inventory/batches/NOPE/paid-toggle", {"action": "pay"}),
    # T100 匯出（accounting_export：_require_t100_admin）
    ("GET",    "/api/reports/t100-export/vouchers" + _D, None),
    ("GET",    "/api/reports/t100-export/preview" + _D, None),
    ("GET",    "/api/reports/t100-export/confirmed" + _D, None),
]
#: 第42班預設 Q7：T100 確認／取消確認（寫入總帳狀態）僅 superadmin；財務角色只能預覽／下載（22753d76 起）
SUPERADMIN_ONLY_ENDPOINTS = [
    ("POST",   "/api/reports/t100-export/confirm", {"start": "2026-10-01", "end": "2026-10-31"}),
    ("POST",   "/api/reports/t100-export/unconfirm", {"sourceType": "x", "sourceKey": "y"}),
]


@pytest.mark.parametrize("method,path,body", EXT_ENDPOINTS, ids=lambda v: v if isinstance(v, str) else None)
def test_ext_matrix(client, accounts, method, path, body):
    _assert_gate(client, accounts, method, path, body)


@pytest.mark.parametrize("method,path,body", SUPERADMIN_ONLY_ENDPOINTS, ids=lambda v: v if isinstance(v, str) else None)
def test_superadmin_only_endpoints(client, accounts, method, path, body):
    for role, h in accounts.items():
        r = _call(client, h, method, path, body)
        if role == "superadmin":
            assert r.status_code not in (401, 403) and r.status_code < 500, (method, path, r.status_code, r.text[:160])
        else:
            assert r.status_code == 403, "%s %s 應只有 superadmin，卻放行 %s：%s %s" % (method, path, role, r.status_code, r.text[:160])


def test_ext_matrix_bank_reconcile_upload(client, accounts):
    """檔案上傳端點：守門在讀檔之前（has_cashier_access）；上傳一個空 CSV，財務放行（400／404 都可以，不可 5xx）。"""
    for role, h in accounts.items():
        r = client.post("/api/reports/bank-reconcile", headers=h, files={"file": ("x.csv", b"a,b\n", "text/csv")})
        if role in ALLOWED:
            assert r.status_code not in (401, 403) and r.status_code < 500, (role, r.status_code, r.text[:160])
        elif role in DENIED:
            assert r.status_code == 403, (role, r.status_code, r.text[:160])


def test_ext_list_is_not_stale():
    """清單裡的路徑都真的存在於程式（改路徑沒同步更新這份清單，題目會變成『全員 404』卻看起來綠）——以靜態掃路由字面值核對。"""
    import re
    routes = []
    for p in list((BACKEND / "modules").rglob("*.py")) + list((BACKEND / "routers").rglob("*.py")):
        if "/tests/" in p.as_posix():
            continue
        src = p.read_text(encoding="utf-8")
        prefix = re.search(r'APIRouter\([^)]*prefix="([^"]+)"', src)
        for m in re.finditer(r'@router\.(get|post|put|patch|delete)\(\s*"([^"]*)"', src):
            routes.append((m.group(1).upper(), (prefix.group(1) if prefix else "") + m.group(2)))
    def _rx(p):
        return re.compile("^" + "[^/]+".join(re.escape(x) for x in re.split(r"\{[^}]+\}", p)) + "$")
    rx = [(m, _rx(p)) for m, p in routes]
    missing = [(m, p) for m, p, _b in EXT_ENDPOINTS + SUPERADMIN_ONLY_ENDPOINTS
               if not any(rm == m and r.match(p.split("?")[0]) for rm, r in rx)]
    assert not missing, "EXT_ENDPOINTS 指向不存在的路由：%s" % missing


# ── 2. 超管不變式：PDF／Excel／匯出煙霧題 ───────────────────────────────────────
SMOKE_EXPORTS = [
    ("GET", "/api/reports/financial/excel"),
    ("GET", "/api/reports/financial/pdf"),
    ("GET", "/api/cashier/export"),
    ("GET", "/api/reports/t100-export/vouchers" + _D),
    ("GET", "/api/bonus/awards/999999/pdf-download"),
]


@pytest.mark.parametrize("method,path", SMOKE_EXPORTS)
def test_superadmin_without_modules_and_finance_can_reach_every_pdf_and_export(client, accounts, method, path):
    for role in ALLOWED:
        r = client.request(method, path, headers=accounts[role])
        assert r.status_code not in (401, 403) and r.status_code < 500, \
            "%s %s：%s（modules=%s）被擋或炸掉：%s %s" % (method, path, role, "[]" if role == "superadmin" else "角色樣板", r.status_code, r.text[:160])


@pytest.mark.parametrize("path", ["/api/cashier/export", "/api/reports/t100-export/vouchers" + _D])
def test_excel_exports_really_return_a_workbook_for_allowed_roles(client, accounts, path):
    for role in ALLOWED:
        r = client.get(path, headers=accounts[role])
        assert r.status_code == 200, (role, r.status_code, r.text[:160])
        assert r.content[:2] == b"PK", "%s：不是 xlsx（zip）檔頭：%r" % (role, r.content[:8])


# ── 3. 通知收件人 ─────────────────────────────────────────────────────────────
@pytest.fixture()
def mailbox(client, make_user, monkeypatch):
    """四個有 Email 的帳號＋攔截 `_async_send`（不真的寄）。回傳 `sent`＝[(收件人清單, 主旨)]。"""
    import db
    from helpers import email_notify as en
    for name, role in (("n_boss", "superadmin"), ("n_fin", "finance"), ("n_adm", "admin"), ("n_sales", "sales")):
        make_user(name, role=role)
    conn = db.get_db()
    try:
        for name in ("n_boss", "n_fin", "n_adm", "n_sales"):
            conn.execute("UPDATE users SET email=? WHERE username=?", (name + "@example.test", name))
        conn.commit()
    finally:
        conn.close()
    sent = []
    monkeypatch.setattr(en, "_async_send", lambda to, subject, html, *a, **k: sent.append((list(to), subject)))
    return sent


def _mails(sent):
    return {a for to, _s in sent for a in to}


def test_finance_audience_goes_to_finance_and_superadmin_only(mailbox):
    from helpers import email_notify as en
    en.notify_module_activity("報價單", "申請沖銷", "某人", "MQ-1 第1期", "quotations.html", audience="finance")
    assert _mails(mailbox) == {"n_boss@example.test", "n_fin@example.test"}, "財務事件不可寄 admin／sales：%s" % mailbox


def test_default_audience_still_goes_to_admins_and_superadmin_not_finance(mailbox):
    from helpers import email_notify as en
    en.notify_module_activity("報價單", "建立", "某人", "MQ-1", "quotations.html")
    assert _mails(mailbox) == {"n_boss@example.test", "n_adm@example.test"}, "一般事件維持寄管理員＋超管（財務角色不在內）：%s" % mailbox


def test_finance_audience_respects_personal_mute_and_the_recipient_override(mailbox, make_user):
    import db
    from helpers import email_notify as en
    from helpers import mail_types as mt
    from helpers.settings import _set_setting
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET notification_muted=? WHERE username='n_fin'", (json.dumps(["module_activity"]),))
        conn.commit()
    finally:
        conn.close()
    en.notify_module_activity("報價單", "申請沖銷", "某人", "MQ-1", "quotations.html", audience="finance")
    assert _mails(mailbox) == {"n_boss@example.test"}, "退訂的財務角色不收：%s" % mailbox
    mailbox.clear()
    _set_setting(mt.OVERRIDES_KEY, {"module_activity": {"mode": "custom", "users": ["n_sales"], "roles": []}})
    en.notify_module_activity("報價單", "申請沖銷", "某人", "MQ-1", "quotations.html", audience="finance")
    assert _mails(mailbox) == {"n_sales@example.test"}, "超管在收件設定頁的『指定帳號』覆寫優先於財務預設：%s" % mailbox
    mailbox.clear()
    _set_setting(mt.OVERRIDES_KEY, {"module_activity": {"mode": "superadmin_only", "users": [], "roles": []}})
    en.notify_module_activity("報價單", "申請沖銷", "某人", "MQ-1", "quotations.html", audience="finance")
    assert _mails(mailbox) == {"n_boss@example.test"}


def test_in_app_cashier_recipient_helpers_are_finance_plus_superadmin(client, make_user):
    """站內／信件的『出納』收件人 helper（取代掃 cashier 勾選）：持有惰性 cashier 勾選的 admin 不在內。
    （用 `client` 夾具重置資料庫，且結束時刪掉自己建的帳號：沒有重置的測試會把帳號留給同一 worker 的下一題。）"""
    import db
    from helpers.module_registry import ROLE_TEMPLATES
    names_made = ("c_boss", "c_fin", "c_adm", "c_sales")
    try:
        make_user("c_boss", role="superadmin", modules=[])
        make_user("c_fin", role="finance")
        _db_user("c_adm", "admin", list(ROLE_TEMPLATES["admin"]) + INERT_FLAGS)
        _db_user("c_sales", "sales", list(ROLE_TEMPLATES["sales"]) + INERT_FLAGS)
        assert _role_of("c_adm") == "admin" and _role_of("c_sales") == "sales"
        from modules.case import expense_notify as EN
        from modules.payroll import bonus_payouts as BP
        conn = db.get_db()
        try:
            for who, names in (("expense_notify._cashiers", EN._cashiers(conn)), ("bonus_payouts.cashier_recipients", BP.cashier_recipients(conn, {}))):
                assert {"c_boss", "c_fin"} <= set(names) and not ({"c_adm", "c_sales"} & set(names)), (who, names)
        finally:
            conn.close()
    finally:
        conn = db.get_db()
        try:
            conn.execute("DELETE FROM users WHERE username IN (%s)" % ",".join("?" * len(names_made)), names_made)
            conn.commit()
        finally:
            conn.close()


#: 財務通知呼叫點：檔案 ⇒ 預期有幾個 `notify_module_activity` 呼叫，且**全部**帶 audience="finance"
FINANCE_NOTIFY_FILES = {
    "modules/arap/api/cashier.py": 1,
    "modules/arap/api/invoice_vouchers.py": 2,
    "modules/arap/api/payment_requests.py": 2,
    "modules/subcontract/api/contractor_vouchers.py": 5,
}
#: 案件檔裡的財務動作（以所在函式辨認）：沖銷申請／取消／核可退回、收款標記
FINANCE_NOTIFY_FUNCS = {"modules/case/api/quotations.py": {"request_payment_writeoff", "cancel_payment_writeoff", "approve_payment_writeoff", "mark_payment"}}


def _notify_calls(rel):
    """⇒ [(行, 所在函式, audience 字面值或 None)]"""
    tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8"))
    out = []
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for n in ast.walk(fn):
                if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "notify_module_activity":
                    aud = next((k.value.value for k in n.keywords if k.arg == "audience" and isinstance(k.value, ast.Constant)), None)
                    out.append((n.lineno, fn.name, aud))
    return sorted(set(out))


@pytest.mark.parametrize("rel,count", sorted(FINANCE_NOTIFY_FILES.items()))
def test_every_finance_notification_call_site_passes_audience_finance(rel, count):
    calls = _notify_calls(rel)
    assert len(calls) == count, "%s 的 notify_module_activity 呼叫數變了（%d → %d）：新增的財務通知要帶 audience=\"finance\"，並更新這份清單" % (rel, count, len(calls))
    assert all(a == "finance" for _l, _x, a in calls), "%s 有財務通知沒帶 audience=\"finance\"：%s" % (rel, [c for c in calls if c[2] != "finance"])


@pytest.mark.parametrize("rel,funcs", sorted(FINANCE_NOTIFY_FUNCS.items()))
def test_finance_actions_in_case_module_pass_audience_finance(rel, funcs):
    calls = [(l, f, a) for l, f, a in _notify_calls(rel) if f in funcs]
    assert {f for _l, f, _a in calls} == funcs, "找不到預期的財務通知呼叫：%s" % (funcs - {f for _l, f, _a in calls})
    assert all(a == "finance" for _l, _f, a in calls), [c for c in calls if c[2] != "finance"]


# ── 4. 財務角色對別人的案件（擁有者範圍）──────────────────────────────────────


@pytest.fixture()
def finance_on_foreign_case(W, make_user):
    """W：案件 NO 的業務是 pl_sa（superadmin）；財務帳號不是該案業務、也沒被指派。"""
    from helpers.module_registry import ROLE_TEMPLATES
    c, h = W
    cred = make_user("f_fin", role="finance", modules=list(ROLE_TEMPLATES["finance"]))
    return c, h, _login(c, *cred)


def _expense(c, h):
    r = _mk(c, h, "purchase_order", [_ln("a", 1)])
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_control_superadmin_can_register_extra_expense_dates(W):
    c, h = W
    eid = _expense(c, h)
    r = c.patch("/api/quotations/%s/extra-expenses/%d/dates" % (NO, eid), headers=h, json={"invoiceDate": "2026-10-05"})
    assert r.status_code == 200, r.text


def test_finance_role_can_register_extra_expense_dates_on_a_foreign_case(finance_on_foreign_case):
    c, h, fh = finance_on_foreign_case
    eid = _expense(c, h)
    r = c.patch("/api/quotations/%s/extra-expenses/%d/dates" % (NO, eid), headers=fh, json={"invoiceDate": "2026-10-05"})
    assert r.status_code == 200, "財務角色登錄別人案件的額外支出日期：%s %s" % (r.status_code, r.text[:160])


def test_control_superadmin_can_register_material_invoice_date(W):
    c, h = W
    _material_setup()
    r = c.patch("/api/quotations/%s/material-orders/m1/invoice-date" % NO, headers=h, json={"invoiceDate": "2026-10-05"})
    assert r.status_code == 200, r.text


def test_finance_role_can_register_material_invoice_date_on_a_foreign_case(finance_on_foreign_case):
    c, h, fh = finance_on_foreign_case
    _material_setup()
    r = c.patch("/api/quotations/%s/material-orders/m1/invoice-date" % NO, headers=fh, json={"invoiceDate": "2026-10-05"})
    assert r.status_code == 200, "財務角色登錄別人案件的叫料發票日：%s %s" % (r.status_code, r.text[:160])


def test_control_superadmin_sees_unmasked_material_payments(W):
    c, h = W
    _material_setup()
    r = c.get("/api/quotations/%s/material-payments" % NO, headers=h)
    assert r.status_code == 200 and not r.json().get("moneyMasked") and "m1" in r.json()["orders"], r.text[:200]


def test_finance_role_sees_material_payments_of_a_foreign_case(finance_on_foreign_case):
    c, h, fh = finance_on_foreign_case
    _material_setup()
    r = c.get("/api/quotations/%s/material-payments" % NO, headers=fh)
    assert r.status_code == 200 and not r.json().get("moneyMasked") and "m1" in r.json()["orders"], "%s %s" % (r.status_code, r.text[:160])


# ── 5. 業務／管理員：報價單編輯與金額不受財務角色改動影響 ─────────────────────


def _seed_case(assigned, owner=None):
    """`owner`＝案件業務帳號（PUT 只有案件業務或 admin+ 能改；被指派的協作者只能看）。"""
    import db
    from tests.test_case_money_mask_2026_09_24 import NO as MASK_NO, _seed
    _seed(assigned=assigned, status="草稿")        # 非草稿的報價單要走正式流程／解鎖才能 PUT（與角色無關）
    if owner:
        conn = db.get_db()
        try:
            uid = conn.execute("SELECT id FROM users WHERE username=?", (owner,)).fetchone()["id"]
            conn.execute("UPDATE quotations SET sales_person_id=?, sales_person=? WHERE quote_no=?", (uid, owner, MASK_NO))
            conn.commit()
        finally:
            conn.close()
    return MASK_NO


def _quote_data(no):
    import db
    conn = db.get_db()
    try:
        return json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()["data_json"])
    finally:
        conn.close()


@pytest.mark.parametrize("role", ["superadmin"])
def test_control_superadmin_edits_quotation_and_sees_totals(client, make_user, role):
    u = make_user("q_ctrl", role="superadmin", modules=[])
    no = _seed_case([u[0]])
    h = _login(client, *u)
    row = next(it for it in client.get("/api/quotations?deal_tag=已成案", headers=h).json()["items"] if (it.get("quote_no") or it.get("quoteNo")) == no)
    assert row["total"] == 10290
    r = client.put("/api/quotations/%s" % no, headers=h, json={"data": _quote_data(no)})
    assert r.status_code == 200, r.text[:200]


@pytest.mark.parametrize("role", ["sales", "admin"])
def test_sales_and_admin_still_see_quotation_totals(client, make_user, role):
    from helpers.module_registry import ROLE_TEMPLATES
    u = make_user("q_tot_" + role, role=role, modules=list(ROLE_TEMPLATES[role]))
    no = _seed_case([u[0]])
    h = _login(client, *u)
    row = next(it for it in client.get("/api/quotations?deal_tag=已成案", headers=h).json()["items"] if (it.get("quote_no") or it.get("quoteNo")) == no)
    assert row["total"] == 10290 and not row.get("moneyMasked"), "報價單清單金額被遮：%s" % {k: row.get(k) for k in ("total", "moneyMasked")}
    detail = client.get("/api/quotations/%s" % no, headers=h).json()
    assert detail["total"] == 10290 and detail["data"]["tot"]["total"] == 10290, "報價單內容金額被遮"


@pytest.mark.parametrize("role", ["sales", "admin"])
def test_sales_and_admin_can_still_edit_a_quotation(client, make_user, role):
    from helpers.module_registry import ROLE_TEMPLATES
    u = make_user("q_edit_" + role, role=role, modules=list(ROLE_TEMPLATES[role]))
    no = _seed_case([u[0]], owner=u[0])
    h = _login(client, *u)
    before = _quote_data(no)
    r = client.put("/api/quotations/%s" % no, headers=h, json={"data": before})
    assert r.status_code == 200, "業務／管理員編輯報價單：%s %s" % (r.status_code, r.text[:200])


# ── 6. 22753d76 的裁示對照（(a)–(d)）────────────────────────────────────────────
def test_material_suppliers_picker_roles(client, accounts):
    """材料申請建立（admin／專案經理）與匯款申請（財務）都要選供應商：superadmin／admin／finance 放行；業務、工程、檢視者 403。"""
    for role, h in accounts.items():
        r = client.get("/api/material-suppliers", headers=h)
        if role in ("superadmin", "admin", "finance"):
            assert r.status_code == 200, (role, r.status_code, r.text[:160])
        else:
            assert r.status_code == 403, (role, r.status_code, r.text[:160])


def test_finance_and_admin_can_replace_material_orders_but_not_sales(finance_on_foreign_case, make_user):
    """Q6：材料申請日常作業維持 admin；財務角色可（不受擁有者限制）。空清單＝最小的合法 PATCH。"""
    from helpers.module_registry import ROLE_TEMPLATES
    c, h, fh = finance_on_foreign_case
    ah = _login(c, *make_user("m_adm", role="admin", modules=list(ROLE_TEMPLATES["admin"])))
    sh = _login(c, *make_user("m_sal", role="sales", modules=list(ROLE_TEMPLATES["sales"])))
    body = {"materialOrders": []}
    for who, hh in (("superadmin", h), ("finance", fh), ("admin", ah)):
        r = c.patch("/api/quotations/%s/material-orders" % NO, headers=hh, json=body)
        assert r.status_code == 200, (who, r.status_code, r.text[:160])
    r = c.patch("/api/quotations/%s/material-orders" % NO, headers=sh, json=body)
    assert r.status_code in (403, 404), (r.status_code, r.text[:160])               # 不是案件業務（404）或沒有權限（403）；絕不可 200


def test_material_invoice_date_is_finance_only_not_admin(finance_on_foreign_case, make_user):
    """使用者裁示：材料申請發票日＝財務角色／superadmin（admin 與專案經理都不行）。"""
    from helpers.module_registry import ROLE_TEMPLATES
    c, h, fh = finance_on_foreign_case
    _material_setup()
    ah = _login(c, *make_user("m_adm2", role="admin", modules=list(ROLE_TEMPLATES["admin"]) + ["project_manage"]))
    r = c.patch("/api/quotations/%s/material-orders/m1/invoice-date" % NO, headers=ah, json={"invoiceDate": "2026-10-05"})
    assert r.status_code == 403, (r.status_code, r.text[:160])


def test_settlement_and_finance_summary_stay_finance_only(finance_on_foreign_case, make_user):
    """成本精算／財務彙總維持財務專屬（22753d76 沒有放寬）：superadmin、finance（不受擁有者限制）放行；admin 403。
    這是『現況特徵化』題——使用者若裁示要讓業務／管理員做精算，改這題。"""
    from helpers.module_registry import ROLE_TEMPLATES
    c, h, fh = finance_on_foreign_case
    ah = _login(c, *make_user("s_adm", role="admin", modules=list(ROLE_TEMPLATES["admin"])))
    for url in ("/api/quotations/%s/settlement" % NO, "/api/quotations/%s/finance-summary" % NO):
        for who, hh in (("superadmin", h), ("finance", fh)):
            if who == "finance" and url.endswith("finance-summary"):
                continue                      # 見下面的探針（22753d76 漏改：仍用 require_case）
            r = c.get(url, headers=hh)
            assert r.status_code == 200, (url, who, r.status_code, r.text[:160])
        r = c.get(url, headers=ah)
        assert r.status_code == 403, (url, "admin", r.status_code, r.text[:160])


@pytest.mark.xfail(strict=True, reason="22753d76 漏改：GET /api/quotations/{no}/finance-summary（案件財務 Tab 應收應付總覽）仍用 require_case ⇒ 財務角色讀別人的案件 404；"
                                      "應與 settlement 一樣改 require_case_money。修好後這題會 XPASS ⇒ 拿掉標記")
def test_finance_role_reads_finance_summary_of_a_foreign_case(finance_on_foreign_case):
    c, h, fh = finance_on_foreign_case
    r = c.get("/api/quotations/%s/finance-summary" % NO, headers=fh)
    assert r.status_code == 200, (r.status_code, r.text[:160])


def test_receivable_list_knows_the_finance_group_and_the_finance_audience():
    """users.html 的退訂清單：財務角色會收到 module_activity（audience=finance）⇒ 要列出；未知／新群組不丟 KeyError。"""
    from types import SimpleNamespace
    from helpers import mail_types as mt
    from routers.mail_settings import receivable
    t = mt.get("module_activity")
    assert receivable(t, {}, "u", "finance") is True and receivable(t, {}, "u", "admin") is True and receivable(t, {}, "u", "sales") is False
    grp = SimpleNamespace(key="x_finance_group", group="finance", event="")
    assert receivable(grp, {}, "u", "finance") is True and receivable(grp, {}, "u", "superadmin") is True and receivable(grp, {}, "u", "admin") is False
    odd = SimpleNamespace(key="x_unknown_group", group="no_such_group", event="")
    assert receivable(odd, {}, "u", "finance") is False                                  # 不丟 KeyError


def test_receivable_endpoint_lists_module_activity_for_a_finance_user(client, make_user):
    su = make_user("r_sa", role="superadmin", modules=[])
    make_user("r_fin", role="finance")
    import db
    conn = db.get_db()
    try:
        uid = conn.execute("SELECT id FROM users WHERE username='r_fin'").fetchone()["id"]
    finally:
        conn.close()
    r = client.get("/api/mail-types/receivable?user_id=%d" % uid, headers=_login(client, *su))
    assert r.status_code == 200, r.text
    assert next(x for x in r.json()["items"] if x["key"] == "module_activity")["receivable"] is True
