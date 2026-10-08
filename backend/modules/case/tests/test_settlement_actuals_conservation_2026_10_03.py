# -*- coding: utf-8 -*-
"""33-A3 漂移守門（合約測試，必跑）：同一案件、權責口徑，三處「採購類金額」逐情境相等——
精算端點 `purchasedTotal`＝營運報表（材料申請＋額外支出）；扣掉待審核後＝總帳（E11＋E12 的應付貸方）。
任何一邊改規則而另一邊沒跟（只改 `recognition` 原語以外的地方），這題立刻紅。規格 SETTLEMENT-ACTUALS-SPEC §3.3。"""
import json
from datetime import date

import pytest

import db
from modules.case import gl_events as GE
from modules.case import recognition as R
from modules.case.tests.test_material_link_2026_10_02 import _put_materials
from modules.case.tests.test_material_link_booking_2026_10_02 import _approved_po, _order, _won_case  # noqa: F401
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W, _ln, _mk, _set_tiers, _submit  # noqa: F401
from modules.case.tests.test_settlement_actuals_2026_10_03 import _get, _put_settlement

def _today():
    return date.today().isoformat()   # 呼叫時才取，避免跨午夜與伺服器日期不一致


def _report(basis="accrual"):
    cn = db.get_db()
    try:
        return (sum(e["amount"] for e in R.material_entries(cn, basis) if e["quoteNo"] == NO)
                + sum(e["amount"] for e in R.extra_entries(cn, basis) if e["quoteNo"] == NO))
    finally:
        cn.close()


def _gl_cost(codes):
    tot = 0
    for e in GE.gl_events("2000-01-01", "2099-12-31")["events"]:
        if e["event_code"] in codes and e["case_no"] == NO:
            tot += sum(l["amount"] for l in e["lines"] if l["role"] == "AP" and l["side"] == "C")
    return tot


def _check(c, h, expect=None, scn_pending_expected=None):
    d = _get(c, h)
    t = d["totals"]
    if scn_pending_expected is not None:
        assert t["pendingTotal"] == scn_pending_expected
    assert t["purchasedTotal"] == _report(), "精算 ≠ 營運報表"
    assert t["purchasedTotal"] - t["pendingTotal"] == _gl_cost(("E11", "E12")), "精算（扣待審核）≠ 總帳 E11＋E12"
    if expect is not None:
        assert t["purchasedTotal"] == expect
    # 守恆：每筆錢只出現一次——品項上的＋未對應的＝總額
    assert sum(t_ for t_ in d["sources"].values()) == t["purchasedTotal"]
    return d


def _scn_po_item_and_extra(c, h):
    _approved_po(c, h, [_ln("a", 3, unitCost=1000), _ln(None, 1, unitCost=500)])
    return 3500


def _scn_materials_linked_unlinked_nobinding(c, h):
    po = _approved_po(c, h, [_ln("a", 3, unitCost=1000)])
    _put_materials([_order("K", 3, 3000, quoteItemId="a", poDocCode=po["docCode"], poLine=1),      # 連採購單：金額在採購單
                    _order("N", 2, 800, quoteItemId="b"),                                          # 連品項沒連採購單
                    _order("X", 1, 250)], {"K": "已核准", "N": "已核准", "X": "已核准"})            # 沒品項
    return 3000 + 800 + 250


def _scn_status_matrix(c, h):
    _put_materials([_order("A", 1, 100), _order("B", 1, 200), _order("C", 1, 400), _order("D", 1, 800), _order("E", 1, 1600)],
                   {"A": "已核准", "B": "待審核", "C": "草稿", "D": "已取消", "E": "已退回"})
    return 100 + 200


def _scn_zero_and_legacy_no_approval_row(c, h):
    _put_materials([_order("Z", 1, 0, quoteItemId="a"), _order("O", 2, 500, quoteItemId="a")], {"Z": "已核准"})   # O 沒有疊加審核列＝舊單，照計
    return 500


def _scn_deleted_item(c, h):
    _approved_po(c, h, [_ln("a", 3, unitCost=1000)])
    _put_materials([_order("G", 1, 900, quoteItemId="gone")], {"G": "已核准"})
    cn = db.get_db()
    d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
    d["items"] = [i for i in d["items"] if i["id"] != "a"]
    d["dealTag"] = "已成案"
    cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
    cn.commit()
    cn.close()
    return 3000 + 900


def _scn_offsets_move_not_change(c, h):
    ex = _mk(c, h, "purchase_order", [_ln(None, 1, unitCost=700)]).json()
    assert _submit(c, h, ex["id"]).status_code == 200
    _put_materials([_order("X", 1, 250)], {"X": "已核准"})
    return 950


def _scn_pending_po(c, h):
    _approved_po(c, h, [_ln("a", 1, unitCost=100)])                                    # 已核准 100（沒設簽核層）
    _set_tiers([{"order": 0, "approvers": [{"username": "pl_sa", "displayName": "主管"}]}])
    p = _mk(c, h, "purchase_order", [_ln("b", 2, unitCost=50), _ln(None, 1, unitCost=30)]).json()
    assert _submit(c, h, p["id"]).status_code == 200                                    # 有簽核層 ⇒ 待審核（精算與報表計入並標 pending；總帳不入帳）
    return 100 + 100 + 30


SCENARIOS = [_scn_pending_po, _scn_po_item_and_extra, _scn_materials_linked_unlinked_nobinding, _scn_status_matrix, _scn_zero_and_legacy_no_approval_row,
             _scn_deleted_item, _scn_offsets_move_not_change]


@pytest.mark.parametrize("scn", SCENARIOS, ids=[s.__name__[5:] for s in SCENARIOS])
def test_three_places_agree(W, scn):
    c, h = W
    expect = scn(c, h)
    _check(c, h, expect, {"_scn_pending_po": 130, "_scn_status_matrix": 200}.get(scn.__name__))


def test_offsets_move_money_between_buckets_but_never_change_the_total(W):
    c, h = W
    ex = _mk(c, h, "purchase_order", [_ln(None, 1, unitCost=700)]).json()
    assert _submit(c, h, ex["id"]).status_code == 200
    _put_materials([_order("X", 1, 250)], {"X": "已核准"})
    before = _check(c, h, 950)
    _put_settlement({"items": [], "offsets": [{"kind": "material", "ref": "X", "itemId": "b"}, {"kind": "extra", "ref": str(ex["id"]), "itemId": "a"}]})
    after = _check(c, h, 950)
    assert before["totals"]["extraTotal"] == 700 and after["totals"]["extraTotal"] == 0       # 錢搬家（正對照：不是沒動）
    assert after["sources"]["materialAssigned"] == 250 and after["sources"]["extraAssigned"] == 700


def test_cash_basis_report_equals_gl_for_materials_and_adopt_toggle_never_changes_purchased(W):
    c, h = W
    po = _approved_po(c, h, [_ln("a", 3, unitCost=1000)])
    _put_materials([_order("K", 3, 3000, quoteItemId="a", poDocCode=po["docCode"]),
                    _order("N", 2, 800, paidStatus="paid", paidAmount=800, paidDate=_today())], {"K": "已核准", "N": "已核准"})
    cn = db.get_db()
    try:
        cash = sum(e["amount"] for e in R.material_entries(cn, "cash") if e["quoteNo"] == NO)
    finally:
        cn.close()
    assert cash == 800                                                                         # 現金口徑：已付的那張（連採購單的不重複）
    gl_cash = sum(l["amount"] for e in GE.gl_events("2000-01-01", "2099-12-31")["events"] if e["event_code"] == "E12b" and e["case_no"] == NO
                  for l in e["lines"] if l["side"] == "D" and l["role"] == "AP")
    assert gl_cash == cash
    t0 = _check(c, h, 3800)["totals"]["purchasedTotal"]
    _put_settlement({"items": [{"id": "a", "adoptSystem": False, "actualTotalCost": 1}]})
    assert _check(c, h, 3800)["totals"]["purchasedTotal"] == t0                               # 採用開關只改「實際」，不改採購類總額
