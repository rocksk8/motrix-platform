# -*- coding: utf-8 -*-
"""31-A S6：下游的閘——匯款申請、總帳 E04、營運報表應計成本、精算比對總額。
每個閘都寫明五種新審核狀態＋**舊單（approval_status=''）＝與今天完全相同**。"""
import pytest

import db
from modules.subcontract import dispatch_flow as F
from modules.subcontract.tests.test_dispatch_approval_s2_2026_10_01 import _login, _mk, _row, W  # noqa: F401

pytestmark = pytest.mark.no_dispatch_shim

STATES = ["", F.APPROVED, F.DRAFT, F.PENDING, F.IN_PROGRESS, F.RETURNED]      # '' ＝舊單
PASS_VOUCHER = {"", F.APPROVED}


def _with_invoice(did, date="2026-09-15"):
    c = db.get_db()
    c.execute("UPDATE contractor_dispatches SET invoice_date=?, invoice_no='AB12345678', total_amount=1000, items_json='[]' WHERE id=?", (date, did))
    c.commit()
    c.close()


# ── 匯款申請閘 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ap", STATES)
@pytest.mark.parametrize("status", ["accepted", "completed"])
def test_voucher_gate_matrix(W, ap, status):                                                      # noqa: F811
    c, h = W
    did = _mk(status=status, approval=ap)
    r = c.post("/api/contractor-vouchers", json={"dispatch_id": did}, headers=h["da_a"])
    if ap in PASS_VOUCHER:
        assert r.status_code in (200, 201), (ap, status, r.text)          # 舊單與已核准：與今天一樣能開
    else:
        assert r.status_code == 409 and "尚未核准" in r.text, (ap, status, r.text)


@pytest.mark.parametrize("status", ["draft", "sent", "confirmed", "pending_acceptance", "cancelled"])
def test_voucher_old_status_gate_unchanged_even_when_approved_or_legacy(W, status):               # noqa: F811
    c, h = W
    for ap in ("", F.APPROVED):
        r = c.post("/api/contractor-vouchers", json={"dispatch_id": _mk(status=status, approval=ap)}, headers=h["da_a"])
        assert r.status_code == 409 and "已驗收" in r.text


def test_voucher_not_blocked_by_completion_review(W):                                              # noqa: F811
    """完工審核不是開匯款申請的前置（設計 §2.6）：accepted＋完工待審核＋第一段已核准 ⇒ 仍可開。"""
    c, h = W
    did = _mk(status="accepted", approval=F.APPROVED, completion=F.PENDING)
    assert c.post("/api/contractor-vouchers", json={"dispatch_id": did}, headers=h["da_a"]).status_code in (200, 201)


# ── 總帳 E04 ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ap", STATES)
def test_gl_event_only_for_approved_or_legacy(W, ap):                                              # noqa: F811
    from modules.subcontract import gl_events as G
    did = _mk(status="accepted", approval=ap)
    _with_invoice(did)
    ev = [e for e in G.gl_events("2026-09-01", "2026-09-30")["events"] if e["source_key"] == str(did) and e["event_code"] == "E04"]
    assert bool(ev) == (ap in PASS_VOUCHER), ap


# ── 營運報表應計成本 ────────────────────────────────────────────────────────

def _entries():
    from modules.case import recognition as R
    c = db.get_db()
    try:
        return {e["dispatchId"]: e for e in R.dispatch_entries(c, "accrual")}
    finally:
        c.close()


def test_accrual_rule_matrix_including_legacy(W):                                                  # noqa: F811
    ids = {ap: _mk(status="accepted", approval=ap) for ap in STATES}
    ent = _entries()
    assert ids[F.DRAFT] not in ent and ids[F.RETURNED] not in ent                                  # 草稿、已退回：不計
    for ap in (F.PENDING, F.IN_PROGRESS):
        assert ids[ap] in ent and ent[ids[ap]]["approvalPending"] is True                          # 待審核／簽核中：計入並標示
    for ap in ("", F.APPROVED):
        assert ids[ap] in ent and ent[ids[ap]]["approvalPending"] is False                         # 已核准與舊單：正常


def test_accrual_cancelled_still_excluded_and_completion_pending_still_counts(W):                  # noqa: F811
    a = _mk(status="cancelled", approval=F.APPROVED)
    b = _mk(status="accepted", approval=F.APPROVED, completion=F.PENDING)
    ent = _entries()
    assert a not in ent and b in ent and ent[b]["approvalPending"] is False


def test_operating_report_marks_pending_dispatch(W):                                               # noqa: F811
    c, h = W
    did = _mk(status="accepted", approval=F.PENDING)
    _with_invoice(did, "2026-09-10")
    r = c.get("/api/reports/expenses-monthly", params={"year": 2026, "month": "2026-09", "basis": "accrual"}, headers=h["da_sa"])
    assert r.status_code == 200, r.text
    rows = [x for x in r.json()["expenses"]["details"]["contractor"] if "派發待審核" in x.get("taxNote", "")]
    assert len(rows) == 1 and rows[0]["pending"] is True
    ok = _mk(status="accepted", approval="")                                                       # 舊單：不標
    _with_invoice(ok, "2026-09-11")
    r = c.get("/api/reports/expenses-monthly", params={"year": 2026, "month": "2026-09", "basis": "accrual"}, headers=h["da_sa"])
    allrows = r.json()["expenses"]["details"]["contractor"]
    assert len(allrows) == 2 and sum(1 for x in allrows if x["pending"]) == 1


# ── 精算比對的即時總額 ───────────────────────────────────────────────────────

def test_live_totals_follow_the_same_rule(W):                                                      # noqa: F811
    from modules.analytics.api import reports as RP
    for ap in STATES:
        _mk(status="accepted", approval=ap)
    c = db.get_db()
    try:
        tot = RP._live_dispatch_totals_by_quote(c)["MQ-DA-1"]
    finally:
        c.close()
    per = 1000 * 1.05 + 100                                                                        # 每筆 grandTotal（含稅承攬商＋外包人員）
    # 舊單、已核准、待審核、簽核中＝4 筆；草稿、已退回不計
    assert tot == pytest.approx(per * 4)


# ── 成本檢視（傳票摘要來源 dispatch.cost_for_case）：同一條報表規則，且與應計成本對得起來 ──────────

def _cost_view(h):
    from core import registry
    return registry.single_provider("dispatch.cost_for_case")("MQ-DA-1", h["da_sa"]["Authorization"])


def test_cost_view_rule_matrix_including_legacy_and_cancelled(W):                                  # noqa: F811
    c, h = W
    ids = {ap: _mk(status="accepted", approval=ap) for ap in STATES}
    gone = _mk(status="cancelled", approval=F.APPROVED)
    got = {r["id"]: r for r in _cost_view(h)}
    assert ids[F.DRAFT] not in got and ids[F.RETURNED] not in got and gone not in got
    for ap in (F.PENDING, F.IN_PROGRESS):
        assert got[ids[ap]]["approvalPending"] is True
    for ap in ("", F.APPROVED):
        assert got[ids[ap]]["approvalPending"] is False


def test_reconcile_accrual_and_cost_view_cover_the_same_dispatches(W):                             # noqa: F811
    """使用者裁示一條報表規則：同一組資料，應計成本與傳票摘要成本檢視納入的派發完全相同
    （金額口徑本來就不同：應計＝未稅［AC2］、成本檢視＝含稅 grandTotal，所以對「集合」與「各列金額換算」，不對合計）。"""
    c, h = W
    for ap in STATES:
        _mk(status="accepted", approval=ap)
    _mk(status="cancelled", approval=F.APPROVED)
    _mk(status="draft", approval=F.PENDING)
    acc = _entries()
    cost = {r["id"]: r for r in _cost_view(h)}
    assert set(acc) == set(cost) and len(acc) == 5                                                 # 舊單、已核准、待審核、簽核中、草稿狀態的 pending 單
    for did, e in acc.items():
        assert e["amount"] == pytest.approx(cost[did]["amount"] - (cost[did]["totalWithTax"] - 1000))   # 去掉稅額＝未稅＋人員
        assert e["approvalPending"] == cost[did]["approvalPending"]
