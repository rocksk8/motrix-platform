# -*- coding: utf-8 -*-
"""32-S3：連到案件品項的採購單明細＝品項實際成本（Q1）——同一列在「額外支出清單／營運報表來源／總帳 E11」各只算一次且金額守恆；
作廢、駁回、請購單不計；變更申請核准後以新明細為準；沒有 itemId 的歷史資料（含舊版額外支出列）數字與以前完全相同；
E11 的 item 維度不改既有分錄金額與科目。"""
import json
from datetime import date

import pytest

import db
from modules.case import gl_events as GE
from modules.case import recognition as R
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, BASE, W, _body, _ln, _mk, _set_tiers, _status, _submit  # noqa: F401

pytestmark = pytest.mark.usefixtures("W")


def _approved(c, h, kind, lines, data=None):
    eid = _mk(c, h, kind, lines, data).json()["id"]
    assert _submit(c, h, eid).status_code == 200
    return eid


def _legacy_row(amount=200, status="已核准"):
    cn = db.get_db()
    try:
        cn.execute("INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, total_cost, note, expense_date, doc_no, files_json, "
                   "created_by, created_by_name, created_by_inferred, payer_username, payer_name, created_at, updated_at, updated_by_name, status, approval_json) "
                   "VALUES (?,?,?,?,?,?,?,?,?,?,'[]',?,?,0,?,?,?,?,?,?,'{}')",
                   (NO, "其他", "舊版支出", 1, "式", amount, amount, "", "2026-10-02", "", "pl_sa", "pl_sa", "pl_sa", "pl_sa",
                    "2026-10-02T00:00:00", "2026-10-02T00:00:00", "pl_sa", status))
        cn.commit()
    finally:
        cn.close()


def _world(c, h):
    """PO1 已核准：連 a 3×1000＋未連 500；PO2 已核准：連 b 100×5；PR 已核准連 a（不計成本）；PO3 已駁回連 a；PO4 未連 800；舊版列 200。"""
    po1 = _approved(c, h, "purchase_order", [_ln("a", 3, unitCost=1000), _ln(None, 1, unitCost=500)])
    po2 = _approved(c, h, "purchase_order", [_ln("b", 100, unitCost=5)])
    pr = _approved(c, h, "purchase_req", [_ln("a", 4, unitCost=900)])
    po3 = _mk(c, h, "purchase_order", [_ln("a", 1, unitCost=1000)]).json()["id"]
    _status(po3, "已駁回")
    po4 = _approved(c, h, "purchase_order", [_ln(None, 8, unitCost=100)])
    _legacy_row(200)
    return {"po1": po1, "po2": po2, "pr": pr, "po3": po3, "po4": po4}


def _list(c, h):
    r = c.get(BASE, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _entries(basis="accrual"):
    cn = db.get_db()
    try:
        return [e for e in R.extra_entries(cn, basis) if e["quoteNo"] == NO]
    finally:
        cn.close()


# ── 清單 ──────────────────────────────────────────────────────────────────

def test_list_splits_linked_from_extra_without_losing_money(W):
    c, h = W
    _world(c, h)
    d = _list(c, h)
    assert d["totalAmount"] == 3500 + 500 + 800 + 200 and d["itemLinkedAmount"] == 3500 and d["extraOnlyAmount"] == 1500     # PR、駁回不計
    assert d["totalAmount"] == d["itemLinkedAmount"] + d["extraOnlyAmount"]
    rows = {i["docCode"] or "legacy": i for i in d["items"]}
    assert sorted(i["linkedAmount"] for i in d["items"] if "linkedAmount" in i) == [0.0, 0.0, 500.0, 3000.0]


# ── 營運報表來源 ───────────────────────────────────────────────────────────

def test_report_entries_split_per_line_and_conserve_each_document(W):
    c, h = W
    ids = _world(c, h)
    ent = _entries()
    linked = [e for e in ent if e.get("linkedItem")]
    assert sorted((e["itemId"], e["amount"]) for e in linked) == [("a", 3000.0), ("b", 500.0)]
    assert all(e["bucket"] == R.ITEM_COST_BUCKET == "material" for e in linked)
    assert sum(e["amount"] for e in ent) == 5000.0                                              # 合計＝清單合計（不多不少）
    assert not any(e.get("linkedItem") for e in ent if e.get("kind") != "purchase_order")
    cn = db.get_db()
    try:
        po1 = cn.execute("SELECT doc_code, total_cost FROM case_extra_expenses WHERE id=?", (ids["po1"],)).fetchone()
    finally:
        cn.close()
    assert sum(e["amount"] for e in ent if e.get("docCode") == po1["doc_code"]) == po1["total_cost"] == 3500     # 同一張單據拆列後金額守恆
    assert not any(e.get("docCode") and e.get("kind") == "purchase_req" for e in ent)               # 請購單不進報表
    assert not any(e.get("itemId") == "a" and e["amount"] == 1000 for e in ent)                  # 駁回的 PO3 不計


def test_operating_report_endpoint_puts_linked_lines_in_the_material_bucket(W):
    c, h = W
    _world(c, h)
    month = date.today().strftime("%Y-%m")
    r = c.get("/api/reports/expenses-monthly", params={"year": date.today().year, "month": month, "basis": "accrual"}, headers=h)
    assert r.status_code == 200, r.text
    ex = r.json()["expenses"]
    mrow = next(m for m in ex["monthly"] if m["month"] == month)
    assert mrow["material"] == 3500 and mrow["other"] == 1500
    assert sum(x["amount"] for x in ex["details"]["material"] if x.get("quoteNo") == NO) == 3500
    assert sum(x["amount"] for x in ex["details"]["other"] if x.get("quoteNo") == NO) == 1500


# ── 總帳 E11 ──────────────────────────────────────────────────────────────

def _e11():
    ev = GE.gl_events("2000-01-01", "2099-12-31")["events"]
    return [e for e in ev if e["event_code"] == "E11"]


def test_e11_item_dimension_does_not_change_amounts_or_roles(W):
    c, h = W
    ids = _world(c, h)
    cn = db.get_db()
    try:
        po1 = cn.execute("SELECT id FROM case_extra_expenses WHERE id=?", (ids["po1"],)).fetchone()["id"]
    finally:
        cn.close()
    ev = {e["source_key"]: e for e in _e11()}
    e = ev[str(po1)]
    debits = [l for l in e["lines"] if l["side"] == "D"]
    assert sorted((l["amount"], l.get("dims", {}).get("item", "")) for l in debits) == [(500, ""), (3000, "a")]
    assert all(l["role"] == "COST_PROJECT" for l in debits)                                      # 角色（科目來源）不變
    assert sum(l["amount"] for l in debits) == sum(l["amount"] for l in e["lines"] if l["side"] == "C") == 3500
    assert str(ids["pr"]) not in ev and str(ids["po3"]) not in ev                               # 請購單、駁回不入帳


def test_unlinked_history_is_byte_identical_in_every_view(W):
    """沒有 itemId 的資料（舊版列＋未連結的採購單）：清單、報表來源、總帳行都不帶任何新鍵，數字與以前相同。"""
    c, h = W
    po = _approved(c, h, "purchase_order", [_ln(None, 8, unitCost=100), _ln(None, 2, unitCost=50, category="差旅")])
    _legacy_row(200)
    d = _list(c, h)
    assert d["totalAmount"] == 900 + 200 and d["itemLinkedAmount"] == 0 and d["extraOnlyAmount"] == d["totalAmount"]
    ent = _entries()
    assert not any(k in e for e in ent for k in ("itemId", "linkedItem", "bucket"))
    assert sorted(e["amount"] for e in ent) == [100, 200, 800]                                   # 依類別逐類（雜項 800、差旅 100）＋舊版 200
    line_sets = [l for e in _e11() if e["source_key"] == str(po) for l in e["lines"]]
    assert not any("dims" in l for l in line_sets) and sum(l["amount"] for l in line_sets if l["side"] == "D") == 900


# ── 作廢／駁回／變更申請 ────────────────────────────────────────────────────

def test_void_and_rejection_remove_the_line_from_all_three_views(W):
    c, h = W
    ids = _world(c, h)
    before = _list(c, h)["itemLinkedAmount"]
    _status(ids["po1"], "已作廢")
    d = _list(c, h)
    assert d["itemLinkedAmount"] == before - 3000 and d["totalAmount"] == 5000 - 3500
    assert not any(e.get("itemId") == "a" for e in _entries())
    assert str(ids["po1"]) not in {e["source_key"] for e in _e11()}
    _status(ids["po2"], "已駁回")
    assert _list(c, h)["itemLinkedAmount"] == 0 and not any(e.get("linkedItem") for e in _entries())


def test_pending_review_counts_in_list_and_report_but_not_in_gl(W):
    """待審核：清單與報表照計（標待定）；總帳只收已核准（沿用 E11 規則）。"""
    c, h = W
    ids = _world(c, h)
    _status(ids["po2"], "待審核")
    d = _list(c, h)
    assert d["itemLinkedAmount"] == 3500 and d["totalPending"] == 500
    assert any(e.get("itemId") == "b" and e["pending"] for e in _entries())
    assert str(ids["po2"]) not in {e["source_key"] for e in _e11()}


def test_approved_change_request_replaces_the_lines_everywhere(W):
    c, h = W
    po = _approved(c, h, "purchase_order", [_ln("a", 3, unitCost=1000)])
    r = c.put("%s/%d/change-request" % (BASE, po), headers=h, json=_body("purchase_order", [_ln("b", 10, unitCost=5), _ln("a", 1, unitCost=1000)]))
    assert r.status_code == 200, r.text
    assert c.post("%s/%d/change-request/submit" % (BASE, po), headers=h).status_code == 200      # 沒設簽核層 ⇒ 核准並套用
    d = _list(c, h)
    assert d["itemLinkedAmount"] == 1050 and d["totalAmount"] == 1050
    got = {e["itemId"]: e["amount"] for e in _entries() if e.get("linkedItem")}
    assert got == {"a": 1000.0, "b": 50.0}
    e11 = next(e for e in _e11() if e["source_key"] == str(po))
    assert sorted((l["amount"], l["dims"]["item"]) for l in e11["lines"] if l["side"] == "D") == [(50, "b"), (1000, "a")]


# ── 挑選器／精算的系統帶入 ───────────────────────────────────────────────────

def test_picker_actual_amount_only_counts_counted_po_lines_and_is_hidden_without_finance(W):
    c, h = W
    _world(c, h)
    r = c.get("/api/quotations/%s/purchase-items" % NO, headers=h)
    got = {i["itemId"]: i for i in r.json()["items"]}
    assert got["a"]["actualAmount"] == 3000 and got["b"]["actualAmount"] == 500                 # PR、駁回的 a 不計
    assert got["a"]["orderedQty"] == 3 and got["a"]["requestedQty"] == 4
