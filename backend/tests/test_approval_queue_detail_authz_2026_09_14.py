"""簽核佇列詳情的授權與金額遮蔽（2026-09-14，自動安全掃描後補）。

`/api/approval-queue/detail` 第一版只要求登入，理由是「跟佇列清單一致」——**那個
理由站不住腳**：清單只有摘要，詳情回的是完整內容（明細、附件、變更 payload、匯款
帳戶），而 `id` 是可預測的單號或小整數。這正是同日模組權限稽核收掉的那種 IDOR。

這裡釘住三件事：
1. 外人打不開（403）
2. **這張單自己的簽核人打得開**——他往往既不是該案業務也不在協作者名單裡，
   擋掉他等於讓簽核佇列失去意義
3. 沒有財務檢視權的人看得到內容但**看不到金額**（規則與憑證流一致），
   而本單簽核人例外
"""
import json


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": "Bearer " + token}


def _seed_case(quote_no, sales_person=""):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, sales_person, assigned_user_ids) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", 100000, 95238,
             json.dumps({"dealTag": "已成案"}, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", sales_person, "[]"),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_completion_note(note_no, quote_no, approver=None):
    """建一張待審的完工單；`approver` 會被放進單據自己的簽核名單。"""
    import db
    data = {}
    if approver:
        data["approval"] = {"tiers": [{"approvers": [{"username": approver, "status": "pending"}]}],
                            "currentTier": 0}
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO completion_notes (note_no, quote_no, status, data_json, created_by, "
            "created_at, updated_at, site_address, work_summary, items_json, warranty_months) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (note_no, quote_no, "待審核", json.dumps(data, ensure_ascii=False), "someone",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "台中市", "施工說明",
             json.dumps([{"name": "佈線", "qty": 1, "amount": 5000}], ensure_ascii=False), 12),
        )
        conn.commit()
    finally:
        conn.close()


def test_outsider_cannot_open_queue_detail(client, make_user):
    """單號可預測（CN-YYYYMM-NNN），外人不該撈得到內容。"""
    _seed_case("MQ-AQZ-001", sales_person="aqz_owner")
    _seed_completion_note("CN-AQZ-001", "MQ-AQZ-001")
    u, p = make_user(username="aqz_outsider", role="viewer", modules=["dashboard"])
    r = client.get("/api/approval-queue/detail?type=completion_note&id=CN-AQZ-001",
                   headers=_auth(_login(client, u, p)))
    assert r.status_code == 404, f"外人看得到送審內容：{r.status_code} {r.text}"   # M01-O1：看不到＝不存在（同一個 404）


def test_document_approver_can_open_detail(client, make_user):
    """反向控制（這一題才是重點）：這張單的簽核人打得開——他既不是業務也沒被指派。

    少了這條放行，簽核佇列就等於失效：看得到清單卻點不開任何一筆。
    """
    _seed_case("MQ-AQZ-002", sales_person="someone_else")
    u, p = make_user(username="aqz_approver", role="engineer", modules=["dashboard"])
    _seed_completion_note("CN-AQZ-002", "MQ-AQZ-002", approver="aqz_approver")
    r = client.get("/api/approval-queue/detail?type=completion_note&id=CN-AQZ-002",
                   headers=_auth(_login(client, u, p)))
    assert r.status_code == 200, r.text
    assert r.json()["case"]["quoteNo"] == "MQ-AQZ-002"


def test_case_member_can_open_detail(client, make_user):
    """具「案件管理」模組的人也打得開（與其他每案端點同一套規則）。"""
    _seed_case("MQ-AQZ-003", sales_person="someone_else")
    _seed_completion_note("CN-AQZ-003", "MQ-AQZ-003")
    u, p = make_user(username="aqz_cm", role="engineer", modules=["case_manage"])
    r = client.get("/api/approval-queue/detail?type=completion_note&id=CN-AQZ-003",
                   headers=_auth(_login(client, u, p)))
    assert r.status_code == 200, r.text


def test_money_is_masked_without_financial_view(client, make_user):
    """沒有財務檢視權：內容看得到，金額看不到（規則與憑證流一致）。"""
    _seed_case("MQ-AQZ-004", sales_person="someone_else")
    _seed_completion_note("CN-AQZ-004", "MQ-AQZ-004")
    u, p = make_user(username="aqz_nofin", role="engineer", modules=["case_manage"])
    d = client.get("/api/approval-queue/detail?type=completion_note&id=CN-AQZ-004",
                   headers=_auth(_login(client, u, p))).json()
    assert d.get("moneyMasked") is True, d
    assert all("amount" not in (it or {}) for it in d["items"]), d["items"]
    # 內容本身仍然看得到——遮的是金額，不是整張單
    labels = {f["label"]: f["value"] for f in d["fields"]}
    assert labels["執行說明"] == "施工說明", labels


def test_money_visible_for_approver_without_financial_view(client, make_user):
    """本單簽核人例外：看不到金額就沒辦法判斷該不該簽。"""
    _seed_case("MQ-AQZ-005", sales_person="someone_else")
    u, p = make_user(username="aqz_appr2", role="engineer", modules=["dashboard"])
    _seed_completion_note("CN-AQZ-005", "MQ-AQZ-005", approver="aqz_appr2")
    d = client.get("/api/approval-queue/detail?type=completion_note&id=CN-AQZ-005",
                   headers=_auth(_login(client, u, p))).json()
    assert not d.get("moneyMasked"), d
    assert d["items"][0]["amount"] == 5000, d["items"]


def test_passbook_image_rejects_non_image_scheme(client, make_user):
    """存簿封面只收 `data:image/`——混進 javascript: 的話，簽核人點下去就是在本站
    原點執行腳本（自動安全掃描 finding #2，前後端都擋）。"""
    import db
    _seed_case("MQ-AQZ-006", sales_person="someone_else")
    snap = {"grandTotal": 5000, "vendorName": "測試承攬商",
            "bankPassbookImage": "javascript:alert(document.cookie)"}
    conn = db.get_db()
    try:
        # 憑證的 dispatch_id 有外鍵，要先有一張派工單
        conn.execute(
            "INSERT INTO contractor_dispatches (id, quote_no, vendor_id, dispatch_date, scope, "
            "items_json, personnel_json, total_amount, tax_rate, status, notes, created_by, "
            "created_at, updated_at, accepted_at, accepted_by, files_json, invoice_files_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (99001, "MQ-AQZ-006", None, "2026-09-01", "測試", "[]", "[]", 5000, 0,
             "已完成", "", "someone", "2026-01-01T00:00:00", "2026-01-01T00:00:00",
             "", "", "[]", "[]"),
        )
        conn.execute(
            "INSERT INTO contractor_payment_vouchers (voucher_no, quote_no, dispatch_id, status, "
            "snapshot_json, data_json, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("CV-AQZ-006", "MQ-AQZ-006", 99001, "待審核", json.dumps(snap, ensure_ascii=False),
             json.dumps({"approval": {"tiers": [{"approvers": [
                 {"username": "aqz_su", "status": "pending"}]}], "currentTier": 0}},
                 ensure_ascii=False),
             "someone", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    u, p = make_user(username="aqz_su", role="superadmin")
    d = client.get("/api/approval-queue/detail?type=contractor_voucher&id=CV-AQZ-006",
                   headers=_auth(_login(client, u, p))).json()
    urls = [f.get("dataUrl", "") for f in d["files"]]
    assert not any(str(x).lower().startswith("javascript:") for x in urls), d["files"]
