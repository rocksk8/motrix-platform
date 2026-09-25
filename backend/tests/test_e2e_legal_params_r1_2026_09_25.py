# -*- coding: utf-8 -*-
"""R1 e2e：法規參數設定頁、勞報單頁的版本與跨年提示（CUSTOMIZATION-SPEC §9.1）。

- 設定頁：列出版本；「新增下一年度」→ 改最低工資（門檻自動跟著）→ 儲存 ⇒ 真的寫進設定。
- 設定頁：門檻≠最低工資 ⇒ 畫面標出、後端拒絕，錯誤訊息看得到。
- 12 月且下一年度未設定 ⇒ 設定頁與勞報單頁都顯示提示。
- 勞報單頁：新單依開單日期套用版本；舊單改日期 ⇒ 顯示「沿用建立時版本」與重算勾選，勾選存檔後版本才變。
"""
import copy
from datetime import date

import pytest

pytest.importorskip("playwright.sync_api")

from helpers import legal_params as lp  # noqa: E402

ROOT = "Alpine.$data(document.querySelector('[x-data]'))"


def _v2027():
    v = copy.deepcopy(lp.DEFAULT_TAX_RULE_VERSIONS[0])
    v.update(version="2027", effectiveFrom="2027-01-01", sources=["測試資料"])
    v["minimum_wage"]["monthly"] = 30900
    v["nhi"]["thresholds"]["50"] = 30900
    return v


@pytest.fixture()
def before_new_year(monkeypatch):
    monkeypatch.setattr(lp, "today", lambda: date(2026, 9, 25))


def _open(page, base, path, ready):
    page.goto(base + "/pages/" + path)
    page.wait_for_function(f"() => window.Alpine && document.querySelector('[x-data]') && ({ready})",
                           timeout=20000)


@pytest.mark.e2e
def test_settings_page_adds_next_year_and_saves(live_server, make_user, new_page, login_as, before_new_year):
    u = make_user(username="r1e_a", role="superadmin")
    page = new_page()
    login_as(page, u)
    _open(page, live_server, "legal-params.html", f"{ROOT}.versions.length > 0")
    assert page.locator("tr[data-version='2026']").count() == 1
    page.locator("[data-add-next-year]").click()
    row = page.locator("tr[data-version='2027']")
    row.wait_for(state="visible", timeout=5000)
    mw = row.locator("input[data-field='minimum_wage']")
    mw.fill("30900")
    assert row.locator("input[data-field='nhi50']").input_value() == "30900", "門檻要跟著最低工資"
    bonus = row.locator("input[data-field='bonus_multiple']")
    assert bonus.input_value() == "4" and bonus.is_enabled(), "獎金補充保費倍數要看得到、改得到"
    page.locator("[data-save]").click()
    page.wait_for_function(f"() => {ROOT}.okMsg === '已儲存'", timeout=10000)
    vs = lp.load_versions()
    assert [v["version"] for v in vs] == ["2026", "2027"]
    assert vs[1]["minimum_wage"]["monthly"] == 30900 and vs[1]["nhi"]["thresholds"]["50"] == 30900
    # 已生效的 2026 版輸入框鎖住
    assert page.locator("tr[data-version='2026'] input[data-field='minimum_wage']").is_disabled()


@pytest.mark.e2e
def test_settings_page_shows_the_threshold_mismatch(live_server, make_user, new_page, login_as, before_new_year):
    u = make_user(username="r1e_b", role="superadmin")
    page = new_page()
    login_as(page, u)
    _open(page, live_server, "legal-params.html", f"{ROOT}.versions.length > 0")
    page.locator("[data-add-next-year]").click()
    row = page.locator("tr[data-version='2027']")
    row.locator("input[data-field='minimum_wage']").fill("30900")
    row.locator("input[data-field='nhi50']").fill("29500")
    row.locator("[data-mismatch]").wait_for(state="visible", timeout=5000)
    assert "須等於最低工資" in row.locator("[data-mismatch]").inner_text()
    page.locator("[data-save]").click()
    err = page.locator("[data-error]")
    err.wait_for(state="visible", timeout=5000)
    assert "最低工資" in err.inner_text()
    assert [v["version"] for v in lp.load_versions()] == ["2026"], "被擋下的不可以寫進去"
