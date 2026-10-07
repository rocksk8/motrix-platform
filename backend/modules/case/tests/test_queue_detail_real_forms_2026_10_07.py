# -*- coding: utf-8 -*-
"""簽核佇列詳情 × 四種費用單據（請購單／採購單／差旅費用請款單／零用金支付單）：用**真的 API** 存一張像使用者填的單，詳情要顯示使用者填的每個欄位。

欄位真正的來源（費用單據）：申請人／部門／事由／廠商…＝`data_json`（類型定義）；品項與金額＝`lines_json`；`qty`／`unit_cost`／`category`／`description`／`doc_no`／`payer_name`
欄位是舊版額外支出專用（費用單據是預設值或自動帶入）⇒ 詳情不顯示。金額欄位（小計、明細的單價與金額）仍受金額遮蔽規則約束。"""
import json

import pytest

from tests._requires import requires_module

pytestmark = requires_module("case", "額外支出在 M01")

_MAKE_USER_DEFAULT_ROLE = "superadmin"
SENT = "/api/quotations/-/extra-expenses"
LEGACY_ONLY = ("類別", "項目", "數量", "單價", "支出日期", "單據號碼", "支出人")

LINES = [{"category": "其他", "summary": "網路線 Cat6", "qty": 4, "unitCost": 150, "invoiceNo": "AB12345678"},
         {"category": "其他", "summary": "交換器", "qty": 1, "unitCost": 5200.5, "invoiceNo": "CD87654321"}]       # 小計 600 + 5201 = 5801

DOCS = {
    "purchase_req": {"data": {"ptype": "案件追加設備、零件", "urgency": "特急", "need_period": {"from": "2031-06-10", "to": "2031-06-20"}, "remark": "週五前到貨"},
                     "expect": {"採購類型": "案件追加設備、零件", "緊急程度": "特急", "需求日期": "2031-06-10 ～ 2031-06-20", "採購備註說明": "週五前到貨", "填表日期": "2031-06-01"}},
    "purchase_order": {"data": {"vendor": "甲廠商", "delivery_date": "2031-07-01", "urgency": "急件", "remark": "含運含稅", "pr_no": ""},
                       "expect": {"廠商": "甲廠商", "預計交貨日": "2031-07-01", "緊急程度": "急件", "備註": "含運含稅", "採購日期": "2031-06-01"}},
    "travel": {"data": {"place": "國內", "city": "台中", "period": {"from": "2031-06-03", "to": "2031-06-05"}, "pay_date": "2031-06-30", "remark": "客戶教育訓練"},
               "expect": {"地點": "國內", "國家／城市": "台中", "出差區間": "2031-06-03 ～ 2031-06-05", "付款日": "2031-06-30", "備註": "客戶教育訓練", "申請日期": "2031-06-01"}},
    "petty_cash": {"data": {"payee": "王小姐（文具行）", "remark": "辦公文具"},
                   "expect": {"支付對象／事由": "王小姐（文具行）", "備註": "辦公文具", "支付日期": "2031-06-01"}},
}


def _db():
    import db
    return db.get_db()


@pytest.fixture
def world(client, make_user):
    c = _db()
    try:
        c.execute("INSERT INTO divisions (name, created_at) VALUES ('營運處', '2026-01-01T00:00:00')")
        div = c.execute("SELECT id FROM divisions WHERE name='營運處'").fetchone()["id"]
        c.execute("INSERT INTO departments (division_id, name, created_at) VALUES (?, '工務部', '2026-01-01T00:00:00')", (div,))
        dept = c.execute("SELECT id FROM departments WHERE name='工務部'").fetchone()["id"]
        c.commit()
    finally:
        c.close()
    u, p = make_user(username="rf_boss", role="superadmin")
    c = _db()
    try:
        c.execute("UPDATE users SET display_name='陳經理' WHERE username=?", (u,))
        c.commit()
    finally:
        c.close()
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    return {"h": h, "dept": dept, "user": u}


def _save(client, w, kind):
    spec = DOCS[kind]
    data = dict(spec["data"], applicant=w["user"], dept=w["dept"], req_date="2031-06-01")
    if kind in ("travel", "petty_cash"):
        data["cost_dept"] = w["dept"]
    lines = LINES if kind != "petty_cash" else [{"category": "其他", "summary": "文具", "amount": 5801, "invoiceNo": "CD87654321"}]
    r = client.post(SENT, headers=w["h"], json={"kind": kind, "data": data, "lines": lines, "departmentId": w["dept"], "expenseDate": "2031-06-01"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _detail(client, w, eid):
    r = client.get("/api/approval-queue/detail", params={"type": "extra_expense", "id": str(eid)}, headers=w["h"])
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("kind", list(DOCS))
def test_detail_shows_every_field_the_user_filled_and_no_legacy_defaults(client, world, kind):
    d = _detail(client, world, _save(client, world, kind))
    f = {x["label"]: x["value"] for x in d["fields"]}
    for label, value in DOCS[kind]["expect"].items():
        assert f.get(label) == value, (kind, label, f.get(label))
    assert f["申請人"] == "陳經理" and f["部門"] == "工務部", "參照欄位轉成名稱，不顯示 id"
    for legacy in LEGACY_ONLY:
        assert legacy not in f, "%s：%s 是舊版專用欄位（費用單據是預設值）" % (kind, legacy)
    assert f["小計"] == "5,801" and f["發票／憑證號碼"] == "AB12345678、CD87654321" or kind == "petty_cash"
    if kind == "petty_cash":
        assert f["小計"] == "5,801" and f["發票／憑證號碼"] == "CD87654321"
    labels = [x["label"] for x in d["fields"]]
    assert len(labels) == len(set(labels)), "標籤不可重複（前端用標籤當 key）"
    assert labels[0] == "單號" and labels[1] == "類型"
    assert d["caseless"] if "caseless" in d else True


@pytest.mark.parametrize("kind", ["purchase_req", "purchase_order", "travel"])
def test_detail_items_table_has_qty_unit_price_and_amount(client, world, kind):
    d = _detail(client, world, _save(client, world, kind))
    it = d["items"]
    assert [x["description"] for x in it] == ["網路線 Cat6", "交換器"]
    assert [x["qty"] for x in it] == [4, 1] and [x["unitPrice"] for x in it] == [150, 5200.5] and [x["amount"] for x in it] == [600, 5201]
    assert "AB12345678" in it[0]["notes"]


def test_money_masking_still_applies_to_the_new_shape(client, world):
    """金額遮蔽（L1 `_mask_money`）：小計換成說明字串、明細不帶單價與金額；其他欄位照常顯示。"""
    from routers.approval_queue import _mask_money
    d = _detail(client, world, _save(client, world, "purchase_order"))
    out = {"fields": list(d["fields"]), "items": list(d["items"])}
    _mask_money(out)
    f = {x["label"]: x["value"] for x in out["fields"]}
    assert f["小計"] == "（無財務檢視權限）" and f["廠商"] == "甲廠商"
    assert all("unitPrice" not in x and "amount" not in x for x in out["items"])
    assert "5,801" not in json.dumps(out, ensure_ascii=False) and "5200" not in json.dumps(out, ensure_ascii=False)


def test_change_request_panel_has_no_misleading_zero_qty_or_price_for_typed_docs(client, world):
    eid = _save(client, world, "purchase_order")
    c = _db()
    try:
        c.execute("UPDATE case_extra_expenses SET status='已核准', change_status='pending', change_json=? WHERE id=?",
                  (json.dumps({"lines": LINES[:1], "totalCost": 600, "description": "改"}), eid))
        c.commit()
    finally:
        c.close()
    ch = _detail(client, world, eid)["changes"]
    for side in ("before", "after"):
        assert "數量" not in ch[side] and "單價" not in ch[side], side
    assert ch["before"]["小計"] == 5801 and ch["after"]["小計"] == 600 and ch["before"]["明細列數"] == 2 and ch["after"]["明細列數"] == 1


def test_pr_to_po_picker_copies_unit_price_only_for_viewers_who_may_see_money(client, make_user):
    """「單價沒有帶入採購單」查證：請購單明細的單價在挑選器 `GET …/purchase-requests/lines` 只回給看得到財務金額的人（第 44 班設計：不複製價格給看不到金額的人）；
    看得到的人，單價隨帶入列進採購單（前端 `row.unitCost = hit.line.unitCost`），存檔後明細保有單價。"""
    c = _db()
    try:
        uid = make_user(username="rf_member", role="sales", modules=["expense_forms"], legacy_finance_flag=False)
        c.execute("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag,"
                  " sales_person, assigned_user_ids) VALUES ('MQ-RF-001','已送出','客','案',1,1,'{}','2031-01-01','2031-01-01','已成案','rf_member','[]')")
        c.execute("INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, total_cost, expense_date, files_json, created_by, created_by_name,"
                  " payer_name, created_at, updated_at, status, kind, doc_code, data_json, lines_json, approval_json) VALUES ('MQ-RF-001','其他','x',0,'',0,5801,'2031-06-01','[]',"
                  "'rf_member','m','','2031-06-01','2031-06-01','已核准','purchase_req','PR-20310601-0009','{}',?, '{}')",
                  (json.dumps([{"category": "其他", "summary": "交換器", "qty": 2, "unitCost": 2900.5, "amount": 5801}]),))
        c.commit()
    finally:
        c.close()
    su, sp = make_user(username="rf_su2", role="superadmin")
    hs = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": su, "password": sp}).json()["token"]}
    hm = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": uid[0], "password": uid[1]}).json()["token"]}
    got = client.get("/api/quotations/MQ-RF-001/purchase-requests/lines", headers=hs).json()["requests"][0]["lines"][0]
    assert got["unitCost"] == 2900.5 and got["summary"] == "交換器" and got["qty"] == 2
    r = client.get("/api/quotations/MQ-RF-001/purchase-requests/lines", headers=hm)
    if r.status_code == 200 and r.json()["requests"]:
        assert "unitCost" not in r.json()["requests"][0]["lines"][0], "沒有財務金額可視權限 ⇒ 不帶價格（設計如此）"
    # 帶入列（含單價）存成採購單 ⇒ 明細保有單價，詳情的明細表顯示單價
    body = {"kind": "purchase_order", "data": {"vendor": "甲", "applicant": "rf_su2", "req_date": "2031-06-02", "urgency": "一般", "remark": "r", "fromPr": "PR-20310601-0009"},
            "lines": [{"category": "其他", "summary": "交換器", "qty": 2, "unitCost": 2900.5, "prDocCode": "PR-20310601-0009", "prLine": 1}]}
    r = client.post("/api/quotations/MQ-RF-001/extra-expenses", headers=hs, json=body)
    assert r.status_code == 201, r.text
    d = client.get("/api/approval-queue/detail", params={"type": "extra_expense", "id": str(r.json()["id"])}, headers=hs).json()
    assert d["items"][0]["unitPrice"] == 2900.5 and d["items"][0]["amount"] == 5801
