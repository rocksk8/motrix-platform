"""兩支含金額的 PDF 加財務檢查（CM15，2026-09-24 使用者裁示）。

closing-report-pdf（結案報表：成本、毛利、收款）與 pdf-download?internal=true（內部版：成本）
過去只看擁有者／case_manage／簽核人，沒有財務檢查。規則＝money_visible()（CM13：can_see_financial
或 cashier 模組）或本單簽核人（使用者：「簽核人可以」）。對外版 pdf-download 不在範圍內。
斷言只看「是不是被權限擋下（403）」——PDF 產生本身在測試環境可能因字型等原因回 5xx，與權限無關。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json

import pytest
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')

NO = "MQ-PDFG-001"


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _uid(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[0]
    finally:
        conn.close()


def _seed(assigned=(), requested_by=None, deal_tag="已結案"):
    import db
    data = {"dealTag": deal_tag, "items": [{"desc": "x", "qty": 1, "cost": 10, "unitPrice": 20, "amount": 20}],
            "caseRecord": {"payment": {"items": []}}}
    if requested_by:
        data["approval"] = {"requestedBy": requested_by}
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "客", "案", 21, 20, json.dumps(data, ensure_ascii=False), now, now, deal_tag,
             json.dumps([_uid(u) for u in assigned])))
        conn.commit()
    finally:
        conn.close()


CLOSING = f"/api/quotations/{NO}/closing-report-pdf"
INTERNAL = f"/api/quotations/{NO}/pdf-download?internal=true"
EXTERNAL = f"/api/quotations/{NO}/pdf-download"


@pytest.mark.parametrize("url", [CLOSING, INTERNAL])
def test_member_without_money_view_is_403(client, make_user, url):
    u = make_user(username="pg_eng", role="engineer")
    _seed(assigned=[u[0]])
    r = client.get(url, headers=_login(client, *u))
    assert r.status_code == 403, r.text


@pytest.mark.parametrize("url", [CLOSING, INTERNAL])
def test_approver_without_money_view_is_allowed(client, make_user, url):
    u = make_user(username="pg_appr", role="engineer")
    _seed(requested_by="pg_appr")
    r = client.get(url, headers=_login(client, *u))
    assert r.status_code != 403, r.text


@pytest.mark.parametrize("role,modules", [("sales", None), ("engineer", ["case_manage", "financial_view"]),
                                          ("engineer", ["case_manage", "cashier"])])
@pytest.mark.parametrize("url", [CLOSING, INTERNAL])
def test_money_visible_members_are_allowed(client, make_user, url, role, modules):
    u = make_user(username="pg_ok", role=role, modules=modules)
    _seed(assigned=[u[0]])
    r = client.get(url, headers=_login(client, *u))
    assert r.status_code != 403, r.text


def test_external_pdf_unchanged_for_member_without_money_view(client, make_user):
    u = make_user(username="pg_ext", role="engineer")
    _seed(assigned=[u[0]])
    r = client.get(EXTERNAL, headers=_login(client, *u))
    assert r.status_code != 403, r.text
