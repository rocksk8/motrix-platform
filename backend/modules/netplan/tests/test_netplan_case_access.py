"""IP-12 `case.access`（M01 → M10）：網路規劃書與案件的相依（2026-09-26，M10 搬遷前置）。

① 提供者已登記
② 正對照：綁定案件時帶出客戶名稱；依案件查詢有逐案權限（沒有案件權限的人 403）
③ 反向控制：拿掉提供者（＝M01 不在）⇒ 不綁案件的規劃書照常建立；綁案件 400、依案件查詢 404，訊息明說
"""
import json

from core import registry

MISSING = "案件模組未安裝"


def _tok(client, make_user, u, role, mods=None):
    name, pw = make_user(username=u, role=role, modules=mods)
    r = client.post("/api/auth/login", json={"username": name, "password": pw})
    return {"Authorization": "Bearer " + r.json()["token"]}


def _case(no, customer="規劃客戶"):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at,"
                     " updated_at) VALUES (?,?,?,?,?,?,?)", (no, "已送出", customer, "規劃專案", json.dumps({}), "t", "t"))
        conn.commit()
    finally:
        conn.close()


def _drop(monkeypatch):
    monkeypatch.delitem(registry._LEGACY_PROVIDERS, ("case.access", "case"))
    assert registry.single_provider("case.access") is None


def test_provider_is_registered(client):
    ca = registry.single_provider("case.access")
    assert ca is not None and callable(ca.guard) and callable(ca.summary)


def test_with_m01_binding_and_per_case_access(client, make_user):
    sa = _tok(client, make_user, "np_sa", "superadmin")
    out = _tok(client, make_user, "np_out", "sales", ["netplan", "dashboard", "quotation"])
    _case("MQ-NP-0926")
    r = client.post("/api/network-plans", headers=sa, json={"quoteNo": "MQ-NP-0926"})
    assert r.status_code == 201, r.text
    plan = client.get("/api/network-plans/%d" % r.json()["id"], headers=sa).json()
    assert plan["siteName"] == "規劃客戶" and plan["quoteNo"] == "MQ-NP-0926"      # summary 帶出客戶名
    assert client.get("/api/quotations/MQ-NP-0926/network-plan", headers=sa).status_code == 200
    assert client.get("/api/quotations/MQ-NP-0926/network-plan", headers=out).status_code == 403


def test_reverse_without_m01_plans_work_but_cannot_bind(client, make_user, monkeypatch):
    sa = _tok(client, make_user, "np_sa2", "superadmin")
    _case("MQ-NP-0927")
    _drop(monkeypatch)
    r = client.post("/api/network-plans", headers=sa, json={"siteName": "獨立評估"})
    assert r.status_code == 201, r.text                                       # 不綁案件照常
    r = client.post("/api/network-plans", headers=sa, json={"quoteNo": "MQ-NP-0927"})
    assert r.status_code == 400 and MISSING in r.json()["detail"], r.text
    r = client.get("/api/quotations/MQ-NP-0927/network-plan", headers=sa)
    assert r.status_code == 404 and MISSING in r.json()["detail"], r.text
