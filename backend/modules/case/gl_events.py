# -*- coding: utf-8 -*-
"""M01 → M06 總帳事件提供者（`gl.events`，IP-GL1，契約 v1）：案件額外支出 E11／E11b、叫料 E12／E12b。設計：proposal-gl/02-events-engine.md §4。

- E11 額外支出（只收**已核准**；草稿、送審中、已駁回不入帳）：日期＝發票日 → 核准日 → 憑證日（與營運報表權責口徑同一條規則，`recognition.extra_entries`）；
  借 專案成本（依案件）／貸 應付帳款，金額＝`total_cost`。來源金額是**未拆稅**（含稅），進項稅額請在 `gl_source_annotations` 補登（`input_tax`），
  引擎收集時把成本拆成「未稅成本＋進項稅額」。
- E11b 額外支出付款（出納登錄的付款日）：借 應付帳款＋手續費（公司自付）／貸 銀行＝實付＋手續費；實付≠應付且**已核可**⇒差額入其他費用；差額**待審核**⇒不產生並 notice。
- E12 叫料（案件 `caseRecord.materialOrders`）：日期＝發票日，沒有發票日退回付款日（標 `date_estimated`）；借 專案成本（依案件）／貸 應付帳款，金額＝`totalPrice`（未拆稅，同上）。
- E12b 叫料付款（已付款、有付款日）：借 應付帳款／貸 銀行＝`paidAmount`。
- 保固（使用者裁示）：本批不特別處理，保固實際發生仍歸專案成本。
只讀，不寫資料。
"""
import json

from db import get_db
from helpers.legal_params import round_half_up
from modules.case import expense_forms as _EF
from modules.case import recognition as _rec


def _i(x):
    return int(round_half_up(x or 0))


def _accrual_lines(r, total, memo) -> list:
    """E11 應付認列的分錄行。舊版列（kind=''）＝單一借方（案件成本）——**行為不變**。
    費用單據（kind≠''）且明細金額加總＝單據金額 ⇒ 依費用類別**逐類**借方（行上帶 `category`＝類別代碼，W4 引擎據此重新解科目；
    有案件 COST_PROJECT、無案件 EXP_OTHER），貸方 AP 合計。明細對不上金額（不該發生）⇒ 退回單一借方，不猜。"""
    role = "COST_PROJECT" if r["quote_no"] else "EXP_OTHER"
    ap = {"role": "AP", "side": "C", "amount": total, "memo": memo}
    if not (r["kind"] or ""):
        return [{"role": "COST_PROJECT", "side": "D", "amount": total, "memo": memo}, ap]
    try:
        lines = json.loads(r["lines_json"] or "[]")
    except (TypeError, ValueError):
        lines = []
    by_cat = {}
    for l in lines if isinstance(lines, list) else []:
        if isinstance(l, dict):
            key = l.get("categoryCode") or l.get("category") or ""
            by_cat[key] = by_cat.get(key, 0) + _i(l.get("amount"))
    if not by_cat or sum(by_cat.values()) != total or any(v <= 0 for v in by_cat.values()):
        return [{"role": role, "side": "D", "amount": total, "memo": memo}, ap]
    return [{"role": role, "side": "D", "amount": v, "memo": memo, **({"category": k} if k else {})} for k, v in by_cat.items()] + [ap]


def gl_events(start, end, *, changed_since=""):
    events, notices = [], []
    conn = get_db()
    try:
        extra_rows = conn.execute(
            "SELECT id, quote_no, category, description, total_cost, expense_date, created_at, doc_no, invoice_no, invoice_date, approval_json,"
            " paid_date, remit_actual, remit_fee, remit_review, kind, lines_json, pay_method, pay_account_code"
            " FROM case_extra_expenses WHERE status='已核准' AND " + _EF.payable_sql() + " ORDER BY id").fetchall()
        mat_accrual = _rec.material_entries(conn, "accrual")
        mat_cash = _rec.material_entries(conn, "cash")
    finally:
        conn.close()
    unsplit = typed_unsplit = pending = nodate = 0

    for r in extra_rows:
        total = _i(r["total_cost"])
        if total <= 0:
            continue
        inv = (r["invoice_date"] or "")[:10]
        d = (inv or _rec._approved_at(r["approval_json"]) or (r["expense_date"] or r["created_at"] or ""))[:10]
        memo = "%s %s" % (r["category"] or "額外支出", (r["description"] or "")[:30])
        doc = r["invoice_no"] or r["doc_no"] or ""
        if d and start <= d <= end:
            if r["kind"]:
                typed_unsplit += 1                                  # 費用單據：不是「專案成本」，另列說明
            else:
                unsplit += 1
            events.append({
                "source_type": "case_extra_expense", "source_key": str(r["id"]), "event_code": "E11", "event_date": d, "doc_no": doc,
                "case_no": r["quote_no"] or "", "party": {"key": "", "name": ""}, "tax_code": "", "mode": "snapshot",
                "lines": _accrual_lines(r, total, memo),
                "meta": {"category": r["category"] or "其他", "tax_unsplit": True, "date_estimated": not inv}})
        paid = (r["paid_date"] or "")[:10]
        if paid and start <= paid <= end:
            actual = _i(r["remit_actual"]) if r["remit_actual"] is not None else total
            fee = _i(r["remit_fee"])
            if actual != total and (r["remit_review"] or "") != "approved":
                pending += 1
                continue
            lines = [{"role": "AP", "side": "D", "amount": total, "memo": memo}]
            if fee:
                lines.append({"role": "FEE", "side": "D", "amount": fee, "memo": "匯款手續費（公司自付）"})
            if actual > total:
                lines.append({"role": "EXP_OTHER", "side": "D", "amount": actual - total, "memo": "付款多付（已核可）"})
            elif actual < total:
                lines.append({"role": "EXP_OTHER", "side": "C", "amount": total - actual, "memo": "付款少付（已核可）"})
            # 付款方式（A2-3）：零用金貸 PETTY，其餘貸 BANK；出納另選了付款科目 ⇒ 帶 `account_code`（W4 的引擎優先採用）。舊版列＝BANK
            _leg = {"role": "PETTY" if (r["pay_method"] or "") == "petty_cash" else "BANK", "side": "C", "amount": actual + fee, "memo": memo}
            if (r["pay_account_code"] or "").strip():
                _leg["account_code"] = r["pay_account_code"].strip()
            lines.append(_leg)
            events.append({
                "source_type": "case_extra_expense_payment", "source_key": str(r["id"]), "event_code": "E11b", "event_date": paid, "doc_no": doc,
                "case_no": r["quote_no"] or "", "party": {"key": "", "name": ""}, "tax_code": "", "mode": "snapshot", "lines": lines, "meta": {}})

    for m in mat_accrual:
        amt = _i(m["amount"])
        d = (m["date"] or "")[:10]
        if amt <= 0:
            continue
        if not d:
            nodate += 1
            continue
        if start <= d <= end:
            unsplit += 1
            events.append({
                "source_type": "case_material_order", "source_key": "%s::%s" % (m["quoteNo"], m["itemId"] or m["desc"]), "event_code": "E12",
                "event_date": d, "doc_no": "", "case_no": m["quoteNo"], "party": {"key": "", "name": ""}, "tax_code": "", "mode": "snapshot",
                "lines": [{"role": "COST_PROJECT", "side": "D", "amount": amt, "memo": m["desc"][:40]}, {"role": "AP", "side": "C", "amount": amt, "memo": m["desc"][:40]}],
                "meta": {"tax_unsplit": True, "date_estimated": bool(m.get("provisional")), "weak_key": not m["itemId"]}})
    for m in mat_cash:
        amt = _i(m["amount"])
        d = (m["date"] or "")[:10]
        if amt > 0 and d and start <= d <= end:
            events.append({
                "source_type": "case_material_payment", "source_key": "%s::%s" % (m["quoteNo"], m["itemId"] or m["desc"]), "event_code": "E12b",
                "event_date": d, "doc_no": "", "case_no": m["quoteNo"], "party": {"key": "", "name": ""}, "tax_code": "", "mode": "snapshot",
                "lines": [{"role": "AP", "side": "D", "amount": amt, "memo": m["desc"][:40]}, {"role": "BANK", "side": "C", "amount": amt, "memo": m["desc"][:40]}],
                "meta": {"weak_key": not m["itemId"]}})

    if unsplit:
        notices.append("%d 筆額外支出／叫料的來源金額是未拆稅（含稅）：以全額列專案成本；有進項稅額請在來源憑證補登（input_tax）。" % unsplit)
    if typed_unsplit:
        notices.append("%d 筆費用單據的來源金額是未拆稅（含稅）：以全額列費用（依費用類別對應的科目；未設定對應者列預設費用科目並標註）；有進項稅額請在來源憑證補登（input_tax）。" % typed_unsplit)
    if pending:
        notices.append("%d 筆額外支出付款的實付與應付有差額且尚未核可：暫不產生付款分錄，核可後再執行。" % pending)
    if nodate:
        notices.append("%d 筆叫料沒有發票日也沒有付款日：不產生分錄（請補日期）。" % nodate)
    return {"events": events, "notice": " ".join(notices)}
