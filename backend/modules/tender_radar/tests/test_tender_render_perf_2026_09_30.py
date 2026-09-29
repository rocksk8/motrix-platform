# -*- coding: utf-8 -*-
"""T22-4：標案雷達 500 筆進頁到清單可見的時間（前景頁、真的瀏覽器）。

使用者回報（2026-09-30）：進頁面完全卡死約 6 秒（計數 0→484），再 6～7 秒才出清單，每次都會；後端預先運算已上線
（1.5.1），研判是前端渲染。本題把資料灌到 500 筆／3 條件，量：
  fetch（/tenders 的請求耗時）、長任務總和與最長一段（主執行緒被占住）、進頁到「500 列都畫出來」。
- 量測用**前景頁**：隱藏視窗 rAF 不跑，帶動畫的轉場量不到（記憶〈瀏覽器量測陷阱〉）；這裡是 headless chromium 的前景頁。
- 數字印在 stdout（-s 看得到），並附在 CHANGELOG／回報。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._map_tiles import block_tiles  # noqa: E402
from tests._mapiso import no_tile_probe  # noqa: E402,F401

N = 500
PW = "T-Pass-1234"
BUDGET_SECONDS = 1.5

INIT = """
(() => {
  window.__perf = { longTasks: [], rowsAt: null, N: %d };
  try {
    new PerformanceObserver(l => { for (const e of l.getEntries()) window.__perf.longTasks.push([e.startTime, e.duration]) })
      .observe({ entryTypes: ['longtask'] });
  } catch (e) {}
  const check = () => {
    if (window.__perf.rowsAt !== null) return;
    const n = document.querySelectorAll('table[data-layout-list=tenders] tbody tr').length;
    if (n >= window.__perf.N) window.__perf.rowsAt = performance.now();
  };
  new MutationObserver(check).observe(document, { childList: true, subtree: true });
})();
""" % N


def _seed():
    import db
    conn = db.get_db()
    try:
        for i in range(N):
            kw = ("監視器", "門禁", "網路")[i % 3] if i % 2 == 0 else "其他"
            conn.execute(
                "INSERT INTO tenders (case_no, name, org, location, published_at, deadline, budget, url, fetched_at) "
                "VALUES (?, ?, ?, '台中市', ?, ?, ?, ?, '2026-09-30')",
                ("PERF-%04d" % i, "%s採購案第%d號" % (kw, i), "臺中市第%d機關" % (i % 40), "2026-09-2%d" % (i % 9), "2026-10-1%d" % (i % 9),
                 (i * 1000) if i % 5 else None, "https://web.pcc.gov.tw/x/%d" % i))
        for name, kw in (("監視", "監視器"), ("門禁", "門禁"), ("網路", "網路")):
            conn.execute("INSERT INTO tender_watches (name, keywords, excludes, org, budget_min, budget_max, enabled, created_at, updated_at) "
                         "VALUES (?, ?, '[]', '', NULL, NULL, 1, '2026-09-30T00:00:00', '2026-09-30T00:00:00')",
                         (name, json.dumps([kw], ensure_ascii=False)))
        conn.commit()
    finally:
        conn.close()


def measure(live_server, make_user, e2e_browser):
    make_user("perfuser", PW, role="superadmin")
    _seed()
    ctx = e2e_browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    block_tiles(page)
    page.add_init_script(INIT)
    inject_login(page, live_server, "perfuser", PW)
    page.goto(live_server + "/pages/tender-radar.html", wait_until="commit")
    page.wait_for_function("() => window.__perf && window.__perf.rowsAt !== null", timeout=60000)
    r = page.evaluate("""() => {
      const res = performance.getEntriesByType('resource').filter(e => e.name.includes('/api/tender-radar/tenders'))[0];
      const lt = window.__perf.longTasks;
      return { rowsAtMs: window.__perf.rowsAt,
               fetchMs: res ? res.responseEnd - res.startTime : null,
               fetchDoneAt: res ? res.responseEnd : null,
               longTaskTotalMs: lt.reduce((a, x) => a + x[1], 0),
               longTaskMaxMs: lt.reduce((a, x) => Math.max(a, x[1]), 0), longTasks: lt.length,
               domNodes: document.getElementsByTagName('*').length }
    }""")
    ctx.close()
    return r


def test_500_tenders_visible_within_budget(live_server, make_user, no_tile_probe, e2e_browser):
    r = measure(live_server, make_user, e2e_browser)
    print("\nPERF %s" % json.dumps(r, ensure_ascii=False))
    assert r["rowsAtMs"] / 1000 < BUDGET_SECONDS, r


def test_cells_are_escaped_and_only_http_links_are_made(live_server, make_user, no_tile_probe, e2e_browser):
    """整格 x-html 的前提：抓來的資料一律跳脫；非 http(s) 的網址不產生 <a>（純文字）。"""
    import db
    make_user("perfuser2", PW, role="superadmin")
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO tenders (case_no, name, org, location, url, fetched_at) VALUES "
                     "('X-1', '<img src=x onerror=\"window.__pwned=1\">名稱', '機關&<b>粗</b>', '台中市', 'javascript:window.__pwned=2', '2026-09-30')")
        conn.execute("INSERT INTO tenders (case_no, name, org, location, url, fetched_at) VALUES "
                     "('X-2', '正常', '正常機關', '台中市', 'https://web.pcc.gov.tw/ok', '2026-09-30')")
        conn.commit()
    finally:
        conn.close()
    page = e2e_browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
    block_tiles(page)
    inject_login(page, live_server, "perfuser2", PW)
    page.goto(live_server + "/pages/tender-radar.html")
    page.wait_for_function("() => document.querySelectorAll('table[data-layout-list=tenders] tbody tr').length >= 2", timeout=20000)
    assert page.evaluate("() => window.__pwned") is None
    bad = page.locator('tr[data-case-no="X-1"]')
    assert bad.locator("img").count() == 0 and bad.locator("a[href^='javascript']").count() == 0
    assert bad.locator("a[target=_blank]").count() == 0                       # 非 http(s) ⇒ 純文字
    assert "<b>粗</b>" in bad.inner_text() and "<img" in bad.inner_text()
    ok = page.locator('tr[data-case-no="X-2"] a[target=_blank]')
    assert ok.count() == 2 and all("noopener" in (ok.nth(i).get_attribute("rel") or "") for i in range(2))
