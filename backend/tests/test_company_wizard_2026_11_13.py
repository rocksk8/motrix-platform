# -*- coding: utf-8 -*-
"""公司設定精靈（T84，2026-11-13）：靜態結構、428 放行清單原封不動、閘門導向、瀏覽器（1440／390）流程。"""
import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.company_gate]     # 預設測試環境關閘門；精靈的題目要閘門真的開著

FRONT = Path(__file__).resolve().parent.parent.parent / "frontend"
JS = FRONT / "static" / "company-wizard.js"

WIZARD_URL = "/pages/company-setup-wizard.html?setup=1"

# 目前放行清單的完整內容（T84 前後都不得變動：精靈只用清單內既有的端點，寄信信箱不在精靈內）。
EXPECTED_ALLOWED = {
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/auth/me"),
    ("PATCH", "/api/auth/change-password"),
    ("GET", "/api/ping"),
    ("GET", "/api/license/status"),
    ("GET", "/api/settings/company-profile"),
    ("PUT", "/api/settings/company-profile"),
    ("PUT", "/api/settings/branding/{kind}"),
    ("GET", "/api/settings/branding"),
    ("DELETE", "/api/settings/branding/{kind}"),
    ("GET", "/api/settings/company-setup/status"),
    ("GET", "/api/platform/menu"),
    ("GET", "/api/auth/totp/status"),
    ("POST", "/api/auth/totp/setup"),
    ("POST", "/api/auth/totp/enable"),
}


def _page(name):
    from core.source_tree import page_file
    return page_file(name).read_text(encoding="utf-8")


def _js():
    return JS.read_text(encoding="utf-8")


# ── 靜態 ───────────────────────────────────────────────────────────────────

def test_company_setup_allowlist_is_pinned_exactly(client):
    import main
    assert set(main._COMPANY_SETUP_ALLOWED) == EXPECTED_ALLOWED, "428 放行清單被改動：新增／移除端點要有 PM 裁示並同步這份清單"


def test_wizard_only_calls_allowlisted_endpoints(client):
    """精靈 JS 呼叫的 API 路徑都要在放行清單內（閘門生效時只有精靈能動）。"""
    import main
    allowed_paths = {p for _m, p in main._COMPANY_SETUP_ALLOWED}
    called = set(re.findall(r"""['"](/api/[A-Za-z0-9_/\-{}]+)""", _js()))
    assert called, "找不到任何 API 呼叫（正規式失效？）"
    for c in called:
        norm = c.rstrip("/")
        assert any(norm == a or a.startswith(norm + "/") or (a.endswith("{kind}") and norm.startswith(a[:-6])) for a in allowed_paths), norm


def test_wizard_js_never_uses_html_injection():
    src = _js()
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert bad not in src, bad


def test_wizard_has_five_steps_and_hint_markers_without_own_popover():
    src = _js()
    assert re.search(r"STEP_TITLES\s*=\s*\[[^\]]*\]", src)
    titles = re.search(r"STEP_TITLES\s*=\s*\[([^\]]*)\]", src).group(1)
    assert titles.count("'") // 2 == 5
    assert "data-hint" in src and "data-hint-label" in src
    assert "hint__pop" not in src and "hint__btn" not in src, "不自己做 popover（交給 hint-popover）"


def test_wizard_page_is_registered_and_gate_points_to_it():
    from helpers import company_setup as cs
    assert cs.SETTINGS_URL == WIZARD_URL
    root = Path(__file__).resolve().parent.parent
    assert "company-setup-wizard.html" in (root / "core" / "l1_pages.json").read_text(encoding="utf-8")
    assert "page:pages/company-setup-wizard.html" in (root.parent / "docs" / "platform" / "modules.json").read_text(encoding="utf-8")
    notif = (FRONT / "static" / "notif.js").read_text(encoding="utf-8")
    assert "company-setup-wizard.html?setup=1" in notif
    req = _page("company-setup-required.html")
    assert "company-setup-wizard.html?setup=1" in req
    old = _page("company-profile-settings.html")
    assert "company-setup-wizard.html?setup=1" in old, "舊頁的 ?setup=1 要導到精靈"


def test_wizard_page_loads_scripts_and_has_mobile_rules():
    html = _page("company-setup-wizard.html")
    assert "company-wizard.js" in html and "auth-guard.js" in html and "ux-wizard.js" in html
    assert "max-width:900px" in html and "min-height:44px" in html


def test_done_card_links_email_settings_and_getting_started():
    src = _js()
    assert "notification-settings.html" in src
    assert "getting-started.html" in src


def test_getting_started_company_step_links_to_wizard():
    from helpers import getting_started as GS
    by = {s["id"]: s for s in GS.STEPS}
    assert by["company"]["href"] == "company-setup-wizard.html"
    assert by["quote_style"]["href"].startswith("company-setup-wizard.html")


# ── 瀏覽器 ─────────────────────────────────────────────────────────────────

def _no_hscroll(page):
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"), \
        "橫向捲軸：" + str(page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]"))


def _profile_put_ok(page, action):
    with page.expect_response(lambda r: "/api/settings/company-profile" in r.url and r.request.method == "PUT") as resp:
        action()
    assert resp.value.status == 200
    return resp.value


@pytest.mark.e2e
@pytest.mark.parametrize("vw,vh", [(1440, 900), (390, 844)])
def test_full_flow_each_step_saves_then_resumes_then_done(client, live_server, make_user, new_page, login_as, vw, vh):
    from tests.test_company_setup_core_2026_09_28 import make_ubn
    from helpers import company_setup as cs
    cs.reset_cache()
    user = make_user(username="e2e_cw_full_%d" % vw, role="superadmin")
    page = new_page(viewport={"width": vw, "height": vh})
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    login_as(page, tuple(user)[:2])
    page.goto(f"{live_server}/pages/customers.html")
    page.wait_for_url("**/company-setup-wizard.html?setup=1", timeout=20000)      # 閘門：導到精靈
    page.locator("[data-testid=cw-card]").wait_for(state="visible", timeout=15000)
    _no_hscroll(page)
    assert page.locator("[data-testid=cw-title]").inner_text().startswith("先填公司的名稱")
    # 閘門生效時，放行清單以外的端點仍是 428（精靈是唯一能動的頁面）
    tok = client.post("/api/auth/login", json={"username": user[0], "password": user[1]}).json()["token"]
    r = client.get("/api/customers", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 428 and r.json().get("code") == "company_setup_required"

    # 步驟 1：名稱＋統編；每步各自儲存
    name = "精靈測試股份有限公司"
    ubn = make_ubn("2456789")
    assert page.locator("[data-testid=cw-next]").is_disabled()
    page.fill("[data-testid=cw-field-name]", name)
    page.fill("[data-testid=cw-field-tax_id]", "12345678")
    assert "檢查碼不符" in page.locator("[data-testid=cw-tax-msg]").inner_text()
    assert page.locator("[data-testid=cw-next]").is_disabled()
    page.fill("[data-testid=cw-field-tax_id]", ubn)
    assert "格式正確" in page.locator("[data-testid=cw-tax-msg]").inner_text()
    _profile_put_ok(page, lambda: page.click("[data-testid=cw-next]"))
    page.wait_for_function("document.querySelector('[data-testid=cw-title]').innerText.startsWith('客戶要怎麼聯絡')", timeout=10000)
    _no_hscroll(page)

    # 中途離開（只存了步驟 1）→ 重新載入，接在步驟 2
    page.goto(f"{live_server}{WIZARD_URL}")
    page.locator("[data-testid=cw-card]").wait_for(state="visible", timeout=15000)
    assert page.locator("[data-testid=cw-title]").inner_text().startswith("客戶要怎麼聯絡"), "要接在還沒做完的必填步驟"
    assert page.input_value("[data-testid=cw-field-phone]") == ""
    page.fill("[data-testid=cw-field-phone]", "02-8765-4321")
    _profile_put_ok(page, lambda: page.click("[data-testid=cw-next]"))
    # 步驟 3：看得到固定的單號格式說明；略過
    page.wait_for_function("document.querySelector('[data-testid=cw-title]').innerText.startsWith('客戶要把錢匯到哪裡')", timeout=10000)
    assert "MQ-" in page.locator("[data-testid=cw-numbering]").inner_text()
    _no_hscroll(page)
    page.click("[data-testid=cw-skip]")
    page.wait_for_function("document.querySelector('[data-testid=cw-title]').innerText.startsWith('放上公司 Logo')", timeout=10000)
    _no_hscroll(page)
    page.click("[data-testid=cw-skip]")
    page.locator("[data-testid=cw-summary]").wait_for(state="visible", timeout=10000)
    assert name in page.locator("[data-testid=cw-summary]").inner_text()
    assert ubn in page.locator("[data-testid=cw-summary]").inner_text()
    _no_hscroll(page)
    btn = page.locator("[data-testid=cw-confirm]")
    assert btn.is_disabled()
    page.check("[data-testid=cw-ack]")
    _profile_put_ok(page, lambda: btn.click())
    page.locator("[data-testid=cw-done]").wait_for(state="visible", timeout=10000)
    _no_hscroll(page)
    assert page.locator("[data-testid=wizard-email]").get_attribute("href") == "notification-settings.html"

    import db
    conn = db.get_db()
    try:
        assert cs.status(conn)["configured"] is True
    finally:
        conn.close()
    # 「開始使用」第 1 步（公司資料）自動打勾；放行後其他端點恢復
    from helpers import getting_started as GS
    steps = {x["id"]: x for x in GS.overview()["steps"]}
    assert steps["company"]["status"] == "done"
    assert client.get("/api/customers", headers={"Authorization": "Bearer " + tok}).status_code != 428
    # 再回精靈也不被導走（已設定）：能直接進，頁面不當掉
    page.goto(f"{live_server}/pages/customers.html")
    page.wait_for_load_state("networkidle")
    assert page.url.endswith("/pages/customers.html")
    assert not errs, errs


@pytest.mark.e2e
def test_wizard_is_the_only_working_page_while_gate_active(live_server, make_user, new_page, login_as):
    from helpers import company_setup as cs
    cs.reset_cache()
    user = make_user(username="e2e_cw_only", role="superadmin")
    page = new_page(viewport={"width": 390, "height": 844})
    login_as(page, tuple(user)[:2])
    page.goto(f"{live_server}/pages/quotations.html")
    page.wait_for_url("**/company-setup-wizard.html?setup=1", timeout=20000)
    page.locator("[data-testid=cw-card]").wait_for(state="visible", timeout=15000)
    # 精靈不會被再導一次（不迴圈）
    page.wait_for_timeout(1200)
    assert page.url.endswith("/company-setup-wizard.html?setup=1")
    _no_hscroll(page)


@pytest.mark.e2e
def test_old_settings_page_redirects_setup_param_to_wizard(live_server, make_user, new_page, login_as):
    from helpers import company_setup as cs
    cs.reset_cache()
    user = make_user(username="e2e_cw_redir", role="superadmin")
    page = new_page(viewport={"width": 1440, "height": 900})
    login_as(page, tuple(user)[:2])
    page.goto(f"{live_server}/pages/company-profile-settings.html?setup=1")
    page.wait_for_url("**/company-setup-wizard.html?setup=1", timeout=20000)


@pytest.mark.e2e
def test_non_superadmin_gets_plain_notice_not_a_form(live_server, make_user, new_page, login_as):
    from helpers import company_setup as cs
    cs.reset_cache()
    user = make_user(username="e2e_cw_clerk", role="admin")
    page = new_page(viewport={"width": 390, "height": 844})
    login_as(page, tuple(user)[:2])
    page.goto(f"{live_server}/pages/customers.html")
    page.wait_for_url("**/company-setup-required.html", timeout=20000)
    assert page.locator("[data-testid=cw-field-name]").count() == 0


@pytest.mark.e2e
def test_editing_required_field_after_confirmed_goes_to_reconfirm_step(client, live_server, make_user, new_page, login_as):
    """已確認的安裝再從精靈改必填欄位：後端回 409 company_setup_reconfirm ⇒ 精靈不存、跳到確認步驟，勾選後一併確認才存。"""
    from tests.test_company_setup_core_2026_09_28 import make_ubn
    from helpers import company_setup as cs
    import db
    cs.reset_cache()
    user = make_user(username="e2e_cw_reconf", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": user[0], "password": user[1]}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    ubn = make_ubn("2456789")
    assert client.put("/api/settings/company-profile", headers=h, json={
        "name": "原本股份有限公司", "tax_id": ubn, "phone": "02-1111-2222", "confirmIdentity": True}).status_code == 200
    cs.reset_cache()
    page = new_page(viewport={"width": 390, "height": 844})
    login_as(page, tuple(user)[:2])
    page.goto(f"{live_server}/pages/company-setup-wizard.html")
    page.locator("[data-testid=cw-card]").wait_for(state="visible", timeout=15000)
    page.click("[data-testid=cw-step-1]")
    page.fill("[data-testid=cw-field-name]", "改名後股份有限公司")
    with page.expect_response(lambda r: "/api/settings/company-profile" in r.url and r.request.method == "PUT") as resp:
        page.click("[data-testid=cw-next]")
    assert resp.value.status == 409
    page.locator("[data-testid=cw-summary]").wait_for(state="visible", timeout=10000)      # 跳到確認步驟
    conn = db.get_db()
    try:
        assert cs._get(conn, "company_profile")["name"] == "原本股份有限公司", "409 時不能已經存進去"
    finally:
        conn.close()
    page.check("[data-testid=cw-ack]")
    _profile_put_ok(page, lambda: page.click("[data-testid=cw-confirm]"))
    page.locator("[data-testid=cw-done]").wait_for(state="visible", timeout=10000)
    conn = db.get_db()
    try:
        assert cs._get(conn, "company_profile")["name"] == "改名後股份有限公司"
        assert cs.status(conn)["configured"] is True
    finally:
        conn.close()
    _no_hscroll(page)
