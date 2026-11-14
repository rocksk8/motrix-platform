"""T86 案件 UX（h8 負責：#4 統一新增記錄、#5 階段勾選復原、#9 財務款項卡、#11 動態輸入框）。

觀測點是畫面本身：點真的勾選框、真的「復原」鈕、真的「顯示」鈕；不是直接呼叫方法。
"""
from tests._requires import requires_module  # noqa: E402
import json
import re
from pathlib import Path

import pytest

pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）')

ROOT = Path(__file__).resolve().parents[2]
NO = "MQ-UXH8-001"
DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"


# ── 靜態釘：前端摺疊「系統自動記錄」靠的字首，要和後端寫入的文字一致 ──────────────────────
def test_auto_stage_prefix_matches_backend_text():
    feed_js = (ROOT / "frontend/js/case-management-feed.js").read_text(encoding="utf-8")
    m = re.search(r"AUTO_STAGE_PREFIX:\s*'([^']+)'", feed_js)
    assert m, "case-management-feed.js 找不到 AUTO_STAGE_PREFIX"
    backend = (ROOT / "backend/modules/case/case_stage_tasks.py").read_text(encoding="utf-8")
    assert f'completion_report=(f"{m.group(1)}' in backend, "後端自動記錄的文字字首與前端 AUTO_STAGE_PREFIX 不一致，摺疊會失效"


def test_undo_toast_text_does_not_contain_daily_task_word():
    """test_e2e_case_stage_daily_task_notice 以「每日任務」過濾模組提示；復原提示若含該詞會被誤算。"""
    exec_js = (ROOT / "frontend/js/case-management-exec.js").read_text(encoding="utf-8")
    seg = exec_js.split("async onStageTick(st)", 1)[1].split("async undoStageDone", 1)[0]
    assert "每日任務" not in seg


def _seed(stages=3, done=0):
    import db
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        ids = []
        for i in range(stages):
            ids.append(conn.execute(
                "INSERT INTO case_stages (quote_no, label, sort_order, done, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (NO, "階段%d" % (i + 1), i, 1 if i < done else 0, now, now)).lastrowid)
        cr = {"payment": {"items": []}, "stages": [{"id": sid, "label": "階段%d" % (i + 1), "done": i < done} for i, sid in enumerate(ids)]}
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "客戶", "專案", 1000, 952,
             json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False), now, now, "已成案", "2026-08-01"))
        conn.commit()
    finally:
        conn.close()


def _stage_done(page, idx):
    """問伺服器（不是看畫面）：第 idx 個階段目前是否完成。測試不可自己對外連線（NETGUARD），所以用頁面的 fetch。"""
    d = page.evaluate("""async (no) => { const t = JSON.parse(localStorage.getItem('motrix_session')).token;
        const r = await fetch('/api/quotations/' + no + '/stages', {headers: {Authorization: 'Bearer ' + t}}); return await r.json() }""", NO)
    rows = d if isinstance(d, list) else d.get("stages") or d.get("items") or []
    return bool(rows[idx].get("done"))


def _open(page, live_server, tab):
    page.goto(f"{live_server}/pages/case-management.html?q={NO}&tab={tab}")
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'", timeout=20000)


@pytest.mark.e2e
def test_tick_stage_shows_undo_and_undo_restores_todo(live_server, make_user, e2e_browser):
    from tests._e2e_login import inject_login
    u = make_user(username="uxh8_e1", role="superadmin")
    _seed()
    page = e2e_browser.new_context().new_page()
    inject_login(page, live_server, u[0], u[1])
    _open(page, live_server, "exec")
    box = page.locator('[data-testid="stage-done-box"]').nth(1)
    box.wait_for(state="visible", timeout=10000)
    box.check()
    toast = page.locator('[data-testid="ui-toast"]', has_text="標為完成")
    toast.wait_for(state="visible", timeout=8000)
    assert "階段2" in toast.inner_text() and "復原" in toast.inner_text()
    page.locator('[data-testid="ui-toast-action"]').click()
    page.wait_for_function(f"() => !{DATA_JS}.cr.caseRecord.stages[1].done", timeout=8000)
    assert box.is_checked() is False
    assert _stage_done(page, 1) is False


@pytest.mark.e2e
def test_auto_feed_items_are_folded_until_shown(live_server, make_user, e2e_browser):
    from tests._e2e_login import inject_login
    u = make_user(username="uxh8_e2", role="superadmin")
    _seed()
    page = e2e_browser.new_context().new_page()
    inject_login(page, live_server, u[0], u[1])
    _open(page, live_server, "exec")
    page.locator('[data-testid="stage-done-box"]').nth(0).check()
    page.locator('[data-testid="ui-toast"]', has_text="標為完成").wait_for(state="visible", timeout=8000)
    page.locator(".cm-tab", has_text="動態").first.click()
    bar = page.locator('[data-testid="cm-feed-autobar"]')
    bar.wait_for(state="visible", timeout=8000)
    assert "已摺疊" in bar.inner_text()
    assert page.locator(".feed-item").count() == 0
    page.locator('[data-testid="cm-feed-autobar-toggle"]').click()
    page.wait_for_function("() => document.querySelectorAll('.feed-item').length === 1", timeout=5000)
    assert "案件管理勾選" in page.locator(".feed-item").first.inner_text()


@pytest.mark.e2e
def test_feed_send_button_hint_and_focus_ring_not_error_red(live_server, make_user, e2e_browser):
    from tests._e2e_login import inject_login
    u = make_user(username="uxh8_e3", role="superadmin")
    _seed()
    page = e2e_browser.new_context().new_page()
    inject_login(page, live_server, u[0], u[1])
    _open(page, live_server, "feed")
    box = page.locator(".feed-compose__box")
    box.wait_for(state="visible", timeout=10000)
    send = page.locator(".feed-compose__send")
    assert send.is_disabled()
    assert page.locator('[data-testid="cm-feed-send-hint"]').is_visible()
    box.focus()
    ring = page.evaluate("() => getComputedStyle(document.querySelector('.feed-compose__box')).borderColor")
    accent = page.evaluate("() => { const e = document.createElement('i'); e.style.color = 'var(--accent)'; document.body.appendChild(e); const c = getComputedStyle(e).color; e.remove(); return c }")
    assert ring != accent, "聚焦外框仍是品牌紅，看起來像驗證錯誤"
    box.fill("測試內容")
    page.locator('[data-testid="cm-feed-send-hint"]').wait_for(state="hidden", timeout=5000)   # x-show 晚一個影格，不能立刻斷言
    assert send.is_enabled()


# ── #9 財務款項卡：發票資料收合＋千分位＋提示改灰字 ─────────────────────────────────────
def _open_fin(live_server, e2e_browser, user):
    from tests.test_e2e_case_concurrent_edit_2026_09_24 import _login, NOTE_INPUT
    from tests.test_case_money_mask_2026_09_24 import NO as MNO
    page = e2e_browser.new_context().new_page()
    page.on("dialog", lambda d: d.accept())
    _login(page, live_server, *user)
    page.goto(f"{live_server}/pages/case-management.html?q={MNO}&tab=fin")
    page.locator(NOTE_INPUT).first.wait_for(state="visible", timeout=20000)
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{MNO}'", timeout=10000)
    return page


@pytest.mark.e2e
def test_payment_card_invoice_section_collapsed_by_default_and_expands(live_server, make_user, e2e_browser):
    from tests.test_case_money_mask_2026_09_24 import _seed as mseed
    u = make_user(username="uxh8_fin1", role="finance")
    mseed(assigned=[u[0]])
    page = _open_fin(live_server, e2e_browser, u)
    toggle0 = page.locator('[data-testid="pay-detail-toggle-0"]')
    toggle1 = page.locator('[data-testid="pay-detail-toggle-1"]')
    assert toggle0.get_attribute("aria-expanded") == "false"
    # 收合時：發票欄位不可見，但標題列摘要告知第一期已填了發票金額；第二期尚未填寫
    assert not page.locator('[data-testid="invoice-pretax"]').nth(0).is_visible()
    assert "已填發票金額" in toggle0.inner_text()
    assert "尚未填寫" in toggle1.inner_text()
    # 預設仍看得到的：預計收款日、收款日期、備註
    assert page.locator('#pay-1-expected').is_visible() and page.locator('#pay-1-received-at').is_visible()
    toggle0.click()
    page.locator('[data-testid="invoice-pretax"]').nth(0).wait_for(state="visible", timeout=5000)
    assert toggle0.get_attribute("aria-expanded") == "true"
    assert page.locator('#pay-1-invno').is_visible()


@pytest.mark.e2e
def test_payment_card_half_filled_invoice_auto_expands(live_server, make_user, e2e_browser):
    from tests.test_case_money_mask_2026_09_24 import _seed as mseed
    u = make_user(username="uxh8_fin2", role="finance")
    mseed(assigned=[u[0]])
    page = _open_fin(live_server, e2e_browser, u)
    toggle1 = page.locator('[data-testid="pay-detail-toggle-1"]')
    toggle1.click()
    page.locator('[data-testid="invoice-pretax"]').nth(1).fill("6000")
    half = page.locator('[data-testid="invoice-half"]').nth(1)
    half.wait_for(state="visible", timeout=5000)
    assert "（需確認）" in toggle1.inner_text()
    # 正對照：第一期（已完整填寫、合計與金額相符）不加「需確認」
    assert "（需確認）" not in page.locator('[data-testid="pay-detail-toggle-0"]').inner_text()


@pytest.mark.e2e
def test_payment_amount_inputs_show_thousands_separator_and_rounding_note_is_not_warning_color(live_server, make_user, e2e_browser):
    from tests.test_case_money_mask_2026_09_24 import _seed as mseed
    u = make_user(username="uxh8_fin3", role="finance")
    mseed(assigned=[u[0]])
    page = _open_fin(live_server, e2e_browser, u)
    # 第一期含稅 3087 ⇒ 3,087；未聚焦時顯示千分位
    assert page.locator('[data-num="wt-1"]').input_value() == "3,087"
    # 聚焦後改打帶千分位的數字仍能解析，存的是數值（第一期不是尾款，不受尾款自動吸收影響）
    box = page.locator('[data-num="wt-1"]')
    box.fill("5,000")
    box.blur()
    page.wait_for_function(f"() => {DATA_JS}.paymentItems()[0].amount === 5000", timeout=5000)
    assert box.input_value() == "5,000"
    note = page.locator('[data-testid="pay-rounding-note"]')
    note.wait_for(state="visible", timeout=5000)
    assert "↩" not in note.inner_text() and "四捨五入" in note.inner_text()
    color = note.evaluate("e => getComputedStyle(e).color")
    warn = page.evaluate("() => { const e = document.createElement('i'); e.style.color = 'var(--tone-orange-fg)'; document.body.appendChild(e); const c = getComputedStyle(e).color; e.remove(); return c }")
    assert color != warn, "四捨五入說明仍用警示橘色"


# ── #29 沒有財務檢視權的人：款項卡只留後端允許改的欄位，其餘唯讀 ───────────────────────────────
@pytest.mark.e2e
def test_masked_user_payment_card_keeps_only_editable_fields(live_server, make_user, e2e_browser):
    from tests.test_case_money_mask_2026_09_24 import _seed as mseed
    u = make_user(username="uxh8_eng29", role="engineer")
    mseed(assigned=[u[0]])
    page = _open_fin(live_server, e2e_browser, u)
    assert page.evaluate(f"() => {DATA_JS}.moneyMasked()") is True
    # 種子：第 1 期（id 1）已收款 2026-09-01；第 2 期（id 2）未收
    ro = page.locator('[data-testid="pay-received-at-ro"]')
    assert ro.nth(0).is_visible() and ro.nth(1).is_visible()
    assert not page.locator('#pay-1-received-at').is_visible() and not page.locator('#pay-2-received-at').is_visible(), "收款日期只給看，沒有輸入框"
    assert "2026-09-01" in ro.nth(0).inner_text()
    assert "尚未收款" in ro.nth(1).inner_text()
    # 未收款的期別：預計收款日、備註、發票號碼（展開後）都能改
    assert page.locator('#pay-2-expected').is_enabled() and page.locator('#pay-2-note').is_enabled()
    page.locator('[data-testid="pay-detail-toggle-1"]').click()
    page.locator('#pay-2-invno').wait_for(state="visible", timeout=5000)
    assert page.locator('#pay-2-invno').is_enabled()
    # 已收款的期別：除發票資料外凍結（後端 _RECEIVED_ITEM_EDITABLE），發票號碼仍可填
    assert page.locator('#pay-1-expected').is_disabled() and page.locator('#pay-1-note').is_disabled()
    page.locator('[data-testid="pay-detail-toggle-0"]').click()
    page.locator('#pay-1-invno').wait_for(state="visible", timeout=5000)
    assert page.locator('#pay-1-invno').is_enabled()
    # 無法由他處理的提示（四捨五入說明）不出現
    assert page.locator('[data-testid="pay-rounding-note"]').count() == 0


@pytest.mark.e2e
def test_finance_user_still_edits_received_date(live_server, make_user, e2e_browser):
    """正對照：有財務檢視權的人仍看得到收款日期輸入框與四捨五入說明。"""
    from tests.test_case_money_mask_2026_09_24 import _seed as mseed
    u = make_user(username="uxh8_fin29", role="finance")
    mseed(assigned=[u[0]])
    page = _open_fin(live_server, e2e_browser, u)
    assert page.locator('#pay-1-received-at').is_visible()
    assert page.locator('[data-testid="pay-received-at-ro"]').first.is_hidden()
    assert page.locator('[data-testid="pay-rounding-note"]').count() == 1


# ── #31 手機動態輸入列：單欄堆疊 ───────────────────────────────────────────────────────
@pytest.mark.e2e
def test_feed_compose_stacks_in_one_column_on_phone(live_server, make_user, e2e_browser):
    from tests._e2e_login import inject_login
    u = make_user(username="uxh8_e31", role="superadmin")
    _seed()
    page = e2e_browser.new_context(viewport={"width": 390, "height": 844}).new_page()
    inject_login(page, live_server, u[0], u[1])
    _open(page, live_server, "feed")
    page.locator(".feed-compose__box").wait_for(state="visible", timeout=10000)
    boxes = page.evaluate("""() => [...document.querySelectorAll('[data-testid=cm-feed-fields] .feed-compose__field')]
        .map(e => { const r = e.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.top), Math.round(r.width)] })""")
    assert len(boxes) == 4
    assert len({b[0] for b in boxes}) == 1, "四個欄位左緣要對齊（單欄）：%r" % boxes
    assert all(boxes[i][1] < boxes[i + 1][1] for i in range(3)), "四個欄位要由上而下排列：%r" % boxes
    # 發布鈕獨佔一列、寬度接近整列；附檔與重要勾選各自一列
    send = page.locator(".feed-compose__send").bounding_box()
    box = page.locator(".feed-compose__box").bounding_box()
    assert send["width"] >= box["width"] - 4, (send, box)
    attach = page.locator('[data-testid="cm-feed-attach"]').bounding_box()
    assert attach["y"] + attach["height"] <= send["y"] + 1, "附加檔案與發布鈕不可同列"
    # 控制項夠寬、不被截斷；整頁不橫向溢位
    ctl_w = page.evaluate("() => [...document.querySelectorAll('.feed-compose__ctl')].filter(e => e.offsetParent).map(e => Math.round(e.getBoundingClientRect().width))")
    assert all(w >= 140 for w in ctl_w), ctl_w
    assert page.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
    # 「標記為重要」說明文字不折成三行（單行高度約一行）
    imp = page.locator('[data-testid="cm-feed-important"]').bounding_box()
    assert imp["height"] <= 48, imp


@pytest.mark.e2e
def test_feed_compose_stays_a_row_on_desktop(live_server, make_user, e2e_browser):
    from tests._e2e_login import inject_login
    u = make_user(username="uxh8_e31d", role="superadmin")
    _seed()
    page = e2e_browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
    inject_login(page, live_server, u[0], u[1])
    _open(page, live_server, "feed")
    page.locator(".feed-compose__box").wait_for(state="visible", timeout=10000)
    tops = page.evaluate("() => [...document.querySelectorAll('[data-testid=cm-feed-fields] .feed-compose__field')].map(e => Math.round(e.getBoundingClientRect().top))")
    assert len(set(tops)) == 1, "電腦版四個欄位維持同一列：%r" % tops


# ── #4 統一的「新增記錄」編輯器（動態分頁）：類型下拉＝留言／工作日誌、階段出勤、每日工作事項 ──────────────
def _stage_visits(page, idx):
    d = page.evaluate("""async (no) => { const t = JSON.parse(localStorage.getItem('motrix_session')).token;
        const r = await fetch('/api/quotations/' + no + '/stages', {headers: {Authorization: 'Bearer ' + t}}); return await r.json() }""", NO)
    rows = d if isinstance(d, list) else d.get("stages") or d.get("items") or []
    return rows[idx].get("visits") or []


@pytest.mark.e2e
def test_compose_type_dropdown_adds_a_stage_visit_from_the_feed_tab(live_server, make_user, e2e_browser):
    from tests._e2e_login import inject_login
    u = make_user(username="uxh8_c4a", role="superadmin")
    _seed()
    page = e2e_browser.new_context().new_page()
    inject_login(page, live_server, u[0], u[1])
    _open(page, live_server, "feed")
    sel = page.locator('[data-testid="cm-compose-type"]')
    sel.wait_for(state="visible", timeout=10000)
    assert page.eval_on_selector_all('[data-testid="cm-compose-type"] option', "els => els.map(e => e.value)") == ["note", "visit", "task"]
    # 預設是留言／工作日誌：階段欄位不在畫面上
    assert page.locator('[data-testid="cm-compose-stage"]').is_hidden()
    sel.select_option("visit")
    stage = page.locator('[data-testid="cm-compose-stage"]')
    stage.wait_for(state="visible", timeout=5000)
    assert page.locator('[data-testid="cm-feed-fields"]').is_hidden(), "選了階段出勤，留言用的欄位（執行時數等）要收起來"
    assert stage.input_value() != "", "預設帶入第一個未完成的階段"
    assert page.locator('[data-testid="cm-compose-people"]').input_value() == "1"
    send = page.locator('[data-testid="cm-compose-send"]')
    assert send.inner_text().strip() == "新增出勤記錄" and send.is_enabled()
    page.locator('[data-testid="cm-compose-people"]').fill("")
    page.wait_for_function("() => document.querySelector('[data-testid=\"cm-compose-send\"]').disabled", timeout=5000)
    assert "人次" in page.locator('[data-testid="cm-feed-send-hint"]').inner_text()
    page.locator('[data-testid="cm-compose-people"]').fill("3")
    page.locator(".feed-compose__box").fill("拉線到二樓")
    send.click()
    page.locator('[data-testid="ui-toast"]', has_text="新增出勤記錄").wait_for(state="visible", timeout=8000)
    visits = _stage_visits(page, 0)
    assert len(visits) == 1 and visits[0]["visitPeople"] == 3 and visits[0]["note"] == "拉線到二樓", visits
    assert page.locator(".feed-compose__box").input_value() == "", "送出後清空內容"


@pytest.mark.e2e
def test_compose_task_type_only_links_to_daily_tasks_with_the_case(live_server, make_user, e2e_browser):
    from tests._e2e_login import inject_login
    u = make_user(username="uxh8_c4b", role="superadmin")
    _seed()
    page = e2e_browser.new_context().new_page()
    inject_login(page, live_server, u[0], u[1])
    _open(page, live_server, "feed")
    page.locator('[data-testid="cm-compose-type"]').select_option("task")
    link = page.locator('[data-testid="cm-compose-task-link"]')
    link.wait_for(state="visible", timeout=5000)
    assert link.get_attribute("href") == "daily-tasks.html?case_no=" + NO
    page.locator('[data-testid="cm-compose-send"]').wait_for(state="hidden", timeout=5000)


@pytest.mark.e2e
def test_log_entry_links_only_jump_to_the_editor_with_the_type_preselected(live_server, make_user, e2e_browser):
    from tests._e2e_login import inject_login
    from tests.test_e2e_onepipe_p4b_2026_11_13 import _flag
    u = make_user(username="uxh8_c4c", role="superadmin")
    _seed()
    _flag(True)
    try:
        page = e2e_browser.new_context().new_page()
        inject_login(page, live_server, u[0], u[1])
        _open(page, live_server, "biz")
        page.locator('[data-testid="case-log-entry"]').wait_for(state="visible", timeout=15000)
        page.locator('[data-testid="case-log-visit"]').click()
        page.locator('[data-testid="cm-compose-stage"]').wait_for(state="visible", timeout=8000)
        assert page.locator('[data-testid="cm-compose-type"]').input_value() == "visit"
        page.locator(".cm-tab", has_text="案件資訊").first.click()
        page.locator('[data-testid="case-log-feed"]').click()
        page.locator('[data-testid="cm-compose-stage"]').wait_for(state="hidden", timeout=8000)
        assert page.locator('[data-testid="cm-compose-type"]').input_value() == "note"
        page.wait_for_function("() => document.activeElement && document.activeElement.classList.contains('feed-compose__box')", timeout=5000)
    finally:
        _flag(False)
