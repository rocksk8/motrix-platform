# -*- coding: utf-8 -*-
"""營運報表預設現金口徑＋收款手續費不重複扣（使用者 2026-09-30，正式機案件 MQ-202607-045）。

fixture＝正式機那一筆：第 2 期交貨款 應收 263,828、9/1 已收、實收（銀行入帳）263,813、手續費 15（客戶內扣）。
規則（`helpers.tax_calc.receipt_amounts`，單一定義）：
  bank＝actualAmount（沒填＝應收−手續費）；收入(含稅)＝bank＋手續費＝263,828；淨額＝bank＝263,813（**不再減手續費**）；
  手續費 15 以 IP-9 expense.entries 列支出（收款日、類別「收款手續費」）；損益＝收入−手續費＝263,813＝銀行。
使用者原本看到「淨 263,798」＝263,813−15：手續費被扣兩次。
"""
import pytest

from core import source_tree
from modules.analytics.tests.test_payment_anomalies_2026_09_11 import _login, _auth, _make_case_with_payments

_NEEDS = pytest.mark.skipif(
    not (source_tree.module_installed("modules/arap/") and source_tree.module_installed("modules/case/")),
    reason="需要應收應付（M05）與案件（M01）")

QNO = "MQ-202607-045-T"


def _seed(actual=263813, fee=15, amount=263828):
    _make_case_with_payments(QNO, [{
        "type": "第2期交貨款", "received": True, "receivedAt": "2026-09-01", "amount": amount,
        "actualAmount": actual, "feeAmount": fee, "expectedReceiptDate": "", "invoiceNo": "", "note": ""}],
        total=879427)


def test_receipt_amounts_is_the_single_definition():
    from helpers import receipt_amounts
    assert receipt_amounts(263828, 263813, 15) == (263813, 263828, 15)       # 銀行入帳／收入／手續費
    assert receipt_amounts(100, None, 5) == (95, 100, 5)                      # 沒填實收：應收−手續費（舊行為）
    assert receipt_amounts(100, None, 0) == (100, 100, 0)
    assert receipt_amounts(100, 90, None) == (90, 90, 0)                      # 短收、沒手續費：入帳＝收入
    assert receipt_amounts(100, 0, 0) == (0, 0, 0)                            # 實收 0 是合法值（is None 判斷，不是真假值）


@_NEEDS
def test_default_basis_is_cash_and_income_expense_and_profit_agree_with_the_bank(client, make_user):
    u, pw = make_user(username="rc_su1", role="superadmin")
    tok = _login(client, u, pw)
    _seed()
    d = client.get("/api/reports/expenses-monthly?year=2026&month=2026-09", headers=_auth(tok)).json()
    assert d["basis"] == "cash", "預設口徑要是現金（依收付款日、含稅）"
    assert d["incomeTaxLabel"] == "含稅"
    hit = [i for i in d["monthIncomeItems"] if i["quoteNo"] == QNO]
    assert len(hit) == 1
    assert hit[0]["amount"] == 263828 and hit[0]["netAmount"] == 263813 and hit[0]["feeAmount"] == 15
    assert d["monthIncomeTotal"] == 263828 and d["monthIncomeNet"] == 263813
    fees = [e for e in d["monthExpenseItems"] if e.get("category") == "收款手續費"]
    assert len(fees) == 1 and fees[0]["amount"] == 15 and fees[0]["quoteNo"] == QNO, d["monthExpenseItems"]
    assert d["monthExpenseTotal"] == 15
    assert d["monthIncomeTotal"] - d["monthExpenseTotal"] == 263813, "損益要等於銀行入帳（手續費只扣一次）"


@_NEEDS
def test_accrual_switch_still_follows_stage_completion_and_keeps_the_receipt_compare(client, make_user):
    u, pw = make_user(username="rc_su2", role="superadmin")
    tok = _login(client, u, pw)
    _seed()
    a = client.get("/api/reports/expenses-monthly?year=2026&month=2026-09&basis=accrual", headers=_auth(tok)).json()
    assert a["basis"] == "accrual"
    assert not [i for i in a["monthIncomeItems"] if i["quoteNo"] == QNO], "階段未完成：權責收入仍是 0（切換行為不變）"
    cmp_ = [i for i in a["monthCashReceiptItems"] if i["quoteNo"] == QNO]
    assert cmp_ and cmp_[0]["amount"] == 263828 and cmp_[0]["netAmount"] == 263813
    # 手續費是現金事件：兩口徑都列支出
    assert [e for e in a["monthExpenseItems"] if e.get("category") == "收款手續費"]


@_NEEDS
def test_collection_summary_net_is_the_bank_amount_not_bank_minus_fee(client, make_user):
    u, pw = make_user(username="rc_su3", role="superadmin")
    tok = _login(client, u, pw)
    _seed()
    d = client.get("/api/reports/financial?period=2026-09", headers=_auth(tok)).json()
    s = d["summary"]
    assert s["periodReceived"] == 263828 and s["periodFee"] == 15
    assert s["periodNet"] == 263813, "以前是 263,798（實收 263,813 再減手續費 15）"
    assert s["netCollected"] == 263813
    it = [i for i in d["periodItems"] if i["quoteNo"] == QNO][0]
    assert it["netAmount"] == 263813


@_NEEDS
def test_actual_not_filled_falls_back_to_receivable_minus_fee(client, make_user):
    u, pw = make_user(username="rc_su4", role="superadmin")
    tok = _login(client, u, pw)
    _make_case_with_payments("MQ-RC-NOACT", [{
        "type": "頭期款", "received": True, "receivedAt": "2026-09-02", "amount": 100000,
        "feeAmount": 30, "expectedReceiptDate": "", "invoiceNo": "", "note": ""}])
    d = client.get("/api/reports/financial?period=2026-09", headers=_auth(tok)).json()
    it = [i for i in d["periodItems"] if i["quoteNo"] == "MQ-RC-NOACT"][0]
    assert it["netAmount"] == 99970
    c = client.get("/api/reports/expenses-monthly?year=2026&month=2026-09&basis=cash", headers=_auth(tok)).json()
    hit = [i for i in c["monthIncomeItems"] if i["quoteNo"] == "MQ-RC-NOACT"][0]
    assert hit["amount"] == 100000 and hit["netAmount"] == 99970


@_NEEDS
def test_excel_export_defaults_to_cash_and_carries_the_bank_net(client, make_user):
    import io
    import openpyxl
    u, pw = make_user(username="rc_su5", role="superadmin")
    tok = _login(client, u, pw)
    _seed()
    r = client.get("/api/reports/financial/excel?period=2026-09&expense_month=2026-09", headers=_auth(tok))
    assert r.status_code == 200, r.text[:200]
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    texts = " ".join(str(c.value) for ws in wb for row in ws.iter_rows() for c in row if c.value is not None)
    assert "現金口徑" in texts, "匯出的口徑說明要是現金（預設）"
    assert "263813" in texts.replace(",", "") and "263798" not in texts.replace(",", "")


def _t100_lines(quote_no):
    from modules.accounting.api import accounting_export as ax
    evs = [e for e in ax._collect_t100_events("2026-09-01", "2026-09-30") if e["sourceKey"].startswith(quote_no + "::")]
    assert len(evs) == 1, evs
    return evs[0]["lines"]


@_NEEDS
def test_t100_receipt_voucher_is_balanced_with_a_fee_line(client):
    """借 銀行(入帳)＋借 手續費／貸 收入(未稅)＋貸 銷項稅額：借貸相等；入帳＝含稅−手續費。"""
    from modules.arap import receivables
    _make_case_with_payments("MQ-RC-T100", [{
        "type": "交貨款", "received": True, "receivedAt": "2026-09-01", "amount": 105000,
        "actualAmount": 104985, "feeAmount": 15, "invoiceNo": "AB12345678", "expectedReceiptDate": "", "note": ""}],
        total=105000)
    inv = [i for i in receivables.collect_tax_invoices() if i["quoteNo"] == "MQ-RC-T100"][0]
    assert inv["feeAmount"] == 15 and inv["bankAmount"] == inv["amountTotal"] - 15
    lines = _t100_lines("MQ-RC-T100")
    debit = sum(l["debit"] or 0 for l in lines)
    credit = sum(l["credit"] or 0 for l in lines)
    assert debit == credit and debit == inv["amountTotal"], (debit, credit, lines)
    bank = [l for l in lines if l["acctName"] not in ("收款手續費支出", "銷貨收入", "銷項稅額")][0]
    fee = [l for l in lines if l["acctName"] == "收款手續費支出"][0]
    assert bank["debit"] == inv["amountTotal"] - 15 and fee["debit"] == 15


@_NEEDS
def test_t100_receipt_without_fee_is_exactly_the_old_voucher(client):
    _make_case_with_payments("MQ-RC-T100B", [{
        "type": "交貨款", "received": True, "receivedAt": "2026-09-01", "amount": 105000,
        "invoiceNo": "AB12345679", "expectedReceiptDate": "", "note": ""}], total=105000)
    lines = _t100_lines("MQ-RC-T100B")
    assert not [l for l in lines if l["acctName"] == "收款手續費支出"]
    assert sum(l["debit"] or 0 for l in lines) == sum(l["credit"] or 0 for l in lines) == 105000
