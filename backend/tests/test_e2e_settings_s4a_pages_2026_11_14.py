"""瀏覽器端對端：設定矩陣 S4a 各頁（2026-11-14；S2-PAGE-CONTRACT §4「e2e 一題」）。

S4a 只補資料（白話名稱、「什麼時候用」），不改鍵、預設、範圍、風險。這一題逐頁開啟：
- 該頁每個群組的每個欄位都有一列（以後端 `/api/settings-center/groups/<g>` 回傳的欄位為準）；
- 每一列的顯示名稱不是內部欄位代碼，也不為空；
（可批次格子與清單一致由 `gen_seed.py --check` 守門，不在這一題。）
觀測點打在元件狀態與後端回傳，不打頁面寫死的文字。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

# S4a 各頁的代表群組（頁面＝這些群組所在的頁）
BASE_GROUPS = ["account_security", "external_login", "retention", "recycle_bin", "uploads", "system_hub", "ui_format", "login_greeting",
               "brand", "lodging_freshness", "tender_closing", "list_view", "download_name", "netplan_labels", "builder_exports"]


def _open(page, live_server, page_id):
    page.goto("about:blank")
    page.goto(f"{live_server}/pages/settings-center.html")
    page.wait_for_function("() => window.__settingsCenter && window.__settingsCenter.state().view", timeout=20000)
    btn = page.locator(f'[data-testid="sc-page-{page_id}"]')
    btn.wait_for(state="attached", timeout=20000)
    if not btn.is_visible():
        page.locator('[data-testid="sc-navtoggle"]').click()
        btn.wait_for(state="visible", timeout=10000)
    btn.click()
    page.wait_for_function(f"() => window.__settingsCenter.state().page === '{page_id}'", timeout=15000)


@pytest.mark.e2e
def test_every_s4a_page_lists_every_field_of_its_groups_with_a_plain_name(live_server, make_user, e2e_browser):
    sa = make_user(username="s4a_sa", role="superadmin")
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    page.goto(f"{live_server}/pages/settings-center.html")
    page.wait_for_function("() => window.__settingsCenter && window.__settingsCenter.state().view", timeout=20000)
    idx = page.evaluate("() => window.__settingsCenter.state().idx.filter(x => x.kind === 'group').map(x => ({page: x.page, group: x.group}))")
    pages = sorted({x["page"] for x in idx if x["group"] in BASE_GROUPS})
    assert len(pages) >= 8, "S4a 的頁面太少（設定中心沒有載入？）：%s" % pages
    for pid in pages:
        _open(page, live_server, pid)
        groups = [x["group"] for x in idx if x["page"] == pid]
        page.wait_for_function("(gs) => gs.every(g => window.__settingsCenter.state().details[g])", arg=groups, timeout=15000)
        for g in groups:
            fields = page.evaluate(f"() => ((window.__settingsCenter.state().details['{g}'] || {{}}).fields || []).map(f => f.field || f.key || f.name)")
            assert fields, "%s 沒有欄位（API 回傳格式變了？）" % g
            for f in fields:
                row = page.locator(f'[data-testid="mx-row-{g}.{f}"]')
                assert row.count() == 1, "%s／%s 的欄位 %s.%s 沒有出現在畫面上" % (pid, g, g, f)
                text = (row.first.inner_text() or "").strip()
                assert text and not text.startswith(f), "%s.%s 的顯示名稱是空的或就是內部代碼" % (g, f)
