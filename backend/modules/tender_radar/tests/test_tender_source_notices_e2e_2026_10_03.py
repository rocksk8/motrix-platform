# -*- coding: utf-8 -*-
"""2026-10-03 標案雷達頁的來源網站狀態與「未取得」——真瀏覽器：狀態列各自一句話、地點為 NULL 顯示「未取得」。

斷言打在畫面上的終點狀態（等 data-source-notice／表格列出現，不用 sleep）。今天是不是不寄信日取決於真實時鐘，
所以這裡不斷言「今天不寄信」那一句（API 層的測試用注入日期驗過）。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._map_tiles import block_tiles  # noqa: E402
from tests._mapiso import no_tile_probe  # noqa: E402,F401

PW = "N-Pass-123"


def _seed():
    import db
    import modules.tender_radar.source as ts
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO tenders (case_no, name, org, location, fetched_at) VALUES ('N-1','有地點的標案','機關甲','台中市','2026-10-03')")
        conn.execute("INSERT INTO tenders (case_no, name, org, location, fetched_at) VALUES ('N-2','沒拿到地點的標案','機關乙',NULL,'2026-10-03')")
        conn.execute("INSERT INTO tender_watches (name, keywords, excludes, org, budget_min, budget_max, enabled, created_at, updated_at) "
                     "VALUES ('N條件', ?, '[]', '', NULL, NULL, 1, '2026-10-03T00:00:00', '2026-10-03T00:00:00')",
                     (json.dumps(["標案"], ensure_ascii=False),))
        ts._log_fetch(conn, 1, 9, "", suspected=1)
        ts._save_scan_state(conn, list="format_changed", detail="captcha", parsed=1, dropped=9, scan_at="2026-10-03T09:00:00")
        conn.commit()
    finally:
        conn.close()


@pytest.mark.e2e
def test_page_states_the_source_problems_and_marks_a_missing_location(live_server, make_user, e2e_browser, no_tile_probe):
    make_user(username="n_boss", password=PW, role="superadmin")
    _seed()
    page = e2e_browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
    block_tiles(page)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, "n_boss", PW)
    page.goto(live_server + "/pages/tender-radar.html")
    page.wait_for_selector('[data-source-notice="format_changed"]', timeout=20000)
    fmt = page.locator('[data-source-notice="format_changed"]').inner_text()
    cap = page.locator('[data-source-notice="detail_captcha"]').inner_text()
    assert "來源網站格式異動" in fmt and "解析失敗 9 筆" in fmt and "不是「沒有符合的標案」" in fmt
    assert "驗證碼" in cap and "未取得" in cap
    assert page.locator('[data-source-notice="empty_day"]').count() == 0
    # 兩句不同的話，不合併
    assert fmt != cap
    # 地點：有值的照常；NULL 的明講「未取得」（不是空白、不是破折號）
    page.wait_for_function("() => document.querySelectorAll('[data-location-missing]').length >= 1")
    assert page.locator('[data-location-missing]').first.inner_text().strip() == "未取得"
    body = page.locator("table[data-layout-list=tenders] tbody").inner_text()
    assert "台中市" in body
    # 不斷言 pageerror 為空：測試環境的側欄／選單腳本會丟與本頁功能無關的 `Cannot read properties of null (reading 'office'…)`
    # （既有的 tender e2e 同樣不檢查）。只確認沒有跟本題相關的錯誤字樣。
    assert not [e for e in errors if 'notices' in e or 'status' in e], errors
