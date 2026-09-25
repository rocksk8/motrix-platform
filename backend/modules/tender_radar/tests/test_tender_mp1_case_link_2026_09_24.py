"""（自 tests/test_mp1_map_points_link_to_records_2026_09_24.py 拆出，2026-09-25）MP1：標案雷達頁的 `?case=` 深連結。

`?case=` ⇒ 那一列被標示，並有「在地圖上看」回地圖的連結。地圖端（M08）的其餘頁面留在原檔。
"""
import pytest

pw = pytest.importorskip("playwright.sync_api")

from tests._map_tiles import block_tiles  # noqa: E402
from tests.test_mp1_map_points_link_to_records_2026_09_24 import _geo  # noqa: E402,F401  （fixture）
from tests.test_voucher_preview_export_feedback_2026_09_23 import _login  # noqa: E402


@pytest.mark.e2e
def test_tender_case_link_marks_the_row_and_links_back(live_server, make_user, _geo, e2e_browser):
    # 原 MP1 的一部分（編號由 tests/test_mp1_… 承擔，這裡不重複認領）。
    # `_geo`：標案雷達頁會畫自己的小地圖，後端會探測圖磚——換掉，不對外連線（NETGUARD）。
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO tenders (case_no, name, org, location, fetched_at)"
                     " VALUES ('MP1-T-9', 'MP1標案', 'MP1機關', '台中市', '2026-09-24')")
        # 第二筆：「只有那一列被標示」要有別列可以比（只有一列時「全部標示」也會過——突變 M5 抓到）。
        conn.execute("INSERT INTO tenders (case_no, name, org, location, fetched_at)"
                     " VALUES ('MP1-T-8', 'MP1別的標案', 'MP1機關', '台中市', '2026-09-24')")
        conn.commit()
    finally:
        conn.close()
    u, p = make_user(username="mp1_tender", role="superadmin")
    page = e2e_browser.new_page(viewport={"width": 1366, "height": 900})
    block_tiles(page)   # 地圖圖磚不連外（conftest._browser_netguard）
    _login(page, live_server, u, p)
    # 標案雷達：`?case=` ⇒ 那一列被標示並有回地圖的連結。
    page.goto(live_server + "/pages/tender-radar.html?case=MP1-T-9")
    page.wait_for_function(
        "() => { const r = document.querySelector('tr[data-case-no=\"MP1-T-9\"]');"
        " return r && r.style.outline.indexOf('2px') >= 0 }", timeout=15000)
    href = page.locator('tr[data-case-no="MP1-T-9"] a.mp1-onmap').get_attribute("href")
    assert href == "map.html?focus=tenders%3AMP1-T-9", href
    other = page.locator("tr[data-case-no]").evaluate_all(
        "els => els.filter(e => e.style.outline).map(e => e.dataset.caseNo)")
    rows_n = page.locator("tr[data-case-no]").count()
    assert rows_n >= 2 and other == ["MP1-T-9"], "只有那一列被標示（共 %d 列）：%r" % (rows_n, other)
