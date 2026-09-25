# -*- coding: utf-8 -*-
"""D4 驗收（CUSTOMIZATION-SPEC §8.3）：用建構器從零建立「測試用設備借用單」，不改任何程式碼就能新增、送審、核准、匯出。

一條細線走到底（瀏覽器操作，斷言打在伺服器狀態：定義庫、單據表、通知表、輸出端點）：
  ① 建構器（超級管理員）：基本＋編號預覽 → 欄位（拖曳、必填、預設、公式〔先打錯看位置〕、參照）
     → 版面（分組、列表欄）→ 流程（狀態、轉換、兩層簽核〔第二層帶 when〕、通知）→ 輸出（指定版型、預覽）
     → 發布（先故意缺參照對象：422 標回步驟與欄位；補上後看差異、發布）
  ② 一般使用者（只有 custom.equipment_loan 權限）：新增（先漏必填：400 標回欄位）→ 送審
  ③ 兩位簽核人（沒有模組權限，用 &no= 開單）依序核准 → ④ 申請人匯出 PDF
  ⑤ 改定義發布第 2 版 ⇒ 舊單仍是第 1 版（輸出照舊）、新單用第 2 版

- 等待一律等動作的終點狀態（草稿存檔完成、busy 解除、狀態改變），不用 sleep。
- 布林下拉（必填、終點、只限申請人）寫死 value＋x-model.boolean ⇒ 驗 DB 裡是 true／false，不是字串。
"""
import json
import re

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

KEY = "equipment_loan"
SAVED = """() => { const e = document.getElementById('mb-save-state');
  return !!e && e.dataset.dirty === '0' && e.dataset.saving === '0' && e.dataset.state === 'saved' }"""
IDLE = """() => { const e = document.getElementById('cr-record'); return !!e && e.dataset.busy === '0' }"""


def _db():
    import db
    return db.get_db()


def _definition(version=None):
    conn = _db()
    try:
        if version is None:
            r = conn.execute("SELECT version, body_json FROM ui_definitions WHERE kind='custom_module' AND key=? "
                             "AND status='published' ORDER BY version DESC LIMIT 1", (KEY,)).fetchone()
        else:
            r = conn.execute("SELECT version, body_json FROM ui_definitions WHERE kind='custom_module' AND key=? AND version=?",
                             (KEY, version)).fetchone()
        return (r["version"], json.loads(r["body_json"])) if r else (None, None)
    finally:
        conn.close()


def _record(no):
    conn = _db()
    try:
        r = conn.execute("SELECT * FROM custom_records WHERE module_key=? AND record_no=?", (KEY, no)).fetchone()
        if r is None:
            return None
        d = dict(r)
        d["data"] = json.loads(d.pop("data_json") or "{}")
        d["approval"] = json.loads(d.pop("approval_json") or "{}")
        return d
    finally:
        conn.close()


def _record_count():
    conn = _db()
    try:
        return conn.execute("SELECT COUNT(*) FROM custom_records WHERE module_key=?", (KEY,)).fetchone()[0]
    finally:
        conn.close()


def _notices(username, ref_id):
    conn = _db()
    try:
        return [dict(r) for r in conn.execute("SELECT type, message FROM notifications WHERE username=? AND ref_id=?",
                                              (username, ref_id)).fetchall()]
    finally:
        conn.close()


def _output_html(client, token, no):
    r = client.get("/api/custom/%s/records/%s/output" % (KEY, no), headers={"Authorization": "Bearer " + token})
    assert r.status_code == 200, r.text
    return r.text


def _login_token(client, user):
    r = client.post("/api/auth/login", json={"username": user[0], "password": user[1]})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _page(new_context, base, user, errors):
    ctx = new_context(accept_downloads=True)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append("%s: %s" % (user[0], e)))
    inject_login(page, base, user[0], user[1])
    return page


# ── 建構器操作 ─────────────────────────────────────────────────────────────

def _wait_saved(page):
    page.wait_for_function(SAVED, timeout=15000)


def _step(page, n):
    page.click('.mb-step[data-step="%d"]' % n)
    page.wait_for_selector('#mb-step-%d' % n, state="visible")


def _set_field(page, key, label, required=None, default=None):
    """設定目前選取的欄位（屬性面板）。"""
    page.fill("#mb-f-key", key)
    page.press("#mb-f-key", "Tab")
    page.wait_for_selector('.mb-fc.is-sel[data-field-key="%s"]' % key)
    page.fill("#mb-f-label", label)
    if required is not None:
        page.select_option("#mb-f-required", "true" if required else "false")
    if default is not None:
        page.fill("#mb-f-default", str(default))
        page.press("#mb-f-default", "Tab")


def _state_row(page, i):
    return page.locator('#mb-states tr[data-state-index="%d"]' % i)


def _set_state(page, i, key, label):
    row = _state_row(page, i)
    row.locator('input[data-k="key"]').fill(key)
    row.locator('input[data-k="key"]').press("Tab")
    page.wait_for_selector('#mb-states tr[data-state-index="%d"][data-state-key="%s"]' % (i, key))
    row.locator('input[data-k="label"]').fill(label)


def _transition_row(page, i):
    return page.locator('#mb-transitions tr[data-transition-index="%d"]' % i)


def _build_equipment_loan(page, base):
    page.goto(base + "/pages/module-builder.html")
    page.fill("#mb-key", KEY)
    page.click("#mb-open")
    page.wait_for_selector("#mb-step-1", state="visible")

    # ① 基本＋編號預覽（伺服器產生的範例）
    page.fill("#mb-name", "測試用設備借用單")
    page.fill("#mb-prefix", "EL")
    page.select_option("#mb-date", "YYYYMMDD")
    page.wait_for_function("() => /^EL-\\d{8}-0001$/.test(document.getElementById('mb-num-example').dataset.example || '')")
    _wait_saved(page)

    # ② 欄位：第一個用拖曳，其餘點一下加到最後
    _step(page, 2)
    page.drag_and_drop('[data-palette-type="text"]', "#mb-canvas")
    page.wait_for_selector('.mb-fc[data-field-index="0"]')
    _set_field(page, "item", "設備", required=True)
    page.click('[data-palette-type="number"]')
    _set_field(page, "qty", "數量", required=True)
    page.click('[data-palette-type="number"]')
    _set_field(page, "unit_value", "單價", required=False, default=0)
    page.click('[data-palette-type="formula"]')
    _set_field(page, "total", "總值")
    page.fill("#mb-f-formula", "qty * unit_valeu")            # 打錯：第 7 字（pos 6）引用不到
    page.wait_for_selector('#mb-f-formula-problems[data-state="bad"] [data-pos="6"]')
    page.fill("#mb-f-formula", "qty * unit_value")
    page.wait_for_selector('#mb-f-formula-problems[data-state="ok"]')
    page.click('[data-palette-type="ref"]')
    _set_field(page, "borrower", "借用人", required=False)    # 參照對象故意先不選
    _wait_saved(page)

    # ⑥ 先發布一次：缺參照對象 ⇒ 422，問題標回 ② 的第 5 個欄位
    _step(page, 6)
    page.click("#mb-publish")
    page.wait_for_selector('#mb-publish-problems [data-problem-path="fields[4].target"][data-problem-step="2"]')
    assert _definition()[0] is None, "有問題的定義不可以被發布"
    page.click('#mb-publish-problems [data-problem-path="fields[4].target"] a')
    page.wait_for_selector('#mb-step-2', state="visible")
    page.wait_for_selector('.mb-fc.is-bad.is-sel[data-field-index="4"]')
    page.select_option("#mb-f-target", "users")
    _wait_saved(page)

    # ③ 版面：一個分組放設備與數量；列表多顯示借用人
    _step(page, 3)
    page.click("#mb-add-group")
    page.locator('[data-group-index="0"] input').fill("借用資訊")
    page.locator('[data-group-index="0"] input').press("Tab")
    page.select_option('[data-assign-field="item"]', "0")
    page.wait_for_selector('[data-group-index="0"] [data-group-field="item"]')
    page.select_option('[data-assign-field="qty"]', "0")
    page.wait_for_selector('[data-group-index="0"] [data-group-field="qty"]')
    page.click('[data-list-column="borrower"]')
    _wait_saved(page)

    # ④ 流程：draft → pending（兩層簽核，第二層帶條件）→ approved／rejected → returned
    _step(page, 4)
    _set_state(page, 1, "returned", "已歸還")
    _state_row(page, 1).locator('select[data-k="final"]').select_option("true")
    for _ in range(3):
        page.click("#mb-add-state")
    _set_state(page, 2, "pending", "簽核中")
    _set_state(page, 3, "approved", "已核准")
    _set_state(page, 4, "rejected", "已退回")
    _state_row(page, 3).locator('select[data-k="notify-requester"]').select_option("true")
    _state_row(page, 4).locator('select[data-k="notify-requester"]').select_option("true")
    _state_row(page, 2).locator('select[data-k="has-approval"]').select_option("true")
    ap = page.locator('[data-approval-state="2"]')
    ap.wait_for()
    ap.locator('select[data-k="on-approved"]').select_option("approved")
    ap.locator('select[data-k="on-rejected"]').select_option("rejected")
    ap.locator('[data-tier-index="0"] select[data-k="approver-user"]').select_option("p8_mgr")
    ap.locator('[data-k="add-tier"]').click()
    ap.locator('[data-tier-index="1"] select[data-k="approver-user"]').select_option("p8_boss")
    ap.locator('[data-tier-index="1"] input[data-k="when"]').fill("total >")          # 打錯：條件不完整
    ap.locator('[data-tier-index="1"] [data-when-state="bad"]').wait_for(state="attached")
    ap.locator('[data-tier-index="1"] input[data-k="when"]').fill("total > 10000")
    ap.locator('[data-tier-index="1"] [data-when-state="ok"]').wait_for(state="attached")

    t0 = _transition_row(page, 0)
    t0.locator('input[data-k="label"]').fill("送審")
    t0.locator('select[data-k="to"]').select_option("pending")
    page.click("#mb-add-transition")
    t1 = _transition_row(page, 1)
    t1.locator('input[data-k="key"]').fill("give_back")
    t1.locator('input[data-k="label"]').fill("歸還")
    t1.locator('[data-from="approved"]').check()
    t1.locator('select[data-k="to"]').select_option("returned")
    page.click("#mb-add-transition")
    t2 = _transition_row(page, 2)
    t2.locator('input[data-k="key"]').fill("revise")
    t2.locator('input[data-k="label"]').fill("改回草稿")
    t2.locator('[data-from="rejected"]').check()
    t2.locator('select[data-k="to"]').select_option("draft")
    t2.locator('select[data-k="requester-only"]').select_option("true")
    _wait_saved(page)

    # ⑤ 輸出：指定版型（從目錄的積木組出來），伺服器用樣本資料預覽
    _step(page, 5)
    page.click("#mb-out-custom")
    page.wait_for_selector('#mb-out-editor [data-block-type="meta"]')
    page.wait_for_selector('#mb-preview-state[data-state="ok"]')
    _wait_saved(page)

    # ⑥ 差異 → 發布
    _step(page, 6)
    page.wait_for_selector('#mb-diff[data-loaded="1"] [data-change-path="fields"]')
    page.fill("#mb-publish-note", "第一版")
    page.click("#mb-publish")
    page.wait_for_selector('#mb-versions tr[data-version="1"]')


def _assert_definition_v1():
    v, body = _definition()
    assert v == 1, v
    fields = {f["key"]: f for f in body["fields"]}
    assert [f["key"] for f in body["fields"]] == ["item", "qty", "unit_value", "total", "borrower"]
    assert body["name"] == "測試用設備借用單"
    assert body["numbering"] == {"prefix": "EL", "date": "YYYYMMDD", "digits": 4}
    # 布林下拉存的是布林（不是 "true"／"false" 字串）
    assert fields["item"]["required"] is True and fields["qty"]["required"] is True
    assert fields["unit_value"]["required"] is False and fields["unit_value"]["default"] == 0
    assert fields["total"] == {"key": "total", "label": "總值", "type": "formula", "dataClass": "T1", "formula": "qty * unit_value"}
    assert fields["borrower"]["type"] == "ref" and fields["borrower"]["target"] == "users"
    assert body["ui"]["form"]["groups"] == [{"title": "借用資訊", "fields": ["item", "qty"]}]
    assert "borrower" in body["ui"]["list"]["columns"]
    wf = body["workflow"]
    states = {s["key"]: s for s in wf["states"]}
    assert wf["initial"] == "draft"
    assert states["returned"]["final"] is True
    assert states["approved"]["notify"] == {"requester": True}
    appr = states["pending"]["approval"]
    assert appr["on_approved"] == "approved" and appr["on_rejected"] == "rejected"
    assert [a["username"] for a in appr["tiers"][0]["approvers"]] == ["p8_mgr"]
    assert "when" not in appr["tiers"][0]
    assert [a["username"] for a in appr["tiers"][1]["approvers"]] == ["p8_boss"]
    assert appr["tiers"][1]["when"] == "total > 10000"
    trans = {t["key"]: t for t in wf["transitions"]}
    assert trans["submit"] == {"key": "submit", "label": "送審", "from": "draft", "to": "pending"}
    assert trans["give_back"]["from"] == "approved" and trans["give_back"]["to"] == "returned"
    assert trans["revise"]["requester_only"] is True
    tpl = body["output"]["template"]
    assert [b["type"] for b in tpl["blocks"]] == ["identity_header", "meta", "approval_sign", "identity_footer"]
    return body


@pytest.mark.e2e
def test_d4_equipment_loan_built_in_browser_then_used_end_to_end(live_server, make_user, new_context, client):
    admin = make_user(username="p8_admin", role="superadmin")
    requester = make_user(username="p8_user", role="viewer", modules=["custom.%s" % KEY])
    mgr = make_user(username="p8_mgr", role="viewer", modules=[])
    boss = make_user(username="p8_boss", role="viewer", modules=[])
    errors = []

    # ① 建構器
    ap = _page(new_context, live_server, admin, errors)
    _build_equipment_loan(ap, live_server)
    _assert_definition_v1()

    # ② 一般使用者：選單出現模組 → 新增（先漏必填）→ 送審
    up = _page(new_context, live_server, requester, errors)
    up.goto(live_server + "/pages/custom-records.html?key=" + KEY)
    up.wait_for_selector('#app-mainnav a[data-custom-nav="%s"]' % KEY, state="attached")   # 在下拉面板裡（收合）
    up.wait_for_selector("#cr-new")
    up.click("#cr-new")
    up.fill("#cr-in-item", "投影機")
    up.fill("#cr-in-unit_value", "5000")
    up.click("#cr-save")
    up.wait_for_selector('[data-field-error="qty"]', state="visible")          # 400 problems[{key}] 標回欄位
    assert _record_count() == 0
    up.fill("#cr-in-qty", "3")
    up.wait_for_selector('#cr-in-borrower option[value="p8_user"]', state="attached")
    up.select_option("#cr-in-borrower", "p8_user")
    up.click("#cr-save")
    up.wait_for_selector("#cr-record[data-record-no]")
    no = up.get_attribute("#cr-record", "data-record-no")
    assert re.match(r"^EL-\d{8}-0001$", no), no
    rec = _record(no)
    assert rec["def_version"] == 1 and rec["status"] == "draft"
    assert rec["data"] == {"item": "投影機", "qty": 3, "unit_value": 5000, "total": 15000, "borrower": "p8_user"}

    up.click('[data-transition="submit"]')
    up.wait_for_selector('#cr-record[data-status="pending"][data-busy="0"]')
    rec = _record(no)
    assert rec["status"] == "pending"
    assert [[a["username"] for a in t["approvers"]] for t in rec["approval"]["tiers"]] == [["p8_mgr"], ["p8_boss"]]   # 15000 > 10000 ⇒ 第二層列入
    assert any(n["type"] == "approval" for n in _notices("p8_mgr", no)), "進入簽核要通知第一位簽核人"

    # ③ 簽核人（沒有模組權限）用 &no= 開單核准
    mp = _page(new_context, live_server, mgr, errors)
    mp.goto("%s/pages/custom-records.html?key=%s&no=%s" % (live_server, KEY, no))
    mp.wait_for_selector("#cr-approve")
    mp.fill("#cr-decide-note", "同意借用")
    mp.click("#cr-approve")
    mp.wait_for_selector("#cr-decide", state="detached")
    mp.wait_for_function(IDLE)
    rec = _record(no)
    assert rec["status"] == "pending" and rec["approval"]["currentTier"] == 1
    assert any(n["type"] == "approval" for n in _notices("p8_boss", no)), "過一層要通知下一位"

    bp = _page(new_context, live_server, boss, errors)
    bp.goto("%s/pages/custom-records.html?key=%s&no=%s" % (live_server, KEY, no))
    bp.wait_for_selector("#cr-approve")
    bp.click("#cr-approve")
    bp.wait_for_selector('#cr-record[data-status="approved"][data-busy="0"]')
    rec = _record(no)
    assert rec["status"] == "approved"
    assert any(n["type"] == "info" for n in _notices("p8_user", no)), "已核准要通知申請人"

    # ④ 申請人匯出 PDF
    up.goto("%s/pages/custom-records.html?key=%s&no=%s" % (live_server, KEY, no))
    up.wait_for_selector('#cr-record[data-status="approved"]')
    with up.expect_download(timeout=60000) as dl:
        up.click("#cr-out-pdf")
    pdf_path = dl.value.path()
    with open(pdf_path, "rb") as f:
        assert f.read(5) == b"%PDF-"

    # ⑤ 改定義（欄位名稱＋輸出列標籤）發布第 2 版 ⇒ 舊單仍依第 1 版
    ap.goto("%s/pages/module-builder.html?key=%s" % (live_server, KEY))
    ap.wait_for_selector("#mb-step-1", state="visible")
    _step(ap, 2)
    ap.click('.mb-fc[data-field-key="qty"]')
    ap.fill("#mb-f-label", "借用數量")
    _step(ap, 5)
    row = ap.locator('#mb-out-editor [data-block-type="meta"] [data-meta-row]').filter(
        has=ap.locator('select[data-k="path"] option:checked[value="fields.qty"]'))
    row.locator('input[data-k="label"]').fill("借用數量")
    _wait_saved(ap)
    _step(ap, 6)
    ap.wait_for_selector('#mb-diff[data-loaded="1"] [data-change-path="fields[1].label"]')
    ap.click("#mb-publish")
    ap.wait_for_selector('#mb-versions tr[data-version="2"]')
    assert _definition()[0] == 2
    assert _definition(2)[1]["fields"][1]["label"] == "借用數量"

    token = _login_token(client, requester)
    assert _record(no)["def_version"] == 1
    old_html = _output_html(client, token, no)
    assert "數量" in old_html and "借用數量" not in old_html, "舊單要照它當時的版本輸出"

    up.goto("%s/pages/custom-records.html?key=%s" % (live_server, KEY))
    up.wait_for_selector("#cr-new")
    up.click("#cr-new")
    up.fill("#cr-in-item", "筆電")
    up.fill("#cr-in-qty", "1")
    up.click("#cr-save")
    up.wait_for_selector('#cr-record[data-record-no]:not([data-record-no="%s"])' % no)
    no2 = up.get_attribute("#cr-record", "data-record-no")
    assert _record(no2)["def_version"] == 2
    assert up.inner_text("#cr-record-version") == "2"
    assert "借用數量" in _output_html(client, token, no2)

    up.goto("%s/pages/custom-records.html?key=%s&no=%s" % (live_server, KEY, no))
    up.wait_for_selector('#cr-record[data-record-no="%s"]' % no)
    assert up.inner_text("#cr-record-version") == "1"

    assert not errors, errors


@pytest.mark.e2e
def test_d4_builder_restores_an_old_version_as_a_new_one(live_server, make_user, new_context, client):
    """⑥ 可以還原到任一版：還原＝把舊版內容再發布成新版（歷史不改）。"""
    admin = make_user(username="p8_admin2", role="superadmin")
    token = _login_token(client, admin)
    h = {"Authorization": "Bearer " + token}
    body = {"name": "還原測試", "permission": "custom.%s" % KEY, "numbering": {"prefix": "RT", "date": "", "digits": 3},
            "fields": [{"key": "a", "label": "甲", "type": "text", "dataClass": "T1"}],
            "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿"}, {"key": "done", "label": "完成", "final": True}],
                         "transitions": [{"key": "go", "label": "完成", "from": "draft", "to": "done"}]}}
    for label in ("甲", "乙"):
        body["fields"][0]["label"] = label
        assert client.put("/api/definitions/custom_module/%s/draft" % KEY, json={"body": body}, headers=h).status_code == 200
        assert client.post("/api/definitions/custom_module/%s/publish" % KEY, json={}, headers=h).status_code == 200
    errors = []
    page = _page(new_context, live_server, admin, errors)
    page.goto("%s/pages/module-builder.html?key=%s" % (live_server, KEY))
    page.wait_for_selector("#mb-step-1", state="visible")
    _step(page, 6)
    page.click('[data-restore="1"]')
    page.click('[data-testid="ui-dialog-ok"]')
    page.wait_for_selector('#mb-versions tr[data-version="3"]')
    v, b = _definition()
    assert v == 3 and b["fields"][0]["label"] == "甲"
    assert _definition(2)[1]["fields"][0]["label"] == "乙", "還原不可以改歷史"
    assert not errors, errors
