"""獎金分潤發放的營運報表使用方（自 tests/platform/test_bonus_payout_connectors.py 拆出，M08 搬遷反向控制）。

`expense.entries` 串接點：發放後以發放日計入月支出的「其他」；拿掉提供者 ⇒ 報表照常、只少這一筆。
拿掉本模組 ⇒ 本檔一起消失。
"""
from tests.platform.test_bonus_payout_connectors import (  # noqa: F401  people、_legal（autouse）是 fixture
    _auth, _drop, _insure_all, _legal, _q, _to_payout, _with_legal, insure_all, people)


def _year_other(client, tok, year):
    r = client.get("/api/reports/expenses-monthly?year=%s" % year, headers=_auth(tok))
    assert r.status_code == 200, r.text
    return r.json()["expenses"]


def test_report_counts_bonus_on_paid_date(client, people):
    insure_all()
    _to_payout(client, people, "MQ-BP-R1")
    total = _q("SELECT SUM(l.amount) AS s FROM bonus_case_award_lines l JOIN bonus_case_awards a"
               " ON a.id=l.award_id WHERE a.quote_no='MQ-BP-R1'")[0]["s"]
    before = _year_other(client, people["bc_sa"], 2026)
    assert not [e for e in before["details"]["other"] if e["quoteNo"] == "MQ-BP-R1"]   # 待發放不算
    client.post("/api/bonus/cases/MQ-BP-R1/mark-paid", headers=_auth(people["bc_cash"]), json={})
    paid = _q("SELECT paid_at FROM bonus_case_awards WHERE quote_no='MQ-BP-R1'")[0]["paid_at"][:10]
    exp = _year_other(client, people["bc_sa"], int(paid[:4]))
    rows = [e for e in exp["details"]["other"] if e["quoteNo"] == "MQ-BP-R1"]
    assert rows == [dict(rows[0], date=paid, amount=total, category="獎金分潤")]
    month = next(m for m in exp["monthly"] if m["month"] == paid[:7])
    month_before = next(m for m in before["monthly"] if m["month"] == paid[:7])
    assert month["other"] - month_before["other"] == total


def test_reverse_without_payroll_report_still_works(client, people, monkeypatch):
    insure_all()
    _to_payout(client, people, "MQ-BP-R2")
    client.post("/api/bonus/cases/MQ-BP-R2/mark-paid", headers=_auth(people["bc_cash"]), json={})
    paid = _q("SELECT paid_at FROM bonus_case_awards WHERE quote_no='MQ-BP-R2'")[0]["paid_at"][:4]
    assert [e for e in _year_other(client, people["bc_sa"], paid)["details"]["other"] if e["quoteNo"] == "MQ-BP-R2"]
    _drop(monkeypatch, "expense.entries")
    exp = _year_other(client, people["bc_sa"], paid)
    assert not [e for e in exp["details"]["other"] if e["quoteNo"] == "MQ-BP-R2"]


def test_reverse_without_accounting_report_still_counts_bonus(client, people, monkeypatch):
    """會計模組不在時照常發放（tests/platform 那一題驗發放本身）；報表仍以發放日計入。"""
    _with_legal(monkeypatch)
    _insure_all(client, people, bc_s1=20000)
    _to_payout(client, people, "MQ-BP-A2")
    _drop(monkeypatch, "voucher.draft", "voucher.account_check", "accounting.settings",
          "voucher.void_draft", "voucher.status")
    r = client.post("/api/bonus/cases/MQ-BP-A2/mark-paid", headers=_auth(people["bc_cash"]), json={})
    assert r.status_code == 200, r.text
    paid = _q("SELECT paid_at FROM bonus_case_awards WHERE quote_no='MQ-BP-A2'")[0]["paid_at"][:4]
    assert [e for e in _year_other(client, people["bc_sa"], paid)["details"]["other"] if e["quoteNo"] == "MQ-BP-A2"]
