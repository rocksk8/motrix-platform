"""T86 業務開發 D（問題 12）案件管理這一側：成案的案件要標出「來自業務開發：○○商機」並連回去。

後端：`GET /api/quotations?with_dev_case=1` 每列多一個 `dev_case`（{id, name} 或 null）；`case-bundle` 的 `parts.devCase`。
可見性：管理員或有 dev_crm 模組、且依業務開發案自己的規則（row_access `dev_case`）看得到那件商機的人才有；其他人一律當作沒有。
前端：清單卡片與案件標題列的連結（`dev-crm.html?case=<id>`）。反向（業務開發 → 案件管理）用既有的 `case-management.html?q=<單號>`。
"""
import json

import pytest

from tests._e2e_login import inject_login  # noqa: E402

QNO, QNO2 = "MQ-DCRM-D1", "MQ-DCRM-D2"
NOW = "2026-11-14T00:00:00"


def _seed(creator_id=1):
    import db
    c = db.get_db()
    try:
        for q in (QNO, QNO2):
            c.execute("INSERT OR REPLACE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (q, "已送出", "商機客戶", "商機工程", 1000, 952, json.dumps({"dealTag": "已成案"}), NOW, NOW, "已成案"))
        c.execute("DELETE FROM dev_cases WHERE converted_quote_no IN (?,?)", (QNO, QNO2))
        c.execute("INSERT INTO dev_cases (case_name, customer_name, status, converted_quote_no, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                  ("智慧工廠監控商機", "商機客戶", "成案", QNO, creator_id, NOW, NOW))
        c.commit()
        return c.execute("SELECT id FROM dev_cases WHERE converted_quote_no=?", (QNO,)).fetchone()["id"]
    finally:
        c.close()


def _user_row(username):
    import db
    c = db.get_db()
    try:
        return dict(c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone())
    finally:
        c.close()


def _hdr(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_list_and_bundle_carry_the_source_dev_case_for_admins(client, make_user):
    u, p = make_user("dcrm_admin", "Conn-Pass-123", role="superadmin")[:2]
    did = _seed()
    h = _hdr(client, u, p)
    items = client.get("/api/quotations?deal_tag=已成案&with_dev_case=1&limit=50", headers=h).json()["items"]
    by = {i["quote_no"]: i for i in items}
    assert by[QNO]["dev_case"] == {"id": did, "name": "智慧工廠監控商機"}
    assert by[QNO2]["dev_case"] is None, "沒有來源商機的案件是 null，不是缺鍵"
    plain = client.get("/api/quotations?deal_tag=已成案&limit=50", headers=h).json()["items"]
    assert all("dev_case" not in i for i in plain), "沒要求就不多欄位（舊呼叫端不變）"
    b = client.get("/api/quotations/%s/case-bundle" % QNO, headers=h).json()
    assert b["parts"]["devCase"] == {"ok": True, "data": {"id": did, "name": "智慧工廠監控商機"}}
    b2 = client.get("/api/quotations/%s/case-bundle" % QNO2, headers=h).json()
    assert b2["parts"]["devCase"] == {"ok": True, "data": None}


def test_dev_case_name_is_not_leaked_to_users_who_cannot_see_that_opportunity(make_user, client):
    from modules.case.api.quotations import _dev_case_map
    import db
    make_user("dcrm_plain", "Conn-Pass-123", role="sales")
    make_user("dcrm_crm_other", "Conn-Pass-123", role="sales", modules=["dev_crm"])
    make_user("dcrm_crm_owner", "Conn-Pass-123", role="sales", modules=["dev_crm"])
    plain, other, owner = (_user_row(n) for n in ("dcrm_plain", "dcrm_crm_other", "dcrm_crm_owner"))
    admin = make_user("dcrm_adm2", "Conn-Pass-123", role="admin")
    did = _seed(creator_id=owner["id"])
    conn = db.get_db()
    try:
        assert _dev_case_map(conn, _user_row("dcrm_adm2"), [QNO]) == {QNO: {"id": did, "name": "智慧工廠監控商機"}}
        assert _dev_case_map(conn, plain, [QNO]) == {}, "沒有業務開發模組權限 ⇒ 看不到"
        assert _dev_case_map(conn, other, [QNO]) == {}, "有模組但不是那件商機的建立者／業務／企劃／被指派人 ⇒ 看不到"
        assert _dev_case_map(conn, owner, [QNO]) == {QNO: {"id": did, "name": "智慧工廠監控商機"}}
        assert _dev_case_map(conn, owner, []) == {}
    finally:
        conn.close()
    assert admin is not None


@pytest.mark.e2e
def test_case_page_shows_the_source_link_on_card_and_header(live_server, make_user, e2e_browser):
    u, p = make_user(username="dcrm_e2e", role="superadmin")[:2]
    did = _seed()
    page = e2e_browser.new_page(viewport={"width": 1440, "height": 900})
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/case-management.html")
    card_link = page.locator('[data-testid="cm-card-devcase"]')
    card_link.first.wait_for(state="visible", timeout=20000)
    assert card_link.count() == 1, "只有來自商機的那一件有標示"
    assert card_link.first.inner_text() == "來自業務開發：智慧工廠監控商機"
    assert card_link.first.get_attribute("href") == f"dev-crm.html?case={did}"
    page.goto(f"{live_server}/pages/case-management.html?q={QNO}")
    head = page.locator('[data-testid="cm-header-devcase"]')
    head.wait_for(state="visible", timeout=20000)
    assert head.get_attribute("href") == f"dev-crm.html?case={did}"
    assert "智慧工廠監控商機" in head.inner_text()
    page.goto(f"{live_server}/pages/case-management.html?q={QNO2}")
    page.wait_for_selector(f"text={QNO2}", timeout=20000)
    page.wait_for_timeout(500)
    assert page.locator('[data-testid="cm-header-devcase"]').count() == 0
    page.set_viewport_size({"width": 390, "height": 900})
    page.goto(f"{live_server}/pages/case-management.html?q={QNO}")
    page.locator('[data-testid="cm-header-devcase"]').wait_for(state="visible", timeout=20000)
    over = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert over <= 1, "手機不可橫向捲動（超出 %s px）" % over
