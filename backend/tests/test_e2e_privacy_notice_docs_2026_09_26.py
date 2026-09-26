# -*- coding: utf-8 -*-
"""e2e：單據上手動輸入的聯絡人也要個資蒐集告知（2026-09-26 主持裁示；CUSTOMIZATION-SPEC §9.3）。

報價單（聯絡人）、案件（合約現場聯絡人）、完工單（驗收人）、網路規劃書（聯絡人；建立視窗與編輯頁）。
- 已存檔的聯絡人：顯示「尚未記錄」；勾選 ⇒ 伺服器立刻記錄 ⇒ 顯示已告知。
- 畫面上改了聯絡人但還沒存檔：勾選 ⇒ 伺服器拒絕，區塊顯示原因，沒有紀錄。
觀測點是伺服器端紀錄（`privacy_notice_acks`）。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from helpers import privacy_notice as pn  # noqa: E402

ROOT = "Alpine.$data(document.querySelector('[x-data]'))"
NO_PRINT = "window.print = function () { window.__printed = true }"


def _tok(client, u):
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u[0], "password": u[1]}).json()["token"]}


def _insert_quote(no, contact="林聯絡", site="趙現場"):
    import db
    cr = {"contract": {"contactPerson": site},
          "payment": {"items": [{"id": 1, "type": "訂金款", "pct": 100, "received": False, "note": ""}]},
          "materials": []}
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (no, "已送出", "測試客戶", "告知測試", 100, 95,
             json.dumps({"dealTag": "已成案", "contactName": contact, "caseRecord": cr}, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"))
        conn.commit()
    finally:
        conn.close()


def _check_and_expect_ack(page, name, user, card_sel="[data-privacy-card]"):
    card = page.locator(card_sel)
    card.locator("[data-privacy-missing]").wait_for(state="visible", timeout=20000)
    card.locator("input[data-privacy-ack]").check()
    acked = card.locator("[data-privacy-acked]")
    acked.wait_for(state="visible", timeout=10000)
    assert name in acked.inner_text() and user in acked.inner_text()


@pytest.mark.e2e
def test_quotation_contact_notice(live_server, make_user, new_page, login_as):
    u = make_user(username="pnd_q", role="superadmin")
    _insert_quote("PND-Q-001")
    page = new_page()
    page.context.add_init_script(NO_PRINT)
    login_as(page, u)
    page.goto(live_server + "/pages/quotation-form.html?id=PND-Q-001")
    _check_and_expect_ack(page, "林聯絡", "pnd_q")
    assert pn.get_ack("quote_contact", "PND-Q-001:林聯絡")["byUsername"] == "pnd_q"


@pytest.mark.e2e
def test_case_site_contact_notice(live_server, make_user, new_page, login_as):
    u = make_user(username="pnd_c", role="superadmin")
    _insert_quote("PND-C-001")
    page = new_page()
    page.on("dialog", lambda d: d.accept())
    login_as(page, u)
    page.goto(live_server + "/pages/case-management.html?q=PND-C-001")
    # 案件頁有兩個告知對象（合約現場聯絡人、出貨單收件人；稽核 D PN-M1）⇒ 指定這一個
    _check_and_expect_ack(page, "趙現場", "pnd_c", '[data-privacy-card][data-privacy-subject="case_site_contact"]')
    assert pn.get_ack("case_site_contact", "PND-C-001:趙現場")["byUsername"] == "pnd_c"


@pytest.mark.e2e
def test_completion_note_recipient_notice(live_server, make_user, new_page, login_as, client):
    u = make_user(username="pnd_cn", role="superadmin")
    _insert_quote("PND-CN-001")
    no = client.post("/api/completion-notes", json={"quote_no": "PND-CN-001", "recipient": "陳經理"},
                     headers=_tok(client, u)).json()["note_no"]
    page = new_page()
    login_as(page, u)
    page.goto(live_server + "/pages/completion-note-form.html?no=" + no)
    _check_and_expect_ack(page, "陳經理", "pnd_cn")
    assert pn.get_ack("completion_contact", f"{no}:陳經理")["byUsername"] == "pnd_cn"


@pytest.mark.e2e
def test_network_plan_form_unsaved_contact_is_refused_then_saved_one_is_recorded(
        live_server, make_user, new_page, login_as, client):
    u = make_user(username="pnd_np", role="superadmin")
    pid = client.post("/api/network-plans", json={"siteName": "告知案場", "contactName": "周窗口"},
                      headers=_tok(client, u)).json()["id"]
    page = new_page()
    page.context.add_init_script(NO_PRINT)
    login_as(page, u)
    page.goto(live_server + f"/pages/network-plan-form.html?id={pid}")
    card = page.locator("[data-privacy-card]")
    card.locator("[data-privacy-missing]").wait_for(state="visible", timeout=20000)
    # 畫面上換了聯絡人、還沒存檔 ⇒ 勾選被伺服器拒絕，區塊說明原因
    page.evaluate(f"() => {{ {ROOT}.plan.contactName = '未存的人' }}")
    card.locator("input[data-privacy-ack]").check()
    card.locator("[data-privacy-error]").wait_for(state="visible", timeout=10000)
    assert "先儲存" in card.locator("[data-privacy-error]").inner_text()
    assert pn.get_ack("network_plan_contact", f"{pid}:未存的人") is None
    # 改回已存檔的聯絡人 ⇒ 可以記錄
    page.evaluate(f"() => {{ {ROOT}.plan.contactName = '周窗口' }}")
    _check_and_expect_ack(page, "周窗口", "pnd_np")
    assert pn.get_ack("network_plan_contact", f"{pid}:周窗口")["byUsername"] == "pnd_np"


@pytest.mark.e2e
def test_network_plan_create_modal_records_after_create(live_server, make_user, new_page, login_as, client):
    u = make_user(username="pnd_nc", role="superadmin")
    page = new_page()
    login_as(page, u)
    page.goto(live_server + "/pages/network-plans.html")
    page.wait_for_function(f"() => window.Alpine && {ROOT} && {ROOT}.session && {ROOT}.session.token", timeout=20000)
    page.evaluate(f"""() => {{ const d = {ROOT}; d.openCreateModal(); d.createMode = 'standalone';
        d.createForm.siteName = '建立告知案場'; d.createForm.contactName = '鄭窗口' }}""")
    card = page.locator("[data-privacy-card]")
    card.locator("[data-privacy-missing]").wait_for(state="visible", timeout=10000)
    card.locator("input[data-privacy-ack]").check()
    with page.expect_navigation(timeout=15000):
        page.evaluate(f"() => {ROOT}.submitCreate()")
    plans = client.get("/api/network-plans", headers=_tok(client, u)).json()
    plans = plans.get("items", plans) if isinstance(plans, dict) else plans
    pid = next(p["id"] for p in plans if p.get("siteName") == "建立告知案場")
    assert pn.get_ack("network_plan_contact", f"{pid}:鄭窗口")["byUsername"] == "pnd_nc"
