"""瀏覽器端對端：LINE 通知事件矩陣頁（pages/line-events.html，共用元件 settings-matrix.js；2026-11-13，LINE 事件矩陣票）。

驗：點選只算草稿（頂端儲存列、未儲存標示、放棄、儲存才寫入）、新開事件預設只發給我、勾選＋批次動作（草稿）、
儲存前確認視窗（預估每月則數）與「重要」告警的第二段警告、復原這一批、儲存時偵測別人改過、
有草稿時點站內連結的離開警告、共用元件的「不能批次」與群組快捷鈕開關、搜尋與篩選、手機寬度卡片且不橫向捲動、舊通知設定頁有連結過來。
對外呼叫一律換掉 `line_notify._http`，不連 LINE。
"""
import re

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect  # noqa: E402


@pytest.fixture()
def fake(monkeypatch):
    from helpers import line_notify, line_quota

    def _http(method, path, token, payload=None):
        if path.endswith("/quota/consumption"):
            return 200, {"totalUsage": 10}
        if path.endswith("/quota"):
            return 200, {"type": "limited", "value": 200}
        return 200, {}
    monkeypatch.setattr(line_notify, "_http", _http)
    line_quota._mem.update(checked_at=None, failed_at=None, error="", fp=None)


def _configure():
    from helpers.settings import _set_setting
    _set_setting("line_notify", {"enabled": True, "channel_access_token": "tok-e2e-mx-0123456789", "public_base_url": "https://line.example.com",
                                 "login_channel_id": "1234567890", "login_channel_secret": "0123456789abcdef0123456789abcdef"})


def _open(live_server, make_user, new_page, login_as, name, width=1440):
    u = make_user(username=name, role="superadmin")
    page = new_page(viewport={"width": width, "height": 1800})
    login_as(page, u)
    page.goto(f"{live_server}/pages/line-events.html")
    page.locator("[data-testid='mx-row-approval_request']" if width > 900 else ".mx-card-row").first.wait_for(state="attached", timeout=20000)
    return page


def _row(page, key):
    return page.locator("[data-testid='mx-row-%s']" % key)


def _sw(page, key):
    return _row(page, key).locator(".mx-sw")


def _dlg_btn(page, text):
    return page.locator(".mx-dlg button").filter(has_text=text).first


def _save(page):
    """按儲存列的「儲存」＋確認視窗的「儲存」（遇到「重要」告警的第二段警告由呼叫端另外處理）。"""
    page.locator("[data-testid=mx-draft-save]").click()
    _dlg_btn(page, "儲存").wait_for(state="visible", timeout=10000)
    _dlg_btn(page, "儲存").click()
    expect(page.locator("[data-testid=mx-draftbar]")).to_have_count(0)          # 存完草稿清空（吐司文字可能是上一次的，不能拿來當同步點）


@pytest.mark.e2e
def test_click_is_only_a_draft_until_saved_and_new_on_defaults_to_only_me(live_server, make_user, new_page, login_as, fake):
    _configure()
    from helpers import line_notify as L
    page = _open(live_server, make_user, new_page, login_as, "e2e_mx1")
    key = "approval_request"
    expect(page.locator("[data-testid=mx-draftbar]")).to_have_count(0)
    _sw(page, key).click()
    expect(_sw(page, key)).to_have_attribute("aria-checked", "true")
    expect(page.locator("[data-testid=mx-draft-count]")).to_contain_text("1 項未儲存的修改")
    expect(_row(page, key)).to_have_class(re.compile(r"mx-draft"))
    expect(_row(page, key)).to_contain_text("未儲存")
    assert not L.event_enabled(key), "草稿階段不寫入"
    _save(page)
    expect(page.locator("[data-testid=mx-toast-text]")).to_contain_text("已儲存")
    expect(page.locator("[data-testid=mx-draftbar]")).to_have_count(0)
    assert L.event_enabled(key)
    assert L.audience_view()[key] == {"mode": "only", "roles": [], "users": ["e2e_mx1"]}, "新開的事件預設只發給操作者本人"
    expect(_row(page, key).locator("[data-testid='le-who-%s']" % key)).to_contain_text("e2e_mx1")
    page.locator("[data-testid=mx-undo]").click()                              # 儲存之後才有「復原這一批」
    expect(_sw(page, key)).to_have_attribute("aria-checked", "false")
    assert not L.event_enabled(key)


@pytest.mark.e2e
def test_draft_can_be_discarded_and_toggling_back_removes_it(live_server, make_user, new_page, login_as, fake):
    _configure()
    from helpers import line_notify as L
    page = _open(live_server, make_user, new_page, login_as, "e2e_mx2")
    key = "approval_request"
    _sw(page, key).click()
    expect(page.locator("[data-testid=mx-draftbar]")).to_be_visible()
    page.locator("[data-testid=mx-draft-discard]").click()
    expect(page.locator("[data-testid=mx-draftbar]")).to_have_count(0)
    expect(_sw(page, key)).to_have_attribute("aria-checked", "false")
    _sw(page, key).click()
    expect(page.locator("[data-testid=mx-draft-count]")).to_contain_text("1 項")
    _sw(page, key).click()                                                    # 切回原狀 ⇒ 自動移出草稿
    expect(page.locator("[data-testid=mx-draftbar]")).to_have_count(0)
    assert not L.event_enabled(key)


@pytest.mark.e2e
def test_batch_actions_stage_drafts_then_one_save_with_preview(live_server, make_user, new_page, login_as, fake):
    _configure()
    from helpers import line_notify as L
    page = _open(live_server, make_user, new_page, login_as, "e2e_mx3")
    keys = ["approval_request", "dev_case_unassigned"]
    page.locator("[data-testid=mx-batch]").wait_for(state="hidden", timeout=5000)
    for k in keys:
        _row(page, k).locator("input[data-mx=sel]").check()
    expect(page.locator("[data-testid=mx-batch-count]")).to_have_text("已選 2 項")
    page.locator("[data-testid=mx-batch-on]").click()
    expect(page.locator("[data-testid=mx-toast-text]")).to_contain_text("已加入草稿 2 項")
    expect(page.locator("[data-testid=mx-draft-count]")).to_contain_text("2 項未儲存的修改")
    assert not any(L.event_enabled(k) for k in keys), "批次動作也只是草稿"
    page.locator("[data-testid=mx-draft-save]").click()
    _dlg_btn(page, "儲存").wait_for(state="visible", timeout=10000)
    expect(page.locator(".mx-dlg-body")).to_contain_text("預估每月")          # 確認視窗：每月則數預估＋可能收件人數
    expect(page.locator(".mx-dlg-body")).to_contain_text("可能收件人")
    _dlg_btn(page, "取消").click()
    expect(page.locator(".mx-dlg")).to_have_count(0)
    assert not any(L.event_enabled(k) for k in keys), "取消 ⇒ 不動，草稿還在"
    expect(page.locator("[data-testid=mx-draftbar]")).to_be_visible()
    _save(page)
    expect(page.locator("[data-testid=mx-toast-text]")).to_contain_text("已儲存")
    assert all(L.event_enabled(k) for k in keys)
    assert all(L.audience_view()[k]["users"] == ["e2e_mx3"] for k in keys)
    page.locator(".mx-toolbar [data-f=on]").first.click()                      # 篩選「已開啟」只剩這兩列；搜尋
    expect(page.locator(".mx-table tbody tr.mx-row")).to_have_count(2)
    page.locator(".mx-toolbar [data-f=all]").first.click()
    page.locator("[data-mx=search]").fill("dev_case_unassigned")
    expect(page.locator(".mx-table tbody tr.mx-row")).to_have_count(1)


@pytest.mark.e2e
def test_critical_off_needs_second_warning_and_group_quick_action_is_draft(live_server, make_user, new_page, login_as, fake):
    _configure()
    from helpers import line_notify as L
    L.set_event("backup_error", True)
    L.set_event("approval_request", True)
    page = _open(live_server, make_user, new_page, login_as, "e2e_mx4")
    for k in ("backup_error", "approval_request"):
        _row(page, k).locator("input[data-mx=sel]").check()
    page.locator("[data-testid=mx-batch-off]").click()
    expect(page.locator("[data-testid=mx-draft-count]")).to_contain_text("2 項未儲存的修改")
    page.locator("[data-testid=mx-draft-save]").click()
    _dlg_btn(page, "儲存").click()                                              # 第一段：預覽
    expect(page.locator(".mx-dlg h3")).to_contain_text("重要")                  # 第二段：重要告警警告
    expect(page.locator(".mx-dlg .mx-danger-box")).to_be_visible()
    _dlg_btn(page, "取消").click()
    expect(page.locator(".mx-dlg")).to_have_count(0)
    assert L.event_enabled("backup_error") and L.event_enabled("approval_request"), "第二段取消 ⇒ 都不動"
    expect(page.locator("[data-testid=mx-draftbar]")).to_be_visible()           # 草稿保留
    page.locator("[data-testid=mx-draft-save]").click()
    _dlg_btn(page, "儲存").click()
    _dlg_btn(page, "仍要關閉").click()
    expect(page.locator("[data-testid=mx-toast-text]")).to_contain_text("已儲存")
    assert not L.event_enabled("backup_error") and not L.event_enabled("approval_request")
    page.locator("[data-testid=mx-undo]").click()
    expect(_sw(page, "backup_error")).to_have_attribute("aria-checked", "true")
    expect(page.locator("[data-testid=mx-toast-text]")).to_contain_text("已復原這一批")
    assert L.event_enabled("backup_error") and L.event_enabled("approval_request")
    page.locator(".mx-table .mx-grp [data-act=off]").first.click()              # 群組「全關」：只進草稿，要儲存才寫入
    expect(page.locator("[data-testid=mx-draftbar]")).to_be_visible()
    assert L.event_enabled("approval_request")


@pytest.mark.e2e
def test_mode_picker_stages_and_save_writes(live_server, make_user, new_page, login_as, fake):
    _configure()
    from helpers import line_notify as L
    key = "approval_request"
    L.set_event(key, True)
    L.set_audience(key, "business", [], [])
    page = _open(live_server, make_user, new_page, login_as, "e2e_mx5")
    _row(page, key).locator("select[data-col=mode]").select_option("only")
    page.locator("[data-testid=le-pick-mode-only]").wait_for(state="visible", timeout=5000)
    page.locator(".le-roles input[data-role=finance]").check()
    _dlg_btn(page, "套用").click()
    expect(_row(page, key).locator("select[data-col=mode]")).to_have_value("only")
    expect(page.locator("[data-testid=mx-draft-count]")).to_contain_text("1 項")
    assert L.audience_view()[key]["mode"] == "business", "草稿階段不寫入"
    _save(page)
    expect(page.locator("[data-testid=mx-toast-text]")).to_contain_text("已儲存")
    assert L.audience_view()[key] == {"mode": "only", "roles": ["finance"], "users": []}
    _row(page, key).locator("select[data-col=mode]").select_option("business")   # 改回「照原本」：也是草稿，存下去才清掉指定
    expect(page.locator("[data-testid=mx-draft-count]")).to_contain_text("1 項")
    _save(page)
    expect(page.locator("[data-testid=mx-toast-text]")).to_contain_text("已儲存")
    assert L.audience_view()[key]["mode"] == "business"


@pytest.mark.e2e
def test_save_refused_when_someone_else_changed_the_event_after_page_load(live_server, make_user, new_page, login_as, fake):
    _configure()
    from helpers import line_notify as L
    page = _open(live_server, make_user, new_page, login_as, "e2e_mx6")
    key = "approval_request"
    _sw(page, key).click()
    expect(page.locator("[data-testid=mx-draftbar]")).to_be_visible()
    L.set_audience(key, "only", ["admin"], [])                                  # 載入之後，別的視窗改了它的收件對象（版本變了）
    page.locator("[data-testid=mx-draft-save]").click()
    _dlg_btn(page, "儲存").click()
    expect(page.locator(".mx-toast-error")).to_contain_text("無法儲存")
    expect(page.locator("[data-testid=mx-draftbar]")).to_be_visible()           # 草稿保留，沒有蓋掉別人的修改
    assert L.audience_view()[key] == {"mode": "only", "roles": ["admin"], "users": []} and not L.event_enabled(key)


@pytest.mark.e2e
def test_leaving_with_unsaved_draft_asks_first(live_server, make_user, new_page, login_as, fake):
    _configure()
    page = _open(live_server, make_user, new_page, login_as, "e2e_mx7")
    _sw(page, "approval_request").click()
    expect(page.locator("[data-testid=mx-draftbar]")).to_be_visible()
    page.locator("[data-testid=le-back-link]").click()
    _dlg_btn(page, "留在這一頁").wait_for(state="visible", timeout=5000)
    _dlg_btn(page, "留在這一頁").click()
    expect(page.locator("[data-testid=mx-draftbar]")).to_be_visible()
    page.locator("[data-testid=le-back-link]").click()
    with page.expect_navigation():
        _dlg_btn(page, "放棄修改並離開").click()
    assert page.url.endswith("notification-settings.html")


@pytest.mark.e2e
def test_shared_core_ineligible_rows_group_switch_and_registered_override(live_server, make_user, new_page, login_as, fake):
    _configure()
    page = _open(live_server, make_user, new_page, login_as, "e2e_mx8")
    reg = page.evaluate("() => SettingsMatrix.eligibleOverrides().map(o => o.id)")
    assert reg == ["line-events"], "目前登記的 eligible 覆寫只有 LINE 事件頁的「重要」告警"
    err = page.evaluate("() => { try { SettingsMatrix.mount(document.createElement('div'), { rows: [], eligible: 'not-registered' }); return '' } catch (e) { return e.message } }")
    assert "沒有登記" in err, "沒登記的覆寫直接丟錯"
    page.evaluate("""() => {
      const box = document.createElement('div'); box.id = 'mx-probe'; document.body.appendChild(box)
      SettingsMatrix.mount(box, {
        rows: [{ key: 'a', name: 'A', group: 'G', risk: 'none' }, { key: 'b', name: 'B', group: 'G', risk: 'money' }, { key: 'c', name: 'C', group: 'G', requires_pending: true }],
        rowKey: r => r.key, rowName: r => r.name, rowGroup: r => r.group,
        columns: [{ id: 'v', type: 'html', label: 'v', render: () => 'x' }],
        batch: { actions: [{ id: 'x', label: 'X', run: () => ({}) }], groupActions: [{ action: 'x', label: '全部開啟' }], groupActionsEnabled: false },
      })
    }""")
    probe = page.locator("#mx-probe")
    t = probe.locator(".mx-table")
    expect(t.locator("input[data-mx=sel][data-key=a]")).to_be_enabled()
    expect(t.locator("input[data-mx=sel][data-key=b]")).to_be_disabled()
    expect(t.locator("input[data-mx=sel][data-key=c]")).to_be_disabled()
    expect(t.locator("input[data-mx=sel][data-key=b]")).to_have_attribute("title", re.compile("不能批次"))
    expect(probe.locator("[data-mx=gact]")).to_have_count(0)                    # 群組快捷鈕總開關關掉
    t.locator("input[data-mx=selall]").check()
    expect(probe.locator("[data-testid=mx-batch-count]")).to_have_text("已選 1 項")   # 全選略過不能批次的列


@pytest.mark.e2e
def test_header_shows_accumulated_days_and_old_page_links_here(live_server, make_user, new_page, login_as, fake):
    _configure()
    page = _open(live_server, make_user, new_page, login_as, "e2e_mx9")
    expect(page.locator("[data-testid=le-total30]")).to_be_visible()
    expect(page.locator("[data-testid=le-accum]")).to_contain_text("已累積")
    page.goto(f"{live_server}/pages/notification-settings.html")
    link = page.locator("[data-testid=line-open-matrix]")
    link.wait_for(state="visible", timeout=20000)
    with page.expect_navigation():
        link.click()
    expect(page.locator("[data-testid=le-matrix]")).to_be_visible()


@pytest.mark.e2e
def test_phone_width_uses_cards_and_has_no_horizontal_scroll(live_server, make_user, new_page, login_as, fake):
    _configure()
    page = _open(live_server, make_user, new_page, login_as, "e2e_mx10", width=390)
    expect(page.locator(".mx-wrap")).to_be_hidden()
    expect(page.locator(".mx-card-row").first).to_be_visible()
    over = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert over <= 1, "手機寬度頁面不可橫向捲動（超出 %s px）" % over


# ── 共用元件補強（hichan-9 審查的 8 項）：在 LINE 頁上另掛一個探針矩陣來驗 ────────────────────────────────────────────

_PROBE = """(opts) => {
  window.__log = []
  const box = document.createElement('div'); box.id = 'mx-probe'; document.body.appendChild(box)
  const rows = [
    { key: 'a', name: 'A<b>x</b>', group: 'G', n: 1, t: 'hi', on: false, mode: 'x', lockSw: false, ro: false },
    { key: 'b', name: 'B', group: 'G', n: 2, t: 'yo', on: true, mode: 'x', lockSw: true, ro: true, selectable: false, selectableReason: '管理列' },
  ]
  window.__rows = rows
  const mx = SettingsMatrix.mount(box, Object.assign({
    rows, rowKey: r => r.key, rowName: r => r.name, rowGroup: r => r.group,
    columns: [
      { id: 'on', type: 'switch', label: '開', get: r => r.on, disabled: r => r.lockSw ? '這列鎖住' : false,
        set: (r, v) => { window.__log.push(['on', r.key, v]); return window.__gate ? new Promise(res => { window.__gate = res }).then(() => { r.on = v }) : (r.on = v, {}) } },
      { id: 'n', type: 'number', label: '數量', min: 0, max: 9, get: r => r.n, readonly: r => r.ro, validate: (v) => v > 5 ? '太大' : null,
        set: (r, v) => { window.__log.push(['n', r.key, v]); r.n = v; return {} } },
      { id: 't', type: 'text', label: '備註', maxlength: 5, get: r => r.t, set: (r, v) => { window.__log.push(['t', r.key, v]); r.t = v; return {} } },
      { id: 'mode', type: 'select', label: '模式', options: [{ value: 'x', label: 'X' }, { value: 'y', label: 'Y' }], get: r => r.mode, disabled: r => r.lockSw,
        set: (r, v) => { window.__log.push(['mode', r.key, v]); r.mode = v; return {} } },
      { id: 'h', type: 'html', label: '不信任', render: r => '<i data-testid="h-' + r.key + '">' + r.name + '</i>' },
      { id: 'raw', type: 'html', raw: true, label: '信任', render: r => '<u data-testid="raw-' + r.key + '">ok</u>' },
    ],
    reload: () => Promise.resolve(rows.map(r => Object.assign({}, r))),
  }, opts || {}))
  window.__mx = mx
}"""


@pytest.mark.e2e
def test_core_number_text_columns_per_cell_lock_selectable_and_html_escaping(live_server, make_user, new_page, login_as, fake):
    _configure()
    page = _open(live_server, make_user, new_page, login_as, "e2e_mx11")
    page.evaluate(_PROBE)
    t = page.locator("#mx-probe .mx-table")
    # html 預設跳脫；raw 欄位照放；列名稱一律跳脫
    expect(t.locator("[data-testid=h-a]")).to_have_count(0)
    expect(t).to_contain_text("<i data-testid=")
    expect(t.locator("[data-testid=raw-a]")).to_have_count(1)
    assert page.evaluate("() => document.querySelector('#mx-probe .mx-nm').innerHTML").startswith("A&lt;b&gt;x")
    # 每格 disabled／readonly、列 selectable:false
    expect(t.locator("button[data-mx=switch][data-key=b]")).to_be_disabled()
    expect(t.locator("button[data-mx=switch][data-key=b]")).to_have_attribute("title", "這列鎖住")
    expect(t.locator("select[data-mx=select][data-key=b]")).to_be_disabled()
    expect(t.locator("input[data-mx=input][data-col=n][data-key=b]")).to_have_attribute("readonly", "")
    expect(t.locator("input[data-mx=sel][data-key=b]")).to_be_disabled()
    expect(t.locator("input[data-mx=sel][data-key=b]")).to_have_attribute("title", re.compile("管理列"))
    t.locator("input[data-mx=selall]").check()
    expect(page.locator("#mx-probe [data-testid=mx-batch-count]")).to_have_text("已選 1 項")
    # number：改值＝change 才寫入；超出驗證 ⇒ 不寫、顯示原因
    n = t.locator("input[data-mx=input][data-col=n][data-key=a]")
    n.fill("4")
    n.press("Enter")
    expect(page.locator("[data-testid=mx-toast-text]")).to_have_text(re.compile("已更新"))
    assert page.evaluate("() => window.__log.filter(x => x[0]==='n')") == [["n", "a", 4]]
    n = t.locator("input[data-mx=input][data-col=n][data-key=a]")
    n.fill("8")
    n.press("Enter")
    expect(page.locator("[data-testid=mx-toast-text]")).to_have_text("太大")
    assert page.evaluate("() => window.__log.filter(x => x[0]==='n').length") == 1, "驗證失敗不寫入"
    # text
    tx = t.locator("input[data-mx=input][data-col=t][data-key=a]")
    tx.fill("abc")
    tx.press("Enter")
    expect(page.locator("[data-testid=mx-toast-text]")).to_have_text(re.compile("已更新"))
    assert page.evaluate("() => window.__log.filter(x => x[0]==='t')") == [["t", "a", "abc"]]


@pytest.mark.e2e
def test_core_focus_survives_rerender_and_cfg_labels_replace_strings(live_server, make_user, new_page, login_as, fake):
    _configure()
    page = _open(live_server, make_user, new_page, login_as, "e2e_mx12")
    page.evaluate(_PROBE, {"labels": {"expand": "Expand all", "allGroups": "All groups", "empty": "Nothing", "selected": "{n} selected", "undo": "Undo", "all": "All"}})
    box = page.locator("#mx-probe")
    expect(box.locator("[data-mx=expand]")).to_have_text("Expand all")
    expect(box.locator("[data-mx=gsel-filter] option").first).to_have_text("All groups")
    expect(box.locator("[data-mx=filter]").first).to_have_text("All")
    t = box.locator(".mx-table")
    t.locator("input[data-mx=sel][data-key=a]").check()
    expect(box.locator("[data-testid=mx-batch-count]")).to_have_text("1 selected")
    # 焦點：在搜尋框打字（每個字都會重繪）→ 焦點還在；沒結果時顯示換掉的文案
    s = box.locator("[data-mx=search]")
    s.click()
    s.type("zz")
    assert page.evaluate("() => document.activeElement && document.activeElement.getAttribute('data-mx')") == "search"
    expect(box.locator(".mx-empty").first).to_have_text("Nothing")
    s.fill("")
    sel = t.locator("input[data-mx=sel][data-key=a]")
    sel.focus()
    sel.press("Space")
    assert page.evaluate("() => { const a = document.activeElement; return [a.getAttribute('data-mx'), a.getAttribute('data-key')] }") == ["sel", "a"]
    # 開關重繪後焦點仍在該開關上
    sw = t.locator("button[data-mx=switch][data-key=a]")
    sw.focus()
    sw.press("Enter")
    expect(page.locator("[data-testid=mx-toast-text]")).to_have_text(re.compile("已開啟"))
    assert page.evaluate("() => { const a = document.activeElement; return [a.getAttribute('data-mx'), a.getAttribute('data-col'), a.getAttribute('data-key')] }") == ["switch", "on", "a"]


@pytest.mark.e2e
def test_core_edits_made_while_busy_are_queued_not_dropped_and_destroy_cleans_up(live_server, make_user, new_page, login_as, fake):
    _configure()
    page = _open(live_server, make_user, new_page, login_as, "e2e_mx13")
    page.evaluate("() => { window.__gate = true }")
    page.evaluate(_PROBE)
    t = page.locator("#mx-probe .mx-table")
    t.locator("button[data-mx=switch][data-key=a]").click()                    # 第一筆寫入：卡住（busy）
    assert page.evaluate("() => window.__log.length") == 1
    # busy 期間改別的格子（select、number）：不能被丟掉
    page.evaluate("""() => {
      const t = document.querySelector('#mx-probe .mx-table')
      const sel = t.querySelector('select[data-key=a]'); sel.value = 'y'; sel.dispatchEvent(new Event('change', { bubbles: true }))
      const n = t.querySelector('input[data-col=n][data-key=a]'); n.value = '3'; n.dispatchEvent(new Event('change', { bubbles: true }))
    }""")
    assert page.evaluate("() => window.__log.length") == 1, "還在寫第一筆，後面的在排隊"
    page.evaluate("() => { window.__gate(); window.__gate = false }")           # 放行第一筆
    page.wait_for_function("() => window.__log.length === 3", timeout=10000)
    assert page.evaluate("() => window.__log") == [["on", "a", True], ["mode", "a", "y"], ["n", "a", 3]], "依序套用、值照點下去當下的決定"
    # destroy：容器清空、移除 window／document 監聽；之後 api 是空操作、不丟錯
    removed = page.evaluate("""() => {
      let removed = 0
      const rw = window.removeEventListener, rd = document.removeEventListener
      window.removeEventListener = function (...a) { removed++; return rw.apply(this, a) }
      document.removeEventListener = function (...a) { removed++; return rd.apply(this, a) }
      window.__mx.destroy()
      window.removeEventListener = rw; document.removeEventListener = rd
      window.__mx.save(); window.__mx.refresh(); window.__mx.destroy()
      return removed
    }""")
    assert page.evaluate("() => document.getElementById('mx-probe').innerHTML") == ""
    assert page.evaluate("() => document.getElementById('mx-probe').className") == ""
    assert removed == 2, "destroy 一律對 window／document 各拆一次（沒掛過也無害）；容器上的監聽隨 destroy 拆掉"


@pytest.mark.e2e
def test_core_draft_mode_destroy_removes_window_and_document_listeners(live_server, make_user, new_page, login_as, fake):
    _configure()
    page = _open(live_server, make_user, new_page, login_as, "e2e_mx15")
    removed = page.evaluate("""() => {
      const box = document.createElement('div'); document.body.appendChild(box)
      const rows = [{ key: 'a', name: 'A', group: 'G', on: false }]
      const mx = SettingsMatrix.mount(box, { rows, rowKey: r => r.key, rowName: r => r.name, rowGroup: r => r.group,
        columns: [{ id: 'on', type: 'switch', label: '開', get: r => r.on, draft: (r, v) => ({ on: v }) }], draft: { save: () => Promise.resolve({}) } })
      const names = []
      const rw = window.removeEventListener, rd = document.removeEventListener
      window.removeEventListener = function (...a) { names.push('w:' + a[0]); return rw.apply(this, a) }
      document.removeEventListener = function (...a) { names.push('d:' + a[0]); return rd.apply(this, a) }
      mx.destroy()
      window.removeEventListener = rw; document.removeEventListener = rd
      return names
    }""")
    assert sorted(removed) == ["d:click", "w:beforeunload"]


@pytest.mark.e2e
def test_core_draft_edits_during_save_are_kept_and_snapshot_must_be_an_object(live_server, make_user, new_page, login_as, fake):
    _configure()
    page = _open(live_server, make_user, new_page, login_as, "e2e_mx14")
    page.evaluate("""() => {
      const box = document.createElement('div'); box.id = 'mx-probe'; document.body.appendChild(box)
      const rows = [{ key: 'a', name: 'A', group: 'G', on: false }, { key: 'b', name: 'B', group: 'G', on: false }]
      window.__rows = rows
      let release = null
      window.__release = () => release && release()
      window.__mx = SettingsMatrix.mount(box, {
        rows, rowKey: r => r.key, rowName: r => r.name, rowGroup: r => r.group,
        columns: [{ id: 'on', type: 'switch', label: '開', get: r => r.on, draft: (r, v) => ({ on: v }) }],
        draft: { save: (changes) => new Promise(res => { release = () => { changes.forEach(c => { rows.find(r => r.key === c.key).on = c.patch.on }); res({}) } }) },
        batch: { actions: [], snapshot: () => 'not-an-object', restore: () => Promise.resolve() },
        reload: () => Promise.resolve(rows.map(r => Object.assign({}, r))),
      })
    }""")
    t = page.locator("#mx-probe .mx-table")
    t.locator("button[data-mx=switch][data-key=a]").click()
    page.locator("#mx-probe [data-testid=mx-draft-save]").click()                # 儲存中（卡住）
    t.locator("button[data-mx=switch][data-key=b]").dispatch_event("click")      # 儲存中又改了 b（忙碌時表格 pointer-events:none，用鍵盤等同的事件）：不能被「儲存後清空草稿」吃掉
    page.evaluate("() => window.__release()")
    expect(page.locator("#mx-probe [data-testid=mx-draft-count]")).to_contain_text("1 項未儲存")
    expect(t.locator("button[data-mx=switch][data-key=b]")).to_have_attribute("aria-checked", "true")
    assert page.evaluate("() => window.__rows.map(r => r.on)") == [True, False], "a 已儲存、b 還只是草稿"
    expect(page.locator("[data-testid=mx-undo]")).to_have_count(0)               # snapshot 不是物件 ⇒ 沒有復原鈕（並 console 警告）
