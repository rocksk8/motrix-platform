"""瀏覽器端對端：設定中心外框（S2，2026-11-14；SPEC §14）。取代舊的 test_e2e_settings_center_edit_s1／_b9（舊頁的 Alpine 卡片版面已由矩陣表取代）。

- 導覽：總覽三張統計卡、兩層導覽（分類／頁）、分類切換、全域欄位級搜尋 → 跳到那一頁並閃一下那一列
- 草稿：點格子只算草稿；換頁草稿不丟；導覽顯示「未儲存 N」；放棄；儲存要確認（原因必填、紅色橫幅要勾「我已了解」）
- 寫入：收緊立即生效（落地值＋變更明細）；放寬列入待生效，第二位最高管理者在「待生效」核准；別人先改過 ⇒ 整組不儲存並說明
- 其他視圖：最近變更、版本紀錄（?tab=versions&group=）、待生效撤銷、規劃中群組只有灰色說明
- 安全與手機：名稱含 HTML 不會執行；畫面不露出內部鍵名；390px 沒有橫向捲動、導覽抽屜可開
觀測點打在資料庫落地值與元件狀態，不打在頁面寫死的文字上（文字只驗不出現鍵名）。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

ROW = '[data-testid="mx-row-%s.%s"]'


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


def _go(page, live_server, url_tail=""):
    page.goto("about:blank")                                         # 只差網址 # 或 ? 的跳轉是同頁導覽，不會重載
    page.goto(f"{live_server}/pages/settings-center.html{url_tail}")
    page.wait_for_function("() => window.__settingsCenter && window.__settingsCenter.state().view", timeout=20000)      # 資料讀完、第一個畫面選好


def _open(page, live_server, page_id):
    _go(page, live_server)
    btn = page.locator(f'[data-testid="sc-page-{page_id}"]')
    btn.wait_for(state="attached", timeout=20000)
    if not btn.is_visible():                                         # 手機寬度：導覽預設收起
        page.locator('[data-testid="sc-navtoggle"]').click()
        btn.wait_for(state="visible", timeout=10000)
    btn.click()
    page.locator('[data-testid="sc-pagehead"] h2').wait_for(timeout=15000)


def _set_number(page, group, field, value):
    box = page.locator(ROW % (group, field) + ' input[data-mx="input"]').first
    box.wait_for(timeout=15000)
    box.fill(str(value))
    box.press("Tab")


def _save_with_reason(page, reason, ack=False):
    page.locator('[data-testid="mx-draft-save"]').click()
    page.locator('[data-testid="sc-reason"]').wait_for(timeout=15000)
    ok = page.locator('[data-testid="sc-confirm-ok"]')
    page.wait_for_function("() => document.querySelector('[data-testid=\"sc-confirm-ok\"]').disabled", timeout=10000)                      # 還沒填原因
    page.fill('[data-testid="sc-reason"]', reason)
    if ack:
        page.wait_for_function("() => document.querySelector('[data-testid=\"sc-confirm-ok\"]').disabled", timeout=10000)                  # 紅色橫幅：沒勾「我已了解」不可送出
        page.check('[data-testid="sc-ack"]')
    page.wait_for_function("() => !document.querySelector('[data-testid=\"sc-confirm-ok\"]').disabled", timeout=10000)
    ok.click()


def _toast(page):
    t = page.locator('[data-testid="mx-toast-text"]')
    t.wait_for(timeout=20000)
    return t.inner_text()


@pytest.mark.e2e
def test_overview_nav_segments_and_global_search_jump_and_flash(live_server, make_user, e2e_browser):
    sa = make_user(username="s2_e2e_a", role="superadmin")
    page = e2e_browser.new_page(viewport={"width": 1280, "height": 900})
    inject_login(page, live_server, *sa)
    _go(page, live_server)
    for k in ("differs", "pending", "high"):
        page.locator(f'[data-testid="sc-card-{k}"]').wait_for(timeout=15000)
    page.locator('[data-testid="sc-page-uploads"]').wait_for(timeout=10000)
    # 分類切換：只看「安全」時，別的分類的頁不在導覽
    page.click('[data-testid="sc-seg-安全"]')
    page.wait_for_function("() => !document.querySelector('[data-testid=\"sc-nav\"] [data-page=\"uploads\"]')", timeout=10000)
    page.click('[data-testid="sc-seg-全部"]')
    page.locator('[data-testid="sc-page-uploads"]').wait_for(timeout=10000)
    # 全域搜尋（欄位問句，群組名稱裡沒有的字）→ 跳到那一頁、那一列閃一下
    page.fill('[data-testid="sc-search"]', "最大可以多大")
    hit = page.locator('[data-testid="sc-hit"]').first
    hit.wait_for(timeout=10000)
    hit.click()
    row = page.locator(ROW % ("uploads", "max_file_mb"))
    row.wait_for(timeout=15000)
    page.wait_for_function("() => document.querySelector('[data-testid=\"mx-row-uploads.max_file_mb\"]').classList.contains('sc-flash')", timeout=5000)
    page.fill('[data-testid="sc-search"]', "完全不存在的字串zzz")
    page.locator('[data-testid="sc-nohit"]').wait_for(timeout=10000)
    # 舊網址 #群組代碼 仍可直接開那一頁
    _go(page, live_server, "#retention")
    page.locator(ROW % ("retention", "audit_log_keep_days")).wait_for(timeout=15000)
    text = page.inner_text("main")
    for key in ("max_file_mb", "audit_log_keep_days", "confirm_period_days", "show_denied", "pending_approval", "immediate"):
        assert key not in text


@pytest.mark.e2e
def test_tightening_is_a_draft_until_confirmed_then_saves_immediately(live_server, make_user, e2e_browser):
    sa = make_user(username="s2_e2e_b", role="superadmin")
    page = e2e_browser.new_page(viewport={"width": 1280, "height": 900})
    inject_login(page, live_server, *sa)
    _open(page, live_server, "uploads")
    _set_number(page, "uploads", "max_file_mb", 10)                    # 20 → 10：收緊
    page.locator('[data-testid="mx-draftbar"]').wait_for(timeout=10000)
    assert not _q("SELECT 1 FROM ui_definitions WHERE kind='setting_group' AND key='uploads'")          # 只是草稿，沒寫入
    page.locator(f'[data-testid="sc-navdraft-uploads"]').wait_for(timeout=10000)
    _save_with_reason(page, "測試收緊")
    assert "已立即生效" in _toast(page)
    rows = _q("SELECT body_json FROM ui_definitions WHERE kind='setting_group' AND key='uploads' AND status='published' ORDER BY version DESC")
    assert json.loads(rows[0]["body_json"])["values"]["max_file_mb"] == 10
    ch = _q("SELECT field, reason FROM config_changes WHERE domain='setting:uploads'")
    assert [(c["field"], c["reason"]) for c in ch] == [("max_file_mb", "測試收緊")]
    page.locator('[data-testid="sc-navdiff-uploads"]').wait_for(timeout=10000)                       # 導覽：與預設不同 1
    page.locator('[data-testid="mx-draftbar"]').wait_for(state="detached", timeout=10000)


@pytest.mark.e2e
def test_loosening_needs_ack_then_second_superadmin_approves_in_pending_view(live_server, make_user, e2e_browser):
    a = make_user(username="s2_e2e_c", role="superadmin")
    b = make_user(username="s2_e2e_d", role="superadmin")
    page = e2e_browser.new_page(viewport={"width": 1280, "height": 900})
    inject_login(page, live_server, *a)
    _open(page, live_server, "retention")
    _set_number(page, "retention", "audit_log_keep_days", 400)       # 縮短保存期限＝放寬
    _save_with_reason(page, "測試放寬", ack=True)
    t = _toast(page)
    assert "待生效" in t and "日生效" in t                                  # 白話結果帶預計生效日（M 月 D 日）
    pend = _q("SELECT id, approvals_required FROM config_changes WHERE domain='setting:retention' AND field='audit_log_keep_days'")
    assert len(pend) == 1 and pend[0]["approvals_required"] == 1
    assert not _q("SELECT 1 FROM ui_definitions WHERE kind='setting_group' AND key='retention'")            # 放寬沒有直接生效
    page2 = e2e_browser.new_page(viewport={"width": 1280, "height": 900})
    inject_login(page2, live_server, *b)
    _go(page2, live_server)
    page2.locator('[data-testid="sc-go-pending"]').click()
    btn = page2.locator('[data-testid="sc-approve-%d"]' % pend[0]["id"])
    btn.wait_for(timeout=15000)
    btn.click()
    assert "已核准" in _toast(page2)
    ev = _q("SELECT event FROM config_change_events WHERE change_id=? ORDER BY id", (pend[0]["id"],))
    assert [e["event"] for e in ev] == ["pending", "approved"]


@pytest.mark.e2e
def test_draft_survives_page_switch_and_discard_clears_it_and_choice_field_works(live_server, make_user, e2e_browser):
    sa = make_user(username="s2_e2e_e", role="superadmin")
    page = e2e_browser.new_page(viewport={"width": 1280, "height": 900})
    inject_login(page, live_server, *sa)
    _open(page, live_server, "uploads")
    _set_number(page, "uploads", "max_file_mb", 10)
    page.locator('[data-testid="mx-draftbar"]').wait_for(timeout=10000)
    page.click('[data-testid="sc-page-system_hub"]')                  # 換頁：草稿不丟、導覽標出未儲存
    sel = page.locator(ROW % ("system_hub", "show_denied") + ' select').first
    sel.wait_for(timeout=15000)
    sel.select_option(index=1)                                        # 選另一個選項也成為草稿
    page.wait_for_function("() => document.querySelector('[data-testid=\"mx-draft-count\"] b').textContent === '2'", timeout=10000)
    page.locator('[data-testid="sc-navdraft-uploads"]').wait_for(timeout=10000)
    page.click('[data-testid="sc-page-uploads"]')
    page.locator(ROW % ("uploads", "max_file_mb") + ' input[data-mx="input"]').first.wait_for(timeout=10000)
    assert page.locator(ROW % ("uploads", "max_file_mb") + ' input[data-mx="input"]').first.input_value() == "10"
    page.click('[data-testid="mx-draft-discard"]')
    page.locator('[data-testid="mx-draftbar"]').wait_for(state="detached", timeout=10000)
    assert page.locator(ROW % ("uploads", "max_file_mb") + ' input[data-mx="input"]').first.input_value() == "20"


@pytest.mark.e2e
def test_confirm_dialog_lists_who_gets_notified_and_never_claims_no_one_is(live_server, make_user, e2e_browser):
    """h5 M1：有第二位最高管理者時，確認視窗要寫出他會收到通知（不得寫「不會另外通知別人」）；通知對象來自伺服器預覽。"""
    a = make_user(username="s2_e2e_n1", role="superadmin")
    make_user(username="s2_e2e_n2", role="superadmin")
    page = e2e_browser.new_page(viewport={"width": 1280, "height": 900})
    inject_login(page, live_server, *a)
    _open(page, live_server, "uploads")
    _set_number(page, "uploads", "max_file_mb", 9)                    # 調小＝收緊 ⇒ 立即生效，但仍會通知其他最高管理者
    page.locator('[data-testid="mx-draft-save"]').click()
    box = page.locator('[data-testid="sc-recipients"]')
    box.wait_for(timeout=15000)
    txt = box.inner_text()
    assert txt.startswith("儲存後會通知：") and "最高管理者" in txt and "不會另外通知" not in txt
    assert "會留下紀錄，不會另外通知別人" not in page.content()


@pytest.mark.e2e
def test_someone_else_changed_it_first_blocks_the_save_and_says_so(live_server, make_user, e2e_browser):
    from helpers import settings_registry as R
    sa = make_user(username="s2_e2e_f", role="superadmin")
    page = e2e_browser.new_page(viewport={"width": 1280, "height": 900})
    inject_login(page, live_server, *sa)
    _open(page, live_server, "uploads")
    page.locator(ROW % ("uploads", "max_file_mb")).wait_for(timeout=15000)
    R.publish("uploads", {"max_file_mb": 15}, reason="別人先改", user="someone_else")                # 載入之後、儲存之前，別人改了同一項
    _set_number(page, "uploads", "max_file_mb", 10)
    _save_with_reason(page, "我的修改")
    msg = _toast(page)
    assert "改過" in msg and "沒有儲存" in msg
    page.locator('[data-testid="mx-draftbar"]').wait_for(timeout=10000)                                # 失敗：草稿保留，不吞掉使用者的修改
    vals = json.loads(_q("SELECT body_json FROM ui_definitions WHERE kind='setting_group' AND key='uploads' AND status='published' ORDER BY version DESC")[0]["body_json"])["values"]
    assert vals["max_file_mb"] == 15


@pytest.mark.e2e
def test_recent_pending_cancel_versions_deeplink_and_planned_group(live_server, make_user, e2e_browser):
    from core import spine
    from helpers import settings_pages as SP
    from helpers import settings_registry as R
    snap = spine.snapshot()
    R.register_group("zz_e2e_plan", "尚未開放的功能群組", [R.SettingDef("n", "int", 1, min=0, max=9, question="這項要設多少？", label="測試項目", help="測試用的設定項目。", impact="影響測試。")],
                     help="測試用的規劃中群組。", owner="zz_e2e")
    spine.register_manifest({"features": [{"code": "zz_e2e_plan_f", "label": "規劃中的測試功能", "status": "planned", "planned_train": "MS3", "settings": {"group": "zz_e2e_plan"}}]}, "zz_e2e")
    spine.validate_all()
    pages0 = list(SP.PAGES)
    SP.PAGES.append({"id": "zz_e2e_plan", "plain": "規劃中的測試頁", "category": "系統", "groups": ["zz_e2e_plan"], "style": "checkbox"})
    SP.GROUPS["zz_e2e_plan"] = {"plain": "規劃中的測試群組", "currentName": "尚未開放的功能群組", "privacy": False}
    try:
        R.publish("uploads", {"max_file_mb": 12}, reason="先收緊一次", user="s2_e2e_g")
        R.publish("retention", {"audit_log_keep_days": 500}, reason="放寬一次", user="s2_e2e_g")          # 待生效
        sa = make_user(username="s2_e2e_g2", role="superadmin")
        page = e2e_browser.new_page(viewport={"width": 1280, "height": 900})
        inject_login(page, live_server, *sa)
        _go(page, live_server)
        page.click('[data-testid="sc-go-recent"]')
        page.locator('[data-testid="sc-recent-list"]').wait_for(timeout=15000)
        assert "先收緊一次" in page.inner_text('[data-testid="sc-recent-list"]')
        page.check('[data-testid="sc-recent-high"]')
        page.wait_for_function("() => !document.querySelector('[data-testid=\"sc-recent-list\"]').innerText.includes('先收緊一次')", timeout=10000)
        page.click('[data-testid="sc-go-pending"]')                                                      # 待生效：撤銷
        cancel = page.locator('[data-testid^="sc-cancel-"]').first
        cancel.wait_for(timeout=15000)
        cancel.click()
        assert "已撤銷" in _toast(page)
        assert _q("SELECT 1 FROM config_change_events e JOIN config_changes c ON c.id=e.change_id WHERE c.domain='setting:retention' AND e.event='cancelled'")
        _go(page, live_server, "?tab=versions&group=uploads")                                           # 深連結：版本紀錄、已選到那個群組
        page.locator('[data-testid="sc-vgroup"]').wait_for(timeout=15000)
        assert page.locator('[data-testid="sc-vgroup"]').input_value() == "uploads"
        page.locator('[data-testid="sc-versions-list"]').wait_for(timeout=10000)
        # 規劃中群組：只有灰色說明，沒有列
        _go(page, live_server)
        page.click('[data-testid="sc-page-zz_e2e_plan"]')
        page.locator('[data-testid="sc-planned"]').wait_for(timeout=10000)
        assert page.locator('[data-testid="sc-planned"]').inner_text() == "「規劃中的測試群組」開發中，尚未開放。"
        assert page.locator('[data-testid^="mx-row-zz_e2e_plan"]').count() == 0
    finally:
        spine.restore(snap)
        SP.PAGES[:] = pages0
        SP.GROUPS.pop("zz_e2e_plan", None)
        R._GROUPS.pop("zz_e2e_plan", None)
        R.invalidate()


@pytest.mark.e2e
def test_names_with_html_never_execute_and_mobile_has_no_horizontal_scroll(live_server, make_user, e2e_browser):
    from helpers import settings_pages as SP
    from helpers import settings_registry as R
    evil = '<img src=x onerror="window.__xss=1">名稱<script>window.__xss=2</script>'
    R.register_group("zz_e2e_xss", evil, [R.SettingDef("n", "int", 1, min=0, max=9, question="填多少？", label=evil, help="測試用。", impact="影響測試。")], help=evil)
    pages0 = list(SP.PAGES)
    SP.PAGES.append({"id": "zz_e2e_xss", "plain": evil, "category": "系統", "groups": ["zz_e2e_xss"], "style": "checkbox"})
    SP.GROUPS["zz_e2e_xss"] = {"plain": evil, "currentName": evil, "privacy": False}
    try:
        sa = make_user(username="s2_e2e_x", role="superadmin")
        page = e2e_browser.new_page(viewport={"width": 390, "height": 800})
        inject_login(page, live_server, *sa)
        _go(page, live_server)
        page.locator('[data-testid="sc-navtoggle"]').click()
        page.locator('[data-testid="sc-page-zz_e2e_xss"]').click()
        page.locator('[data-testid="sc-pagehead"] h2').wait_for(timeout=15000)
        page.wait_for_timeout(500)
        assert page.evaluate("window.__xss") is None
        assert "<img" in page.inner_text('[data-testid="sc-pagehead"]')                                  # 以純文字顯示
        assert page.evaluate("document.querySelector('main').querySelectorAll('img[src=\"x\"]').length") == 0
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"), "手機寬度不橫向捲動"
        page.locator('[data-testid="sc-navtoggle"]').click()
        page.locator('[data-testid="sc-nav"]').wait_for(state="visible", timeout=10000)                  # 導覽抽屜可開
        page.fill('[data-testid="sc-search"]', "填多少")
        page.locator('[data-testid="sc-hit"]').first.wait_for(timeout=10000)
        assert page.evaluate("window.__xss") is None
    finally:
        SP.PAGES[:] = pages0
        SP.GROUPS.pop("zz_e2e_xss", None)
        R._GROUPS.pop("zz_e2e_xss", None)
        R.invalidate()


@pytest.mark.e2e
def test_builder_page_master_is_a_switch_and_locks_dependent_rows_until_it_is_on(live_server, make_user, e2e_browser):
    """⑨ 自訂功能的開關：總開關是開關（不是數字框）；有真正相依的子項在上一層關著時先鎖住並說明；治理的強制預覽不跟總開關連動。"""
    sa = make_user(username="s2_e2e_builder", role="superadmin")
    page = e2e_browser.new_page(viewport={"width": 1280, "height": 900})
    inject_login(page, live_server, *sa)
    _open(page, live_server, "builder_all")
    master = page.locator(ROW % ("builder_rules", "enabled") + ' [data-mx="switch"]')
    master.wait_for(timeout=15000)
    assert master.get_attribute("aria-checked") == "false"
    assert page.locator(ROW % ("builder_rules", "enabled") + ' input[data-mx="input"]').count() == 0
    seed = page.locator(ROW % ("builder_rules", "k01_seed") + ' select')
    assert seed.is_disabled()
    assert "請先開啟" in (seed.get_attribute("title") or "")
    # 治理的強制預覽：關閉總開關也不解除，所以不鎖
    assert not page.locator(ROW % ("builder_governance", "enforce_layout") + ' select').is_disabled()
    # 暫存把總開關打開 ⇒ 子項解鎖（草稿就算數，不必先儲存）
    master.click()
    page.wait_for_function("() => document.querySelector('[data-testid=\"mx-row-builder_rules.k01_seed\"] select') && !document.querySelector('[data-testid=\"mx-row-builder_rules.k01_seed\"] select').disabled", timeout=10000)
    page.locator('[data-testid="mx-draft-discard"]').click()                 # e2e-lint: ok 放棄草稿後下一行才讀鎖定狀態並有 wait_for_function
    page.wait_for_function("() => document.querySelector('[data-testid=\"mx-row-builder_rules.k01_seed\"] select').disabled", timeout=10000)
