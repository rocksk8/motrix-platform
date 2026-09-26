"""2026-08-31：承攬商匯款申請「標記已匯款」原本一律用系統操作當下的時間當
匯款日期（paid_at），沒有地方讓財務填實際匯款日期（銀行匯款完成的時間跟
回系統標記的時間常常不是同一天）。POST /api/contractor-vouchers/{no}/paid-toggle
的 action=pay 現在可以帶 paid_at（YYYY-MM-DD）。"""
import io


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_approved_voucher(client, token, quote_no="MQ-PAIDDATE-001"):
    """建立一張已核准狀態的承攬商匯款申請，供 paid-toggle 測試用。直接用 SQL
    插入已核准狀態（比照 test_dispatch_edit_guard_2026_08_28.py 的既有作法），
    不走 submit/approve HTTP 流程——這裡只是要測 paid-toggle 本身，用同一個
    使用者 submit 又 approve 會被 check_no_tier_self_approval() 擋下（無 tiers
    設定時不能自行審核自己送出的申請），跟本測試主題無關。"""
    r = client.post(
        "/api/vendor-contractors", headers=_auth(token),
        json={"name": f"廠商{quote_no}", "data": {}},
    )
    assert r.status_code == 201, r.text
    vendor_id = r.json()["id"]

    r = client.post(
        "/api/contractor-dispatches", headers=_auth(token),
        json={
            "quote_no": quote_no, "vendor_id": vendor_id,
            "items_json": [{"description": "測試品項", "qty": 1, "unit": "式", "unitPrice": 10000, "amount": 10000}],
            "status": "completed",
        },
    )
    assert r.status_code == 201, r.text
    did = r.json()["id"]

    cv = client.post("/api/contractor-vouchers", headers=_auth(token), json={"dispatch_id": did})
    assert cv.status_code == 201, cv.text
    voucher_no = cv.json()["voucher_no"]

    import db
    conn = db.get_db()
    try:
        conn.execute(
            "UPDATE contractor_payment_vouchers SET status='已核准' WHERE voucher_no=?", (voucher_no,)
        )
        conn.commit()
    finally:
        conn.close()
    return voucher_no


def test_paid_toggle_accepts_custom_paid_at(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    voucher_no = _make_approved_voucher(client, token)

    r = client.post(
        f"/api/contractor-vouchers/{voucher_no}/paid-toggle", headers=_auth(token),
        json={"action": "pay", "paid_at": "2026-07-15", "note": "測試備註"},
    )
    assert r.status_code == 200, r.text

    detail = client.get(f"/api/contractor-vouchers/{voucher_no}", headers=_auth(token))
    assert detail.status_code == 200, detail.text
    dj = detail.json()
    assert dj["isPaid"] is True
    assert dj["paidAt"] == "2026-07-15"
    assert dj["paidLog"][-1]["paidAt"] == "2026-07-15"
    assert dj["paidLog"][-1]["note"] == "測試備註"


def test_paid_toggle_defaults_to_today_without_paid_at(client, make_user):
    from datetime import date

    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    voucher_no = _make_approved_voucher(client, token, "MQ-PAIDDATE-002")

    r = client.post(
        f"/api/contractor-vouchers/{voucher_no}/paid-toggle", headers=_auth(token),
        json={"action": "pay"},
    )
    assert r.status_code == 200, r.text
    detail = client.get(f"/api/contractor-vouchers/{voucher_no}", headers=_auth(token))
    assert detail.json()["paidAt"] == date.today().isoformat()


def test_paid_toggle_rejects_malformed_paid_at(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    voucher_no = _make_approved_voucher(client, token, "MQ-PAIDDATE-003")

    for bad in ("2026/07/15", "not-a-date", "2026-13-01"):
        r = client.post(
            f"/api/contractor-vouchers/{voucher_no}/paid-toggle", headers=_auth(token),
            json={"action": "pay", "paid_at": bad},
        )
        assert r.status_code == 400, f"paid_at={bad!r} should be rejected, got {r.status_code}: {r.text}"

    detail = client.get(f"/api/contractor-vouchers/{voucher_no}", headers=_auth(token))
    assert detail.json()["isPaid"] is False, "格式錯誤時不應該把申請標記成已匯款"


def test_pdf_shows_custom_paid_date(client, make_user):
    """PDF 產製（pdf_gen.py::_contractor_voucher_html）讀 paidAt[:10] 當「匯款日期」
    顯示欄位，這裡驗證自訂日期真的會被讀到（不需要 Edge headless，直接測資料層）。"""
    from pdf_gen import _contractor_voucher_dict
    import db

    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    voucher_no = _make_approved_voucher(client, token, "MQ-PAIDDATE-004")
    r = client.post(
        f"/api/contractor-vouchers/{voucher_no}/paid-toggle", headers=_auth(token),
        json={"action": "pay", "paid_at": "2026-06-01"},
    )
    assert r.status_code == 200, r.text

    conn = db.get_db()
    row = conn.execute(
        "SELECT * FROM contractor_payment_vouchers WHERE voucher_no=?", (voucher_no,)
    ).fetchone()
    conn.close()
    v = _contractor_voucher_dict(row)
    assert v["paidAt"][:10] == "2026-06-01"
