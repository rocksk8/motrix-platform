# -*- coding: utf-8 -*-
"""2026-11-11 e2e（真瀏覽器）：hichan-12 UX 評分 A 項＋「已成案」卡住（正式機 regression）。

A 項
- 申請人沒歸屬部門：按送審 ⇒ 前置檢查攔下（四步驟清單＋後端同一句中文），不開送審確認、不打送審 API；
  補好部門與主管後按「重新檢查」⇒ 放行（開出送審確認）。
- 前置檢查被繞過（例如查詢失敗）而後端 400：畫面要還原成原狀態（草稿）、彈窗顯示後端具體原因，
  不可再說「請確認後端伺服器是否在線」、也不可讓畫面停在「待審核」。
已成案
- 已送出的單由管理員選「已成案」：只打 PATCH /deal-tag（不整份 PUT ⇒ 不再 403 被擋），建 5 個階段，
  `_lastUpdatedAt` 與資料庫同步（之後整份存檔不會撞樂觀鎖 409）。
- 業務角色：下拉的「未成案／已成案」停用；硬呼叫 onDealTagChange 也在建階段「之前」就被擋下，不留殘餘階段。
"""
from tests._requires import requires_module  # noqa: E402
import json
import datetime as _dt

import pytest
pytestmark = requires_module("case", "本檔打 M01（案件）的報價單端點與頁面")

pytest.importorskip("playwright.sync_api")

ROOT = "Alpine.$data(document.querySelector('[x-data]'))"


def _db(sql, args=(), one=False, commit=False):
    import db
    conn = db.get_db()
    try:
        cur = conn.execute(sql, args)
        if commit:
            conn.commit()
            return cur.lastrowid
        return cur.fetchone() if one else cur.fetchall()
    finally:
        conn.close()


def _uid(username):
    return _db("SELECT id FROM users WHERE username=?", (username,), one=True)["id"]


def _org_with_manager(member_names, manager_name):
    """建處＋部門；成員歸屬進去、指定主管。回 department_id。"""
    now = _dt.datetime.now().isoformat(timespec="seconds")
    div = _db("INSERT INTO divisions (name, sort_order, created_at) VALUES (?,?,?)", ("e2e處", 0, now), commit=True)
    dept = _db("INSERT INTO departments (division_id, name, sort_order, manager_user_id, created_at) VALUES (?,?,?,?,?)",
               (div, "e2e部", 0, _uid(manager_name), now), commit=True)
    for n in list(member_names) + [manager_name]:
        _db("UPDATE users SET department_id=? WHERE username=?", (dept, n), commit=True)
    return dept


def _fill_form(page, no_items=True):
    page.evaluate(f"""() => {{ const d = {ROOT}; d.q.customerName = '清楚度客戶'; d.q.projectName = '清楚度專案';
        d.q.items = [{{id: 1, type: 'item', description: '設備', qty: 1, cost: 0, unitPrice: 1000, amount: 1000, margin: 1}}];
        d.calcTotals() }}""")


def _wait_form(page):
    page.wait_for_function(f"() => window.Alpine && document.querySelector('[x-data]') && {ROOT}.q && {ROOT}.session", timeout=20000)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _api_login(client, name, pw):
    r = client.post("/api/auth/login", json={"username": name, "password": pw})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _quote_body(username):
    # 業務可見性看 salesPerson（顯示名稱）對得上自己；留空 ⇒ 業務自己也看不到這張單
    dn = _db("SELECT display_name FROM users WHERE username=?", (username,), one=True)["display_name"] or username
    return {
        "status": "待審核",
        "data": {
            "customerName": "已成案客戶", "projectName": "已成案專案", "salesPerson": dn, "quoteDate": "2026-11-11",
            "tot": {"total": 1000, "pretax": 952, "directMarginPct": 0, "netMarginPct": 0},
            "items": [{"description": "品項 A", "amount": 1000}],
            "approval": {"requestedBy": username, "status": "pending"},
        },
    }


def _sent_quote(client, sales, mgr):
    """業務送審 → 部門主管核准 ⇒ 已送出。回單號。（真實流程，不直接寫庫）"""
    st = _api_login(client, *sales)
    r = client.post("/api/quotations", json=_quote_body(sales[0]), headers=_auth(st))
    assert r.status_code == 201, r.text
    no = r.json()["quote_no"]
    mt = _api_login(client, *mgr)
    r = client.post(f"/api/quotations/{no}/approve", headers=_auth(mt), json={})
    assert r.status_code == 200, r.text
    assert _db("SELECT status FROM quotations WHERE quote_no=?", (no,), one=True)["status"] == "已送出"
    return no


# ───────────────────────────── A 項 ─────────────────────────────

@pytest.mark.e2e
def test_precheck_blocks_then_recheck_passes_after_setup(live_server, make_user, new_page, login_as):
    u = make_user(username="sc_nodept", role="sales")
    m = make_user(username="sc_mgr", role="admin")
    page = new_page()
    login_as(page, u)
    page.goto(live_server + "/pages/quotation-form.html")
    _wait_form(page)
    _fill_form(page)
    submit_calls = []
    page.on("request", lambda rq: submit_calls.append(rq.method + " " + rq.url) if "/api/quotations" in rq.url and rq.method in ("POST", "PUT") else None)

    page.evaluate(f"() => {ROOT}.submitQuote()")
    modal = page.locator("[data-testid=qf-precheck-modal]")
    modal.wait_for(state="visible", timeout=8000)
    text = modal.inner_text()
    assert "尚未歸屬任何部門" in text, text                       # 後端同一句話
    for label in ("建立「處」", "建立「部門」", "歸屬到某個部門", "指定在職主管"):
        assert label in text, (label, text)
    assert "目前處於此步驟" in text
    assert page.evaluate(f"() => {ROOT}.showSubmitModal") is False
    assert not submit_calls, submit_calls                          # 前置檢查階段不送審、不存檔
    assert page.evaluate(f"() => {ROOT}.q.status") in ("草稿", "", None)

    # 設定補齊（有部門＋有主管）→「重新檢查」放行
    _org_with_manager(["sc_nodept"], "sc_mgr")
    page.locator("[data-testid=qf-precheck-recheck]").click()
    page.wait_for_function(f"() => {ROOT}.showSubmitModal === true", timeout=8000)
    assert not modal.is_visible()


@pytest.mark.e2e
def test_failed_submit_restores_state_and_shows_backend_reason(live_server, make_user, new_page, login_as):
    u = make_user(username="sc_fail", role="sales")
    page = new_page()
    login_as(page, u)
    # 讓前置檢查「查不到」（模擬繞過）：直接放行，驗證送審失敗那一半
    page.route("**/api/quotations/submit-precheck", lambda route: route.fulfill(status=500, body="{}"))
    page.goto(live_server + "/pages/quotation-form.html")
    _wait_form(page)
    _fill_form(page)
    before = _db("SELECT COUNT(*) c FROM quotations", one=True)["c"]
    page.evaluate(f"() => {ROOT}.submitQuote()")
    page.wait_for_function(f"() => {ROOT}.showSubmitModal === true", timeout=8000)
    msgs = []
    page.on("dialog", lambda dl: (msgs.append(dl.message), dl.dismiss()))
    page.evaluate(f"() => {ROOT}.confirmSubmit()")
    page.wait_for_function(f"() => !{ROOT}.submitting", timeout=15000)
    assert msgs, "送審失敗必須有提示"
    assert "尚未歸屬任何部門" in msgs[0], msgs                      # 後端具體原因
    assert "後端伺服器是否在線" not in msgs[0], msgs
    assert "尚未送出" in msgs[0]
    st = page.evaluate(f"() => ({{status: {ROOT}.q.status, approval: {ROOT}.q.approval}})")
    assert st["status"] in ("草稿", "", None), st                     # 不再停在「待審核」
    assert not st["approval"] or st["approval"].get("status") != "pending", st
    assert _db("SELECT COUNT(*) c FROM quotations", one=True)["c"] == before


# ───────────────────────────── 已成案 ─────────────────────────────

@pytest.mark.e2e
def test_admin_marks_won_without_put_403_and_syncs_updated_at(client, live_server, make_user, new_page, login_as):
    sales = make_user(username="won_sales", role="sales")
    mgr = make_user(username="won_mgr", role="admin")
    adm = make_user(username="won_admin", role="admin")
    _org_with_manager(["won_sales"], "won_mgr")
    no = _sent_quote(client, sales, mgr)

    page = new_page()
    login_as(page, adm)
    page.goto(live_server + f"/pages/quotation-form.html?id={no}")
    _wait_form(page)
    page.wait_for_function(f"() => {ROOT}.q.status === '已送出' && {ROOT}._lastUpdatedAt", timeout=15000)
    loaded_at = page.evaluate(f"() => {ROOT}._lastUpdatedAt")
    reqs, dialogs = [], []
    page.on("request", lambda rq: reqs.append(rq.method + " " + rq.url.split("/api/")[-1]) if "/api/quotations/" in rq.url else None)
    page.on("dialog", lambda dl: (dialogs.append(dl.message), dl.accept()))
    page.locator("select[x-on\\:change], select").filter(has=page.locator("option[value='已成案']")).first.select_option("已成案")
    page.wait_for_function(f"() => (({ROOT}.q.caseRecord||{{}}).stages||[]).length === 5", timeout=20000)

    assert not any(r.startswith("PUT quotations/" + no) for r in reqs), reqs      # 不再整份 PUT
    assert any(r.startswith("PATCH ") and r.endswith("/deal-tag") or "/deal-tag" in r and r.startswith("PATCH") for r in reqs), reqs
    assert len(dialogs) == 1 and "已成案" in dialogs[0], dialogs                     # 只有「確認標記」那一個，沒有錯誤彈窗
    row = _db("SELECT deal_tag, updated_at FROM quotations WHERE quote_no=?", (no,), one=True)
    assert row["deal_tag"] == "已成案"
    assert _db("SELECT COUNT(*) c FROM case_stages WHERE quote_no=?", (no,), one=True)["c"] == 5
    # 階段長滿 5 個時，_refreshUpdatedAt 的 GET 可能還在路上：等前端基準離開載入時的舊值，再與資料庫比
    page.wait_for_function(f"(old) => {ROOT}._lastUpdatedAt && {ROOT}._lastUpdatedAt !== old", arg=loaded_at, timeout=10000)
    row = _db("SELECT deal_tag, updated_at FROM quotations WHERE quote_no=?", (no,), one=True)
    assert page.evaluate(f"() => {ROOT}._lastUpdatedAt") == row["updated_at"], "樂觀鎖基準要與資料庫同步"
    assert page.evaluate(f"() => {ROOT}.q.dealTag") == "已成案"


@pytest.mark.e2e
def test_sales_cannot_pick_won_and_leaves_no_residual_stages(client, live_server, make_user, new_page, login_as):
    sales = make_user(username="won2_sales", role="sales")
    mgr = make_user(username="won2_mgr", role="admin")
    _org_with_manager(["won2_sales"], "won2_mgr")
    no = _sent_quote(client, sales, mgr)

    page = new_page()
    login_as(page, sales)
    page.goto(live_server + f"/pages/quotation-form.html?id={no}")
    _wait_form(page)
    page.wait_for_function(f"() => {ROOT}.q.status === '已送出'", timeout=15000)
    sel = page.locator("select").filter(has=page.locator("option[value='已成案']")).first
    assert sel.locator("option[value='已成案']").is_disabled()
    assert sel.locator("option[value='未成案']").is_disabled()
    assert page.locator("[data-testid=qf-dealtag-admin-hint]").is_visible()
    # 硬呼叫（第二道）：要在建階段之前就擋下
    msgs = []
    page.on("dialog", lambda dl: (msgs.append(dl.message), dl.accept()))
    page.evaluate(f"() => {ROOT}.onDealTagChange('已成案')")
    page.wait_for_timeout(800)
    assert msgs and "管理員以上" in msgs[0], msgs
    assert page.evaluate(f"() => {ROOT}.q.dealTag") in ("", None, "未標記")
    assert _db("SELECT COUNT(*) c FROM case_stages WHERE quote_no=?", (no,), one=True)["c"] == 0
    assert (_db("SELECT deal_tag FROM quotations WHERE quote_no=?", (no,), one=True)["deal_tag"] or "") != "已成案"


@pytest.mark.e2e
def test_patch_failure_reverts_tag_shows_reason_and_creates_no_stages(client, live_server, make_user, new_page, login_as):
    """PATCH 被後端擋（這裡用攔截模擬 400）⇒ 退回舊值、顯示後端 detail，且**不建階段**。"""
    sales = make_user(username="won3_sales", role="sales")
    mgr = make_user(username="won3_mgr", role="admin")
    adm = make_user(username="won3_admin", role="admin")
    _org_with_manager(["won3_sales"], "won3_mgr")
    no = _sent_quote(client, sales, mgr)
    page = new_page()
    login_as(page, adm)
    page.route("**/deal-tag", lambda route: route.fulfill(status=400, content_type="application/json",
                                                           body=json.dumps({"detail": "測試用：後端拒絕這次變更"})))
    page.goto(live_server + f"/pages/quotation-form.html?id={no}")
    _wait_form(page)
    page.wait_for_function(f"() => {ROOT}.q.status === '已送出'", timeout=15000)
    msgs = []
    page.on("dialog", lambda dl: (msgs.append(dl.message), dl.accept()))
    page.locator("select").filter(has=page.locator("option[value='已成案']")).first.select_option("已成案")
    page.wait_for_function(f"() => {ROOT}.q.dealTag !== '已成案'", timeout=10000)
    page.wait_for_timeout(500)
    assert any("測試用：後端拒絕這次變更" in m for m in msgs), msgs
    assert _db("SELECT COUNT(*) c FROM case_stages WHERE quote_no=?", (no,), one=True)["c"] == 0
