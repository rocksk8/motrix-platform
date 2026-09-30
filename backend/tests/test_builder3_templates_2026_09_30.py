# -*- coding: utf-8 -*-
"""建構器第三輪 S2（2026-09-30）：內建範本全部（報價單、請款單、請假單、加班單、出差單、採購單、借用登記、人員增補）——
每一個都要：列在目錄、驗證過、能發布、能用最小填寫建單（預設值 token 帶入申請人）、能輸出 HTML；
有金流的（報價單收入；請款單、出差單、採購單支出）金流欄位齊全，沒金流的不帶 finance（反向控制）。"""
import pytest

from helpers import custom_modules as CM

KEYS = ["quotation", "payment_request", "leave", "overtime", "business_trip", "purchase", "equipment_loan", "headcount"]
FINANCE = {"quotation": "income", "payment_request": "expense", "business_trip": "expense", "purchase": "expense"}

MIN = {  # 最小可建單的填寫（申請人／借用人由 token 帶入）
    "quotation": {"cust": "客戶甲", "lines": [{"name": "A", "qty": 2, "price": 100}]},
    "payment_request": {"payee": "廠商乙", "lines": [{"item": "運費", "qty": 1, "price": 500}]},
    "leave": {"leave_type": "特休", "period": {"from": "2026-10-01T09:00", "to": "2026-10-01T18:00"}, "hours": 8},
    "overtime": {"work_date": "2026-10-01", "period": {"from": "2026-10-01T18:00", "to": "2026-10-01T20:00"}, "hours": 2, "comp": "補休"},
    "business_trip": {"dest": "台中", "period": {"from": "2026-10-05", "to": "2026-10-06"}, "expenses": [{"item": "交通", "amt": 1500}]},
    "purchase": {"vendor": "供應商丙", "lines": [{"name": "線材", "qty": 10, "price": 20}]},
    "equipment_loan": {"item": "示波器", "qty": 1, "period": {"from": "2026-10-01", "to": "2026-10-03"}},
    "headcount": {"dept": None, "position": "工程師", "headcount": 1, "why": "專案需求"},
}


def _login(client, make_user, name):
    u, p = make_user(name, "Custom-Pass-123", role="superadmin")[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def test_catalog_lists_all_templates_and_none_are_gaps():
    ok, gaps = CM.templates(include_gaps=True)
    assert sorted(t["key"] for t in ok) == sorted(KEYS) and gaps == []
    assert all(t["name"] and t["category"] and t["description"] for t in ok)


@pytest.mark.parametrize("key", KEYS)
def test_template_validates_and_finance_matches_the_money_direction(key):
    body = CM.template_body(key)
    assert CM.validate_module(dict(body, permission="custom." + key), key) == []
    kinds = {f["finance"]["kind"] for f in body["fields"] if f.get("finance")}
    if key in FINANCE:
        assert kinds == {FINANCE[key]}, key
        assert any(f.get("finance", {}).get("dateField") for f in body["fields"])
    else:
        assert kinds == set(), "沒有金流的範本不可帶 finance：%s" % key       # 反向控制


@pytest.mark.parametrize("key", KEYS)
def test_template_publishes_creates_a_record_and_renders_output(key, client, make_user):
    h = _login(client, make_user, "b3t_" + key[:12])
    body = client.get("/api/custom-modules/templates/" + key, headers=h).json()["body"]
    body["permission"] = "custom.b3t" + key.replace("_", "")
    mkey = "t_" + key
    assert client.put("/api/definitions/custom_module/%s/draft" % mkey, headers=h, json={"body": body}).json()["problems"] == []
    assert client.post("/api/definitions/custom_module/%s/publish" % mkey, headers=h, json={}).status_code == 200
    values = dict(MIN[key])
    if key == "headcount":
        import db
        conn = db.get_db()
        try:
            dep = conn.execute("SELECT id FROM departments LIMIT 1").fetchone()
            if dep is None:
                div = conn.execute("SELECT id FROM divisions LIMIT 1").fetchone()
                if div is None:
                    conn.execute("INSERT INTO divisions (name, created_at) VALUES ('測試處', '2026-09-30')")
                    div = conn.execute("SELECT id FROM divisions LIMIT 1").fetchone()
                conn.execute("INSERT INTO departments (division_id, name, created_at) VALUES (?, '測試部', '2026-09-30')", (div["id"],))
                dep = conn.execute("SELECT id FROM departments LIMIT 1").fetchone()
            conn.commit()
            values["dept"] = str(dep["id"])
        finally:
            conn.close()
    r = client.post("/api/custom/%s/records" % mkey, headers=h, json={"values": values})
    assert r.status_code == 200, r.text
    rec = r.json()
    who = rec["data"].get("applicant") or rec["data"].get("borrower") or rec["data"].get("sales")
    assert who, "申請人／借用人應由預設值 token 帶入"
    out = client.get("/api/custom/%s/records/%s/output" % (mkey, rec["record_no"]), headers=h)
    assert out.status_code == 200 and body["name"] in out.text and rec["record_no"] in out.text
