"""瀏覽器端對端：報價清單重排（T84，2026-11-13）。

- 三個有定義的數字（要我處理／等別人／本月已成案）、可點擊篩選
- 預設「我負責的、進行中」＋目前條件列＋清除條件、每人記住上次選擇
- 「下一步」欄（等誰簽核、被退回、已核准待寄客戶）
- 預設欄位 ≤ 7、可加欄、緊湊密度；案件進度小選單仍在每一列（專家效率 E3）
- 手機寬度（390px）：卡片、操作按鈕看得到且 ≥ 44px、頁面不橫向捲動
"""
import json
from datetime import datetime

import pytest

pytest.importorskip("playwright.sync_api")

from playwright.sync_api import expect  # noqa: E402

from tests._requires import requires_module  # noqa: E402

pytestmark = requires_module("case", "本檔打 M01（報價單）的清單頁")

DATA = "Alpine.$data(document.querySelector('[x-data]'))"


def _today():
    """收集期不取系統時鐘（跨午夜會偶發失敗）：要用的時候才取。"""
    return datetime.now().strftime("%Y-%m-%d")


def _uid(username):
    import db
    c = db.get_db()
    try:
        return c.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    finally:
        c.close()


def _seed(no, owner_id, status, deal_tag="", approval=None, project="案"):
    import db
    dj = {"quoteNo": no, "status": status}
    if approval is not None:
        dj["approval"] = approval
    if deal_tag:
        dj["dealTag"] = deal_tag
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    c = db.get_db()
    try:
        c.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, quote_date, sales_person_id, sales_person) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (no, status, "客戶" + no[-3:], project + no[-3:], 1050, 1000, json.dumps(dj, ensure_ascii=False),
             now, now, deal_tag, _today(), owner_id, "業務甲"))
        c.commit()
    finally:
        c.close()


def _seed_set(owner):
    boss = {"userId": None, "username": "t84e_boss", "displayName": "舊名", "status": "pending"}
    _seed("MQ-T84E-001", owner, "草稿")
    _seed("MQ-T84E-002", owner, "待審核", approval={"requestedBy": "x", "currentTier": 0, "tiers": [{"order": 0, "approvers": [boss]}]})
    _seed("MQ-T84E-003", owner, "已核准")
    _seed("MQ-T84E-004", owner, "已拒絕")
    _seed("MQ-T84E-005", owner, "已送出")
    _seed("MQ-T84E-006", owner, "已送出", deal_tag="已成案")


def _open(live_server, make_user, new_page, login_as, name, width=1280, height=900, prep=None):
    sales = make_user(username=name, role="sales")
    make_user(username="t84e_boss", role="admin")
    import db
    c = db.get_db()
    c.execute("UPDATE users SET display_name=? WHERE username='t84e_boss'", ("王經理",))
    c.commit()
    c.close()
    _seed_set(_uid(name))
    page = new_page(viewport={"width": width, "height": height})
    login_as(page, sales)
    if prep:
        prep(page)
    page.goto(live_server + "/pages/quotations.html")
    page.wait_for_function("() => %s.loading === false && %s.quotes.length >= 6" % (DATA, DATA), timeout=20000)
    return page


VIS_HEADS = "() => [...document.querySelectorAll('thead th')].filter(t => t.offsetParent !== null).map(t => t.textContent.trim())"


@pytest.mark.e2e
def test_three_numbers_default_filter_next_step_columns_and_remembered_choice(live_server, make_user, new_page, login_as):
    page = _open(live_server, make_user, new_page, login_as, "t84e_sales")
    # 三個數字的定義
    assert page.get_by_test_id("ql-sum-todo").inner_text().count("3 張") == 1, "草稿＋被退回＋已核准＝3"
    assert "1 張" in page.get_by_test_id("ql-sum-waiting").inner_text()
    assert "待簽核 1・簽核中 0" in page.get_by_test_id("ql-sum-waiting").inner_text()
    assert "1 張" in page.get_by_test_id("ql-sum-won").inner_text()
    # 預設條件：我負責的、進行中；有清除條件
    cond = page.get_by_test_id("ql-cond").inner_text()
    assert page.get_by_test_id("ql-cond-mine").count() == 1 and "進行中" in cond and page.get_by_test_id("ql-clear-conditions").is_visible()
    # 預設欄位 ≤ 7（不含「操作」）
    heads = [h for h in page.evaluate(VIS_HEADS) if h != "操作"]
    assert len(heads) <= 7 and heads[:1] == ["報價單號"] and "下一步" in heads and "案件進度" in heads, heads
    assert "毛利率" not in heads and "客戶名稱" not in heads
    # 客戶名稱併進單號格
    first = page.locator("tr.ql-row[data-quote-no='MQ-T84E-001'] td[data-col=quoteNo]").inner_text()
    assert "MQ-T84E-001" in first and "客戶001" in first
    # 下一步：等誰簽核（現名）、已核准待寄客戶、被退回
    nxt = lambda no: page.locator("tr.ql-row[data-quote-no='%s'] td[data-col=next]" % no).inner_text()   # noqa: E731
    assert "等 王經理 簽核" in nxt("MQ-T84E-002")
    assert "簽完了，請寄給客戶" in nxt("MQ-T84E-003")
    assert "被退回" in nxt("MQ-T84E-004")
    assert "還沒送簽" in nxt("MQ-T84E-001")
    # 案件進度小選單仍在（E3：一次選擇完成），未標記有說明
    sel = page.locator("tr.ql-row[data-quote-no='MQ-T84E-005'] td[data-col=dealTag] select")
    assert sel.count() == 1 and "未標記" in (sel.get_attribute("title") or "")
    # E1／E2／E4 入口都還在、各一步：新增、複製、搜尋
    assert page.get_by_role("link", name="新增報價單").is_visible()
    assert page.locator("tr.ql-row[data-quote-no='MQ-T84E-001'] button[title='複製為新報價單']").count() == 1
    assert page.locator("input.search-input[placeholder*='搜尋報價單號']").is_visible()
    # 點「要我處理」→ 只剩 3 張
    page.get_by_test_id("ql-sum-todo").click()
    assert page.evaluate("() => document.querySelectorAll('tr.ql-row').length") == 3
    page.get_by_test_id("ql-sum-todo").click()                                  # 再點一次取消
    # 點數字／清除條件只是暫時的檢視：重新整理後回到記住的選擇（預設「只看我負責的」）
    page.get_by_test_id("ql-clear-conditions").click()
    page.get_by_test_id("ql-cond-mine").wait_for(state="detached", timeout=5000)
    assert page.evaluate("() => %s._mineLimit" % DATA) is False and page.get_by_test_id("ql-cond-mine").count() == 0
    # 清除條件後，「只看我負責的」不再顯示為按下；按一次就回到我負責的，而且不改寫記住的選擇
    expect(page.get_by_test_id("ql-mine-toggle")).to_have_attribute("aria-pressed", "false")
    page.get_by_test_id("ql-mine-toggle").click()
    assert page.evaluate("() => %s._mineLimit" % DATA) is True and page.evaluate("() => localStorage.getItem('motrix_quote_mine:t84e_sales')") in (None, "1")
    page.get_by_test_id("ql-clear-conditions").click()
    page.reload()
    page.wait_for_function("() => %s.loading === false && %s.quotes.length >= 6" % (DATA, DATA), timeout=20000)
    assert page.evaluate("() => %s._mineLimit" % DATA) is True, "清除條件不改寫記住的選擇"
    # 只有明確切換「只看我負責的」才會記住
    page.get_by_test_id("ql-mine-toggle").click()
    assert page.evaluate("() => %s.onlyMine" % DATA) is False
    page.reload()
    page.wait_for_function("() => %s.loading === false && %s.quotes.length >= 6" % (DATA, DATA), timeout=20000)
    assert page.evaluate("() => %s.onlyMine" % DATA) is False, "記住上次明確的選擇"
    assert page.get_by_test_id("ql-cond-mine").count() == 0
    # 點「要我處理」不會把記住的選擇改成「只看我負責的」
    page.get_by_test_id("ql-sum-todo").click()
    page.reload()
    page.wait_for_function("() => %s.loading === false && %s.quotes.length >= 6" % (DATA, DATA), timeout=20000)
    assert page.evaluate("() => %s.onlyMine" % DATA) is False


@pytest.mark.e2e
def test_columns_and_density_are_user_choices(live_server, make_user, new_page, login_as):
    page = _open(live_server, make_user, new_page, login_as, "t84e_sales2")
    # 加欄：毛利率、有效天數；空毛利率是灰色「—」
    page.get_by_test_id("ql-cols-btn").click()
    page.get_by_test_id("ql-col-margin").check()
    page.get_by_test_id("ql-col-validDays").check()
    page.wait_for_function("(js) => { const h = eval(js)(); return h.includes('毛利率') && h.includes('有效天數') }", arg=VIS_HEADS, timeout=5000)
    heads = page.evaluate(VIS_HEADS)
    assert "毛利率" in heads and "有效天數" in heads, heads
    dash = page.locator("tr.ql-row[data-quote-no='MQ-T84E-001'] td[data-col=margin] span")
    assert dash.inner_text() == "—" and "text-dim" in (dash.get_attribute("style") or "") and "danger" not in (dash.get_attribute("style") or "")
    # 緊湊密度
    page.get_by_test_id("ql-density").click()
    assert page.evaluate("() => document.querySelector('table.ql-table').classList.contains('ql-compact')")
    page.reload()
    page.wait_for_function("() => %s.loading === false" % DATA, timeout=20000)
    assert "毛利率" in page.evaluate(VIS_HEADS), "欄位選擇有記住"
    assert page.evaluate("() => document.querySelector('table.ql-table').classList.contains('ql-compact')"), "密度有記住"


@pytest.mark.e2e
def test_superadmin_with_no_owned_quotes_is_not_shown_an_empty_page(live_server, make_user, new_page, login_as):
    """預設「我負責的」在名單是空的時候不套用（否則最高管理者第一次開什麼都看不到）。"""
    admin = make_user(username="t84e_super", role="superadmin")
    owner = make_user(username="t84e_owner", role="sales")
    make_user(username="t84e_boss", role="admin")
    _seed_set(_uid("t84e_owner"))
    page = new_page(viewport={"width": 1280, "height": 900})
    login_as(page, admin)
    page.goto(live_server + "/pages/quotations.html")
    page.wait_for_function("() => %s.loading === false && %s.quotes.length >= 6" % (DATA, DATA), timeout=20000)
    assert page.evaluate("() => %s._mineLimit" % DATA) is False
    assert page.evaluate("() => document.querySelectorAll('tr.ql-row').length") >= 5
    assert "你目前沒有負責的報價，先顯示全部" in page.get_by_test_id("ql-mine-note").inner_text()
    assert owner  # 夾具已建帳號


@pytest.mark.e2e
def test_phone_390_cards_show_actions_with_44px_targets_and_no_horizontal_scroll(live_server, make_user, new_page, login_as):
    page = _open(live_server, make_user, new_page, login_as, "t84e_sales3", width=390, height=844)
    page.wait_for_timeout(300)
    # 全站的「第一次來？」橫幅（ux-help，UX A4／A5）新帳號第一次看到會佔約 100px；使用者按「我知道了」之後才是日常的樣子，第一屏量那個狀態
    hint = page.get_by_test_id("ux-first-hint")
    if hint.count() and hint.is_visible():
        hint.locator("[data-ux=dismiss]").click()
        hint.wait_for(state="detached", timeout=3000)
    # 第一屏（390x844）要看得到第一張卡片：三個數字一排、篩選收進「篩選」鈕、壓力帶收起
    ys = {page.get_by_test_id(t).bounding_box()["y"] for t in ("ql-sum-todo", "ql-sum-waiting", "ql-sum-won")}
    assert len(ys) == 1, "三個數字併成一排：%s" % ys
    assert not page.get_by_test_id("ql-filters").is_visible() and page.get_by_test_id("ql-filter-btn").is_visible()
    first = page.locator("tr.ql-row").first.bounding_box()
    assert first["y"] + 120 <= 844, "第一張卡片在第一屏內：y=%s" % first["y"]
    page.get_by_test_id("ql-filter-btn").click()
    page.get_by_test_id("ql-filters").wait_for(state="visible", timeout=3000)
    page.get_by_test_id("ql-filter-btn").click()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "手機寬度不橫向捲動"
    assert page.evaluate("() => getComputedStyle(document.querySelector('thead')).display") == "none"
    row = page.locator("tr.ql-row[data-quote-no='MQ-T84E-002']")
    row.scroll_into_view_if_needed()
    expect(row.get_by_text("等 王經理 簽核")).to_be_visible()          # 下一步在卡片上
    edit = row.locator(".row-actions a.icon-btn")
    edit.wait_for(state="visible", timeout=5000)
    box = edit.bounding_box()
    assert edit.is_visible() and box["width"] >= 44 and box["height"] >= 44, box
    assert float(page.evaluate("() => getComputedStyle(document.querySelector('.row-actions')).opacity")) == 1, "手機上操作按鈕不靠 hover"
    sel = page.locator("tr.ql-row[data-quote-no='MQ-T84E-005'] td[data-col=dealTag] select")
    sel.scroll_into_view_if_needed()
    sb = sel.bounding_box()
    assert sb["height"] >= 44
    act = page.locator("tr.ql-row[data-quote-no='MQ-T84E-005'] .row-actions").bounding_box()
    assert abs((sb["y"] + sb["height"] / 2) - (act["y"] + act["height"] / 2)) < 30, "進度選單與操作按鈕同一列"
    # 三個數字在 390px 都看得到、可點
    for t in ("ql-sum-todo", "ql-sum-waiting", "ql-sum-won"):
        expect(page.get_by_test_id(t)).to_be_visible()
    # 每張卡片不超出視窗寬度
    assert page.evaluate("() => [...document.querySelectorAll('tr.ql-row')].every(r => r.getBoundingClientRect().right <= window.innerWidth + 1)")


def _admin_world(make_user):
    adm = make_user(username="t84e_adm", role="admin")
    make_user(username="t84e_col", role="sales")
    make_user(username="t84e_boss", role="admin")
    _seed("MQ-T84E-101", _uid("t84e_adm"), "草稿")
    _seed("MQ-T84E-102", _uid("t84e_col"), "已送出")
    return adm


@pytest.mark.e2e
def test_search_ignores_mine_and_says_so_without_an_extra_click(live_server, make_user, new_page, login_as):
    """E4：找別人負責的單，打字就找得到（不必先清除條件）；清掉搜尋回到原本的條件。"""
    adm = _admin_world(make_user)
    page = new_page(viewport={"width": 1280, "height": 900})
    login_as(page, adm)
    page.goto(live_server + "/pages/quotations.html")
    page.wait_for_function("() => %s.loading === false && %s.quotes.length >= 2" % (DATA, DATA), timeout=20000)
    assert page.evaluate("() => document.querySelectorAll('tr.ql-row').length") == 1, "預設只列我負責的"
    page.locator("input.search-input[placeholder*='搜尋報價單號']").fill("客戶102")
    page.wait_for_function("() => document.querySelectorAll(\"tr.ql-row[data-quote-no='MQ-T84E-102']\").length === 1", timeout=5000)
    assert "搜尋範圍：全部你可看的報價" in page.get_by_test_id("ql-cond").inner_text()
    page.locator("input.search-input[placeholder*='搜尋報價單號']").fill("")
    page.wait_for_function("() => document.querySelectorAll('tr.ql-row').length === 1", timeout=5000)
    assert page.get_by_test_id("ql-cond-mine").count() == 1


@pytest.mark.e2e
def test_remembered_mine_with_empty_list_and_failed_mine_fetch_never_show_an_empty_or_wrong_page(live_server, make_user, new_page, login_as):
    adm = make_user(username="t84e_adm2", role="admin")
    make_user(username="t84e_col", role="sales")
    make_user(username="t84e_boss", role="admin")
    _seed("MQ-T84E-102", _uid("t84e_col"), "已送出")
    page = new_page(viewport={"width": 1280, "height": 900})
    login_as(page, adm)
    page.add_init_script("try { localStorage.setItem('motrix_quote_mine:t84e_adm2', '1') } catch (e) {}")
    page.goto(live_server + "/pages/quotations.html")
    page.wait_for_function("() => %s.loading === false && %s.quotes.length >= 1" % (DATA, DATA), timeout=20000)
    assert page.evaluate("() => document.querySelectorAll('tr.ql-row').length") >= 1, "記住「只看我負責的」但名單是空的 ⇒ 仍顯示全部"
    # 第二個請求（我負責的名單）失敗：數字顯示「暫時無法計算」，不是 0 張；列表照常
    page2 = new_page(viewport={"width": 1280, "height": 900})
    login_as(page2, adm)
    page2.route("**/api/quotations?*mine=1*", lambda r: r.abort())
    page2.goto(live_server + "/pages/quotations.html")
    page2.wait_for_function("() => %s.loading === false && %s.quotes.length >= 1" % (DATA, DATA), timeout=20000)
    assert "暫時無法計算" in page2.get_by_test_id("ql-sum-todo").inner_text() and "0 張" not in page2.get_by_test_id("ql-sum-todo").inner_text()
    assert page2.get_by_test_id("ql-sum-todo").is_disabled()
    assert page2.evaluate("() => document.querySelectorAll('tr.ql-row').length") >= 1


@pytest.mark.e2e
def test_hidden_columns_hide_their_folded_data_and_compact_keeps_the_customer(live_server, make_user, new_page, login_as):
    page = _open(live_server, make_user, new_page, login_as, "t84e_sales4")
    row = "tr.ql-row[data-quote-no='MQ-T84E-001']"
    assert "客戶001" in page.locator(row + " td[data-col=quoteNo]").inner_text(), "預設精簡：客戶折進單號格"
    page.get_by_test_id("ql-density").click()
    expect(page.locator(row + " td[data-col=quoteNo]")).to_contain_text("客戶001")                       # 緊湊不丟客戶與填單人
    expect(page.locator(row + " td[data-col=date]")).to_contain_text("業務甲")
    page.get_by_test_id("ql-density").click()
    # 設定中心的個人檢視（或公司版面）隱藏客戶／填單人 ⇒ 資料也不從別的格漏出來
    page.evaluate("() => { const d = %s; d.lvOn = { columns: true, tab: false, size: false }; d.pv = { ...d.pv, hidden: ['customer', 'filler'] } }" % DATA)
    page.wait_for_function("(js) => !eval(js)().includes('客戶名稱')", arg=VIS_HEADS, timeout=5000)
    assert "客戶001" not in page.locator(row + " td[data-col=quoteNo]").inner_text()
    assert "業務甲" not in page.locator(row + " td[data-col=date]").inner_text()


@pytest.mark.e2e
def test_confirmed_quote_next_step_and_no_lane_headers_while_a_number_is_selected(live_server, make_user, new_page, login_as):
    sales = make_user(username="t84e_sales5", role="sales")
    make_user(username="t84e_boss", role="admin")
    uid = _uid("t84e_sales5")
    _seed_set(uid)
    _seed("MQ-T84E-007", uid, "已確認")
    page = new_page(viewport={"width": 1280, "height": 900})
    login_as(page, sales)
    page.goto(live_server + "/pages/quotations.html")
    page.wait_for_function("() => %s.loading === false && %s.quotes.length >= 7" % (DATA, DATA), timeout=20000)
    nxt = page.locator("tr.ql-row[data-quote-no='MQ-T84E-007'] td[data-col=next]").inner_text()
    assert "客戶已確認，請轉案件" in nxt and "有效期" not in nxt
    assert page.locator("tr.ql-lane:visible").count() >= 1
    page.get_by_test_id("ql-sum-todo").click()
    page.wait_for_function("() => document.querySelectorAll('tr.ql-row').length === 3", timeout=5000)
    assert page.locator("tr.ql-lane:visible").count() == 0, "選了數字就不分階段標題"
    assert page.locator(".filter-tab.active").count() == 0, "選了數字時分頁不亮「進行中」"


# ── 平板（768–1023）搜尋列：「欄位」「緊湊」併成一列（fix/quotations-tablet-searchbar-t84）─────────────────

def _page_html():
    from core.source_tree import page_file
    return page_file("quotations.html").read_text(encoding="utf-8")


def test_tablet_searchbar_pairs_columns_and_density_buttons_in_one_row_static():
    """靜態規則：兩顆在同一個 .ql-pair 裡；.ql-pair 預設 display:contents（桌機／手機不變）；
    只有 768–1023 的 media 規則把它變成跨整列的兩欄格線、兩顆各半。"""
    import re
    html = _page_html()
    m = re.search(r'<div class="ql-pair">(.*?)\n      </div>\n    </div>', html, re.S)
    assert m, "找不到 .ql-pair 區塊"
    assert 'data-testid="ql-cols-btn"' in m.group(1) and 'data-testid="ql-density"' in m.group(1)
    assert re.search(r"\n\s*\.ql-pair \{ display:contents; \}", html), "預設必須是 display:contents（桌機、手機版面不變）"
    tab = re.search(r"@media \(min-width: 768px\) and \(max-width: 1023px\) \{(.*?)\n    \}", html, re.S)
    assert tab, "找不到平板 768–1023 的 media 規則"
    body = tab.group(1)
    assert re.search(r"\.search-bar \.ql-pair \{[^}]*display:grid[^}]*grid-template-columns: 1fr 1fr[^}]*grid-column: 1 / -1", body)
    # 平板以外的 media（桌機 >1023、手機 ≤767）不得改 .ql-pair
    outside = html.replace(body, "")
    assert not re.search(r"\.search-bar \.ql-pair|@media[^{]*\{[^}]*\.ql-pair", outside)


@pytest.mark.e2e
@pytest.mark.parametrize("width,height", [(900, 900), (768, 1024)])
def test_tablet_columns_and_density_buttons_sit_side_by_side(live_server, make_user, new_page, login_as, width, height):
    page = _open(live_server, make_user, new_page, login_as, "t84e_tabbar_%d" % width, width=width, height=height)
    a = page.get_by_test_id("ql-cols-btn")
    b = page.get_by_test_id("ql-density")
    a.wait_for(state="visible", timeout=5000)
    ba, bb = a.bounding_box(), b.bounding_box()
    assert abs(ba["y"] - bb["y"]) < 2, "「欄位」「緊湊」要在同一列：%s %s" % (ba, bb)
    assert ba["x"] + ba["width"] <= bb["x"] + 1, "「欄位」在左、「緊湊」在右"
    assert abs(ba["width"] - bb["width"]) < 4, "兩顆各半"
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")


@pytest.mark.e2e
@pytest.mark.parametrize("width,height", [(1440, 900), (390, 844)])
def test_desktop_and_phone_searchbar_layout_is_unchanged_pair_has_no_box(live_server, make_user, new_page, login_as, width, height):
    """桌機／手機：.ql-pair 是 display:contents（不產生方框），兩顆按鈕仍是搜尋列的直接版面成員。"""
    page = _open(live_server, make_user, new_page, login_as, "t84e_pairbox_%d" % width, width=width, height=height)
    assert page.evaluate("getComputedStyle(document.querySelector('.ql-pair')).display") == "contents"
    if width >= 1024:
        ba = page.get_by_test_id("ql-cols-btn").bounding_box()
        bb = page.get_by_test_id("ql-density").bounding_box()
        assert abs(ba["y"] - bb["y"]) < 2, "桌機一列排開"
