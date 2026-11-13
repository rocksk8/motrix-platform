"""手機版（375／390／430 寬）案件管理頁＋頂欄＋主選單＋徽章（2026-11-13；基底＝ui/mobile-tablet-combined 的頂欄「⋯」實作）。

① 案件清單：`.cm-list` 在 ≤767px 設 max-height:44vh＋overflow:hidden，清單標頭佔 ~320px，內層只剩 70–148px ⇒ 4 件只看得到半張卡片。
② 主選單：手機改「☰ 主選單」鈕＋左側抽屜（群組手風琴），每個群組都點得到；768–1023px 維持橫向捲動＋右緣漸層；桌機不變。
③ 頂欄（combined 的「⋯」面板）：字級 小／標／大 × 淺／深 × 375／390／430 全部放得下（⋯ 不被切、搜尋框 ≥96px）；
   觸控目標實際畫面 ≥44px；通知鈴手機只留圖示；面板外點（含非互動區）收合、Esc 收合並把焦點還給 ⋯、面板內切換深淺色不收合；
   面板內容在 DOM 順序上排在 ⋯ 之後（桌機版面不變）。
④ 數字徽章：一位數正圓、兩位數膠囊（`.mbadge`；flex:none、高 20px、min-width＝高）。
⑤ WebKit（iPhone 描述檔）：外點收合在 iOS 引擎上同樣有效（有安裝 WebKit 才跑；`MOTRIX_WEBKIT_PATH` 可指定瀏覽器目錄）。
"""
from tests._requires import requires_module  # noqa: E402
import json
import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

pytestmark = requires_module("case", "本檔的題打 M01（案件）的頁面與資料")

_MAKE_USER_DEFAULT_ROLE = "superadmin"  # 要看得到「在線」鈕（只有最高管理者有）

N_CASES = 4
PAGES = ("case-management.html", "customers.html", "suppliers.html", "quotations.html")


def _seed_cases():
    import db
    conn = db.get_db()
    try:
        for i in range(1, N_CASES + 1):
            cr = {"stages": [{"label": "訂單確認"}]}
            conn.execute(
                "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
                " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (f"MQ-MOB-{i:03d}", "已送出", f"手機測試客戶{i}", f"專案{i}", 100000, 95238,
                 json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False),
                 "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "2026-08-01"))
        conn.commit()
    finally:
        conn.close()


def _ctx(browser, w, h, mobile=True, fz=1.0, dark=False):
    ctx = browser.new_context(viewport={"width": w, "height": h}, is_mobile=mobile, has_touch=mobile)
    ctx.add_init_script("try{localStorage.setItem('motrix_font_zoom','%s');%s}catch(e){}" % (
        fz, "localStorage.setItem('motrix_theme','dark');" if dark else "localStorage.removeItem('motrix_theme');"))
    return ctx


def _goto(page, base, name, wait=".mnav__in"):
    page.goto(f"{base}/pages/{name}")
    page.wait_for_selector("#app-topbar .topbar__right", timeout=15000)
    page.wait_for_selector("#app-mainnav " + wait, state="attached", timeout=10000)
    page.wait_for_timeout(250)


def _open(browser, base, user, w, h, mobile=True, name="case-management.html", **kw):
    ctx = _ctx(browser, w, h, mobile, **kw)
    page = ctx.new_page()
    inject_login(page, base, *user)
    _goto(page, base, name)
    if name == "case-management.html":
        page.locator(".cm-card").first.wait_for(state="visible", timeout=20000)
    return page


# ── ① 案件清單 ───────────────────────────────────────────────────────────────

@pytest.mark.e2e
@pytest.mark.parametrize("w,h", [(375, 667), (390, 844)])
def test_phone_case_list_shows_every_card_not_a_squashed_strip(live_server, make_user, e2e_browser, w, h):
    u = make_user(username=f"mob_list_{w}")
    _seed_cases()
    page = _open(e2e_browser, live_server, u, w, h)
    m = page.evaluate("""() => {
      const body = document.querySelector('.cm-list__body');
      const cs = getComputedStyle(body), ls = getComputedStyle(document.querySelector('.cm-list'));
      const cards = [...document.querySelectorAll('.cm-card')].filter(e => e.offsetParent !== null);
      return {n: cards.length, bodyOv: cs.overflowY, listOv: ls.overflowY, listMax: ls.maxHeight,
              bodyClipped: body.scrollHeight > body.clientHeight + 1,
              cardsH: cards.map(e => Math.round(e.getBoundingClientRect().height)),
              docW: document.documentElement.scrollWidth, vw: innerWidth};
    }""")
    assert m["n"] == N_CASES, m
    assert m["listMax"] == "none" and m["listOv"] == "visible" and m["bodyOv"] == "visible", "手機清單不可再自成小捲動區／被 vh 上限壓扁：%r" % m
    assert not m["bodyClipped"], m
    assert all(hh > 60 for hh in m["cardsH"]), "卡片被壓扁：%r" % m
    assert m["docW"] <= m["vw"], "頁面水平溢出：%r" % m
    last = page.locator(".cm-card").nth(N_CASES - 1)
    last.scroll_into_view_if_needed()
    box = last.bounding_box()
    assert box and 0 <= box["y"] and box["y"] + box["height"] <= h + 1, (box, h)


# ── ② 主選單抽屜 ─────────────────────────────────────────────────────────────

@pytest.mark.e2e
@pytest.mark.parametrize("w,h", [(375, 667), (390, 844)])
def test_phone_main_menu_is_a_drawer_and_every_group_is_reachable(live_server, make_user, e2e_browser, w, h):
    u = make_user(username=f"mob_nav_{w}")
    _seed_cases()
    page = _open(e2e_browser, live_server, u, w, h)
    st = page.evaluate("""() => { const b = document.querySelector('.mnav__burger'), d = document.querySelector('.mnav__in');
      const bs = getComputedStyle(b), ds = getComputedStyle(d);
      return {burger: bs.display, drawerVis: ds.visibility, drawerPos: ds.position, docW: document.documentElement.scrollWidth, vw: innerWidth} }""")
    assert st["burger"] == "flex" and st["drawerVis"] == "hidden" and st["drawerPos"] == "fixed", st
    assert st["docW"] <= st["vw"], "頁面水平溢出：%r" % st
    page.click(".mnav__burger")
    page.wait_for_function("() => getComputedStyle(document.querySelector('.mnav__in')).visibility === 'visible'", timeout=3000)
    assert page.get_attribute(".mnav__burger", "aria-expanded") == "true"
    r = page.evaluate("""() => { const tops = [...document.querySelectorAll('.mnav__in > .mnav__grp > .mnav__top, .mnav__in > a.mnav__top')];
      return tops.map(t => { const x = t.getBoundingClientRect(); return {t: t.textContent.trim(), h: Math.round(x.height), r: Math.round(x.right)} }) }""")
    assert len(r) >= 3, r
    assert all(x["h"] >= 44 and x["r"] <= w for x in r), "抽屜裡的群組標題要夠高、不超出視窗：%r" % r
    grp = page.locator(".mnav__in > .mnav__grp").last
    grp.locator("> .mnav__top").scroll_into_view_if_needed()
    grp.locator("> .mnav__top").click()
    assert page.evaluate("() => !!document.querySelector('.mnav__grp.is-open')")
    it = grp.locator(".mnav__item").first
    it.scroll_into_view_if_needed()
    box = it.bounding_box()
    assert box and box["x"] >= 0 and box["x"] + box["width"] <= w and box["height"] >= 40, box
    page.click(".mnav__backdrop", position={"x": w - 5, "y": 200})
    page.wait_for_function("() => !document.querySelector('#app-mainnav').classList.contains('mnav--open')", timeout=3000)
    page.click(".mnav__burger")
    page.keyboard.press("Escape")
    page.wait_for_function("() => !document.querySelector('#app-mainnav').classList.contains('mnav--open')", timeout=3000)
    assert page.evaluate("() => document.activeElement && document.activeElement.classList.contains('mnav__burger')"), "Esc 後焦點要回到 ☰ 鈕"


@pytest.mark.e2e
def test_tablet_width_keeps_scroll_menu_with_fade(live_server, make_user, e2e_browser):
    """768–1023px 仍是橫向捲動選單（右緣漸層提示）；漢堡抽屜只用在手機（≤767px）。"""
    u = make_user(username="mob_nav_tab")
    page = _open(e2e_browser, live_server, u, 800, 900, mobile=False, name="customers.html")
    info = page.evaluate("""() => [getComputedStyle(document.querySelector('.mnav__burger')).display,
                                   getComputedStyle(document.querySelector('#app-mainnav'), '::after').content,
                                   getComputedStyle(document.querySelector('.mnav__in')).position]""")
    assert info[0] == "none" and info[1] != "none" and info[2] != "fixed", info


# ── ③ 頂欄矩陣 ───────────────────────────────────────────────────────────────

_TB = """() => {
  const q = s => document.querySelector(s), tb = q('#app-topbar');
  const vis = e => { if (!e) return null; const b = e.getBoundingClientRect(); return {l: b.left, r: b.right, w: b.width, h: b.height, d: getComputedStyle(e).display} };
  const z = parseFloat(getComputedStyle(document.documentElement).zoom) || 1;
  const bell = q('#app-topbar .topbar__right > div[x-data] > button');
  return {z, vw: innerWidth, docW: document.documentElement.scrollWidth, tbSW: tb.scrollWidth, tbCW: tb.clientWidth,
          more: vis(q('#tb-more')), search: vis(q('#app-topbar input.global-search-input')), bell: vis(bell),
          lbl: vis(q('#app-topbar .tb-lbl')), avatar: vis(q('#tb-avatar'))};
}"""


@pytest.mark.e2e
@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
@pytest.mark.parametrize("fz", [0.85, 1.0, 1.15], ids=["small", "std", "large"])
@pytest.mark.parametrize("w,h", [(375, 667), (390, 844), (430, 932)])
def test_phone_topbar_matrix_fits_and_targets_are_44(live_server, make_user, e2e_browser, w, h, fz, dark):
    u = make_user(username=f"mob_tb_{w}_{int(fz * 100)}_{int(dark)}")
    ctx = _ctx(e2e_browser, w, h, True, fz=fz, dark=dark)
    page = ctx.new_page()
    inject_login(page, live_server, *u)
    for name in ("index.html", "case-management.html", "customers.html", "suppliers.html"):
        page.goto(f"{live_server}/{'' if name == 'index.html' else 'pages/'}{name}")
        page.wait_for_selector("#app-topbar .topbar__right", timeout=15000)
        page.wait_for_timeout(250)
        m = page.evaluate(_TB)
        tag = (name, w, fz, dark, m)
        assert m["tbSW"] <= m["tbCW"] + 1, "頂欄內容放不下（⋯／頭像被擠出畫面）：%r" % (tag,)
        assert m["vw"] == w and m["docW"] <= m["vw"] + 1, "頁面水平溢出／版面視窗被內容撐寬（L4：customers／suppliers 曾排成 584 寬）：%r" % (tag,)
        assert m["more"] and m["more"]["d"] != "none" and m["more"]["r"] <= m["vw"] + 0.5, "⋯ 被切到畫面外：%r" % (tag,)
        assert m["search"]["w"] / m["z"] >= 80, "搜尋框被擠到不能用（<80px）：%r" % (tag,)
        assert m["lbl"] is None or m["lbl"]["d"] == "none", "手機通知鈴只留圖示：%r" % (tag,)
        for k in ("more", "bell", "avatar"):
            assert m[k]["h"] >= 43.5 and m[k]["w"] >= 43.5, "觸控目標 <44px（%s）：%r" % (k, (m[k], tag[:4]))
        assert m["search"]["h"] >= 43.5, tag
    ctx.close()


@pytest.mark.e2e
def test_more_panel_interactions(live_server, make_user, e2e_browser):
    """面板：外點（含非互動區）收合；Esc 收合＋焦點回 ⋯；面板內切換深淺色不收合；面板項目在 DOM 順序上排在 ⋯ 之後；面板內控制項 ≥44px。"""
    u = make_user(username="mob_more_ix")
    page = _open(e2e_browser, live_server, u, 390, 844, name="customers.html")
    st = lambda: page.evaluate("() => [document.querySelector('#app-topbar').classList.contains('tb-more-open'), document.querySelector('#tb-more').getAttribute('aria-expanded')]")
    order = page.evaluate("() => { const more = document.querySelector('#tb-more'), sec = document.querySelector('#tb-sec'); return !!(more.compareDocumentPosition(sec) & Node.DOCUMENT_POSITION_FOLLOWING) }")
    assert order, "面板內容要排在 ⋯ 之後（DOM 順序）"
    page.click("#tb-more")
    assert st() == [True, "true"]
    sizes = page.evaluate("""() => [...document.querySelectorAll('#tb-sec button, #tb-sec a')].filter(e => e.offsetParent !== null)
      .map(e => { const b = e.getBoundingClientRect(); return [e.id || e.textContent.trim().slice(0, 6), Math.round(b.height)] })""")
    assert sizes and all(h >= 43 for _, h in sizes), "面板內控制項觸控目標 <44px：%r" % sizes
    # L1：面板內切換深淺色，面板不收合
    page.click("#theme-toggle-btn")
    page.wait_for_timeout(200)
    assert st() == [True, "true"], "切換深色模式後面板不該收起"
    # M2：點面板外的非互動區（頁面標題區）要收合
    page.mouse.click(200, 700)
    page.wait_for_function("() => !document.querySelector('#app-topbar').classList.contains('tb-more-open')", timeout=3000)
    assert st() == [False, "false"]
    # M3：Esc 收合、aria-expanded 設回 false、焦點回 ⋯
    page.click("#tb-more")
    page.keyboard.press("Escape")
    assert st() == [False, "false"]
    assert page.evaluate("() => document.activeElement && document.activeElement.id") == "tb-more"


# ── 頭像個人選單 ──────────────────────────────────────────────────────────────

@pytest.mark.e2e
@pytest.mark.parametrize("w,h,mobile", [(1400, 900, False), (390, 844, True)], ids=["desktop", "phone"])
def test_avatar_menu_content_and_a11y(live_server, make_user, e2e_browser, w, h, mobile):
    """頭像（姓氏圓圈）＝按鈕，展開「修改密碼／登出」（我的帳號頁未上線時不列）；頂端姓名＋職務中文名；
    Esc 收合並把焦點還給頭像、aria-expanded 同步、外點收合；頂欄不再有獨立的修改密碼／登出；手機觸控目標 ≥44px。"""
    u = make_user(username=f"mob_acct_{w}")
    page = _open(e2e_browser, live_server, u, w, h, mobile=mobile, name="customers.html")
    ex = lambda: page.evaluate("() => [!document.querySelector('#tb-acct-menu').hidden, document.querySelector('#tb-avatar').getAttribute('aria-expanded')]")
    assert page.evaluate("() => !document.querySelector('#app-topbar .topbar__right > button[onclick*=motrixLogout]') && !document.querySelector('#app-topbar .topbar__right > a[href*=change-password]') && !document.querySelector('#tb-sec a[href*=change-password]') && !document.querySelector('#tb-sec button[onclick*=motrixLogout]')"), "獨立的登出／修改密碼不該還在頂欄"
    assert page.evaluate("() => document.querySelector('#tb-avatar').tagName") == "BUTTON"
    assert ex() == [False, "false"]
    page.click("#tb-avatar")
    assert ex() == [True, "true"]
    info = page.evaluate("""() => { const m = document.querySelector('#tb-acct-menu');
      return {role: m.getAttribute('role'), head: m.querySelector('.acct__head').textContent.trim(),
              items: [...m.querySelectorAll('[role=menuitem]')].map(e => [e.textContent.trim(), Math.round(e.getBoundingClientRect().height), e.getAttribute('href')]),
              right: Math.round(m.getBoundingClientRect().right), vw: innerWidth} }""")
    assert info["role"] == "menu" and info["right"] <= info["vw"], info
    names = [i[0] for i in info["items"]]
    assert names == ["我的帳號", "修改密碼", "登出"], info      # T82：我的帳號頁上線（sidebar.js MY_ACCOUNT_READY）⇒ 選單多一項；修改密碼改到帳號安全分頁
    assert info["items"][0][2] == "my-account.html" and "my-account.html?tab=security" in info["items"][1][2], info
    if mobile:
        assert all(i[1] >= 43.5 for i in info["items"]), "手機選單項目觸控目標 <44px：%r" % info
    # Esc：收合、aria-expanded=false、焦點回頭像
    page.keyboard.press("Escape")
    assert ex() == [False, "false"]
    assert page.evaluate("() => document.activeElement && document.activeElement.id") == "tb-avatar"
    # 鍵盤開啟 ⇒ 焦點進第一項；↓ 移動；Tab 收合
    page.focus("#tb-avatar")
    page.keyboard.press("Enter")
    assert ex() == [True, "true"]
    assert page.evaluate("() => document.activeElement.textContent.trim()") == "我的帳號"
    page.keyboard.press("ArrowDown")
    assert page.evaluate("() => document.activeElement.textContent.trim()") == "修改密碼"
    page.keyboard.press("ArrowDown")
    assert page.evaluate("() => document.activeElement.textContent.trim()") == "登出"
    page.keyboard.press("Escape")
    # 外點收合
    page.click("#tb-avatar")
    page.mouse.click(w // 3, h - 60)
    page.wait_for_function("() => document.querySelector('#tb-acct-menu').hidden", timeout=3000)
    assert ex() == [False, "false"]


@pytest.mark.e2e
def test_avatar_menu_header_shows_name_and_role_and_logout_works(live_server, make_user, e2e_browser):
    u = make_user(username="mob_acct_out")
    page = _open(e2e_browser, live_server, u, 1400, 900, mobile=False, name="customers.html")
    page.click("#tb-avatar")
    head = page.inner_text("#tb-acct-menu .acct__head")
    sess = page.evaluate("() => JSON.parse(localStorage.getItem('motrix_session'))")
    assert (sess.get("displayName") or sess.get("username")) in head, (head, sess.get("role"))
    assert any(r in head for r in ("最高管理者", "管理員", "業務", "工程師", "檢視者")), head
    page.click("#tb-acct-menu >> text=登出")
    page.wait_for_function("() => !localStorage.getItem('motrix_session')", timeout=8000)


@pytest.mark.e2e
def test_avatar_menu_and_more_panel_are_mutually_exclusive(live_server, make_user, e2e_browser):
    u = make_user(username="mob_acct_more")
    page = _open(e2e_browser, live_server, u, 390, 844, name="customers.html")
    page.click("#tb-more")
    page.click("#tb-avatar")
    assert page.evaluate("() => [document.querySelector('#app-topbar').classList.contains('tb-more-open'), document.querySelector('#tb-acct-menu').hidden]") == [False, False]
    page.click("#tb-more")
    assert page.evaluate("() => [document.querySelector('#app-topbar').classList.contains('tb-more-open'), document.querySelector('#tb-acct-menu').hidden]") == [True, True]


# ── 複驗補修（hichan-2：N1 通知下拉被切、N2 未讀 9+ 擠掉頭像、N4 抽屜 a11y）────────────────

@pytest.mark.e2e
@pytest.mark.parametrize("w,h,fz", [(375, 667, 1.15), (390, 844, 1.0), (390, 844, 1.15)], ids=["375-large", "390-std", "390-large"])
def test_phone_bell_dropdown_stays_in_viewport_and_9plus_keeps_avatar(live_server, make_user, e2e_browser, w, h, fz):
    u = make_user(username=f"mob_bell_{w}_{int(fz * 100)}")
    page = _open(e2e_browser, live_server, u, w, h, True, name="customers.html", fz=fz)
    # N2：把鈴鐺徽章撐成「9+」，頭像仍要在畫面內、頂欄不溢出
    page.evaluate("""() => { const b = document.querySelector('#app-topbar .topbar__right > div[x-data] > button .mbadge');
      b.textContent = '9+'; b.style.display = 'inline-block'; }""")
    m = page.evaluate(_TB)
    assert m["tbSW"] <= m["tbCW"] + 1, m
    assert m["avatar"]["r"] <= m["vw"] + 0.5 and m["avatar"]["w"] >= 43.5, m["avatar"]
    # N1：通知下拉左右都在畫面內
    page.click("#app-topbar .topbar__right > div[x-data] > button")
    page.wait_for_timeout(300)
    r = page.evaluate("() => { const b = document.querySelector('.tb-notif-dd').getBoundingClientRect(); return [b.left, b.right, innerWidth] }")
    assert r[0] >= -0.5 and r[1] <= r[2] + 0.5, "通知下拉超出畫面：%r" % (r,)


@pytest.mark.e2e
@pytest.mark.parametrize("w,h,fz", [(375, 667, 1.15), (390, 844, 1.0)], ids=["375-large", "390-std"])
def test_phone_drawer_a11y_focus_trap_and_backdrop_strip(live_server, make_user, e2e_browser, w, h, fz):
    u = make_user(username=f"mob_dr_a11y_{w}_{int(fz * 100)}")
    _seed_cases()
    page = _open(e2e_browser, live_server, u, w, h, True, name="case-management.html", fz=fz)
    ctl = page.evaluate("() => document.querySelector('.mnav__burger').getAttribute('aria-controls')")
    assert ctl == "app-mainnav" and page.evaluate("() => !!document.getElementById('app-mainnav')")
    assert page.evaluate("() => document.querySelector('.mnav__in').getAttribute('role')") is None, "收起時不該是 dialog"
    page.focus(".mnav__burger")
    page.keyboard.press("Enter")
    page.wait_for_function("() => document.querySelector('#app-mainnav').classList.contains('mnav--open')", timeout=3000)
    assert page.evaluate("() => [document.querySelector('.mnav__in').getAttribute('role'), document.querySelector('.mnav__in').getAttribute('aria-modal')]") == ["dialog", "true"]
    # focus trap：Tab 30 次，焦點一直留在抽屜內
    outside = 0
    for _ in range(30):
        page.keyboard.press("Tab")
        if not page.evaluate("() => document.querySelector('.mnav__in').contains(document.activeElement)"):
            outside += 1
    assert outside == 0, "Tab 跑出抽屜 %d 次" % outside
    page.keyboard.press("Shift+Tab")
    assert page.evaluate("() => document.querySelector('.mnav__in').contains(document.activeElement)")
    # 遮罩條：抽屜右緣到視窗右緣至少 16px（實際畫面），點遮罩收起
    gap = page.evaluate("() => innerWidth - document.querySelector('.mnav__in').getBoundingClientRect().right")
    assert gap >= 16, "字級大時抽屜蓋滿畫面、沒有可點的遮罩：gap=%r" % gap
    page.mouse.click(w - 6, h // 2)
    page.wait_for_function("() => !document.querySelector('#app-mainnav').classList.contains('mnav--open')", timeout=3000)
    assert page.evaluate("() => document.querySelector('.mnav__in').getAttribute('role')") is None


# ── 桌機不變 ────────────────────────────────────────────────────────────────

@pytest.mark.e2e
def test_desktop_layout_is_unchanged(live_server, make_user, e2e_browser):
    u = make_user(username="mob_desktop")
    _seed_cases()
    page = _open(e2e_browser, live_server, u, 1400, 900, mobile=False)
    m = page.evaluate("""() => {
      const q = s => document.querySelector(s);
      const x = s => { const e = q(s); return e ? Math.round(e.getBoundingClientRect().left) : null };
      return {moreHidden: getComputedStyle(q('#tb-more')).display === 'none', burgerHidden: getComputedStyle(q('.mnav__burger')).display === 'none',
              drawerPos: getComputedStyle(q('.mnav__in')).position,
              // 面板內容在 DOM 裡排在 ⋯ 之後，但桌機畫面上仍然是「姓名／字級／…／修改密碼」在前、通知鈴、頭像在後
              xs: [x('#tb-display-name'), x('#fz-0'), x('#theme-toggle-btn'), x('#tb-online-btn'), x('#ux-help-btn'),
                   Math.round(q('#app-topbar .topbar__right > div[x-data] > button').getBoundingClientRect().left),
                   Math.round(q('#tb-avatar').getBoundingClientRect().left)],
              listW: Math.round(q('.cm-list').getBoundingClientRect().width),
              listOv: getComputedStyle(q('.cm-list')).overflowY, bodyOv: getComputedStyle(q('.cm-list__body')).overflowY};
    }""")
    assert m["moreHidden"] and m["burgerHidden"] and m["drawerPos"] != "fixed", m
    xs = m["xs"]
    assert all(v is not None for v in xs) and xs == sorted(xs), "桌機頂欄由左至右順序要是 姓名／字級／深淺色／在線／？／通知／頭像：%r" % xs
    assert m["listW"] == 300 and m["listOv"] == "hidden" and m["bodyOv"] == "auto", "桌機清單版面不可變：%r" % m


# ── ④ 徽章 ──────────────────────────────────────────────────────────────────

_MEASURE = """(texts) => {
  const out = [];
  const items = [...document.querySelectorAll('#app-mainnav .mnav__item')].filter(a => a.querySelector('.mbadge'));
  const a = items[0];
  const b = a.querySelector('.mbadge');
  a.firstElementChild.textContent = '一個非常非常長的選單項目名稱用來擠壓右側徽章';      // 逼出被擠壓的情境（修前：徽章縮到 16px 寬）
  for (const t of texts) {
    b.textContent = t; b.style.display = 'inline-block';
    const r = b.getBoundingClientRect(), cs = getComputedStyle(b), z = parseFloat(getComputedStyle(document.documentElement).zoom) || 1;
    out.push({t, w: Math.round(r.width / z * 10) / 10, h: Math.round(r.height / z * 10) / 10, shrink: cs.flexShrink});
  }
  return {n: items.length, rows: out};
}"""


def _check_badge(rows):
    one = rows[0]
    assert one["w"] == one["h"] == 20, "一位數徽章要是正圓（寬＝高＝20）：%r" % one
    assert one["shrink"] == "0", one
    for r in rows[1:]:
        assert r["h"] == 20 and r["w"] > r["h"], "兩位數／9+ 要是膠囊（寬>高，高仍 20）：%r" % r


@pytest.mark.e2e
def test_desktop_dropdown_badge_is_circle_then_capsule(live_server, make_user, e2e_browser):
    u = make_user(username="badge_desk")
    _seed_cases()
    page = _open(e2e_browser, live_server, u, 1280, 800, False)
    m = page.evaluate(_MEASURE, ["1", "12", "9+"])
    assert m["n"] >= 1, "選單裡找不到任何徽章元素"
    _check_badge(m["rows"])


@pytest.mark.e2e
def test_phone_drawer_badge_same_shape(live_server, make_user, e2e_browser):
    u = make_user(username="badge_phone")
    _seed_cases()
    page = _open(e2e_browser, live_server, u, 390, 844, True)
    page.click(".mnav__burger")
    page.evaluate("""() => { const a = [...document.querySelectorAll('#app-mainnav .mnav__item')].find(x => x.querySelector('.mbadge'));
      a.closest('.mnav__grp').classList.add('is-open') }""")
    _check_badge(page.evaluate(_MEASURE, ["1", "12", "9+"])["rows"])


@pytest.mark.e2e
def test_bell_badge_uses_the_same_shape(live_server, make_user, e2e_browser):
    u = make_user(username="badge_bell")
    _seed_cases()
    page = _open(e2e_browser, live_server, u, 1280, 800, False)
    n = page.evaluate("() => document.querySelectorAll('#app-topbar .mbadge').length")
    assert n >= 1, "鈴鐺徽章沒有套用共用的 .mbadge 形狀類別"


# ── ⑤ WebKit（iPhone）────────────────────────────────────────────────────────

@pytest.mark.e2e
def test_webkit_iphone_outside_tap_closes_more_panel(live_server, make_user):
    from playwright.sync_api import sync_playwright
    u = make_user(username="mob_webkit")
    old = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    wk = os.environ.get("MOTRIX_WEBKIT_PATH")
    if wk:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = wk
    try:
        with sync_playwright() as p:
            try:
                browser = p.webkit.launch()
            except Exception as e:                                                          # noqa: BLE001
                if os.environ.get("MOTRIX_REQUIRE_WEBKIT") == "1":                          # 驗收時設 1：找不到／啟動不了 WebKit 就紅，不要靜默略過
                    raise
                pytest.skip("沒有安裝 WebKit（版本要與 playwright 相符；設 MOTRIX_WEBKIT_PATH 指向含 webkit 的瀏覽器目錄；MOTRIX_REQUIRE_WEBKIT=1 則改為失敗）（設 MOTRIX_WEBKIT_PATH 指向含 webkit 的瀏覽器目錄）：%s" % str(e)[:80].encode("ascii", "replace").decode())
            ctx = browser.new_context(**p.devices["iPhone 13"])
            page = ctx.new_page()
            inject_login(page, live_server, *u)
            page.goto(f"{live_server}/pages/customers.html")
            page.wait_for_selector("#tb-more", timeout=20000)
            page.tap("#tb-more")
            assert page.evaluate("() => document.querySelector('#app-topbar').classList.contains('tb-more-open')")
            page.touchscreen.tap(190, 600)                       # 面板外的非互動區
            page.wait_for_function("() => !document.querySelector('#app-topbar').classList.contains('tb-more-open')", timeout=3000)
            m = page.evaluate("() => { const t = document.querySelector('#app-topbar'); return [t.scrollWidth, t.clientWidth, document.documentElement.scrollWidth, innerWidth] }")
            assert m[0] <= m[1] + 1 and m[2] <= m[3] + 1, m
            # 頭像選單：外點也要收合（iOS 引擎）。上一步的外點可能點到頁面內容、開了彈窗 ⇒ 重新載入再測
            page.goto(f"{live_server}/pages/customers.html")
            page.wait_for_selector("#tb-avatar", timeout=20000)
            page.tap("#tb-avatar")
            assert page.evaluate("() => !document.querySelector('#tb-acct-menu').hidden")
            page.touchscreen.tap(60, 150)
            page.wait_for_function("() => document.querySelector('#tb-acct-menu').hidden", timeout=3000)
            # 通知下拉不可超出畫面（N1）
            page.tap("#app-topbar .topbar__right > div[x-data] > button")
            page.wait_for_timeout(300)
            r = page.evaluate("() => { const d = document.querySelector('.tb-notif-dd'); const b = d.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.right), innerWidth] }")
            assert r[0] >= 0 and r[1] <= r[2], r
            # N5：點面板外的空白區（頁面下方）要收起通知下拉（WebKit 觸控不送 click，要靠 pointerdown）
            page.touchscreen.tap(190, 780)
            page.wait_for_function("() => getComputedStyle(document.querySelector('.tb-notif-dd')).display === 'none'", timeout=3000)
            browser.close()
    finally:
        if wk:
            if old is None:
                os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
            else:
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = old
