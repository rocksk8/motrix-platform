# -*- coding: utf-8 -*-
"""33-A5（D10）：完結精算時後端用同一來源重算，與頁面送上的 summary 比對；差異超過進位誤差 ⇒ 409、不存檔。"""
import json

import db
from modules.case.tests.test_material_link_2026_10_02 import _put_materials
from modules.case.tests.test_material_link_booking_2026_10_02 import _approved_po, _order, _won_case  # noqa: F401
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W, _ln, _mk, _submit  # noqa: F401
from modules.case.tests.test_settlement_actuals_2026_10_03 import _get

URL = "/api/quotations/%s/settlement" % NO


def _page_payload(c, h, **summary_over):
    """照精算頁的做法：取後端單一來源算出的數字，組成 settlement（採用的品項帶系統金額）＋summary。"""
    d = _get(c, h)
    items = [{"id": i["itemId"], "adoptSystem": True, "actualTotalCost": i["actual"]["amount"]} for i in d["items"]]
    summ = {"itemActualTotal": d["totals"]["itemActualTotal"], "itemPoUnadopted": 0, "extraTotal": d["totals"]["extraTotal"] + d["totals"]["materialUnassignedTotal"],
            "remitFeeTotal": 0, "customExpenseTotal": 0, "purchasedTotal": d["totals"]["purchasedTotal"]}
    summ.update(summary_over)
    return {"status": "finalized", "items": items, "summary": summ, "offsets": []}


def _finalize(c, h, st):
    return c.put(URL, json={"settlement": st}, headers=h)


def _status():
    cn = db.get_db()
    try:
        d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        return (d.get("settlement") or {}).get("status")
    finally:
        cn.close()


def test_consistent_page_numbers_finalize(W):
    c, h = W
    _approved_po(c, h, [_ln("a", 3, unitCost=1000)])
    _put_materials([_order("X", 1, 250)], {"X": "已核准"})
    assert _finalize(c, h, _page_payload(c, h)).status_code == 200 and _status() == "finalized"


def test_stale_page_numbers_are_rejected_with_409_and_nothing_is_saved(W):
    c, h = W
    stale = _page_payload(c, h)                                   # 頁面載入時（還沒有採購）
    _approved_po(c, h, [_ln("a", 3, unitCost=1000)])               # 使用者編輯期間，採購單被核准
    r = _finalize(c, h, stale)
    assert r.status_code == 409, r.text
    assert "重新整理" in r.json()["detail"] and "品項實際成本" in r.json()["detail"]
    assert _status() is None


def test_rounding_tolerance_is_one_dollar_per_item(W):
    c, h = W
    n = len(_get(c, h)["items"])
    assert n == 2
    ok = _page_payload(c, h)
    ok["summary"]["itemActualTotal"] += 2                           # 兩品項各進位 1 ⇒ 允許
    assert _finalize(c, h, ok).status_code == 200
    cn = db.get_db()
    q = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
    q.pop("settlement")
    cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(q), NO))
    cn.commit()
    cn.close()
    bad = _page_payload(c, h)
    bad["summary"]["itemActualTotal"] += 3                          # 超過
    assert _finalize(c, h, bad).status_code == 409


def test_extra_total_mismatch_is_rejected_but_remit_fee_and_custom_expense_are_the_pages_to_add(W):
    c, h = W
    ex = _mk(c, h, "purchase_order", [_ln(None, 1, unitCost=700)]).json()
    assert _submit(c, h, ex["id"]).status_code == 200
    assert _finalize(c, h, _page_payload(c, h, extraTotal=700 + 30 + 4, remitFeeTotal=30, customExpenseTotal=4)).status_code == 200   # 頁面額外加的手續費與自訂模組支出不在比對內
    cn = db.get_db()
    q = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
    q.pop("settlement")
    cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(q), NO))
    cn.commit()
    cn.close()
    r = _finalize(c, h, _page_payload(c, h, extraTotal=100))
    assert r.status_code == 409 and "額外支出" in r.json()["detail"]


def test_old_page_that_adds_unadopted_purchase_on_top_is_rejected(W):
    c, h = W
    _approved_po(c, h, [_ln("a", 3, unitCost=1000)])
    st = _page_payload(c, h)
    st["summary"]["itemPoUnadopted"] = 3000                          # 舊頁面算法（32-S5）：未採用的採購另加
    assert _finalize(c, h, st).status_code == 409


def test_draft_saves_and_summaryless_calls_are_not_checked(W):
    c, h = W
    _approved_po(c, h, [_ln("a", 3, unitCost=1000)])
    st = _page_payload(c, h, itemActualTotal=1)
    st["status"] = "draft"
    assert c.put(URL, json={"settlement": st}, headers=h).status_code == 200      # 草稿不比對
    assert c.put(URL, json={"settlement": {"status": "finalized", "items": []}}, headers=h).status_code == 200   # 非精算頁的呼叫（沒有 summary）無從比對


def test_history_case_without_links_finalizes_with_the_legacy_numbers(W):
    c, h = W
    st = {"status": "finalized", "items": [{"id": "a", "adoptSystem": False, "actualTotalCost": 10500}, {"id": "b", "adoptSystem": False, "actualTotalCost": 525}],
          "summary": {"itemActualTotal": 11025, "itemPoUnadopted": 0, "extraTotal": 0, "remitFeeTotal": 0, "customExpenseTotal": 0}, "offsets": []}
    assert _finalize(c, h, st).status_code == 200


def test_only_purchased_total_wrong_is_rejected(W):
    c, h = W
    _approved_po(c, h, [_ln("a", 3, unitCost=1000)])
    r = _finalize(c, h, _page_payload(c, h, purchasedTotal=1))
    assert r.status_code == 409 and "採購類總額" in r.json()["detail"]


def test_summary_without_the_page_keys_is_not_checked(W):
    c, h = W
    _approved_po(c, h, [_ln("a", 3, unitCost=1000)])
    assert _finalize(c, h, {"status": "finalized", "items": [], "summary": {"extraTotal": 5}}).status_code == 200


def test_the_request_body_is_what_gets_checked_not_the_older_saved_draft(W):
    c, h = W
    _approved_po(c, h, [_ln("a", 3, unitCost=1000)])
    draft = {"status": "draft", "items": [{"id": "a", "adoptSystem": False, "actualTotalCost": 9000}], "offsets": []}
    assert c.put(URL, json={"settlement": draft}, headers=h).status_code == 200            # 資料庫裡存的草稿：a 手填 9000、不採用
    final = {"status": "finalized", "items": [{"id": "a", "adoptSystem": True, "actualTotalCost": 3000}, {"id": "b", "adoptSystem": True, "actualTotalCost": 525}], "offsets": [],
             "summary": {"itemActualTotal": 3525, "itemPoUnadopted": 0, "extraTotal": 0, "remitFeeTotal": 0, "customExpenseTotal": 0, "purchasedTotal": 3000}}
    assert _finalize(c, h, final).status_code == 200                                         # 使用者後來改採用、完結：以這次送上的為準（不是資料庫裡舊草稿的 9000）


def test_resaving_an_already_finalized_settlement_is_not_rechecked(W):
    c, h = W
    assert _finalize(c, h, _page_payload(c, h)).status_code == 200
    _approved_po(c, h, [_ln("a", 3, unitCost=1000)])                                         # 完結後才核准的採購單
    again = _page_payload(c, h)
    again["summary"]["itemActualTotal"] = 1                                                  # 與重算差很多，但這是已完結的再存（超級管理員改備註）：不比對
    assert _finalize(c, h, again).status_code == 200


def test_tolerance_is_per_item_only_for_item_actual_total_not_for_extra_or_purchased(W):
    c, h = W
    ex = _mk(c, h, "purchase_order", [_ln(None, 1, unitCost=700)]).json()
    assert _submit(c, h, ex["id"]).status_code == 200
    r = _finalize(c, h, _page_payload(c, h, extraTotal=700 + 2))                                       # 兩品項的容差 2 不再放寬到額外支出
    assert r.status_code == 409 and "額外支出" in r.json()["detail"]
    assert _finalize(c, h, _page_payload(c, h, extraTotal=700 + 1)).status_code == 200                  # 只留 1 元防浮點
