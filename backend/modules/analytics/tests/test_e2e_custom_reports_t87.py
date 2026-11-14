"""瀏覽器端對端：自訂報表頁（T87 B2-S4）。

流程：選條件 → 預覽 → 存成我的報表 → 重新整理後還在 → 匯出 Excel；無金額權限者的矩陣；旗標關閉時頁面與報表中心卡片；
a11y 規格（h5 r2 nits）：焦點保留、表頭核取框 indeterminate、批次復原會被後續編輯作廢、鎖定列每列只有一個 Tab 停駐點。
每一步等的是「這一次預覽完成」的條件（摘要文字），不是立刻讀畫面。
"""
import io

import openpyxl
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests.platform.test_custom_reports_export_t87 import _quote, _set  # noqa: E402

PREVIEW_ROWS = "[data-testid=cr-preview] tbody tr"


@pytest.fixture(autouse=True)
def _flag(client):
    _set(enabled=1)
    yield
    _set(enabled=0)


def _open(live_server, make_user, e2e_browser, name, role="superadmin", modules=None, path="custom-reports.html", viewport=(1440, 900)):
    username, password = make_user(username=name, role=role, **({"modules": modules, "legacy_finance_flag": False} if modules else {}))
    page = e2e_browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
    inject_login(page, live_server, username, password)
    page.goto(f"{live_server}/pages/{path}")
    return page


def _ready(page):
    page.wait_for_selector("[data-testid=cr-matrix] tbody tr", timeout=20000)
    page.wait_for_selector("[data-testid=cr-summary]", timeout=20000)


def _summary(page):
    return page.locator("[data-testid=cr-summary]").inner_text()


def _filter_customer(page, text, expect_total):
    page.check("[data-fk='m:customer_name:f']")
    page.fill("[aria-label='客戶 值']", text)
    page.wait_for_function(
        """(n) => { const s = document.querySelector('[data-testid=cr-summary]');
                    return s && s.innerText.startsWith('共 ' + n + ' 筆') && !document.querySelector('[data-testid=cr-loading]') }""",
        arg=expect_total, timeout=20000)


@pytest.mark.e2e
def test_build_save_reload_and_export(live_server, make_user, e2e_browser):
    _quote(no="E2E-CR-1", customer_name="端到端甲", total=1200)
    _quote(no="E2E-CR-2", customer_name="端到端甲", total=3400)
    _quote(no="E2E-CR-3", customer_name="端到端乙", total=99)
    page = _open(live_server, make_user, e2e_browser, "e2e_cr1")
    _ready(page)
    # 還沒存：不能匯出
    assert page.locator("[data-testid=cr-export]").is_disabled()
    _filter_customer(page, "端到端甲", 2)
    assert page.locator(PREVIEW_ROWS).count() == 2
    # 儲存
    page.click("[data-testid=cr-save]")
    page.fill("[data-testid=cr-name]", "端到端報表")
    page.click("[data-testid=cr-name-ok]")
    page.wait_for_function("() => document.getElementById('sbTitle').textContent === '端到端報表' && !document.getElementById('btnExport').disabled", timeout=20000)
    # 重新整理：報表還在、條件還在
    page.goto(f"{live_server}/pages/custom-reports.html")
    page.wait_for_selector("[data-testid^=cr-report-]", timeout=20000)
    page.click("[data-testid^=cr-report-]:has-text('端到端報表')")
    page.wait_for_selector("[aria-label='客戶 值']", timeout=20000)
    assert page.input_value("[aria-label='客戶 值']") == "端到端甲"
    page.wait_for_function("() => { const s = document.querySelector('[data-testid=cr-summary]'); return s && s.innerText.startsWith('共 2 筆') }", timeout=20000)
    # 匯出 Excel：只有兩筆「端到端甲」
    page.click("[data-testid=cr-export]")
    with page.expect_download(timeout=30000) as dl:
        page.click("[data-testid=cr-export-go]")
    with open(dl.value.path(), "rb") as fh:
        wb = openpyxl.load_workbook(io.BytesIO(fh.read()))
    ws = wb["報表"]
    flat = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    assert "E2E-CR-1" in flat and "E2E-CR-2" in flat and "E2E-CR-3" not in flat
    assert wb["說明"]["A1"].value == "資料來源"
    page.close()


@pytest.mark.e2e
def test_user_without_money_permission_sees_locked_cells_with_one_tab_stop_per_row(live_server, make_user, e2e_browser):
    page = _open(live_server, make_user, e2e_browser, "e2e_cr2", role="engineer", modules=["quotation"])
    _ready(page)
    locked = page.locator("[data-testid=cr-matrix] tbody tr[aria-describedby]")
    assert locked.count() >= 1
    n = locked.count()
    # 每個鎖定列只有「顯示」格一個 Tab 停駐點；圖例以 aria-describedby 掛在列層
    assert page.locator("[data-testid=cr-matrix] tbody tr[aria-describedby] td[tabindex='0']").count() == n
    assert page.locator("[data-testid=cr-matrix] tbody tr[aria-describedby] td.lock").first.inner_text().startswith("無權限")
    assert page.locator("#lg-lock").count() == 1
    # 表頭「顯示」核取框只看可用欄：全選時不是 indeterminate
    page.close()


@pytest.mark.e2e
def test_focus_kept_indeterminate_header_and_undo_invalidated_by_other_edits(live_server, make_user, e2e_browser):
    page = _open(live_server, make_user, e2e_browser, "e2e_cr3")
    _ready(page)
    box = "[data-fk='m:status:show']"
    was = page.is_checked(box)
    page.focus(box)
    page.keyboard.press("Space")
    page.wait_for_function("([s, w]) => document.querySelector(s).checked !== w", arg=[box, was], timeout=20000)
    assert page.is_checked(box) != was
    assert page.evaluate("() => document.activeElement.getAttribute('data-fk')") == "m:status:show"      # 重畫後焦點還在同一格
    # 部分欄位顯示：表頭核取框是 indeterminate
    assert page.evaluate("() => document.querySelector('[data-fk=showAll]').indeterminate") is True
    # 批次 → 出現「復原上一次批次」；之後做了別的編輯 ⇒ 復原鈕作廢
    page.click("[data-fk='batch:hide']")
    page.locator("#btnUndo").wait_for(state="visible", timeout=20000)
    assert page.locator("#btnUndo").is_visible()
    page.check("[data-fk='m:customer_name:g']")
    page.locator("#btnUndo").wait_for(state="hidden", timeout=20000)
    assert page.locator("#btnUndo").is_hidden()
    # 批次訊息：略過 0 項時不寫「略過」
    page.check("[data-fk='m:quote_no:pick']")
    page.click("[data-fk='batch:show']")
    page.wait_for_function("() => document.getElementById('batchMsg').textContent.includes('已套用')", timeout=20000)
    assert "略過" not in page.locator("#batchMsg").inner_text()
    # 提示節點常駐 DOM
    assert page.locator("#toast[role=status]").count() == 1
    page.close()


@pytest.mark.e2e
def test_flag_off_shows_not_open_and_hides_hub_card(live_server, make_user, e2e_browser):
    _set(enabled=0)
    page = _open(live_server, make_user, e2e_browser, "e2e_cr4")
    page.wait_for_selector("#crLoadError:not([hidden])", timeout=20000)
    assert "尚未開放" in page.locator("#crLoadError").inner_text()
    hub = e2e_browser.new_page(viewport={"width": 1440, "height": 900})
    hub.add_init_script(page.evaluate("() => localStorage.getItem('motrix_session')") and
                        "try{localStorage.setItem('motrix_session', %r)}catch(e){}" % page.evaluate("() => localStorage.getItem('motrix_session')"))
    hub.goto(f"{live_server}/pages/reports-hub.html")
    hub.wait_for_selector("[data-testid^=rh-card-]", timeout=20000)
    hub.wait_for_timeout(800)
    assert hub.locator("[data-testid*='custom-reports']").count() == 0
    _set(enabled=1)
    hub.reload()
    hub.wait_for_selector("[data-testid*='custom-reports']", timeout=20000)
    hub.close()
    page.close()


def _entries(page):
    """這一頁的主選單與頁面本體裡，指向自訂報表的連結數（等選單依角色版面重建完才算）。"""
    page.wait_for_function("() => document.documentElement.getAttribute('data-menu-seq')", timeout=20000)
    page.wait_for_timeout(400)
    return page.evaluate("() => ({nav: document.querySelectorAll('#app-mainnav a[href*=\"custom-reports.html\"]').length,"
                         " card: document.querySelectorAll('[data-testid*=\"custom-reports\"]').length})")


@pytest.mark.e2e
def test_flag_off_means_no_entry_in_main_menu_or_reports_hub_flag_on_shows_both(live_server, make_user, e2e_browser):
    """PM／h10：旗標關著時選單不能出現一個點了只會 404 的入口；開著時選單與報表中心兩邊都有。
    工程師（只有報價模組）沒有報表中心，只靠主選單進得去——那條路最容易漏。"""
    for who, kw in (("engineer", dict(role="engineer", modules=["quotation"])), ("boss", {})):
        _set(enabled=0)
        page = _open(live_server, make_user, e2e_browser, "e2e_cr_menu_" + who, path="reports-hub.html" if who == "boss" else "custom-reports.html", **kw)
        off = _entries(page)
        assert off == {"nav": 0, "card": 0}, (who, off)
        _set(enabled=1)
        page.reload()
        on = _entries(page)
        if who == "engineer":
            assert on["nav"] >= 1, (who, on)                          # 沒有報表中心的人：主選單是唯一入口
        else:
            assert on["card"] >= 1, (who, on)                         # 有報表中心的人：選單把報表群組收成「報表中心」一個連結，入口是卡片
        page.close()


@pytest.mark.e2e
def test_share_panel_search_select_all_share_recipient_sees_batch_remove_and_hidden_when_off(live_server, make_user, e2e_browser):
    """分享面板（B2-S5）：搜尋→全選目前結果→分享；被分享者看得到；批次取消分享；設定關閉時入口不出現。"""
    from db import get_db
    names = []
    for i in range(3):
        u, _p = make_user(username="e2e_sh_t%d" % i, role="sales", modules=["quotation"])
        names.append(u)
    nocap, _ = make_user(username="e2e_sh_nocap", role="sales", modules=["inventory"])
    c = get_db()
    try:
        for u, dn in zip(names, ("林一號", "林二號", "林三號")):
            c.execute("UPDATE users SET display_name=? WHERE username=?", (dn, u))
        c.execute("UPDATE users SET display_name='林無權' WHERE username=?", (nocap,))
        c.commit()
    finally:
        c.close()
    _set(sharing=0)
    try:
        page = _open(live_server, make_user, e2e_browser, "e2e_sh_owner", role="engineer", modules=["quotation"])
        _ready(page)
        page.click("[data-testid=cr-save]")
        page.fill("[data-testid=cr-name]", "分享用報表")
        page.click("[data-testid=cr-name-ok]")
        page.wait_for_function("() => document.getElementById('sbTitle').textContent === '分享用報表'", timeout=20000)
        assert page.locator("[data-testid=cr-share]").is_hidden()                              # 設定關閉：沒有入口
        _set(sharing=1)
        page.goto(f"{live_server}/pages/custom-reports.html")
        page.wait_for_selector("[data-testid^=cr-report-]", timeout=20000)
        page.click("[data-testid^=cr-report-]:has-text('分享用報表')")
        page.wait_for_selector("[data-testid=cr-share]:not([hidden])", timeout=20000)
        page.click("[data-testid=cr-share]")
        page.wait_for_selector("[data-testid=cr-dlg-share][open]")
        page.fill("[data-testid=cr-sh-q]", "林")
        page.wait_for_function("() => document.querySelectorAll('#shCands li label.row').length === 3", timeout=20000)     # 沒有權限的「林無權」不在名單
        assert "林無權" not in page.inner_text("[data-testid=cr-sh-cands]")
        page.check("[data-testid=cr-sh-selcands]")
        page.wait_for_function("() => { const b = document.querySelector('[data-testid=cr-sh-add]'); return !b.disabled && b.textContent.includes('（3）') }", timeout=20000)
        assert page.is_enabled("[data-testid=cr-sh-add]") and "（3）" in page.inner_text("[data-testid=cr-sh-add]")
        page.uncheck("[data-testid=cr-sh-selcands]")                                         # 全選可以切換成清除
        page.wait_for_function("() => document.querySelector('[data-testid=cr-sh-add]').disabled", timeout=20000)
        assert page.is_disabled("[data-testid=cr-sh-add]")
        page.check("[data-testid=cr-sh-selcands]")
        page.click("[data-testid=cr-sh-add]")
        page.wait_for_function("() => document.getElementById('shMsg').textContent.includes('已分享給 3 位')", timeout=20000)
        # 分享完（沒有勾選了、按鈕變成不能用）：焦點留在對話框內（結果訊息），不掉到 BODY；對話框也沒有被標成忙碌
        assert page.evaluate("() => document.getElementById('dlgShare').contains(document.activeElement)") is True
        assert page.evaluate("() => document.getElementById('dlgShare').hasAttribute('aria-busy')") is False
        assert page.locator("#shShared li label.row").count() == 3
        assert page.locator("#shCands li label.row.off").count() == 3                        # 已分享的人在候選名單標示、不能重複勾
        # 被分享者看得到
        other = e2e_browser.new_page(viewport={"width": 1440, "height": 900})
        inject_login(other, live_server, names[0], "Test-Pass-123")
        other.goto(f"{live_server}/pages/custom-reports.html")
        other.wait_for_selector("[data-testid^=cr-report-]:has-text('分享用報表')", timeout=20000)
        assert other.locator("[data-testid=cr-share]").is_hidden()                         # 被分享者沒有分享入口
        other.close()
        # 批次取消分享（先勾兩位，確認後移除）
        page.check("[data-fk='sh:S:%s']" % names[1])
        page.check("[data-fk='sh:S:%s']" % names[2])
        page.click("[data-testid=cr-sh-remove]")
        page.click("[data-testid=cr-confirm-yes]")
        page.wait_for_function("() => document.getElementById('shMsg').textContent.includes('已取消分享 2 位')", timeout=20000)
        assert page.evaluate("() => document.getElementById('dlgShare').contains(document.activeElement)") is True
        assert page.locator("#shShared li label.row").count() == 1
        page.click("[data-testid=cr-sh-close]")
        c = get_db()
        try:
            acts = [r[0] for r in c.execute("SELECT action FROM audit_log WHERE username = ? AND action LIKE 'custom_reports.share_%' ORDER BY id", ("e2e_sh_owner",))]
        finally:
            c.close()
        assert acts == ["custom_reports.share_add"] * 3 + ["custom_reports.share_remove"] * 2
        page.close()
    finally:
        _set(sharing=0)


@pytest.mark.e2e
def test_undo_returns_focus_to_page_not_body_header_show_all_reports_skips_and_partially_hidden_filters_text(live_server, make_user, e2e_browser):
    """h5 實機複核三項 nits：復原後焦點不掉到 BODY；表頭「全部顯示」回報略過的無權限欄；有隱藏條件的分享報表，篩選面板不說「沒有條件」。"""
    _set(sharing=1)
    try:
        eng = _open(live_server, make_user, e2e_browser, "e2e_nit_eng", role="engineer", modules=["quotation"])
        _ready(eng)
        eng.click("[data-fk=showAll]")                                          # 全部顯示 ⇒ 有無權限欄位被略過，要說出數量
        eng.wait_for_function("() => document.getElementById('batchMsg').textContent.includes('略過')", timeout=20000)
        assert "含稅總額（無權限）" in eng.locator("#batchMsg").inner_text()
        eng.click("[data-fk='batch:hide']")
        eng.locator("#btnUndo").wait_for(state="visible", timeout=20000)
        assert eng.locator("#btnUndo").is_visible()
        eng.click("#btnUndo")
        eng.locator("#btnUndo").wait_for(state="hidden", timeout=20000)
        assert eng.locator("#btnUndo").is_hidden()
        assert eng.evaluate("() => document.activeElement && document.activeElement !== document.body") is True       # 按鈕消失後焦點不掉到 BODY
        eng.close()
        # 分享報表：擁有者的篩選用到工程師看不到的「含稅總額」
        owner = _open(live_server, make_user, e2e_browser, "e2e_nit_owner")
        _ready(owner)
        eng_user, _p = make_user(username="e2e_nit_eng2", role="engineer", modules=["quotation"])
        made = owner.evaluate("""async (who) => {
            const tok = JSON.parse(localStorage.getItem('motrix_session')).token
            const H = {Authorization: 'Bearer ' + tok, 'Content-Type': 'application/json'}
            const d = {version: 1, source: 'quotation', layout: 'detail', columns: ['quote_no', 'customer_name', 'total'],
                       filters: [{field: 'total', op: 'gte', value: 100000}], groupBy: [], aggregates: [], sort: []}
            const c = await (await fetch('/api/custom-reports', {method: 'POST', headers: H, body: JSON.stringify({name: '含金額門檻', definition: d})})).json()
            const r = await fetch('/api/custom-reports/' + c.id + '/shares', {method: 'POST', headers: H, body: JSON.stringify({add: [who]})})
            return [c.id, r.status]
        }""", eng_user)
        assert made[1] == 200
        owner.close()
        rd = e2e_browser.new_page(viewport={"width": 1440, "height": 900})
        inject_login(rd, live_server, eng_user, "Test-Pass-123")
        rd.goto(f"{live_server}/pages/custom-reports.html#{made[0]}")
        rd.wait_for_selector("[data-testid=cr-no-filters]", timeout=20000)
        txt = rd.inner_text("[data-testid=cr-no-filters]")
        assert "另有條件" in txt and "目前沒有篩選條件" not in txt
        rd.close()
    finally:
        _set(sharing=0)
