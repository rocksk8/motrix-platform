# -*- coding: utf-8 -*-
"""T85 匯入精靈頁（真瀏覽器）：選對象→範本→上傳→預覽→確認→結果；員工臨時密碼只顯示一次；設定關閉時的樣子；舊頁面連結。"""
import io

import pytest

pytest.importorskip("playwright.sync_api")

from openpyxl import Workbook  # noqa: E402

from tests._requires import requires_module  # noqa: E402

pytestmark = requires_module("importer", "本檔打匯入精靈模組的頁面")

DATA = "Alpine.$data(document.querySelector('[x-data]'))"


def _flag(on):
    from db import get_db
    from helpers import settings_groups, settings_registry as SR      # noqa: F401
    c = get_db()
    try:
        SR.publish("import_wizard", {"enabled": 1 if on else 0}, reason="測試", user="e2e", conn=c)
    finally:
        c.close()


def _xlsx(tmp_path, name, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "資料"
    for r in rows:
        ws.append(r)
    p = tmp_path / name
    wb.save(str(p))
    return str(p)


def _open(live_server, make_user, new_page, login_as, role="superadmin", name="iw_sa"):
    u = make_user(username=name, role=role)
    page = new_page(viewport={"width": 1280, "height": 900})
    login_as(page, u)
    page.goto(live_server + "/pages/import-wizard.html")
    page.wait_for_function("() => %s.loaded === true" % DATA, timeout=15000)
    return page


@pytest.mark.e2e
def test_flag_off_shows_not_open_and_hides_the_wizard(live_server, make_user, new_page, login_as):
    page = _open(live_server, make_user, new_page, login_as)
    page.get_by_test_id("iw-off").wait_for(state="visible", timeout=5000)
    assert not page.get_by_test_id("iw-choose").is_visible()


@pytest.mark.e2e
def test_customers_flow_preview_commit_and_result(live_server, make_user, new_page, login_as, tmp_path):
    _flag(True)
    page = _open(live_server, make_user, new_page, login_as, name="iw_sa2")
    page.get_by_test_id("iw-choose").wait_for(state="visible", timeout=5000)
    page.get_by_test_id("iw-kind-customers").click()
    page.get_by_test_id("iw-upload").wait_for(state="visible", timeout=5000)
    # 範本可下載
    with page.expect_download() as dl:
        page.get_by_test_id("iw-template").click()
    assert dl.value.suggested_filename.endswith(".xlsx")
    f = _xlsx(tmp_path, "c.xlsx", [["公司名稱＊", "統一編號", "神秘欄"], ["精靈甲公司", "12345675", "x"], ["精靈乙公司", "12345678", ""], ["", "", ""]])
    page.get_by_test_id("iw-file").set_input_files(f)
    page.get_by_test_id("iw-plan").wait_for(state="visible", timeout=15000)
    assert page.get_by_test_id("iw-n-created").inner_text().strip() == "2"
    assert "神秘欄" in page.get_by_test_id("iw-unused").inner_text()
    # 乙的統編檢查碼不對 ⇒ 要勾「我已確認」才能確認匯入
    assert page.get_by_test_id("iw-ubn-ack").is_visible()
    assert page.get_by_test_id("iw-commit").is_disabled()
    page.get_by_test_id("iw-ubn-ack-box").check()
    page.wait_for_function("() => { const b = document.querySelector('[data-testid=\"iw-commit\"]'); return b && !b.disabled }", timeout=10000)
    page.get_by_test_id("iw-commit").click()
    page.get_by_test_id("iw-result").wait_for(state="visible", timeout=15000)
    assert "新增 2 筆" in page.get_by_test_id("iw-result-summary").inner_text()
    import db
    c = db.get_db()
    try:
        names = {r["name"] for r in c.execute("SELECT name FROM customers").fetchall()}
    finally:
        c.close()
    assert {"精靈甲公司", "精靈乙公司"} <= names


@pytest.mark.e2e
def test_users_flow_temp_passwords_are_shown_once_and_cleared(live_server, make_user, new_page, login_as, tmp_path):
    _flag(True)
    page = _open(live_server, make_user, new_page, login_as, name="iw_sa3")
    page.get_by_test_id("iw-kind-users").click()
    f = _xlsx(tmp_path, "u.xlsx", [["帳號＊", "姓名＊", "角色", "密碼"], ["iw_u1", "甲", "業務", "abc"], ["iw_u2", "乙", "管理員", ""]])
    page.get_by_test_id("iw-file").set_input_files(f)
    page.get_by_test_id("iw-plan").wait_for(state="visible", timeout=15000)
    assert page.get_by_test_id("iw-n-created").inner_text().strip() == "1"
    assert "此角色需手動建立" in page.get_by_test_id("iw-manual").inner_text()
    assert page.get_by_test_id("iw-users-note").is_visible()
    page.get_by_test_id("iw-commit").click()
    page.get_by_test_id("iw-credentials").wait_for(state="visible", timeout=15000)
    pw = page.locator(".iw-pw").first.inner_text().strip()
    assert len(pw) >= 14 and pw != "abc"
    import db
    c = db.get_db()
    try:
        row = c.execute("SELECT must_change_password FROM users WHERE username='iw_u1'").fetchone()
        assert row["must_change_password"] == 1
        assert c.execute("SELECT 1 FROM users WHERE username='iw_u2'").fetchone() is None
    finally:
        c.close()
    # 密碼不進 localStorage／sessionStorage
    stored = page.evaluate("() => JSON.stringify([localStorage, sessionStorage])")
    assert pw not in stored
    page.get_by_test_id("iw-cred-done").click()
    page.get_by_test_id("iw-credentials").wait_for(state="hidden", timeout=5000)
    assert pw not in page.content(), "清除後畫面上沒有密碼"


@pytest.mark.e2e
def test_old_customers_page_keeps_its_import_button_and_shows_the_link_only_when_on(live_server, make_user, new_page, login_as):
    u = make_user(username="iw_sa4", role="superadmin")
    page = new_page(viewport={"width": 1280, "height": 900})
    login_as(page, u)
    page.goto(live_server + "/pages/customers.html")
    page.get_by_role("button", name="匯入 Excel").wait_for(state="visible", timeout=15000)
    assert not page.get_by_test_id("import-wizard-link").is_visible()
    _flag(True)
    page.reload()
    page.get_by_test_id("import-wizard-link").wait_for(state="visible", timeout=15000)
    assert page.get_by_role("button", name="匯入 Excel").is_visible()
    page.get_by_test_id("import-wizard-link").click()
    page.wait_for_url("**/import-wizard.html")


@pytest.mark.e2e
def test_lost_response_says_uncertain_then_query_replays_without_passwords_and_reset_works(live_server, make_user, new_page, login_as, tmp_path):
    """M3：伺服器已經建好、回應在路上掉了 ⇒ 頁面不可以說「沒有建立」；查詢＝同一把 key 重送 ⇒ 看到建了哪些帳號（沒有密碼）；可逐一重設臨時密碼。"""
    import requests
    _flag(True)
    page = _open(live_server, make_user, new_page, login_as, name="iw_sa5")
    page.get_by_test_id("iw-kind-users").click()
    f = _xlsx(tmp_path, "u5.xlsx", [["帳號＊", "姓名＊"], ["iw_lost1", "遺失甲"], ["iw_lost2", "遺失乙"]])
    page.get_by_test_id("iw-file").set_input_files(f)
    page.get_by_test_id("iw-plan").wait_for(state="visible", timeout=15000)
    seen = {"n": 0, "keys": []}

    def drop_first_commit(route):
        req = route.request
        body = req.post_data or ""
        if '"dryRun":false' in body.replace(" ", "") and seen["n"] == 0:
            seen["n"] += 1
            seen["keys"].append(req.headers.get("idempotency-key"))
            route.fetch()                                   # 伺服器真的處理了……
            route.abort("connectionreset")                  # ……但回應掉了
        else:
            if '"dryRun":false' in body.replace(" ", ""):
                seen["keys"].append(req.headers.get("idempotency-key"))
            route.continue_()
    page.route("**/api/users/import-rows", drop_first_commit)
    page.get_by_test_id("iw-commit").click()
    page.get_by_test_id("iw-uncertain").wait_for(state="visible", timeout=15000)
    assert "沒有任何帳號被建立" not in page.inner_text("body"), "可能已經建立了，不能說沒有"
    assert page.get_by_test_id("iw-commit").is_disabled()
    import db
    c = db.get_db()
    try:
        assert c.execute("SELECT COUNT(*) AS n FROM users WHERE username IN ('iw_lost1','iw_lost2')").fetchone()["n"] == 2
    finally:
        c.close()
    page.get_by_test_id("iw-query").click()
    page.get_by_test_id("iw-replayed").wait_for(state="visible", timeout=15000)
    assert seen["keys"][0] and seen["keys"][0] == seen["keys"][1], "查詢要用同一把 key"
    assert page.locator(".iw-pw").count() == 0 or not page.get_by_test_id("iw-credentials").is_visible()
    assert "已建立 2 個帳號" in page.get_by_test_id("iw-result-summary").inner_text()
    page.get_by_test_id("iw-lost").wait_for(state="visible", timeout=5000)
    page.get_by_test_id("iw-reset-pw").first.click()
    page.get_by_test_id("iw-credentials").wait_for(state="visible", timeout=15000)
    pw = page.locator(".iw-pw").first.inner_text().strip()
    assert len(pw) >= 14
    r = requests.post(live_server + "/api/auth/login", json={"username": "iw_lost1", "password": pw}, timeout=15)
    assert r.status_code == 200, r.text


@pytest.mark.e2e
def test_credentials_csv_neutralizes_formula_cells_and_keeps_the_bom(live_server, make_user, new_page, login_as):
    _flag(True)
    page = _open(live_server, make_user, new_page, login_as, name="iw_sa6")
    page.evaluate("""() => { const d = %s; d.credentials = [
        {username: '=cmd|calc', displayName: '+SUM(1)', password: '@x1Y2z3W4v5U6t7'},
        {username: '-lead', displayName: '\tTab', password: 'Normal1Pass2Word'}]; }""" % DATA)
    with page.expect_download() as dl:
        page.evaluate("() => %s.downloadCredentials()" % DATA)
    raw = open(dl.value.path(), "rb").read()
    assert raw[:3] == b"\xef\xbb\xbf"
    text = raw.decode("utf-8-sig")
    assert '"\'=cmd|calc"' in text and '"\'+SUM(1)"' in text and '"\'@x1Y2z3W4v5U6t7"' in text
    assert '"\'-lead"' in text and "\"'\tTab\"" in text and '"Normal1Pass2Word"' in text
