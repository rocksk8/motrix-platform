"""傳票：帶入來源移到分錄下方（左案件、右已上傳檔案），點檔案跳預覽、確認才帶入；附件顯示縮圖。

使用者（2026-09-25，以示意圖確認版型 A，取代 4963170 的右側面板）：
「改到頁面科目的下方左邊顯示案件名稱可點選、右邊顯示已上傳檔案，點選已上傳檔案的時候跳出預覽這張照片的
 視窗做確認是否帶入，在附件的時候也顯示預覽圖」。
預覽視窗：大圖置中、◀ ▶ 切換同案其他檔案、下方案件單號與上傳日期、「取消」「帶入附件」、右上 ✕；
附件區縮圖點開同一視窗（只看不帶入）。鍵盤比照 MotrixUI：Esc 關、焦點鎖在視窗內。
觀測點：實際位置（getBoundingClientRect）、DOM、attachments 落地筆數。
"""
import json
import os

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402

QNO = "MQ-VCSRC-01"
D = "Alpine.$data(document.querySelector('[x-data]'))"
FILES = [("s1", "現場照片一.png", "2026-09-20T10:00:00"), ("s2", "現場照片二.png", "2026-09-21T11:30:00")]


def _png(color):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (60, 40), color).save(buf, format="PNG")
    return buf.getvalue()


def _seed(client, u):
    import db
    from helpers.uploads import UPLOADS_ROOT
    metas = []
    for i, (fid, name, at) in enumerate(FILES):
        rel = "vcsrc/%s.png" % fid
        full = os.path.join(UPLOADS_ROOT, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(_png((40 * i, 120, 200)))
        metas.append({"id": fid, "filename": name, "path": rel, "mime": "image/png", "uploadedAt": at})
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
                     " created_at, updated_at, deal_tag, signed_files_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (QNO, "已送出", "來源客戶", "來源專案", 1000, 952, "{}", "2026-01-01T00:00:00",
                      "2026-01-01T00:00:00", "已成案", json.dumps(metas)))
        conn.commit()
    finally:
        conn.close()
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u[0], "password": u[1]}).json()["token"]}
    r = client.post("/api/vouchers", headers=h, json={"summary": "來源", "lines": [
        {"account_code": "6111", "debit": 1000, "credit": 0, "summary": "第一行"},
        {"account_code": "1113", "debit": 0, "credit": 1000, "summary": "付現"}]})
    assert r.status_code == 200, r.text[:300]
    return r.json()["id"]


def _rendered(page):
    page.evaluate("() => new Promise(r => Alpine.nextTick(() => requestAnimationFrame(() => requestAnimationFrame(r))))")


def _open(browser, base, u, vid, width=1440, height=900):
    ctx = browser.new_context(viewport={"width": width, "height": height})
    page = ctx.new_page()
    inject_login(page, base, u[0], u[1])
    page.goto(f"{base}/pages/voucher.html?id={vid}")
    page.wait_for_function(f"() => {{ try {{ return {D}.id == {vid} && {D}.canEdit && {D}.sourcesLoaded }} catch (e) {{ return false }} }}",
                           timeout=20000)
    page.locator('[data-testid="src-block"]').wait_for(state="visible", timeout=5000)
    return page


def _pick_case(page):
    page.locator("textarea[x-model='l.summary']").nth(0).click()
    page.click(f'[data-testid="src-case"]:has-text("{QNO}")')
    page.locator('[data-testid="src-file"]').nth(1).wait_for(state="visible", timeout=10000)
    _rendered(page)


def _box(page, sel):
    return page.evaluate("""s => { const e = document.querySelector(s); if (!e) return null; const b = e.getBoundingClientRect();
        return { l: b.left, t: b.top, r: b.right, b: b.bottom } }""", sel)


@pytest.mark.e2e
def test_the_block_sits_below_the_lines_cases_left_files_right(live_server, make_user, e2e_browser, client):
    u = make_user(username="vcsrc_layout", role="superadmin")
    vid = _seed(client, u)
    page = _open(e2e_browser, live_server, u, vid)
    _pick_case(page)
    lines, block = _box(page, "table.vc-lines"), _box(page, '[data-testid="src-block"]')
    left, right = _box(page, '[data-testid="src-cases"]'), _box(page, '[data-testid="src-files"]')
    mid = _box(page, '[data-testid="src-expenses"]')
    assert block["t"] >= lines["b"], ("來源區塊要在分錄下方", lines, block)
    # 📌 2026-09-25 使用者：「案件、支出項、已上傳檔案這三個並排由左到右」⇒ 三欄（原本兩欄、支出項在案件下方）
    assert left["r"] <= mid["l"] + 1 and mid["r"] <= right["l"] + 1, ("寬螢幕要三欄由左到右", left, mid, right)
    picked = page.locator('[data-testid="src-case"].on')
    assert picked.count() == 1 and QNO in picked.inner_text() and "來源客戶" in picked.inner_text()
    assert "▶" in picked.inner_text(), "選中的案件要標 ▶"
    # 縮圖在檔案清單之後非同步載入（每張一個請求）⇒ 等它真的出現，不在清單一出來就數
    page.wait_for_function("() => document.querySelectorAll('[data-testid=src-file] img').length === 2",
                           timeout=10000)
    assert page.evaluate(f"() => {D}.lines[0].summary").find("來源客戶") >= 0, "點案件：目前這一行摘要改成案件名稱"
    # 舊的右側並排（4963170）已移除
    assert page.evaluate("() => !document.querySelector('.vc-body--split')")


@pytest.mark.e2e
def test_clicking_a_file_previews_it_and_only_bring_in_adds_the_attachment(live_server, make_user, e2e_browser, client):
    u = make_user(username="vcsrc_preview", role="superadmin")
    vid = _seed(client, u)
    page = _open(e2e_browser, live_server, u, vid)
    _pick_case(page)
    pv = page.locator('[data-testid="voucher-att-preview"]')
    page.locator('[data-testid="src-file"]').nth(0).click()
    pv.wait_for(state="visible", timeout=5000)
    page.locator('[data-testid="voucher-att-preview-img"]').wait_for(state="visible", timeout=5000)
    foot = page.locator('[data-testid="att-pv-meta"]').inner_text()
    assert QNO in foot and "2026-09-20" in foot, foot
    title = page.locator('[data-testid="voucher-att-preview"] .modal-head__title').inner_text()
    assert "現場照片一" in title
    page.click('[data-testid="att-pv-next"]')
    page.wait_for_function("() => document.querySelector('[data-testid=voucher-att-preview] .modal-head__title').innerText.includes('現場照片二')")
    assert "2026-09-21" in page.locator('[data-testid="att-pv-meta"]').inner_text()
    page.click('[data-testid="att-pv-prev"]')
    page.wait_for_function("() => document.querySelector('[data-testid=voucher-att-preview] .modal-head__title').innerText.includes('現場照片一')")
    # 取消 ⇒ 不帶入
    page.click('[data-testid="att-pv-cancel"]')
    pv.wait_for(state="hidden", timeout=5000)
    assert page.evaluate(f"() => {D}.attachments.length") == 0, "取消卻帶入了"
    # 帶入 ⇒ 附件多一筆，且有縮圖
    page.locator('[data-testid="src-file"]').nth(0).click()
    pv.wait_for(state="visible", timeout=5000)
    page.click('[data-testid="att-pv-bring"]')
    pv.wait_for(state="hidden", timeout=5000)
    page.wait_for_function(f"() => {D}.attachments.length === 1", timeout=10000)
    page.locator('[data-testid="voucher-att-thumb"]').first.wait_for(state="visible", timeout=10000)
    assert page.locator('[data-testid="src-file"]').nth(0).locator('[data-testid="src-file-brought"]').is_visible(), \
        "已帶入的檔案要標示"


@pytest.mark.e2e
def test_an_attachment_thumbnail_opens_the_same_preview_without_bring_in(live_server, make_user, e2e_browser, client):
    u = make_user(username="vcsrc_att", role="superadmin")
    vid = _seed(client, u)
    page = _open(e2e_browser, live_server, u, vid)
    _pick_case(page)
    page.locator('[data-testid="src-file"]').nth(1).click()
    page.click('[data-testid="att-pv-bring"]')
    page.locator('[data-testid="voucher-att-thumb"]').first.wait_for(state="visible", timeout=10000)
    page.locator('[data-testid="voucher-att-thumb"]').first.click()
    pv = page.locator('[data-testid="voucher-att-preview"]')
    pv.wait_for(state="visible", timeout=5000)
    page.locator('[data-testid="voucher-att-preview-img"]').wait_for(state="visible", timeout=5000)
    assert page.locator('[data-testid="att-pv-bring"]').count() == 0 or not page.locator('[data-testid="att-pv-bring"]').is_visible(), \
        "附件區只看不帶入"


@pytest.mark.e2e
def test_the_preview_follows_motrix_ui_keyboard_rules(live_server, make_user, e2e_browser, client):
    u = make_user(username="vcsrc_keys", role="superadmin")
    vid = _seed(client, u)
    page = _open(e2e_browser, live_server, u, vid)
    _pick_case(page)
    page.locator('[data-testid="src-file"]').nth(0).click()
    pv = page.locator('[data-testid="voucher-att-preview"]')
    pv.wait_for(state="visible", timeout=5000)
    inside = "() => !!document.activeElement && !!document.activeElement.closest('[data-testid=voucher-att-preview]')"
    page.wait_for_function(inside, timeout=3000)
    for _ in range(8):                              # 焦點鎖：Tab 繞一圈仍在視窗內
        page.keyboard.press("Tab")
        assert page.evaluate(inside), "Tab 跑出了預覽視窗"
    page.keyboard.press("Shift+Tab")
    assert page.evaluate(inside)
    page.keyboard.press("Escape")
    pv.wait_for(state="hidden", timeout=5000)
    assert page.evaluate(f"() => {D}.attachments.length") == 0, "Esc 等同取消，不可以帶入"


@pytest.mark.e2e
def test_a_file_used_by_another_voucher_is_marked_and_says_which(live_server, make_user, e2e_browser, client):
    """`JV18`（頁籤區拿掉後改在這裡）：已被其他傳票帶入的檔案標紅字「已計算」，點它看是哪一張；只標不擋。"""
    u = make_user(username="vcsrc_used", role="superadmin")
    vid = _seed(client, u)
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u[0], "password": u[1]}).json()["token"]}
    other = client.post("/api/vouchers", headers=h, json={"summary": "另一張", "lines": [
        {"account_code": "6111", "debit": 10, "credit": 0}, {"account_code": "1113", "debit": 0, "credit": 10}]}).json()
    files = client.get(f"/api/vouchers/line-source-files?source_type=case&ref={QNO}", headers=h).json()["files"]
    f0 = [f for f in files if f["filename"] == FILES[0][1]][0]
    r = client.post(f"/api/vouchers/{other['id']}/attachments", headers=h,
                    json={"picks": [{"type": f0["type"], "docNo": f0["docNo"], "fileId": f0["fileId"]}]})
    assert r.status_code == 200, r.text[:300]
    page = _open(e2e_browser, live_server, u, vid)
    _pick_case(page)
    tile = page.locator(f'[data-testid="src-file"]:has-text("{FILES[0][1]}")')
    used = tile.locator('[data-testid="src-file-used"]')
    used.wait_for(state="visible", timeout=5000)
    assert "已計算" in used.inner_text()
    used.click()
    info = tile.locator('[data-testid="src-file-usedinfo"]')
    info.wait_for(state="visible", timeout=5000)
    assert other["voucher_no"] in info.inner_text(), info.inner_text()
    assert not page.locator('[data-testid="voucher-att-preview"]').is_visible(), "點「已計算」不應該打開預覽"
    other_tile = page.locator(f'[data-testid="src-file"]:has-text("{FILES[1][1]}")')
    assert other_tile.locator('[data-testid="src-file-used"]').is_hidden(), "沒被用過的不可以標已計算"
    # 只標不擋：仍然可以預覽並帶入
    tile.locator(".vc-srcblk__name").click()
    page.click('[data-testid="att-pv-bring"]')
    page.wait_for_function(f"() => {D}.attachments.length === 1", timeout=10000)


@pytest.mark.e2e
@pytest.mark.parametrize("width,stacked", [(1024, False), (768, True), (390, True)])
def test_narrow_screens_stack_the_two_columns_without_horizontal_overflow(live_server, make_user, e2e_browser, client,
                                                                         width, stacked):
    """三欄或上下排看**區塊本身**的寬度（< 700px 上下排）：傳票紙面有最大寬度，1024 與 1440 時區塊一樣寬
    （實測 783px，內容 753px），三欄（最小約 608px）放得下；視窗再窄（約 < 920px）區塊才縮，768 時 586px ⇒ 上下排。
    任何寬度都不可橫向溢出。"""
    u = make_user(username="vcsrc_%d" % width, role="superadmin")
    vid = _seed(client, u)
    page = _open(e2e_browser, live_server, u, vid, width=width, height=800)
    _pick_case(page)
    left, right = _box(page, '[data-testid="src-cases"]'), _box(page, '[data-testid="src-files"]')
    mid = _box(page, '[data-testid="src-expenses"]')
    if stacked:
        assert mid["t"] >= left["b"] - 1 and right["t"] >= mid["b"] - 1, ("%d 寬要上下排" % width, left, mid, right)
    else:
        assert left["r"] <= mid["l"] + 1 and mid["r"] <= right["l"] + 1, ("%d 寬三欄放得下" % width, left, mid, right)
    sw, vw = page.evaluate("() => [document.documentElement.scrollWidth, innerWidth]")
    assert sw <= vw, "頁面橫向溢出：%s > %s" % (sw, vw)


@pytest.mark.e2e
@pytest.mark.parametrize("width", [1440, 1024])
def test_the_three_columns_sit_side_by_side_from_the_same_top(live_server, make_user, e2e_browser, client, width):
    """使用者（2026-09-25）：「傳票，案件、支出項、已上傳檔案這三個並排由左到右，方便點選跟查閱」。
    三欄由左到右、同一高度起始，1024 寬不橫向溢出。"""
    u = make_user(username="vcsrc3_%d" % width, role="superadmin")
    vid = _seed(client, u)
    page = _open(e2e_browser, live_server, u, vid, width=width, height=900)
    _pick_case(page)
    cols = [_box(page, '[data-testid="%s"]' % t) for t in ("src-cases", "src-expenses", "src-files")]
    assert all(cols), cols
    assert cols[0]["r"] <= cols[1]["l"] + 1 and cols[1]["r"] <= cols[2]["l"] + 1, ("三欄要由左到右", cols)
    tops = [c["t"] for c in cols]
    assert max(tops) - min(tops) < 2, ("三欄要同一高度起始", tops)
    heads = page.evaluate("""() => ['src-cases','src-expenses','src-files'].map(t =>
        document.querySelector('[data-testid=' + t + '] .vc-src__hint').innerText)""")
    assert heads[0].startswith("案件") and heads[1].startswith("支出項") and heads[2].startswith("已上傳檔案"), heads
    sw, vw = page.evaluate("() => [document.documentElement.scrollWidth, innerWidth]")
    assert sw <= vw, "頁面橫向溢出：%s > %s" % (sw, vw)
