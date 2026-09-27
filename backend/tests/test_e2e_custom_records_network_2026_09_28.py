# -*- coding: utf-8 -*-
"""custom-records 同頁的列表、儲存、轉換、核准在網路層失敗時要說出來並可重試（稽核 D O15-O1；IMPROVEMENT-REPORT §6）。

修正前：這幾支請求有 try/finally（按鈕會恢復），但 fetch reject 沒人接 ⇒ 畫面沒有任何訊息、console 有 pageerror。
修正：api／post／put 走同一支 `_send`，網路層失敗回 {ok:false, status:'network'}，錯誤列顯示「…失敗：網路連線失敗」
＋〔重試〕；建立單據例外——回應掉了可能已建好 ⇒ 按鈕是「重新整理列表」，不直接重送（會重複建單）。
非網路失敗（伺服器回 4xx）行為不變：顯示伺服器的說明、沒有〔重試〕。

route.abort 決定性重現；斷言打在資料庫與錯誤列的 DOM；等待一律等動作的終點（busy 解除、狀態屬性）。
"""
import json
import re

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

KEY = "cr_netfail"


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def _status(no):
    return _q("SELECT status FROM custom_records WHERE module_key=? AND record_no=?", (KEY, no))[0]["status"]


def _count():
    return _q("SELECT COUNT(*) AS n FROM custom_records WHERE module_key=?", (KEY,))[0]["n"]


def _h(client, user):
    r = client.post("/api/auth/login", json={"username": user[0], "password": user[1]})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _module(approver):
    return {"name": "網路失敗測試", "permission": "custom.%s" % KEY, "numbering": {"prefix": "NF", "date": "", "digits": 3},
            "fields": [{"key": "a", "label": "甲", "type": "text", "dataClass": "T1"}],
            "workflow": {"initial": "draft", "states": [
                {"key": "draft", "label": "草稿"},
                {"key": "pending", "label": "簽核中", "approval": {
                    "tiers": [{"approvers": [{"username": approver}]}], "on_approved": "done", "on_rejected": "draft"}},
                {"key": "done", "label": "完成", "final": True}],
                "transitions": [{"key": "submit", "label": "送審", "from": "draft", "to": "pending"}]}}


@pytest.fixture()
def setup(live_server, make_user, client, new_context):
    admin = make_user(username="crn_admin", role="superadmin")
    user = make_user(username="crn_user", role="viewer", modules=["custom.%s" % KEY])
    mgr = make_user(username="crn_mgr", role="viewer", modules=[])
    h = _h(client, admin)
    assert client.put("/api/definitions/custom_module/%s/draft" % KEY, json={"body": _module(mgr[0])}, headers=h).status_code == 200
    assert client.post("/api/definitions/custom_module/%s/publish" % KEY, json={}, headers=h).status_code == 200
    errors = []

    def page_for(u):
        ctx = new_context()
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append("%s: %s" % (u[0], e)))
        inject_login(page, live_server, u[0], u[1])
        return page

    def new_record(values=None):
        r = client.post("/api/custom/%s/records" % KEY, json={"values": values or {"a": "x"}}, headers=_h(client, user))
        assert r.status_code == 200, r.text
        return r.json()["record_no"]
    return {"base": live_server, "user": user, "mgr": mgr, "page_for": page_for, "new_record": new_record,
            "client": client, "errors": errors}


def _url(s, no=None):
    return "%s/pages/custom-records.html?key=%s%s" % (s["base"], KEY, ("&no=" + no) if no else "")


def _error(page, needle):
    page.wait_for_function("t => { const e = document.getElementById('cr-error-text'); return !!e && e.textContent.indexOf(t) >= 0 }", arg=needle)
    return page.text_content("#cr-error-text"), page.locator("#cr-retry")


def _idle(page):
    page.wait_for_selector('#cr-record[data-busy="0"]')


@pytest.mark.e2e
def test_list_network_failure_says_so_and_retry_loads(setup):
    s = setup
    no = s["new_record"]()
    page = s["page_for"](s["user"])
    pat = re.compile(r".*/api/custom/%s/records(\?.*)?$" % KEY)
    page.route(pat, lambda r: r.abort())
    page.goto(_url(s))
    text, retry = _error(page, "讀取列表失敗")
    assert "網路連線失敗" in text and retry.is_visible() and retry.text_content() == "重試"
    page.unroute(pat)
    retry.click()
    page.wait_for_selector('#cr-list tr[data-record-no="%s"]' % no)
    assert page.locator("#cr-error").is_hidden()
    assert not s["errors"], s["errors"]


@pytest.mark.e2e
def test_create_network_failure_does_not_resend_blindly(setup):
    """建立：網路失敗 ⇒ 說「無法確認是否已建立」、按鈕是「重新整理列表」（不是重送）；確認後再儲存 ⇒ 只建一筆。"""
    s = setup
    page = s["page_for"](s["user"])
    page.goto(_url(s))
    page.wait_for_selector("#cr-new")
    page.click("#cr-new")
    page.fill("#cr-in-a", "網路斷了")
    pat = re.compile(r".*/api/custom/%s/records$" % KEY)
    page.route(pat, lambda r: r.abort() if r.request.method == "POST" else r.continue_())
    page.click("#cr-save")
    text, retry = _error(page, "建立失敗")
    assert "無法確認是否已建立" in text and retry.text_content() == "重新整理列表"
    assert _count() == 0
    page.unroute(pat)
    retry.click()
    page.wait_for_function("() => document.getElementById('cr-error').style.display === 'none'")
    page.click("#cr-save")
    _idle(page)
    assert _count() == 1
    assert not s["errors"], s["errors"]


@pytest.mark.e2e
def test_update_network_failure_retry_saves(setup):
    s = setup
    no = s["new_record"]({"a": "舊"})
    page = s["page_for"](s["user"])
    page.goto(_url(s, no))
    _idle(page)
    page.click("#cr-edit")
    page.fill("#cr-in-a", "新")
    pat = re.compile(r".*/api/custom/%s/records/%s$" % (KEY, no))
    page.route(pat, lambda r: r.abort() if r.request.method == "PUT" else r.continue_())
    page.click("#cr-save")
    text, retry = _error(page, "儲存失敗")
    assert "網路連線失敗" in text and retry.text_content() == "重試"
    page.unroute(pat)
    retry.click()
    _idle(page)
    got = json.loads(_q("SELECT data_json FROM custom_records WHERE record_no=?", (no,))[0]["data_json"])
    assert got["a"] == "新"
    assert not s["errors"], s["errors"]


@pytest.mark.e2e
def test_transition_and_approval_network_failure_retry_completes(setup):
    s = setup
    no = s["new_record"]()
    page = s["page_for"](s["user"])
    page.goto(_url(s, no))
    _idle(page)
    pat = re.compile(r".*/transitions/submit$")
    page.route(pat, lambda r: r.abort())
    page.click('[data-transition="submit"]')
    text, retry = _error(page, "送審失敗")
    assert "網路連線失敗" in text and _status(no) == "draft"
    page.unroute(pat)
    retry.click()
    page.wait_for_selector('#cr-record[data-status="pending"][data-busy="0"]')
    assert _status(no) == "pending"

    mp = s["page_for"](s["mgr"])
    mp.goto(_url(s, no))
    mp.wait_for_selector("#cr-approve")
    pat2 = re.compile(r".*/records/%s/approve$" % no)
    mp.route(pat2, lambda r: r.abort())
    mp.click("#cr-approve")
    text, retry2 = _error(mp, "核准失敗")
    assert "網路連線失敗" in text and _status(no) == "pending"
    mp.unroute(pat2)
    retry2.click()
    mp.wait_for_selector('#cr-record[data-status="done"][data-busy="0"]')
    assert _status(no) == "done"
    assert not s["errors"], s["errors"]


@pytest.mark.e2e
def test_server_errors_are_unchanged_and_offer_no_retry(setup):
    """反向控制：伺服器回 409（有 HTTP 狀態）⇒ 照舊顯示伺服器的說明，**沒有**〔重試〕（重送不會變好）。"""
    s = setup
    no = s["new_record"]()
    page = s["page_for"](s["user"])
    page.goto(_url(s, no))
    _idle(page)
    page.route(re.compile(r".*/transitions/submit$"),
               lambda r: r.fulfill(status=409, content_type="application/json", body=json.dumps({"detail": "目前狀態不能送審（測試）"})))
    page.click('[data-transition="submit"]')
    _error(page, "目前狀態不能送審（測試）")
    _idle(page)
    assert page.locator("#cr-retry").is_hidden()
    assert "網路" not in page.text_content("#cr-error-text")
    assert not s["errors"], s["errors"]
