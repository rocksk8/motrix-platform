# -*- coding: utf-8 -*-
"""36：承攬商派發單可經 offsets（kind=dispatch, ref=派發 id）對應到報價單品項（規格 DISPATCH-OFFSET-SPEC.md §2）。
金額＝report（未稅＋外包人員）；規則 A 併入（採用時取代估計）；不得重複計入 totalActualCost；無 dispatch offsets ⇒ 與舊口徑逐位相同。
品項 a：估計 10500；品項 b：估計 525。"""
import copy
import json
import os

import pytest

import db
from modules.case import settlement_actuals as SA
from modules.case.tests.test_material_link_2026_10_02 import _put_materials
from modules.case.tests.test_material_link_booking_2026_10_02 import _order  # noqa: F401
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W  # noqa: F401
from modules.case.tests.test_settlement_actuals_2026_10_03 import EST_A, EST_B, _get, _items, _put_settlement
from modules.case.tests.test_settlement_tax_basis_2026_10_03 import _dispatch
from modules.case.tests._t40_won import quote_is_won  # noqa: F401  第 40 班：完結要已成案（autouse）

URL = "/api/quotations/%s/settlement" % NO


def _off(ref, item="a"):
    return {"kind": "dispatch", "ref": str(ref), "itemId": item}


def _get_off(c, h, offsets):
    r = c.get("/api/quotations/%s/settlement-actuals" % NO, params={"offsets": json.dumps(offsets)}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _put(c, h, offsets, **extra):
    return c.put(URL, json={"settlement": dict({"items": [], "offsets": offsets}, **extra)}, headers=h)


@pytest.fixture
def D(W):
    c, h = W
    d1 = _dispatch(10000, 2000)                       # 含稅計入 12500（未稅 10000＋稅 500＋人員 2000）
    d2 = _dispatch(3000, 0, approval="待審核")        # report 3000、pending
    _dispatch(999, 0, status="cancelled")             # 不計
    _dispatch(888, 0, approval="草稿")                # 不計
    return c, h, d1, d2


def test_sample_contract_json(D):
    c, h, d1, d2 = D
    d = _get_off(c, h, [_off(d1)])
    out = os.environ.get("T36_SAMPLE_OUT")
    if out:
        open(out, "w", encoding="utf-8").write(json.dumps({"unassigned.dispatches": d["unassigned"]["dispatches"], "items[a].dispatch": _items(d)["a"]["dispatch"],
                                                          "totals": {k: v for k, v in d["totals"].items() if k.startswith("dispatch") or k == "totalActualCost"}},
                                                         ensure_ascii=False, indent=2))
    assert [x["itemId"] for x in d["unassigned"]["dispatches"]] == [str(d2)]
    assert d["unassigned"]["dispatches"][0]["pending"] is True


def test_conservation_unassigned_plus_assigned_equals_dispatch_total(D):
    c, h, d1, d2 = D
    for offs in ([], [_off(d1)], [_off(d1), _off(d2, "b")]):
        t = _get_off(c, h, offs)["totals"]
        assert t["dispatchUnassignedTotal"] + t["dispatchAssignedTotal"] == t["dispatchTotal"] == 15650


def test_amount_is_report_and_tax_is_display_only(D):
    c, h, d1, d2 = D
    d = _get_off(c, h, [_off(d1)])
    o = _items(d)["a"]["dispatch"]["orders"][0]
    assert (o["amount"], o["tax"], o["grandTotal"], o["assignedBy"]) == (12500, 500, 12500, "offset")
    assert _items(d)["a"]["dispatch"]["amount"] == 12500 and _items(d)["b"]["dispatch"] == {"amount": 0, "orders": []}


def test_adopt_on_replaces_estimate_and_total_not_double_counted(D):
    c, h, d1, d2 = D
    base = _get_off(c, h, [])["totals"]["totalActualCost"]
    assert base == EST_A + EST_B + 15650
    _put_settlement({"items": [{"id": "a", "adoptSystem": True}], "offsets": [_off(d1)]})
    d = _get(c, h)
    a = _items(d)["a"]
    assert a["actual"]["amount"] == 12500 and a["actual"]["source"] == "purchase" and a["actual"]["replacedEstimate"] is True
    assert d["totals"]["totalActualCost"] == 12500 + EST_B + 3150                   # 12500 只算一次
    assert d["totals"]["dispatchAbsorbedTotal"] == 12500
    # 取消對應：回未對應、估計恢復，總成本回到對應前（採用開時總成本會隨取代估計而變，但金額都只計一次）
    _put_settlement({"items": [{"id": "a", "adoptSystem": True}], "offsets": []})
    assert _get(c, h)["totals"]["totalActualCost"] == EST_A + EST_B + 15650 and _get(c, h)["totals"]["dispatchAbsorbedTotal"] == 0


def test_adopt_off_moving_between_unassigned_and_assigned_keeps_total(D):
    c, h, d1, d2 = D
    _put_settlement({"items": [{"id": "a", "adoptSystem": False}, {"id": "b", "adoptSystem": False}], "offsets": []})
    for mode in (SA.UNADOPTED_IGNORE, SA.UNADOPTED_ADD):
        cn = db.get_db()
        try:
            t_un = SA.compute(cn, NO, offsets=[], unadopted=mode)["totals"]["totalActualCost"]
            t_as = SA.compute(cn, NO, offsets=[_off(d1), _off(d2, "b")], unadopted=mode)["totals"]["totalActualCost"]
        finally:
            cn.close()
        assert t_un == t_as == EST_A + EST_B + 15650, mode
        cn = db.get_db()
        try:
            assert SA.compute(cn, NO, offsets=[_off(d1)], unadopted=mode)["totals"]["dispatchAbsorbedTotal"] == 0          # 不採用：不吸收
        finally:
            cn.close()


def test_mixed_with_material_offset_sum_replaces_estimate(D):
    c, h, d1, d2 = D
    _put_materials([_order("X", 1, 250)], {"X": "已核准"})
    cn = db.get_db()
    try:
        dd = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        dd["dealTag"] = "已成案"
        cn.execute("UPDATE quotations SET data_json=?, deal_tag='已成案' WHERE quote_no=?", (json.dumps(dd), NO))
        cn.commit()
    finally:
        cn.close()
    _put_settlement({"items": [{"id": "b", "adoptSystem": True}], "offsets": [_off(d1, "b"), {"kind": "material", "ref": "X", "itemId": "b"}]})
    b = _items(_get(c, h))["b"]
    assert b["purchased"] == 12500 + 250 and b["actual"]["amount"] == 12750


def test_validate_offsets(D):
    c, h, d1, d2 = D
    assert _put(c, h, [_off(d1)]).status_code == 200
    for bad in ([_off(99999)],                                    # 不存在
                [_off(d1, "zzz")],                                # 品項不存在
                [_off(d1), _off(d1, "b")],                        # 兩個去處
                [{"kind": "dispatch", "ref": "", "itemId": "a"}]):
        assert _put(c, h, bad).status_code == 422, bad
    cn = db.get_db()
    try:
        cid = cn.execute("SELECT id FROM contractor_dispatches WHERE status='cancelled'").fetchone()["id"]
        did = cn.execute("SELECT id FROM contractor_dispatches WHERE approval_status='草稿'").fetchone()["id"]
    finally:
        cn.close()
    assert _put(c, h, [_off(cid)]).status_code == 422 and _put(c, h, [_off(did)]).status_code == 422   # 已取消／草稿不在未對應清單


def test_saved_offset_survives_dispatch_cancelled_later(D):
    c, h, d1, d2 = D
    assert _put(c, h, [_off(d1)]).status_code == 200
    cn = db.get_db()
    try:
        cn.execute("UPDATE contractor_dispatches SET status='cancelled' WHERE id=?", (d1,))
        cn.commit()
    finally:
        cn.close()
    assert _put(c, h, [_off(d1)]).status_code == 200              # 原樣沒改的列放行
    assert _get(c, h)["totals"]["dispatchAssignedTotal"] == 0     # 取消的派發不計，錢不留在品項上


def test_legacy_without_dispatch_offsets_is_identical(D):
    c, h, d1, d2 = D
    d = _get(c, h)
    t = d["totals"]
    assert t["dispatchAssignedTotal"] == 0 and t["dispatchUnassignedTotal"] == t["dispatchTotal"] == 15650
    assert t["totalActualCost"] == t["itemActualTotal"] + t["itemPoUnadopted"] + t["extraTotal"] + t["materialUnassignedTotal"] + t["remitFeeTotal"] + t["customExpenseTotal"] + t["dispatchTotal"]
    assert t["purchasedTotal"] == 0 and t["pendingTotal"] == 0
    assert all(i["dispatch"] == {"amount": 0, "orders": []} and i["purchased"] == 0 for i in d["items"])
    assert d["sources"] == {"po": 0, "materialAssigned": 0, "materialUnassigned": 0, "extraAssigned": 0, "extraUnassigned": 0}


def test_frozen_summary_keeps_dispatch_split(D):
    c, h, d1, d2 = D
    _put_settlement({"status": "finalized", "items": [{"id": "a", "actualTotalCost": 12000, "adoptSystem": True}], "offsets": [_off(d1)],
                     "summary": {"itemActualTotal": 12000 + EST_B, "extraTotal": 0, "dispatchTotal": 15000, "totalActualCost": 12000 + EST_B + 3000,
                                 "dispatchAssignedTotal": 12000, "dispatchUnassignedTotal": 3000}})
    t = _get(c, h)["totals"]
    assert (t["dispatchAssignedTotal"], t["dispatchUnassignedTotal"], t["totalActualCost"]) == (12000, 3000, 12000 + EST_B + 3000)
    cn = db.get_db()
    try:
        cn.execute("UPDATE contractor_dispatches SET total_amount=99999 WHERE id=?", (d2,))
        cn.commit()
    finally:
        cn.close()
    t2 = _get(c, h)["totals"]
    assert (t2["dispatchAssignedTotal"], t2["dispatchUnassignedTotal"]) == (12000, 3000)       # 完結後派發漂移不影響凍結值


def test_legacy_frozen_without_split_keys(D):
    c, h, d1, d2 = D
    _put_settlement({"status": "finalized", "items": [], "summary": {"itemActualTotal": 1, "extraTotal": 0, "dispatchTotal": 777, "totalActualCost": 778}})
    t = _get(c, h)["totals"]
    assert (t["dispatchAssignedTotal"], t["dispatchUnassignedTotal"], t["dispatchTotal"]) == (0, 777, 777)


def test_finalize_fills_split_and_rejects_wrong_split(D):
    c, h, d1, d2 = D
    from modules.case.tests.test_settlement_finalize_integrity_2026_10_03 import _set_tot, page_payload
    _set_tot()
    _put_settlement({"items": [{"id": "a", "adoptSystem": True}], "offsets": [_off(d1)]})
    t = _get(c, h)["totals"]                                  # 頁面總成本一律用伺服器的 totalActualCost（舊 page_payload 公式會把被吸收的派發加兩次）
    gross = 100000 - t["totalActualCost"]
    admin, charity = SA.round_half_up(100000, 0.10), SA.round_half_up(gross, 0.01)
    net = gross - admin - charity
    p = page_payload(c, h, totalActualCost=t["totalActualCost"], grossProfit=gross, charityDonation=charity, netProfit=net,
                     grossMarginPct=round(gross / 1000, 1), netMarginPct=round(net / 1000, 1))
    p["offsets"] = [_off(d1)]
    bad = copy.deepcopy(p)
    bad["summary"]["dispatchAssignedTotal"] = 1
    assert c.put(URL, json={"settlement": bad}, headers=h).status_code == 409
    r = c.put(URL, json={"settlement": p}, headers=h)
    assert r.status_code == 200, r.text
    s = _get(c, h)["savedSummary"]
    assert (s["dispatchAssignedTotal"], s["dispatchUnassignedTotal"]) == (12500, 3150)


def test_item_actual_source_roundtrip_is_display_only(D):
    c, h, d1, d2 = D
    items = [{"id": "a", "adoptSystem": False, "actualTotalCost": 700, "actualSource": "labor"}, {"id": "b", "adoptSystem": False, "actualSource": "legacy"}]
    before = _get(c, h)["totals"]
    assert _put(c, h, [], items=items).status_code == 200
    d = _get(c, h)
    assert (_items(d)["a"]["actualSource"], _items(d)["b"]["actualSource"]) == ("labor", "legacy")
    cn = db.get_db()
    try:
        saved = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])["settlement"]["items"]
    finally:
        cn.close()
    assert [i.get("actualSource") for i in saved] == ["labor", "legacy"]                            # 存檔原樣保留
    assert _items(d)["a"]["actual"]["amount"] == 700 and _items(d)["b"]["actual"]["amount"] == EST_B   # 不影響金額
    assert before["dispatchTotal"] == d["totals"]["dispatchTotal"]
    assert _items(_get(c, h))["a"]["actualSource"] == "labor"
    _put_settlement({"items": [{"id": "a"}], "offsets": []})
    assert _items(_get(c, h))["a"]["actualSource"] == "manual"                                       # 沒有＝manual
    assert _put(c, h, [], items=[{"id": "a", "actualSource": "bogus"}]).status_code == 422


def test_item_actual_source_survives_finalize_freeze(D):
    c, h, d1, d2 = D
    _put_settlement({"status": "finalized", "items": [{"id": "a", "actualTotalCost": 700, "actualSource": "labor"}], "offsets": [],
                     "summary": {"itemActualTotal": 700 + EST_B, "extraTotal": 0, "dispatchTotal": 15000, "totalActualCost": 700 + EST_B + 15000}})
    d = _get(c, h)
    assert d["frozen"] is True and _items(d)["a"]["actualSource"] == "labor" and _items(d)["a"]["actual"]["amount"] == 700
