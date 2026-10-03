# -*- coding: utf-8 -*-
"""D12：新設計器在「模組建構器 ② 表單」與「請款類型編輯頁」都預設開（全新瀏覽器、沒有任何偏好）。
- 沒有網址參數、沒有 localStorage 偏好 ⇒ 設計器（.fd-paper）；`?designer=0` ⇒ 舊畫面；按「改用舊的…」會記住（下次不帶參數仍是舊畫面）
- 其他 e2e 預設釘在舊畫面（tests/_e2e_login.py LEGACY_UI_PINS）；本檔把釘子清掉，才是真正的「全新使用者」。
⚠️ 這只驗程式面；**真滑鼠拖放**（Playwright 對原生拖放只送 dragstart，e2e 用 dispatch_event 補，不能取代）要由人依
FORM-DESIGNER-PREVIEW-GUIDE.md 的 8 步驗證——列為上線前條件。"""
import pytest

pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.e2e

from tests._e2e_login import inject_login  # noqa: E402
from tests._builder_nav import go_step  # noqa: E402
from tests.test_e2e_form_designer_beginner_tasks_2026_10_02 import KEY, _body  # noqa: E402

FRESH = ("try { if (!sessionStorage.getItem('_d12_fresh')) { localStorage.removeItem('mb_designer'); localStorage.removeItem('et_designer');"
         " sessionStorage.setItem('_d12_fresh', '1'); } sessionStorage.setItem('_no_legacy_pin', '1'); } catch (e) {}")      # 只在這個分頁的第一次載入清（之後的偏好要能留住）


@pytest.fixture()
def fresh(live_server, client, make_user, new_context):
    u = make_user(username="d12_sa", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": u[0], "password": u[1]}).json()["token"]
    r = client.put("/api/definitions/custom_module/%s/draft" % KEY, json={"body": _body()}, headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 200, r.text
    ctx = new_context(viewport={"width": 1600, "height": 1000})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, u[0], u[1])
    return page, ctx, live_server, errors


def _unpin(ctx):
    ctx.add_init_script(FRESH)               # 在 inject_login 的釘子之後執行 ⇒ 全新使用者


def _et(page, base, query=""):
    page.goto(base + "/pages/expense-types.html" + query)
    page.wait_for_selector("[data-testid=et-new]", timeout=20000)
    page.wait_for_function("() => !document.body.innerText.includes('載入中…')", timeout=20000)
    page.click("[data-testid=et-open-travel]")


def test_expense_types_default_is_the_designer_and_designer0_goes_back_and_is_remembered(fresh):
    page, ctx, base, errors = fresh
    _unpin(ctx)
    _et(page, base)
    page.wait_for_selector(".fd .fd-paper", state="visible", timeout=20000)
    _et(page, base, "?designer=0")
    page.wait_for_selector("[data-testid=et-new-ui]", state="visible", timeout=20000)
    assert page.locator(".fd .fd-paper").count() == 0
    page.goto(base + "/pages/expense-types.html")                                # 回到有設計器的畫面後按「改用舊的」＝記住
    page.wait_for_selector("[data-testid=et-new]", timeout=20000)
    page.click("[data-testid=et-open-travel]")
    page.wait_for_selector("[data-testid=et-old-ui]", state="visible", timeout=20000)
    page.click("[data-testid=et-old-ui]")
    page.wait_for_selector("[data-testid=et-new-ui]", state="visible")
    page.goto(base + "/pages/expense-types.html")                                # 不帶參數：偏好 '0' 仍是舊畫面
    page.wait_for_selector("[data-testid=et-new]", timeout=20000)
    page.click("[data-testid=et-open-travel]")
    page.wait_for_selector("[data-testid=et-new-ui]", state="visible", timeout=20000)
    assert page.locator(".fd .fd-paper").count() == 0 and not errors


def test_module_builder_default_is_the_designer_and_designer0_is_the_old_canvas(fresh):
    page, ctx, base, errors = fresh
    _unpin(ctx)
    page.goto("%s/pages/module-builder.html?key=%s" % (base, KEY))
    page.wait_for_selector("#mb-step-1", state="visible")
    go_step(page, 2)
    page.wait_for_selector(".fd .fd-paper", state="visible", timeout=20000)
    page.goto("%s/pages/module-builder.html?key=%s&designer=0" % (base, KEY))
    page.wait_for_selector("#mb-step-1", state="visible")
    go_step(page, 2)
    page.wait_for_function("() => !!document.querySelector('#mb-step-2, [data-testid=mb-canvas]')", timeout=20000)
    assert page.locator(".fd .fd-paper").count() == 0 and not errors
