# -*- coding: utf-8 -*-
"""【預備的紅燈測試，尚未實作；裁示 Q1–Q6 回來後可能要微調】精算「全含稅」（使用者 2026-10-06 裁示）：承攬商成本改回含稅（未稅承攬費＋稅額＋外包人員），
標記 `summary.dispatchBasis`：沒有鍵＝35c 前含稅（凍結）、'pretax'＝35c／36 完結（凍結，值不改）、'taxed'＝新口徑。不借用 schemaVersion。
稅額顯示：`totals.taxExpense = {exact, estimated, unsplit}`（形狀為提案，待裁示 Q1／Q2）。

目前紅燈（依提案行為）：新口徑的草稿合計／完結寫入標記／完結比對／營運報表應計金額／稅額拆分。
目前綠燈（實作後必須維持，是凍結與口徑配對的平行對照）：舊標記完結案原樣、過期比對口徑對口徑。
"""
import json

import pytest

import db
from modules.case import recognition as R
from modules.case.tests.test_settlement_actuals_2026_10_03 import _get, _put_settlement
from modules.case.tests.test_settlement_finalize_integrity_2026_10_03 import (  # noqa: F401
    NO, URL, W, _approved_po, _dispatch, _ln, _put, _set_tot, _status, case, page_payload, quote_is_won)

# 紅燈：新口徑（含稅）--------------------------------------------------------------------------------

def test_draft_dispatch_cost_is_tax_inclusive_plus_personnel(W):
    """未稅 10000、5%、人員 2000 ⇒ 計入成本 12500（＝含稅承攬費 10500＋人員 2000）；稅額 500 仍並列；口徑標記 'taxed'。"""
    c, h = W
    base = _get(c, h)["totals"]["totalActualCost"]
    _dispatch(10000, 2000)
    t = _get(c, h)["totals"]
    assert t["dispatchTotal"] == 12500 and t["dispatchBasis"] == "taxed", t
    assert t["dispatchTax"] == 500 and t["dispatchGrandTotal"] == 12500
    assert t["totalActualCost"] - base == 12500                                      # 35c 是 +12000


def test_honest_page_payload_finalizes_and_stores_the_taxed_marker(case):
    c, h = case
    r = _put(c, h, page_payload(c, h, dispatchBasis="taxed"))
    assert r.status_code == 200, r.text
    assert _get(c, h)["totals"]["dispatchBasis"] == "taxed" and _get(c, h)["totals"]["dispatchTotal"] == 12500


def test_taxed_marker_with_pretax_numbers_is_rejected_409(case):
    """標 'taxed' 卻送未稅合計（頁面與後端口徑錯配／偽造）⇒ 409，不存檔。"""
    c, h = case
    r = _put(c, h, page_payload(c, h, dispatchBasis="taxed", dispatchTotal=12000))      # 12000＝35c 未稅值；新口徑 live＝12500
    assert r.status_code == 409 and _status() != "finalized", r.text


def test_a_35c_draft_stays_pretax_until_the_page_saves_it_as_taxed(W):
    """Q5：草稿存檔標記 pretax ⇒ 後端維持未稅算（總成本不變）；標記改 taxed（轉換後存檔）⇒ 含稅；完結後標記 pretax 的凍結值不動。"""
    c, h = W
    _dispatch(10000, 2000)
    _put_settlement({"status": "draft", "items": [], "offsets": [], "summary": {"dispatchBasis": "pretax"}})
    t = _get(c, h)["totals"]
    assert t["dispatchBasis"] == "pretax" and t["dispatchTotal"] == 12000 and t["dispatchGrandTotal"] == 12500 and t["taxExpense"]["exact"] == 0, t
    _put_settlement({"status": "draft", "items": [], "offsets": [], "summary": {"dispatchBasis": "taxed"}})
    t = _get(c, h)["totals"]
    assert t["dispatchBasis"] == "taxed" and t["dispatchTotal"] == 12500 and t["taxExpense"]["exact"] == 500, t


def test_new_finalize_with_the_old_pretax_marker_is_refused_until_converted(case):
    """（待 Q5 裁示；建議行為）35c 時期存的草稿帶 'pretax'：完結時要先「轉為含稅」，不靜默改數字也不接受舊口徑新完結。"""
    c, h = case
    r = _put(c, h, page_payload(c, h, dispatchBasis="pretax", dispatchTotal=12000))
    assert r.status_code == 409 and _status() != "finalized" and "轉為含稅口徑" in r.text, r.text          # 訊息要叫人去轉換，不是只丟「數字對不上」


def test_recognition_accrual_dispatch_entries_are_tax_inclusive_with_exact_tax(W):
    """營運報表應計：Σ dispatch_entries＝含稅＋人員（12500），每筆帶 `tax`（500，精確）與 taxKind。（Q4 若限定切換日，測試加日期條件）"""
    c, h = W
    _dispatch(10000, 2000)
    cn = db.get_db()
    try:
        es = [e for e in R.dispatch_entries(cn, "accrual") if e["quoteNo"] == NO]
    finally:
        cn.close()
    assert sum(e["amount"] for e in es) == 12500
    assert sum(e.get("tax", 0) for e in es) == 500 and all(e.get("taxKind") == "exact" for e in es if e.get("tax")), es
    assert all("含稅" in e["taxNote"] for e in es), es


def test_tax_expense_splits_exact_from_estimated_and_unsplit(case):
    """承攬商稅 500＝精確；品項（採購單含稅最終金額無稅欄、估計列＝報價成本×1.05）一律「推估」＝金額−金額÷1.05（逐品項進位，容差每品項 ±1）；額外支出沒稅額 ⇒ unsplit。
    形狀待 Q1／Q2。"""
    c, h = case
    d = _get(c, h)
    te = d["totals"]["taxExpense"]
    exp_est = sum(R.estimated_tax(i["actual"]["amount"]) for i in d["items"])               # 與實作同一個推估函式、逐品項進位：必須完全相等（不留容差）
    assert te["exact"] == 500 and te["estimated"] == exp_est and te["estimated"] > 0 and te["unsplit"] == 0, (te, exp_est)


def test_finalized_summary_freezes_tax_expense(case):
    c, h = case
    assert _put(c, h, page_payload(c, h, dispatchBasis="taxed")).status_code == 200
    te = _get(c, h)["totals"]["taxExpense"]
    assert te["exact"] == 500 and te["estimated"] > 0, te                            # 完結後讀存檔值
    _put_settlement({"status": "finalized", "items": [], "summary": {"itemActualTotal": 1, "extraTotal": 0, "dispatchTotal": 12500, "totalActualCost": 12501}})
    assert _get(c, h)["totals"]["taxExpense"] is None, "完結於稅額功能之前的舊案：沒有資料就是 None，不現算、不改寫"


def test_tax_expense_is_hidden_without_financial_view(case, make_user):
    """遮罩：看得到案件、但沒有財務檢視的帳號，精算端點 403，回應裡沒有稅額。"""
    c, h = case
    eu, ep = make_user(username="tx_eng", role="engineer", modules=["case_manage", "expense_forms"])
    from modules.case.tests.test_settlement_actuals_2026_10_03 import _login
    he = _login(c, eu, ep)
    cn = db.get_db()
    uid = cn.execute("SELECT id FROM users WHERE username='tx_eng'").fetchone()["id"]
    cn.execute("UPDATE quotations SET assigned_user_ids=? WHERE quote_no=?", (json.dumps([uid]), NO))
    cn.commit()
    cn.close()
    r = c.get("/api/quotations/%s/settlement-actuals" % NO, headers=he)
    assert r.status_code == 403 and "taxExpense" not in r.text, r.text[:200]
    assert "taxExpense" in c.get("/api/quotations/%s/settlement-actuals" % NO, headers=h).text           # 正對照：有權限的人看得到


def _dispatch_on(dispatch_date, invoice_date, total=10000, personnel=2000):
    cn = db.get_db()
    try:
        vid = cn.execute("SELECT id FROM vendor_contractors WHERE name='稅基測試承攬商'").fetchone()
        if not vid:
            cn.execute("INSERT INTO vendor_contractors (name, tax_id, created_at, updated_at) VALUES ('稅基測試承攬商','87650001','2026-10-03','2026-10-03')")
            vid = cn.execute("SELECT id FROM vendor_contractors WHERE name='稅基測試承攬商'").fetchone()
        cn.execute(
            "INSERT INTO contractor_dispatches (quote_no, vendor_id, dispatch_date, scope, items_json, total_amount, tax_rate, personnel_json, status, approval_status,"
            " invoice_no, invoice_date, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (NO, vid["id"], dispatch_date, "amount", "[]", total, 0.05, json.dumps([{"name": "甲", "amount": personnel}]), "accepted", "", "ZZ1", invoice_date,
             "2026-10-03", "2026-10-03"))
        cn.commit()
    finally:
        cn.close()


def test_report_cutover_september_dispatch_unchanged_october_dispatch_taxed(W):
    """Q4：以派發單自己的 dispatch_date 判斷；9 月派發（含發票日在 10 月的）照舊未稅＋人員、不帶稅；10/01 起含稅＋精確稅額。完結案不受影響（另測）。"""
    c, h = W
    _dispatch_on("2026-09-15", "2026-09-20")                         # 9 月派發
    _dispatch_on("2026-10-01", "2026-10-05")                         # 切換日當天
    _dispatch_on("2026-09-30", "2026-10-02")                         # 9/30 派發、10 月開發票：仍是舊口徑（看派發日，不看發票日）
    cn = db.get_db()
    try:
        es = sorted((e["date"], e["amount"], e["tax"], e["taxKind"]) for e in R.dispatch_entries(cn, "accrual") if e["quoteNo"] == NO)
    finally:
        cn.close()
    assert es == [("2026-09-20", 12000, 0.0, ""), ("2026-10-02", 12000, 0.0, ""), ("2026-10-05", 12500, 500.0, "exact")], es


def test_expense_report_rows_and_monthly_block_split_exact_estimated_unsplit(W):
    """營運報表：每列 tax／taxKind；月累計 taxExact／taxEstimated／taxUnsplit；承攬商 10 月含稅、9 月照舊。"""
    c, h = W
    _dispatch_on("2026-09-15", "2026-09-20")
    _dispatch_on("2026-10-01", "2026-10-05")
    _insert_extra(total=1050, tax=50, kind="")                        # 有稅額的額外支出單據 ⇒ exact 50
    _insert_extra(total=2000, tax=0, kind="")                         # 簡單額外支出無稅額 ⇒ unsplit 2000（備忘）
    from modules.analytics.api.reports import _collect_expenses
    ex = _collect_expenses(2026, None, "accrual")
    sep, octo = [m for m in ex["monthly"] if m["month"] in ("2026-09", "2026-10")]
    assert sep["contractor"] == 12000 and sep["taxExact"] == 0 and sep["taxContractor"] == 0
    assert octo["contractor"] == 12500 and octo["taxExact"] == 500 + 50 and octo["taxUnsplit"] == 2000, octo
    rows = {(r["desc"][:2], r["taxKind"]): r["tax"] for r in ex["details"]["contractor"] + ex["details"]["other"] if r.get("taxKind")}
    assert any(k[1] == "exact" and v == 500 for k, v in rows.items()) and any(k[1] == "unsplit" for k in rows), rows
    assert ex["totals"]["taxExact"] == 550 and ex["totals"]["taxUnsplit"] == 2000


def _insert_extra(total, tax, kind, day="2026-10-06"):
    cn = db.get_db()
    try:
        cn.execute("INSERT INTO case_extra_expenses (quote_no, category, description, total_cost, expense_date, status, created_at, updated_at, tax, kind)"
                   " VALUES (?,?,?,?,?,?,?,?,?,?)", (NO, "雜費", "稅額測試", total, day, "已核准", day + "T00:00:00", day + "T00:00:00", tax, kind))
        cn.commit()
    finally:
        cn.close()


def test_po_and_material_tax_are_estimated_not_exact(W):
    from modules.case.recognition import estimated_tax
    assert estimated_tax(1050) == 50 and estimated_tax(3000) == 143 and estimated_tax(0) == 0 and estimated_tax(-5) == 0


def test_ledger_diff_keeps_the_contractor_tax_in_its_own_bucket(W):
    """對總帳差異：10 月起承攬商成本含稅，總帳稅額在 1268；差額進 tax 分桶，不讓 residual 暴增。"""
    from modules.analytics.api import ledger_diff as L
    _dispatch_on("2026-10-01", "2026-10-05")
    out = L.build(2026, "accrual")
    m = next(x for x in out["months"] if x["month"] == "2026-10")
    cat = m["expense"]["categories"]["contractor"]
    assert cat["report"] >= 12500
    if "buckets" in cat:
        assert cat["buckets"]["tax"] == 500, cat["buckets"]


# 綠燈：凍結與口徑配對（實作後必須維持）-------------------------------------------------------------

@pytest.mark.parametrize("marker,stored,basis", [(None, 12500, "taxed"), ("pretax", 12000, "pretax"), ("taxed", 12500, "taxed")])
def test_finalized_summaries_stay_exactly_as_stored(W, marker, stored, basis):
    c, h = W
    _dispatch(10000, 2000)
    summ = {"itemActualTotal": 1, "extraTotal": 0, "dispatchTotal": stored, "totalActualCost": stored + 1}
    if marker:
        summ["dispatchBasis"] = marker
    _put_settlement({"status": "finalized", "items": [], "summary": summ})
    t = _get(c, h)["totals"]
    assert t["dispatchTotal"] == stored and t["totalActualCost"] == stored + 1 and t["dispatchBasis"] == basis


def _stale(summary):
    from modules.analytics.api.reports import _collect
    from modules.analytics.tests.test_reports_logic_fixes_2026_08_28 import _insert_case, _insert_dispatch
    _insert_case("MQ-TX-001", deal_tag="已結案", settlement={"status": "finalized", "summary": summary})
    _insert_dispatch("MQ-TX-001", total_amount=45000)           # 未稅 45000；含稅 47250
    return _collect("2026-01-01", "2026-12-31")["summary"]["staleSettlementCount"]


@pytest.mark.parametrize("summary,stale", [
    ({"dispatchTotal": 47250, "netProfit": 1}, 0),                                   # 無標記＝含稅
    ({"dispatchTotal": 45000, "dispatchBasis": "pretax", "netProfit": 1}, 0),         # 35c／36 完結＝未稅
    ({"dispatchTotal": 47250, "dispatchBasis": "taxed", "netProfit": 1}, 0),          # 新口徑＝含稅
    ({"dispatchTotal": 45000, "dispatchBasis": "taxed", "netProfit": 1}, 1),          # 標含稅卻存未稅值 ⇒ 過期
    ({"dispatchTotal": 47250, "dispatchBasis": "pretax", "netProfit": 1}, 1),         # 標未稅卻存含稅值 ⇒ 過期
])
def test_stale_check_pairs_each_marker_with_its_own_live_basis(client, summary, stale):
    assert _stale(summary) == stale


# ── 稽核 a4 的補強（2026-10-06）─────────────────────────────────────────────

def _items_stub(po_docs=(), extra_docs=()):
    return [{"itemId": "a", "hasPurchase": True, "adopt": True, "po": {"docs": list(po_docs)}, "material": {"orders": []},
             "extra": {"docs": list(extra_docs)}, "actual": {"source": "purchase", "amount": 4000}}]


def test_multi_line_po_with_a_document_tax_is_not_double_counted():
    """稅額只放在單據第一列，其餘列 tax＝0 但已被涵蓋：探針＝PO 3000＋1000、單據稅 190 ⇒ 確定 190、推估 0（原本多算 48）；額外支出同理不得掉進 unsplit。"""
    from modules.case import settlement_actuals as SA
    ex = {"dispatch": {"tax": 0}}
    po = [{"amount": 3000, "tax": 190, "taxKind": "exact"}, {"amount": 1000, "tax": 0, "taxKind": "exact"}]
    te = SA._tax_expense(_items_stub(po_docs=po), [], [], ex, "taxed", {}, 2)
    assert te == {"exact": 190, "estimated": 0, "unsplit": 0}, te
    extra = [{"amount": 3000, "tax": 190, "taxKind": "exact"}, {"amount": 1000, "tax": 0, "taxKind": "exact"}]
    assert SA._tax_expense([], [], extra, ex, "taxed", {}, 2) == {"exact": 190, "estimated": 0, "unsplit": 0}
    # 正對照：沒有稅額的採購單＝每列推估；沒有稅額的額外支出＝未拆稅（只列金額）
    po2 = [{"amount": 3000, "tax": 0, "taxKind": "estimated"}, {"amount": 1000, "tax": 0, "taxKind": "estimated"}]
    assert SA._tax_expense(_items_stub(po_docs=po2), [], [{"amount": 700, "tax": 0, "taxKind": "unsplit"}], ex, "taxed", {}, 2) == {
        "exact": 0, "estimated": R.estimated_tax(3000) + R.estimated_tax(1000), "unsplit": 700}


def _insert_typed(kind, lines, total, tax, code):
    cn = db.get_db()
    try:
        cn.execute("INSERT INTO case_extra_expenses (quote_no, category, description, total_cost, expense_date, status, created_at, updated_at, tax, kind, lines_json, doc_code)"
                   " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (NO, "雜費", "多列單據", total, "2026-10-06", "已核准", "2026-10-06T00:00:00", "2026-10-06T00:00:00", tax, kind,
                                                       json.dumps(lines, ensure_ascii=False), code))
        cn.commit()
    finally:
        cn.close()


def test_typed_documents_carry_their_tax_once_and_label_the_kind(W):
    c, h = W
    lines = [{"categoryName": "甲", "amount": 3000}, {"categoryName": "乙", "amount": 1000}]
    _insert_typed("travel", lines, 4000, 190, "TX-1")                 # 有稅額的費用單據（兩個類別 ⇒ 兩列）
    _insert_typed("purchase_order", lines, 4000, 0, "TX-2")           # 沒有稅額的採購單
    cn = db.get_db()
    try:
        es = [e for e in R.extra_entries(cn, "accrual") if e["quoteNo"] == NO]
    finally:
        cn.close()
    doc = [e for e in es if e["docCode"] == "TX-1" and e["kind"] == "travel"]
    po = [e for e in es if e["kind"] == "purchase_order"]
    assert len(doc) == 2 and sum(e["tax"] for e in doc) == 190 and {e["taxKind"] for e in doc} == {"exact"}, doc
    assert len(po) == 2 and {e["taxKind"] for e in po} == {"estimated"} and sum(e["tax"] for e in po) == R.estimated_tax(3000) + R.estimated_tax(1000), po
    te = _get(c, h)["totals"]["taxExpense"]
    assert te["exact"] == 190 and te["unsplit"] == 0, te                     # 多列單據：稅額計一次、不掉進 unsplit；無稅額的採購單（未連品項）＝推估，不是未拆稅
    items_est = sum(R.estimated_tax(i["actual"]["amount"]) for i in _get(c, h)["items"])
    assert te["estimated"] == items_est + R.estimated_tax(3000) + R.estimated_tax(1000), te


def test_a_dispatch_without_a_date_keeps_the_old_basis_and_missing_grand_total_never_goes_negative(W, monkeypatch):
    from modules.case import settlement_actuals as SA
    c, h = W
    _dispatch(10000, 2000)
    cn = db.get_db()
    try:
        cn.execute("UPDATE contractor_dispatches SET dispatch_date='' WHERE quote_no=?", (NO,))
        cn.commit()
        es = [e for e in R.dispatch_entries(cn, "accrual") if e["quoteNo"] == NO]
    finally:
        cn.close()
    assert [(e["amount"], e["tax"], e["taxKind"]) for e in es] == [(12000, 0.0, "")], es       # 沒有派發日 ⇒ 舊口徑（不猜）
    # 提供者沒給 grandTotal：稅額 0、含稅合計退回未稅＋人員，不得變負
    real = SA.registry.single_provider
    monkeypatch.setattr(SA.registry, "single_provider", lambda name: (lambda r: {"id": 1, "totalAmount": 100, "personnelTotal": 20, "approvalStatus": ""})
                        if name == "dispatch.row" else real(name))
    cn = db.get_db()
    try:
        rows = SA.dispatch_rows(cn, NO)
    finally:
        cn.close()
    assert rows and all(r["tax"] == 0 and r["amount"] == 120 for r in rows), rows


def test_saving_the_taxed_marker_twice_is_stable(W):
    c, h = W
    _dispatch(10000, 2000)
    for _ in range(2):
        _put_settlement({"status": "draft", "items": [], "offsets": [], "summary": {"dispatchBasis": "taxed"}})
        t = _get(c, h)["totals"]
        assert (t["dispatchBasis"], t["dispatchTotal"], t["taxExpense"]["exact"]) == ("taxed", 12500, 500)


def test_dispatch_entries_clamp_tax_and_fall_back_when_the_provider_has_no_grand_total(W, monkeypatch):
    """稽核 a4 U4：切換日後的應計派發列，提供者沒給 grandTotal ⇒ 稅額 0、金額＝未稅＋人員（不得變負、不得少算成本）；grandTotal 小於未稅＋人員 ⇒ 稅額夾 0。"""
    from core import registry
    _dispatch(10000, 2000)                                                  # 派發日 2026-10-01（≥ 切換日）
    real = registry.single_provider
    rows = {"d": {"id": 1, "approvalStatus": "", "vendorName": "甲", "totalAmount": 100, "personnelTotal": 20}}
    monkeypatch.setattr(registry, "single_provider", lambda name: (lambda r: dict(rows["d"])) if name == "dispatch.row" else real(name))
    cn = db.get_db()
    try:
        es = [e for e in R.dispatch_entries(cn, "accrual") if e["quoteNo"] == NO]
        assert [(e["amount"], e["tax"], e["taxKind"]) for e in es] == [(120.0, 0.0, "exact")], es          # 沒有 grandTotal
        rows["d"]["grandTotal"] = 50                                                                        # 含稅合計 < 未稅＋人員（壞資料）
        es = [e for e in R.dispatch_entries(cn, "accrual") if e["quoteNo"] == NO]
        assert [(e["amount"], e["tax"]) for e in es] == [(120.0, 0.0)], es
        rows["d"]["grandTotal"] = 126                                                                       # 正對照：正常含稅合計 ⇒ 稅 6、金額 126
        es = [e for e in R.dispatch_entries(cn, "accrual") if e["quoteNo"] == NO]
        assert [(e["amount"], e["tax"]) for e in es] == [(126.0, 6.0)], es
    finally:
        cn.close()
