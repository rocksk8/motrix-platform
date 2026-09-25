# -*- coding: utf-8 -*-
"""R1 e2e：法規參數設定頁、勞報單頁的版本與跨年提示（CUSTOMIZATION-SPEC §7.1）。

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


@pytest.mark.e2e
def test_december_without_next_year_warns_on_both_pages(live_server, make_user, new_page, login_as, monkeypatch):
    monkeypatch.setattr(lp, "today", lambda: date(2026, 12, 3))
    u = make_user(username="r1e_c", role="superadmin")
    page = new_page()
    login_as(page, u)
    _open(page, live_server, "legal-params.html", f"{ROOT}.versions.length > 0")
    w = page.locator("[data-legal-warning]").first
    w.wait_for(state="visible", timeout=5000)
    assert "2027 年的法規參數" in w.inner_text()
    _open(page, live_server, "payslip-form.html", f"{ROOT}.rulesVersion !== ''")
    w = page.locator("[data-legal-warning]").first
    w.wait_for(state="visible", timeout=5000)
    assert "2027 年的法規參數" in w.inner_text()


@pytest.mark.e2e
def test_payslip_form_new_slip_follows_the_date(live_server, make_user, new_page, login_as, before_new_year):
    lp.save_versions(lp.load_versions() + [_v2027()])
    u = make_user(username="r1e_d", role="superadmin")
    page = new_page()
    login_as(page, u)
    _open(page, live_server, "payslip-form.html", f"{ROOT}.rulesVersion !== ''")
    page.evaluate(f"() => {{ const d = {ROOT}; d.q.slipDate = '2027-01-05'; return d.onSlipDateChange() }}")
    label = page.locator("[data-rules-version]")
    page.wait_for_function(f"() => {ROOT}.rulesVersion === '2027'", timeout=5000)
    assert "2027" in label.inner_text() and "2027-01-01" in label.inner_text()


@pytest.mark.e2e
def test_payslip_form_old_slip_keeps_its_version_until_recalc(live_server, make_user, new_page, login_as,
                                                                client, before_new_year):
    lp.save_versions(lp.load_versions() + [_v2027()])
    u = make_user(username="r1e_e", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": u[0], "password": u[1]}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    r = client.post("/api/payslips", headers=h, json={"data": {
        "contractorName": "受領人", "incomeType": "50", "grossAmount": 30000, "serviceContent": "x",
        "contractorNationality": "本國籍", "contractorHasUnionInsurance": False, "slipDate": "2026-12-20"}})
    assert r.status_code == 201, r.text
    no = r.json()["slip_no"]
    page = new_page()
    login_as(page, u)
    _open(page, live_server, f"payslip-form.html?id={no}", f"{ROOT}.rulesVersion === '2026'")
    box = page.locator("[data-rules-mismatch]")
    assert not box.is_visible()
    page.locator("input[type=date][x-model='q.slipDate']").fill("2027-01-05")
    page.locator("input[type=date][x-model='q.slipDate']").dispatch_event("change")
    box.wait_for(state="visible", timeout=5000)
    assert "2027" in box.inner_text() and "2026" in box.inner_text()
    assert page.evaluate(f"() => {ROOT}.result.nhiSupplement") == 633, "沒勾重算 ⇒ 試算仍用 2026"
    page.locator("[data-recalc]").check()
    page.wait_for_function(f"() => {ROOT}.rulesVersion === '2027'", timeout=5000)
    assert page.evaluate(f"() => {ROOT}.result.nhiSupplement") == 0
    page.evaluate(f"() => {ROOT}.save()")
    page.wait_for_function(f"() => !{ROOT}.saving && !{ROOT}.isDirty", timeout=10000)
    row = client.get("/api/payslips/" + no, headers=h).json()
    assert row["tax_rules_version"] == "2027" and row["nhi_supplement"] == 0
