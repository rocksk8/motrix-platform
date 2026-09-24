# -*- coding: utf-8 -*-
"""營運報表的認列口徑（權責／現金）與「待補登」標註（2026-09-24 使用者規則＋hichan-0a 細部裁示）。

```
權責（預設）  收入＝成交未稅 × 階段比例，認列在階段完成月；沒設比例 ⇒ 全部完工月；沒完工 ⇒ 不認列
              支出＝廠商發票月；沒登錄 ⇒ 暫用核准／完工月並標註；拆得出稅用未稅
現金          收入＝收款日（含稅）；派工＝匯款申請已匯款日；叫料＝付款日；額外支出＝付款日→憑證日
標註          每一種：有狀況 ⇒ 出現；補登後 ⇒ 消失
```
"""
import json

import pytest

URL = "/api/reports/expenses-monthly"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def sa(client, make_user):
    return _login(client, *make_user(username="rb_sa", role="superadmin"))


def _db():
    import db
    return db.get_db()


def _case(no, pretax=10000, total=10500, data=None, deal="已成案"):
    data = dict(data or {})
    data.setdefault("dealTag", deal)
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (no, "已送出", "認列客戶", "認列專案", total, pretax, json.dumps(data, ensure_ascii=False),
             "2026-01-01", "2026-01-01", deal))
        conn.commit()
    finally:
        conn.close()


def _stage(no, label, done=False, done_at="", ratio=None, order=0):
    conn = _db()
    try:
        cur = conn.execute(
            "INSERT INTO case_stages (quote_no, label, sort_order, done, done_at, start_date, due_date,"
            " assigned_to, depends_on, created_at, updated_at, ratio_bp) VALUES (?,?,?,?,?,'','','[]','[]','t','t',?)",
            (no, label, order, 1 if done else 0, done_at, ratio))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _dispatch(no, total=10000, dispatch_date="2026-03-15", invoice_date="", accepted_at=""):
    conn = _db()
    try:
        conn.execute("INSERT OR IGNORE INTO vendor_contractors (name, active, created_at) VALUES ('認列承攬商',1,'t')")
        vid = conn.execute("SELECT id FROM vendor_contractors WHERE name='認列承攬商'").fetchone()["id"]
        cur = conn.execute(
            "INSERT INTO contractor_dispatches (quote_no, vendor_id, dispatch_date, scope, items_json, total_amount,"
            " status, created_at, updated_at, invoice_date, accepted_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (no, vid, dispatch_date, "s", "[]", total, "confirmed", "t", "t", invoice_date, accepted_at))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _report(client, hdr, basis=None, month="2026-03", year=2026):
    q = "%s?year=%s&month=%s" % (URL, year, month) + ("&basis=%s" % basis if basis else "")
    r = client.get(q, headers=hdr)
    assert r.status_code == 200, r.text
    return r.json()


def _month(body, mo, key):
    return next(m for m in body["expenses"]["monthly"] if m["month"] == mo)[key]


def _flag_quotes(body, kind):
    return [i["quoteNo"] for i in body["recognitionFlags"][kind]["items"]]


# ══════════════════════════════════════════════════════════════════════
# 收入：純函式
# ══════════════════════════════════════════════════════════════════════

def _rev(stages, pretax=10000):
    from helpers.recognition import stage_revenue
    return stage_revenue(pretax, stages)


def test_no_ratio_all_done_recognizes_everything_in_the_last_done_month():
    r = _rev([{"label": "a", "done": True, "doneAt": "2026-02-10", "ratioBp": None},
              {"label": "b", "done": True, "doneAt": "2026-04-01", "ratioBp": None}])
    assert [(e["date"], e["amount"]) for e in r["entries"]] == [("2026-04-01", 10000)]
    assert r["flags"] == {"stage_ratio_unset"}


def test_no_ratio_not_all_done_is_not_recognized():
    r = _rev([{"label": "a", "done": True, "doneAt": "2026-02-10", "ratioBp": None},
              {"label": "b", "done": False, "doneAt": "", "ratioBp": None}])
    assert r["entries"] == [] and r["unrecognized"] == 10000
    assert r["flags"] == {"stage_ratio_unset", "case_incomplete"}


def test_ratios_recognize_each_done_stage_in_its_month():
    r = _rev([{"label": "a", "done": True, "doneAt": "2026-02-10", "ratioBp": 3000},
              {"label": "b", "done": False, "doneAt": "", "ratioBp": 7000}])
    assert [(e["label"], e["date"], e["amount"]) for e in r["entries"]] == [("a", "2026-02-10", 3000)]
    assert r["flags"] == {"case_incomplete"} and r["unrecognized"] == 7000


def test_ratios_not_adding_to_100_are_flagged_and_not_topped_up():
    r = _rev([{"label": "a", "done": True, "doneAt": "2026-02-10", "ratioBp": 3000},
              {"label": "b", "done": True, "doneAt": "2026-03-10", "ratioBp": 6000}])
    assert sum(e["amount"] for e in r["entries"]) == 9000, "不補差"
    assert r["flags"] == {"stage_ratio_not_100"}


def test_zero_ratio_is_set_not_unset():
    """0＝這個階段不認列；None＝未設——兩件事（null≠0）。"""
    r = _rev([{"label": "a", "done": True, "doneAt": "2026-02-10", "ratioBp": 0},
              {"label": "b", "done": True, "doneAt": "2026-03-10", "ratioBp": 10000}])
    assert "stage_ratio_unset" not in r["flags"]
    assert [(e["label"], e["amount"]) for e in r["entries"]] == [("b", 10000)]


def test_all_zero_ratios_recognize_nothing_rather_than_everything():
    """全部設 0：比例「有設」而合計 0% ⇒ 不認列、標 ≠100%；**不可以**退回「未設 ⇒ 完工月一次認列」。"""
    r = _rev([{"label": "a", "done": True, "doneAt": "2026-02-10", "ratioBp": 0}])
    assert r["entries"] == []
    assert r["flags"] == {"stage_ratio_not_100"}


def test_done_without_a_date_is_not_recognized():
    r = _rev([{"label": "a", "done": True, "doneAt": "", "ratioBp": None}])
    assert r["entries"] == [] and "case_incomplete" in r["flags"]


def test_rounding_is_half_up_not_bankers():
    r = _rev([{"label": "a", "done": True, "doneAt": "2026-02-10", "ratioBp": 5000},
              {"label": "b", "done": False, "doneAt": "", "ratioBp": 5000}], pretax=5)
    assert r["entries"][0]["amount"] == 3   # 2.5 → 3（round() 會給 2）


# ══════════════════════════════════════════════════════════════════════
# 收入：報表
# ══════════════════════════════════════════════════════════════════════

def test_accrual_income_is_pretax_by_stage_month_and_cash_income_is_received(client, sa):
    data = {"caseRecord": {"payment": {"items": [
        {"id": 1, "type": "訂金", "amount": 10500, "received": True, "receivedAt": "2026-05-02",
         "actualAmount": 10500}]}}}
    _case("MQ-RB-001", pretax=10000, total=10500, data=data)
    _stage("MQ-RB-001", "施工", done=True, done_at="2026-03-20", ratio=6000, order=0)
    _stage("MQ-RB-001", "驗收", done=False, ratio=4000, order=1)
    body = _report(client, sa)
    assert body["basis"] == "accrual" and body["incomeTaxLabel"] == "未稅"
    got = [(i["quoteNo"], i["type"], i["amount"]) for i in body["monthIncomeItems"] if i["quoteNo"] == "MQ-RB-001"]
    assert got == [("MQ-RB-001", "施工", 6000)]
    cash = _report(client, sa, basis="cash", month="2026-05")
    assert cash["incomeTaxLabel"] == "含稅"
    assert [(i["quoteNo"], i["amount"]) for i in cash["monthIncomeItems"] if i["quoteNo"] == "MQ-RB-001"] == [
        ("MQ-RB-001", 10500)]
    assert "權責" in body["basisNote"] and "舊版" in body["basisNote"]


def test_bad_basis_is_refused(client, sa):
    assert client.get(URL + "?year=2026&basis=foo", headers=sa).status_code == 400


# ══════════════════════════════════════════════════════════════════════
# 派工
# ══════════════════════════════════════════════════════════════════════

def test_dispatch_accrual_uses_invoice_month_and_pretax(client, sa):
    _case("MQ-RB-010")
    _dispatch("MQ-RB-010", total=10000, dispatch_date="2026-03-15", invoice_date="2026-05-03")
    body = _report(client, sa)
    assert _month(body, "2026-05", "contractor") == 10000, "權責：發票月、未稅"
    assert _month(body, "2026-03", "contractor") == 0


def test_dispatch_without_invoice_falls_back_and_is_flagged_until_entered(client, sa):
    _case("MQ-RB-011")
    did = _dispatch("MQ-RB-011", dispatch_date="2026-03-15", accepted_at="2026-04-02T10:00:00")
    body = _report(client, sa)
    assert _month(body, "2026-04", "contractor") == 10000, "沒發票 ⇒ 暫用驗收月"
    d = [x for x in body["expenses"]["details"]["contractor"] if x["quoteNo"] == "MQ-RB-011"]
    assert d[0]["provisional"] is True and d[0]["taxNote"] == "未稅"
    assert "MQ-RB-011" in _flag_quotes(body, "dispatch_no_invoice")
    # 已有匯款申請（PUT 會 409）也登得進去
    conn = _db()
    try:
        conn.execute("INSERT INTO contractor_payment_vouchers (voucher_no, dispatch_id, quote_no, status,"
                     " created_at, updated_at) VALUES ('CPV-RB-1', ?, 'MQ-RB-011', '草稿', 't', 't')", (did,))
        conn.commit()
    finally:
        conn.close()
    r = client.patch("/api/contractor-dispatches/%s/invoice-date" % did, headers=sa,
                     json={"invoiceDate": "2026-06-01"})
    assert r.status_code == 200, r.text
    body = _report(client, sa)
    assert "MQ-RB-011" not in _flag_quotes(body, "dispatch_no_invoice")
    assert _month(body, "2026-06", "contractor") == 10000


def test_dispatch_invoice_date_is_validated(client, sa):
    _case("MQ-RB-012")
    did = _dispatch("MQ-RB-012")
    for bad in ("2026-13-01", "2026/03/01", "20260301"):
        r = client.patch("/api/contractor-dispatches/%s/invoice-date" % did, headers=sa, json={"invoiceDate": bad})
        assert r.status_code == 400, bad


def test_dispatch_cash_uses_paid_voucher_with_tax(client, sa):
    _case("MQ-RB-013")
    did = _dispatch("MQ-RB-013")
    conn = _db()
    try:
        conn.execute("INSERT INTO contractor_payment_vouchers (voucher_no, dispatch_id, quote_no, status,"
                     " snapshot_json, is_paid, paid_at, created_at, updated_at)"
                     " VALUES ('CPV-RB-2', ?, 'MQ-RB-013', '已核准', ?, 1, '2026-07-08T09:00:00', 't', 't')",
                     (did, json.dumps({"grandTotal": 10500, "vendorName": "認列承攬商"})))
        conn.commit()
    finally:
        conn.close()
    body = _report(client, sa, basis="cash")
    assert _month(body, "2026-07", "contractor") == 10500
    assert _month(body, "2026-03", "contractor") == 0, "現金口徑不看派工日"


# ══════════════════════════════════════════════════════════════════════
# 叫料
# ══════════════════════════════════════════════════════════════════════

def _mo(invoice=""):
    return {"itemId": "m1", "itemName": "線材", "quantity": 10, "unit": "捲", "unitPrice": 100,
            "totalPrice": 1000, "paidStatus": "paid", "paidAmount": 1000, "paidDate": "2026-03-09",
            "notes": "", "invoiceDate": invoice}


def test_material_orders_are_counted_and_flag_clears_after_invoice(client, sa):
    _case("MQ-RB-020", data={"caseRecord": {"materialOrders": [_mo()]}})
    body = _report(client, sa)
    assert _month(body, "2026-03", "material") == 1000, "叫料原本沒算；沒發票 ⇒ 暫用付款月"
    assert "MQ-RB-020" in _flag_quotes(body, "material_no_invoice")
    r = client.patch("/api/quotations/MQ-RB-020/material-orders", headers=sa,
                     json={"materialOrders": [_mo("2026-04-20")]})
    assert r.status_code == 200, r.text
    body = _report(client, sa)
    assert "MQ-RB-020" not in _flag_quotes(body, "material_no_invoice")
    assert _month(body, "2026-04", "material") == 1000 and _month(body, "2026-03", "material") == 0


def test_material_invoice_date_is_validated(client, sa):
    _case("MQ-RB-021", data={"caseRecord": {"materialOrders": []}})
    r = client.patch("/api/quotations/MQ-RB-021/material-orders", headers=sa,
                     json={"materialOrders": [_mo("2026-02-30")]})
    assert r.status_code == 400, r.text


# ══════════════════════════════════════════════════════════════════════
# 額外支出
# ══════════════════════════════════════════════════════════════════════

def test_extra_expense_invoice_and_paid_date_flags_clear_after_entry(client, sa, seed_extra_expense):
    _case("MQ-RB-030")
    eid = seed_extra_expense("MQ-RB-030", total_cost=800, description="吊車", expense_date="2026-03-02")
    conn = _db()
    try:
        conn.execute("UPDATE case_extra_expenses SET approval_json=? WHERE id=?", (json.dumps(
            {"tiers": [{"approvers": [{"username": "x", "approvedAt": "2026-04-11T08:00:00"}]}]}), eid))
        conn.commit()
    finally:
        conn.close()
    body = _report(client, sa)
    assert _month(body, "2026-04", "other") == 800, "沒發票 ⇒ 暫用核准月"
    assert "MQ-RB-030" in _flag_quotes(body, "extra_no_invoice")
    assert "MQ-RB-030" in _flag_quotes(body, "extra_no_paid_date")
    cash = _report(client, sa, basis="cash")
    assert _month(cash, "2026-03", "other") == 800, "現金：沒付款日 ⇒ 暫用憑證日"

    r = client.patch("/api/quotations/MQ-RB-030/extra-expenses/%s/dates" % eid, headers=sa,
                     json={"invoiceDate": "2026-05-05", "paidDate": "2026-06-06"})
    assert r.status_code == 200, r.text
    body = _report(client, sa)
    assert "MQ-RB-030" not in _flag_quotes(body, "extra_no_invoice")
    assert "MQ-RB-030" not in _flag_quotes(body, "extra_no_paid_date")
    assert _month(body, "2026-05", "other") == 800
    assert _month(_report(client, sa, basis="cash"), "2026-06", "other") == 800


def test_extra_expense_dates_can_be_entered_after_approval_but_not_by_strangers(
        client, sa, make_user, seed_extra_expense):
    _case("MQ-RB-031")
    eid = seed_extra_expense("MQ-RB-031", total_cost=500, expense_date="2026-03-02", status="已核准")
    other = _login(client, *make_user(username="rb_other", role="admin"))
    assert client.patch("/api/quotations/MQ-RB-031/extra-expenses/%s/dates" % eid, headers=other,
                        json={"paidDate": "2026-03-03"}).status_code == 200, "admin 可以"
    stranger = _login(client, *make_user(username="rb_eng", role="engineer", modules=["case_manage"]))
    r = client.patch("/api/quotations/MQ-RB-031/extra-expenses/%s/dates" % eid, headers=stranger,
                     json={"paidDate": "2026-03-03"})
    assert r.status_code in (403, 404), r.text
    assert client.patch("/api/quotations/MQ-RB-031/extra-expenses/%s/dates" % eid, headers=sa,
                        json={"paidDate": "03/03/2026"}).status_code == 400


# ══════════════════════════════════════════════════════════════════════
# 階段比例與完工
# ══════════════════════════════════════════════════════════════════════

def test_stage_ratio_flags_follow_what_is_entered(client, sa):
    _case("MQ-RB-040")
    a = _stage("MQ-RB-040", "施工", done=True, done_at="2026-03-01", order=0)
    b = _stage("MQ-RB-040", "驗收", done=False, order=1)
    body = _report(client, sa)
    assert "MQ-RB-040" in _flag_quotes(body, "stage_ratio_unset")
    assert "MQ-RB-040" in _flag_quotes(body, "case_incomplete")

    put = "/api/quotations/MQ-RB-040/stages/%s"
    assert client.put(put % a, headers=sa, json={"ratioBp": 5000}).json()["ratioBp"] == 5000
    assert client.put(put % b, headers=sa, json={"ratioBp": 4000}).status_code == 200
    body = _report(client, sa)
    assert "MQ-RB-040" not in _flag_quotes(body, "stage_ratio_unset")
    assert "MQ-RB-040" in _flag_quotes(body, "stage_ratio_not_100")

    client.put(put % b, headers=sa, json={"ratioBp": 5000, "done": True, "doneAt": "2026-03-30"})
    body = _report(client, sa)
    assert "MQ-RB-040" not in _flag_quotes(body, "stage_ratio_not_100")
    assert "MQ-RB-040" not in _flag_quotes(body, "case_incomplete")


@pytest.mark.parametrize("bad", [10001, -1, 12.5, "abc", True])
def test_stage_ratio_is_validated(client, sa, bad):
    _case("MQ-RB-041")
    sid = _stage("MQ-RB-041", "施工")
    assert client.put("/api/quotations/MQ-RB-041/stages/%s" % sid, headers=sa,
                      json={"ratioBp": bad}).status_code == 400


def test_stage_ratio_can_be_cleared_back_to_unset(client, sa):
    _case("MQ-RB-042")
    sid = _stage("MQ-RB-042", "施工", ratio=10000)
    r = client.put("/api/quotations/MQ-RB-042/stages/%s" % sid, headers=sa, json={"ratioBp": None})
    assert r.status_code == 200 and r.json()["ratioBp"] is None


# ══════════════════════════════════════════════════════════════════════
# 舊稅率單、金額遮蔽
# ══════════════════════════════════════════════════════════════════════

def test_legacy_tax_rate_case_is_flagged_until_changed(client, sa):
    _case("MQ-RB-050", data={"taxRate": 3})
    assert "MQ-RB-050" in _flag_quotes(_report(client, sa), "legacy_tax")
    conn = _db()
    try:
        conn.execute("UPDATE quotations SET data_json=? WHERE quote_no='MQ-RB-050'",
                     (json.dumps({"dealTag": "已成案", "taxRate": 5, "taxType": "taxable"}),))
        conn.commit()
    finally:
        conn.close()
    assert "MQ-RB-050" not in _flag_quotes(_report(client, sa), "legacy_tax")


def test_flag_amounts_are_hidden_without_financial_view(client, make_user):
    _case("MQ-RB-060")
    _dispatch("MQ-RB-060")
    hdr = _login(client, *make_user(username="rb_rpt_eng", role="engineer", modules=["reports"]))
    body = _report(client, hdr)
    items = body["recognitionFlags"]["dispatch_no_invoice"]["items"]
    mine = [i for i in items if i["quoteNo"] == "MQ-RB-060"]
    assert mine and mine[0]["amount"] is None
    sa_hdr = _login(client, *make_user(username="rb_sa2", role="superadmin"))
    mine = [i for i in _report(client, sa_hdr)["recognitionFlags"]["dispatch_no_invoice"]["items"]
            if i["quoteNo"] == "MQ-RB-060"]
    assert mine[0]["amount"] == 10000


def test_every_flag_kind_has_a_label_and_a_link(client, sa):
    _case("MQ-RB-070")
    _dispatch("MQ-RB-070")
    body = _report(client, sa)
    from helpers.recognition import FLAG_LABELS
    assert set(body["recognitionFlags"]) == set(FLAG_LABELS)
    it = [i for i in body["recognitionFlags"]["dispatch_no_invoice"]["items"] if i["quoteNo"] == "MQ-RB-070"][0]
    assert it["link"] == "case-management.html?q=MQ-RB-070"


def test_a_dispatch_put_without_the_invoice_date_key_keeps_it(client, sa):
    """其他頁面的 PUT 沒帶 invoice_date ⇒ 保留原值（不可以被清成未登錄）。"""
    _case("MQ-RB-014")
    did = _dispatch("MQ-RB-014", invoice_date="2026-05-03")
    body = {"quote_no": "MQ-RB-014", "vendor_id": None, "personnel_json": [{"name": "甲", "amount": 100}],
            "dispatch_date": "2026-03-15"}
    assert client.put("/api/contractor-dispatches/%s" % did, headers=sa, json=body).status_code == 200
    conn = _db()
    try:
        assert conn.execute("SELECT invoice_date FROM contractor_dispatches WHERE id=?", (did,)).fetchone()[0] == "2026-05-03"
    finally:
        conn.close()
    body["invoice_date"] = ""
    assert client.put("/api/contractor-dispatches/%s" % did, headers=sa, json=body).status_code == 200
    conn = _db()
    try:
        assert conn.execute("SELECT invoice_date FROM contractor_dispatches WHERE id=?", (did,)).fetchone()[0] == ""
    finally:
        conn.close()


@pytest.mark.parametrize("basis,label", [("accrual", "認列金額（未稅）"), ("cash", "應收金額（含稅）")])
def test_exports_label_tax_basis_and_carry_the_note(client, sa, basis, label):
    import io
    import openpyxl
    r = client.get("/api/reports/financial/excel?period=2026&expense_month=2026-03&basis=%s" % basis, headers=sa)
    assert r.status_code == 200, r.text
    ws = openpyxl.load_workbook(io.BytesIO(r.content))["當月收支"]
    cells = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    assert label in cells
    from helpers.recognition import BASIS_NOTES
    assert BASIS_NOTES[basis] in cells

    from routers.reports import (_augment_with_targets, _build_income_expense_scopes, _build_report_html,
                                 _collect, _parse_period)
    lab, d0, d1 = _parse_period("2026")
    data = _augment_with_targets(_collect(d0, d1, None), d0)
    data["arAging"] = []
    data.update(_build_income_expense_scopes(2026, "2026-03", None, basis=basis))
    html = _build_report_html(data, lab, "t")
    assert BASIS_NOTES[basis] in html
