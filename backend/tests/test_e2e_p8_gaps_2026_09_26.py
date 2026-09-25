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
