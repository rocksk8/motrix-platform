# -*- coding: utf-8 -*-
"""建構器第三輪 S4／S5 — 畫面（＋DB）：
① 建構器發布抽屜的「模組審核人」名單與模式：勾審核人 ⇒ 標頭徽章變「送審：啟用」（伺服器狀態一致）
② 審核頁（簽核人不是最高管理者也能開）：差異表、退回沒填原因被擋、退回落地、歷史列出、核可後發布
③ 執行頁單據的修訂紀錄：-R1 顯示、比對顯示差異"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._builder_nav import go_step, start_blank  # noqa: E402
from tests._e2e_login import inject_login  # noqa: E402

SAVED = """() => { const e = document.getElementById('mb-save-state');
  return !!e && e.dataset.dirty === '0' && e.dataset.saving === '0' && e.dataset.state === 'saved' }"""


def _db(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _tok(client, u, p):
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


@pytest.mark.e2e
def test_builder_drawer_reviewer_list_switches_the_header_badge(live_server, make_user, new_context, client):
    boss = make_user(username="b3e2_boss", role="superadmin")
    make_user(username="b3e2_appr", role="admin", modules=[])
    page = new_context().new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, boss[0], boss[1])
    page.goto(live_server + "/pages/module-builder.html")
    start_blank(page, "b3e2_mod")
    assert page.locator("#mb-review-badge").inner_text().strip() == "送審：未啟用"
    page.click('.mb-tab[data-tab="form"]')
    page.click('#mb-palette [data-palette-element="text"]')
    page.fill("#mb-f-label", "標題")
    page.wait_for_function(SAVED, timeout=15000)
    go_step(page, 6)
    assert "未經第二人審核" in page.locator("#mb-review-state").inner_text()
    page.locator("#mb-review-box summary").click()
    page.check('[data-reviewer="b3e2_appr"]')
    page.wait_for_function("() => document.getElementById('mb-review-badge').innerText.trim() === '送審：啟用'", timeout=10000)
    assert "b3e2_appr" in json.dumps(_db("SELECT value_json FROM system_settings WHERE key='custom_module_def_reviewers'"), ensure_ascii=False)
    assert page.locator("#mb-publish").inner_text().strip() == "送審"
    page.select_option("#mb-review-mode", "off")
    page.wait_for_function("() => document.getElementById('mb-review-badge').innerText.trim() === '送審：未啟用'", timeout=10000)
    assert page.locator("#mb-publish").inner_text().strip() == "發布"
    page.uncheck('[data-reviewer="b3e2_appr"]')
    page.select_option("#mb-review-mode", "auto")
    assert not errors, errors


@pytest.mark.e2e
def test_review_page_shows_diff_blocks_reject_without_reason_and_publishes_on_approve(live_server, make_user, new_context, client):
    boss = make_user(username="b3e2_boss2", role="superadmin")
    appr = make_user(username="b3e2_appr2", role="admin", modules=[])
    hb = _tok(client, boss[0], boss[1])
    key = "b3e2rv"
    body = {"name": "審核頁", "permission": "custom." + key, "numbering": {"prefix": "RP", "period": "none", "digits": 3},
            "fields": [{"key": "title", "label": "標題", "type": "text", "required": True, "dataClass": "T1"}],
            "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿"}, {"key": "done", "label": "完成", "final": True}],
                         "transitions": [{"key": "submit", "label": "送出", "from": "draft", "to": "done"}]}}
    assert client.put("/api/custom-modules/definition-review", headers=hb, json={"reviewers": ["b3e2_appr2"]}).status_code == 200
    assert client.put("/api/definitions/custom_module/%s/draft" % key, headers=hb, json={"body": body}).json()["problems"] == []
    assert client.post("/api/definitions/custom_module/%s/publish" % key, headers=hb, json={"note": "首版"}).json()["pending"] is True

    page = new_context().new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, appr[0], appr[1])                            # 審核人不是最高管理者也開得了審核頁
    page.goto(live_server + "/pages/custom-def-review.html?key=" + key)
    page.wait_for_selector("#dr-open", timeout=15000)
    assert page.locator("#dr-open").get_attribute("data-version") == "1"
    assert page.locator("#dr-diff tbody tr").count() >= 1                        # 第一次發布：全是新增
    page.click("#dr-reject")                                                     # 沒填原因 ⇒ 擋
    page.wait_for_selector("#dr-error", state="visible")
    assert "退回要填原因" in page.locator("#dr-error").inner_text()
    assert [s for _v, s in [(r["version"], r["status"]) for r in _db("SELECT version, status FROM ui_definitions WHERE key=? ORDER BY version", (key,))]] == ["draft", "submitted"]
    page.fill("#dr-note", "欄位要再想一下")
    page.click("#dr-reject")
    page.wait_for_selector("#dr-none", state="visible", timeout=10000)
    assert page.locator('[data-hist-version="1"]').inner_text().count("欄位要再想一下") == 1
    assert _db("SELECT status FROM ui_definitions WHERE key=? AND version=1", (key,))[0]["status"] == "rejected"
    # 重送 ⇒ v2；核可 ⇒ 發布
    assert client.post("/api/definitions/custom_module/%s/publish" % key, headers=hb, json={}).json()["version"] == 2
    page.reload()
    page.wait_for_selector("#dr-open", timeout=15000)
    assert page.locator("#dr-open").get_attribute("data-version") == "2"
    page.click("#dr-approve")
    page.wait_for_selector("#dr-done", state="visible", timeout=10000)
    assert "已核可並發布" in page.locator("#dr-done").inner_text()
    assert _db("SELECT status FROM ui_definitions WHERE key=? AND version=2", (key,))[0]["status"] == "published"
    assert not errors, errors


@pytest.mark.e2e
def test_record_page_shows_r1_and_compares_revisions(live_server, make_user, new_context, client):
    boss = make_user(username="b3e2_boss3", role="superadmin")
    appr = make_user(username="b3e2_appr3", role="user", modules=[])
    hb = _tok(client, boss[0], boss[1])
    ha = _tok(client, appr[0], appr[1])
    key = "b3e2hs"
    f = lambda k, l, t, **kw: dict({"key": k, "label": l, "type": t, "dataClass": "T1"}, **kw)
    body = {"name": "修訂頁", "permission": "custom." + key, "numbering": {"prefix": "HS", "period": "none", "digits": 3},
            "fields": [f("title", "標題", "text", required=True), f("amt", "金額", "number")],
            "workflow": {"initial": "draft",
                         "states": [{"key": "draft", "label": "草稿"},
                                    {"key": "pending", "label": "簽核中", "approval": {"tiers": [{"approvers": [{"username": "b3e2_appr3"}]}],
                                                                                       "on_approved": "done", "on_rejected": "draft"}},
                                    {"key": "done", "label": "完成", "final": True}],
                         "transitions": [{"key": "submit", "label": "送簽", "from": "draft", "to": "pending"}]}}
    assert client.put("/api/definitions/custom_module/%s/draft" % key, headers=hb, json={"body": body}).json()["problems"] == []
    assert client.post("/api/definitions/custom_module/%s/publish" % key, headers=hb, json={}).status_code == 200
    no = client.post("/api/custom/%s/records" % key, headers=hb, json={"values": {"title": "T", "amt": 100}}).json()["record_no"]
    assert client.post("/api/custom/%s/records/%s/transitions/submit" % (key, no), headers=hb, json={}).status_code == 200
    assert client.post("/api/custom/%s/records/%s/reject" % (key, no), headers=ha, json={"note": "金額不對"}).status_code == 200
    assert client.put("/api/custom/%s/records/%s" % (key, no), headers=hb, json={"values": {"title": "T", "amt": 120}}).status_code == 200
    assert client.post("/api/custom/%s/records/%s/transitions/submit" % (key, no), headers=hb, json={}).status_code == 200

    page = new_context().new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, boss[0], boss[1])
    page.goto(live_server + "/pages/custom-records.html?key=%s&no=%s" % (key, no))
    page.wait_for_selector("#cr-record", timeout=20000)
    assert page.locator("#cr-record-no").inner_text().strip() == no + "-R1"
    assert page.locator("#cr-record-no").get_attribute("data-base-no") == no
    page.wait_for_selector("#cr-revisions", state="visible", timeout=10000)
    assert page.locator('#cr-revisions tr[data-revision]').count() == 2
    assert "退回：金額不對" in page.locator('#cr-revisions tr[data-revision="0"]').inner_text()
    page.click('[data-diff-prev="1"]')
    page.wait_for_selector('#cr-rev-diff [data-diff-field="amt"]', timeout=10000)
    row = page.locator('#cr-rev-diff [data-diff-field="amt"]').inner_text()
    assert "100" in row and "120" in row
    assert page.locator('#cr-rev-diff [data-diff-field="title"]').count() == 0            # 沒變的欄位不列
    assert not errors, errors
