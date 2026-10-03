# -*- coding: utf-8 -*-
"""重新開啟精算的「理由」只給有財務檢視權限的人看（0c 稽核 should-fix）。

理由是自由文字（可能寫到金額、對帳細節），而 `editHistory` 會隨案件單筆 GET、修改紀錄端點回給所有看得到案件的人。
沿用 CM13 的遮蔽（`helpers/financial_mask.py`，條件 `money_visible()`）：沒有財務檢視的帳號拿到的歷程保留誰／何時／事件，**不含理由文字**。
這裡不只測一個端點：掃出「路徑帶案件單號」的**每一支 GET**，沒有財務檢視的帳號打過去，回應裡都不可以出現理由文字。
"""
import json
import re

import pytest

from tests._requires import requires_module

pytestmark = requires_module("case", "本檔的題打 M01（案件）的端點或讀寫 M01 的資料")

NO = "MQ-REASON-001"
SECRET = "機密理由XYZ金額99999"


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer %s" % r.json()["token"]}


def _seed(assigned_username):
    import db
    conn = db.get_db()
    try:
        uid = conn.execute("SELECT id FROM users WHERE username=?", (assigned_username,)).fetchone()[0]
        data = {
            "dealTag": "已成案", "items": [{"desc": "品項", "qty": 1, "cost": 100, "unitPrice": 200, "amount": 200}],
            "settlement": {"status": "draft", "items": [], "summary": {}},
            "editHistory": [
                {"rev": 1, "at": "2026-10-03T10:00:00", "by": "boss", "byDisplay": "老闆", "type": "settlement_finalized"},
                {"rev": 2, "at": "2026-10-04T09:00:00", "by": "boss", "byDisplay": "老闆", "type": "settlement_draft", "reason": SECRET, "from": "finalized"},
            ],
        }
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, assigned_user_ids)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "客", "案", 210, 200, json.dumps(data, ensure_ascii=False), "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", json.dumps([uid])))
        conn.commit()
    finally:
        conn.close()


def _case_get_routes(app):
    """路徑帶案件單號參數的 GET 路由（quote_no／no／quoteNo／case_no）。用 OpenAPI 清單取（新版 FastAPI 的 app.routes 是 include 包裝，走不到子路由）。"""
    pat = re.compile(r"\{(quote_no|no|quoteNo|case_no)(:[^}]*)?\}")
    out = set()
    for path, ops in app.openapi().get("paths", {}).items():
        if "get" in ops and pat.search(path):
            p = pat.sub(NO, path)
            if "{" not in p:
                out.add(p)
    return sorted(out)


@pytest.fixture
def world(client, make_user):
    make_user(username="fin_boss", password="Test-Pass-123", role="superadmin")
    make_user(username="eng_plain", password="Test-Pass-123", role="engineer")
    _seed("eng_plain")
    return client, _login(client, "fin_boss", "Test-Pass-123"), _login(client, "eng_plain", "Test-Pass-123")


def test_the_plain_account_can_open_the_case_but_never_receives_the_reason(world):
    client, fin, plain = world
    r = client.get("/api/quotations/%s" % NO, headers=plain)
    assert r.status_code == 200, r.text[:200]
    assert SECRET not in r.text, "沒有財務檢視的帳號從單筆案件 GET 拿到了重新開啟的理由"
    hist = r.json()["data"]["editHistory"]
    assert [h.get("type") for h in hist] == ["settlement_finalized", "settlement_draft"] and hist[1]["by"] == "boss" and hist[1]["at"], "誰／何時／事件要保留"
    assert "reason" not in hist[1]


def test_the_financial_account_still_sees_the_reason(world):
    client, fin, plain = world
    r = client.get("/api/quotations/%s" % NO, headers=fin)
    assert r.status_code == 200 and SECRET in r.text


def test_no_get_route_that_takes_a_case_number_leaks_the_reason_to_the_plain_account(world):
    client, fin, plain = world
    routes = _case_get_routes(client.app)
    assert len(routes) >= 10, "掃到的路由太少（掃描器壞了？）：%d" % len(routes)
    leaked, ok = [], 0
    for p in routes:
        try:
            r = client.get(p, headers=plain)
        except Exception:                                   # noqa: BLE001  掃路由時個別端點因缺參數丟例外不是本題的事
            continue
        ok += 1
        if SECRET in r.text:
            leaked.append((p, r.status_code))
    assert ok >= 10
    assert not leaked, "這些端點把重新開啟的理由回給沒有財務檢視的帳號：%s" % leaked


def test_the_edit_history_endpoint_masks_the_reason_for_the_plain_account_but_not_for_finance(world):
    client, fin, plain = world
    paths = [p for p in _case_get_routes(client.app) if "version" in p or "history" in p]
    assert paths, "找不到修改紀錄端點"
    for p in paths:
        assert SECRET not in client.get(p, headers=plain).text, p


def test_the_case_list_does_not_carry_the_reason_either(world):
    client, fin, plain = world
    r = client.get("/api/quotations", headers=plain)
    assert r.status_code == 200 and SECRET not in r.text, "案件清單的『最近一次修改』不可以帶理由"
