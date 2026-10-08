# -*- coding: utf-8 -*-
"""採購單廠商收款帳戶（第 47 班）的瀏覽器 e2e：採購單表單多一塊「廠商收款帳戶」，只在採購單出現；填了就存進單據（銀行＋分行、帳號只留數字、戶名）；
壞帳號在前端就擋（沒打 API）；非金額角色（業務）也能填，但送出後畫面不會回顯完整帳號。"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402
from tests.test_e2e_expense_form_a24_2026_10_01 import _fill, _join_dept, _q, _seed, _wait_done, _x  # noqa: E402

pytestmark = [requires_module("case", "請款＝M01 額外支出"), requires_module("accounting", "費用類別下拉（W4 G2）")]

BLOCK = "[data-testid=pr-po-bank-block]"


def _open(page, live_server, user, kind):
    inject_login(page, live_server, user[0], user[1])
    page.goto(live_server + "/pages/payment-request.html")
    page.wait_for_selector("#pr-type-card", state="visible", timeout=15000)
    page.select_option("#pr-type", kind)


def _fill_bank(page, bank="玉山銀行", branch="台中分行", account="1234-5678 9012", name="甲廠商有限公司"):
    page.fill("[data-testid=pr-po-bank]", bank)
    page.fill("[data-testid=pr-po-branch]", branch)
    page.fill("[data-testid=pr-po-account]", account)
    page.fill("[data-testid=pr-po-account-name]", name)


@pytest.mark.e2e
def test_bank_block_is_only_on_purchase_orders(live_server, make_user, new_context):
    _seed()
    adm = make_user(username="pob_adm0", role="admin")
    page = new_context().new_page()
    _open(page, live_server, adm, "travel")
    page.wait_for_selector("#pr-df .df-root", timeout=15000)
    assert not page.locator(BLOCK).is_visible()
    page.select_option("#pr-type", "purchase_order")
    page.wait_for_selector(BLOCK, state="visible", timeout=15000)


@pytest.mark.e2e
def test_po_saves_the_entered_bank_snapshot_and_bad_account_is_stopped_in_the_browser(live_server, make_user, new_context):
    _seed()
    adm = make_user(username="pob_adm", role="admin")
    mgr = make_user(username="pob_mgr", role="admin")
    _join_dept(adm[0], mgr[0])
    page = new_context().new_page()
    _open(page, live_server, adm, "purchase_order")
    _fill(page)
    _fill_bank(page, account="12AB5678")
    page.click("#pr-t-submit")
    page.wait_for_function("() => { const e = document.getElementById('pr-t-error'); return e && e.offsetParent !== null && e.textContent.trim() }", timeout=10000)
    assert "數字" in page.locator("#pr-t-error").text_content()
    assert not _q("SELECT id FROM case_extra_expenses WHERE kind='purchase_order'"), "前端擋下，沒有打 API"
    page.fill("[data-testid=pr-po-account]", "1234-5678 9012")
    page.click("#pr-t-submit")
    _wait_done(page)
    row = _q("SELECT payee_type, payee_name, payee_bank, payee_account, status FROM case_extra_expenses WHERE kind='purchase_order' ORDER BY id DESC LIMIT 1")[0]
    assert (row["payee_type"], row["payee_name"], row["payee_bank"], row["payee_account"]) == ("vendor", "甲廠商有限公司", "玉山銀行 台中分行", "123456789012")
    assert row["status"] != "草稿"


@pytest.mark.e2e
def test_po_without_bank_entries_still_saves_and_non_money_role_never_sees_the_account_echoed(live_server, make_user, new_context):
    _seed()
    eng = make_user(username="pob_sales", role="sales")
    import json
    mods = json.loads(_q("SELECT modules FROM users WHERE username=?", (eng[0],))[0]["modules"] or "[]")
    _x("UPDATE users SET modules=? WHERE username=?", (json.dumps(sorted(set(mods) | {"expense_forms"})), eng[0]))        # 業務原有權限＋無案件費用單權限（仍然沒有金額權限）
    _join_dept(eng[0], make_user(username="pob_mgr2", role="admin")[0])
    page = new_context().new_page()
    _open(page, live_server, eng, "purchase_order")
    _fill(page)
    page.click("#pr-t-submit")
    _wait_done(page)
    row = _q("SELECT payee_bank, payee_account FROM case_extra_expenses WHERE kind='purchase_order' ORDER BY id DESC LIMIT 1")[0]
    assert (row["payee_bank"], row["payee_account"]) == ("", ""), "沒填就不存（出納會看到『未收集』警示）"
    page = new_context().new_page()                                   # 新分頁＝全新的表單狀態
    _open(page, live_server, eng, "purchase_order")
    _fill(page)
    _fill_bank(page, account="55556666777")
    page.click("#pr-t-submit")
    _wait_done(page)
    assert _q("SELECT payee_account FROM case_extra_expenses WHERE kind='purchase_order' ORDER BY id DESC LIMIT 1")[0]["payee_account"] == "55556666777"
    assert "55556666777" not in page.inner_text("body"), "送出後的畫面（含我的申請）不回顯完整帳號"
