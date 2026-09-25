# -*- coding: utf-8 -*-
"""e2e：個資蒐集告知擴大到其他表單（2026-09-26；CUSTOMIZATION-SPEC §9.3，沿用 R3）。

- 客戶（新建＋聯絡人）：每一位聯絡人顯示「尚未記錄」；列印告知書（聯絡人範本＋姓名）；勾選存檔 ⇒ 伺服器紀錄；再打開顯示已告知。
- 供應商、承攬商、使用者帳號：編輯視窗勾選存檔 ⇒ 伺服器紀錄；再打開顯示已告知。
- 沒勾選照常存檔（不擋）。
觀測點一律是伺服器端的紀錄（`privacy_notice_acks`），不是畫面上的模型。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from helpers import privacy_notice as pn  # noqa: E402

ROOT = "Alpine.$data(document.querySelector('[x-data]'))"
NO_PRINT = "window.print = function () { window.__printed = true }"


def _ready(page, cond):
    page.wait_for_function(f"() => window.Alpine && document.querySelector('[x-data]') && ({cond})", timeout=20000)


def _tok(client, u):
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u[0], "password": u[1]}).json()["token"]}


@pytest.mark.e2e
def test_customer_contact_notice_print_and_record(live_server, make_user, new_page, login_as, client):
    u = make_user(username="pne_cu", role="superadmin")
    page = new_page()
    page.context.add_init_script(NO_PRINT)
    login_as(page, u)
    page.goto(live_server + "/pages/customers.html")
    _ready(page, f"{ROOT}.backendOnline && {ROOT}.privacyNotice")
    page.evaluate(f"""() => {{ const d = {ROOT}; d.openCreate(); d.form.name = '告知測試客戶'; d.addContact();
        d.form.contacts[0].name = '王聯絡' }}""")
    card = page.locator("[data-privacy-card]")
    row = card.locator("[data-privacy-contact]")
    row.locator("[data-privacy-missing]").wait_for(state="visible", timeout=10000)
    with page.context.expect_page(timeout=10000) as pop:
        row.locator("[data-print-notice]").click()
    doc = pop.value
    doc.wait_for_load_state()
    assert "王聯絡" in doc.locator("[data-subject]").inner_text()
    assert "業務往來" in doc.locator("[data-notice-text]").inner_text(), "要印聯絡人用的告知，不是承攬範本"
    doc.close()
    row.locator("input[data-privacy-ack]").check()
    page.evaluate(f"() => {ROOT}.saveCustomer()")
    page.wait_for_function(f"() => !{ROOT}.showModal", timeout=10000)
    cust = next(c for c in client.get("/api/customers", headers=_tok(client, u)).json() if c["name"] == "告知測試客戶")
    ctid = cust["contacts"][0]["id"]
    rec = pn.get_ack("customer_contact", f"{cust['id']}:{ctid}")
    assert rec and rec["byUsername"] == "pne_cu"
    assert rec["noticeHash"] == pn.notice_hash(pn.current_purpose_notice("contact"))
    page.evaluate(f"() => {ROOT}.openEdit({ROOT}.customers.find(c => c.id === {cust['id']}))")
    acked = card.locator("[data-privacy-acked]")
    acked.wait_for(state="visible", timeout=10000)
    assert "pne_cu" in acked.inner_text()


@pytest.mark.e2e
def test_supplier_contact_notice_records_and_unchecked_does_not_block(live_server, make_user, new_page, login_as, client):
    u = make_user(username="pne_su", role="superadmin")
    h = _tok(client, u)
    sid = client.post("/api/suppliers", json={"name": "告知測試供應商", "data": {"contacts": [
        {"id": 501, "name": "甲窗口"}, {"id": 502, "name": "乙窗口"}]}}, headers=h).json()["id"]
    page = new_page()
    login_as(page, u)
    page.goto(live_server + "/pages/suppliers.html")
    _ready(page, f"{ROOT}.suppliers.length > 0 && {ROOT}.privacyNotice")
    page.evaluate(f"() => {ROOT}.openEdit({ROOT}.suppliers.find(s => s.id === {sid}))")
    rows = page.locator("[data-privacy-card] [data-privacy-contact]")
    rows.nth(1).locator("[data-privacy-missing]").wait_for(state="visible", timeout=10000)
    rows.nth(0).locator("input[data-privacy-ack]").check()          # 只勾第一位
    page.evaluate(f"() => {ROOT}.saveSupplier()")
    page.wait_for_function(f"() => !{ROOT}.showModal", timeout=10000)
    assert pn.get_ack("supplier_contact", f"{sid}:501")["byUsername"] == "pne_su"
    assert pn.get_ack("supplier_contact", f"{sid}:502") is None, "沒勾的那一位不可以被記錄（而且存檔沒被擋）"


@pytest.mark.e2e
def test_vendor_contractor_notice_records(live_server, make_user, new_page, login_as, client):
    u = make_user(username="pne_vd", role="superadmin")
    vid = client.post("/api/vendor-contractors", json={"name": "告知測試承攬商", "contact_name": "陳窗口"},
                      headers=_tok(client, u)).json()["id"]
    page = new_page()
    page.context.add_init_script(NO_PRINT)
    login_as(page, u)
    page.goto(live_server + "/pages/vendor-contractors.html")
    _ready(page, f"{ROOT}.vendors.length > 0 && {ROOT}.privacyNotice")
    page.evaluate(f"() => {ROOT}.openEdit({ROOT}.vendors.find(v => v.id === {vid}))")
    card = page.locator("[data-privacy-card]")
    card.locator("[data-privacy-missing]").wait_for(state="visible", timeout=10000)
    with page.context.expect_page(timeout=10000) as pop:
        card.locator("[data-print-notice]").click()
    doc = pop.value
    doc.wait_for_load_state()
    assert "陳窗口" in doc.locator("[data-subject]").inner_text()
    doc.close()
    card.locator("input[data-privacy-ack]").check()
    page.evaluate(f"() => {ROOT}.save()")
    page.wait_for_function(f"() => !{ROOT}.showModal && !{ROOT}.saving", timeout=10000)
    assert pn.get_ack("vendor_contractor", vid)["byUsername"] == "pne_vd"


@pytest.mark.e2e
def test_user_account_notice_records(live_server, make_user, new_page, login_as, client):
    u = make_user(username="pne_us", role="superadmin")
    uid = client.post("/api/users", json={"username": "pne_target", "password": "Xy9#long-pass",
                                          "display_name": "林員工"}, headers=_tok(client, u)).json()["id"]
    page = new_page()
    page.context.add_init_script(NO_PRINT)
    login_as(page, u)
    page.goto(live_server + "/pages/users.html")
    _ready(page, f"{ROOT}.users.length > 0 && {ROOT}.isSuperAdmin && {ROOT}.privacyNotice")
    page.evaluate(f"() => {ROOT}.openEdit({ROOT}.users.find(x => x.id === {uid}))")
    card = page.locator("[data-privacy-card]")
    card.locator("[data-privacy-missing]").wait_for(state="visible", timeout=10000)
    with page.context.expect_page(timeout=10000) as pop:
        card.locator("[data-print-notice]").click()
    doc = pop.value
    doc.wait_for_load_state()
    assert "林員工" in doc.locator("[data-subject]").inner_text()
    assert "帳號" in doc.locator("[data-notice-text]").inner_text()
    doc.close()
    card.locator("input[data-privacy-ack]").check()
    page.evaluate(f"() => {ROOT}.saveUser()")
    page.wait_for_function(f"() => !{ROOT}.showModal", timeout=10000)
    assert pn.get_ack("user", uid)["byUsername"] == "pne_us"
    page.evaluate(f"() => {ROOT}.openEdit({ROOT}.users.find(x => x.id === {uid}))")
    acked = card.locator("[data-privacy-acked]")
    acked.wait_for(state="visible", timeout=10000)
    assert "pne_us" in acked.inner_text()


@pytest.mark.e2e
def test_company_profile_edits_contact_notice(live_server, make_user, new_page, login_as):
    from helpers.settings import _get_setting
    u = make_user(username="pne_cp", role="superadmin")
    page = new_page()
    login_as(page, u)
    page.goto(live_server + "/pages/company-profile-settings.html")
    _ready(page, f"{ROOT}.session && {ROOT}.session.token")
    card = page.locator("[data-privacy-notice-card]")
    card.wait_for(state="visible", timeout=10000)
    card.locator("[data-apply-template-contact]").click()
    page.wait_for_function("() => (document.querySelector('textarea[data-privacy-notice-contact]').value || '')"
                           ".includes('業務往來')", timeout=5000)
    ta = card.locator("textarea[data-privacy-notice-contact]")
    ta.fill(ta.input_value().replace("【請填寫】", "台中市（測試）", 1))
    card.locator("[data-save-privacy]").click()
    page.wait_for_function(f"() => !{ROOT}.saving && {ROOT}.msg === '設定已儲存'", timeout=10000)
    prof = _get_setting("company_profile", {}) or {}
    assert "台中市（測試）" in prof.get("privacy_notice_contact", "")
    assert not (prof.get("privacy_notice") or "").strip(), "只改聯絡人那一段，承攬那一段不可以被帶動"
