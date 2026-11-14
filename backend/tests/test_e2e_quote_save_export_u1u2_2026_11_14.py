"""瀏覽器端對端：報價單存檔失敗與重複存檔／匯出（T86 U1／U2，2026-11-14）。

正式機：主檔 PUT 失敗 403 ×14、409 ×2（約 9%）；同人 10 分鐘內反覆存檔／匯出 PDF。根因（程式＋沙盒重現）：
- 已送出（非解鎖）／已駁回結案的單，表單仍可打字 → 60 秒後自動存檔送出必 403（靜默）；駁回結案的單甚至還有「儲存草稿」鈕。
- 內容沒變也能一直按「儲存草稿」→ 每次都是一筆 PUT＋稽核，更新時間往前跳。
- 衝突（409）只能「放棄我的修改重載」。
- 已送出單的匯出 PDF 每按一次就重產＋重記一次。

觀測點：頁面送出的 PUT／pdf-download／export 請求數、資料庫落地值、元件狀態（不打頁面文字）。
"""
import json
from datetime import datetime

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402

pytestmark = pytest.mark.e2e
ROOT = "Alpine.$data(document.querySelector('[x-data]'))"


def _db(sql, args=(), write=False):
    import db
    c = db.get_db()
    try:
        if write:
            c.execute(sql, args)
            c.commit()
            return []
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _seed(no, status):
    now = datetime.now().isoformat()
    data = {"quoteNo": no, "status": status, "dealTag": "", "customerName": "測試客戶", "projectName": "測試案", "caseRecord": {},
            "items": [{"id": 1, "type": "item", "description": "設備", "qty": 1, "unitPrice": 1000, "amount": 1000}]}
    _db("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, "
        "deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (no, status, "測試客戶", "測試案", 1000, 1000, json.dumps(data, ensure_ascii=False), now, now, "", "2026-11-14"), write=True)


def _open(live_server, e2e_browser, user, no):
    page = e2e_browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
    puts = []
    page.on("request", lambda r: puts.append(r.url) if r.method == "PUT" and f"/api/quotations/{no}" in r.url else None)
    inject_login(page, live_server, user[0], user[1])
    page.goto(f"{live_server}/pages/quotation-form.html?id={no}")
    page.wait_for_function(f"() => {ROOT}.q && {ROOT}.q.quoteNo === '{no}' && {ROOT}._lastUpdatedAt && {ROOT}.q.items && {ROOT}.q.items.length", timeout=20000)
    return page, puts


@pytest.mark.parametrize("status,expect_how", [("已送出", "解鎖編輯"), ("已拒絕", "駁回結案")])
def test_locked_status_shows_banner_hides_save_and_never_autosaves(live_server, make_user, e2e_browser, status, expect_how):
    u = make_user(username="u1_sa_" + ("a" if status == "已送出" else "b"), role="superadmin")
    no = "MQ-2611-91" + ("1" if status == "已送出" else "2")
    _seed(no, status)
    page, puts = _open(live_server, e2e_browser, u, no)
    page.locator('[data-testid="qf-status-lock-banner"]').wait_for(state="visible", timeout=10000)
    assert expect_how in page.locator('[data-testid="qf-status-lock-banner"]').inner_text()
    assert page.evaluate(f"() => {ROOT}.isStatusLocked()") is True
    # 鎖定狀態：setDirty 不標未儲存、不啟動自動存檔；直接呼叫 autoSave／saveDraft 也不送 PUT
    page.evaluate(f"() => {{ const d = {ROOT}; d.setDirty(); d.autoSave(); d.saveDraft() }}")
    page.wait_for_function(f"() => {ROOT}.isDirty === false", timeout=5000)
    page.wait_for_timeout(500)       # 等可能送出的請求（負向斷言：給請求一個流動的機會）
    assert puts == [], f"鎖定狀態不該送出 PUT：{puts}"
    assert not page.locator("button:has-text('儲存草稿')").first.is_visible(), "鎖定狀態沒有儲存鈕"


def test_unchanged_draft_does_not_resend_put_but_changed_draft_does(live_server, make_user, e2e_browser):
    u = make_user(username="u1_sa_c", role="superadmin")
    no = "MQ-2611-913"
    _seed(no, "草稿")
    page, puts = _open(live_server, e2e_browser, u, no)
    page.evaluate(f"() => {ROOT}.saveDraft()")                      # 沒改任何東西
    page.wait_for_function(f"() => {ROOT}.isDirty === false", timeout=5000)
    page.wait_for_timeout(500)
    assert puts == [], "內容沒變：不重複送 PUT"
    page.evaluate(f"() => {{ const d = {ROOT}; d.q.projectName = '改過的專案'; d.setDirty(); d.saveDraft() }}")
    page.wait_for_function("() => true")
    _wait_until(page, lambda: _db("SELECT project_name FROM quotations WHERE quote_no=?", (no,))[0]["project_name"] == "改過的專案", "存檔落地")
    assert len(puts) == 1
    # 存完又按一次（沒再改）：不再送
    page.evaluate(f"() => {ROOT}.saveDraft()")
    page.wait_for_timeout(500)
    assert len(puts) == 1, "存完沒再改，不該再送一次"


def _wait_until(page, fn, what, timeout=15000):
    waited = 0
    while waited < timeout:
        if fn():
            return
        page.wait_for_timeout(200)
        waited += 200
    raise AssertionError("逾時：" + what)


def test_conflict_keep_mine_replaces_only_untouched_fields(live_server, make_user, e2e_browser):
    u = make_user(username="u1_sa_d", role="superadmin")
    no = "MQ-2611-914"
    _seed(no, "草稿")
    page, puts = _open(live_server, e2e_browser, u, no)
    # 別人（資料庫直接改）在我載入之後把「公司名稱」改掉、更新時間往前
    data = json.loads(_db("SELECT data_json FROM quotations WHERE quote_no=?", (no,))[0]["data_json"])
    data["customerName"] = "對方改的客戶"
    _db("UPDATE quotations SET data_json=?, customer_name=?, updated_at=? WHERE quote_no=?",
        (json.dumps(data, ensure_ascii=False), "對方改的客戶", "2099-01-01T00:00:00", no), write=True)
    # 我改「專案名稱」，自動存檔撞 409 → 衝突橫幅
    page.evaluate(f"() => {{ const d = {ROOT}; d.q.projectName = '我改的專案'; d.setDirty(); d.autoSave() }}")
    page.locator('[data-testid="qf-save-conflict"]').wait_for(state="visible", timeout=10000)
    page.locator('[data-testid="qf-save-conflict-keep"]').click()
    page.wait_for_function(f"() => {ROOT}.q.customerName === '對方改的客戶' && !{ROOT}.saveConflictBanner", timeout=10000)
    st = page.evaluate(f"() => ({{ proj: {ROOT}.q.projectName, cust: {ROOT}.q.customerName, dirty: {ROOT}.isDirty }})")
    assert st["proj"] == "我改的專案", "我改過的欄位保留"
    assert st["cust"] == "對方改的客戶", "我沒動的欄位用最新的"
    assert st["dirty"] is True, "合併結果標成未儲存，由使用者確認後再存"
    # 確認後存檔：這次基準是最新版，不再 409
    page.evaluate(f"() => {ROOT}.autoSave()")
    _wait_until(page, lambda: _db("SELECT project_name FROM quotations WHERE quote_no=?", (no,))[0]["project_name"] == "我改的專案", "合併後存檔落地")
    assert _db("SELECT customer_name FROM quotations WHERE quote_no=?", (no,))[0]["customer_name"] == "對方改的客戶"


def test_export_pdf_reuses_same_version_without_regenerating_or_recounting(live_server, make_user, e2e_browser):
    u = make_user(username="u1_sa_e", role="superadmin")
    no = "MQ-2611-915"
    _seed(no, "已送出")
    page, _puts = _open(live_server, e2e_browser, u, no)
    calls = {"pdf": 0, "export": 0}

    def _pdf(route):
        calls["pdf"] += 1
        route.fulfill(status=200, content_type="application/pdf", body=b"%PDF-1.4 test")

    def _exp(route):
        calls["export"] += 1
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"export_count": calls["export"], "log": []}))
    page.route(f"**/api/quotations/{no}/pdf-download*", _pdf)
    page.route(f"**/api/quotations/{no}/export*", _exp)
    page.evaluate(f"() => {ROOT}.directExport()")
    page.wait_for_function(f"() => !{ROOT}.exporting && !!{ROOT}._pdfCache", timeout=10000)
    page.evaluate(f"() => {ROOT}.directExport()")
    page.wait_for_function(f"() => !{ROOT}.exporting", timeout=10000)
    page.wait_for_timeout(500)
    assert calls == {"pdf": 1, "export": 1}, f"同一版匯出第二次沿用上次的檔：{calls}"
    # 版本變了（最後更新時間不同）⇒ 重新產生
    page.evaluate(f"() => {{ {ROOT}._lastUpdatedAt = 'changed' }}")
    page.evaluate(f"() => {ROOT}.directExport()")
    _wait_until(page, lambda: calls["pdf"] == 2, "版本變了重新產生")
