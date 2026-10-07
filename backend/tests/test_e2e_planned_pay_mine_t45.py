# -*- coding: utf-8 -*-
"""第 45 班 S2：「我的申請」預定付款日——核准後本人可補填、重新載入仍在；已付款（歷史）唯讀；已作廢唯讀。斷言實際輸入框的值與文字。"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402

pytestmark = [requires_module("case", "支出申請＝M01 額外支出")]

NO = "MQ-PPM-001"


def _db(sql, args=(), fetch=False):
    import db
    conn = db.get_db()
    try:
        cur = conn.execute(sql, args)
        conn.commit()
        return cur.fetchall() if fetch else cur.lastrowid
    finally:
        conn.close()


@pytest.mark.e2e
def test_mine_planned_pay_date_set_reload_and_readonly(live_server, make_user, new_context, seed_extra_expense):
    eng = make_user(username="ppm_eng", role="sales")
    eng_id = _db("SELECT id FROM users WHERE username=?", (eng[0],), fetch=True)[0]["id"]
    _db("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
        " deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (NO, "已送出", "預定客戶", "機房", 100000, 95238, json.dumps({"dealTag": "已成案"}), "2026-01-01T00:00:00",
         "2026-01-01T00:00:00", "已成案", "", json.dumps([eng_id])))
    ok = seed_extra_expense(NO, total_cost=500, description="可改-核准未付", status="已核准")
    paid = seed_extra_expense(NO, total_cost=500, description="已付款", status="已核准")
    void = seed_extra_expense(NO, total_cost=500, description="已作廢", status="已作廢")
    for i in (ok, paid, void):
        _db("UPDATE case_extra_expenses SET created_by=? WHERE id=?", (eng[0], i))
    _db("UPDATE case_extra_expenses SET paid_date='2031-06-02', planned_pay_date='2031-06-01' WHERE id=?", (paid,))
    page = new_context().new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, eng[0], eng[1])
    page.goto(live_server + "/pages/payment-request.html?tab=mine")
    page.wait_for_selector('#pr-mine[data-loaded="1"]')

    inp = page.locator('[data-testid="pr-mine-planned-%d"]' % ok)
    assert inp.input_value() == ""
    assert page.locator('[data-testid="pr-mine-planned-save-%d"]' % ok).is_disabled()          # 沒改動不能存
    inp.fill("2031-07-15")
    page.locator('[data-testid="pr-mine-planned-save-%d"]' % ok).click()
    page.wait_for_function("() => /已儲存預定付款日/.test(document.querySelector('#pr-mine-result').innerText)")
    assert _db("SELECT planned_pay_date FROM case_extra_expenses WHERE id=?", (ok,), fetch=True)[0][0] == "2031-07-15"
    page.reload()
    page.wait_for_selector('#pr-mine[data-loaded="1"]')
    assert page.locator('[data-testid="pr-mine-planned-%d"]' % ok).input_value() == "2031-07-15"   # 重新載入仍在

    # 清除
    page.locator('[data-testid="pr-mine-planned-%d"]' % ok).fill("")
    page.locator('[data-testid="pr-mine-planned-save-%d"]' % ok).click()
    page.wait_for_function("() => /（清除）/.test(document.querySelector('#pr-mine-result').innerText)")
    assert _db("SELECT planned_pay_date FROM case_extra_expenses WHERE id=?", (ok,), fetch=True)[0][0] == ""

    # 已付款：唯讀、顯示歷史值；已作廢：唯讀
    assert page.locator('[data-testid="pr-mine-planned-%d"]' % paid).count() == 0
    assert page.locator('[data-testid="pr-mine-planned-ro-%d"]' % paid).inner_text() == "2031-06-01"
    assert page.locator('[data-testid="pr-mine-planned-%d"]' % void).count() == 0
    assert page.locator('[data-testid="pr-mine-planned-ro-%d"]' % void).inner_text() == "—"
    assert not errors, errors
