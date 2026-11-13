"""2026-11-13：估價單的前端（真瀏覽器）——開單頁類型切換會重新取號（ME 字首、與報價單 MQ 各自獨立），
清單頁有「新增估價單」、類型標籤與類型篩選。API 面的行為見 test_estimate_doc_type_2026_11_13.py。"""
import json

import pytest

from tests._requires import requires_module  # noqa: E402

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

pytestmark = requires_module("case", "本檔的題打 M01（案件）的頁面與資料")

_MAKE_USER_DEFAULT_ROLE = "superadmin"


def _seed_two():
    import db
    conn = db.get_db()
    try:
        for no, dt, cust in (("MQ-202611-901", "quote", "報價客戶甲"), ("ME-202611-901", "estimate", "估價客戶乙")):
            conn.execute(
                "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
                " created_at, updated_at, quote_date, doc_type) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (no, "已送出", cust, "專案", 1000, 952, json.dumps({"docType": dt}, ensure_ascii=False),
                 "2026-11-13T00:00:00", "2026-11-13T00:00:00", "2026-11-13", dt))
        conn.commit()
    finally:
        conn.close()


@pytest.mark.e2e
def test_form_toggle_switches_number_prefix_and_label(live_server, make_user, e2e_browser):
    u = make_user(username="est_ui_form")
    page = e2e_browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
    inject_login(page, live_server, *u)
    page.goto(f"{live_server}/pages/quotation-form.html")
    page.wait_for_selector("[data-testid=qf-doc-type]", timeout=20000)
    no = 'input.form-input.readonly[readonly]'
    page.wait_for_function("(s) => [...document.querySelectorAll(s)].some(e => /^MQ-/.test(e.value))", arg=no, timeout=15000)
    page.click("[data-testid=qf-doc-type-estimate]")
    page.wait_for_function("(s) => [...document.querySelectorAll(s)].some(e => /^ME-/.test(e.value))", arg=no, timeout=15000)
    assert "估價單" in page.title()
    page.click("[data-testid=qf-doc-type-quote]")
    page.wait_for_function("(s) => [...document.querySelectorAll(s)].some(e => /^MQ-/.test(e.value))", arg=no, timeout=15000)
    assert "報價單" in page.title()


@pytest.mark.e2e
def test_new_estimate_link_from_list_opens_form_as_estimate(live_server, make_user, e2e_browser):
    u = make_user(username="est_ui_link")
    page = e2e_browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
    inject_login(page, live_server, *u)
    page.goto(f"{live_server}/pages/quotations.html")
    page.wait_for_selector("[data-testid=ql-new-estimate]", timeout=20000)
    page.click("[data-testid=ql-new-estimate]")
    page.wait_for_function("() => { return [...document.querySelectorAll('input.form-input.readonly[readonly]')].some(e => /^ME-/.test(e.value)) }", timeout=20000)
    assert "估價單" in page.title()


@pytest.mark.e2e
def test_list_shows_tag_and_filters_by_type(live_server, make_user, e2e_browser):
    u = make_user(username="est_ui_list")
    _seed_two()
    page = e2e_browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
    inject_login(page, live_server, *u)
    page.goto(f"{live_server}/pages/quotations.html")
    page.wait_for_selector("[data-testid=ql-filter-doctype]", timeout=20000)
    page.wait_for_function("() => document.body.innerText.includes('ME-202611-901') && document.body.innerText.includes('MQ-202611-901')", timeout=20000)
    assert page.locator("[data-testid=ql-doctype-tag]").count() == 1, "只有估價單帶「估價單」標籤"
    page.select_option("[data-testid=ql-filter-doctype]", "estimate")
    page.wait_for_function("() => !document.body.innerText.includes('MQ-202611-901') && document.body.innerText.includes('ME-202611-901')", timeout=5000)
    page.select_option("[data-testid=ql-filter-doctype]", "quote")
    page.wait_for_function("() => document.body.innerText.includes('MQ-202611-901') && !document.body.innerText.includes('ME-202611-901')", timeout=5000)


@pytest.mark.e2e
def test_doc_skin_keeps_user_entered_text_that_contains_the_old_word(live_server, make_user, e2e_browser):
    """審查 L3：估價單頁面把寫死的「報價單」換成「估價單」，但使用者自己輸入的內容（客戶名等）要原樣保留。"""
    u = make_user(username="est_ui_skin")
    page = e2e_browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
    inject_login(page, live_server, *u)
    page.goto(f"{live_server}/pages/quotation-form.html?type=estimate")
    page.wait_for_selector("[data-testid=qf-doc-type]", timeout=20000)
    page.wait_for_function("() => { return [...document.querySelectorAll('input.form-input.readonly[readonly]')].some(e => /^ME-/.test(e.value)) }", timeout=20000)
    res = page.evaluate("""() => {
      const el = document.querySelector('[x-data]'); const d = Alpine.$data(el)
      d.q.customerName = '報價單設計有限公司'
      const user = document.createElement('div'); user.id = 'skin-user'; user.textContent = '客戶：報價單設計有限公司'
      const sys = document.createElement('div'); sys.id = 'skin-sys'; sys.textContent = '請確認報價單內容'
      document.body.appendChild(user); document.body.appendChild(sys)
      return new Promise(r => setTimeout(() => r({ user: user.textContent, sys: sys.textContent }), 400))
    }""")
    assert res["user"] == "客戶：報價單設計有限公司", "使用者輸入的內容不可被換字：%r" % res["user"]
    assert res["sys"] == "請確認估價單內容", "系統寫死的用語要換成估價單：%r" % res["sys"]
