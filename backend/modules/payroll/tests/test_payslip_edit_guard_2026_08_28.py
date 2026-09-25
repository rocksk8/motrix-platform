"""2026-08-28（模組逐步檢查：勞報單）：PUT /api/payslips/{slip_no} 補上「已匯出不可修改」鎖。

delete_payslip() 早就擋「已匯出的勞報單不可刪除」，但 update_payslip()（PUT）完全
沒有狀態檢查——匯出成 PDF 封存（record_export 設 status='已匯出'，且系統沒有取消
匯出的還原機制）之後，金額/稅額欄位還是能被自由修改，封存的 PDF 內容就會跟資料庫
最新資料悄悄兜不起來。比照 delete 的做法在 PUT 補上同一道鎖。
"""
import json


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _insert_payslip(slip_no, status="草稿", gross=30000):
    import db
    conn = db.get_db()
    try:
        data_json = json.dumps({
            "slipNo": slip_no, "contractorName": "測試承攬人", "incomeType": "9A",
            "grossAmount": gross, "contractorNationality": "本國籍",
            "contractorHasUnionInsurance": False,
        }, ensure_ascii=False)
        conn.execute(
            "INSERT INTO payslips (slip_no, contractor_id, contractor_name, income_type, "
            "gross_amount, tax_withheld, nhi_supplement, net_amount, payment_method, slip_date, "
            "status, tax_rules_version, data_json, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (slip_no, None, "測試承攬人", "9A", gross, 0, 0, gross, "匯款", "2026-08-01",
             status, "2026", data_json, "2026-08-01T00:00:00", "2026-08-01T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()


def _payload(gross=35000):
    return {"data": {"contractorName": "測試承攬人", "incomeType": "9A",
                      "grossAmount": gross, "contractorNationality": "本國籍",
                      "contractorHasUnionInsurance": False}}


def test_draft_payslip_can_be_edited(client, make_user):
    su, pw = make_user(username="ps_su1", role="superadmin")
    _insert_payslip("PS-202608-001", status="草稿")
    token = _login(client, su, pw)
    r = client.put("/api/payslips/PS-202608-001", json=_payload(40000), headers=_auth(token))
    assert r.status_code == 200, r.text


def test_exported_payslip_cannot_be_edited(client, make_user):
    su, pw = make_user(username="ps_su2", role="superadmin")
    _insert_payslip("PS-202608-002", status="已匯出")
    token = _login(client, su, pw)
    r = client.put("/api/payslips/PS-202608-002", json=_payload(99999), headers=_auth(token))
    assert r.status_code == 409, r.text
    assert "已匯出" in r.text

    import db
    conn = db.get_db()
    row = conn.execute("SELECT gross_amount FROM payslips WHERE slip_no=?",
                        ("PS-202608-002",)).fetchone()
    conn.close()
    assert row["gross_amount"] == 30000  # 未被改動


def test_update_missing_payslip_404(client, make_user):
    su, pw = make_user(username="ps_su3", role="superadmin")
    token = _login(client, su, pw)
    r = client.put("/api/payslips/PS-202608-999", json=_payload(), headers=_auth(token))
    assert r.status_code == 404, r.text
