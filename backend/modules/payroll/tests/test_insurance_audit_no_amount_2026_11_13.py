"""投保／扣繳設定（`PUT /api/bonus/insurance/{username}`）的稽核紀錄不含金額明文（h11 發現，安全票 fix/user-perm-sensitive-gate）。

投保金額與 MOTRIX 以外已發的獎金是薪資等級資料；`audit_log` 任何有稽核權限的人都看得到 ⇒ 稽核只記「誰的哪些欄位改了」。
金額本身仍正確存進 `system_settings`（最高管理者專用的 GET 讀得到）。
"""
import json

SECRET_INSURED = 73219          # 刻意挑不會與其他數字（id、時間、年）碰在一起的值
SECRET_EXTERNAL = 618457


def _login(client, username, password="Test-Pass-123"):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _audit_rows(username):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM audit_log WHERE action='bonus.insurance' AND target_id=? ORDER BY id", (username,)).fetchall()]
    finally:
        conn.close()


def _no_plaintext(rows):
    for r in rows:
        blob = json.dumps(r, ensure_ascii=False)
        for secret in (SECRET_INSURED, SECRET_EXTERNAL, "73,219", "618,457"):
            assert str(secret) not in blob, (secret, r)


def test_put_insurance_audit_names_the_fields_but_not_the_amounts(client, make_user):
    make_user("boss", role="superadmin", modules=[])
    make_user("emp", role="sales", modules=[])
    h = _login(client, "boss")
    r = client.put("/api/bonus/insurance/emp", json={"insuredAmount": SECRET_INSURED, "year": 2026, "ytdExternal": SECRET_EXTERNAL}, headers=h)
    assert r.status_code == 200, r.text
    rows = _audit_rows("emp")
    assert len(rows) == 1
    _no_plaintext(rows)
    assert "insuredAmount" in rows[0]["target_label"] and "ytdExternal" in rows[0]["target_label"] and "2026" in rows[0]["target_label"]
    # 金額照常存起來、最高管理者讀得到
    items = client.get("/api/bonus/insurance?year=2026", headers=h).json()["items"]
    emp = next(i for i in items if i["username"] == "emp")
    assert emp["insuredAmount"] == SECRET_INSURED and emp["ytdExternal"] == SECRET_EXTERNAL


def test_clearing_and_single_field_changes_also_carry_no_amount(client, make_user):
    make_user("boss", role="superadmin", modules=[])
    make_user("emp", role="sales", modules=[])
    h = _login(client, "boss")
    assert client.put("/api/bonus/insurance/emp", json={"insuredAmount": SECRET_INSURED}, headers=h).status_code == 200
    assert client.put("/api/bonus/insurance/emp", json={"insuredAmount": ""}, headers=h).status_code == 200            # 清除
    assert client.put("/api/bonus/insurance/emp", json={"year": 2025, "ytdExternal": SECRET_EXTERNAL}, headers=h).status_code == 200
    rows = _audit_rows("emp")
    assert len(rows) == 3
    _no_plaintext(rows)
    assert [("insuredAmount" in r["target_label"]) for r in rows] == [True, True, False]
    assert "2025" in rows[2]["target_label"]


def test_rejected_put_writes_no_audit_row(client, make_user):
    make_user("boss", role="superadmin", modules=[])
    make_user("emp", role="sales", modules=[])
    h = _login(client, "boss")
    assert client.put("/api/bonus/insurance/emp", json={"insuredAmount": 0}, headers=h).status_code == 400
    assert _audit_rows("emp") == []
