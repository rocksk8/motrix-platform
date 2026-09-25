"""瀏覽器端對端：以案件為中心的獎金分潤頁（SPEC-BONUS §十一，2026-09-24）。

- 最高管理者：選案件 → 建立草稿（自動帶入業務／專案）→ 手動加後勤 → 改比率 → 儲存 → 金額照伺服器算 → 送審
- 名單上的人：待發放後只看到自己那一列；看不到淨利、獎金池、別人
- 出納：待發放時看得到整張金額並標記已發放；看不到淨利與比率（C1）
觀測點打在資料庫落地值與 API 回應，不打在頁面寫死的文字上。
"""
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")

import uvicorn
from tests._e2e_login import inject_login  # noqa: E402
from tests._ports import free_safe_port
from modules.payroll.tests._bonus_insure import insure_all  # noqa: E402

NO = "MQ-E2EBC-001"
DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"




def _login(page, base_url, username, password):
    inject_login(page, base_url, username, password)


def _seed(uid_sales, executor_display):
    import db
    data = {"dealTag": "已結案", "caseRecord": {"roles": {"executor": executor_display}},
            "settlement": {"status": "finalized", "summary": {"netProfit": 100000}}}
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at,"
            " updated_at, deal_tag, sales_person, sales_person_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "頁面客戶", "頁面專案", json.dumps(data, ensure_ascii=False),
             "2026-09-01", "2026-09-01", "已結案", "", uid_sales))
        conn.commit()
    finally:
        conn.close()


def _award():
    import db
    conn = db.get_db()
    try:
        a = conn.execute("SELECT * FROM bonus_case_awards WHERE quote_no=?", (NO,)).fetchone()
        lines = [dict(r) for r in conn.execute(
            "SELECT category, username, amount FROM bonus_case_award_lines WHERE award_id=? ORDER BY id",
            (a["id"],))] if a else []
        return (dict(a) if a else None), lines
    finally:
        conn.close()


def _users(make_user):
    import db
    out = {}
    # M1（使用者「任何登入者都能打開，內容照規則過濾」）：刻意**不給** reports／finance 模組——
    #    受獎人與出納多半沒有營運報表權限，他們也要打得開這一頁。
    eng = ["dashboard", "case_manage", "work_log", "daily_task"]
    for u, role, mods in (("pg_sa", "superadmin", None), ("pg_sa2", "superadmin", None),
                          ("pg_sales", "sales", None), ("pg_exec", "engineer", eng),
                          ("pg_admin", "engineer", eng), ("pg_cash", "engineer", ["cashier"]),
                          ("pg_out", "engineer", eng)):
        out[u] = make_user(username=u, role=role, modules=mods)
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET display_name='執行人員' WHERE username='pg_exec'")
        uid = conn.execute("SELECT id FROM users WHERE username='pg_sales'").fetchone()["id"]
        conn.commit()
    finally:
        conn.close()
    _seed(uid, "執行人員")
    return out


@pytest.mark.e2e
def test_superadmin_builds_draft_and_submits_in_page(live_server, make_user, e2e_browser):
    u = _users(make_user)
    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, *u["pg_sa"])
    page.goto(f"{live_server}/pages/bonus.html")
    card = page.locator(f'.bn-case[data-quote-no="{NO}"]')
    card.wait_for(timeout=20000)
    assert "已精算" in card.inner_text()
    card.click()
    page.locator('[data-testid="bn-create"]').click()
    page.locator('[data-testid="bn-draft"]').wait_for(timeout=15000)
    a, lines = _award()
    assert a["status"] == "草稿"
    assert {(l["category"], l["username"]) for l in lines} == {("sales", "pg_sales"), ("project", "pg_exec")}

    page.select_option('[data-testid="bn-add-admin"]', "pg_admin")
    page.locator('[data-testid="bn-add-admin"] + button').click()
    page.fill('[data-testid="bn-rate"]', "15")
    page.locator('[data-testid="bn-save"]').click()
    page.wait_for_function(f"() => {DATA_JS}.msg === '已儲存'", timeout=15000)
    a, lines = _award()
    assert a["rate_bp"] == 1500 and a["pool_amount"] == 15000
    assert {(l["category"], l["username"]): l["amount"] for l in lines} == {
        ("sales", "pg_sales"): 7500, ("project", "pg_exec"): 4500, ("admin", "pg_admin"): 3000}
    assert page.inner_text('[data-testid="bn-remainder"]').strip() == "NT$ 0"

    page.locator('[data-testid="bn-submit"]').click()
    page.wait_for_function(f"() => {DATA_JS}.msg === '已送審'", timeout=15000)
    assert _award()[0]["status"] == "待審核"
    assert "待審核" in page.inner_text('[data-testid="bn-status"]')


@pytest.mark.e2e
def test_member_sees_own_line_and_cashier_marks_paid(live_server, make_user, e2e_browser):
    u = _users(make_user)
    insure_all()   # U4：撥付前名單上每個人都要有投保金額（tests/_bonus_insure.py）
    browser = e2e_browser
    ctx = browser.new_context()
    page = ctx.new_page()

    def api_login(name):
        r = page.request.post(f"{live_server}/api/auth/login",
                              data={"username": name, "password": u[name][1]})
        return {"Authorization": "Bearer " + r.json()["token"]}
    sa, sa2 = api_login("pg_sa"), api_login("pg_sa2")
    assert page.request.post(f"{live_server}/api/bonus/cases/{NO}", headers=sa,
                             data={"members": {"sales": [{"username": "pg_sales"}],
                                               "project": [{"username": "pg_exec"}],
                                               "admin": [{"username": "pg_admin"}]}}).ok
    assert page.request.post(f"{live_server}/api/bonus/cases/{NO}/submit", headers=sa).ok
    assert page.request.post(f"{live_server}/api/bonus/cases/{NO}/approve", headers=sa2).ok

    # 名單上的人
    _login(page, live_server, *u["pg_exec"])
    page.goto(f"{live_server}/pages/bonus.html?q={NO}")
    page.locator('[data-testid="bn-view-project-pg_exec"]').wait_for(timeout=20000)
    assert "NT$ 3,000" in page.inner_text('[data-testid="bn-view-project-pg_exec"]')
    assert page.locator('[data-testid="bn-view-sales-pg_sales"]').count() == 0
    assert page.locator('[data-testid="bn-pool"]').count() == 0
    assert page.locator('[data-testid="bn-mark-paid"]').count() == 0

    # 出納
    page2 = browser.new_context().new_page()
    _login(page2, live_server, *u["pg_cash"])
    page2.goto(f"{live_server}/pages/bonus.html?q={NO}")
    page2.locator('[data-testid="bn-view-sales-pg_sales"]').wait_for(timeout=20000)
    assert page2.inner_text('[data-testid="bn-paid-total"]').strip() == "NT$ 10,000"
    assert page2.locator('[data-testid="bn-pool"]').is_hidden()
    page2.locator('[data-testid="bn-mark-paid"]').click()
    # AC3 起訊息後面會接「已產生傳票草稿 …」⇒ 比開頭
    page2.wait_for_function(f"() => ({DATA_JS}.msg || '').startsWith('已標記發放')", timeout=15000)
    a, _ = _award()
    assert a["status"] == "已發放" and a["paid_by"] == "pg_cash"


@pytest.mark.e2e
def test_outsider_without_finance_rights_sees_menu_entry_and_empty_state(live_server, make_user, e2e_browser):
    """M1：沒有任何財務權限、也不在名單上的人 ⇒ 選單「財務」分組只剩「獎金分潤」一項（分組不是空的），
    頁面打得開、顯示空狀態，不是「沒有權限」。"""
    u = _users(make_user)
    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, *u["pg_out"])
    page.goto(f"{live_server}/pages/bonus.html")
    page.locator('[data-testid="bn-empty"]').wait_for(timeout=20000)
    assert "目前沒有您的獎金分潤資料" in page.inner_text('[data-testid="bn-empty"]')
    assert "需要對應的模組權限" not in page.inner_text("body")
    links = page.evaluate("""() => [...document.querySelectorAll('a[href]')]
        .filter(a => /bonus\.html$/.test(a.getAttribute('href') || '')).length""")
    assert links >= 1, "選單要有「獎金分潤」入口"
    finance = page.evaluate("""() => {
        const out = []
        document.querySelectorAll('a[href]').forEach(a => {
          const h = a.getAttribute('href') || ''
          if (/(reports|cashier|voucher|account-items|bonus)\.html$/.test(h)) out.push(h.split('/').pop())
        })
        return [...new Set(out)]
    }""")
    print("M1 頁面實測：無財務權限者的財務類入口", finance)
    assert finance == ["bonus.html"], finance
