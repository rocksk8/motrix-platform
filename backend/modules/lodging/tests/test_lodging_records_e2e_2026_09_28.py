# -*- coding: utf-8 -*-
"""附近旅宿紀錄頁（瀏覽器）：顯名在紀錄明細與比較頁都看得到、年份取資料日期（LG-S2）；
Google 中心點說明與「不保存」距離；錯值價格灰字原值（LG-S4）；官方登記未變動（LG-S1）；
沒有資料時說出來；新增詢價後明細顯示。驗 DOM 終點狀態，不驗 Alpine 模型（PLAYBOOK §G5 #9）。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from modules.lodging import search as lsearch  # noqa: E402
from modules.lodging import source as ls  # noqa: E402
from modules.lodging.tests import _fixtures as fx  # noqa: E402

C_LAT, C_LNG = 24.1372, 120.6867


def _seed_catalog(hotels, update=fx.DATASET_UPDATE):
    import db
    conn = db.get_db()
    try:
        ls.replace_catalog(conn, ls.parse_dataset(fx.dataset(hotels, update))["rows"])
    finally:
        conn.close()


def _save(username, source, label):
    """直接以模組函式存一筆紀錄（與端點同一支 save_search）。"""
    import db
    conn = db.get_db()
    try:
        cat = ls.catalog_state(conn)
        items = lsearch.nearby(conn, C_LAT, C_LNG, 3000)
        center = {"kind": "address", "label": label, "lat": C_LAT, "lng": C_LNG, "source": source,
                  "precision": "street"}
        rid = lsearch.save_search(conn, user={"username": username}, center=center, radius_m=3000,
                                  kinds=["hotel", "homestay"], sort="distance", items=items,
                                  dataset_updated_at=cat["dataset_updated_at"])
        conn.commit()
        return rid
    finally:
        conn.close()


def _open(live_server, new_page, login_as, user):
    page = new_page()
    login_as(page, tuple(user)[:2])
    with page.expect_response(lambda r: "/api/lodging/records" in r.url, timeout=20000):
        page.goto(f"{live_server}/pages/lodging-records.html")
    return page


@pytest.mark.e2e
def test_detail_and_compare_show_attribution_google_note_and_suspect_price(live_server, make_user, new_page, login_as):
    user = make_user(username="e2e_lodg_a", role="superadmin")
    _seed_catalog([fx.hotel(1, lat=C_LAT + 0.001, lng=C_LNG, low=2000, high=3000),
                   fx.hotel(2, lat=C_LAT + 0.002, lng=C_LNG, low=5, high=3000)])
    r_google = _save("e2e_lodg_a", "google", "測試路1號")
    r_free = _save("e2e_lodg_a", "nominatim", "測試路2號")
    page = _open(live_server, new_page, login_as, user)

    page.locator("tr[data-record-id='%d'] [data-lodging-open]" % r_google).click()
    detail = page.locator("[data-lodging-detail]")
    note = detail.locator("[data-lodging-google-note]")
    note.wait_for(state="visible", timeout=10000)
    assert "不保存座標與距離" in note.inner_text()
    row1 = detail.locator("tr[data-source-id='Hotel_TEST_000001']")
    assert "不保存" in row1.inner_text()
    assert "業者登記於 2026-07" in row1.inner_text()
    sus = detail.locator("tr[data-source-id='Hotel_TEST_000002'] [data-lodging-suspect]")
    assert sus.is_visible() and "官方登記值：5～3,000 元" in sus.inner_text()
    attr = detail.locator("[data-lodging-attribution]")
    assert attr.is_visible()
    assert "交通部觀光署 2026 旅館民宿 - 觀光資訊資料庫" in attr.inner_text()
    assert "https://data.gov.tw/license" in attr.inner_text()

    # 比較：換一批 2027 的資料再存一筆 ⇒ 兩個年份都在顯名裡；沒變的那家標「官方登記未變動」
    _seed_catalog([fx.hotel(1, lat=C_LAT + 0.001, lng=C_LNG, low=2000, high=3000)],
                  update="2027-01-02T10:00:00+08:00")
    r_new = _save("e2e_lodg_a", "nominatim", "測試路3號")
    page.reload()
    page.locator("tr[data-record-id='%d']" % r_new).wait_for(state="visible", timeout=10000)
    page.locator("tr[data-record-id='%d'] input[type=checkbox]" % r_free).check()
    page.locator("tr[data-record-id='%d'] input[type=checkbox]" % r_new).check()
    page.locator("[data-lodging-compare-btn]").click()
    cmp = page.locator("[data-lodging-compare]")
    cmp.locator("tr[data-source-id='Hotel_TEST_000001']").wait_for(state="visible", timeout=10000)
    assert cmp.locator("tr[data-source-id='Hotel_TEST_000001'] [data-lodging-cmp-note]").inner_text() == "官方登記未變動"
    assert cmp.locator("tr[data-source-id='Hotel_TEST_000002'] [data-lodging-cmp-note]").inner_text() == "只在 A"
    cattr = cmp.locator("[data-lodging-attribution]").inner_text()
    assert "交通部觀光署 2026、2027" in cattr


@pytest.mark.e2e
def test_no_catalog_is_said_not_shown_as_empty(live_server, make_user, new_page, login_as):
    user = make_user(username="e2e_lodg_b", role="sales", modules=["lodging"])
    page = _open(live_server, new_page, login_as, user)
    msg = page.locator("[data-lodging-no-catalog]")
    msg.wait_for(state="visible", timeout=10000)
    assert "尚未下載旅宿資料" in msg.inner_text() and "最高管理者" in msg.inner_text()
    assert page.locator("[data-lodging-refresh]").count() == 0          # 非最高管理者沒有更新鈕
    assert page.locator("[data-lodging-empty]").is_visible()


@pytest.mark.e2e
def test_quote_saved_from_detail_shows_as_latest(live_server, make_user, new_page, login_as):
    user = make_user(username="e2e_lodg_c", role="sales", modules=["lodging"])
    _seed_catalog([fx.hotel(1, lat=C_LAT + 0.001, lng=C_LNG)])
    rid = _save("e2e_lodg_c", "device", "目前位置")
    page = _open(live_server, new_page, login_as, user)
    page.locator("tr[data-record-id='%d'] [data-lodging-open]" % rid).click()
    row = page.locator("[data-lodging-detail] tr[data-source-id='Hotel_TEST_000001']")
    row.wait_for(state="visible", timeout=10000)
    row.locator("[data-lodging-quote-open]").click()
    form = page.locator("[data-lodging-quote-form]")
    form.locator("[data-q=roomType]").fill("雙人房")
    form.locator("[data-q=price]").fill("2800")
    with page.expect_response(lambda r: "/api/lodging/quotes" in r.url and r.request.method == "POST", timeout=10000):
        form.locator("[data-lodging-quote-save]").click()
    page.wait_for_function(
        "() => (document.querySelector(\"[data-lodging-detail] tr[data-source-id='Hotel_TEST_000001']\")"
        " || {}).innerText && document.querySelector(\"[data-lodging-detail] tr[data-source-id='Hotel_TEST_000001']\")"
        ".innerText.includes('2,800 元')", timeout=10000)
    assert "雙人房" in row.inner_text() and "電話" in row.inner_text()
    assert len(fx.rows("SELECT * FROM lodging_quotes WHERE entered_by='e2e_lodg_c'")) == 1
