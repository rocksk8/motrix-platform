"""2026-08-30：承攬商派發新增「應付款日期」（payable_date）與「廠商發票」附件
（invoice_files_json，DB migration v68）。使用者要求填寫派發時可指定應付款
日期並上傳廠商發票，且產生匯款申請後，簽核佇列（/api/approval-queue）與
申請單本身都要能看到這兩項，連同既有的匯款帳戶／存簿圖檔一起顯示——這兩項
本來就已經寫入 snapshot_json，只是簽核佇列的查詢沒有把它們帶出來。"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import io
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _png_file(name="invoice.png"):
    data = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
        "de0000000c4944415478da6360000002000155a5e6ce0000000049454e44ae42"
        "6082"
    )
    return (name, io.BytesIO(data), "image/png")


def _make_vendor_with_bank(client, token, name="發票測試承攬商"):
    r = client.post(
        "/api/vendor-contractors", headers=_auth(token),
        json={
            "name": name,
            "data": {
                "bankCode": "007", "bankName": "第一銀行", "bankBranch": "測試分行",
                "bankAccountName": name, "bankAccountNumber": "1234567890",
                "bankPassbookImage": "data:image/png;base64,ZmFrZQ==",
            },
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_dispatch_create_and_update_persists_payable_date(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)

    r = client.post(
        "/api/contractor-dispatches", headers=_auth(token),
        json={
            "quote_no": "MQ-PAYDATE-001",
            "personnel_json": [{"id": "p1", "name": "測試點工", "amount": 1000}],
            "payable_date": "2026-09-15",
        },
    )
    assert r.status_code == 201, r.text
    did = r.json()["id"]

    r = client.get(f"/api/contractor-dispatches/{did}", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["payableDate"] == "2026-09-15"
    assert r.json()["invoiceFiles"] == []

    r = client.put(
        f"/api/contractor-dispatches/{did}", headers=_auth(token),
        json={
            "quote_no": "MQ-PAYDATE-001",
            "personnel_json": [{"id": "p1", "name": "測試點工", "amount": 1000}],
            "payable_date": "2026-10-01",
        },
    )
    assert r.status_code == 200, r.text
    r = client.get(f"/api/contractor-dispatches/{did}", headers=_auth(token))
    assert r.json()["payableDate"] == "2026-10-01"


def test_dispatch_invoice_file_upload_and_delete(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)

    r = client.post(
        "/api/contractor-dispatches", headers=_auth(token),
        json={"quote_no": "MQ-PAYDATE-002", "personnel_json": [{"id": "p1", "name": "測試點工", "amount": 1000}]},
    )
    did = r.json()["id"]

    up = client.post(
        f"/api/contractor-dispatches/{did}/invoice-files", headers=_auth(token),
        files={"files": _png_file()},
    )
    assert up.status_code == 201, up.text
    file_id = up.json()["files"][0]["id"]

    r = client.get(f"/api/contractor-dispatches/{did}", headers=_auth(token))
    assert len(r.json()["invoiceFiles"]) == 1
    # 廠商發票跟既有的「承攬商報價附件」（files_json）是分開的欄位，互不影響
    assert r.json()["files"] == []

    d = client.delete(f"/api/contractor-dispatches/{did}/invoice-files/{file_id}", headers=_auth(token))
    assert d.status_code == 200, d.text
    r2 = client.get(f"/api/contractor-dispatches/{did}", headers=_auth(token))
    assert r2.json()["invoiceFiles"] == []


def test_dispatch_invoice_file_upload_requires_admin(client, make_user):
    admin_username, admin_password = make_user(username="pd_admin", role="superadmin")
    admin_token = _login(client, admin_username, admin_password)
    r = client.post(
        "/api/contractor-dispatches", headers=_auth(admin_token),
        json={"quote_no": "MQ-PAYDATE-003", "personnel_json": [{"id": "p1", "name": "測試點工", "amount": 1000}]},
    )
    did = r.json()["id"]

    viewer_username, viewer_password = make_user(username="pd_viewer", role="viewer", modules=[])
    viewer_token = _login(client, viewer_username, viewer_password)
    up = client.post(
        f"/api/contractor-dispatches/{did}/invoice-files", headers=_auth(viewer_token),
        files={"files": _png_file()},
    )
    assert up.status_code == 403, up.text


def test_voucher_snapshot_and_approval_queue_carry_payable_date_and_bank_info(client, make_user):
    """端到端：派發（含應付款日期＋廠商發票）→ 產生匯款申請 → 送出審核 →
    簽核佇列項目要能看到應付款日期／匯款帳戶／存簿圖檔／廠商發票。"""
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    vendor_id = _make_vendor_with_bank(client, token)

    r = client.post(
        "/api/contractor-dispatches", headers=_auth(token),
        json={
            "quote_no": "MQ-PAYDATE-004",
            "vendor_id": vendor_id,
            "items_json": [{"description": "測試品項", "qty": 1, "unit": "式", "unitPrice": 10000, "amount": 10000}],
            "status": "completed",
            "payable_date": "2026-09-20",
        },
    )
    assert r.status_code == 201, r.text
    did = r.json()["id"]

    up = client.post(
        f"/api/contractor-dispatches/{did}/invoice-files", headers=_auth(token),
        files={"files": _png_file("vendor_invoice.png")},
    )
    assert up.status_code == 201, up.text

    cv = client.post("/api/contractor-vouchers", headers=_auth(token), json={"dispatch_id": did})
    assert cv.status_code == 201, cv.text
    voucher_no = cv.json()["voucher_no"]

    detail = client.get(f"/api/contractor-vouchers/{voucher_no}", headers=_auth(token))
    assert detail.status_code == 200, detail.text
    dj = detail.json()
    assert dj["payableDate"] == "2026-09-20"
    assert dj["bankAccountNumber"] == "1234567890"
    assert dj["bankPassbookImage"] == "data:image/png;base64,ZmFrZQ=="
    assert len(dj["invoiceFiles"]) == 1
    assert dj["invoiceFiles"][0]["filename"] == "vendor_invoice.png"
    assert dj["snapshot"]["payableDate"] == "2026-09-20"

    # 測試用使用者未歸屬任何部門，關掉「申請人部門主管自動簽核」這個系統
    # 內建的第一層，避免送審卡在跟本測試主題無關的組織架構設定上。
    flow = client.put(
        "/api/contractor-vouchers/settings/approval-flow", headers=_auth(token),
        json={"tiers": [], "includeSubmitterManagerTier": False},
    )
    assert flow.status_code == 200, flow.text

    sub = client.post(f"/api/contractor-vouchers/{voucher_no}/submit", headers=_auth(token))
    assert sub.status_code == 200, sub.text

    q = client.get("/api/approval-queue", headers=_auth(token))
    assert q.status_code == 200, q.text
    items = [it for g in q.json()["queue"] for it in g["items"] if it["quoteNo"] == voucher_no]
    assert len(items) == 1
    item = items[0]
    assert item["type"] == "contractor_voucher"
    assert item["payableDate"] == "2026-09-20"
    assert item["bankAccountNumber"] == "1234567890"
    assert item["bankAccountName"] == "發票測試承攬商"
    assert item["bankPassbookImage"] == "data:image/png;base64,ZmFrZQ=="
    assert len(item["invoiceFiles"]) == 1
    assert item["invoiceFiles"][0]["filename"] == "vendor_invoice.png"


def test_create_voucher_can_set_payable_date_at_creation_time(client, make_user):
    """2026-08-31：使用者要求產生匯款申請當下就能直接填/改應付款日期，不用
    先跳去編輯派發紀錄——派發本身建立時沒填 payable_date，產生申請時補填，
    要同時寫進申請快照，也要回寫到派發紀錄本身（維持兩邊一致）。"""
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)

    r = client.post(
        "/api/contractor-dispatches", headers=_auth(token),
        json={
            "quote_no": "MQ-PAYDATE-005",
            "personnel_json": [{"id": "p1", "name": "測試點工", "amount": 1000}],
            "status": "completed",
        },
    )
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    assert client.get(f"/api/contractor-dispatches/{did}", headers=_auth(token)).json()["payableDate"] == ""

    cv = client.post(
        "/api/contractor-vouchers", headers=_auth(token),
        json={"dispatch_id": did, "payable_date": "2026-10-05"},
    )
    assert cv.status_code == 201, cv.text
    voucher_no = cv.json()["voucher_no"]

    detail = client.get(f"/api/contractor-vouchers/{voucher_no}", headers=_auth(token))
    assert detail.json()["payableDate"] == "2026-10-05"

    # 回寫派發紀錄本身
    d = client.get(f"/api/contractor-dispatches/{did}", headers=_auth(token))
    assert d.json()["payableDate"] == "2026-10-05"


def test_create_voucher_rejects_malformed_payable_date(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    r = client.post(
        "/api/contractor-dispatches", headers=_auth(token),
        json={
            "quote_no": "MQ-PAYDATE-006",
            "personnel_json": [{"id": "p1", "name": "測試點工", "amount": 1000}],
            "status": "completed",
        },
    )
    did = r.json()["id"]

    for bad in ("2026/10/05", "not-a-date", "2026-13-01"):
        cv = client.post(
            "/api/contractor-vouchers", headers=_auth(token),
            json={"dispatch_id": did, "payable_date": bad},
        )
        assert cv.status_code == 400, f"payable_date={bad!r} should be rejected, got {cv.status_code}: {cv.text}"

    # 格式錯誤時不該有任何申請被建立
    r2 = client.get(f"/api/contractor-dispatches?quote_no=MQ-PAYDATE-006", headers=_auth(token))
    assert r2.json()[0]["payableDate"] == "", "格式錯誤時不該把畸形值寫回派發紀錄"
