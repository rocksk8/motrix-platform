# -*- coding: utf-8 -*-
"""第 49 班 e2e：可見範圍收緊後各頁對『一般角色』仍正常。

- 案件管理頁（載入時會呼叫 /api/contractors/selectable）：只有業務模組（quotation）的案件擁有者 ⇒ 不送這個請求、沒有 403 紅字、頁面照常；
  case_manage 人員 ⇒ 照常取得外包名冊（派發下拉可用）；最高管理者照常。
- 網路規劃書清單頁：沒有該案權限的規劃書使用者只看到獨立（未綁案件）的規劃書，看不到綁案件的那份。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

NO = "MQ-VIS49-001"
ROOT = "Alpine.$data(document.querySelector('[x-data]'))"
T0 = "2026-03-01T09:00:00"


def _seed(owner):
    import db
    c = db.get_db()
    try:
        c.execute("INSERT INTO contractors (name, id_number, phone, active, created_at, updated_at) VALUES ('名冊甲','A123456789','0912000111',1,?,?)", (T0, T0))
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, quote_date, sales_person)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (NO, "已送出", "客戶", "專案", 105000, 100000, json.dumps({"dealTag": "已成案"}), T0, T0, "已成案", "2026-03-01", owner))
        c.commit()
    finally:
        c.close()


def _open_case_page(page, live_server, user):
    seen, errors = [], []
    page.on("request", lambda r: seen.append(r.url))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    inject_login(page, live_server, user[0], user[1])
    page.goto("%s/pages/case-management.html" % live_server)
    page.wait_for_function("() => { const d = %s; return d && d.session && d.session.token && !d.loading && d.caseCounts }" % ROOT, timeout=30000)
    page.wait_for_selector(".cm-card[data-quote-no='%s']" % NO, timeout=30000)
    page.wait_for_timeout(800)          # loadVendors 在頁面初始化時呼叫，給它一點時間
    return seen, errors


@pytest.fixture()
def users(make_user):
    plain = make_user(username="vis49_plain", role="user", modules=["quotation", "dashboard"], legacy_finance_flag=False)
    cm = make_user(username="vis49_cm", role="user", modules=["quotation", "case_manage"], legacy_finance_flag=False)
    sa = make_user(username="vis49_sa", role="superadmin")
    _seed(cm[0])                                     # 案件歸 case_manage 人員（案件管理頁本來就要求 case_manage 模組）
    return plain, cm, sa


@pytest.mark.e2e
def test_quotation_only_user_cannot_open_the_case_page_so_no_roster_request_is_ever_sent(live_server, users, new_context):
    """盤點結論：案件管理頁需要 case_manage 模組（沒有就顯示『沒有這個頁面的權限』），所以外包名冊 selectable 的唯一前端呼叫者
    不會被只有 quotation 的角色觸發；收緊後沒有任何角色的頁面壞掉。"""
    plain, _cm, _sa = users
    page = new_context(viewport={"width": 1440, "height": 1000}).new_page()
    seen = []
    page.on("request", lambda r: seen.append(r.url))
    inject_login(page, live_server, plain[0], plain[1])
    page.goto("%s/pages/case-management.html" % live_server)
    page.wait_for_selector("text=你沒有這個頁面的權限", timeout=20000)
    page.wait_for_timeout(500)
    assert not [u for u in seen if "/api/contractors/selectable" in u], seen


@pytest.mark.e2e
def test_case_page_for_case_manage_and_superadmin_still_loads_the_roster(live_server, users, new_context):
    _plain, cm, sa = users
    for user in (cm, sa):
        page = new_context(viewport={"width": 1440, "height": 1000}).new_page()
        seen, errors = _open_case_page(page, live_server, user)
        assert [u for u in seen if "/api/contractors/selectable" in u], user[0]
        assert page.evaluate("() => %s.contractorRoster.map(c => c.name)" % ROOT) == ["名冊甲"], user[0]
        assert not [e for e in errors if "403" in e], errors


@pytest.mark.e2e
def test_client_guard_skips_the_request_for_a_session_without_roster_modules(live_server, users, new_context):
    """前端防線：session 沒有任何允許的模組 ⇒ loadVendors 不送請求、名冊為空（後端本來就會 403）。"""
    _plain, cm, _sa = users
    page = new_context(viewport={"width": 1440, "height": 1000}).new_page()
    _open_case_page(page, live_server, cm)
    seen = []
    page.on("request", lambda r: seen.append(r.url))
    page.evaluate("() => { const d = %s; d.session = { ...d.session, role: 'user', modules: ['quotation'] }; d.contractorRoster = [{id: 1}]; return d.loadVendors() }" % ROOT)
    page.wait_for_timeout(300)
    assert not [u for u in seen if "/api/contractors/selectable" in u], seen
    assert page.evaluate("() => %s.contractorRoster.length" % ROOT) == 0


@pytest.mark.e2e
def test_network_plans_list_hides_the_case_bound_plan_from_a_user_without_case_access(live_server, make_user, client, new_context):
    sa = make_user(username="vis49_np_sa", role="superadmin")
    out = make_user(username="vis49_np_out", role="sales", modules=["netplan", "netplan_edit", "dashboard"], legacy_finance_flag=False)
    import db
    c = db.get_db()
    try:
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at, sales_person) VALUES (?,?,?,?,?,?,?,?)",
                  ("MQ-VIS49-NP", "已送出", "客", "案", "{}", T0, T0, "someone_else"))
        c.commit()
    finally:
        c.close()
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": sa[0], "password": sa[1]}).json()["token"]}
    assert client.post("/api/network-plans", headers=h, json={"quoteNo": "MQ-VIS49-NP", "siteName": "綁案件的規劃"}).status_code == 201
    assert client.post("/api/network-plans", headers=h, json={"siteName": "獨立的規劃"}).status_code == 201
    page = new_context(viewport={"width": 1440, "height": 1000}).new_page()
    inject_login(page, live_server, out[0], out[1])
    page.goto(live_server + "/pages/network-plans.html")
    page.wait_for_selector("text=獨立的規劃", timeout=20000)
    assert page.locator("text=綁案件的規劃").count() == 0
