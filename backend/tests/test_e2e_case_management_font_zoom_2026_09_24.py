# -*- coding: utf-8 -*-
"""字級「特」：案件管理頁的左側案件清單與右側明細，底邊在畫面內、而且真的捲得到最後一筆。

使用者最初的原話：「部分使用者在字型用特大情況下，**左右列表會無法閱讀**」——案件管理正是
左右列表的頁面。靜態守門（`test_fz_no_raw_vh_is_left_in_the_frontend`）只證明沒有裸的 vh，
**證明不了畫面上真的看得到**（A 裁示加這一支）。

⚙️ 1366×768、字級 1.3（特）；對照組：字級 1.0（標）同樣要過。
⚙️ 「看得到最後一筆」＝把可捲動區捲到底之後，最後一個元素的底邊 ≤ 視窗高、頂邊 ≥ 0。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_voucher_preview_export_feedback_2026_09_23 import (  # noqa: E402,F401
    _login)

#: O5-S1：本檔量版面／字級（getBoundingClientRect 等）⇒ 要真字型，不吃 conftest 的字型替身
pytestmark = pytest.mark.real_fonts

W, H = 1366, 768
N_CASES = 40


def _seed_cases():
    import db
    conn = db.get_db()
    try:
        for i in range(N_CASES):
            qn = "MQ-FZCM-%03d" % i
            conn.execute(
                "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax,"
                " data_json, created_at, updated_at, deal_tag, quote_date)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (qn, "已送出", "字級客戶%02d" % i, "字級專案%02d" % i, 100000, 95238,
                 json.dumps({"dealTag": "已成案", "caseRecord": {
                     "payment": {"items": []}, "materials": [],
                     "stages": [{"label": "訂單確認"}]}}, ensure_ascii=False),
                 "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "2026-08-01"))
        conn.commit()
    finally:
        conn.close()


_MEASURE = """sel => {
    const box = document.querySelector(sel);
    if (!box) return null;
    box.scrollTop = box.scrollHeight;
    const r = box.getBoundingClientRect();
    const kids = Array.from(box.querySelectorAll(':scope > *')).filter(e => e.offsetParent !== null);
    const last = kids.length ? kids[kids.length - 1] : null;
    const lr = last ? last.getBoundingClientRect() : null;
    return {bottom: r.bottom, height: r.height, scrollable: box.scrollHeight > box.clientHeight,
            lastTop: lr ? lr.top : null, lastBottom: lr ? lr.bottom : null, ih: innerHeight};
}"""


def _measure(browser, zoom, live_server, make_user, uname):
    _seed_cases()
    u, p = make_user(username=uname, role="superadmin")
    page = browser.new_page(viewport={"width": W, "height": H})
    page.add_init_script("localStorage.setItem('motrix_font_zoom', '%s')" % zoom)
    _login(page, live_server, u, p)
    page.goto(live_server + "/pages/case-management.html")
    page.wait_for_function("n => document.querySelectorAll('.cm-card').length >= n",
                           arg=N_CASES, timeout=20000)
    page.wait_for_timeout(300)
    lst = page.evaluate(_MEASURE, ".cm-list__body")
    page.locator(".cm-card").first.click()
    page.locator(".cm-body").first.wait_for(state="visible", timeout=15000)
    page.wait_for_timeout(500)
    det = page.evaluate(_MEASURE, ".cm-body")
    return lst, det


def _check(zoom, lst, det):
    print("字級 %.2f 案件管理實測：清單 %r／明細 %r" % (zoom, lst, det))
    assert lst and lst["scrollable"], "量尺：清單沒有長到需要捲動（%r）——量不到「捲到底看得到嗎」" % lst
    assert lst["bottom"] <= H + 1, "字級 %.2f：左側案件清單底邊 %.0f 超出畫面 %d" % (zoom, lst["bottom"], H)
    assert lst["lastBottom"] <= H + 1 and lst["lastTop"] >= 0, (
        "字級 %.2f：清單捲到底之後，最後一筆（%.0f～%.0f）不在畫面內" % (zoom, lst["lastTop"], lst["lastBottom"]))
    assert det and det["bottom"] <= H + 1, "字級 %.2f：右側明細底邊 %.0f 超出畫面 %d" % (zoom, det["bottom"], H)
    assert det["lastBottom"] is None or det["lastBottom"] <= H + 1, (
        "字級 %.2f：明細捲到底之後，最後一塊（底邊 %.0f）不在畫面內" % (zoom, det["lastBottom"]))


@pytest.mark.e2e
def test_fz_case_management_lists_fit_and_scroll_to_the_end_at_the_largest_size(
        live_server, make_user, e2e_browser):
    lst, det = _measure(e2e_browser, 1.3, live_server, make_user, "fzcm_13")
    _check(1.3, lst, det)


@pytest.mark.e2e
def test_fz_case_management_lists_fit_at_the_standard_size(live_server, make_user, e2e_browser):
    """對照組：「標」字級同樣要過（不是只有「特」被特別處理）。"""
    lst, det = _measure(e2e_browser, 1.0, live_server, make_user, "fzcm_10")
    _check(1.0, lst, det)
