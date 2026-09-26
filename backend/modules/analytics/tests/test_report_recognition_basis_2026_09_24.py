"""自 `tests/test_report_recognition_basis_2026_09_24.py` 拆出（M08 搬遷反向控制：這幾題需要營運分析模組，拿掉模組時一起消失）。"""
import json
import pytest
from tests.test_report_recognition_basis_2026_09_24 import (  # noqa: E402,F401  含 fixture
    MO_INV,
    URL,
    _case,
    _db,
    _dispatch,
    _flag_quotes,
    _login,
    _mo,
    _month,
    _one_json,
    _report,
    _stage,
    sa,
)

from core import source_tree as _source_tree

#: 跨 M04×M08 的題（2026-09-26 第六班列車交會：外包工班與營運分析兩邊都把它搬進自己的 tests/，只留這一份）：
#: 同時需要外包工班；外包工班不在時略過——那時的行為（報表明說少了派工）由 test_reports_dispatch_row_consumer 負責。
needs_subcontract = pytest.mark.skipif(not _source_tree.module_installed("modules/subcontract/"),
                                       reason="需要外包工班模組（M04）")



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


@needs_subcontract
def test_dispatch_accrual_uses_invoice_month_and_pretax(client, sa):
    _case("MQ-RB-010")
    _dispatch("MQ-RB-010", total=10000, dispatch_date="2026-03-15", invoice_date="2026-05-03")
    body = _report(client, sa)
    assert _month(body, "2026-05", "contractor") == 10000, "權責：發票月、未稅"
    assert _month(body, "2026-03", "contractor") == 0


@needs_subcontract
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


@needs_subcontract
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


@needs_subcontract
def test_every_flag_kind_has_a_label_and_a_link(client, sa):
    _case("MQ-RB-070")
    _dispatch("MQ-RB-070")
    body = _report(client, sa)
    from helpers.recognition import FLAG_LABELS
    assert set(body["recognitionFlags"]) == set(FLAG_LABELS)
    it = [i for i in body["recognitionFlags"]["dispatch_no_invoice"]["items"] if i["quoteNo"] == "MQ-RB-070"][0]
    assert it["link"] == "case-management.html?q=MQ-RB-070&tab=dispatch"   # 2026-09-24 使用者裁：開對應分頁


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

    from modules.analytics.api.reports import (_augment_with_targets, _build_income_expense_scopes, _build_report_html,
                                 _collect, _parse_period)
    lab, d0, d1 = _parse_period("2026")
    data = _augment_with_targets(_collect(d0, d1, None), d0)
    data["arAging"] = []
    data.update(_build_income_expense_scopes(2026, "2026-03", None, basis=basis))
    html = _build_report_html(data, lab, "t")
    assert BASIS_NOTES[basis] in html


def test_material_invoice_date_can_be_entered_on_a_closed_case_without_touching_money(client, sa):
    _case("MQ-RB-022", deal="已結案", data={"caseRecord": {"materialOrders": [_mo()]}})
    assert client.patch("/api/quotations/MQ-RB-022/material-orders", headers=sa,
                        json={"materialOrders": [_mo("2026-04-20")]}).status_code == 400, "整份覆寫在已結案仍擋"
    assert "MQ-RB-022" in _flag_quotes(_report(client, sa), "material_no_invoice")
    r = client.patch(MO_INV % ("MQ-RB-022", "m1"), headers=sa, json={"invoiceDate": "2026-04-20"})
    assert r.status_code == 200, r.text
    mo = json.loads(_one_json("MQ-RB-022"))["caseRecord"]["materialOrders"][0]
    assert mo["invoiceDate"] == "2026-04-20"
    assert (mo["totalPrice"], mo["paidAmount"], mo["itemName"]) == (1000, 1000, "線材"), "其他欄位原封不動"
    assert "MQ-RB-022" not in _flag_quotes(_report(client, sa), "material_no_invoice")


@needs_subcontract
def test_dashboard_expenses_equal_the_report_accrual_numbers(client, sa, seed_extra_expense):
    from datetime import date
    today = date.today()
    mo = today.strftime("%Y-%m")
    _case("MQ-RB-080", data={"caseRecord": {"materialOrders": [dict(_mo(), paidDate=today.isoformat())]}})
    _dispatch("MQ-RB-080", total=10000, dispatch_date=today.isoformat())
    seed_extra_expense("MQ-RB-080", total_cost=700, category="運費", expense_date=today.isoformat())
    dash = client.get("/api/dashboard/expenses-monthly", headers=sa).json()
    assert dash["basis"] == "accrual"
    d = next(x for x in dash["items"] if x["month"] == mo)
    rpt = _report(client, sa, year=today.year, month=mo)
    r = next(x for x in rpt["expenses"]["monthly"] if x["month"] == mo)
    assert {k: d[k] for k in ("contractor", "equipment", "material", "other", "total")} == \
           {k: r[k] for k in ("contractor", "equipment", "material", "other", "total")}
    assert d["contractor"] >= 10000 and d["material"] >= 1000, "未稅派工＋叫料都要在"
    assert dash["otherBreakdown"][mo].get("運費", 0) >= 700
