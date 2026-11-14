# -*- coding: utf-8 -*-
"""業務開發 UX 巡檢（hichan-10，2026-11-14）批次 A：深連結 ?case=、人員挑選、手機漏斗／篩選、admin 不被通用鎖頁擋、
連結說明、無結果提示、詳情固定列、使用者／客戶延後載入。"""
import re
from core import source_tree
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DC = source_tree.page_file("dev-crm.html").read_text(encoding="utf-8")
SIDEBAR = (ROOT / "frontend/static/sidebar.js").read_text(encoding="utf-8")
NOTIF = (ROOT / "frontend/static/notif.js").read_text(encoding="utf-8")
CRM_API = (ROOT / "backend/modules/crm/api.py").read_text(encoding="utf-8")


# ── 靜態 ─────────────────────────────────────────────────────────────
def test_every_crm_notification_links_to_the_case_not_the_bare_page():
    """通知／搜尋點進來要選到那一件商機：後端的 link 一律帶 ?case=<id>。"""
    assert "def _case_link(" in CRM_API
    bare = re.findall(r"""(?:notify|_notify)[^\n]*["']dev-crm\.html["']""", CRM_API)
    assert not bare, "還有通知用不帶案件編號的連結：%s" % bare[:3]


def test_search_and_bell_jump_with_case_param():
    assert "goDevCase(id)" in NOTIF and "'?case='" in NOTIF
    assert '@click="goDevCase(item.id)"' in SIDEBAR


def test_page_reads_case_param_and_tells_when_missing():
    assert "_openFromUrl" in DC and "get('case')" in DC
    assert "找不到這個商機，或您沒有權限查看。" in DC


def test_sidebar_leaves_dev_crm_to_its_own_gate():
    assert "file !== 'dev-crm.html'" in SIDEBAR


def test_mobile_funnel_is_one_scrollable_row_and_hides_in_detail():
    assert ".dc-funnel.dc-has-sel { display: none; }" in DC
    assert "flex-wrap: nowrap; overflow-x: auto" in DC
    assert "dc-filter-toggle" in DC and "filtersOpen" in DC


def test_empty_state_offers_clear_filters_and_funnel_note():
    assert 'data-testid="dc-clear-filters"' in DC and 'data-testid="dc-funnel-note"' in DC
    assert "查無符合條件的商機。" in DC and "上方數字依目前的搜尋／篩選結果計算。" in DC
    assert "無符合商機" not in DC


def test_relink_button_has_text_and_sales_get_a_hint():
    assert "修改連結" in DC and 'data-testid="dc-relink-btn"' in DC
    assert "要修改連結或刪除商機，請洽主管。" in DC
    assert 'style="width:20px;height:20px;padding:0"' not in DC


def test_users_and_customers_are_not_fetched_on_first_load():
    m = re.search(r"async init\(\) \{.*?\n    \},\n", DC, re.S)
    assert m, "找不到 init()"
    body = m.group(0)
    assert "loadUsers()" not in body and "loadCustomers()" not in body
    assert "_ensureUsers" in DC and "_ensureCustomers" in DC


def test_picker_choices_follow_role():
    assert "personChoices('sales')" in DC and "personChoices('planner')" in DC
    assert "顯示全部人員" in DC


# ── e2e ─────────────────────────────────────────────────────────────
pytest.importorskip("playwright.sync_api")


def _mk_case(client, token, name, **kw):
    r = client.post("/api/dev-cases", json={"case_name": name, "customer_name": "測試客戶", "sales_persons": kw.get("sales", []), "planners": []},
                    headers={"Authorization": "Bearer " + token})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _token(client, user):
    r = client.post("/api/auth/login", json={"username": user[0], "password": user[1]})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.mark.e2e
def test_deep_link_selects_the_case_and_missing_one_says_so(live_server, make_user, new_page, login_as, client):
    u = make_user(username="e2e_dca_sales", role="sales", modules=["dev_crm"])
    tok = _token(client, tuple(u)[:2])
    cid = _mk_case(client, tok, "深連結商機甲")
    for k in range(3):
        _mk_case(client, tok, "陪襯案件%d" % k)
    page = new_page()
    login_as(page, tuple(u)[:2])
    page.goto(f"{live_server}/pages/dev-crm.html?case={cid}")
    page.wait_for_function(
        "() => { const d = Alpine.$data(document.querySelector('[x-data=\"devCrmPage()\"]')); return d.selectedCase && d.selectedCase.id === %d }" % cid,
        timeout=15000)
    assert page.locator(".dc-detail-title").first.inner_text() == "深連結商機甲"
    page.goto(f"{live_server}/pages/dev-crm.html?case=99999999")
    page.get_by_text("找不到這個商機，或您沒有權限查看。").wait_for(timeout=10000)


@pytest.mark.e2e
def test_admin_without_the_module_is_not_blocked_by_the_generic_lock(live_server, make_user, new_page, login_as, client):
    u = make_user(username="e2e_dca_admin_nomod", role="admin", modules=["quotation"])
    page = new_page()
    login_as(page, tuple(u)[:2])
    page.goto(f"{live_server}/pages/dev-crm.html")
    page.wait_for_timeout(3000)
    assert page.locator('[data-testid="dev-crm-no-access"]').count() == 0
    assert page.locator(".dc-funnel").count() == 1
    body = page.inner_text("body")
    assert "您沒有這個頁面的權限" not in body


@pytest.mark.e2e
def test_first_load_does_not_fetch_users_or_customers_but_opening_a_case_does(live_server, make_user, new_page, login_as, client):
    u = make_user(username="e2e_dca_lazy", role="sales", modules=["dev_crm"])
    _mk_case(client, _token(client, tuple(u)[:2]), "延後載入案")
    page = new_page()
    login_as(page, tuple(u)[:2])
    urls = []
    page.on("request", lambda r: urls.append(r.url) if "/api/" in r.url else None)
    page.goto(f"{live_server}/pages/dev-crm.html")
    page.locator(".dc-case-card").first.wait_for(timeout=15000)
    page.wait_for_timeout(800)
    assert not [x for x in urls if "/api/customers" in x or "/api/users" in x], urls
    page.locator(".dc-case-card").first.click()
    page.wait_for_timeout(1500)
    assert [x for x in urls if "/api/users" in x]


@pytest.mark.e2e
def test_no_match_search_shows_note_and_clear_button(live_server, make_user, new_page, login_as, client):
    u = make_user(username="e2e_dca_nomatch", role="sales", modules=["dev_crm"])
    _mk_case(client, _token(client, tuple(u)[:2]), "有案件")
    page = new_page()
    login_as(page, tuple(u)[:2])
    page.goto(f"{live_server}/pages/dev-crm.html")
    page.locator(".dc-case-card").first.wait_for(timeout=15000)
    page.locator(".dc-search").first.fill("不存在的客戶xyz")
    page.locator('[data-testid="dc-funnel-note"]').wait_for(state="visible", timeout=8000)
    page.locator('[data-testid="dc-clear-filters"]').locator("visible=true").first.click()
    page.locator(".dc-case-card").first.wait_for(timeout=8000)


@pytest.mark.e2e
def test_mobile_390_funnel_is_compact_and_filters_collapse(live_server, make_user, new_page, login_as, client):
    u = make_user(username="e2e_dca_mobile", role="sales", modules=["dev_crm"])
    _mk_case(client, _token(client, tuple(u)[:2]), "手機案")
    page = new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    login_as(page, tuple(u)[:2])
    page.goto(f"{live_server}/pages/dev-crm.html")
    page.locator(".dc-case-card").first.wait_for(timeout=15000)
    h = page.evaluate("() => document.querySelector('.dc-funnel').getBoundingClientRect().height")
    assert h < 100, h
    assert page.evaluate("() => getComputedStyle(document.querySelector('.dc-filters')).display") == "none"
    page.locator(".dc-filter-toggle").click()
    assert page.evaluate("() => getComputedStyle(document.querySelector('.dc-filters')).display") != "none"
    assert page.evaluate("() => Math.round(document.querySelector('.dc-sortbtn').getBoundingClientRect().height)") >= 44
    assert not page.evaluate("() => document.documentElement.scrollWidth > innerWidth + 1")
    page.locator(".dc-case-card").first.click()
    page.wait_for_timeout(800)
    assert page.evaluate("() => getComputedStyle(document.querySelector('.dc-funnel')).display") == "none"


# ══ 批次 B：成案≠已連結、狀態變更確認＋原因、轉建表單契約、失敗提示 ═════════════════════════
def test_status_change_asks_first_and_never_fails_silently():
    for s in ("未成案", "暫擱置", "洽談中"):
        assert "askStatus('%s')" % s in DC
    assert 'data-testid="dc-status-modal"' in DC and 'data-testid="dc-status-reason"' in DC
    assert "暫擱置的商機超過 180 天沒有動靜，系統會自動轉為「未成案」。" in DC
    assert "重回洽談中不會動到單據，連結會保留" in DC
    assert "狀態沒有更新：" in DC          # 失敗有提示
    assert "markConverted" not in DC and "convertQuoteNo" not in DC   # 手動輸入單號已拿掉（PM 2026-11-14）
    assert 'data-testid="card-linked-talk"' in DC and "已連結單據（洽談中）" in DC   # #6：洽談中仍連著單據要標示


def test_convert_hands_over_customer_project_type_and_case_id():
    m = re.search(r"    doConvert\(\) \{.*?\n    \},\n", DC, re.S)
    assert m
    body = m.group(0)
    for needle in ("p.set('customer'", "p.set('project'", "p.set('type', 'estimate')", "p.set('devCase'"):
        assert needle in body, needle
    assert "_refreshAfterConvert" in DC and "visibilitychange" in DC


def test_won_card_says_how_many_are_unlinked():
    assert 'data-testid="dc-won-sub"' in DC and "件尚未連結單據" in DC
    assert 'data-testid="card-unlinked"' in DC and 'data-testid="detail-unlinked"' in DC


def test_toast_cancels_the_previous_timer():
    assert "clearTimeout(this._toastT)" in DC


@pytest.mark.e2e
def test_unmade_and_hold_need_confirmation_and_reason_lands_in_the_log(live_server, make_user, new_page, login_as, client):
    u = make_user(username="e2e_dcb_status", role="sales", modules=["dev_crm"])
    cid = _mk_case(client, _token(client, tuple(u)[:2]), "狀態確認案", sales=[])
    page = new_page()
    login_as(page, tuple(u)[:2])
    page.goto(f"{live_server}/pages/dev-crm.html?case={cid}")
    page.get_by_role("button", name="設為未成案").wait_for(timeout=15000)
    page.get_by_role("button", name="設為未成案").click()
    page.locator('[data-testid="dc-status-modal"]').wait_for(state="visible", timeout=5000)
    # 還沒確認 ⇒ 狀態沒變
    assert page.evaluate("() => Alpine.$data(document.querySelector('[x-data=\"devCrmPage()\"]')).selectedCase.status") == "洽談中"
    page.locator('[data-testid="dc-status-reason"]').fill("客戶預算不足")
    page.locator('[data-testid="dc-status-confirm"]').click()
    page.wait_for_function("() => Alpine.$data(document.querySelector('[x-data=\"devCrm"
                           "Page()\"]')).selectedCase.status === '未成案'", timeout=8000)
    page.wait_for_function("() => Alpine.$data(document.querySelector('[x-data=\"devCrmPage()\"]')).devLogs.some(l => (l.content||'').includes('客戶預算不足'))", timeout=8000)


@pytest.mark.e2e
def test_won_without_link_is_flagged_and_convert_modal_opens_form_with_params(live_server, make_user, new_page, login_as, client):
    u = make_user(username="e2e_dcb_convert", role="sales", modules=["dev_crm"])
    cid = _mk_case(client, _token(client, tuple(u)[:2]), "成案未連結案", sales=[])
    page = new_page()
    login_as(page, tuple(u)[:2])
    page.goto(f"{live_server}/pages/dev-crm.html?case={cid}")
    page.get_by_role("button", name="設為成案").wait_for(timeout=15000)
    page.get_by_role("button", name="設為成案").click()
    page.locator('[data-testid="detail-unlinked"]').wait_for(state="visible", timeout=8000)
    assert "尚未連結單據" in page.locator('[data-testid="dc-won-sub"]').inner_text()
    page.get_by_role("button", name="轉建報價單／估價單").click()
    page.locator('[data-testid="dc-doc-estimate"]').evaluate("e => e.click()")
    with page.context.expect_page() as pop:
        page.locator('[data-testid="dc-convert-go"]').click()
    url = pop.value.url
    assert "type=estimate" in url and f"devCase={cid}" in url and "project=" in url, url


# ══ U3：開發記錄連續新增 ═══════════════════════════════════════════════════════
def test_log_form_has_save_and_next_and_remembers_channel_and_date():
    assert 'data-testid="log-save-next"' in DC and "儲存並新增下一筆" in DC
    assert "saveLog(true)" in DC and "_lastLog" in DC
    assert "dc_last_log_channel" in DC


@pytest.mark.e2e
def test_save_and_next_keeps_form_open_with_channel_and_date(live_server, make_user, new_page, login_as, client):
    u = make_user(username="e2e_dcu3", role="sales", modules=["dev_crm"])
    cid = _mk_case(client, _token(client, tuple(u)[:2]), "連續記錄案", sales=[])
    page = new_page()
    login_as(page, tuple(u)[:2])
    page.goto(f"{live_server}/pages/dev-crm.html?case={cid}")
    page.get_by_role("button", name="新增記錄").wait_for(timeout=15000)
    page.get_by_role("button", name="新增記錄").click()
    data = "Alpine.$data(document.querySelector('[x-data=\"devCrmPage()\"]'))"
    page.evaluate("() => { const d = %s; d.logForm.channel = '電話'; d.logForm.content = '第一筆' }" % data)
    page.locator('[data-testid="log-save-next"]').click()
    page.wait_for_function("() => %s.devLogs.length === 1" % data, timeout=8000)
    assert page.evaluate("() => %s.showLogForm" % data) is True
    assert page.evaluate("() => [%s.logForm.channel, %s.logForm.content]" % (data, data)) == ["電話", ""]
    page.evaluate("() => { %s.logForm.content = '第二筆' }" % data)
    page.locator('[data-testid="log-save"]').click()
    page.wait_for_function("() => %s.devLogs.length === 2 && !%s.showLogForm" % (data, data), timeout=8000)


def test_review_fixes_h5():
    assert ".dc-user-check:focus-within" in DC                        # 單據類型晶片要有鍵盤焦點框
    assert ".dc-doc-type .dc-user-check { min-height: 44px !important; }" in DC
    m = re.search(r"async _openFromUrl\(\) \{.*?\n    \},\n", DC, re.S)
    assert m and "await this.loadCases()" in m.group(0)               # 深連結清篩選後要重抓清單


def test_linked_case_points_to_case_management_with_existing_q_deeplink():
    assert 'data-testid="dc-to-case-mgmt"' in DC
    assert "'case-management.html?q=' + encodeURIComponent(selectedCase.convertedQuoteNo" in DC
    assert "報價單成案後才會出現在案件管理。" in DC
    assert "canOpenCaseMgmt" in DC and "case_manage" in DC


# ══ #17：預估金額／預計成交日（接 h7 的後端；本分支＝feat/t86-devcrm-h10-e17）═══════════════
def test_expected_amount_and_date_fields_are_wired():
    for tid in ("case-expected-amount", "case-expected-date", "detail-expected-amount", "detail-expected-date", "dc-pipeline-amount"):
        assert 'data-testid="%s"' % tid in DC, tid
    assert "/api/dev-cases/expected-summary" in DC
    assert "if (!this.amountFieldVisible) delete body.expectedAmount" in DC     # 沒有金額權限就不送（後端沒帶＝維持原值）


@pytest.mark.e2e
def test_expected_amount_hidden_without_finance_and_saved_with_it(live_server, make_user, new_page, login_as, client):
    sup = make_user(username="e2e_dce_super", role="superadmin")
    cid = _mk_case(client, _token(client, tuple(sup)[:2]), "預估金額案", sales=[])
    page = new_page()
    login_as(page, tuple(sup)[:2])
    page.goto(f"{live_server}/pages/dev-crm.html?case={cid}")
    page.get_by_role("button", name="編輯商機").wait_for(timeout=15000)
    page.get_by_role("button", name="編輯商機").click()
    page.locator('[data-testid="case-expected-amount"]').fill("1500000")
    page.locator('[data-testid="case-expected-date"]').fill("2026-12-31")
    page.locator(".dc-modal-foot .btn-primary").locator("visible=true").first.click()
    page.get_by_text("NT$ 1,500,000").first.wait_for(timeout=8000)
    assert "2026-12-31" in page.locator('[data-testid="detail-expected-date"]').inner_text()
    page.locator('[data-testid="dc-pipeline-amount"]').wait_for(state="visible", timeout=8000)
    # 業務沒有金額可見權限：詳情顯示「—」、表單沒有金額輸入框、不顯示漏斗金額
    sales = make_user(username="e2e_dce_sales", role="sales", modules=["dev_crm"])
    stok = _token(client, tuple(sales)[:2])
    sid = _mk_case(client, stok, "業務看不到金額", sales=[])
    p2 = new_page()
    login_as(p2, tuple(sales)[:2])
    p2.goto(f"{live_server}/pages/dev-crm.html?case={sid}")
    p2.get_by_role("button", name="編輯商機").wait_for(timeout=15000)
    assert p2.locator('[data-testid="detail-expected-amount"] .dc-info-val').inner_text().strip() == "—"
    p2.get_by_role("button", name="編輯商機").click()
    p2.locator(".dc-modal-foot .btn-primary").locator("visible=true").first.wait_for(state="visible", timeout=8000)   # 編輯視窗已開（先等它，再斷言「沒有金額欄」，否則是假綠燈）
    assert p2.locator('[data-testid="case-expected-amount"]').locator("visible=true").count() == 0
    assert p2.locator('[data-testid="dc-pipeline-amount"]').locator("visible=true").count() == 0


def test_pipeline_amount_card_does_not_show_zero_as_a_real_total():
    """全部洽談中都沒填金額（或沒有洽談中）時，漏斗金額顯示「—」，不顯示像真實合計的「NT$ 0」。"""
    src = source_tree.page_file("dev-crm.html").read_text(encoding="utf-8")
    assert "pipelineCount === 0 || pipelineMissing >= pipelineCount ? '—'" in src
    assert "尚無洽談中商機" in src
    assert "尚未填寫" in src and "件已填，" in src
