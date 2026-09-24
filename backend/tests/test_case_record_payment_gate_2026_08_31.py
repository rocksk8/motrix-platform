"""2026-08-31（財務/出納權限分工，安全稽核追加發現）：案件管理頁面的款項
明細（勾選已收款／填實收金額／手續費）走的是「整包存檔」update_case_record
（PATCH /api/quotations/{no}/case-record），不是走有 admin+ 門檻的
mark_payment（PATCH .../payment/{idx}，只有 receivables.html 在用）——這支
端點原本完全沒有角色檢查，任何登入使用者都能在案件管理頁面直接改動金流
狀態。修法：偵測 payment.items 的 received/actualAmount/feeAmount 有變動、
且使用者不是 admin+/cashier 模組，整筆拒絕（不寫入任何欄位，包含同一次
request 裡其他合法的材料/合約欄位也一併不寫，避免使用者誤以為部分成功）。
"""
import json


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_quotation(quote_no):
    import db
    conn = db.get_db()
    try:
        data_json = json.dumps({
            "caseRecord": {
                "payment": {"items": [
                    {"id": 1, "type": "訂金款", "pct": 30, "amount": 30000, "received": False,
                     "actualAmount": None, "feeAmount": 0, "note": ""},
                ]},
                "materials": [
                    {"id": 1, "name": "測試料件", "qty": 1, "unit": "台", "ordered": False, "arrived": False},
                ],
            },
        })
        # 2026-09-24（CM14）：case-record 只收案件成員的存檔——本檔的非 admin 帳號一律是
        # make_user 的預設帳號 tester，讓它當這張單的業務（舊資料格式：只有顯示名稱）。
        # 這裡驗的是金流欄位的角色規則，不是成員規則（成員規則見 test_case_record_member_guard）。
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, "
            "data_json, created_at, updated_at, deal_tag, sales_person) VALUES (?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", data_json,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "tester"),
        )
        conn.commit()
    finally:
        conn.close()


def _case_record(quote_no):
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    finally:
        conn.close()
    return json.loads(row["data_json"] or "{}")["caseRecord"]


def test_non_admin_case_record_save_rejected_when_payment_received_changed(client, make_user):
    username, password = make_user(role="sales")
    token = _login(client, username, password)
    _make_quotation("MQ-CRGATE-001")

    cr = _case_record("MQ-CRGATE-001")
    cr["payment"]["items"][0]["received"] = True
    cr["payment"]["items"][0]["actualAmount"] = 30000
    cr["materials"][0]["ordered"] = True  # 同一次請求裡也帶一個合法欄位的變動

    r = client.patch("/api/quotations/MQ-CRGATE-001/case-record", headers=_auth(token), json={"case_record": cr})
    assert r.status_code == 403, r.text

    # 整筆拒絕：連同這次一起帶的合法欄位（materials.ordered）也不該被寫入
    saved = _case_record("MQ-CRGATE-001")
    assert saved["payment"]["items"][0]["received"] is False
    assert saved["materials"][0]["ordered"] is False


def test_non_admin_can_still_save_other_case_record_fields(client, make_user):
    username, password = make_user(role="sales")
    token = _login(client, username, password)
    _make_quotation("MQ-CRGATE-002")

    cr = _case_record("MQ-CRGATE-002")
    cr["materials"][0]["ordered"] = True
    cr["payment"]["items"][0]["note"] = "更新備註"  # 非金流欄位

    r = client.patch("/api/quotations/MQ-CRGATE-002/case-record", headers=_auth(token), json={"case_record": cr})
    assert r.status_code == 200, r.text

    saved = _case_record("MQ-CRGATE-002")
    assert saved["materials"][0]["ordered"] is True
    assert saved["payment"]["items"][0]["note"] == "更新備註"


def test_non_admin_can_add_and_remove_payment_installments(client, make_user):
    """關鍵回歸測試：sales/engineer 本來就能自行新增/刪除/調整款項期別（跟
    「標記已收款」是完全不同的動作）。比對邏輯如果誤用陣列索引位置而不是
    item['id'] 配對新舊品項，光是新增一期款項（陣列筆數變動）就會被整支
    擋下 403，變成非 admin/出納完全不能編輯款項明細——不是這次要的效果。"""
    username, password = make_user(role="sales")
    token = _login(client, username, password)
    _make_quotation("MQ-CRGATE-005")

    cr = _case_record("MQ-CRGATE-005")
    # 新增一期款項（未收款，received=False，屬正常編輯行為）
    cr["payment"]["items"].append(
        {"id": 2, "type": "驗收款", "pct": 70, "amount": 70000, "received": False,
         "actualAmount": None, "feeAmount": 0, "note": ""}
    )
    r = client.patch("/api/quotations/MQ-CRGATE-005/case-record", headers=_auth(token), json={"case_record": cr})
    assert r.status_code == 200, r.text
    saved = _case_record("MQ-CRGATE-005")
    assert len(saved["payment"]["items"]) == 2

    # 刪除剛新增的那期款項（陣列筆數再次變動）
    cr2 = _case_record("MQ-CRGATE-005")
    cr2["payment"]["items"] = [it for it in cr2["payment"]["items"] if it["id"] != 2]
    r2 = client.patch("/api/quotations/MQ-CRGATE-005/case-record", headers=_auth(token), json={"case_record": cr2})
    assert r2.status_code == 200, r2.text
    assert len(_case_record("MQ-CRGATE-005")["payment"]["items"]) == 1


def test_non_admin_cannot_add_payment_item_already_marked_received(client, make_user):
    """新增品項時如果一開始就直接帶 received=true，仍然要視為違規擋下
    （不能繞過「先新增再改」的偵測方式）。"""
    username, password = make_user(role="sales")
    token = _login(client, username, password)
    _make_quotation("MQ-CRGATE-006")

    cr = _case_record("MQ-CRGATE-006")
    cr["payment"]["items"].append(
        {"id": 2, "type": "驗收款", "pct": 70, "amount": 70000, "received": True,
         "actualAmount": 70000, "feeAmount": 0, "note": ""}
    )
    r = client.patch("/api/quotations/MQ-CRGATE-006/case-record", headers=_auth(token), json={"case_record": cr})
    assert r.status_code == 403, r.text
    assert len(_case_record("MQ-CRGATE-006")["payment"]["items"]) == 1


def test_admin_can_save_payment_received_via_case_record(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_quotation("MQ-CRGATE-003")

    cr = _case_record("MQ-CRGATE-003")
    cr["payment"]["items"][0]["received"] = True
    cr["payment"]["items"][0]["actualAmount"] = 30000
    # 2026-09-24 起已收款必須帶收款日期（所有角色，見 _validate_changed_receipts()）
    cr["payment"]["items"][0]["receivedAt"] = "2026-08-31"

    r = client.patch("/api/quotations/MQ-CRGATE-003/case-record", headers=_auth(token), json={"case_record": cr})
    assert r.status_code == 200, r.text
    saved = _case_record("MQ-CRGATE-003")
    assert saved["payment"]["items"][0]["received"] is True


def test_cashier_module_user_can_save_payment_received_via_case_record(client, make_user):
    username, password = make_user(role="engineer", modules=["cashier"])
    token = _login(client, username, password)
    _make_quotation("MQ-CRGATE-004")

    cr = _case_record("MQ-CRGATE-004")
    cr["payment"]["items"][0]["feeAmount"] = 100

    r = client.patch("/api/quotations/MQ-CRGATE-004/case-record", headers=_auth(token), json={"case_record": cr})
    assert r.status_code == 200, r.text
    saved = _case_record("MQ-CRGATE-004")
    assert saved["payment"]["items"][0]["feeAmount"] == 100
