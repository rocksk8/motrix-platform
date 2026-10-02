# -*- coding: utf-8 -*-
"""33-A1：`recognition.material_money_rows` 抽出後，`material_entries` 的輸出必須與抽出前**逐筆相同**（零行為變化）。
做法：把抽出前（52033606）的 `material_entries` 原文凍結在本檔當參考實作，對各種情境（草稿／待審／核准／舊單、連採購單、未連、$0、
舊付款歷史、匯款明細、發票日有無）比較權責與現金兩種口徑的整份輸出；另測原語本身的欄位與 `quote_no` 篩選。"""
import json

import pytest

import db
from modules.case import recognition as R
from modules.case.recognition import _case_rows, _material_states  # noqa: F401  (參考實作用)
from modules.case.tests.test_material_link_2026_10_02 import _put_materials
from modules.case.tests.test_material_link_booking_2026_10_02 import NO, TODAY, W, _approved_po, _order, _won_case  # noqa: F401
from modules.case.tests.test_purchase_item_lines_2026_10_02 import _ln

# ── 參考實作：抽出前的 material_entries（逐字凍結；不要改） ─────────────────────────────
def _legacy_material_entries(conn, basis, department_id=None):
    """叫料（案件 data_json）→ 逐筆。沒有稅欄位 ⇒ 一律「未拆稅」。

    審核規則（31-C，與承攬商派發同一組）：**權責口徑**——草稿／已退回／已取消**不計**；待審核／簽核中**計入並標 `pending`**；已核准與舊單（沒有審核單）照舊。
    **現金口徑**——付出去的錢是事實，不因審核狀態排除（只標 `pending`）。每筆帶 `approval`（'' ＝ 舊單）。"""
    from modules.case import material_approval as _ma
    from modules.case import material_payment as _mp
    from modules.case import purchase_items as _pi
    states = _material_states(conn)
    pay_lines, pay_legacy = (_mp.lines_by_order(conn), _mp.legacy_by_order(conn)) if basis == "cash" else ({}, {})
    out = []
    no_po = {}                                    # (案件, 叫料 itemId) ⇒ 該叫料是否「未申請採購單」（S4c；只加備註，不改金額）
    _po_cache = {}

    def po_rows_of(quote_no):
        if quote_no not in _po_cache:
            _po_cache[quote_no] = conn.execute(
                "SELECT id, kind, status, lines_json, doc_code FROM case_extra_expenses WHERE quote_no=? AND kind='purchase_order'", (quote_no,)).fetchall()
        return _po_cache[quote_no]
    for row in _case_rows(conn, department_id):
        try:
            cr = (json.loads(row["data_json"] or "{}") or {}).get("caseRecord") or {}
        except (TypeError, ValueError):
            cr = {}
        for mo in cr.get("materialOrders") or []:
            if not isinstance(mo, dict):
                continue
            name = mo.get("itemName") or "材料申請"
            paid = (mo.get("paidDate") or "")[:10]
            st = states.get((row["quote_no"], str(mo.get("itemId"))), "")
            cs = _ma.cost_state(st)
            prs = po_rows_of(row["quote_no"])
            if _pi._link_check(mo, prs)[0]:
                continue        # 32-S4c：連到有效採購單 ⇒ 金額由採購單負責（成本進品項實際成本／額外支出的採購單列），叫料只是已叫／已到追蹤——權責與現金都不重複計
            no_po[(row["quote_no"], str(mo.get("itemId")))] = _pi.material_link_status(mo, prs, legacy=(st == ""))["state"] == "none"
            if basis != "cash" and cs == "excluded":
                continue                                                           # 權責：草稿／已退回／已取消不計
            if basis == "cash":
                key = (row["quote_no"], str(mo.get("itemId")))
                if key in pay_legacy:                                              # 有匯款申請 ⇒ 讀付款明細（每筆一列）＋舊單歷史已付；不讀 JSON 的 paid*（那是投影）
                    la, ld = pay_legacy[key]
                    if la and ld:
                        out.append({"date": ld, "quoteNo": row["quote_no"], "desc": "材料申請｜" + name, "amount": la, "taxNote": "未拆稅", "provisional": False,
                                    "itemId": mo.get("itemId") or "", "approval": st, "pending": cs == "pending", "lineId": "", "fee": 0.0,
                                    "remitPending": False, "payMethod": "", "payAccountCode": ""})
                    for ln in pay_lines.get(key, []):
                        if ln["amount"] and ln["paid_at"]:
                            out.append({"date": ln["paid_at"], "quoteNo": row["quote_no"], "desc": "材料申請｜" + name, "amount": ln["amount"], "taxNote": "未拆稅",
                                        "provisional": False, "itemId": mo.get("itemId") or "", "approval": st, "pending": cs == "pending",
                                        "lineId": str(ln["id"]), "fee": ln["fee"], "remitPending": ln["review"] == "pending",
                                        "payMethod": ln["pay_method"], "payAccountCode": ln["pay_account_code"], "paymentCode": ln["doc_code"]})
                    continue
                if (mo.get("paidStatus") or "pending") == "pending" or paid == "":
                    continue
                amt = float(mo.get("paidAmount") or 0)
                if amt:
                    out.append({"date": paid, "quoteNo": row["quote_no"], "desc": "材料申請｜" + name,
                                "amount": amt, "taxNote": "未拆稅", "provisional": False,
                                "itemId": mo.get("itemId") or "", "approval": st, "pending": cs == "pending"})
                continue
            amt = float(mo.get("totalPrice") or 0)
            if not amt:
                continue
            inv = (mo.get("invoiceDate") or "")[:10]
            out.append({"date": inv if inv != "" else paid, "quoteNo": row["quote_no"],
                        "desc": "材料申請｜" + name, "amount": amt, "taxNote": "未拆稅",
                        "provisional": inv == "", "itemId": mo.get("itemId") or "", "invoiceDate": inv,
                        "approval": st, "pending": cs == "pending"})
    for e in out:
        e["noPo"] = bool(no_po.get((e["quoteNo"], str(e.get("itemId") or ""))))
    return out


def _scenario(c, h):
    po = _approved_po(c, h, [_ln("a", 3, unitCost=1000)])
    _put_materials([
        _order("K", 3, 3000, quoteItemId="a", poDocCode=po["docCode"], poLine=1),                       # 連到有效採購單（略過）
        _order("N", 2, 800),                                                                            # 未連、核准
        _order("D", 1, 500),                                                                            # 草稿
        _order("P", 1, 700, invoiceDate=""),                                                            # 待審核、沒發票日
        _order("Z", 1, 0),                                                                              # $0
        _order("O", 1, 400, paidStatus="paid", paidAmount=400, paidDate="2026-08-01"),                  # 舊付款歷史（舊單）
        _order("C", 1, 300),                                                                            # 已取消
        _order("L", 1, 200, paidStatus="paid", paidAmount=200, paidDate="2026-08-02"),                  # 舊單（沒有審核列）
        _order("H", 1, 100, quoteItemId="a", poDocCode=po["docCode"], poLine=1, paidStatus="paid", paidAmount=100, paidDate="2026-08-03"),   # 有連結但已有付款紀錄 ⇒ 不算連結
    ], {"K": "已核准", "N": "已核准", "D": "草稿", "P": "待審核", "C": "已取消", "O": "已核准", "H": "已核准"})


@pytest.mark.parametrize("basis", ["accrual", "cash"])
def test_material_entries_is_identical_to_the_frozen_pre_extraction_implementation(W, basis):
    c, h = W
    _scenario(c, h)
    cn = db.get_db()
    try:
        old = _legacy_material_entries(cn, basis)
        new = R.material_entries(cn, basis)
    finally:
        cn.close()
    assert old, "情境必須真的產生列（不然比對沒有意義）"
    assert new == old                                                                                   # 逐筆、逐鍵、同順序


def test_primitive_fields_and_quote_filter(W):
    c, h = W
    _scenario(c, h)
    cn = db.get_db()
    try:
        rows = {r["itemId"]: r for r in R.material_money_rows(cn)}
        assert set(rows) == {"K", "N", "D", "P", "Z", "O", "C", "L", "H"}
        assert (rows["K"]["linked"], rows["K"]["noPo"]) == (True, False)                                # 連採購單：不標
        assert (rows["N"]["linked"], rows["N"]["noPo"], rows["N"]["cost"], rows["N"]["state"]) == (False, True, "counted", "已核准")
        assert (rows["D"]["cost"], rows["P"]["cost"], rows["C"]["cost"]) == ("excluded", "pending", "excluded")
        assert rows["L"]["state"] == "" and rows["L"]["noPo"] is False                                  # 舊單不標
        assert rows["Z"]["noPo"] is False and rows["Z"]["total"] == 0.0                                 # $0 不標
        assert (rows["H"]["linked"], rows["H"]["noPo"]) == (False, True)                                # 已有付款紀錄不視為連結 ⇒ 金額留在材料申請、標「未申請採購單」
        assert rows["N"]["total"] == 800.0 and rows["N"]["name"].startswith("品")
        assert [r["quoteNo"] for r in R.material_money_rows(cn, quote_no=NO)] == [NO] * 9
        assert R.material_money_rows(cn, quote_no="MQ-NOPE") == []                                      # 只取那一案
    finally:
        cn.close()
