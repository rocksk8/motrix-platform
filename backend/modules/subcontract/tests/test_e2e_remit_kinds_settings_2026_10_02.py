# -*- coding: utf-8 -*-
"""匯款款別設定頁（`remit-kinds-settings.html`；31-B S0）：開頁看到出貨預設四種 → 停用一個、新增一個（代碼規則提示）→ 勾派發狀態 →
驗證 → 存草稿（DB 有草稿）→ 發布（版本 1）→ 下拉 API 反映；已存在的款別沒有『移除』鈕（只能停用）、代碼不可改。
終點狀態＝畫面＋資料庫（ui_definitions.body_json）。"""
import json

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402


def _db(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args)]
    finally:
        c.close()


def _open(e2e_browser, base, user):
    page = e2e_browser.new_context(viewport={"width": 1400, "height": 1000}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, base, user[0], user[1])
    page.goto(base + "/pages/remit-kinds-settings.html")
    page.wait_for_selector("[data-testid=rk-table] tbody tr", timeout=20000)
    page.errors = errors
    return page


@pytest.mark.e2e
def test_superadmin_edits_validates_saves_and_publishes_remit_kinds(live_server, make_user, e2e_browser):
    u = make_user(username="rk_e2e_sa", role="superadmin", modules=[])
    page = _open(e2e_browser, live_server, u)
    assert "出貨預設" in page.inner_text("[data-testid=rk-version]")
    rows = page.locator("[data-testid=rk-row]")
    assert rows.count() == 4
    # 已存在的款別：代碼是固定文字、沒有「移除」鈕
    assert page.locator("[data-testid=rk-code-fixed]").count() == 4 and page.locator("[data-testid=rk-remove-new]:visible").count() == 0
    # 停用「進度款」
    progress = page.locator('[data-testid=rk-row][data-code=progress]')
    progress.locator("[data-testid=rk-active]").uncheck()
    # 新增款別：代碼格式提示 → 填對 → 勾完工
    page.click("[data-testid=rk-add]")
    new = rows.nth(4)
    new.locator("[data-testid=rk-name]").fill("保固金")
    new.locator("[data-testid=rk-code]").fill("Bad Code")
    assert "代碼只能用" in new.inner_text()
    new.locator("[data-testid=rk-code]").fill("retention")
    assert "代碼只能用" not in new.inner_text()
    # 沒勾任何派發狀態 ⇒ 伺服器驗證會擋
    page.click("[data-testid=rk-validate]")
    page.wait_for_selector("[data-testid=rk-problems] li", timeout=8000)
    assert "至少要有一個可開立" in page.inner_text("[data-testid=rk-problems]")
    new.locator("[data-testid=rk-stage-completed]").check()
    page.click("[data-testid=rk-validate]")
    page.wait_for_function("() => document.querySelector('[data-testid=rk-msg]').innerText.includes('驗證通過')", timeout=8000)
    # 存草稿 ⇒ DB 有草稿
    page.click("[data-testid=rk-save]")
    page.wait_for_function("() => document.querySelector('[data-testid=rk-msg]').innerText.includes('草稿已儲存')", timeout=10000)
    d = _db("SELECT status, body_json FROM ui_definitions WHERE kind='remit_kinds' AND key='default'")
    assert len(d) == 1 and d[0]["status"] == "draft"
    kinds = {k["code"]: k for k in json.loads(d[0]["body_json"])["kinds"]}
    assert kinds["progress"]["active"] is False and kinds["retention"]["stages"] == ["completed"] and kinds["retention"]["name"] == "保固金"
    # 比較（草稿 vs 出貨預設）看得到差異
    page.click("[data-testid=rk-changes]")
    page.wait_for_selector("[data-testid=rk-changes-list] li", timeout=8000)
    # 發布 ⇒ v1；下拉 API 反映
    page.fill("[data-testid=rk-note]", "停用進度款、加保固金")
    page.click("[data-testid=rk-publish]")
    page.wait_for_function("() => document.querySelector('[data-testid=rk-msg]').innerText.includes('已發布第 1 版')", timeout=10000)
    assert "第 1 版" in page.inner_text("[data-testid=rk-version]")
    pub = _db("SELECT version, status, note FROM ui_definitions WHERE kind='remit_kinds' AND key='default' AND status='published'")
    assert pub == [{"version": 1, "status": "published", "note": "停用進度款、加保固金"}]
    # 重新載入後：保固金已是『已存在』（代碼固定、沒有移除鈕），進度款維持停用
    page.reload()
    page.wait_for_selector("[data-testid=rk-table] tbody tr", timeout=20000)
    assert page.locator("[data-testid=rk-code-fixed]").count() == 5 and page.locator("[data-testid=rk-remove-new]:visible").count() == 0
    assert not page.locator('[data-testid=rk-row][data-code=progress] [data-testid=rk-active]').is_checked()
    assert page.locator("[data-testid=rk-versions]").count() == 1
    assert not page.errors, page.errors


@pytest.mark.e2e
def test_non_superadmin_cannot_read_or_write_the_settings(live_server, make_user, e2e_browser):
    u = make_user(username="rk_e2e_admin", role="admin")
    page = e2e_browser.new_context(viewport={"width": 1200, "height": 900}).new_page()
    inject_login(page, live_server, u[0], u[1])
    page.goto(live_server + "/pages/remit-kinds-settings.html")
    page.wait_for_timeout(2500)
    # 後端才是守門：不是最高管理者時，設定讀取 403、頁面沒有可編輯的表格（可能被導走、也可能顯示錯誤）
    assert page.locator("[data-testid=rk-table] tbody tr").count() == 0
    r = page.request.get(live_server + "/api/remit-kinds/definition", headers={"Authorization": "Bearer " + page.evaluate("() => JSON.parse(localStorage.getItem('motrix_session')).token")})
    assert r.status == 403
    r = page.request.put(live_server + "/api/definitions/remit_kinds/default/draft", data={"body": {"kinds": []}},
                         headers={"Authorization": "Bearer " + page.evaluate("() => JSON.parse(localStorage.getItem('motrix_session')).token")})
    assert r.status == 403
