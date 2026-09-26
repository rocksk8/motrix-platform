# -*- coding: utf-8 -*-
"""報價表單的稅別：新單只能選應稅 5%／零稅率／免稅；舊 1～4% 單顯示已停用、存檔前要改選。

使用者（2026-09-24）逐字：「算了會計稅率1~4%取消，直接依法規進行，用現金折讓就好」。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
from datetime import datetime

import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_voucher_preview_export_feedback_2026_09_23 import _login  # noqa: E402,F401
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


def _ready(page):
    page.wait_for_function("() => window.Alpine && document.querySelector('[x-data]')"
                           " && Alpine.$data(document.querySelector('[x-data]')).q", timeout=15000)


def _legacy_quote(no, owner_id):
    import db
    now = datetime.now().isoformat()
    data = {"quoteNo": no, "customerName": "舊客戶", "projectName": "舊專案", "taxRate": 3,
            "quoteDate": "2026-09-01", "validDays": 30, "discount": 0, "freight": 0,
            "items": [{"id": 1, "type": "item", "description": "設備", "qty": 1, "cost": 0,
                       "unitPrice": 10000, "amount": 10000, "margin": 1}]}
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, total, pretax, data_json, created_at, updated_at, "
            "customer_name, sales_person_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (no, "草稿", 10300, 10000, json.dumps(data, ensure_ascii=False), now, now, "舊客戶", owner_id))
        conn.commit()
    finally:
        conn.close()


def _uid(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    finally:
        conn.close()


@pytest.mark.e2e
def test_a_new_quote_offers_only_the_three_legal_tax_types(live_server, make_user, e2e_browser):
    u, pw = make_user(username="alice", role="superadmin")
    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, u, pw)
    page.goto(live_server + "/pages/quotation-form.html")
    _ready(page)
    sel = page.locator("select[data-tax-type]")
    values = sel.evaluate("s => [...s.options].filter(o => o.style.display !== 'none' && !o.disabled)"
                          ".map(o => o.value)")
    assert values == ["taxable", "zero", "exempt"]
    assert sel.input_value() == "taxable"
    # 免稅 ⇒ 稅額 0、合計標籤寫「免稅」
    page.evaluate("() => { const d = Alpine.$data(document.querySelector('[x-data]'));"
                  " d.q.items = [{id: 1, type: 'item', description: 'x', qty: 1, cost: 0, unitPrice: 1000,"
                  " amount: 1000, margin: 1}]; d.calcTotals() }")
    sel.select_option("exempt")
    got = page.evaluate("() => { const d = Alpine.$data(document.querySelector('[x-data]'));"
                        " return {tax: d.tot.tax, rate: d.q.taxRate, type: d.q.taxType, label: d.taxLineLabel()} }")
    assert got == {"tax": 0, "rate": 0, "type": "exempt", "label": "免稅"}
    sel.select_option("taxable")
    assert page.evaluate("() => Alpine.$data(document.querySelector('[x-data]')).tot.tax") == 50


@pytest.mark.e2e
def test_an_old_legacy_rate_quote_is_shown_as_disabled_and_must_be_changed_before_saving(
        live_server, make_user, e2e_browser):
    u, pw = make_user(username="alice", role="superadmin")
    _legacy_quote("MQ-LEG3", _uid("alice"))
    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, u, pw)
    page.goto(live_server + "/pages/quotation-form.html?id=MQ-LEG3")
    page.wait_for_function("() => { const d = window.Alpine && document.querySelector('[x-data]')"
                           " && Alpine.$data(document.querySelector('[x-data]')); return d && d.q.quoteNo === 'MQ-LEG3' }",
                           timeout=15000)
    note = page.locator("[data-legacy-tax]")
    note.wait_for(state="visible", timeout=5000)
    assert "3%" in note.inner_text()
    # 數字維持原樣（不因為打開就被改算）
    assert page.evaluate("() => Alpine.$data(document.querySelector('[x-data]')).tot.tax") == 300

    messages = []
    page.on("dialog", lambda d: (messages.append(d.message), d.dismiss()))
    # PERF #6：原本固定等 500ms ⇒ 等那個提示對話框出現（沒出現就逾時紅，說明在下一行）
    with page.expect_event("dialog", timeout=10000):
        page.evaluate("() => Alpine.$data(document.querySelector('[x-data]')).saveDraft()")
    assert messages and "已停用的稅率" in messages[0], messages

    page.locator("select[data-tax-type]").select_option("taxable")
    note.wait_for(state="hidden", timeout=3000)
    assert page.evaluate("() => Alpine.$data(document.querySelector('[x-data]')).tot.tax") == 500
