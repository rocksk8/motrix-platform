"""收款日期「2026/09/01」等寫法不可被收入報表靜默漏掉；非成案案件的已收款、日期讀不懂的要被點名；
權責視圖附「實收對照」（依收款日），讓階段未設／尾款未結而權責認列 0 的已收款看得見（正式機 MQ-202607-045 交貨款的形狀）。
"""
import pytest

from core import source_tree
from modules.analytics.tests.test_payment_anomalies_2026_09_11 import (
    _login, _auth, _make_case_with_payments, _item, _anomalies)

_NEEDS_ARAP = pytest.mark.skipif(not source_tree.module_installed("modules/arap/"),
                                 reason="需要應收應付（M05）：模組不在這個安裝包")
_NEEDS_CASE = pytest.mark.skipif(not source_tree.module_installed("modules/case/"),
                                 reason="需要案件管理（M01）：模組不在這個安裝包")


def test_norm_ymd_accepts_common_spellings():
    from helpers import norm_ymd
    for raw in ("2026/09/01", "2026.9.1", "115/09/01", "2026-09-01", "2026年9月1日", "2026-09-01T10:00:00"):
        assert norm_ymd(raw) == "2026-09-01", raw
    assert norm_ymd("") == "" and norm_ymd(None) == ""
    assert norm_ymd("abc") == "abc"          # 讀不懂：原樣，不假造
    assert norm_ymd("2026/13/40") == "2026/13/40"


@_NEEDS_ARAP
def test_slash_date_counts_in_september_income(client):
    from modules.analytics.api.reports import _collect_income_items
    _make_case_with_payments("MQ-SLASH-001", [
        _item("交貨款", received=True, received_at="2026/09/01", amount=100000)])
    hit = [i for i in _collect_income_items("2026-09-01", "2026-09-30") if i["quoteNo"] == "MQ-SLASH-001"]
    assert hit and hit[0]["receivedAt"] == "2026-09-01"


def test_unparseable_received_date_is_flagged(client, make_user):
    u, pw = make_user(username="rd_su1", role="superadmin")
    tok = _login(client, u, pw)
    _make_case_with_payments("MQ-SLASH-002", [_item("交貨款", received=True, received_at="9月初", amount=100000)])
    kinds = {(a["quoteNo"], a["kind"]) for a in _anomalies(client, tok)["items"]}
    assert ("MQ-SLASH-002", "received_bad_date") in kinds


def test_received_on_non_won_case_is_flagged_but_normal_is_not(client, make_user):
    u, pw = make_user(username="rd_su2", role="superadmin")
    tok = _login(client, u, pw)
    _make_case_with_payments("MQ-NW-001", [
        _item("頭期款", received=True, received_at="2026-09-01", amount=100000)], deal_tag="未成案")
    _make_case_with_payments("MQ-NW-002", [
        _item("頭期款", received=False, expected="2026-09-05", amount=100000)], deal_tag="未成案")
    _make_case_with_payments("MQ-OK-001", [
        _item("頭期款", received=True, received_at="2026-09-01", amount=100000)], deal_tag="已成案")
    kinds = {(a["quoteNo"], a["kind"]) for a in _anomalies(client, tok)["items"]}
    assert ("MQ-NW-001", "case_not_won") in kinds
    assert not any(q in ("MQ-NW-002", "MQ-OK-001") for q, _ in kinds)


@_NEEDS_ARAP
@_NEEDS_CASE
def test_accrual_view_shows_cash_receipt_compare_for_unrecognized_case(client, make_user):
    """9/1 已收款，但階段比例未設、尾款未結清 ⇒ 權責收入 0。權責視圖要另附「實收對照」讓 9/1 那筆看得見，
    且標「尚未認列」；權責數字不動。現金口徑：本來就在收入裡，不需要對照區。"""
    u, pw = make_user(username="rd_su3", role="superadmin")
    tok = _login(client, u, pw)
    _make_case_with_payments("MQ-CMP-001", [_item("交貨款", received=True, received_at="2026-09-01", amount=263813)])
    d = client.get("/api/reports/expenses-monthly?year=2026&month=2026-09&basis=accrual", headers=_auth(tok)).json()
    hit = [i for i in d["monthCashReceiptItems"] if i["quoteNo"] == "MQ-CMP-001"]
    assert hit and hit[0]["recognized"] is False and hit[0]["receivedAt"] == "2026-09-01"
    assert not [i for i in d["monthIncomeItems"] if i["quoteNo"] == "MQ-CMP-001"]
    c = client.get("/api/reports/expenses-monthly?year=2026&month=2026-09&basis=cash", headers=_auth(tok)).json()
    assert [i for i in c["monthIncomeItems"] if i["quoteNo"] == "MQ-CMP-001"]
    assert c["monthCashReceiptItems"] == []
