"""瀏覽器端對端：獎金分潤改比例／人員即時重算、簽核中修改會作廢簽核（使用者 2026-09-25）。

觀測點：畫面上「存檔前」顯示的每人金額，與按下儲存後**資料庫**裡的金額逐人相等；
簽核是否作廢看資料庫 approval_json，不看頁面文字。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from modules.payroll.tests.test_e2e_bonus_case_page_2026_09_24 import _login  # noqa: E402,F401
from modules.payroll.tests.test_bonus_case_api_2026_09_24 import _seed_case, _set_flow, _auth, _login as _api_login  # noqa: E402
from tests._ui_dialogs import answer_confirm, forbid_native_dialogs  # noqa: E402

DATA = "Alpine.$data(document.querySelector('[x-data]'))"
PW = "Test-Pass-123"


def _db():
    import db
    return db.get_db()


def _award(no):
    conn = _db()
    try:
        a = dict(conn.execute("SELECT * FROM bonus_case_awards WHERE quote_no=?", (no,)).fetchone())
        a["appr"] = json.loads(a["approval_json"] or "{}")
        a["lines"] = {(r["category"], r["username"]): r["amount"] for r in conn.execute(
            "SELECT category, username, amount FROM bonus_case_award_lines WHERE award_id=?", (a["id"],))}
        return a
    finally:
        conn.close()


@pytest.fixture
def team(client, make_user):
    toks = {}
    for u, role in (("lr_sa", "superadmin"), ("lr_sa2", "superadmin"), ("lr_sa3", "superadmin"),
                    ("lr_s1", "sales"), ("lr_s2", "sales"), ("lr_p1", "engineer"), ("lr_p2", "engineer")):
        name, pw = make_user(username=u, role=role, password=PW)
        toks[u] = _api_login(client, name, pw)
    return toks


def _draft(client, team, no, net=123457):
    _seed_case(no, net=net)
    r = client.post("/api/bonus/cases/%s" % no, headers=_auth(team["lr_sa"]), json={"members": {
        "sales": [{"username": "lr_s1"}], "project": [{"username": "lr_p1"}, {"username": "lr_p2"}], "admin": []}})
    assert r.status_code == 200, r.text


def _open(page, base, no):
    _login(page, base, "lr_sa", PW)
    page.goto(f"{base}/pages/bonus.html?q={no}")
    page.wait_for_function(f"() => window.Alpine && {DATA} && {DATA}.detail && {DATA}.detail.quote_no !== null",
                           timeout=20000)


def _amt(page, cat, user):
    return page.locator('[data-testid="bn-amt-%s-%s"]' % (cat, user)).inner_text().strip()


def _wait_preview(page):
    page.wait_for_function(f"() => {DATA}.draft && !{DATA}.previewPending && ({DATA}.preview || {DATA}.previewError)",
                           timeout=10000)


def _money_to_int(t):
    return int(t.replace("NT$", "").replace(",", "").strip())


@pytest.mark.e2e
def test_changing_the_rate_updates_amounts_before_saving_and_saving_stores_them(live_server, client, team, e2e_browser):
    no = "MQ-LRE-001"
    _draft(client, team, no)
    browser = e2e_browser
    page = browser.new_context().new_page()
    dialogs = forbid_native_dialogs(page)
    puts = []
    page.on("request", lambda r: puts.append(r.url) if r.method == "PUT" else None)
    _open(page, live_server, no)
    page.wait_for_selector('[data-testid="bn-draft"]', timeout=10000)
    _wait_preview(page)
    before = _amt(page, "sales", "lr_s1")
    page.fill('[data-testid="bn-rate"]', "12")
    page.wait_for_function(f"() => {DATA}.preview && {DATA}.preview.pool === Math.floor(123457 * 1200 / 10000)",
                           timeout=10000)
    _wait_preview(page)
    after = _amt(page, "sales", "lr_s1")
    assert after != before, "改比率後金額要立即變（不必先存檔）"
    assert not puts, "還沒按儲存就送出了 PUT：%s" % puts
    shown = {(c, u): _money_to_int(_amt(page, c, u))
             for c, u in (("sales", "lr_s1"), ("project", "lr_p1"), ("project", "lr_p2"))}
    with page.expect_response(lambda r: r.request.method == "PUT" and "/api/bonus/cases/" in r.url):
        page.click('[data-testid="bn-save"]')
    a = _award(no)
    assert a["rate_bp"] == 1200
    assert {k: a["lines"][k] for k in shown} == shown, "畫面預覽的金額必須等於存下去的"
    assert not dialogs


@pytest.mark.e2e
def test_a_split_that_is_not_100_blocks_saving(live_server, client, team, e2e_browser):
    no = "MQ-LRE-002"
    _draft(client, team, no)
    browser = e2e_browser
    page = browser.new_context().new_page()
    _open(page, live_server, no)
    page.wait_for_selector('[data-testid="bn-draft"]', timeout=10000)
    page.fill('[data-testid="bn-split-sales"]', "60")
    page.wait_for_function(f"() => {DATA}.previewError", timeout=10000)
    assert "100%" in page.locator('[data-testid="bn-preview-error"]').inner_text()
    assert page.locator('[data-testid="bn-save"]').is_disabled()


@pytest.mark.e2e
def test_replacing_and_removing_people_recalculates(live_server, client, team, e2e_browser):
    no = "MQ-LRE-003"
    _draft(client, team, no)
    browser = e2e_browser
    page = browser.new_context().new_page()
    _open(page, live_server, no)
    page.wait_for_selector('[data-testid="bn-draft"]', timeout=10000)
    page.wait_for_function(f"() => ({DATA}.users || []).some(u => u.username === 'lr_s2')", timeout=10000)
    _wait_preview(page)
    page.select_option('[data-testid="bn-replace-sales-lr_s1"]', "lr_s2")
    page.wait_for_selector('[data-testid="bn-amt-sales-lr_s2"]', timeout=5000)
    page.click('[data-testid="bn-remove-project-lr_p2"]')
    page.wait_for_function(f"() => {DATA}.preview && {DATA}.preview.categories.project.lines.length === 1",
                           timeout=10000)
    _wait_preview(page)
    p1 = _money_to_int(_amt(page, "project", "lr_p1"))
    with page.expect_response(lambda r: r.request.method == "PUT" and "/api/bonus/cases/" in r.url):
        page.click('[data-testid="bn-save"]')
    a = _award(no)
    assert set(a["lines"]) == {("sales", "lr_s2"), ("project", "lr_p1")}
    assert a["lines"][("project", "lr_p1")] == p1, "專案剩一人 ⇒ 整類歸他，畫面與存檔一致"
    page.wait_for_selector('[data-testid="bn-log-edit"]', timeout=10000)
    assert "lr_s1" in page.locator('[data-testid="bn-log-edit"]').last.inner_text(), "變更紀錄要看得到前後名單"


@pytest.mark.e2e
def test_editing_in_review_warns_and_voids_signatures(live_server, client, team, e2e_browser):
    _set_flow(["lr_sa2"])
    conn = _db()
    try:
        conn.execute("UPDATE system_settings SET value_json=? WHERE key='bonus_approval_flow'", (json.dumps(
            {"includeSubmitterManagerTier": False, "tiers": [
                {"order": 0, "approvers": [{"username": "lr_sa2", "display_name": "lr_sa2"}]},
                {"order": 1, "approvers": [{"username": "lr_sa3", "display_name": "lr_sa3"}]}]}),))
        conn.commit()
    finally:
        conn.close()
    no = "MQ-LRE-004"
    _draft(client, team, no)
    assert client.post("/api/bonus/cases/%s/submit" % no, headers=_auth(team["lr_sa"])).status_code == 200
    assert client.post("/api/bonus/cases/%s/approve" % no, headers=_auth(team["lr_sa2"])).status_code == 200
    assert int(_award(no)["appr"]["currentTier"]) == 1
    browser = e2e_browser
    page = browser.new_context().new_page()
    dialogs = forbid_native_dialogs(page)
    _open(page, live_server, no)
    page.click('[data-testid="bn-edit"]')
    page.wait_for_selector('[data-testid="bn-resign-warn"]', state="visible", timeout=10000)
    _wait_preview(page)
    page.fill('[data-testid="bn-rate"]', "12")
    page.wait_for_function(f"() => {DATA}.preview && {DATA}.preview.pool === Math.floor(123457 * 1200 / 10000)",
                           timeout=10000)
    page.click('[data-testid="bn-save"]')
    answer_confirm(page, ok=False, expect="作廢")          # 取消 ⇒ 什麼都不改
    page.wait_for_timeout(300)
    assert int(_award(no)["appr"]["currentTier"]) == 1 and _award(no)["rate_bp"] == 1000
    page.click('[data-testid="bn-save"]')
    with page.expect_response(lambda r: r.request.method == "PUT" and "/api/bonus/cases/" in r.url):
        answer_confirm(page, ok=True, expect="作廢")
    a = _award(no)
    assert a["status"] == "待審核" and int(a["appr"]["currentTier"]) == 0 and a["rate_bp"] == 1200
    assert all(not x.get("approvedAt") for t in a["appr"]["tiers"] for x in t["approvers"])
    page.wait_for_selector('[data-testid="bn-log-reset_approvals"]', timeout=10000)
    assert not dialogs
