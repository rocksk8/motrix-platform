# -*- coding: utf-8 -*-
"""2026-11-17 e2e（真瀏覽器）：報價單表單「七、備註事項」＋範本。

1. 輸入備註 ⇒ 字數計數器即時更新；存檔後重新載入，內容（換行、縮排、空行）原樣回來。
2. 範本：框是空的 ⇒ 點範本直接套用；框內已有字 ⇒ 先問「取代／接在後面」，兩種選擇各自正確；取消不動內容。
3. 範本 ≤ 10 個不出現分類篩選與搜尋；> 10 個才出現，篩選與搜尋真的會縮小清單。
4. 只有最高管理者看得到「管理範本」；在管理視窗新增（含「以目前備註內容新增」）後儲存 ⇒ 打到 PUT、清單更新；未命名擋下。
"""
from tests._requires import requires_module  # noqa: E402
import json

import pytest
pytestmark = requires_module("case", "本檔打 M01（報價單）的表單頁與設定端點")

pytest.importorskip("playwright.sync_api")

ROOT = "Alpine.$data(document.querySelector('[x-data]'))"
NOTES = "備註事項：\n一、車體規格\n   - 車體尺寸：L1200\n\n九、結尾"


def _wait_form(page):
    page.wait_for_function(f"() => window.Alpine && document.querySelector('[x-data]') && {ROOT}.q && {ROOT}.session", timeout=20000)
    page.wait_for_function(f"() => {ROOT}.notesTpls !== undefined", timeout=5000)


def _token(client, user):
    r = client.post("/api/auth/login", json={"username": user[0], "password": user[1]})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _put_templates(client, h, n, prefix="範本"):
    tpls = [{"key": "", "name": f"{prefix}{i:02d}", "category": "AGV" if i % 2 else "監控", "text": f"{prefix}{i:02d} 內容\n  - 條列"} for i in range(n)]
    r = client.put("/api/settings/quote-notes-templates", headers=h, json={"templates": tpls})
    assert r.status_code == 200, r.text


@pytest.mark.e2e
def test_notes_typing_counter_and_roundtrip(client, live_server, make_user, new_page, login_as):
    u = make_user(username="xn_e2e_rt", role="admin")
    page = new_page()
    login_as(page, u)
    page.goto(live_server + "/pages/quotation-form.html")
    _wait_form(page)
    box = page.locator("[data-testid=qf-extra-notes]")
    assert box.get_attribute("maxlength") == "20000"
    assert "0 / 20000" in page.locator("[data-testid=qf-extra-notes-count]").inner_text()
    box.fill(NOTES)
    assert f"{len(NOTES)} / 20000" in page.locator("[data-testid=qf-extra-notes-count]").inner_text()
    assert page.evaluate(f"() => {ROOT}.q.extraNotes") == NOTES

    page.evaluate(f"() => {{ const d = {ROOT}; d.q.customerName = '備註客戶'; d.q.projectName = '備註專案'; "
                  "d.q.items = [{id:1,type:'item',description:'設備',qty:1,cost:0,unitPrice:1000,amount:1000,margin:1}]; d.calcTotals() }")
    page.evaluate(f"() => {ROOT}.saveDraft ? {ROOT}.saveDraft() : {ROOT}.saveQuote()")
    page.wait_for_function(f"() => {ROOT}.q.quoteNo", timeout=15000)
    no = page.evaluate(f"() => {ROOT}.q.quoteNo")
    assert client.get(f"/api/quotations/{no}", headers=_token(client, u)).json()["data"]["extraNotes"] == NOTES, "存檔要把備註送到後端"

    page2 = new_page()
    login_as(page2, u)
    page2.goto(live_server + f"/pages/quotation-form.html?id={no}")
    _wait_form(page2)
    page2.wait_for_function(f"() => {ROOT}.q.quoteNo === '{no}'", timeout=15000)
    page2.wait_for_function(f"(n) => {ROOT}.q.extraNotes === n", arg=NOTES, timeout=10000)
    assert page2.locator("[data-testid=qf-extra-notes]").input_value() == NOTES


@pytest.mark.e2e
def test_template_apply_replace_append_cancel(client, live_server, make_user, new_page, login_as):
    sup = make_user(username="xn_e2e_tpl", role="superadmin")
    _put_templates(client, _token(client, sup), 2)
    page = new_page()
    login_as(page, sup)
    page.goto(live_server + "/pages/quotation-form.html")
    _wait_form(page)
    page.wait_for_function(f"() => {ROOT}.notesTpls.length === 2", timeout=8000)
    box = page.locator("[data-testid=qf-extra-notes]")
    page.locator("[data-testid=qf-notes-tpl-toggle]").click()
    items = page.locator("[data-testid=qf-notes-tpl-item]")
    assert items.count() == 2
    assert not page.locator("[data-testid=qf-notes-tpl-filter]").is_visible(), "≤10 個不出現篩選"

    items.nth(0).click()                                         # 空框 ⇒ 直接套用、不問
    assert box.input_value() == "範本00 內容\n  - 條列"
    assert not page.locator("[data-testid=qf-notes-tpl-ask]").is_visible()

    items.nth(1).click()                                         # 有內容 ⇒ 先問
    ask = page.locator("[data-testid=qf-notes-tpl-ask]")
    ask.wait_for(state="visible", timeout=5000)
    assert box.input_value() == "範本00 內容\n  - 條列", "沒選之前內容不動"
    page.locator("[data-testid=qf-notes-tpl-append]").click()
    assert box.input_value() == "範本00 內容\n  - 條列\n\n範本01 內容\n  - 條列"
    ask.wait_for(state="hidden", timeout=5000)

    items.nth(0).click()
    page.locator("[data-testid=qf-notes-tpl-replace]").click()
    assert box.input_value() == "範本00 內容\n  - 條列"

    items.nth(1).click()
    ask.get_by_text("取消").click()
    ask.wait_for(state="hidden", timeout=5000)
    assert box.input_value() == "範本00 內容\n  - 條列"


@pytest.mark.e2e
def test_template_filter_only_above_ten(client, live_server, make_user, new_page, login_as):
    sup = make_user(username="xn_e2e_flt", role="superadmin")
    _put_templates(client, _token(client, sup), 12)
    page = new_page()
    login_as(page, sup)
    page.goto(live_server + "/pages/quotation-form.html")
    _wait_form(page)
    page.wait_for_function(f"() => {ROOT}.notesTpls.length === 12", timeout=8000)
    page.locator("[data-testid=qf-notes-tpl-toggle]").click()
    page.locator("[data-testid=qf-notes-tpl-filter]").wait_for(state="visible", timeout=5000)
    assert page.locator("[data-testid=qf-notes-tpl-item]").count() == 12
    page.locator("[data-testid=qf-notes-tpl-search]").fill("範本03")
    assert page.locator("[data-testid=qf-notes-tpl-item]").count() == 1
    page.locator("[data-testid=qf-notes-tpl-search]").fill("")
    page.locator("[data-testid=qf-notes-tpl-filter] button", has_text="AGV").click()
    assert page.locator("[data-testid=qf-notes-tpl-item]").count() == 6      # 奇數編號 6 個
    page.locator("[data-testid=qf-notes-tpl-filter] button", has_text="全部").click()
    assert page.locator("[data-testid=qf-notes-tpl-item]").count() == 12


@pytest.mark.e2e
def test_manage_templates_superadmin_only_and_saves(client, live_server, make_user, new_page, login_as):
    sales = make_user(username="xn_e2e_sales", role="sales")
    p1 = new_page()
    login_as(p1, sales)
    p1.goto(live_server + "/pages/quotation-form.html")
    _wait_form(p1)
    assert not p1.locator("[data-testid=qf-notes-tpl-manage]").is_visible(), "非最高管理者看不到管理入口"

    sup = make_user(username="xn_e2e_mgr", role="superadmin")
    page = new_page()
    login_as(page, sup)
    page.goto(live_server + "/pages/quotation-form.html")
    _wait_form(page)
    page.locator("[data-testid=qf-extra-notes]").fill("要存成範本的內容\n  - 條列")
    page.locator("[data-testid=qf-notes-tpl-manage]").click()
    page.locator("[data-testid=qf-notes-mgr]").wait_for(state="visible", timeout=5000)
    page.get_by_text("以目前備註內容新增").click()
    row = page.locator("[data-testid=qf-notes-mgr-item]").first
    assert row.locator("textarea").input_value() == "要存成範本的內容\n  - 條列"

    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    page.locator("[data-testid=qf-notes-mgr-save]").click()                       # 沒命名 ⇒ 擋下、不打 API
    page.wait_for_timeout(300)
    assert dialogs and "名稱" in dialogs[0], dialogs
    assert client.get("/api/settings/quote-notes-templates", headers=_token(client, sup)).json()["templates"] == []

    row.locator("input").first.fill("我的範本")
    with page.expect_response(lambda r: r.url.endswith("/settings/quote-notes-templates") and r.request.method == "PUT") as ri:
        page.locator("[data-testid=qf-notes-mgr-save]").click()
    assert ri.value.status == 200
    page.locator("[data-testid=qf-notes-mgr]").wait_for(state="hidden", timeout=5000)
    saved = client.get("/api/settings/quote-notes-templates", headers=_token(client, sup)).json()["templates"]
    assert [(t["name"], t["text"]) for t in saved] == [("我的範本", "要存成範本的內容\n  - 條列")]
    assert page.evaluate(f"() => {ROOT}.notesTpls.length") == 1
