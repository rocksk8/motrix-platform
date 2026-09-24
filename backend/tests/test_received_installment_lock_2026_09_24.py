"""已收款期別不可被非管理／非出納改動（2026-09-24）。

`update_case_record()`（案件管理整包存檔）對非 admin、非出納只比對
received／actualAmount／feeAmount 三欄，所以業務仍可以：
- 整期刪掉已收款期別、改它的收款日期／金額／比例／類型
- 自己把任何一期設成 taxExempt（沒經過沖銷簽核，應收金額就變小）

另外（D1 補）：所有角色存檔時，「這次新增或有改動的已收款期別」要驗收款日期與
金額型別，規則同 mark_payment；資料庫裡原本就有的「已收無日期」不擋。

裁示 E1、E3、E4；E2 由使用者 N10 裁示放行（見 test_received_installment_without_id_unchanged_lets_sales_save）（hichan-0a 代裁，待使用者確認）。觀測點打在資料庫落地值。
"""
import copy
import json

import pytest


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


RECEIVED = {"id": 1, "type": "訂金款", "pct": 30, "amount": 30000, "received": True,
            "receivedAt": "2026-08-01", "receivedBy": "出納", "actualAmount": 30000,
            "feeAmount": 0, "note": "", "invoiceNo": "", "invoiceDate": ""}
PENDING = {"id": 2, "type": "尾款", "pct": 70, "amount": 70000, "received": False,
           "receivedAt": "", "actualAmount": None, "feeAmount": 0, "note": "", "invoiceNo": ""}


def _make(quote_no, items):
    import db
    conn = db.get_db()
    try:
        # 2026-09-24（CM14）：case-record 只收案件成員的存檔 ⇒ 讓 lock_sales 當這張單的業務
        # （這裡驗的是已收款期別的鎖，不是成員規則）。
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, "
            "data_json, created_at, updated_at, deal_tag, sales_person) VALUES (?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案",
             json.dumps({"caseRecord": {"payment": {"items": items}, "materials": []}}, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "lock_sales"),
        )
        conn.commit()
    finally:
        conn.close()


def _cr(quote_no):
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    finally:
        conn.close()
    return json.loads(row["data_json"])["caseRecord"]


def _save(client, token, quote_no, cr):
    return client.patch(f"/api/quotations/{quote_no}/case-record", headers=_auth(token),
                        json={"case_record": cr})


@pytest.fixture
def sales(client, make_user):
    u, p = make_user(username="lock_sales", role="sales")
    return _login(client, u, p)


@pytest.fixture
def admin(client, make_user):
    u, p = make_user(username="lock_admin", role="admin")
    return _login(client, u, p)


# ── E1：已收款期別整期凍結 ─────────────────────────────────────────────────

def test_sales_cannot_delete_received_installment(client, sales):
    no = "MQ-LOCK-DEL"
    _make(no, [copy.deepcopy(RECEIVED), copy.deepcopy(PENDING)])
    cr = _cr(no)
    cr["payment"]["items"] = [it for it in cr["payment"]["items"] if it["id"] != 1]
    r = _save(client, sales, no, cr)
    assert r.status_code == 403, r.text
    assert any(it["id"] == 1 for it in _cr(no)["payment"]["items"]), "已收款期別不可以被刪掉"


@pytest.mark.parametrize("field,value", [
    ("receivedAt", "2026-09-30"), ("amount", 1), ("pct", 5), ("type", "改名"), ("note", "x"),
    ("receivedBy", "別人"), ("id", 99),
])
def test_sales_cannot_edit_received_installment(client, sales, field, value):
    no = f"MQ-LOCK-ED-{field}"
    _make(no, [copy.deepcopy(RECEIVED)])
    cr = _cr(no)
    cr["payment"]["items"][0][field] = value
    r = _save(client, sales, no, cr)
    assert r.status_code == 403, r.text
    assert _cr(no)["payment"]["items"][0] == RECEIVED


def test_sales_can_still_register_invoice_on_received_installment(client, sales):
    """發票登錄依既有規則任何登入者都可以做（mark_payment 的 invoiceNo 同此）。"""
    no = "MQ-LOCK-INV"
    _make(no, [copy.deepcopy(RECEIVED)])
    cr = _cr(no)
    cr["payment"]["items"][0]["invoiceNo"] = "AB12345678"
    cr["payment"]["items"][0]["invoiceDate"] = "2026-08-01"
    r = _save(client, sales, no, cr)
    assert r.status_code == 200, r.text
    assert _cr(no)["payment"]["items"][0]["invoiceNo"] == "AB12345678"


def test_sales_can_still_edit_unreceived_installment(client, sales):
    no = "MQ-LOCK-PEND"
    _make(no, [copy.deepcopy(RECEIVED), copy.deepcopy(PENDING)])
    cr = _cr(no)
    cr["payment"]["items"][1]["pct"] = 60
    cr["payment"]["items"][1]["expectedReceiptDate"] = "2026-10-01"
    r = _save(client, sales, no, cr)
    assert r.status_code == 200, r.text
    assert _cr(no)["payment"]["items"][1]["pct"] == 60


def test_admin_can_still_edit_received_installment(client, admin):
    no = "MQ-LOCK-ADM"
    _make(no, [copy.deepcopy(RECEIVED)])
    cr = _cr(no)
    cr["payment"]["items"][0]["receivedAt"] = "2026-08-02"
    r = _save(client, admin, no, cr)
    assert r.status_code == 200, r.text
    assert _cr(no)["payment"]["items"][0]["receivedAt"] == "2026-08-02"


def test_rejection_reason_names_the_installment(client, sales):
    no = "MQ-LOCK-MSG"
    _make(no, [copy.deepcopy(RECEIVED)])
    cr = _cr(no)
    cr["payment"]["items"][0]["receivedAt"] = "2026-09-30"
    r = _save(client, sales, no, cr)
    assert r.status_code == 403
    assert "訂金款" in r.json()["detail"], "訊息要說出是哪一期，前端會原樣顯示"


# ── E2：沒有 id 的舊期別 ──────────────────────────────────────────────────

def test_sales_cannot_edit_received_installment_without_id(client, sales):
    """對照組（N10 放行之後仍然要擋）：舊期別內容有變動 ⇒ 403。"""
    no = "MQ-LOCK-NOID"
    legacy = copy.deepcopy(RECEIVED)
    legacy.pop("id")
    _make(no, [legacy])
    cr = _cr(no)
    cr["payment"]["items"][0]["receivedAt"] = "2026-09-30"
    r = _save(client, sales, no, cr)
    assert r.status_code == 403, r.text
    assert _cr(no)["payment"]["items"][0]["receivedAt"] == "2026-08-01"


def test_received_installment_without_id_unchanged_lets_sales_save(client, sales):
    """N10 翻面（使用者 2026-09-24 晨間裁示原文：「放行：不動那期就能存」）。

    原本（09-24 夜間）這支釘的是現況：沒有 id 的已收款期別配不到舊資料，被當成
    「新增一筆已收款」而整筆擋下——業務在這類案件上連改不相關的欄位都存不了。
    放行相對現況是放寬，夜間不代裁；使用者早上裁示放行，所以翻面。
    對照組：那期內容有任何變動、或被刪掉，仍然 403（見上一支與下一支）。
    """
    no = "MQ-LOCK-NOID2"
    legacy = copy.deepcopy(RECEIVED)
    legacy.pop("id")
    _make(no, [legacy, copy.deepcopy(PENDING)])
    cr = _cr(no)
    cr["payment"]["items"][1]["pct"] = 65
    r = _save(client, sales, no, cr)
    assert r.status_code == 200, r.text
    items = _cr(no)["payment"]["items"]
    assert items[0] == legacy, "舊期別原封不動"
    assert items[1]["pct"] == 65


def test_received_installment_without_id_cannot_be_deleted(client, sales):
    no = "MQ-LOCK-NOID3"
    legacy = copy.deepcopy(RECEIVED)
    legacy.pop("id")
    _make(no, [legacy, copy.deepcopy(PENDING)])
    cr = _cr(no)
    cr["payment"]["items"] = [cr["payment"]["items"][1]]
    r = _save(client, sales, no, cr)
    assert r.status_code == 403, r.text
    assert len(_cr(no)["payment"]["items"]) == 2


def test_two_identical_received_installments_without_id_need_two_matches(client, sales):
    """逐筆配對：兩筆內容相同的舊期別，只留一筆＝刪了一筆 ⇒ 擋。"""
    no = "MQ-LOCK-NOID4"
    legacy = copy.deepcopy(RECEIVED)
    legacy.pop("id")
    _make(no, [legacy, copy.deepcopy(legacy), copy.deepcopy(PENDING)])
    cr = _cr(no)
    cr["payment"]["items"] = [cr["payment"]["items"][0], cr["payment"]["items"][2]]
    r = _save(client, sales, no, cr)
    assert r.status_code == 403, r.text


# ── E3：稅額沖銷欄位 ─────────────────────────────────────────────────────

@pytest.mark.parametrize("field,value", [("taxExempt", True), ("writeOffStatus", "approved")])
def test_sales_cannot_set_write_off_fields(client, sales, field, value):
    no = f"MQ-LOCK-WO-{field}"
    _make(no, [copy.deepcopy(PENDING)])
    cr = _cr(no)
    cr["payment"]["items"][0][field] = value
    r = _save(client, sales, no, cr)
    assert r.status_code == 403, r.text
    assert field not in _cr(no)["payment"]["items"][0]


def test_sales_cannot_add_installment_with_tax_exempt(client, sales):
    no = "MQ-LOCK-WO-NEW"
    _make(no, [copy.deepcopy(PENDING)])
    cr = _cr(no)
    cr["payment"]["items"].append({"id": 3, "type": "進度款", "pct": 0, "received": False,
                                   "taxExempt": True})
    r = _save(client, sales, no, cr)
    assert r.status_code == 403, r.text


# ── E4：新增或改動的已收款期別要過驗證（所有角色）────────────────────────

@pytest.mark.parametrize("over", [{"receivedAt": ""}, {"actualAmount": ""}, {"feeAmount": -1}])
def test_admin_cannot_save_invalid_new_receipt(client, admin, over):
    no = "MQ-LOCK-VAL"
    _make(no, [copy.deepcopy(PENDING)])
    cr = _cr(no)
    it = cr["payment"]["items"][0]
    it.update({"received": True, "receivedAt": "2026-09-01", "actualAmount": 70000, "feeAmount": 0})
    it.update(over)
    r = _save(client, admin, no, cr)
    assert r.status_code == 400, r.text
    assert _cr(no)["payment"]["items"][0]["received"] is False


def test_legacy_received_without_date_does_not_block_unrelated_save(client, admin, sales):
    no = "MQ-LOCK-LEGACY"
    legacy = copy.deepcopy(RECEIVED)
    legacy["receivedAt"] = ""
    _make(no, [legacy, copy.deepcopy(PENDING)])
    for tok in (admin, sales):
        cr = _cr(no)
        cr["payment"]["items"][1]["note"] = "改備註"
        r = _save(client, tok, no, cr)
        assert r.status_code == 200, r.text


def test_legacy_received_without_id_and_date_does_not_block_admin_save(client, admin):
    no = "MQ-LOCK-LEGACY2"
    legacy = copy.deepcopy(RECEIVED)
    legacy.pop("id")
    legacy["receivedAt"] = ""
    _make(no, [legacy, copy.deepcopy(PENDING)])
    cr = _cr(no)
    cr["payment"]["items"][1]["note"] = "改備註"
    r = _save(client, admin, no, cr)
    assert r.status_code == 200, r.text
