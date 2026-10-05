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

🔴 4、5 兩組在 bfe6eb36 是**紅燈探針**（審查發現：財務角色不在案件擁有者範圍 ⇒ 404；money_visible 收窄 ⇒ 業務／管理員不能編輯報價單、金額被遮）。
使用者已裁示要修（財務角色加入金額端點的擁有者範圍；money_visible 與財務拆開）。修好前標 `xfail(strict=True)`：修好之後這幾題會「意外通過」而紅燈
⇒ 逼修的人把標記拿掉（別讓探針永遠停在 xfail）。對照組（superadmin 通過）不標，用來證明夾具本身是對的。
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


# ── 帳號：superadmin modules=[]；其餘用真實角色樣板（admin／sales 另帶惰性的財務勾選） ──────────────
@pytest.fixture()
def accounts(client, make_user):
    from helpers.module_registry import ROLE_TEMPLATES
    out = {"superadmin": make_user("x_super", role="superadmin", modules=[])}
    for r in ("finance", "admin", "sales", "engineer", "viewer"):
        mods = list(ROLE_TEMPLATES[r])
        if r in ("admin", "sales"):
            mods += [k for k in INERT_FLAGS if k not in mods]
        out[r] = make_user("x_" + r, role=r, modules=mods)
    return {r: _login(client, *cred) for r, cred in out.items()}


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
    ("POST",   "/api/reports/t100-export/confirm", {"start": "2026-10-01", "end": "2026-10-31"}),
    ("POST",   "/api/reports/t100-export/unconfirm", {"sourceType": "x", "sourceKey": "y"}),
]


@pytest.mark.parametrize("method,path,body", EXT_ENDPOINTS, ids=lambda v: v if isinstance(v, str) else None)
def test_ext_matrix(client, accounts, method, path, body):
    _assert_gate(client, accounts, method, path, body)


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
    missing = [(m, p) for m, p, _b in EXT_ENDPOINTS
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


def test_in_app_cashier_recipient_helpers_are_finance_plus_superadmin(make_user):
    """站內／信件的『出納』收件人 helper（取代掃 cashier 勾選）：持有惰性 cashier 勾選的 admin 不在內。"""
    import db
    from helpers.module_registry import ROLE_TEMPLATES
    make_user("c_boss", role="superadmin", modules=[])
    make_user("c_fin", role="finance")
    make_user("c_adm", role="admin", modules=list(ROLE_TEMPLATES["admin"]) + INERT_FLAGS)
    make_user("c_sales", role="sales", modules=list(ROLE_TEMPLATES["sales"]) + INERT_FLAGS)
    from modules.case import expense_notify as EN
    from modules.payroll import bonus_payouts as BP
    conn = db.get_db()
    try:
        for who, names in (("expense_notify._cashiers", EN._cashiers(conn)), ("bonus_payouts.cashier_recipients", BP.cashier_recipients(conn, {}))):
            assert {"c_boss", "c_fin"} <= set(names) and not ({"c_adm", "c_sales"} & set(names)), (who, names)
    finally:
        conn.close()


#: 財務通知呼叫點：檔案 ⇒ 預期有幾個 `notify_module_activity` 呼叫，且**全部**帶 audience="finance"
FINANCE_NOTIFY_FILES = {
    "modules/arap/api/cashier.py": 1,
    "modules/arap/api/invoice_vouchers.py": 2,
    "modules/arap/api/payment_requests.py": 2,
    "modules/subcontract/api/contractor_vouchers.py": 5,
}
#: 案件檔裡的財務動作（以第 2 個位置參數＝動作標籤辨認）
FINANCE_NOTIFY_ACTIONS = {"modules/case/api/quotations.py": {"申請沖銷", "取消沖銷申請"}}


def _notify_calls(rel):
    tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8"))
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "notify_module_activity":
            aud = next((k.value.value for k in n.keywords if k.arg == "audience" and isinstance(k.value, ast.Constant)), None)
            act = n.args[1].value if len(n.args) > 1 and isinstance(n.args[1], ast.Constant) else None
            out.append((n.lineno, act, aud))
    return out


@pytest.mark.parametrize("rel,count", sorted(FINANCE_NOTIFY_FILES.items()))
def test_every_finance_notification_call_site_passes_audience_finance(rel, count):
    calls = _notify_calls(rel)
    assert len(calls) == count, "%s 的 notify_module_activity 呼叫數變了（%d → %d）：新增的財務通知要帶 audience=\"finance\"，並更新這份清單" % (rel, count, len(calls))
    assert all(a == "finance" for _l, _x, a in calls), "%s 有財務通知沒帶 audience=\"finance\"：%s" % (rel, [c for c in calls if c[2] != "finance"])


@pytest.mark.parametrize("rel,actions", sorted(FINANCE_NOTIFY_ACTIONS.items()))
def test_finance_actions_in_case_module_pass_audience_finance(rel, actions):
    calls = {act: aud for _l, act, aud in _notify_calls(rel) if act in actions}
    assert set(calls) == actions, "找不到預期的財務通知呼叫：%s" % (actions - set(calls))
    assert all(a == "finance" for a in calls.values()), calls


# ── 4. 財務角色對別人的案件（擁有者範圍）──────────────────────────────────────
#: 修好（財務角色加入金額端點的擁有者範圍，使用者已裁示）之前是紅燈探針；修好後意外通過 ⇒ 拿掉標記。
_PROBE_M2 = pytest.mark.xfail(strict=True, reason="審查發現 #2：財務角色不在案件擁有者範圍 ⇒ 別人的案件 404；待 hichan-7b 修（財務角色加入金額端點的擁有者範圍）")


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


@_PROBE_M2
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


@_PROBE_M2
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


@_PROBE_M2
def test_finance_role_sees_material_payments_of_a_foreign_case(finance_on_foreign_case):
    c, h, fh = finance_on_foreign_case
    _material_setup()
    r = c.get("/api/quotations/%s/material-payments" % NO, headers=fh)
    assert r.status_code == 200 and not r.json().get("moneyMasked") and "m1" in r.json()["orders"], "%s %s" % (r.status_code, r.text[:160])


# ── 5. 業務／管理員：報價單編輯與金額不受財務角色改動影響 ─────────────────────
_PROBE_M1 = pytest.mark.xfail(strict=True, reason="審查發現 #1：money_visible 收窄成財務角色 ⇒ 業務／管理員不能編輯報價單、金額被遮；待 hichan-7b 修（money_visible 與財務拆開，使用者已裁示）")


def _seed_case(assigned):
    from tests.test_case_money_mask_2026_09_24 import _seed
    _seed(assigned=assigned, status="草稿")        # 非草稿的報價單要走正式流程／解鎖才能 PUT（與角色無關）
    from tests.test_case_money_mask_2026_09_24 import NO as MASK_NO
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
@_PROBE_M1
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
@_PROBE_M1
def test_sales_and_admin_can_still_edit_a_quotation(client, make_user, role):
    from helpers.module_registry import ROLE_TEMPLATES
    u = make_user("q_edit_" + role, role=role, modules=list(ROLE_TEMPLATES[role]))
    no = _seed_case([u[0]])
    h = _login(client, *u)
    before = _quote_data(no)
    r = client.put("/api/quotations/%s" % no, headers=h, json={"data": before})
    assert r.status_code == 200, "業務／管理員編輯報價單：%s %s" % (r.status_code, r.text[:200])
