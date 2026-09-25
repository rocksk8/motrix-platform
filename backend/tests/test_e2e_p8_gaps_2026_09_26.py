# -*- coding: utf-8 -*-
"""P8 前端接上 C 的後端缺口 #3～#7（CUSTOMIZATION-SPEC §3.7、INTEGRATION-POINTS IP-10）。

- #3 待我簽核：自訂模組單據出現在 approval-queue.html，點了開 custom-records.html?key=&no=；
     通知中心點 ref_id＝`custom:<模組>:<單號>` 的那一則 ⇒ 開那一張單據。簽核人不必手打 &no=。
- #4 建構器 ⑤ 的積木參數表單依 outputBlockSpecs 產生；主題／欄位格式從目錄取；④ 簽核人來源從 approverSources 取；
     when 旁邊有 fail-safe 說明。
- #5 建構器首頁列出所有模組（含只有草稿的），刪草稿前二次確認。
- #6 參照欄用 ref-options 的下拉＋搜尋；403 才退回手動輸入並說明原因。
- #7 ⑤ 的「PDF 預覽」。

斷言打在伺服器狀態（DB、端點回應），不打在寫死的文字；等待一律等動作的終點狀態，不用 sleep。
"""
import json
import re

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

SAVED = """() => { const e = document.getElementById('mb-save-state');
  return !!e && e.dataset.dirty === '0' && e.dataset.saving === '0' && e.dataset.state === 'saved' }"""


def _db():
    import db
    return db.get_db()


def _q(sql, args=()):
    conn = _db()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def _record(key, no):
    rows = _q("SELECT * FROM custom_records WHERE module_key=? AND record_no=?", (key, no))
    if not rows:
        return None
    d = rows[0]
    d["data"] = json.loads(d.pop("data_json") or "{}")
    d["approval"] = json.loads(d.pop("approval_json") or "{}")
    return d


def _token(client, user):
    r = client.post("/api/auth/login", json={"username": user[0], "password": user[1]})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _h(client, user):
    return {"Authorization": "Bearer " + _token(client, user)}


def _page(new_context, base, user, errors):
    ctx = new_context(accept_downloads=True)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append("%s: %s" % (user[0], e)))
    inject_login(page, base, user[0], user[1])
    return page


def _publish(client, h, key, body):
    assert client.put("/api/definitions/custom_module/%s/draft" % key, json={"body": body}, headers=h).status_code == 200
    r = client.post("/api/definitions/custom_module/%s/publish" % key, json={}, headers=h)
    assert r.status_code == 200, r.text


def _approval_module(key, approver, fields=None):
    return {
        "name": "簽核佇列測試", "permission": "custom.%s" % key, "numbering": {"prefix": "QA", "date": "", "digits": 3},
        "fields": fields or [{"key": "a", "label": "甲", "type": "text", "dataClass": "T1"}],
        "workflow": {"initial": "draft", "states": [
            {"key": "draft", "label": "草稿"},
            {"key": "pending", "label": "簽核中", "approval": {
                "tiers": [{"approvers": [{"username": approver}]}], "on_approved": "done", "on_rejected": "draft"}},
            {"key": "done", "label": "完成", "final": True}],
            "transitions": [{"key": "submit", "label": "送審", "from": "draft", "to": "pending"}]}}


def _submitted_record(client, admin, requester, key, approver):
    """發布一個有一層簽核的模組；申請人建單並送審（API）。回單號。"""
    _publish(client, _h(client, admin), key, _approval_module(key, approver))
    uh = _h(client, requester)
    r = client.post("/api/custom/%s/records" % key, json={"values": {"a": "x"}}, headers=uh)
    assert r.status_code == 200, r.text
    no = r.json()["record_no"]
    r = client.post("/api/custom/%s/records/%s/transitions/submit" % (key, no), json={"note": ""}, headers=uh)
    assert r.status_code == 200, r.text
    assert _record(key, no)["status"] == "pending"
    return no


def _queue_nos(client, user):
    r = client.get("/api/approval-queue", headers=_h(client, user))
    assert r.status_code == 200, r.text
    return [(i.get("type"), i.get("moduleKey"), i.get("quoteNo"))
            for g in r.json().get("queue", []) for i in g.get("items", [])]


# ── #3 待我簽核 ─────────────────────────────────────────────────────────────

@pytest.mark.e2e
@pytest.mark.parametrize("entry", ["card", "button"])
def test_approver_opens_custom_record_from_queue_and_approves_without_typing_no(
        live_server, make_user, new_context, client, entry):
    """簽核人（沒有模組權限）從「待我簽核」點進自訂模組單據並核准；網址由佇列頁產生，不手打 &no=。"""
    key = "queue_entry"
    admin = make_user(username="p8g_q_admin", role="superadmin")
    requester = make_user(username="p8g_q_user", role="viewer", modules=["custom.%s" % key])
    mgr = make_user(username="p8g_q_mgr", role="viewer", modules=[])
    no = _submitted_record(client, admin, requester, key, "p8g_q_mgr")
    assert ("custom_record", key, no) in _queue_nos(client, mgr), "前提：伺服器的佇列要列出這一張"

    errors = []
    page = _page(new_context, live_server, mgr, errors)
    page.goto(live_server + "/pages/approval-queue.html")
    btn = page.locator('[data-open-custom="%s:%s"]' % (key, no))
    btn.wait_for(state="visible")
    if entry == "card":
        page.locator(".aq-card", has=btn).locator(".aq-card__no").click()
    else:
        btn.click()
    page.wait_for_selector('#cr-record[data-record-no="%s"]' % no)
    params = page.evaluate("() => Object.fromEntries(new URLSearchParams(location.search))")
    assert params == {"key": key, "no": no}, params
    page.click("#cr-approve")
    page.wait_for_selector('#cr-record[data-status="done"][data-busy="0"]')
    rec = _record(key, no)
    assert rec["status"] == "done", rec["status"]
    assert _q("SELECT 1 FROM custom_record_log l JOIN custom_records r ON r.id=l.record_id "
              "WHERE r.module_key=? AND r.record_no=? AND l.by_user=? AND l.action LIKE 'approve%%'", (key, no, "p8g_q_mgr"))
    assert ("custom_record", key, no) not in _queue_nos(client, mgr), "簽完要從佇列消失"
    assert not errors, errors


@pytest.mark.e2e
def test_notification_click_opens_the_custom_record(live_server, make_user, new_context, client):
    """通知中心：ref_id＝custom:<模組>:<單號> 的那一則 ⇒ 標已讀並開那一張單據。"""
    key = "notif_entry"
    admin = make_user(username="p8g_n_admin", role="superadmin")
    requester = make_user(username="p8g_n_user", role="viewer", modules=["custom.%s" % key])
    # 鈴鐺只給管理員以上（sidebar.js 既有規則，本次不動）⇒ 簽核人用沒有模組權限的 admin
    mgr = make_user(username="p8g_n_mgr", role="admin", modules=[])
    no = _submitted_record(client, admin, requester, key, "p8g_n_mgr")
    rows = _q("SELECT id, is_read FROM notifications WHERE username=? AND ref_id=?", ("p8g_n_mgr", "custom:%s:%s" % (key, no)))
    assert len(rows) == 1 and not rows[0]["is_read"], rows
    nid = rows[0]["id"]

    errors = []
    page = _page(new_context, live_server, mgr, errors)
    page.goto(live_server + "/pages/approval-queue.html")
    page.click('[x-data="notifStore()"] > button')
    page.click('[data-notif-id="%s"]' % nid)
    page.wait_for_selector('#cr-record[data-record-no="%s"]' % no)
    params = page.evaluate("() => Object.fromEntries(new URLSearchParams(location.search))")
    assert params == {"key": key, "no": no}, params
    assert page.evaluate("() => location.pathname").endswith("/pages/custom-records.html")
    page.wait_for_selector("#cr-approve")          # 簽核人可以直接簽
    page.wait_for_function("""async () => { const s = JSON.parse(localStorage.getItem('motrix_session'));
        const r = await fetch('/api/notifications/mine', { headers: { Authorization: 'Bearer ' + s.token } });
        const d = await r.json(); return d.items.some(i => i.id === %d && i.is_read) }""" % nid)
    assert _q("SELECT is_read FROM notifications WHERE id=?", (nid,))[0]["is_read"] == 1
    assert not errors, errors


# ── #6 參照欄：ref-options 下拉＋搜尋；403 才退回手動輸入 ─────────────────────────

def _ref_module(key):
    return {"name": "參照測試", "permission": "custom.%s" % key, "numbering": {"prefix": "RF", "date": "", "digits": 3},
            "fields": [{"key": "a", "label": "甲", "type": "text", "dataClass": "T1"},
                       {"key": "who", "label": "對象", "type": "ref", "target": "users", "dataClass": "T1"}],
            "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿"}, {"key": "done", "label": "完成", "final": True}],
                         "transitions": [{"key": "go", "label": "完成", "from": "draft", "to": "done"}]}}


def _server_ref_values(client, h, key, q):
    r = client.get("/api/custom/%s/ref-options/who" % key, params={"q": q, "limit": 50}, headers=h)
    assert r.status_code == 200, r.text
    return [str(o["value"]) for o in r.json()]


OPTS = "() => Array.from(document.querySelectorAll('#cr-in-who option')).map(o => o.value).filter(v => v !== '')"


@pytest.mark.e2e
def test_ref_field_lists_ref_options_and_searches(live_server, make_user, new_context, client):
    key = "ref_pick"
    admin = make_user(username="p8g_r_admin", role="superadmin")
    user = make_user(username="p8g_r_user", role="viewer", modules=["custom.%s" % key])
    make_user(username="p8g_r_alice", role="viewer", modules=[])
    make_user(username="p8g_r_bob", role="viewer", modules=[])
    _publish(client, _h(client, admin), key, _ref_module(key))
    uh = _h(client, user)
    all_values = _server_ref_values(client, uh, key, "")
    narrowed = _server_ref_values(client, uh, key, "p8g_r_b")
    assert "p8g_r_alice" in all_values and "p8g_r_bob" in all_values
    assert narrowed == ["p8g_r_bob"], narrowed

    errors = []
    page = _page(new_context, live_server, user, errors)
    page.goto("%s/pages/custom-records.html?key=%s" % (live_server, key))
    page.click("#cr-new")
    page.wait_for_selector('[data-ref-field="who"][data-ref-state="ok"]')
    assert page.evaluate(OPTS) == all_values, "下拉要列出伺服器 ref-options 給的選項"
    with page.expect_response(lambda r: "/ref-options/who" in r.url and "q=p8g_r_b" in r.url) as resp:
        page.fill("#cr-ref-q-who", "p8g_r_b")
    assert resp.value.status == 200
    page.wait_for_function("(want) => JSON.stringify((%s)()) === JSON.stringify(want)" % OPTS, arg=narrowed)
    page.select_option("#cr-in-who", "p8g_r_bob")
    page.fill("#cr-in-a", "x")
    page.click("#cr-save")
    page.wait_for_selector('#cr-record[data-record-no][data-busy="0"]')
    no = page.get_attribute("#cr-record", "data-record-no")
    assert _record(key, no)["data"]["who"] == "p8g_r_bob"
    assert not errors, errors


@pytest.mark.e2e
@pytest.mark.parametrize("status", [403, 500])
def test_ref_field_falls_back_to_manual_input_only_on_403(live_server, make_user, new_context, client, status):
    """403 ⇒ 手動輸入代號＋說明原因，伺服器照樣存；其他失敗（500）⇒ 仍是下拉、標錯誤，不默默改成自由輸入。"""
    key = "ref_denied"
    admin = make_user(username="p8g_rd_admin", role="superadmin")
    user = make_user(username="p8g_rd_user", role="viewer", modules=["custom.%s" % key])
    make_user(username="p8g_rd_bob", role="viewer", modules=[])
    _publish(client, _h(client, admin), key, _ref_module(key))

    errors = []
    page = _page(new_context, live_server, user, errors)
    page.route(re.compile(r".*/api/custom/%s/ref-options/who.*" % key),
               lambda r: r.fulfill(status=status, content_type="application/json", body=json.dumps({"detail": "x"})))
    page.goto("%s/pages/custom-records.html?key=%s" % (live_server, key))
    page.click("#cr-new")
    if status == 403:
        page.wait_for_selector('[data-ref-field="who"][data-ref-state="denied"] [data-ref-why="who"]', state="visible")
        assert page.eval_on_selector("#cr-in-who", "e => e.tagName") == "INPUT"
        page.fill("#cr-in-who", "p8g_rd_bob")
        page.fill("#cr-in-a", "x")
        page.click("#cr-save")
        page.wait_for_selector('#cr-record[data-record-no][data-busy="0"]')
        no = page.get_attribute("#cr-record", "data-record-no")
        assert _record(key, no)["data"]["who"] == "p8g_rd_bob"
    else:
        page.wait_for_selector('[data-ref-field="who"][data-ref-state="error"]')
        assert page.eval_on_selector("#cr-in-who", "e => e.tagName") == "SELECT"
        assert page.locator('[data-ref-why="who"]').count() == 0
    assert not errors, errors



# ── 建構器共用 ─────────────────────────────────────────────────────────────

def _builder_body(key, approver="p8g_b_mgr"):
    return {"name": "建構器缺口測試", "permission": "custom.%s" % key, "numbering": {"prefix": "BG", "date": "", "digits": 3},
            "fields": [{"key": "a", "label": "甲", "type": "text", "dataClass": "T1"},
                       {"key": "n", "label": "數量", "type": "number", "dataClass": "T1"}],
            "workflow": {"initial": "draft", "states": [
                {"key": "draft", "label": "草稿"},
                {"key": "pending", "label": "簽核中", "approval": {
                    "tiers": [{"approvers": [{"username": approver}]}], "on_approved": "done", "on_rejected": "draft"}},
                {"key": "done", "label": "完成", "final": True}],
                "transitions": [{"key": "submit", "label": "送審", "from": "draft", "to": "pending"}]},
            "ui": {"form": {"groups": []}, "list": {"columns": []}}}


def _put_draft(client, h, key, body):
    r = client.put("/api/definitions/custom_module/%s/draft" % key, json={"body": body}, headers=h)
    assert r.status_code == 200, r.text


def _draft(key):
    rows = _q("SELECT body_json FROM ui_definitions WHERE kind='custom_module' AND key=? AND status='draft'", (key,))
    return json.loads(rows[0]["body_json"]) if rows else None


def _open_builder(page, base, key, step):
    page.goto("%s/pages/module-builder.html?key=%s" % (base, key))
    page.wait_for_selector("#mb-step-1", state="visible")
    page.click('.mb-step[data-step="%d"]' % step)
    page.wait_for_selector("#mb-step-%d" % step, state="visible")


def _wait_saved(page):
    page.wait_for_function(SAVED, timeout=15000)


def _blocks(key):
    return _draft(key)["output"]["template"]["blocks"]


# ── #4 ⑤ 積木參數表單依目錄的參數規格 ─────────────────────────────────────────

@pytest.mark.e2e
def test_builder_block_param_forms_follow_catalog_specs(live_server, make_user, new_context, client):
    key = "block_specs"
    admin = make_user(username="p8g_b_admin", role="superadmin")
    make_user(username="p8g_b_mgr", role="viewer", modules=[])
    h = _h(client, admin)
    _put_draft(client, h, key, _builder_body(key))
    cat = client.get("/api/custom-modules/catalog", headers=h).json()
    specs, items = cat["outputBlockSpecs"], cat["outputBlockItemSpecs"]

    errors = []
    page = _page(new_context, live_server, admin, errors)
    _open_builder(page, live_server, key, 5)
    page.click("#mb-out-custom")
    page.wait_for_selector('#mb-out-editor [data-block-type="meta"]')
    _wait_saved(page)

    # 每一塊的參數欄位＝目錄該積木的 params（順序相同）
    shown = page.eval_on_selector_all(
        "#mb-out-editor [data-block-index]",
        "els => els.map(e => [e.dataset.blockType, Array.from(e.querySelectorAll(':scope > [data-param]')).map(x => x.dataset.param)])")
    assert shown and all(ps == list(specs[t]["params"]) for t, ps in shown), shown
    meta_row = page.eval_on_selector_all('#mb-out-editor [data-block-type="meta"] [data-list="fields"] [data-item-row="0"] [data-param]',
                                         "els => els.map(e => e.dataset.param)")
    assert meta_row == list(items["field"]), meta_row
    # 可加入的積木＝目錄 outputBlocks ∩ 有參數規格 − 帶巢狀積木參數的
    addable = page.eval_on_selector_all("#mb-add-block option", "els => els.map(e => e.value).filter(v => v)")
    want = [t for t in cat["outputBlocks"] if t in specs and not any(p["type"] == "blocks" for p in specs[t]["params"].values())]
    assert addable == want, (addable, want)

    # 明細表：文字參數＋布林下拉（寫死 value＋x-model.boolean ⇒ DB 是 true／false，「未設定」＝拿掉）
    page.select_option("#mb-add-block", "items_table")
    blk = page.locator('#mb-out-editor [data-block-type="items_table"]')
    blk.wait_for()
    shown = blk.evaluate("e => Array.from(e.querySelectorAll(':scope > [data-param]')).map(x => x.dataset.param)")
    assert shown == list(specs["items_table"]["params"]), shown
    blk.locator(':scope > [data-param="label"] input[data-k="label"]').fill("借用明細")
    blk.locator(':scope > [data-param="hide_when_empty"] select[data-k="hide_when_empty"]').select_option("true")
    _wait_saved(page)
    it = [b for b in _blocks(key) if b["type"] == "items_table"][0]
    assert it["label"] == "借用明細" and it["hide_when_empty"] is True, it
    blk.locator(':scope > [data-param="hide_when_empty"] select[data-k="hide_when_empty"]').select_option("false")
    _wait_saved(page)
    assert [b for b in _blocks(key) if b["type"] == "items_table"][0]["hide_when_empty"] is False
    blk.locator(':scope > [data-param="hide_when_empty"] select[data-k="hide_when_empty"]').select_option("")
    _wait_saved(page)
    assert "hide_when_empty" not in [b for b in _blocks(key) if b["type"] == "items_table"][0]
    # 子項（list:column）：新增一列 ⇒ 子項參數依 outputBlockItemSpecs.column
    cols = blk.locator(':scope > [data-param="columns"] [data-list="columns"] > [data-item-row]')
    n0 = cols.count()
    blk.locator(':scope > [data-param="columns"] [data-add-item="columns"]').click()
    cols.nth(n0).wait_for()
    ks = cols.nth(n0).evaluate("e => Array.from(e.querySelectorAll('[data-param]')).map(x => x.dataset.param)")
    assert ks == list(items["column"]), ks
    cols.nth(n0).locator('input[data-k="title"]').fill("品名")
    _wait_saved(page)
    assert [b for b in _blocks(key) if b["type"] == "items_table"][0]["columns"][n0]["title"] == "品名"
    assert not errors, errors


def _route_catalog(page, mutate):
    def handle(route):
        resp = route.fetch()
        data = resp.json()
        mutate(data)
        route.fulfill(response=resp, json=data)
    page.route(re.compile(r".*/api/custom-modules/catalog$"), handle)


@pytest.mark.e2e
@pytest.mark.parametrize("variant", ["changed", "missing"])
def test_builder_theme_format_approver_lists_come_only_from_catalog(live_server, make_user, new_context, client, variant):
    """主題、欄位格式、簽核人來源、PDF 按鈕都照目錄：目錄改了畫面跟著改；目錄沒給 ⇒ 沒有選項（前端不留後備值）。"""
    key = "catalog_only"
    admin = make_user(username="p8g_c_admin", role="superadmin")
    make_user(username="p8g_b_mgr", role="viewer", modules=[])
    h = _h(client, admin)
    _put_draft(client, h, key, _builder_body(key))
    real = client.get("/api/custom-modules/catalog", headers=h).json()
    themes = list(real["outputThemes"]) + ["zz_catalog_theme"]
    formats = [f for f in reversed(real["fieldFormats"])][:2]
    sources = [s for s in real["approverSources"] if s["sourceType"] in ("", "submitter_manager")]
    assert len(sources) == 2 and len(formats) == 2

    def mutate(d):
        if variant == "changed":
            d["outputThemes"], d["fieldFormats"], d["approverSources"], d["outputFormats"] = themes, formats, sources, ["html"]
        else:
            for k in ("outputThemes", "fieldFormats", "approverSources", "outputFormats"):
                d.pop(k, None)

    errors = []
    page = _page(new_context, live_server, admin, errors)
    _route_catalog(page, mutate)
    _open_builder(page, live_server, key, 4)
    tier = page.locator('[data-approval-state="1"] [data-tier-index="0"]')
    tier.wait_for()
    assert tier.locator("[data-when-failsafe]").is_visible(), "when 旁邊要有 fail-safe 說明"
    kinds = tier.locator('select[data-k="approver-kind"] option').evaluate_all("els => els.map(e => e.value)")
    if variant == "changed":
        assert kinds == ["user", "submitter_manager"], kinds
        tier.locator('select[data-k="approver-kind"]').select_option("submitter_manager")
        _wait_saved(page)
        st = [s for s in _draft(key)["workflow"]["states"] if s["key"] == "pending"][0]
        assert st["approval"]["tiers"][0]["approvers"] == [{"sourceType": "submitter_manager"}], st
    else:
        assert kinds == [], kinds

    page.click('.mb-step[data-step="5"]')
    page.click("#mb-out-custom")
    page.wait_for_selector('#mb-out-editor [data-block-type="meta"]')
    theme_opts = page.eval_on_selector_all("#mb-out-theme option", "els => els.map(e => e.value)")
    fmt_opts = page.eval_on_selector_all(
        '#mb-out-editor [data-block-type="meta"] [data-list="fields"] [data-item-row="0"] select[data-k="format"] option',
        "els => els.map(e => e.value).filter(v => v)")
    assert page.locator("#mb-preview-pdf").is_hidden(), "目錄沒有 pdf ⇒ 不給 PDF 預覽"
    if variant == "changed":
        assert theme_opts == themes, theme_opts
        assert fmt_opts == formats, fmt_opts
    else:
        assert theme_opts == [] and fmt_opts == [], (theme_opts, fmt_opts)
    assert not errors, errors


# ── #5 建構器首頁：全部模組（含只有草稿的）＋刪草稿要二次確認 ───────────────────

@pytest.mark.e2e
def test_builder_home_lists_draft_only_modules_and_deletes_drafts_after_confirm(live_server, make_user, new_context, client):
    admin = make_user(username="p8g_h_admin", role="superadmin")
    make_user(username="p8g_b_mgr", role="viewer", modules=[])
    h = _h(client, admin)
    _publish(client, h, "home_pub", _builder_body("home_pub"))
    body = _builder_body("home_pub")
    body["name"] = "改過但還沒發布"
    _put_draft(client, h, "home_pub", body)
    _put_draft(client, h, "home_draft", _builder_body("home_draft"))
    server = client.get("/api/definitions/custom_module", headers=h).json()
    by_key = {d["key"]: d for d in server if d["scope"] == "company"}
    assert by_key["home_draft"]["latestVersion"] is None and by_key["home_draft"]["hasDraft"] is True

    errors = []
    page = _page(new_context, live_server, admin, errors)
    page.goto(live_server + "/pages/module-builder.html")
    page.wait_for_selector('#mb-module-list[data-loaded="1"]')
    rows = page.eval_on_selector_all("#mb-module-list tr[data-def-key]",
                                     "els => els.map(e => [e.dataset.defKey, e.dataset.latest, e.dataset.hasDraft])")
    assert rows == [[k, str(d["latestVersion"] or 0), "1" if d["hasDraft"] else "0"] for k, d in sorted(by_key.items())], rows

    # 取消 ⇒ 什麼都不刪
    page.click('[data-delete-draft="home_draft"]')
    page.click('[data-testid="ui-dialog-cancel"]')
    page.wait_for_selector('[data-testid="ui-dialog"]', state="detached")
    assert _draft("home_draft") is not None, "取消確認不可以刪"
    # 確認 ⇒ 只有草稿的模組整個消失
    page.click('[data-delete-draft="home_draft"]')
    page.click('[data-testid="ui-dialog-ok"]')
    page.wait_for_selector('#mb-module-list[data-loaded="1"]:not(:has(tr[data-def-key="home_draft"]))')
    assert not _q("SELECT 1 FROM ui_definitions WHERE kind='custom_module' AND key='home_draft'")
    # 已發布的模組：刪的只是草稿，第 1 版還在
    page.click('[data-delete-draft="home_pub"]')
    page.click('[data-testid="ui-dialog-ok"]')
    page.wait_for_selector('#mb-module-list[data-loaded="1"] tr[data-def-key="home_pub"][data-has-draft="0"]')
    assert _draft("home_pub") is None
    assert _q("SELECT version FROM ui_definitions WHERE kind='custom_module' AND key='home_pub' AND status='published'") == [{"version": 1}]
    assert not errors, errors


# ── #7 ⑤ PDF 預覽 ─────────────────────────────────────────────────────────────

@pytest.mark.e2e
def test_builder_pdf_preview_renders_the_saved_draft(live_server, make_user, new_context, client):
    key = "pdf_preview"
    admin = make_user(username="p8g_p_admin", role="superadmin")
    make_user(username="p8g_b_mgr", role="viewer", modules=[])
    _put_draft(client, _h(client, admin), key, _builder_body(key))
    errors = []
    page = _page(new_context, live_server, admin, errors)
    _open_builder(page, live_server, key, 5)
    page.click("#mb-out-custom")
    page.wait_for_selector('#mb-preview-state[data-state="ok"]')
    _wait_saved(page)
    with page.expect_popup() as pop, \
            page.expect_response(lambda r: "/output/preview" in r.url and r.request.method == "POST" and "format=" in r.url) as resp:
        page.click("#mb-preview-pdf")
    r = resp.value
    assert r.status == 200 and "format=pdf" in r.url, r.url
    assert r.headers["content-type"].startswith("application/pdf"), r.headers["content-type"]
    sent = r.request.post_data_json["body"]
    assert sent == _draft(key), "PDF 預覽的是存好的草稿"
    again = client.post("/api/custom-modules/%s/output/preview?format=pdf" % key, json={"body": sent}, headers=_h(client, admin))
    assert again.status_code == 200 and again.content[:5] == b"%PDF-", (again.status_code, again.content[:40])
    page.wait_for_selector('#mb-pdf-state[data-state="ok"]', state="attached")
    assert int(page.get_attribute("#mb-pdf-state", "data-bytes")) > 1000, "頁面拿到的 PDF 是空的"
    pop.value.close()
    assert not errors, errors
