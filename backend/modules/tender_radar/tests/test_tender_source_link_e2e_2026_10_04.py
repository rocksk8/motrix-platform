# -*- coding: utf-8 -*-
"""2026-10-04 標案雷達：每一列都有看得見的「前往來源網站明細」連結（新分頁、rel noopener）；地點／招標方式顯示「未取得」時附一句怎麼辦。
使用者裁示：來源網站的驗證碼由人處理，系統不自動破解——所以頁面只負責把人帶到官方明細頁、並說清楚為什麼這兩欄是空的。"""
import datetime

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._map_tiles import block_tiles  # noqa: E402
from tests._mapiso import no_tile_probe  # noqa: E402,F401

PW = "N-Pass-123"
HELP = "地點與招標方式需在來源網站通過驗證碼後查看"


def _seed():
    import db
    today = datetime.date.today().isoformat()
    conn = db.get_db()
    try:
        for no, name, url, loc, method in (
                ("N-1", "地點方式都有的標案", "https://web.pcc.gov.tw/prkms/urlSelector/common/tpam?pk=N1", "台中市", "公開招標"),
                ("N-2", "地點方式都沒拿到的標案", "https://web.pcc.gov.tw/prkms/urlSelector/common/tpam?pk=N2", None, None),
                ("N-3", "只缺招標方式的標案", "https://web.pcc.gov.tw/prkms/urlSelector/common/tpam?pk=N3", "高雄市", None),
                ("N-4", "沒有來源網址的標案", None, "新北市", "限制性招標")):
            conn.execute("INSERT INTO tenders (case_no, name, org, location, tender_method, url, fetched_at) VALUES (?,?,?,?,?,?,?)",
                         (no, name, "機關" + no, loc, method, url, today))
        conn.commit()
    finally:
        conn.close()


@pytest.mark.e2e
def test_every_row_has_a_visible_source_link_and_missing_cells_say_what_to_do(live_server, make_user, e2e_browser, no_tile_probe):
    make_user(username="n_boss", password=PW, role="superadmin")
    _seed()
    page = e2e_browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
    block_tiles(page)
    inject_login(page, live_server, "n_boss", PW)
    page.goto(live_server + "/pages/tender-radar.html")
    page.wait_for_selector('tr[data-case-no="N-1"]', timeout=20000)
    row = lambda no: page.locator('tr[data-case-no="%s"]' % no)   # noqa: E731
    for no in ("N-1", "N-2", "N-3"):
        a = row(no).locator("a[data-source-link]")
        assert a.count() == 1, "%s 沒有（或重複了）來源網站連結" % no
        assert a.is_visible() and a.inner_text().strip() == "前往來源網站明細"
        assert a.get_attribute("target") == "_blank" and "noopener" in (a.get_attribute("rel") or "")
        assert a.get_attribute("href").startswith("https://web.pcc.gov.tw/") and a.get_attribute("href").endswith("pk=" + no.replace("-", ""))
    # 沒有網址的那一列：不放連結，但不留空白——明講「來源網址未取得」
    assert row("N-4").locator("a[data-source-link]").count() == 0
    assert "來源網址未取得" in row("N-4").locator("[data-source-link-missing]").inner_text()
    # 說明文字：只出現在「未取得」的格子，且一格一句
    assert row("N-1").locator("[data-captcha-help]").count() == 0
    assert row("N-4").locator("[data-captcha-help]").count() == 0
    assert row("N-2").locator("[data-captcha-help]").count() == 2                           # 地點＋招標方式都缺
    assert row("N-3").locator("[data-captcha-help]").count() == 1                           # 只缺招標方式
    for h in row("N-2").locator("[data-captcha-help]").all():
        assert h.is_visible() and h.inner_text().strip() == HELP
    assert row("N-2").locator("[data-location-missing]").inner_text().strip() == "未取得"
    assert row("N-2").locator("[data-method-missing]").inner_text().strip() == "未取得"
    assert row("N-3").locator("[data-method-missing]").count() == 1 and row("N-3").locator("[data-location-missing]").count() == 0
    assert "公開招標" in row("N-1").inner_text() and "限制性招標" in row("N-4").inner_text()
