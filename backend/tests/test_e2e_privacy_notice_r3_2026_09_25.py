# -*- coding: utf-8 -*-
"""R3 e2e：個資蒐集告知（個資法 §8 I；CUSTOMIZATION-SPEC §9.3）。

- 公司資料設定頁：「套用範本」帶入範本、改寫後存檔 ⇒ 真的寫進 company_profile。
- 勞報單頁：列印告知書（新視窗有告知文字與當事人姓名）；勾「已告知」存檔 ⇒ 伺服器紀錄＋畫面顯示時間與人員。
- 承攬人員名冊：編輯視窗顯示「尚未記錄」；勾選存檔 ⇒ 紀錄寫入；再打開 ⇒ 顯示已告知。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from helpers import privacy_notice as pn  # noqa: E402

ROOT = "Alpine.$data(document.querySelector('[x-data]'))"
NO_PRINT = "window.print = function () { window.__printed = true }"


def _ready(page, cond):
    page.wait_for_function(f"() => window.Alpine && document.querySelector('[x-data]') && ({cond})", timeout=20000)


@pytest.mark.e2e
def test_company_profile_page_edits_the_notice(live_server, make_user, new_page, login_as):
    from helpers.settings import _get_setting
    u = make_user(username="r3e_cp", role="superadmin")
    page = new_page()
    login_as(page, u)
    page.goto(live_server + "/pages/company-profile-settings.html")
    _ready(page, f"{ROOT}.session && {ROOT}.session.token")
    card = page.locator("[data-privacy-notice-card]")
    card.wait_for(state="visible", timeout=10000)
    card.locator("[data-apply-template]").click()
    ta = card.locator("textarea[data-privacy-notice]")
    page.wait_for_function("() => (document.querySelector('textarea[data-privacy-notice]').value || '')"
                           ".includes('個人資料保護法')", timeout=5000)
    ta.fill(ta.input_value().replace("【請填寫】", "台北市（測試）", 1))
    card.locator("[data-save-privacy]").click()
    page.wait_for_function(f"() => !{ROOT}.saving && {ROOT}.msg === '設定已儲存'", timeout=10000)
    saved = (_get_setting("company_profile", {}) or {}).get("privacy_notice", "")
    assert "個人資料保護法" in saved and "台北市（測試）" in saved


@pytest.mark.e2e
def test_payslip_form_prints_and_records_the_notice(live_server, make_user, new_page, login_as, client):
    u = make_user(username="r3e_ps", role="superadmin")
    page = new_page()
    page.context.add_init_script(NO_PRINT)
    login_as(page, u)
    page.goto(live_server + "/pages/payslip-form.html")
    _ready(page, f"{ROOT}.rulesVersion !== '' && {ROOT}.privacyNotice")
    card = page.locator("[data-privacy-card]")
    assert card.locator("[data-privacy-missing]").is_visible()
    page.evaluate(f"""() => {{ const d = {ROOT}; d.q.contractorName = '王受領'; d.q.serviceContent = '安裝';
        d.q.grossAmount = 10000; d.calc() }}""")
    with page.context.expect_page(timeout=10000) as pop:
        card.locator("[data-print-notice]").click()
    doc = pop.value
    doc.wait_for_load_state()
    assert "王受領" in doc.locator("[data-subject]").inner_text()
    assert "蒐集目的" in doc.locator("[data-notice-text]").inner_text()
    doc.close()

    card.locator("input[data-privacy-ack]").check()
    page.evaluate(f"() => {ROOT}.save()")
    acked = card.locator("[data-privacy-acked]")
    acked.wait_for(state="visible", timeout=10000)
    assert "r3e_ps" in acked.inner_text()
    no = page.evaluate(f"() => {ROOT}.q.slipNo")
    tok = client.post("/api/auth/login", json={"username": u[0], "password": u[1]}).json()["token"]
    rec = client.get("/api/payslips/" + no, headers={"Authorization": "Bearer " + tok}).json()["data"]["privacyNotice"]
    assert rec["byUsername"] == "r3e_ps" and rec["noticeHash"] == pn.notice_hash(pn.current_notice())
