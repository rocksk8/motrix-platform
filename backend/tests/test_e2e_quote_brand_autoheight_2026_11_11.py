"""瀏覽器端對端：報價單品項明細多行欄（品名／廠牌型號／備註）自動撐高（2026-11-11）。

使用者回報：廠牌/型號欄文字像被裁切、沒完整顯示。實測根因：文字有換行（pre-wrap），但高度只在
`@input`（逐字打）與 `x-init`（掛載當下）各算一次 scrollHeight ⇒ 載入既有單子、程式改值、欄寬
變動、x-show 由隱藏變顯示都不重算 ⇒ 框停在一行高。修法：`autoGrow`／`autoGrowInit`（@input ＋
x-effect 監看 model ＋ ResizeObserver 監看寬度）。

每題都量「框高 ≥ 內容高（scrollHeight）」——修法前 load_existing／programmatic／width／unhide 皆紅。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

QUOTE_NO = "MQ-202611-901"
LONG = "Cisco Catalyst C9300-48P-E 48-port PoE+ Network Essentials 含三年原廠保固 SmartNet 8x5xNBD"
BRAND = "tbody textarea[placeholder='廠牌 / 型號']"
NOTES = "tbody textarea[placeholder='備註']"
DESC = "tbody textarea[placeholder='品名或規格說明']"
DATA = "Alpine.$data(document.querySelector('[x-data]'))"
FITS = "el => ({h: el.getBoundingClientRect().height, sh: el.scrollHeight, w: el.clientWidth})"


def _seed(items):
    import db
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM quotations WHERE quote_no=?", (QUOTE_NO,))
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, "
            "pretax, data_json, created_at, updated_at, deal_tag, quote_date) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (QUOTE_NO, "草稿", "高度客戶", "高度專案", 1575, 1500,
             json.dumps({"quoteNo": QUOTE_NO, "customerName": "高度客戶",
                         "projectName": "高度專案", "status": "草稿", "items": items,
                         "tot": {"total": 1575, "pretax": 1500,
                                 "directMarginPct": 0, "netMarginPct": 0}},
                        ensure_ascii=False),
             "2026-11-01T00:00:00", "2026-11-01T00:00:00", "", "2026-11-01"),
        )
        conn.commit()
    finally:
        conn.close()


def _item(i, **kw):
    d = {"id": i, "description": "品項 %d" % i, "brand": "", "notes": "", "qty": 1,
         "cost": 1000, "margin": 0.35, "unitPrice": 1650, "amount": 1650}
    d.update(kw)
    return d


def _open(live_server, make_user, e2e_browser, items, name):
    username, password = make_user(username=name, role="superadmin")
    page = e2e_browser.new_page(viewport={"width": 1400, "height": 900})
    inject_login(page, live_server, username, password)
    _seed(items)
    page.goto(f"{live_server}/pages/quotation-form.html?id={QUOTE_NO}")
    page.wait_for_function("() => document.body.innerText.includes('高度客戶')", timeout=20000)
    return page


def _assert_fits(el, label, grown_over=40):
    m = el.evaluate(FITS)
    assert m["sh"] > grown_over, "%s：測試內容沒有撐到多行（%s），題目失效" % (label, m)
    assert m["h"] >= m["sh"] - 1, "%s：框高 %s 小於內容高 %s ⇒ 看起來被裁切" % (label, m["h"], m["sh"])
    return m


def _settle(page, el):
    try:
        page.wait_for_function("e => e.getBoundingClientRect().height >= e.scrollHeight - 1",
                               arg=el.element_handle(), timeout=2000)
    except Exception:
        pass


@pytest.mark.e2e
def test_loaded_existing_quote_shows_full_text(live_server, make_user, e2e_browser):
    page = _open(live_server, make_user, e2e_browser,
                 [_item(1, brand=LONG, notes=LONG, description=LONG)], "e2e_bh1")
    for sel, label in ((BRAND, "廠牌"), (NOTES, "備註"), (DESC, "品名")):
        el = page.locator(sel).first
        el.wait_for(state="visible")
        _settle(page, el)
        _assert_fits(el, "載入既有單／" + label)


@pytest.mark.e2e
def test_programmatic_value_change_regrows(live_server, make_user, e2e_browser):
    page = _open(live_server, make_user, e2e_browser, [_item(1, brand="短")], "e2e_bh2")
    el = page.locator(BRAND).first
    el.wait_for(state="visible")
    short = el.evaluate(FITS)
    page.evaluate(f"{DATA}.q.items[0].brand = {json.dumps(LONG * 2)}")
    _settle(page, el)
    m = _assert_fits(el, "程式改值")
    assert m["h"] > short["h"]
    # 改回短字 ⇒ 要縮回去（不是只會變高）
    page.evaluate(f"{DATA}.q.items[0].brand = '短'")
    page.wait_for_function("e => e.getBoundingClientRect().height <= %s" % (short["h"] + 1),
                           arg=el.element_handle(), timeout=3000)


@pytest.mark.e2e
def test_typing_still_grows_and_marks_dirty(live_server, make_user, e2e_browser):
    page = _open(live_server, make_user, e2e_browser, [_item(1)], "e2e_bh3")
    el = page.locator(BRAND).first
    el.wait_for(state="visible")
    el.click()
    el.type(LONG, delay=0)
    _assert_fits(el, "逐字輸入")
    assert page.evaluate(f"{DATA}.isDirty") is True


@pytest.mark.e2e
def test_column_width_change_regrows(live_server, make_user, e2e_browser):
    page = _open(live_server, make_user, e2e_browser, [_item(1, brand=LONG)], "e2e_bh4")
    el = page.locator(BRAND).first
    el.wait_for(state="visible")
    _settle(page, el)
    wide = el.evaluate(FITS)["h"]
    # 欄寬縮窄（等同視窗縮放／字型載入後換行位置改變）：沒有 input 事件，也沒有 model 變動
    el.evaluate("e => { e.style.width = '60px' }")
    page.wait_for_function("e => e.getBoundingClientRect().height >= e.scrollHeight - 1 && e.clientWidth <= 62",
                           arg=el.element_handle(), timeout=3000)
    narrow = el.evaluate(FITS)
    assert narrow["h"] > wide, "縮窄後框高沒有跟著變高：%s vs %s" % (narrow, wide)
    assert narrow["h"] >= narrow["sh"] - 1


@pytest.mark.e2e
def test_no_window_errors_and_many_rows_fit(live_server, make_user, e2e_browser):
    # K 審（2026-11-11）：在 ResizeObserver 回呼裡改被觀察元素高度會噴 "ResizeObserver loop completed with
    # undelivered notifications"。改成 rAF 批次後不應再有；30 列同時縮窄欄寬也都要撐得下。
    username, password = make_user(username="e2e_bh6", role="superadmin")
    page = e2e_browser.new_page(viewport={"width": 1400, "height": 900})
    errs = []
    page.add_init_script("window.__errs = []; window.addEventListener('error', e => window.__errs.push(e.message))")
    page.on("pageerror", lambda e: errs.append(str(e)))
    inject_login(page, live_server, username, password)
    _seed([_item(i, brand=LONG, notes=LONG) for i in range(1, 31)])
    page.goto(f"{live_server}/pages/quotation-form.html?id={QUOTE_NO}")
    page.wait_for_function("() => document.querySelectorAll(\"tbody textarea[placeholder='廠牌 / 型號']\").length >= 30", timeout=20000)
    page.locator(BRAND).first.evaluate("e => { document.querySelectorAll('tbody textarea').forEach(x => x.style.width = '70px') }")
    page.wait_for_function(
        "() => [...document.querySelectorAll('tbody textarea')].every(e => e.getBoundingClientRect().height >= e.scrollHeight - 1)",
        timeout=5000)
    assert page.evaluate("window.__errs") == [] and errs == [], (page.evaluate("window.__errs"), errs)


@pytest.mark.e2e
def test_row_hidden_then_shown_regrows(live_server, make_user, e2e_browser):
    # 區段標題列（type=header）的廠牌欄 x-show=false：隱藏時量到 0，不可把高度寫成 0；轉成一般品項顯示後要撐開
    page = _open(live_server, make_user, e2e_browser,
                 [_item(1, type="header", brand=LONG), _item(2)], "e2e_bh5")
    el = page.locator("tbody tr").first.locator("textarea[placeholder='廠牌 / 型號']")
    page.wait_for_timeout(300)
    assert not el.is_visible()
    assert el.evaluate("e => e.style.height") != "0px", "隱藏中量到 0 不可寫成高度（顯示後會被壓成一條線）"
    page.evaluate(f"{DATA}.q.items[0].type = 'item'")
    el.wait_for(state="visible")
    _settle(page, el)
    _assert_fits(el, "隱藏→顯示")
