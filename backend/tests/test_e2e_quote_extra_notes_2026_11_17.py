# -*- coding: utf-8 -*-
"""2026-11-17 e2e（真瀏覽器）：報價單表單「七、備註事項」＋範本。

1. 輸入備註 ⇒ 字數計數器即時更新；存檔後重新載入，內容（換行、縮排、空行）原樣回來。
2. 範本：框是空的 ⇒ 點範本直接套用；框內已有字 ⇒ 先問「取代／接在後面」，兩種選擇各自正確；取消不動內容。
3. 範本 ≤ 10 個不出現分類篩選與搜尋；> 10 個才出現，篩選與搜尋真的會縮小清單。
4. 只有最高管理者看得到「管理範本」；在管理視窗新增（含「以目前備註內容新增」）後儲存 ⇒ 打到 PUT、清單更新；未命名擋下。
"""
from tests._requires import requires_module  # noqa: E402
import json

import pytest
pytestmark = requires_module("case", "本檔打 M01（報價單）的表單頁與設定端點")

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect  # noqa: E402

ROOT = "Alpine.$data(document.querySelector('[x-data]'))"
NOTES = "備註事項：\n一、車體規格\n   - 車體尺寸：L1200\n\n九、結尾"


def _wait_form(page):
    page.wait_for_function(f"() => window.Alpine && document.querySelector('[x-data]') && {ROOT}.q && {ROOT}.session", timeout=20000)
    page.wait_for_function(f"() => {ROOT}.notesTpls !== undefined", timeout=5000)


def _token(client, user):
    r = client.post("/api/auth/login", json={"username": user[0], "password": user[1]})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _put_templates(client, h, n, prefix="範本"):
    tpls = [{"key": "", "name": f"{prefix}{i:02d}", "category": "AGV" if i % 2 else "監控", "text": f"{prefix}{i:02d} 內容\n  - 條列"} for i in range(n)]
    r = client.put("/api/settings/quote-notes-templates", headers=h, json={"templates": tpls})
    assert r.status_code == 200, r.text


@pytest.mark.e2e
def test_notes_typing_counter_and_roundtrip(client, live_server, make_user, new_page, login_as):
    u = make_user(username="xn_e2e_rt", role="admin")
    page = new_page()
    login_as(page, u)
    page.goto(live_server + "/pages/quotation-form.html")
    _wait_form(page)
    box = page.locator("[data-testid=qf-extra-notes]")
    assert box.get_attribute("maxlength") == "20000"
    assert "0 / 20000" in page.locator("[data-testid=qf-extra-notes-count]").inner_text()
    box.fill(NOTES)
    expect(page.locator("[data-testid=qf-extra-notes-count]")).to_contain_text(f"{len(NOTES)} / 20000")
    assert page.evaluate(f"() => {ROOT}.q.extraNotes") == NOTES

    page.evaluate(f"() => {{ const d = {ROOT}; d.q.customerName = '備註客戶'; d.q.projectName = '備註專案'; "
                  "d.q.items = [{id:1,type:'item',description:'設備',qty:1,cost:0,unitPrice:1000,amount:1000,margin:1}]; d.calcTotals() }")
    page.evaluate(f"() => {ROOT}.saveDraft ? {ROOT}.saveDraft() : {ROOT}.saveQuote()")
    page.wait_for_function(f"() => {ROOT}.q.quoteNo", timeout=15000)
    no = page.evaluate(f"() => {ROOT}.q.quoteNo")
    assert client.get(f"/api/quotations/{no}", headers=_token(client, u)).json()["data"]["extraNotes"] == NOTES, "存檔要把備註送到後端"

    page2 = new_page()
    login_as(page2, u)
    page2.goto(live_server + f"/pages/quotation-form.html?id={no}")
    _wait_form(page2)
    page2.wait_for_function(f"() => {ROOT}.q.quoteNo === '{no}'", timeout=15000)
    page2.wait_for_function(f"(n) => {ROOT}.q.extraNotes === n", arg=NOTES, timeout=10000)
    assert page2.locator("[data-testid=qf-extra-notes]").input_value() == NOTES


@pytest.mark.e2e
def test_template_apply_replace_append_cancel(client, live_server, make_user, new_page, login_as):
    sup = make_user(username="xn_e2e_tpl", role="superadmin")
    _put_templates(client, _token(client, sup), 2)
    page = new_page()
    login_as(page, sup)
    page.goto(live_server + "/pages/quotation-form.html")
    _wait_form(page)
    page.wait_for_function(f"() => {ROOT}.notesTpls.length === 2", timeout=8000)
    box = page.locator("[data-testid=qf-extra-notes]")
    page.locator("[data-testid=qf-notes-tpl-toggle]").click()
    items = page.locator("[data-testid=qf-notes-tpl-item]")
    expect(items).to_have_count(2)
    expect(page.locator("[data-testid=qf-notes-tpl-filter]")).not_to_be_visible()          # ≤10 個不出現篩選

    items.nth(0).click()                                         # 空框 ⇒ 直接套用、不問
    expect(box).to_have_value("範本00 內容\n  - 條列")
    expect(page.locator("[data-testid=qf-notes-tpl-ask]")).not_to_be_visible()

    items.nth(1).click()                                         # 有內容 ⇒ 先問
    ask = page.locator("[data-testid=qf-notes-tpl-ask]")
    ask.wait_for(state="visible", timeout=5000)
    expect(box).to_have_value("範本00 內容\n  - 條列")                          # 沒選之前內容不動
    page.locator("[data-testid=qf-notes-tpl-append]").click()
    expect(box).to_have_value("範本00 內容\n  - 條列\n\n範本01 內容\n  - 條列")
    ask.wait_for(state="hidden", timeout=5000)

    items.nth(0).click()
    page.locator("[data-testid=qf-notes-tpl-replace]").click()
    expect(box).to_have_value("範本00 內容\n  - 條列")

    items.nth(1).click()
    ask.get_by_text("取消").click()
    ask.wait_for(state="hidden", timeout=5000)
    assert box.input_value() == "範本00 內容\n  - 條列"


@pytest.mark.e2e
def test_template_filter_only_above_ten(client, live_server, make_user, new_page, login_as):
    sup = make_user(username="xn_e2e_flt", role="superadmin")
    _put_templates(client, _token(client, sup), 12)
    page = new_page()
    login_as(page, sup)
    page.goto(live_server + "/pages/quotation-form.html")
    _wait_form(page)
    page.wait_for_function(f"() => {ROOT}.notesTpls.length === 12", timeout=8000)
    page.locator("[data-testid=qf-notes-tpl-toggle]").click()
    page.locator("[data-testid=qf-notes-tpl-filter]").wait_for(state="visible", timeout=5000)
    expect(page.locator("[data-testid=qf-notes-tpl-item]")).to_have_count(12)
    page.locator("[data-testid=qf-notes-tpl-search]").fill("範本03")
    expect(page.locator("[data-testid=qf-notes-tpl-item]")).to_have_count(1)
    page.locator("[data-testid=qf-notes-tpl-search]").fill("")
    page.locator("[data-testid=qf-notes-tpl-filter] button", has_text="AGV").click()
    expect(page.locator("[data-testid=qf-notes-tpl-item]")).to_have_count(6)      # 奇數編號 6 個
    page.locator("[data-testid=qf-notes-tpl-filter] button", has_text="全部").click()
    expect(page.locator("[data-testid=qf-notes-tpl-item]")).to_have_count(12)


@pytest.mark.e2e
def test_manage_templates_superadmin_only_and_saves(client, live_server, make_user, new_page, login_as):
    sales = make_user(username="xn_e2e_sales", role="sales")
    p1 = new_page()
    login_as(p1, sales)
    p1.goto(live_server + "/pages/quotation-form.html")
    _wait_form(p1)
    assert not p1.locator("[data-testid=qf-notes-tpl-manage]").is_visible(), "非最高管理者看不到管理入口"

    sup = make_user(username="xn_e2e_mgr", role="superadmin")
    page = new_page()
    login_as(page, sup)
    page.goto(live_server + "/pages/quotation-form.html")
    _wait_form(page)
    page.locator("[data-testid=qf-extra-notes]").fill("要存成範本的內容\n  - 條列")
    page.locator("[data-testid=qf-notes-tpl-manage]").click()
    page.locator("[data-testid=qf-notes-mgr]").wait_for(state="visible", timeout=5000)
    page.get_by_text("以目前備註內容新增").click()
    row = page.locator("[data-testid=qf-notes-mgr-item]").first
    expect(row.locator("textarea")).to_have_value("要存成範本的內容\n  - 條列")

    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    page.locator("[data-testid=qf-notes-mgr-save]").click()                       # 沒命名 ⇒ 擋下、不打 API
    page.wait_for_timeout(300)
    assert dialogs and "名稱" in dialogs[0], dialogs
    assert client.get("/api/settings/quote-notes-templates", headers=_token(client, sup)).json()["templates"] == []

    row.locator("input").first.fill("我的範本")
    with page.expect_response(lambda r: r.url.endswith("/settings/quote-notes-templates") and r.request.method == "PUT") as ri:
        page.locator("[data-testid=qf-notes-mgr-save]").click()
    assert ri.value.status == 200
    page.locator("[data-testid=qf-notes-mgr]").wait_for(state="hidden", timeout=5000)
    saved = client.get("/api/settings/quote-notes-templates", headers=_token(client, sup)).json()["templates"]
    assert [(t["name"], t["text"]) for t in saved] == [("我的範本", "要存成範本的內容\n  - 條列")]
    assert page.evaluate(f"() => {ROOT}.notesTpls.length") == 1


# ── 規格文件面板（B 段前端；端點由 quotation_specs 提供，這裡用攔截的假回應只驗畫面行為）──────────────

SPECS = [
    {"id": "s1", "name": "規格甲.pdf", "path": "quotation_specs/x/s1.pdf", "size": 2048, "pages": 3, "status": "ok"},
    {"id": "s2", "name": "規格乙.pdf", "path": "quotation_specs/x/s2.pdf", "size": 3 * 1048576, "pages": 12, "status": "ok"},
    {"id": "s3", "name": "加密.pdf", "path": "quotation_specs/x/s3.pdf", "size": 1000, "pages": 0, "status": "encrypted"},
]


def _saved_quote_page(client, live_server, make_user, new_page, login_as, username, specs=None):
    u = make_user(username=username, role="admin")
    h = _token(client, u)
    r = client.post("/api/quotations", headers=h, json={"status": "草稿", "data": {
        "customerName": "規格客戶", "projectName": "規格專案", "quoteDate": "2026-11-17", "items": [{"description": "品項"}],
        "tot": {"total": 1000, "pretax": 952, "directMarginPct": 0, "netMarginPct": 0}}})
    assert r.status_code == 201, r.text
    no = r.json()["quote_no"]
    page = new_page()
    login_as(page, u)
    page._xn_user = u
    if specs is not None:                       # 頁面會在載入／刷新時用單筆 GET 的 specFiles 覆蓋清單：在回應裡注入，畫面才不會被清掉
        def _inject(route):
            resp = route.fetch()
            try:
                body = resp.json()
                body["specFiles"] = specs
                route.fulfill(response=resp, json=body)
            except Exception:
                route.fulfill(response=resp)
        page.route(f"**/api/quotations/{no}", _inject)
    page.goto(live_server + f"/pages/quotation-form.html?id={no}")
    _wait_form(page)
    page.wait_for_function(f"() => {ROOT}.q.quoteNo === '{no}' && !{ROOT}.isNewRecord", timeout=15000)
    # quoteNo／isNewRecord 在單筆 GET 回來「之前」就設好了；GET 完成才會設 _lastUpdatedAt（同一段會覆寫 specFiles）。
    # 沒等它，上傳／注入的清單可能被晚到的初次載入清掉（整檔跑時偶發）。
    page.wait_for_function(f"() => !!{ROOT}._lastUpdatedAt", timeout=15000)
    return page, no


@pytest.mark.e2e
def test_spec_panel_select_reorder_and_warnings(client, live_server, make_user, new_page, login_as):
    page, no = _saved_quote_page(client, live_server, make_user, new_page, login_as, "xn_e2e_spec1", specs=SPECS)
    rows = page.locator("[data-testid=qf-spec-row]")
    rows.first.wait_for(state="visible", timeout=5000)
    assert rows.count() == 3
    warn = page.locator("[data-testid=qf-spec-warn]:visible")
    assert warn.count() == 1 and "已加密" in warn.inner_text()
    assert "3 頁" in rows.nth(0).inner_text() and "3.0 MB" in rows.nth(1).inner_text()

    rows.nth(0).locator("[data-testid=qf-spec-check]").check()
    rows.nth(1).locator("[data-testid=qf-spec-check]").check()
    assert page.evaluate(f"() => {ROOT}.q.mergeFiles") == ["s1", "s2"], "勾選順序＝合併順序"
    page.locator("[data-testid=qf-spec-down]").first.click()                      # s1 往後 ⇒ s2, s1
    page.wait_for_function(f"() => JSON.stringify({ROOT}.q.mergeFiles) === '[\"s2\",\"s1\"]'", timeout=3000)
    assert page.evaluate(f"() => {ROOT}.specRows.map(f => f.id)") == ["s2", "s1", "s3"], "已勾選的依合併順序排前面"
    page.locator("[data-testid=qf-spec-up]").nth(1).click()                       # s1 往前 ⇒ s1, s2
    page.wait_for_function(f"() => JSON.stringify({ROOT}.q.mergeFiles) === '[\"s1\",\"s2\"]'", timeout=3000)

    # 勾有問題的檔：要先確認；取消 ⇒ 不勾
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    page.locator("[data-testid=qf-spec-row]").nth(2).locator("[data-testid=qf-spec-check]").click()
    page.wait_for_timeout(200)
    assert dialogs and "已加密" in dialogs[0], dialogs
    assert page.evaluate(f"() => {ROOT}.q.mergeFiles") == ["s1", "s2"]


@pytest.mark.e2e
def test_spec_save_sends_merge_order_and_copy_to_new_drops_it(client, live_server, make_user, new_page, login_as):
    page, no = _saved_quote_page(client, live_server, make_user, new_page, login_as, "xn_e2e_spec2")
    page.evaluate(f"(s) => {{ const d = {ROOT}; d.specFiles = s; d.q.mergeFiles = ['s2','s1']; d.q.extraNotes = '複製要帶的備註'; }}", SPECS)
    # 複製為新單：備註文字帶、mergeFiles 不帶
    page.route("**/api/next-quote-no*", lambda route: route.fulfill(status=200, content_type="application/json", body='{"quote_no":""}'))
    page.evaluate(f"() => {ROOT}.copyToNew()")
    page.wait_for_function("() => sessionStorage.getItem('motrix_copy_template')", timeout=8000)
    tpl = json.loads(page.evaluate("() => sessionStorage.getItem('motrix_copy_template')"))
    assert tpl["extraNotes"] == "複製要帶的備註"
    assert "mergeFiles" not in tpl and "specFiles" not in tpl, tpl.keys()


@pytest.mark.e2e
def test_spec_upload_delete_update_list_and_keep_selection(client, live_server, make_user, new_page, login_as, tmp_path):
    page, no = _saved_quote_page(client, live_server, make_user, new_page, login_as, "xn_e2e_spec3")
    calls = []

    def _upload(route):
        calls.append(("POST", route.request.url))
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"specFiles": SPECS[:2], "mergeFiles": []}))

    def _delete(route):
        calls.append(("DELETE", route.request.url))
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"specFiles": SPECS[1:2], "mergeFiles": []}))

    page.route(f"**/api/quotations/{no}/spec-files", _upload)
    page.route(f"**/api/quotations/{no}/spec-files/s1", _delete)
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF")
    page.locator("[data-testid=qf-spec-input]").set_input_files(str(pdf))
    page.wait_for_function(f"() => {ROOT}.specFiles.length === 2", timeout=5000)
    assert calls and calls[0][0] == "POST"
    page.evaluate(f"() => {{ {ROOT}.q.mergeFiles = ['s2','s1'] }}")
    page.on("dialog", lambda d: d.accept())
    page.locator("[data-testid=qf-spec-row]").filter(has_text="規格甲.pdf").locator("[data-testid=qf-spec-delete]").click()
    page.wait_for_function(f"() => {ROOT}.specFiles.length === 1", timeout=5000)
    assert page.evaluate(f"() => {ROOT}.q.mergeFiles") == ["s2"], "刪掉的檔從勾選移除，其餘勾選保留"
    assert [c[0] for c in calls] == ["POST", "DELETE"]

    # 非 PDF 在前端就擋（不打 API）
    txt = tmp_path / "x.txt"
    txt.write_text("hi")
    msgs = []
    page.on("dialog", lambda d: msgs.append(d.message))
    page.locator("[data-testid=qf-spec-input]").set_input_files(str(txt))
    page.wait_for_timeout(300)
    assert any("PDF" in m for m in msgs) and len(calls) == 2


@pytest.mark.e2e
def test_download_shows_which_spec_files_were_skipped(client, live_server, make_user, new_page, login_as):
    page, no = _saved_quote_page(client, live_server, make_user, new_page, login_as, "xn_e2e_spec4")
    import urllib.parse
    skipped = urllib.parse.quote(json.dumps([{"id": "s3", "name": "加密.pdf", "reason": "encrypted"}], ensure_ascii=False))
    page.route(f"**/api/quotations/{no}/pdf-download*", lambda route: route.fulfill(
        status=200, content_type="application/pdf", body=b"%PDF-1.4\n%%EOF", headers={"X-Pdf-Merge-Skipped": skipped,
                                                                                      "Access-Control-Expose-Headers": "X-Pdf-Merge-Skipped"}))
    msgs = []
    page.on("dialog", lambda d: (msgs.append(d.message), d.dismiss()))
    page.evaluate(f"() => {ROOT}._downloadServerPdf('external')")
    page.wait_for_timeout(800)
    assert msgs and "加密.pdf" in msgs[0] and "已加密" in msgs[0], msgs


# ── 解鎖編輯（最高管理者）可上傳／刪除規格文件：暫存、待刪標示、儲存才生效、放棄回原狀（真後端）──────────────

def _unlock_world(live_server, make_user, e2e_browser, username):
    from tests.test_e2e_review_edit_lock_2026_11_11 import NO as LNO, _open_form, _seed, _set_mode
    from tests.test_e2e_superadmin_approver_edit_entry_2026_11_13 import _UNLOCK_PW, _set_unlock_password
    from tests._e2e_login import inject_login
    u, p = make_user(username=username, role="superadmin", modules=["quotation"])
    _set_unlock_password(u)
    _set_mode(2)
    _seed([u])
    _make_submittable(u, username + "_mgr", make_user)
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    _open_form(page, live_server)
    return page, LNO, _UNLOCK_PW


def _make_submittable(u, mgr_name, make_user):
    """解鎖存檔會重送簽核：送審人要有部門與部門主管（種子單的送審人改成這位最高管理者本人）。"""
    import db
    from tests.test_e2e_review_edit_lock_2026_11_11 import NO as LNO
    make_user(username=mgr_name, role="admin", modules=["quotation"])
    c = db.get_db()
    try:
        cur = c.execute("INSERT INTO divisions (name, sort_order, created_at) VALUES (?,?,?)", ("規格測試處" + u, 0, "2026-11-17T00:00:00"))
        cur = c.execute("INSERT INTO departments (division_id, name, sort_order, created_at) VALUES (?,?,?,?)", (cur.lastrowid, "規格測試部" + u, 0, "2026-11-17T00:00:00"))
        dept = cur.lastrowid
        mid = c.execute("SELECT id FROM users WHERE username=?", (mgr_name,)).fetchone()[0]
        c.execute("UPDATE departments SET manager_user_id=? WHERE id=?", (mid, dept))
        c.execute("UPDATE users SET department_id=? WHERE username IN (?,?)", (dept, u, mgr_name))
        d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (LNO,)).fetchone()[0])
        d["approval"]["requestedBy"] = u
        c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), LNO))
        c.commit()
    finally:
        c.close()


def _do_unlock(page, pw):
    page.click('[data-testid="qf-unlock-edit"]')
    page.fill('input[placeholder="输入解鎖密碼"]'.replace("输", "輸"), pw)
    page.get_by_role("button", name="確認解鎖").click()
    page.wait_for_selector('[data-testid="qf-unlocked-banner"]', state="visible", timeout=10000)


def _server_specs(no):
    import db
    c = db.get_db()
    try:
        row = c.execute("SELECT spec_files_json, data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()
    finally:
        c.close()
    specs = json.loads(row[0] or "[]")
    return [s for s in specs if not s.get("staged")], [s for s in specs if s.get("staged")], json.loads(row[1] or "{}")


def _pdf_file(tmp_path, name="解鎖規格.pdf"):
    import io
    import pypdf
    w = pypdf.PdfWriter()
    w.add_blank_page(width=200, height=200)
    b = io.BytesIO()
    w.write(b)
    f = tmp_path / name
    f.write_bytes(b.getvalue())
    return str(f)


@pytest.mark.e2e
def test_unlock_edit_upload_is_staged_and_relock_discards_it(live_server, make_user, e2e_browser, tmp_path):
    page, no, pw = _unlock_world(live_server, make_user, e2e_browser, "xn_ul_a")
    assert page.evaluate(f"() => {ROOT}.specLocked()") is True, "鎖定時規格面板不可操作"
    _do_unlock(page, pw)
    assert page.evaluate(f"() => {ROOT}.specLocked()") is False
    page.locator("[data-testid=qf-spec-input]").set_input_files(_pdf_file(tmp_path))
    page.wait_for_function(f"() => {ROOT}.specStaged.length === 1", timeout=10000)
    row = page.locator("[data-testid=qf-spec-row]").first
    row.wait_for(state="visible", timeout=5000)
    assert row.get_attribute("data-spec-state") == "staged"
    row.locator("[data-testid=qf-spec-staged-badge]").wait_for(state="visible", timeout=5000)   # 整合：x-show 比 data-spec-state 晚一個影格，不能立刻 is_visible()
    live, staged, _data = _server_specs(no)
    assert live == [] and len(staged) == 1, "暫存檔不進生效清單"
    page.once("dialog", lambda d: d.accept())
    page.click('[data-testid="qf-discard-unlock-edit"]')   # 整合（t88-int）：「重新鎖定」改為先儲存再鎖（fix/quote-relock-saves）；捨棄暫存／待刪走「放棄修改」
    page.wait_for_function(f"() => !{ROOT}.unlocked && {ROOT}.specStaged.length === 0", timeout=10000)
    assert page.locator("[data-testid=qf-spec-row]").count() == 0
    page.wait_for_timeout(300)
    live, staged, _data = _server_specs(no)
    assert live == [] and staged == [], "放棄後暫存檔與紀錄都清掉"


@pytest.mark.e2e
def test_unlock_edit_save_applies_staged_and_pending_delete(live_server, make_user, e2e_browser, tmp_path):
    page, no, pw = _unlock_world(live_server, make_user, e2e_browser, "xn_ul_b")
    _do_unlock(page, pw)
    page.locator("[data-testid=qf-spec-input]").set_input_files(_pdf_file(tmp_path, "甲.pdf"))
    page.wait_for_function(f"() => {ROOT}.specStaged.length === 1", timeout=10000)
    sid = page.evaluate(f"() => {ROOT}.specStaged[0].id")
    page.locator("[data-testid=qf-spec-check]").first.check()
    assert page.evaluate(f"() => {ROOT}.q.mergeFiles") == [sid]
    page.locator('[data-testid="qf-unlocked-banner"]').get_by_role("button", name="儲存修改").click()
    page.wait_for_function(f"() => !{ROOT}.unlocked && {ROOT}.specStaged.length === 0 && {ROOT}.specFiles.length === 1", timeout=15000)
    live, staged, data = _server_specs(no)
    assert [s["id"] for s in live] == [sid] and staged == [] and data.get("mergeFiles") == [sid]
    assert "_specChanges" not in data and "_isUnlockEdit" not in data, "解鎖旗標與異動清單不存進單據"
    row = page.locator("[data-testid=qf-spec-row]").first
    assert row.get_attribute("data-spec-state") == "ok"
    # 第二次解鎖：標待刪 → 還原 → 再標待刪 → 放棄 → 回原狀 → 再標待刪 → 儲存才真的刪
    _do_unlock(page, pw)
    page.once("dialog", lambda d: d.accept())
    page.locator("[data-testid=qf-spec-delete]").first.click()
    page.wait_for_function(f"() => {ROOT}.specPendingDelete.length === 1", timeout=5000)
    row = page.locator("[data-testid=qf-spec-row]").first
    assert row.get_attribute("data-spec-state") == "deleting"
    row.locator("[data-testid=qf-spec-deleting-badge]").wait_for(state="visible", timeout=5000)   # 整合：同上（x-show 晚一個影格）
    assert page.evaluate(f"() => {ROOT}.q.mergeFiles") == [], "待刪的檔不再送勾選"
    assert _server_specs(no)[0], "標待刪不打 API，伺服器上檔案還在"
    row.locator("[data-testid=qf-spec-restore]").click()
    page.wait_for_function(f"() => {ROOT}.specPendingDelete.length === 0", timeout=5000)
    page.once("dialog", lambda d: d.accept())
    page.locator("[data-testid=qf-spec-delete]").first.click()
    page.wait_for_function(f"() => {ROOT}.specPendingDelete.length === 1", timeout=5000)
    page.once("dialog", lambda d: d.accept())
    page.click('[data-testid="qf-discard-unlock-edit"]')   # 整合（t88-int）：「重新鎖定」改為先儲存再鎖（fix/quote-relock-saves）；捨棄暫存／待刪走「放棄修改」
    page.wait_for_function(f"() => !{ROOT}.unlocked && {ROOT}.specPendingDelete.length === 0", timeout=10000)
    assert page.evaluate(f"() => {ROOT}.q.mergeFiles") == [sid], "放棄修改後勾選回到原狀"
    assert page.locator("[data-testid=qf-spec-row]").first.get_attribute("data-spec-state") == "ok"
    _do_unlock(page, pw)
    page.once("dialog", lambda d: d.accept())
    page.locator("[data-testid=qf-spec-delete]").first.click()
    page.locator('[data-testid="qf-unlocked-banner"]').get_by_role("button", name="儲存修改").click()
    page.wait_for_function(f"() => !{ROOT}.unlocked && {ROOT}.specFiles.length === 0", timeout=15000)
    live, staged, data = _server_specs(no)
    assert live == [] and "mergeFiles" not in data
    import db
    c = db.get_db()
    try:
        acts = [r[0] for r in c.execute("SELECT action FROM audit_log WHERE username=?", ("xn_ul_b",)).fetchall()]
    finally:
        c.close()
    assert "quotation.apply_spec_changes" in acts, acts


@pytest.mark.e2e
def test_other_field_save_keeps_merge_files(client, live_server, make_user, new_page, login_as):
    """update 是整份 data 覆蓋：規格面板每次存檔都要帶目前的 mergeFiles（改別的欄位再存檔，勾選不能被清掉）。"""
    page, no = _saved_quote_page(client, live_server, make_user, new_page, login_as, "xn_e2e_keep")
    import io
    import pypdf
    w = pypdf.PdfWriter()
    w.add_blank_page(width=200, height=200)
    b = io.BytesIO()
    w.write(b)
    h = _token(client, page._xn_user)
    r = client.post(f"/api/quotations/{no}/spec-files", headers=h, files=[("files", ("k.pdf", b.getvalue(), "application/pdf"))])
    assert r.status_code == 200, r.text
    sid = r.json()["specFiles"][0]["id"]
    page.reload()
    _wait_form(page)
    page.wait_for_function(f"() => {ROOT}.specFiles.length === 1", timeout=10000)
    page.locator("[data-testid=qf-spec-check]").first.check()
    page.get_by_role("button", name="儲存草稿").click()
    page.wait_for_function(f"() => !{ROOT}.isDirty", timeout=10000)
    page.fill("[data-testid=qf-extra-notes]", "只改備註")
    page.get_by_role("button", name="儲存草稿").click()
    page.wait_for_function(f"() => !{ROOT}.isDirty", timeout=10000)
    d = client.get(f"/api/quotations/{no}", headers=h).json()["data"]
    assert d.get("mergeFiles") == [sid] and d.get("extraNotes") == "只改備註"
