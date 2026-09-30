# -*- coding: utf-8 -*-
"""費用單據 A2 第二段：類型（kind）／明細（lines）／data／收款人欄位在建立、編輯、變更申請、詳情、佇列、出納清單、金流讀取端的**不丟失**與金額規則。

契約：D:\\開發測試檔\\plan-expense-a2.md §7。驗：明細金額後端重算（qty×unitCost 優先、否則 amount）、總額＝Σ（整數 TWD）、未知鍵原樣保留、
data 合併不丟鍵、單號 `{前綴}-{YYYYMMDD}-{NNNN}`、kind 建立後不可改、請購單（purchase_req）不進出納／營運報表支出／總帳、
已核准後的變更申請帶得走明細與收款人（沉默丟資料清單）、舊版列（kind=''）提議不動新欄。"""
import json
from datetime import date

import pytest
from fastapi import HTTPException

from modules.case import expense_forms as EF

SENT = "/api/quotations/-/extra-expenses"
TODAY = date.today().strftime("%Y%m%d")


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _q(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _no_tiers():
    import db
    c = db.get_db()
    try:
        c.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                  ("unified_approval_flow", json.dumps({"tiers": [], "includeSubmitterManagerTier": False}), "2026-01-01T00:00:00"))
        c.commit()
    finally:
        c.close()


@pytest.fixture
def H(client, make_user):
    out = {}
    for u, role, mods in (("ef_form", "sales", ["expense_forms"]), ("ef_cash", "engineer", ["cashier", "finance"]), ("ef_admin", "admin", None)):
        name, pw = make_user(username=u, role=role, modules=mods)
        out[u] = _login(client, name, pw)
    return out


LINES = [{"category": "交通費", "summary": "停車費", "qty": 2, "unitCost": 150.5, "amount": 9999, "invoiceNo": "AB12345678", "customCol": "保留我"},
         {"category": "住宿費", "summary": "一晚", "amount": 3200, "memo": "不可丟"}]


def _create(client, h, kind="travel", **extra):
    body = {"kind": kind, "lines": LINES, "data": {"applicant": "ef_form", "dept": 7, "req_date": "2026-10-01", "freeKey": "x"}, **extra}
    r = client.post(SENT, headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ── 純函式：金額與保留鍵 ────────────────────────────────────────────────────

def test_lines_amount_authority_total_and_unknown_keys():
    clean, total = EF.normalize_lines(LINES)
    assert clean[0]["amount"] == 301 and clean[1]["amount"] == 3200 and total == 3501          # qty×unitCost 優先（301），前端的 9999 不採用
    assert clean[0]["customCol"] == "保留我" and clean[1]["memo"] == "不可丟"                     # 未知鍵原樣保留
    assert EF.normalize_lines(None) == ([], 0)
    for bad in ([{"amount": -1}], [{"amount": "12"}], [{"qty": 1, "unitCost": -5}], [{}], ["x"], [{"amount": True}]):
        with pytest.raises(HTTPException):
            EF.normalize_lines(bad)
    with pytest.raises(HTTPException):
        EF.normalize_lines([{"amount": 1}] * 201)


def test_data_merge_keeps_unsent_keys_and_none_deletes():
    base = {"a": 1, "b": 2, "dept": 3}
    assert EF.normalize_data({"b": 9}, base) == {"a": 1, "b": 9, "dept": 3}
    assert EF.normalize_data({"a": None}, base) == {"b": 2, "dept": 3}
    with pytest.raises(HTTPException):
        EF.normalize_data([1], base)
    assert EF.department_of({"dept": "7"}) == 7 and EF.department_of({"dept": 7}, 9) == 9 and EF.department_of({"dept": True}) is None


# ── API：建立／編輯 ─────────────────────────────────────────────────────────

def test_create_stores_everything_and_doc_code_is_sequential(client, H):
    a = _create(client, H["ef_form"])
    b = _create(client, H["ef_form"], kind="petty_cash")
    c = _create(client, H["ef_form"])
    assert a["docCode"] == "TE-%s-0001" % TODAY and c["docCode"] == "TE-%s-0002" % TODAY and b["docCode"] == "PC-%s-0001" % TODAY
    row = _q("SELECT * FROM case_extra_expenses WHERE id=?", (a["id"],))[0]
    assert row["kind"] == "travel" and row["total_cost"] == 3501 and row["department_id"] == 7 and row["quote_no"] == ""
    assert json.loads(row["lines_json"])[0]["customCol"] == "保留我" and json.loads(row["data_json"])["freeKey"] == "x"
    assert row["description"] == "停車費"                                                          # 沒給說明 ⇒ 取第一列摘要


def test_bad_kind_and_bad_payloads_write_nothing(client, H):
    n0 = _q("SELECT COUNT(*) AS n FROM case_extra_expenses")[0]["n"]
    for body in ({"kind": "nope", "lines": LINES}, {"kind": "travel", "lines": [{"amount": -5}]}, {"kind": "travel", "lines": "x"},
                 {"kind": "travel", "lines": LINES, "data": [1]}, {"kind": "travel", "lines": LINES, "payeeType": "alien"}):
        r = client.post(SENT, headers=H["ef_form"], json=body)
        assert r.status_code == 400, (body, r.status_code, r.text[:100])
    assert _q("SELECT COUNT(*) AS n FROM case_extra_expenses")[0]["n"] == n0


def test_update_merges_data_keeps_unknown_line_keys_and_kind_is_immutable(client, H):
    a = _create(client, H["ef_form"])
    eid = a["id"]
    r = client.patch("%s/%d" % (SENT, eid), headers=H["ef_form"], json={"data": {"urgency": "急"}, "lines": LINES + [{"category": "其他", "amount": 10, "x1": 1}],
                                                                        "payeeType": "employee", "payeeName": "王小明"})
    assert r.status_code == 200, r.text
    row = _q("SELECT * FROM case_extra_expenses WHERE id=?", (eid,))[0]
    d = json.loads(row["data_json"])
    assert d["freeKey"] == "x" and d["urgency"] == "急" and row["total_cost"] == 3511 and row["payee_name"] == "王小明" and row["payee_type"] == "employee"
    assert json.loads(row["lines_json"])[2]["x1"] == 1
    bad = client.patch("%s/%d" % (SENT, eid), headers=H["ef_form"], json={"kind": "petty_cash", "lines": LINES})
    assert bad.status_code == 400 and _q("SELECT kind FROM case_extra_expenses WHERE id=?", (eid,))[0]["kind"] == "travel"
    # 不送 lines ⇒ 沿用既有明細（不被清空）
    client.patch("%s/%d" % (SENT, eid), headers=H["ef_form"], json={"note": "只改備註"})
    assert len(json.loads(_q("SELECT lines_json FROM case_extra_expenses WHERE id=?", (eid,))[0]["lines_json"])) == 3


# ── 已核准後的變更申請：明細／收款人帶得走 ──────────────────────────────────

def _approve_now(client, h, eid):
    _no_tiers()
    r = client.post("%s/%d/submit" % (SENT, eid), headers=h)
    assert r.status_code == 200 and r.json()["status"] == "已核准", r.text


def test_change_request_carries_lines_data_and_payee(client, H):
    eid = _create(client, H["ef_form"])["id"]
    _approve_now(client, H["ef_form"], eid)
    new_lines = [{"category": "交通費", "summary": "改", "amount": 500, "keep": "k"}]
    r = client.put("%s/%d/change-request" % (SENT, eid), headers=H["ef_form"],
                   json={"description": "改", "lines": new_lines, "data": {"freeKey": "y"}, "payeeName": "李四", "payeeType": "vendor"})
    assert r.status_code == 200 and r.json()["totalCost"] == 500, r.text
    s = client.post("%s/%d/change-request/submit" % (SENT, eid), headers=H["ef_form"])
    assert s.status_code == 200, s.text                                   # 沒簽核層 ⇒ 直接套用
    row = _q("SELECT * FROM case_extra_expenses WHERE id=?", (eid,))[0]
    assert row["total_cost"] == 500 and json.loads(row["lines_json"]) == [dict(new_lines[0], amount=500)]
    assert json.loads(row["data_json"])["freeKey"] == "y" and row["payee_name"] == "李四" and row["payee_type"] == "vendor"
    hist = json.loads(row["approval_json"])["changeHistory"][-1]
    assert hist["from"]["lines"][0]["summary"] == "停車費" and hist["to"]["lines"][0]["summary"] == "改"     # 前後值都留


def test_legacy_row_change_request_does_not_touch_new_columns(client, H, seed_extra_expense):
    eid = seed_extra_expense("MQ-ZZ-LEG-1", total_cost=100, category="其他", description="舊", expense_date="2026-09-10")
    import db
    c = db.get_db()
    try:
        c.execute("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag)"
                  " VALUES ('MQ-ZZ-LEG-1','已送出','c','p',1,1,'{}','2026-01-01','2026-01-01','已成案')")
        c.execute("UPDATE case_extra_expenses SET lines_json=?, data_json=?, payee_name='原收款人' WHERE id=?",
                  (json.dumps([{"amount": 1, "sentinel": "s"}]), json.dumps({"k": "v"}), eid))
        c.commit()
    finally:
        c.close()
    _no_tiers()
    h = H["ef_admin"]
    r = client.put("/api/quotations/MQ-ZZ-LEG-1/extra-expenses/%d/change-request" % eid, headers=h, json={"description": "舊改", "qty": 1, "unitCost": 250})
    assert r.status_code == 200, r.text
    assert "lines" not in _q("SELECT change_json FROM case_extra_expenses WHERE id=?", (eid,))[0]["change_json"]
    client.post("/api/quotations/MQ-ZZ-LEG-1/extra-expenses/%d/change-request/submit" % eid, headers=h)
    row = _q("SELECT * FROM case_extra_expenses WHERE id=?", (eid,))[0]
    assert row["total_cost"] == 250 and json.loads(row["lines_json"])[0]["sentinel"] == "s" and row["payee_name"] == "原收款人"


# ── 金流讀取端：請購單不進、差旅進 ──────────────────────────────────────────

def test_purchase_req_is_not_payable_but_travel_is(client, H):
    req = _create(client, H["ef_form"], kind="purchase_req")["id"]
    trv = _create(client, H["ef_form"], kind="travel", payeeName="王小明", payeeType="employee")["id"]
    for eid in (req, trv):
        _approve_now(client, H["ef_form"], eid)
    pend = client.get("/api/cashier/pending-payables", headers=H["ef_cash"]).json()
    keys = {i["key"]: i for i in pend["items"]}
    assert str(req) not in keys and str(trv) in keys
    it = keys[str(trv)]
    assert it["kind"] == "travel" and it["docCode"].startswith("TE-") and it["payee"] == "王小明" and it["payeeType"] == "employee" and it["quoteNo"] == ""
    from modules.case import recognition as R
    import db
    c = db.get_db()
    try:
        ids = {e.get("id") or e.get("key") for e in R.extra_entries(c, "accrual")}
    finally:
        c.close()
    assert str(req) not in {str(i) for i in ids} and req not in ids
    from modules.case import gl_events as G
    d = date.today().isoformat()
    srcs = {e["source_key"] for e in G.gl_events(d, d)["events"] if e["source_type"] == "case_extra_expense"}
    assert str(req) not in srcs


# ── 佇列／詳情 ──────────────────────────────────────────────────────────────

def test_queue_item_and_detail_for_caseless(client, H):
    eid = _create(client, H["ef_form"])["id"]
    appr = {"requestedBy": "ef_form", "requestedByDisplay": "x", "requestedAt": "2026-10-01T10:00:00",
            "tiers": [{"order": 0, "approvers": [{"username": "ef_admin", "display_name": "a"}]}], "currentTier": 0}
    import db
    c = db.get_db()
    try:
        c.execute("UPDATE case_extra_expenses SET status='待審核', approval_json=? WHERE id=?", (json.dumps(appr), eid))
        c.commit()
        from modules.case.api import quotations as Q
        items = [i for i in Q.approval_queue_items(c) if i.get("extraExpenseId") == eid]
        det = Q.detail_extra_expense(c, eid)
    finally:
        c.close()
    (it,) = items
    assert it["linkedQuoteNo"] == "" and it["caseless"] is True and it["typeLabel"] == "差旅費用請款單"
    assert it["approveUrl"] == "/api/quotations/-/extra-expenses/%d/approve" % eid and it["rejectUrl"].endswith("/reject")
    assert it["quoteNo"].startswith("TE-") and not it["quoteNo"].startswith("-")
    assert det["caseless"] is True and len(det["items"]) == 2 and det["items"][0]["amount"] == 301 and det["title"].startswith("差旅費用請款單")


# ── 送審：費用類別驗證＋代碼／科目快照（W4 合約）；GL 事件行 ─────────────────────

CATS = [{"code": "TRAVEL", "name": "交通費", "default_tax": 0}, {"code": "LODGE", "name": "住宿費", "default_tax": 0}]


@pytest.fixture
def providers(monkeypatch):
    """假的 accounting 提供者：expense.categories（啟用的類別）、gl.category_account（類別→科目）。"""
    from core import registry
    real = registry.providers
    fake = {"expense.categories": {"accounting": lambda conn: CATS},
            "gl.category_account": {"accounting": lambda conn, k: {"TRAVEL": "6151", "LODGE": "6152"}.get(k)}}
    monkeypatch.setattr(registry, "providers", lambda name, *a, **k: fake[name] if name in fake else real(name, *a, **k))
    return fake


def _draft(client, h, lines, kind="travel", **extra):
    r = client.post(SENT, headers=h, json={"kind": kind, "lines": lines, "data": {"applicant": "ef_form"}, **extra})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_submit_rejects_unknown_category_but_draft_may_hold_anything(client, H, providers):
    _no_tiers()
    eid = _draft(client, H["ef_form"], [{"category": "不存在的類別", "amount": 100}])                 # 草稿：放什麼都行
    r = client.post("%s/%d/submit" % (SENT, eid), headers=H["ef_form"])
    assert r.status_code == 400 and "不是啟用中的類別" in r.json()["detail"]
    row = _q("SELECT status, lines_json FROM case_extra_expenses WHERE id=?", (eid,))[0]
    assert row["status"] == "草稿" and "categoryCode" not in row["lines_json"]                         # 狀態不變、明細沒被動


def test_submit_writes_category_code_name_and_account_snapshot(client, H, providers):
    _no_tiers()
    eid = _draft(client, H["ef_form"], [{"category": "交通費", "amount": 100, "keep": 1}, {"category": "LODGE", "amount": 200}])
    assert client.post("%s/%d/submit" % (SENT, eid), headers=H["ef_form"]).json()["status"] == "已核准"
    lines = json.loads(_q("SELECT lines_json FROM case_extra_expenses WHERE id=?", (eid,))[0]["lines_json"])
    assert [(l["categoryCode"], l["categoryName"], l["accountCode"]) for l in lines] == [("TRAVEL", "交通費", "6151"), ("LODGE", "住宿費", "6152")]
    assert lines[0]["keep"] == 1 and lines[0]["category"] == "交通費"                                   # 原欄位保留


def test_without_providers_nothing_is_validated_or_added(client, H):
    _no_tiers()
    eid = _draft(client, H["ef_form"], [{"category": "隨便", "amount": 100}])
    assert client.post("%s/%d/submit" % (SENT, eid), headers=H["ef_form"]).json()["status"] == "已核准"
    (l,) = json.loads(_q("SELECT lines_json FROM case_extra_expenses WHERE id=?", (eid,))[0]["lines_json"])
    assert "categoryCode" not in l and "accountCode" not in l


def test_gl_events_per_category_lines_and_payment_leg(client, H, providers):
    from modules.case import gl_events as G
    _no_tiers()
    eid = _draft(client, H["ef_form"], [{"category": "TRAVEL", "amount": 100}, {"category": "TRAVEL", "amount": 50}, {"category": "LODGE", "amount": 200}],
                 kind="petty_cash")
    client.post("%s/%d/submit" % (SENT, eid), headers=H["ef_form"])
    import db
    c = db.get_db()
    try:
        c.execute("UPDATE case_extra_expenses SET paid_date=?, pay_method='petty_cash', pay_account_code='1112' WHERE id=?", (date.today().isoformat(), eid))
        c.commit()
    finally:
        c.close()
    d = date.today().isoformat()
    ev = {e["event_code"]: e for e in G.gl_events(d, d)["events"] if e["source_key"] == str(eid)}
    acc = ev["E11"]["lines"]
    assert sorted((l["role"], l["side"], l["amount"], l.get("category")) for l in acc) == sorted([
        ("EXP_OTHER", "D", 150, "TRAVEL"), ("EXP_OTHER", "D", 200, "LODGE"), ("AP", "C", 350, None)])      # 無案件 ⇒ EXP_OTHER、逐類
    assert ev["E11"]["case_no"] == ""
    pay = ev["E11b"]["lines"]
    assert [(l["role"], l["side"], l["amount"]) for l in pay] == [("AP", "D", 350), ("PETTY", "C", 350)] and pay[-1]["account_code"] == "1112"


def test_gl_events_legacy_row_unchanged(client, H, seed_extra_expense):
    from modules.case import gl_events as G
    import db
    c = db.get_db()
    try:
        c.execute("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag)"
                  " VALUES ('MQ-GL-LEG','已送出','c','p',1,1,'{}','2026-01-01','2026-01-01','已成案')")
        c.commit()
    finally:
        c.close()
    eid = seed_extra_expense("MQ-GL-LEG", total_cost=300, category="運費", description="舊", expense_date=date.today().isoformat())
    d = date.today().isoformat()
    evs = [e for e in G.gl_events(d, d)["events"] if e["source_key"] == str(eid) and e["event_code"] == "E11"]
    assert evs and [(l["role"], l["side"], l["amount"]) for l in evs[0]["lines"]] == [("COST_PROJECT", "D", 300), ("AP", "C", 300)]
    assert all("category" not in l for l in evs[0]["lines"])
