# -*- coding: utf-8 -*-
"""2026-11-11 e2e（真瀏覽器）：導覽與資訊架構（UX 提案 B1／B2／B3／B6）。

B1 選單重分：客戶與業務／案件／採購與庫存（客戶從「廠商與採購」移出；「設備」併入採購與庫存）；財務會計維持獨立。
B2 報表五個入口收成一個一級「報表」→ 報表中心（營運／財務／帳簿頁籤；報表設定收成齒輪）。
B3 財務會計下拉加小標題：日常／月結／設定。
B6 頁頭規格：麵包屑（群組 › 頁名）依選單宣告自動補、頂部黑列不再重複頁名。

🔑 結構性改動最怕「改好看卻漏功能」：本檔最重要的一題是 `test_every_old_entry_is_still_reachable`——
   改版前導覽列上的每一個目的地，超級管理者現在都要找得到（導覽列 ＋ 報表中心）。
"""
import pytest

pytest.importorskip("playwright.sync_api")

#: 改版前（train/t79-int a71c3164c）超級管理者在導覽列上看得到的全部目的地（不含系統群組：它本來就收成「系統」單一入口）。
OLD_DESTINATIONS = {
    "index.html", "dev-crm.html", "tender-radar.html", "map.html", "quotations.html",
    "case-management.html", "case-stage-board.html",
    "customers.html", "suppliers.html", "vendor-contractors.html", "parts.html", "inventory.html", "procurement.html",
    "devices.html", "warranty.html", "network-plans.html",
    "reports.html",
    "cashier.html", "voucher.html", "account-items.html", "ledger-hub.html", "ledger-periods.html",
    "ledger-reports.html", "ledger-statements.html", "ledger-settings.html", "bonus.html", "bank-account.html",
    "contractors.html", "payslips.html",
    "work-log.html", "daily-tasks.html", "approval-queue.html", "approval-delegates.html",
    "payment-request.html", "approval-history.html",
}

NAV_JS = """() => [...document.querySelectorAll('.mnav__in > *')].map(el => {
  const top = el.matches('a.mnav__top') ? el : el.querySelector('.mnav__top');
  const items = [...el.querySelectorAll('.mnav__item')].map(a => ({label: a.textContent.trim(), href: a.getAttribute('href')}));
  const secs = [...el.querySelectorAll('.mnav__col')].map(c => ({
    sec: (c.querySelector('.mnav__sec') || {}).textContent || '',
    items: [...c.querySelectorAll('.mnav__item')].map(a => a.textContent.trim())}));
  return {label: top.textContent.trim(), href: el.matches('a.mnav__top') ? el.getAttribute('href') : null, items, secs};
})"""


def _nav(page):
    page.wait_for_selector(".mnav .mnav__top", timeout=15000)
    return page.evaluate(NAV_JS)


def _file(href):
    return (href or "").split("#")[0].split("?")[0].split("/")[-1]


def _open_as(live_server, make_user, new_page, login_as, role, modules=None, name="nav_u", path="/index.html"):
    kw = {"username": name, "role": role}
    if modules is not None:
        kw["modules"] = modules
    page = new_page()
    login_as(page, make_user(**kw))
    page.goto(live_server + path)
    return page


@pytest.mark.e2e
def test_b1_groups_are_regrouped_and_old_names_are_gone(live_server, make_user, new_page, login_as):
    page = _open_as(live_server, make_user, new_page, login_as, "superadmin", [], "nav_b1")
    nav = {g["label"]: g for g in _nav(page)}
    labels = list(nav)
    for must in ("客戶與業務", "案件", "採購與庫存", "財務會計", "報表", "勞務管理", "我的工作"):
        assert must in labels, (must, labels)
    for gone in ("廠商與採購", "設備", "經營分析", "業務"):
        assert gone not in labels, (gone, labels)
    biz = [i["label"] for i in nav["客戶與業務"]["items"]]
    assert biz == ["業務開發", "標案雷達", "客戶管理", "報價單", "地圖"], biz
    assert [i["label"] for i in nav["案件"]["items"]] == ["案件管理", "案件執行看板"]
    sup = [i["label"] for i in nav["採購與庫存"]["items"]]
    assert "客戶管理" not in sup, sup
    for must in ("供應商管理", "承攬商管理", "料號主檔", "庫存管理", "採購管理", "設備登載", "保固追蹤", "網路架構規劃書"):
        assert must in sup, (must, sup)


@pytest.mark.e2e
def test_b2_reports_is_one_top_level_link_to_the_hub(live_server, make_user, new_page, login_as):
    page = _open_as(live_server, make_user, new_page, login_as, "superadmin", [], "nav_b2")
    nav = _nav(page)
    rep = [g for g in nav if g["label"] == "報表"]
    assert len(rep) == 1 and rep[0]["items"] == [] and _file(rep[0]["href"]) == "reports-hub.html", rep
    # 其他一級項目底下不再有任何報表入口
    for g in nav:
        for it in g["items"]:
            assert "報表" not in it["label"], (g["label"], it)


@pytest.mark.e2e
def test_b3_finance_dropdown_has_section_headings(live_server, make_user, new_page, login_as):
    page = _open_as(live_server, make_user, new_page, login_as, "superadmin", [], "nav_b3")
    fin = [g for g in _nav(page) if g["label"] == "財務會計"][0]
    got = [(c["sec"], c["items"]) for c in fin["secs"]]
    assert got == [("日常", ["出納", "傳票"]), ("月結", ["總帳作業", "會計期間與結帳", "獎金分潤"]),
                   ("設定", ["會計科目", "收款帳號"])], got
    # 沒有小標題的群組維持原本（不多出標題）
    biz = [g for g in _nav(page) if g["label"] == "客戶與業務"][0]
    assert all(c["sec"] == "" for c in biz["secs"]), biz["secs"]


@pytest.mark.e2e
def test_every_old_entry_is_still_reachable(live_server, make_user, new_page, login_as):
    """結構性改動的守門：舊導覽的每個目的地，現在從導覽列或報表中心都點得到（不是只改好看）。"""
    page = _open_as(live_server, make_user, new_page, login_as, "superadmin", [], "nav_reach")
    reach = set()
    for g in _nav(page):
        if g["href"]:
            reach.add(_file(g["href"]))
        for it in g["items"]:
            reach.add(_file(it["href"]))
    page.goto(live_server + "/pages/reports-hub.html")
    page.wait_for_selector("[data-testid^=rh-tab-]", timeout=15000)
    for tab in page.locator("[data-testid^=rh-tab-]").all():
        tab.click()
        for a in page.locator("[data-testid^=rh-card-] a").all():
            reach.add(_file(a.get_attribute("href")))
    gear = page.locator("[data-testid=rh-gear]")
    assert gear.count() == 1
    reach.add(_file(gear.get_attribute("href")))
    missing = sorted(OLD_DESTINATIONS - reach)
    assert not missing, "改版後從導覽列／報表中心找不到：%s" % missing


@pytest.mark.e2e
def test_report_hub_tabs_cards_and_gear(live_server, make_user, new_page, login_as):
    page = _open_as(live_server, make_user, new_page, login_as, "superadmin", [], "nav_hub", "/pages/reports-hub.html")
    page.wait_for_selector("[data-testid^=rh-tab-]", timeout=15000)
    tabs = [t.inner_text().strip() for t in page.locator("[data-testid^=rh-tab-]").all()]
    assert tabs == ["營運", "財務", "帳簿"], tabs
    assert page.locator("[data-testid=rh-card-reports\\.html]").is_visible()          # 預設第一個頁籤
    page.locator("[data-testid=rh-tab-財務]").click()
    # 切頁籤後的顯示／隱藏要等 Alpine 的 x-show 套完（約一個影格），不能點完立刻 is_visible()
    page.locator("[data-testid=rh-card-ledger-statements\\.html]").wait_for(state="visible", timeout=5000)
    page.locator("[data-testid=rh-card-reports\\.html]").wait_for(state="hidden", timeout=5000)      # 不在 DOM 也算隱藏
    page.locator("[data-testid=rh-tab-帳簿]").click()
    card = page.locator("[data-testid=rh-card-ledger-reports\\.html]")
    card.wait_for(state="visible", timeout=5000)
    assert "明細帳" in card.inner_text()                                                # 卡片寫的是「回答什麼問題」
    card.locator("a").click()
    page.wait_for_url("**/ledger-reports.html*")
    # 子頁頂端有『← 報表』麵包屑，點了回報表中心
    crumb = page.locator("[data-testid=hub-crumb]")
    crumb.wait_for(state="visible", timeout=10000)
    assert "報表" in crumb.inner_text()
    crumb.click()
    page.wait_for_url("**/reports-hub.html*")


@pytest.mark.e2e
def test_report_hub_respects_permissions(live_server, make_user, new_page, login_as):
    """卡片全來自選單宣告 ＋ 這位使用者的權限：只有 reports 模組 ⇒ 只看到「營運」頁籤、沒有報表設定齒輪；
    完全沒有報表相關權限 ⇒ 導覽列沒有「報表」、直接開報表中心顯示『沒有權限』說明（不是一片空白）。"""
    page = _open_as(live_server, make_user, new_page, login_as, "admin", ["reports"], "nav_rpt", "/pages/reports-hub.html")
    page.wait_for_selector("[data-testid^=rh-tab-]", timeout=15000)
    tabs = [t.inner_text().strip() for t in page.locator("[data-testid^=rh-tab-]").all()]
    assert tabs == ["營運"], tabs
    assert page.locator("[data-testid=rh-gear]").count() == 0
    assert "報表" in [g["label"] for g in _nav(page)]
    page2 = _open_as(live_server, make_user, new_page, login_as, "sales", ["quotation"], "nav_none", "/pages/reports-hub.html")
    page2.wait_for_selector("#no-module-notice", timeout=15000)          # 通用的「沒有權限」畫面（sidebar.js），不是一片空白
    assert "報表" not in [g["label"] for g in _nav(page2)]


def _hub_cards(page):
    """走遍報表中心所有頁籤，回傳 {卡片 testid: 開啟連結}（含頁頭齒輪）。"""
    page.wait_for_selector("[data-testid^=rh-tab-]", timeout=15000)
    out = {}
    for t in [x.inner_text().strip() for x in page.locator("[data-testid^=rh-tab-]").all()]:
        page.locator("[data-testid=rh-tab-%s]" % t).click()
        page.wait_for_timeout(150)
        for c in page.locator("[data-testid^=rh-card-]").all():
            out[c.get_attribute("data-testid")] = c.locator("a").get_attribute("href")
    if page.locator("[data-testid=rh-gear]").count():
        out["rh-gear"] = page.locator("[data-testid=rh-gear]").get_attribute("href")
    return out


@pytest.mark.e2e
def test_report_hub_only_lists_reports_this_user_can_open(live_server, make_user, new_page, login_as):
    """權限切片（K 審 N1）：只有「財務」或只有「出納」的使用者，報表中心列出的每一張卡片都必須點得進去
    （不會出現『沒有權限』），而且不會比超級管理員多出任何一張。"""
    sa = _open_as(live_server, make_user, new_page, login_as, "superadmin", [], "nav_hub_sa", "/pages/reports-hub.html")
    full = _hub_cards(sa)
    assert len(full) >= 4, full
    for mod in ("finance", "cashier"):
        page = _open_as(live_server, make_user, new_page, login_as, "admin", [mod], "nav_hub_" + mod, "/pages/reports-hub.html")
        got = _hub_cards(page)
        assert got, "%s：報表中心一張卡片都沒有" % mod
        assert set(got) <= set(full), (mod, sorted(set(got) - set(full)))
        for key, href in got.items():
            page.goto(live_server + "/pages/" + href.split("/")[-1].split("#")[0])
            page.wait_for_timeout(1200)
            assert page.locator("#no-module-notice").count() == 0 or not page.locator("#no-module-notice").is_visible(), \
                "%s：報表中心列出 %s（%s），點進去卻是『沒有權限』" % (mod, key, href)
            page.goto(live_server + "/pages/reports-hub.html")
            page.wait_for_selector("[data-testid^=rh-tab-]", timeout=15000)


@pytest.mark.e2e
def test_b6_page_header_crumb_is_filled_from_the_menu_declaration(live_server, make_user, new_page, login_as):
    page = _open_as(live_server, make_user, new_page, login_as, "superadmin", [], "nav_b6", "/pages/customers.html")
    crumb = page.locator(".pg__crumb")
    crumb.wait_for(state="visible", timeout=15000)
    page.wait_for_function("() => document.querySelector('.pg__crumb [data-crumb-grp]')", timeout=10000)
    assert crumb.inner_text().replace("\n", "").replace(" ", "") == "客戶與業務›客戶管理", crumb.inner_text()
    assert page.locator("h1").count() == 1 and page.locator("h1").inner_text().strip() == "客戶管理"
    # 有麵包屑的頁面：頂部黑列不再重複印頁名
    assert not page.locator(".topbar__title").is_visible()
    # 設備三頁已併入採購與庫存：麵包屑跟著宣告走，頁面檔裡沒有寫死舊群組名
    page.goto(live_server + "/pages/warranty.html")
    page.wait_for_function("() => document.querySelector('.pg__crumb [data-crumb-grp]')", timeout=15000)
    assert page.locator(".pg__crumb").inner_text().replace("\n", "").replace(" ", "") == "採購與庫存›保固追蹤"
