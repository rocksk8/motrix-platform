# -*- coding: utf-8 -*-
"""未讀紅點：點下去**當下**就消失、上一頁回來仍消失、另一分頁會同步。

使用者（2026-09-24）逐字：「目前很多使用者反應，我點選選進某些未讀的，
點選後紅色未讀沒有即時消失」。

## 「當下」怎麼量

把 `POST /api/reads` **攔住不放行**，在伺服器還沒收到之前量畫面：
標記若是等回應才清，這時一定還在。放行之後再驗伺服器真的記下了。
"""
import json
import time
from datetime import datetime

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

from tests.test_voucher_preview_export_feedback_2026_09_23 import (  # noqa: E402,F401
    live_server, _login)


def _uid(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    finally:
        conn.close()


def _sql(q, args=()):
    import db
    conn = db.get_db()
    try:
        cur = conn.execute(q, args)
        conn.commit()
        return cur
    finally:
        conn.close()


def _rows(q, args=()):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(q, args).fetchall()]
    finally:
        conn.close()


def _dev_case(owner, name):
    now = datetime.now().isoformat()
    return _sql("INSERT INTO dev_cases (case_name, created_by, created_at, updated_at) VALUES (?,?,?,?)",
                (name, _uid(owner), now, now)).lastrowid


def _audit(username, action, target_type, target_id):
    time.sleep(0.02)
    _sql("INSERT INTO audit_log (at,user_id,username,display_name,action,target_type,target_id,"
         "target_label,detail) VALUES (?,?,?,?,?,?,?,?,?)",
         (datetime.now().isoformat(), None, username, username, action, target_type,
          str(target_id), "", "{}"))


def _alpine_ready(page):
    page.wait_for_function("() => window.Alpine && document.querySelector('[x-data]')"
                           " && Alpine.$data(document.querySelector('[x-data]'))", timeout=15000)


class _Hold:
    """把 `POST /api/reads` 攔住，直到 `release()` —— 用來量「伺服器回應之前」。"""

    def __init__(self, page):
        self.held = []
        page.route("**/api/reads", self._on)

    def _on(self, route):
        if route.request.method == "POST":
            self.held.append(route)
        else:
            route.continue_()

    def bodies(self):
        return [json.loads(r.request.post_data or "{}") for r in self.held]

    def release(self):
        for r in self.held:
            r.continue_()
        self.held = []


def _dev_crm_with_one_unread(page, live_server):
    """進業務開發（第一次進 ⇒ 建立基準）→ 別人改了那一筆 → 重整 ⇒ 那一筆亮「有更新」。"""
    page.goto(live_server + "/pages/dev-crm.html")
    _alpine_ready(page)
    page.wait_for_selector(".dc-case-card:has-text('紅點測試')", timeout=15000)
    page.wait_for_timeout(600)          # 讓第一次的未讀查詢（建立基準）完成
    cid = _rows("SELECT id FROM dev_cases WHERE case_name='紅點測試'")[0]["id"]
    _audit("bob", "dev_case.update", "dev_case", cid)
    page.reload()
    _alpine_ready(page)
    card = page.locator(".dc-case-card:has-text('紅點測試')")
    card.locator("text=有更新").wait_for(state="visible", timeout=15000)
    return cid, card


@pytest.mark.e2e
def test_dev_case_mark_clears_on_click_before_the_server_answers_and_stays_cleared(
        live_server, make_user):
    make_user(username="bob", role="admin")
    u, pw = make_user(username="alice", role="superadmin")
    _dev_case("bob", "紅點測試")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        _login(page, live_server, u, pw)
        cid, card = _dev_crm_with_one_unread(page, live_server)

        hold = _Hold(page)
        card.click()
        page.wait_for_timeout(300)
        # 🔴 伺服器還沒收到 ⇒ 若畫面等回應才清，這裡標記一定還在
        assert {"kind": "dev_case", "key": str(cid)} in hold.bodies(), hold.bodies()
        assert not _rows("SELECT 1 FROM item_reads WHERE kind='dev_case' AND item_key=?", (str(cid),))
        assert card.locator("text=有更新").count() == 0, "點下去之後標記沒有當下消失"

        hold.release()
        page.unroute("**/api/reads")
        for _ in range(50):
            if _rows("SELECT 1 FROM item_reads WHERE username='alice' AND kind='dev_case' AND item_key=?",
                     (str(cid),)):
                break
            page.wait_for_timeout(100)
        else:
            pytest.fail("已讀沒有寫進伺服器")

        # 上一頁回來仍然是已讀
        page.goto(live_server + "/index.html")
        page.go_back()
        _alpine_ready(page)
        page.wait_for_selector(".dc-case-card:has-text('紅點測試')", timeout=15000)
        page.wait_for_timeout(800)
        assert page.locator(".dc-case-card:has-text('紅點測試') >> text=有更新").count() == 0
        browser.close()


@pytest.mark.e2e
def test_another_tab_drops_the_mark_without_reloading(live_server, make_user):
    make_user(username="bob", role="admin")
    u, pw = make_user(username="alice", role="superadmin")
    _dev_case("bob", "紅點測試")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        a = ctx.new_page()
        _login(a, live_server, u, pw)
        cid, card_a = _dev_crm_with_one_unread(a, live_server)
        b = ctx.new_page()
        b.goto(live_server + "/pages/dev-crm.html")
        _alpine_ready(b)
        card_b = b.locator(".dc-case-card:has-text('紅點測試')")
        card_b.locator("text=有更新").wait_for(state="visible", timeout=15000)

        card_a.click()
        # 另一分頁：不重整，靠 storage 事件重抓
        card_b.locator("text=有更新").wait_for(state="detached", timeout=8000)
        browser.close()


@pytest.mark.e2e
def test_bell_marks_only_the_notification_that_was_clicked(live_server, make_user):
    u, pw = make_user(username="alice", role="superadmin")
    now = datetime.now().isoformat()
    ids = [_sql("INSERT INTO notifications (username, type, ref_id, ref_label, message, is_read, "
                "created_at) VALUES (?,?,?,?,?,0,?)",
                ("alice", "info", "", "通知%s" % i, "內容%s" % i, now)).lastrowid for i in (1, 2)]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        _login(page, live_server, u, pw)
        page.wait_for_timeout(800)
        page.locator(".topbar__btn:has-text('通知')").click()
        first = page.locator("[data-notif-id='%s']" % ids[0])
        second = page.locator("[data-notif-id='%s']" % ids[1])
        first.wait_for(state="visible", timeout=10000)
        assert first.get_attribute("data-unread") == "1"
        # 打開下拉**不再**全部標為已讀
        page.wait_for_timeout(500)
        assert [r["is_read"] for r in _rows("SELECT is_read FROM notifications ORDER BY id")] == [0, 0]

        first.click()
        assert first.get_attribute("data-unread") == "0"
        assert second.get_attribute("data-unread") == "1"
        for _ in range(50):
            got = [r["is_read"] for r in _rows("SELECT is_read FROM notifications ORDER BY id")]
            if got == [1, 0]:
                break
            page.wait_for_timeout(100)
        assert got == [1, 0], got
        browser.close()


@pytest.mark.e2e
def test_menu_badge_clears_the_moment_the_item_is_clicked(live_server, make_user):
    make_user(username="bob", role="admin")
    u, pw = make_user(username="alice", role="superadmin")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        _login(page, live_server, u, pw)
        tok = page.evaluate("() => JSON.parse(localStorage.getItem('motrix_session')).token")
        r = page.request.post(live_server + "/api/reads", headers={"Authorization": "Bearer " + tok},
                              data={"kind": "module", "key": "customer"})
        assert r.ok, r.text()
        _audit("bob", "customer.update", "customer", 1)
        page.reload()
        badge = page.locator("#sb-mod-customer")
        page.wait_for_function(
            "() => { const b = document.getElementById('sb-mod-customer');"
            " return b && getComputedStyle(b).display !== 'none' && b.textContent.trim() === '1' }",
            timeout=15000)
        # 只量「點下去那一刻」：擋住換頁，並攔住已讀請求
        page.evaluate("""() => document.addEventListener('click', e => {
            const a = e.target.closest('a[href]'); if (a) e.preventDefault() })""")
        hold = _Hold(page)
        link = page.locator("a[href$='customers.html']:visible").first
        if link.count() == 0:
            page.locator(".mnav__grp:has(a[href$='customers.html'])").first.hover()
            link = page.locator("a[href$='customers.html']:visible").first
        link.click()
        page.wait_for_timeout(300)
        assert {"kind": "module", "key": "customer"} in hold.bodies(), hold.bodies()
        assert page.evaluate("() => getComputedStyle(document.getElementById('sb-mod-customer')).display") == "none"
        hold.release()
        browser.close()


@pytest.mark.e2e
def test_case_switch_cancelled_keeps_the_unread_mark(live_server, make_user):
    """案件管理：切換前會先存檔，存檔失敗時問要不要放棄；選「否」就留在原案件
    ⇒ 那一筆**沒有被打開**，未讀標記必須還在，也不可以送出已讀。"""
    u, pw = make_user(username="alice", role="superadmin")
    now = datetime.now().isoformat()
    for no in ("MQ-A", "MQ-B"):
        _sql("INSERT INTO quotations (quote_no, status, sales_person, sales_person_id, data_json, "
             "created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?)",
             (no, "已成案", "alice", _uid("alice"), json.dumps({"quoteNo": no}), now, now, "已成案"))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        _login(page, live_server, u, pw)
        page.goto(live_server + "/pages/case-management.html")
        _alpine_ready(page)
        # 📌 更正（2026-09-24，hichan-8d 全量裡紅過 1 次）：原本固定等 1 秒。
        #    負載下初始化的未讀查詢晚於 1 秒回來，會在下面 `await fetch(MQ-B)` 的空隙
        #    把注入的 caseActivity 整包蓋掉 ⇒ `_markCaseRead` 找不到那一筆、不送已讀。
        #    那同時是一個產品競態（見 test_case_management_late_unread_answer_...），
        #    產品已修；這裡改成等初始化的請求真的結束，再注入狀態。
        page.wait_for_load_state("networkidle")
        sent = []
        page.on("request", lambda r: sent.append(r.post_data) if r.url.endswith("/api/reads")
                and r.method == "POST" else None)

        cancelled = page.evaluate("""async () => {
            const d = Alpine.$data(document.querySelector('[x-data]'))
            d.caseActivity = { 'MQ-B': true }
            d.selected = { quote_no: 'MQ-A' }
            d.dirty = true
            d.saving = false
            d.saveCaseRecord = async () => {}      // 存檔失敗：dirty 還是 true
            window.confirm = () => false           // 使用者選「否」
            await d.selectCase('MQ-B')
            return { mark: !!d.caseActivity['MQ-B'], sel: d.selected.quote_no }
        }""")
        page.wait_for_timeout(300)
        assert cancelled == {"mark": True, "sel": "MQ-A"}, cancelled
        assert not [s for s in sent if s and "MQ-B" in s], sent

        # 正對照：選「是」＝真的切換過去 ⇒ 標記消失、已讀送出
        # 固定等 300ms 在負載下不夠 ⇒ 改成等那一個請求真的送出。
        with page.expect_request(lambda r: r.url.endswith("/api/reads") and r.method == "POST"
                                 and "MQ-B" in (r.post_data or ""), timeout=10000):
            switched = page.evaluate("""async () => {
                const d = Alpine.$data(document.querySelector('[x-data]'))
                window.confirm = () => true
                await d.selectCase('MQ-B')
                return { mark: !!d.caseActivity['MQ-B'], sel: d.selected.quote_no }
            }""")
        assert switched == {"mark": False, "sel": "MQ-B"}, switched
        browser.close()


class _LateUnread:
    """把「未讀查詢」的回應**先向伺服器取回、晚一點才交給頁面**。

    重現的是負載下的真實時序：查詢在使用者點選**之前**送出（伺服器那時還沒有已讀紀錄），
    回應在點選**之後**才抵達。
    """

    def __init__(self, page):
        self.held = []
        page.route("**/api/reads/unread", self._on)

    def _on(self, route):
        self.held.append((route, route.fetch()))

    def release(self):
        for route, resp in self.held:
            route.fulfill(response=resp)
        self.held = []


@pytest.mark.e2e
def test_a_late_unread_answer_does_not_bring_back_a_mark_clicked_meanwhile(live_server, make_user):
    """先渲染再非同步載入＝競態：點過的那一筆，不可以被一個「點選前就送出」的查詢蓋回未讀。"""
    make_user(username="bob", role="admin")
    u, pw = make_user(username="alice", role="superadmin")
    _dev_case("bob", "紅點測試")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        _login(page, live_server, u, pw)
        cid, card = _dev_crm_with_one_unread(page, live_server)

        late = _LateUnread(page)
        page.evaluate("() => window.dispatchEvent(new CustomEvent('motrix:reads-changed'))")
        for _ in range(50):
            if late.held:
                break
            page.wait_for_timeout(100)
        assert late.held, "重抓未讀的請求沒有送出"
        card.click()
        page.wait_for_timeout(300)
        assert card.locator("text=有更新").count() == 0
        late.release()
        page.wait_for_timeout(500)
        assert card.locator("text=有更新").count() == 0, "晚到的未讀回應把剛點過的那一筆蓋回未讀"
        browser.close()


@pytest.mark.e2e
def test_case_management_late_unread_answer_does_not_undo_a_click(live_server, make_user):
    make_user(username="bob", role="admin")
    u, pw = make_user(username="alice", role="superadmin")
    now = datetime.now().isoformat()
    _sql("INSERT INTO quotations (quote_no, status, sales_person, sales_person_id, data_json, "
         "created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?)",
         ("MQ-B", "已成案", "alice", _uid("alice"), json.dumps({"quoteNo": "MQ-B"}), now, now, "已成案"))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        _login(page, live_server, u, pw)
        page.goto(live_server + "/pages/case-management.html")
        _alpine_ready(page)
        page.wait_for_load_state("networkidle")
        time.sleep(1.1)
        _sql("INSERT INTO case_updates (quote_no, author, content, created_at) VALUES (?,?,?,?)",
             ("MQ-B", "bob", "x", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        late = _LateUnread(page)
        page.evaluate("() => { Alpine.$data(document.querySelector('[x-data]')).loadCaseActivity() }")
        for _ in range(50):
            if late.held:
                break
            page.wait_for_timeout(100)
        assert late.held
        page.evaluate("() => { const d = Alpine.$data(document.querySelector('[x-data]'));"
                      " d.caseActivity = { ...d.caseActivity, 'MQ-B': true }; d._markCaseRead('MQ-B') }")
        late.release()
        page.wait_for_timeout(500)
        assert page.evaluate("() => !!Alpine.$data(document.querySelector('[x-data]')).caseActivity['MQ-B']") is False
        browser.close()
