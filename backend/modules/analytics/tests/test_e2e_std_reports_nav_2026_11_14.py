# -*- coding: utf-8 -*-
"""T87 B1 e2e（真瀏覽器）：只有「業務開發」權限的業務，從側欄直接進標準報表；報表中心仍進不去（PM 裁示 2026-11-14）。

重點：reports-hub.html 的權限不放寬（hub 上還有其他財務報表的入口）；標準報表自己的 perm 含 dev_crm／case_manage。
需要後端 feat/t87-b1-be-h8 的 /api/std-reports 才跑得起來（合併後才實跑）。"""
import pytest

pytest.importorskip("playwright.sync_api")

#: 只剩單一可見項目的群組會收成一個一級連結（沒有 .mnav__item），所以頂層連結與下拉項目兩處都要收。
NAV_ITEMS_JS = """() => [...document.querySelectorAll('.mnav__item, a.mnav__top[href]')].map(a => ({label: a.textContent.trim(), href: a.getAttribute('href')}))"""


def _file(href):
    return (href or "").split("#")[0].split("?")[0].split("/")[-1]


@pytest.mark.e2e
def test_dev_crm_only_account_reaches_standard_reports_but_not_the_hub(live_server, make_user, new_page, login_as):
    page = new_page()
    login_as(page, make_user(username="sr_dev_only", role="sales", modules=["dev_crm"]))
    page.goto(live_server + "/index.html")
    page.wait_for_selector(".mnav .mnav__top", timeout=15000)
    hrefs = {_file(i["href"]) for i in page.evaluate(NAV_ITEMS_JS)}
    assert "reports-standard.html" in hrefs, "側欄看不到標準報表：%s" % sorted(hrefs)
    assert "reports-hub.html" not in hrefs, "報表中心不該出現在這位使用者的導覽列"

    # 沒有「營運報表」模組：絕不能對金額報表送請求
    seen = []
    page.on("request", lambda r: seen.append(r.url))
    page.goto(live_server + "/pages/reports-standard.html")
    page.wait_for_selector("[data-testid^=sr-tab-]", timeout=15000)
    tabs = {t.get_attribute("data-testid")[len("sr-tab-"):] for t in page.locator("[data-testid^=sr-tab-]").all()}
    assert "sales-funnel" in tabs, tabs
    assert not (tabs & {"revenue", "gross-margin", "ar-aging"}), "金額報表不該出頁籤：%s" % sorted(tabs)
    assert not [u for u in seen if any(("/api/std-reports/" + k) in u for k in ("revenue", "gross-margin", "ar-aging"))], seen
    # 站在標準報表上，不放「← 報表」回報表中心的連結（這位使用者進不去）
    assert page.locator("[data-testid=hub-crumb]").count() == 0
    # 頁頭麵包屑的群組名稱（報表）對這位使用者只是文字，不是連到報表中心的連結（他進不去）
    page.wait_for_selector(".pg__crumb [data-crumb-grp]", timeout=15000)
    assert page.locator(".pg__crumb a[data-crumb-grp]").count() == 0

    # 報表中心：通用的「沒有權限」畫面，不是一片空白
    page.goto(live_server + "/pages/reports-hub.html")
    page.wait_for_selector("#no-module-notice", timeout=15000)


@pytest.mark.e2e
def test_account_with_no_report_related_permission_sees_the_notice(live_server, make_user, new_page, login_as):
    page = new_page()
    login_as(page, make_user(username="sr_none", role="sales", modules=["quotation"]))
    page.goto(live_server + "/pages/reports-standard.html")
    page.wait_for_selector("#no-module-notice", timeout=15000)
