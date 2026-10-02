"""31-A S7 瀏覽器端對端（一個檔、一個瀏覽器、一題連續流程）：派發卡片的審核操作與合併後的人話狀態。

流程：建草稿 → 新增視窗沒有狀態下拉 → 送審 → 審核中不能編輯／可撤回／外包總成本標「含待審核」 → 簽核人核准 →
「已送出」按鈕出現並可按 → （測試直接把列推到已驗收）→ 申請完工 → 完工審核中 → 簽核人核准 → 完工。
另有一筆舊單（approval_status=''）：顯示「舊單（未經審核）」徽章，作業按鈕照舊。
終點狀態以後端列為準（不只看畫面文字），每個階段留截圖：D:\\開發測試檔\\shots\\31a-*.png。
"""
import json
import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests._requires import requires_module  # noqa: E402
from tests.test_e2e_case_concurrent_edit_2026_09_24 import DATA_JS, _login  # noqa: F401

pytestmark = requires_module("case", "本檔的題讀寫 M01（案件）的資料與頁面")

NO = "MQ-DA-E2E-1"
SHOTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "logs", "e2e-shots", "wip-t31-dispatch-approval-2e")
OK = '[data-testid="ui-dialog-ok"]'


def _seed():
    import db
    from helpers import _set_setting
    now = "2026-10-01T00:00:00"
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "派發客", "派發案", 100, 95, json.dumps({"dealTag": "已成案", "caseRecord": {"payment": {"items": []}, "materials": []}}), now, now, "已成案"))
        conn.commit()
    finally:
        conn.close()
    _set_setting("unified_approval_flow", {"includeSubmitterManagerTier": False, "tiers": [
        {"order": 0, "approvers": [{"username": "da_e2e_ap", "displayName": "簽核人"}]}]})


def _row(did):
    import db
    c = db.get_db()
    try:
        return dict(c.execute("SELECT * FROM contractor_dispatches WHERE id=?", (did,)).fetchone())
    finally:
        c.close()


def _reload(page, want=1):
    """重新載入派發清單。頁面自己在切到分頁時也會載一次（較早發出、可能較晚回來而蓋掉我們的結果），所以：
    先等它載完，再載、確認筆數到位（量測用的同步點，不是產品行為）。"""
    for _ in range(8):
        page.wait_for_function(f"() => !{DATA_JS}.dispatchesLoading", timeout=10000)
        page.evaluate(f"async () => await {DATA_JS}.loadDispatches('{NO}')")
        if page.evaluate(f"() => {DATA_JS}.dispatches.length") >= want:
            page.wait_for_load_state("networkidle")
            return
        page.wait_for_timeout(300)
    raise AssertionError("派發清單載不到 %d 筆" % want)


def _shot(page, name):
    os.makedirs(SHOTS, exist_ok=True)          # repo 內（BK19 守門只准 repo／tmp）；跑完另外複製到 D:\開發測試檔\shots
    page.screenshot(path=os.path.join(SHOTS, "31a-%s.png" % name), full_page=False)


def _api(page, method, path, body=None, token=None):
    return page.evaluate("""async ([m, p, b, t]) => {
        const r = await fetch(p, {method: m, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + (t || """ + DATA_JS + """.session.token)}, body: b ? JSON.stringify(b) : undefined})
        let j = {}; try { j = await r.json() } catch (e) {}
        return {status: r.status, json: j}
    }""", [method, path, body, token])


@pytest.mark.e2e
def test_dispatch_card_review_flow(live_server, make_user, e2e_browser):
    import db
    adm = make_user(username="da_e2e_adm", role="admin")
    ap = make_user(username="da_e2e_ap", role="user")
    _seed()
    page = e2e_browser.new_context(viewport={"width": 1500, "height": 950}).new_page()
    _login(page, live_server, *adm)
    page.goto(f"{live_server}/pages/case-management.html?q={NO}")
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'", timeout=20000)
    page.evaluate(f"() => {{ {DATA_JS}.activeTab = 'dispatch' }}")
    page.wait_for_load_state("networkidle")          # 頁面自己的案件整包載入（含第一次派發清單）先落地，之後才動資料

    # 建一筆草稿（走 API：建立時狀態一律 draft；UI 建立流程由其他 e2e 蓋）
    r = _api(page, "POST", "/api/contractor-dispatches",
             {"quote_no": NO, "personnel_json": [{"id": 1, "name": "甲", "amount": 1000}], "items_json": [], "status": "completed"})
    assert r["status"] in (200, 201), r
    did = r["json"]["id"]
    assert _row(did)["status"] == "draft" and _row(did)["approval_status"] == "草稿"                  # 想偷設 completed 沒用
    _reload(page)
    badge = page.locator('[data-testid="dispatch-status"]').first
    badge.wait_for(timeout=10000)
    assert "草稿" in badge.inner_text()
    assert page.locator('[data-testid="dispatch-submit"]').first.is_visible()
    assert not page.locator('[data-testid="dispatch-sent"]').first.is_visible()                      # 未核准：不能往下推
    assert not page.locator('[data-testid="dispatch-legacy-badge"]').first.is_visible()
    # 回歸（2026-10-02 建包 e2e 偶發 detached）：同一案件重新載入不可以把卡片換掉——量「卡片元素重新載入後仍在 DOM、期間沒有被移除過」
    page.evaluate("""() => {
        const el = document.querySelector('[data-testid="dispatch-submit"]'); window.__card = el; window.__detached = 0
        new MutationObserver(() => { if (!window.__card.isConnected) window.__detached++ }).observe(document.body, {childList: true, subtree: true})
    }""")
    _reload(page)
    assert page.evaluate("() => window.__card.isConnected") is True and page.evaluate("() => window.__detached") == 0, "重新載入把卡片換掉了（清單先清空再填）"
    _shot(page, "1-draft")

    # 新增視窗：沒有狀態下拉
    page.evaluate(f"() => {DATA_JS}.openNewDispatch()")
    page.wait_for_selector('[data-testid="dispatch-form-scope"]', state="visible", timeout=10000)
    assert page.locator('select[x-model="dispatchForm.status"]').count() == 0
    _shot(page, "2-modal-no-status")
    page.evaluate(f"() => {{ {DATA_JS}.showDispatchModal = false }}")

    # 送審 → 審核中
    state = page.evaluate(f"() => ({{tab: {DATA_JS}.activeTab, n: {DATA_JS}.dispatches.length, modal: {DATA_JS}.showDispatchModal, "
                          f"btns: document.querySelectorAll('[data-testid=dispatch-submit]').length}})")
    assert state["btns"] >= 1, state
    page.locator('[data-testid="dispatch-submit"]').first.click()
    page.locator(OK).click()
    page.wait_for_function("() => ((document.querySelector('[data-testid=\"dispatch-status\"]') || {}).innerText || '').includes('派發審核中')", timeout=10000)
    row = _row(did)
    assert row["approval_status"] == "待審核" and row["status"] == "draft"
    assert page.locator('[data-testid="dispatch-edit"]').first.is_disabled()
    assert page.locator('[data-testid="dispatch-withdraw"]').first.is_visible()
    assert "含待審核 1 筆" in page.locator('[data-testid="dispatch-pending-note"]').first.inner_text()
    _shot(page, "3-pending")

    # 簽核人核准（簽核佇列頁另有自己的 e2e；這裡用同一支後端端點）
    tok = _api(page, "POST", "/api/auth/login", {"username": ap[0], "password": ap[1]})
    assert tok["status"] == 200, tok
    r = _api(page, "POST", f"/api/contractor-dispatches/{did}/approve", {}, token=tok["json"]["token"])
    assert r["status"] == 200 and r["json"]["approvalStatus"] == "已核准", r
    _reload(page)
    page.wait_for_selector('[data-testid="dispatch-sent"]', state="visible", timeout=10000)
    assert not page.locator('[data-testid="dispatch-pending-note"]').first.is_visible()
    _shot(page, "4-approved")
    page.locator('[data-testid="dispatch-sent"]').first.click()
    page.locator(OK).click()
    page.wait_for_function("() => ((document.querySelector('[data-testid=\"dispatch-status\"]') || {}).innerText || '').includes('已送出')", timeout=10000)
    assert _row(did)["status"] == "sent"

    # 把列推到已驗收（驗收人≠建立者的規則由後端題蓋；這裡只為了走到完工 UI）
    c = db.get_db()
    c.execute("UPDATE contractor_dispatches SET status='accepted', accepted_by='驗收人', accepted_at='2026-10-01T09:00:00' WHERE id=?", (did,))
    c.commit()
    c.close()
    _reload(page)
    page.wait_for_selector('[data-testid="dispatch-completion-request"]', state="visible", timeout=10000)
    _shot(page, "5-accepted")
    page.locator('[data-testid="dispatch-completion-request"]').first.click()
    page.locator(OK).click()
    page.wait_for_function("() => ((document.querySelector('[data-testid=\"dispatch-status\"]') || {}).innerText || '').includes('完工審核中')", timeout=10000)
    row = _row(did)
    assert row["completion_status"] == "待審核" and row["status"] == "accepted"
    assert page.locator('[data-testid="dispatch-completion-withdraw"]').first.is_visible()
    _shot(page, "6-completion-pending")
    r = _api(page, "POST", f"/api/contractor-dispatches/{did}/completion/approve", {}, token=tok["json"]["token"])
    assert r["status"] == 200, r
    _reload(page)
    page.wait_for_function("() => ((document.querySelector('[data-testid=\"dispatch-status\"]') || {}).innerText || '').includes('完工')", timeout=10000)
    assert _row(did)["status"] == "completed"
    assert not page.locator('[data-testid="dispatch-completion-request"]').first.is_visible()
    assert not page.locator('[data-testid="dispatch-cancel"]').first.is_visible()                    # 完工＝終態
    _shot(page, "7-completed")

    # 舊單：徽章＋作業按鈕照舊（不需要送審）
    c = db.get_db()
    c.execute("INSERT INTO contractor_dispatches (quote_no, dispatch_date, scope, items_json, personnel_json, total_amount, status, created_at, updated_at)"
              " VALUES (?,?,?,?,?,?,?,?,?)", (NO, "2026-01-01", "舊單", "[]", '[{"id":9,"name":"乙","amount":500}]', 0, "confirmed", "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
    c.commit()
    c.close()
    _reload(page, want=2)
    legacy = page.locator('[data-testid="dispatch-legacy-badge"]:visible')
    legacy.first.wait_for(timeout=10000)
    assert legacy.count() == 1                                                                       # 只有舊單那一張有（兩張卡裡另一張的徽章是隱藏的）
    assert page.locator('button:visible:has-text("待驗收")').count() == 1                             # 舊單照舊可往下推
    _shot(page, "8-legacy")

