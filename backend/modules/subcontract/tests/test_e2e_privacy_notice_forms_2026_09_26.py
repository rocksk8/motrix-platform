# -*- coding: utf-8 -*-
"""需要外包工班（M04）的題：刪掉 modules/subcontract 時隨模組消失（PLAYBOOK §B-11，稽核 D M04-M1）。

（2026-09-26 自 tests/test_e2e_privacy_notice_forms_2026_09_26.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
e2e：個資蒐集告知擴大到其他表單（2026-09-26；CUSTOMIZATION-SPEC §9.3，沿用 R3）。

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
