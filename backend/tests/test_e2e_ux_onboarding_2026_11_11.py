"""瀏覽器端對端：首次體驗與一致性（UX 提案 A1–A6、E1–E2，2026-11-11）。

驗的是「使用者看到什麼」（DOM／導向／可見性），每題對應提案的一項：
  A1 首次設定精靈：強制改密碼 → 重新登入 → 公司資料 → 兩步驟驗證（可略過）→ 儀表板；步驟條「步驟 n／N」、頂欄隱藏
  A2 公司資料閘門頁：只剩一張卡、統編即時驗證、確認後出現「下一步」卡
  A3 儀表板上手清單：帶進度、可收起、可從「？」重新打開
  A4 「第一次來？」橫幅：關掉後記住、從「？」重看
  A5 「？」說明抽屜：開／關（含 Esc）
  A6 送出審核前的「這會…」說明
  E1 空狀態三種（從未有資料／篩選後沒有／載入失敗）
  E2 「DB 已連線／MQ 系列」不再出現；建置戳記只給管理員
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import bootstrap_unavailable  # noqa: E402

from helpers import company_setup as cs  # noqa: E402
from tests.test_company_setup_core_2026_09_28 import make_ubn  # noqa: E402

NEW_PW = "NewPass#2026x"


def _must_change(username, on=1):
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET must_change_password=? WHERE username=?", (on, username))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _fresh():
    cs.reset_cache()
    yield
    cs.reset_cache()


def _wait_path(page, tail, timeout=30000):
    """等網址以 tail 結尾。不用 wait_for_url：登入後連續導向（login→index→目標頁）時它會因 ERR_ABORTED 丟錯。"""
    page.wait_for_function("t => (location.pathname + location.search).endsWith(t)", arg=tail, timeout=timeout)


def _help_ready(page):
    """「？」按鈕先出現、ux-help.js 隨後才載入：等它就緒再點（真人點得比這慢）。"""
    page.wait_for_function("() => !!window.MotrixUX", timeout=15000)


def _type_login(page, live_server, user, pw):
    page.goto(f"{live_server}/pages/login.html")
    page.fill("input[type=text]", user)
    page.fill("input[type=password]", pw)
    page.keyboard.press("Enter")


# ── A1／A2：首次設定精靈（最高管理者 4 步）────────────────────────────────────

@pytest.mark.e2e
@pytest.mark.company_gate
def test_first_run_wizard_superadmin_four_steps(live_server, make_user, new_page):
    username, password = make_user(username="e2e_ux_boss", role="superadmin")
    _must_change(username)
    page = new_page(viewport={"width": 1440, "height": 900})

    # 步驟 1：設新密碼——精簡外殼（沒有頂欄）、說明「為什麼」、TOTP 卡片先不出現
    _type_login(page, live_server, username, password)
    _wait_path(page, "/my-account.html?forced=1")
    page.locator("[data-testid=ux-wizard-count]").wait_for(state="visible", timeout=15000)
    assert page.locator("[data-testid=ux-wizard-count]").inner_text() == "步驟 1／4：設新密碼"
    assert not page.locator("#app-topbar").is_visible()
    assert "臨時密碼" in page.locator("[data-testid=ux-wizard-why]").inner_text()
    assert not page.locator("text=兩步驟驗證（TOTP）").is_visible()
    fields = page.locator("input[type=password]")
    fields.nth(0).fill(password)
    fields.nth(1).fill(NEW_PW)
    fields.nth(2).fill(NEW_PW)
    page.click("button[type=submit]")
    page.locator("text=步驟 1 完成").wait_for(state="visible", timeout=10000)

    # 被帶回登入頁：說明這是流程的一部分
    _wait_path(page, "/login.html")
    assert page.locator("[data-testid=wizard-login-note]").is_visible()
    page.fill("input[type=text]", username)
    page.fill("input[type=password]", NEW_PW)
    page.keyboard.press("Enter")

    # 步驟 2：公司資料閘門——只剩一張卡（原本 7000px 長頁）
    _wait_path(page, "/company-profile-settings.html?setup=1")
    page.locator("[data-company-setup-card]").wait_for(state="visible", timeout=15000)
    page.locator("[data-testid=ux-wizard-count]").wait_for(state="visible", timeout=15000)
    assert page.locator("[data-testid=ux-wizard-count]").inner_text() == "步驟 2／4：確認公司資料"
    assert not page.locator("#app-topbar").is_visible()
    visible_cards = page.evaluate("[...document.querySelectorAll('.ns-card')].filter(e => e.offsetParent !== null).length")
    assert visible_cards == 1, "閘門模式只該看到確認卡這一張"
    assert page.evaluate("document.documentElement.scrollHeight") <= 1400
    for sel in ("[data-brand-card]", "[data-privacy-notice-card]"):
        assert not page.locator(sel).is_visible()
    btn = page.locator("[data-company-setup-confirm]")
    assert btn.is_disabled()

    # 統編即時驗證：錯的說明原因，對的打勾
    page.fill("#gate-name", "愛思歐測試股份有限公司")
    page.fill("#gate-tax", "12345678")
    assert "檢查碼不符" in page.locator("[data-gate-tax-msg]").inner_text()
    ubn = make_ubn("2456789")
    page.fill("#gate-tax", ubn)
    assert "格式正確" in page.locator("[data-gate-tax-msg]").inner_text()
    page.fill("#gate-phone", "02-1234-5678")
    page.check("[data-company-setup-ack]")
    with page.expect_response(lambda r: "/api/settings/company-profile" in r.url and r.request.method == "PUT") as resp:
        btn.click()
    assert resp.value.status == 200
    done = page.locator("[data-company-setup-done]")
    done.wait_for(state="visible", timeout=10000)
    page.locator("[data-company-setup-card]").wait_for(state="hidden", timeout=10000)

    # 步驟 3：兩步驟驗證（可略過）——只剩 TOTP 卡，沒有密碼表單
    page.click("[data-testid=wizard-next]")
    _wait_path(page, "/my-account.html?wizard=totp")
    page.locator("[data-testid=ux-wizard-count]").wait_for(state="visible", timeout=15000)
    assert page.locator("[data-testid=ux-wizard-count]").inner_text() == "步驟 3／4：兩步驟驗證"
    page.locator("text=兩步驟驗證（TOTP）").wait_for(state="visible", timeout=10000)
    assert not page.locator("button:has-text('更新密碼')").is_visible()
    page.click("[data-testid=wizard-finish]")

    # 步驟 4：儀表板；精靈旗標清掉；不會緊接著跳出「尚未啟用兩步驟驗證」提醒
    _wait_path(page, "/index.html")
    page.wait_for_timeout(2500)
    assert page.evaluate("sessionStorage.getItem('motrix_wizard')") is None
    assert page.locator("#totp-reminder-banner").count() == 0
    assert page.locator("#app-topbar").is_visible()


@pytest.mark.e2e
def test_wizard_for_regular_user_has_two_steps(live_server, make_user, new_page):
    username, password = make_user(username="e2e_ux_clerk", role="sales")
    _must_change(username)
    page = new_page(viewport={"width": 1440, "height": 900})
    _type_login(page, live_server, username, password)
    _wait_path(page, "/my-account.html?forced=1")
    page.locator("[data-testid=ux-wizard-count]").wait_for(state="visible", timeout=15000)
    assert page.locator("[data-testid=ux-wizard-count]").inner_text() == "步驟 1／2：設新密碼"
    # 一般使用者不留精靈旗標（後面沒有別的步驟）
    assert page.evaluate("sessionStorage.getItem('motrix_wizard')") is None


@pytest.mark.e2e
def test_plain_change_password_page_is_not_a_wizard(live_server, make_user, new_page, login_as):
    username, password = make_user(username="e2e_ux_plain", role="sales")
    page = new_page(viewport={"width": 1440, "height": 900})
    login_as(page, (username, password))
    page.goto(f"{live_server}/pages/my-account.html?tab=security")
    page.locator("h1:has-text('我的帳號')").wait_for(state="visible", timeout=15000)
    assert page.locator("[data-testid=ux-wizard]").count() == 0
    assert page.locator("#app-topbar").is_visible()
    assert page.locator("text=兩步驟驗證（TOTP）").is_visible()


@pytest.mark.e2e
@pytest.mark.company_gate
def test_gate_card_edits_the_identity_that_actually_takes_effect(live_server, make_user, new_page, login_as):
    """R1（K 審 hichan-11）：複製／搬家來的舊庫已經有據點，而後端的身分是「主要據點欄位優先、頂層只是後備」。
    閘門卡顯示的要是生效的那一份（據點裡的舊名／示範統編），改完確認後，生效的身分要是新的——不能只改頂層而被據點蓋回去。"""
    import db
    from helpers import company_identity as ci
    conn = db.get_db()
    try:
        cs._set(conn, "company_profile", {
            "name": "舊公司股份有限公司", "tax_id": "", "phone": "",
            "locations": [{"id": "loc-1", "name": "總公司", "address": "台中市", "company_name": "舊公司股份有限公司",
                           "tax_id": "00000000", "phone": "02-0000-0000"},
                          {"id": "loc-2", "name": "分公司", "address": "高雄市"}]})
        conn.commit()
    finally:
        conn.close()
    cs.reset_cache()
    username, password = make_user(username="e2e_ux_gate_loc", role="superadmin")
    page = new_page(viewport={"width": 1440, "height": 900})
    login_as(page, (username, password))
    page.goto(f"{live_server}/pages/company-profile-settings.html?setup=1")
    page.locator("[data-company-setup-card]").wait_for(state="visible", timeout=15000)
    # 顯示的是生效的那一份（據點[0]），不是頂層空白
    assert page.input_value("#gate-name") == "舊公司股份有限公司"
    assert page.input_value("#gate-tax") == "00000000"
    assert "保留" in page.locator("[data-gate-tax-msg]").inner_text()     # N1：示範統編不能被當成「格式正確」
    assert page.locator("[data-company-setup-confirm]").is_disabled()
    ubn = make_ubn("2456789")
    page.fill("#gate-name", "新公司股份有限公司")
    page.fill("#gate-tax", ubn)
    page.fill("#gate-phone", "02-1234-5678")
    page.check("[data-company-setup-ack]")
    with page.expect_response(lambda r: "/api/settings/company-profile" in r.url and r.request.method == "PUT") as resp:
        page.click("[data-company-setup-confirm]")
    assert resp.value.status == 200
    page.locator("[data-company-setup-done]").wait_for(state="visible", timeout=10000)
    conn = db.get_db()
    try:
        saved = cs._get(conn, "company_profile")
    finally:
        conn.close()
    ident = ci.identity_from_profile(saved)
    assert ident["company_name"] == "新公司股份有限公司"
    assert ident["tax_id"] == ubn
    assert ident["phone"] == "02-1234-5678"
    assert saved["locations"][1].get("company_name") in (None, ""), "沒填身分的第二據點不該被動到"


# ── A4／A5：橫幅與「？」抽屜 ────────────────────────────────────────────────

@pytest.mark.e2e
def test_first_visit_hint_dismiss_persist_and_replay(live_server, make_user, new_page, login_as):
    username, password = make_user(username="e2e_ux_hint", role="superadmin")
    page = new_page(viewport={"width": 1440, "height": 900})
    login_as(page, (username, password))
    for name in ("quotations", "quotation-form", "approval-queue", "approval-settings"):
        page.goto(f"{live_server}/pages/{name}.html")
        page.locator("[data-testid=ux-first-hint]").wait_for(state="visible", timeout=15000)
    page.goto(f"{live_server}/pages/quotations.html")
    hint = page.locator("[data-testid=ux-first-hint]")
    hint.wait_for(state="visible", timeout=15000)
    hint.locator("[data-ux=dismiss]").click()
    assert hint.count() == 0
    page.reload()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)
    assert page.locator("[data-testid=ux-first-hint]").count() == 0, "關掉之後重新整理不該再出現"
    # 從「？」重看
    _help_ready(page)
    page.click("#ux-help-btn")
    drawer = page.locator("[data-testid=ux-drawer] .ux-drawer__panel")
    drawer.wait_for(state="visible", timeout=5000)
    page.locator("[data-testid=ux-drawer] [data-ux=replay]").click()
    page.locator("[data-testid=ux-first-hint]").wait_for(state="visible", timeout=5000)
    drawer.wait_for(state="hidden", timeout=5000)


@pytest.mark.e2e
def test_help_drawer_opens_closes_and_has_page_specific_content(live_server, make_user, new_page, login_as):
    username, password = make_user(username="e2e_ux_drawer", role="superadmin")
    page = new_page(viewport={"width": 1440, "height": 900})
    login_as(page, (username, password))
    page.goto(f"{live_server}/pages/quotations.html")
    btn = page.locator("#ux-help-btn")
    btn.wait_for(state="visible", timeout=15000)
    _help_ready(page)
    assert btn.get_attribute("aria-expanded") == "false"
    btn.click()
    drawer = page.locator("[data-testid=ux-drawer] .ux-drawer__panel")
    drawer.wait_for(state="visible", timeout=5000)
    assert btn.get_attribute("aria-expanded") == "true"
    text = drawer.inner_text()
    assert "報價單" in text and "最常見的做法" in text and "已成案" in text      # 本頁內容＋名詞解釋
    page.keyboard.press("Escape")
    drawer.wait_for(state="hidden", timeout=5000)
    assert btn.get_attribute("aria-expanded") == "false"
    # 沒寫專屬內容的頁面也有通用說明，不是空白
    page.goto(f"{live_server}/pages/daily-tasks.html")
    _help_ready(page)
    page.locator("#ux-help-btn").click()
    page.locator("[data-testid=ux-drawer] .ux-drawer__panel").wait_for(state="visible", timeout=5000)
    assert "搜尋框" in page.locator("[data-testid=ux-drawer] .ux-drawer__panel").inner_text()


# ── A3：儀表板上手清單 ─────────────────────────────────────────────────────

@pytest.mark.e2e
def test_dashboard_checklist_progress_dismiss_and_reopen(live_server, make_user, new_page, login_as, client):
    username, password = make_user(username="e2e_ux_check", role="superadmin")
    page = new_page(viewport={"width": 1440, "height": 900})
    sess = login_as(page, (username, password))
    page.goto(f"{live_server}/index.html")
    box = page.locator("[data-testid=onboarding-checklist]")
    box.wait_for(state="visible", timeout=20000)
    prog = page.locator("[data-testid=checklist-progress]").inner_text()
    assert prog.endswith("完成") and " / " in prog
    done0 = int(prog.split("/")[0])
    # 建一位客戶 ⇒ 「建立第一筆客戶」打勾，進度 +1（清單由資料判定，不是手動勾）
    h = {"Authorization": "Bearer " + sess["token"]}
    assert client.post("/api/customers", json={"name": "清單測試客戶"}, headers=h).status_code in (200, 201)
    page.reload()
    box.wait_for(state="visible", timeout=20000)
    assert page.locator("[data-testid=checklist-customer]").get_attribute("class").count("is-done") == 1
    assert int(page.locator("[data-testid=checklist-progress]").inner_text().split("/")[0]) == done0 + 1
    # 收起 ⇒ 重新整理仍收著；從「？」可重新打開
    page.click("[data-testid=checklist-dismiss]")
    box.wait_for(state="hidden", timeout=5000)
    page.reload()
    page.wait_for_timeout(2500)
    assert not page.locator("[data-testid=onboarding-checklist]").is_visible()
    _help_ready(page)
    page.click("#ux-help-btn")
    page.locator("[data-testid=ux-drawer] [data-ux=checklist]").click()
    page.locator("[data-testid=onboarding-checklist]").wait_for(state="visible", timeout=10000)


@pytest.mark.e2e
def test_checklist_does_not_remember_a_failed_stats_load(live_server, make_user, new_page, login_as):
    """R2（K 審 hichan-11）：統計讀失敗時 totalQuotes 停在預設 0——不可以把它當成「全新系統」而把「看過清單」旗標寫進瀏覽器，
    否則之後網路好了，有大量資料的老使用者會一直看到新手清單。"""
    username, password = make_user(username="e2e_ux_check_fail", role="superadmin")
    page = new_page(viewport={"width": 1440, "height": 900})
    login_as(page, (username, password))
    page.route("**/api/dashboard/stats*", lambda route: route.fulfill(status=500, body="{}"))
    page.goto(f"{live_server}/index.html")
    page.wait_for_timeout(3000)
    assert not page.locator("[data-testid=onboarding-checklist]").is_visible()
    keys = page.evaluate("Object.keys(localStorage).filter(k => k.startsWith('motrix_ux_check_started_'))")
    assert keys == [], "統計沒讀到時不該寫下「全新系統」的旗標：%s" % keys


# ── A6：送出審核前的說明 ───────────────────────────────────────────────────

@pytest.mark.e2e
def test_submit_modal_explains_the_consequence(live_server, make_user, new_page, login_as):
    username, password = make_user(username="e2e_ux_submit", role="superadmin")
    page = new_page(viewport={"width": 1440, "height": 900})
    login_as(page, (username, password))
    page.goto(f"{live_server}/pages/quotation-form.html")
    page.locator(".form-toolbar").wait_for(state="visible", timeout=20000)
    # 送出鈕有「這會…」提示（title）；確認視窗第一段說明後果
    btn = page.locator("button.btn:has-text('申請送出簽核')")
    btn.wait_for(state="visible", timeout=15000)
    assert "簽核" in (btn.get_attribute("title") or "")
    page.evaluate("Alpine.$data(document.querySelector('[x-data]')).showSubmitModal = true")
    cons = page.locator("[data-testid=qf-submit-consequence]")
    cons.wait_for(state="visible", timeout=5000)
    assert "通知對方" in cons.inner_text() and "已成案" in cons.inner_text()
    page.evaluate("Alpine.$data(document.querySelector('[x-data]')).showSubmitModal = false")
    # 取消折讓：按鈕 title 說明會清成 0
    toggle = page.locator(".toggle-btn:has-text('申請折讓')")
    toggle.click()
    assert "清成 0" in page.locator(".toggle-btn:has-text('取消折讓')").get_attribute("title")


# ── E1：空狀態三種 ─────────────────────────────────────────────────────────

def _seed_quote(no="MQ-202611-777", name="空狀態客戶"):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, "
            "created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (no, "草稿", name, "專案", 100, 95,
             json.dumps({"quoteNo": no, "customerName": name, "status": "草稿", "items": [], "tot": {}},
                        ensure_ascii=False),
             "2026-11-01T00:00:00", "2026-11-01T00:00:00", "", "2026-11-01"),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.e2e
def test_quotations_empty_states_three_kinds(live_server, make_user, new_page, login_as):
    username, password = make_user(username="e2e_ux_empty", role="superadmin")
    page = new_page(viewport={"width": 1440, "height": 900})
    login_as(page, (username, password))

    # ① 從未有資料：說明用途＋主按鈕；不說「重試」
    page.goto(f"{live_server}/pages/quotations.html")
    none = page.locator("[data-testid=empty-none]")
    none.wait_for(state="visible", timeout=20000)
    assert "新增第一張報價單" in none.inner_text()
    assert "自動重試" not in page.locator("body").inner_text()
    page.locator("[data-testid=empty-error]").wait_for(state="hidden", timeout=5000)

    # E2：工程師用語不再出現
    body = page.locator("body").inner_text()
    assert "DB 已連線" not in body and "MQ 系列" not in body

    # ② 有資料、篩選後沒有：說明＋清除篩選
    _seed_quote()
    page.reload()
    page.wait_for_load_state("networkidle")
    page.wait_for_function("Alpine.$data(document.querySelector('[x-data]')).quotes.length > 0", timeout=15000)
    page.locator("input[x-model='search']").first.fill("絕對找不到的字串zzz")
    filt = page.locator("[data-testid=empty-filtered]")
    filt.wait_for(state="visible", timeout=10000)
    page.locator("[data-testid=empty-none]").wait_for(state="hidden", timeout=5000)
    filt.locator("[data-testid=empty-clear-filters]").click()
    # 偶發紅燈（T79-FLAKE-ONBOARDING-EMPTY-STATES）的根因：Alpine 3.17 的 x-show 隱藏要等約一個動畫影格（實測點擊後 ~11–14ms）才生效，
    # 而 Playwright 點擊→is_visible() 的來回也是這個量級 ⇒ 這裡不能「點完立刻斷言」。改等終態；
    # 真的沒清掉篩選（filtered 仍為 0）時 5 秒後照樣逾時判失敗。
    filt.wait_for(state="hidden", timeout=5000)
    page.locator("text=空狀態客戶").first.wait_for(state="visible", timeout=5000)

    # ③ 載入失敗：才用「重試」，並說明原因
    page.route("**/api/quotations?*", lambda route: route.abort())
    page.reload()
    err = page.locator("[data-testid=empty-error]")
    err.wait_for(state="visible", timeout=20000)
    assert "重試" in err.inner_text() and "載入失敗" in err.inner_text()
    page.locator("[data-testid=empty-none]").wait_for(state="hidden", timeout=5000)


# ── E2：建置戳記只給管理員 ──────────────────────────────────────────────────

_BUILD_INFO = {"commit": "abc1234def", "commit_short": "abc1234", "started_at": "2026-11-11T10:00:00", "stale": False}


@pytest.mark.e2e
def test_build_footer_is_admin_only(live_server, make_user, new_page, login_as):
    """同一份 /api/build-info 回應：管理員看得到戳記，一般同仁沒有（內容是維運資訊，不是給使用者的）。"""
    admin = make_user(username="e2e_ux_foot_admin", role="superadmin")
    sales = make_user(username="e2e_ux_foot_sales", role="sales")
    route = lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(_BUILD_INFO))  # noqa: E731

    pa = new_page(viewport={"width": 1440, "height": 900})
    login_as(pa, admin)
    bootstrap_unavailable(pa)            # 攔的是原端點 /api/build-info；bootstrap 開著時第一趟由它供應（真值，不是替身）
    pa.route("**/api/build-info", route)
    pa.goto(f"{live_server}/pages/customers.html")
    pa.locator("#build-footer").wait_for(state="visible", timeout=15000)
    assert "abc1234" in pa.locator("#build-footer").inner_text()

    ps = new_page(viewport={"width": 1440, "height": 900})
    login_as(ps, sales)
    bootstrap_unavailable(ps)
    ps.route("**/api/build-info", route)
    ps.goto(f"{live_server}/pages/customers.html")
    ps.locator("#app-topbar").wait_for(state="visible", timeout=15000)
    ps.wait_for_timeout(2000)
    assert ps.locator("#build-footer").count() == 0, "一般同仁不該看到建置戳記"
