# -*- coding: utf-8 -*-
"""第 38 班後端（案件／精算）：①完結時下游欄位一律由伺服器值覆蓋 ②PUT /settlement 樂觀鎖＋整份存檔不帶精算本文 ③負數／零和採購列算「有採購」
④PDF／獎金精算表在派發被品項吸收時列「已併入品項」 ⑤完結快照進編輯歷程＋草稿存檔歷程不無限成長＋已刪品項的存檔資料可見。
品項 a：估計 10500；品項 b：估計 525。"""
import json

import pytest

import db
from modules.case import settlement_actuals as SA
from modules.case.tests.test_material_link_booking_2026_10_02 import _approved_po  # noqa: F401
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W, _ln  # noqa: F401
from modules.case.tests.test_settlement_actuals_2026_10_03 import EST_A, EST_B, _get, _items, _put_settlement
from modules.case.tests.test_settlement_assigned_fields_2026_10_03 import _extra
from modules.case.tests.test_settlement_finalize_integrity_2026_10_03 import _set_tot, page_payload
from modules.case.tests.test_settlement_tax_basis_2026_10_03 import _dispatch

URL = "/api/quotations/%s/settlement" % NO


def _saved():
    cn = db.get_db()
    try:
        return json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
    finally:
        cn.close()


def _put(c, h, settlement, **kw):
    return c.put(URL, json=dict({"settlement": settlement}, **kw), headers=h)


# ── ① 完結：下游欄位一律覆蓋 ─────────────────────────────────────────────────────

def test_finalize_overwrites_downstream_with_server_values_even_when_within_tolerance(W):
    c, h = W
    _set_tot()
    _dispatch(10000, 2000)
    p = page_payload(c, h)
    server = _get(c, h)["totals"]["totalActualCost"]
    p["summary"]["totalActualCost"] += 1                      # 容差內的偏差：過去照存，現在以伺服器值為準
    p["summary"]["grossProfit"] -= 1
    p["summary"]["netProfit"] -= 1
    assert _put(c, h, p).status_code == 200
    s = _saved()["settlement"]["summary"]
    assert s["totalActualCost"] == server and s["grossProfit"] == 100000 - server


def test_finalize_without_item_actual_total_is_rebuilt_from_server_not_trusted(W):
    c, h = W
    _set_tot()
    _dispatch(10000, 2000)
    server = _get(c, h)["totals"]
    forged = {"status": "finalized", "items": [], "offsets": [], "summary": {"netProfit": 888888, "totalActualCost": 1, "note": "keep-me"}}
    r = _put(c, h, forged)
    assert r.status_code == 200, r.text
    s = _saved()["settlement"]["summary"]
    assert s["netProfit"] != 888888 and s["totalActualCost"] == server["totalActualCost"] and s["dispatchTotal"] == server["dispatchTotal"]
    assert "itemActualTotal" in s and s["note"] == "keep-me"            # 非計算欄位保留
    r2 = _put(c, h, {"status": "finalized", "items": [], "offsets": []}, reason="再存")
    assert r2.status_code == 200 and _saved()["settlement"]["summary"]["totalActualCost"] == server["totalActualCost"]


# ── ② 樂觀鎖 ──────────────────────────────────────────────────────────────────

def test_put_settlement_optimistic_lock(W):
    c, h = W
    g = c.get(URL, headers=h).json()
    assert g.get("updatedAt")
    r1 = _put(c, h, {"status": "draft", "items": [], "offsets": []}, expectedUpdatedAt=g["updatedAt"])
    assert r1.status_code == 200 and r1.json()["updated_at"] != g["updatedAt"]
    stale = _put(c, h, {"status": "draft", "items": [{"id": "a", "actualTotalCost": 1}], "offsets": []}, expectedUpdatedAt=g["updatedAt"])
    assert stale.status_code == 409
    assert _saved()["settlement"]["items"] == []                      # 衝突不存檔
    fresh = _put(c, h, {"status": "draft", "items": [], "offsets": []}, expectedUpdatedAt=r1.json()["updated_at"])
    assert fresh.status_code == 200
    assert _put(c, h, {"status": "draft", "items": [], "offsets": []}).status_code == 200      # 舊頁面不帶欄位：不受影響


def test_whole_quote_save_does_not_overwrite_settlement_body(W):
    c, h = W
    cn = db.get_db()
    cn.execute("UPDATE quotations SET status='草稿' WHERE quote_no=?", (NO,))
    cn.commit()
    cn.close()
    assert _put(c, h, {"status": "draft", "items": [{"id": "a", "actualTotalCost": 777}], "offsets": []}).status_code == 200
    q = _saved()
    q["settlement"] = {"status": "draft", "items": [{"id": "a", "actualTotalCost": 1}], "offsets": [], "stale": True}      # 舊頁面帶著過期的精算本文
    r = c.put("/api/quotations/%s" % NO, json={"status": "草稿", "data": q}, headers=h)
    assert r.status_code == 200, r.text
    st = _saved()["settlement"]
    assert st["items"][0]["actualTotalCost"] == 777 and "stale" not in st


# ── ③ 負數／零和採購列 ──────────────────────────────────────────────────────────

def _offset_extra(eid, item="b"):
    return {"kind": "extra", "ref": str(eid), "itemId": item}


def test_negative_refund_row_counts_as_a_purchase(W):
    c, h = W
    eid = _extra("退款", -300)
    _put_settlement({"items": [{"id": "b", "adoptSystem": True}], "offsets": [_offset_extra(eid)]})
    b = _items(_get(c, h))["b"]
    assert b["hasPurchase"] is True and b["purchased"] == -300
    assert b["actual"]["amount"] == -300 and b["actual"]["replacedEstimate"] is True


def test_zero_sum_purchase_rows_still_replace_the_estimate(W):
    c, h = W
    e1, e2 = _extra("買", 100), _extra("退", -100)
    _put_settlement({"items": [{"id": "b", "adoptSystem": True}], "offsets": [_offset_extra(e1), _offset_extra(e2)]})
    b = _items(_get(c, h))["b"]
    assert b["hasPurchase"] is True and b["actual"]["amount"] == 0 and b["actual"]["source"] == "purchase"


def test_positive_purchase_behaviour_unchanged_and_adopt_off_keeps_estimate(W):
    c, h = W
    eid = _extra("正常", 400)
    _put_settlement({"items": [{"id": "b", "adoptSystem": False}], "offsets": [_offset_extra(eid)]})
    b = _items(_get(c, h))["b"]
    assert b["hasPurchase"] is True and b["actual"]["amount"] == EST_B and b["actual"]["source"] == "estimate"
    _put_settlement({"items": [{"id": "b", "adoptSystem": True}], "offsets": [_offset_extra(eid)]})
    assert _items(_get(c, h))["b"]["actual"]["amount"] == 400


# ── ④ 派發被吸收時的列：PDF／獎金精算表 ─────────────────────────────────────────────

def test_summary_carries_absorbed_total_and_rows_sum_to_total(W):
    c, h = W
    _set_tot()
    d1 = _dispatch(10000, 2000)
    _put_settlement({"items": [{"id": "a", "adoptSystem": True}], "offsets": [{"kind": "dispatch", "ref": str(d1), "itemId": "a"}]})
    t = _get(c, h)["totals"]
    gross = 100000 - t["totalActualCost"]
    admin, charity = SA.round_half_up(100000, 0.10), SA.round_half_up(gross, 0.01)
    net = gross - admin - charity
    p = page_payload(c, h, totalActualCost=t["totalActualCost"], grossProfit=gross, charityDonation=charity, netProfit=net,
                     grossMarginPct=round(gross / 1000, 1), netMarginPct=round(net / 1000, 1))
    p["items"] = [{"id": "a", "adoptSystem": True, "actualTotalCost": 12000}, {"id": "b", "adoptSystem": True, "actualTotalCost": EST_B}]
    p["offsets"] = [{"kind": "dispatch", "ref": str(d1), "itemId": "a"}]
    r = _put(c, h, p)
    assert r.status_code == 200, r.text
    s = _saved()["settlement"]["summary"]
    assert s["dispatchAbsorbedTotal"] == 12000
    assert s["itemActualTotal"] + s["itemPoUnadopted"] + s["extraTotal"] + s["dispatchTotal"] - s["dispatchAbsorbedTotal"] == s["totalActualCost"]


def test_bonus_settlement_rows_show_an_explicit_absorbed_row_only_when_absorbed():
    from modules.payroll import bonus_pdf as BP
    plain = {"summary": {"itemActualTotal": 100, "extraTotal": 0, "dispatchTotal": 50, "totalActualCost": 150}}
    absorbed = {"summary": {"itemActualTotal": 150, "extraTotal": 0, "dispatchTotal": 50, "dispatchAbsorbedTotal": 50, "totalActualCost": 150}}
    legacy_html = BP._settlement_rows_html(plain)
    assert "已併入品項" not in legacy_html
    html = BP._settlement_rows_html(absorbed)
    assert "已併入品項" in html and html.index("承攬商派發成本") < html.index("已併入品項") < html.index("實際總成本")
    assert html.replace(html[html.index("<tr><td>已併入品項"):html.index("</tr>", html.index("已併入品項")) + 5], "") != ""


def test_closing_pdf_rows_for_absorbed_dispatch():
    import pdf_gen
    assert hasattr(pdf_gen, "_dispatch_absorbed_row")
    assert pdf_gen._dispatch_absorbed_row({"dispatchTotal": 50}) == ""                      # 舊案／沒吸收：一個位元組都不加
    assert "已併入品項" in pdf_gen._dispatch_absorbed_row({"dispatchAbsorbedTotal": 50})


# ── ⑤ 完結快照、歷程上限、已刪品項 ───────────────────────────────────────────────

def test_finalize_history_entry_has_snapshot(W):
    c, h = W
    _set_tot()
    _dispatch(10000, 2000)
    assert _put(c, h, page_payload(c, h)).status_code == 200
    ent = [e for e in _saved()["editHistory"] if e["type"] == "settlement_finalized"][-1]
    s = _saved()["settlement"]["summary"]
    assert ent["netProfit"] == s["netProfit"] and ent["totalActualCost"] == s["totalActualCost"] and ent["dispatchBasis"] == "pretax" and ent["frozenAt"]


def test_consecutive_draft_saves_do_not_grow_history_without_bound(W):
    c, h = W
    for i in range(60):
        assert _put(c, h, {"status": "draft", "items": [{"id": "a", "actualTotalCost": i + 1}], "offsets": []}).status_code == 200
    hist = [e for e in _saved().get("editHistory", []) if e["type"] == "settlement_draft"]
    assert len(hist) <= 5 and hist[-1]["rev"] >= 1
    # 完結／重新開啟（有理由）的紀錄不被合併吞掉
    _set_tot()
    assert _put(c, h, page_payload(c, h)).status_code == 200
    assert _put(c, h, {"status": "draft", "items": [], "offsets": []}, reason="重開").status_code == 200
    types = [e["type"] for e in _saved()["editHistory"]]
    assert "settlement_finalized" in types and any(e.get("reason") == "重開" for e in _saved()["editHistory"])


def test_history_keeps_only_last_50_settlement_draft_entries(W):
    c, h = W
    d = _saved()
    d["editHistory"] = [{"rev": i + 1, "at": "2026-01-01T00:00:%02d" % (i % 60), "by": "u%d" % i, "byDisplay": "u", "type": "settlement_draft"} for i in range(70)]
    cn = db.get_db()
    cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
    cn.commit()
    cn.close()
    assert _put(c, h, {"status": "draft", "items": [], "offsets": []}).status_code == 200
    assert len([e for e in _saved()["editHistory"] if e["type"] == "settlement_draft"]) <= 50


def test_orphan_saved_items_are_exposed_read_only(W):
    c, h = W
    _put_settlement({"items": [{"id": "a", "actualTotalCost": 5}, {"id": "gone", "description": "已刪品項", "actualTotalCost": 321, "adoptSystem": False}], "offsets": []})
    d = _get(c, h)
    assert [o["id"] for o in d["orphanItems"]] == ["gone"] and d["orphanItems"][0]["actualTotalCost"] == 321
    assert "gone" not in _items(d)
    _put_settlement({"items": [{"id": "a"}], "offsets": []})
    assert _get(c, h)["orphanItems"] == []


# ── 稽核 AUDIT-T38 稽核項目 ───────────────────────────────────────────

def _post_quote(c, h, **extra):
    data = {"customerName": "京城", "projectName": "偽造探針", "quoteDate": "2026-10-04", "validDays": 30, "salesPerson": "pl_sa", "items": [], "tot": {"total": 1000, "pretax": 952}}
    data.update(extra)
    return c.post("/api/quotations", headers=h, json={"data": data, "status": "草稿"})


def _row(no):
    cn = db.get_db()
    try:
        r = cn.execute("SELECT deal_tag, settle_status, data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()
        return r["deal_tag"], r["settle_status"], json.loads(r["data_json"])
    finally:
        cn.close()


def test_create_quotation_ignores_client_deal_tag_and_settlement(W):
    c, h = W
    forged = {"status": "finalized", "items": [], "summary": {"netProfit": 99999999, "totalActualCost": 1}}
    r = _post_quote(c, h, dealTag="已結案", settlement=forged)
    assert r.status_code == 201, r.text
    deal_tag, settle_status, data = _row(r.json()["quote_no"])
    assert deal_tag == "" and settle_status == "" and "settlement" not in data and data.get("dealTag", "") == ""


def test_create_quotation_copy_to_new_shape_still_creates(W):
    c, h = W
    r = _post_quote(c, h, dealTag="", settlement=None)                # 前端 copyToNew 的形狀
    assert r.status_code == 201, r.text
    deal_tag, settle_status, data = _row(r.json()["quote_no"])
    assert (deal_tag, settle_status) == ("", "") and data["projectName"] == "偽造探針"


def test_whole_quote_put_cannot_set_deal_tag_or_settlement_status(W):
    c, h = W
    cn = db.get_db()
    cn.execute("UPDATE quotations SET status='草稿' WHERE quote_no=?", (NO,))
    cn.commit()
    cn.close()
    q = _saved()
    q["dealTag"] = "已結案"
    q["settlement"] = {"status": "finalized", "items": [], "summary": {"netProfit": 99999999}}
    assert c.put("/api/quotations/%s" % NO, json={"status": "草稿", "data": q}, headers=h).status_code == 200
    deal_tag, settle_status, data = _row(NO)
    assert deal_tag != "已結案" and settle_status != "finalized" and (data.get("settlement") or {}).get("status") != "finalized"


def test_forged_original_side_keys_are_overwritten_by_server(W):
    c, h = W
    _set_tot()
    _dispatch(10000, 2000)
    p = page_payload(c, h)
    p["summary"].update(origNetProfit=777777, profitDiff=555555, origTotalCost=1, quotedTotal=9, origDirectProfit=5, origAdminCost=5, origCharity=5, origMarginPct=99.9, origNetMarginPct=99.9)
    assert _put(c, h, p).status_code == 200
    s = _saved()["settlement"]["summary"]
    assert s["origTotalCost"] == 10500 and s["quotedTotal"] == 105000 and s["origDirectProfit"] == 89500
    assert s["origAdminCost"] == 10000 and s["origCharity"] == 895 and s["origNetProfit"] == 78605
    assert s["profitDiff"] == s["netProfit"] - 78605 and s["origMarginPct"] != 99.9 and s["origNetMarginPct"] != 99.9


def test_readers_fall_back_to_page_key_dispatch_absorbed():
    import pdf_gen
    from modules.payroll import bonus_pdf as BP
    old_final = {"dispatchTotal": 50, "dispatchAbsorbed": 50}               # 36／37 班完結案：只有頁面寫的鍵
    assert "已併入品項" in pdf_gen._dispatch_absorbed_row(old_final)
    assert "已併入品項" in BP._settlement_rows_html({"summary": dict(old_final, itemActualTotal=150, totalActualCost=150)})
    assert pdf_gen._dispatch_absorbed_row({"dispatchTotal": 50}) == ""


def test_finalize_response_returns_the_server_overwritten_summary(W):
    c, h = W
    _set_tot()
    _dispatch(10000, 2000)
    p = page_payload(c, h)
    p["summary"]["totalActualCost"] += 1
    r = _put(c, h, p)
    assert r.status_code == 200
    assert r.json()["summary"] == _saved()["settlement"]["summary"]
    d = _put(c, h, {"status": "draft", "items": [], "offsets": []}, reason="重開")
    assert d.status_code == 200 and "summary" not in d.json()
