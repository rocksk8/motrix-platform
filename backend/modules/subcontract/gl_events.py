# -*- coding: utf-8 -*-
"""M04 → M06 總帳事件提供者（`gl.events`，IP-GL1，契約 v1）：承攬商發票（E04）與匯款（E05／E05b）。設計：proposal-gl/02-events-engine.md §4。

- E04 承攬商發票（依發票日認列）：借 專案成本（派工未稅金額）＋進項稅額／貸 應付帳款（含稅）。稅額＝派工 `tax_rate`×未稅（估計，`meta.tax_estimated=true`），
  會計可用 `gl_source_annotations`（field=input_tax）補登實際發票稅額，引擎收集時覆寫（來源模組不必加欄位）。只收已驗收／完工、且有發票日的派工。
- E05 匯款（依匯款日）：借 應付帳款＝匯款單快照 grandTotal（含個人點工）＋手續費（公司自付）／貸 銀行＝實付＋手續費；實付≠應付且**已核可**⇒差額入其他費用；
  差額**待審核**⇒不產生事件、notice 明說（不猜）。
- E05b 個人點工（歷史未關聯勞報單）：匯款單快照 personnelTotal 與 E05 同日認列「借 專案成本／貸 應付帳款」，`meta.no_withholding=true`，notice 提醒未扣繳。
  （使用者裁示 2026-09-30：新資料個人點工一律走勞報單 E06；此列只讓歷史匯款的應付帳款帳平。）
只讀，不寫資料。
⚠ 提示（notice）字串是 `%` 格式字串：字面的百分比要寫 `%%`。寫壞會丟 TypeError ⇒ 整個提供者失敗、所有承攬商事件消失（引擎只在 notices 記『讀取失敗』）——`test_ledger_acceptance` 斷言每個事件來源都讀取成功。
"""
import json

from db import get_db
from helpers.legal_params import round_half_up


def _i(x):
    return int(round_half_up(x or 0))


def _snap(row):
    try:
        return json.loads(row["snapshot_json"] or "{}") or {}
    except (TypeError, ValueError):
        return {}


def gl_events(start, end, *, changed_since=""):
    conn = get_db()
    try:
        disp = conn.execute(
            "SELECT d.*, v.name AS vendor_name, v.tax_id AS vendor_tax_id FROM contractor_dispatches d "
            "LEFT JOIN vendor_contractors v ON v.id=d.vendor_id "
            "WHERE d.status IN ('accepted','completed') AND d.invoice_date IS NOT NULL AND d.invoice_date<>'' "
            "AND d.invoice_date BETWEEN ? AND ? ORDER BY d.id", (start, end)).fetchall()
        vouchers = conn.execute(
            "SELECT * FROM contractor_payment_vouchers WHERE is_paid=1 AND substr(paid_at,1,10) BETWEEN ? AND ? ORDER BY voucher_no",
            (start, end)).fetchall()
        invoiced = {r["dispatch_id"] for r in conn.execute(
            "SELECT p.dispatch_id FROM contractor_payment_vouchers p JOIN contractor_dispatches d ON d.id=p.dispatch_id "
            "WHERE d.invoice_date IS NOT NULL AND d.invoice_date<>''").fetchall()}
    finally:
        conn.close()
    events, notices = [], []
    estimated = pending = no_withhold = uninvoiced = 0

    for d in disp:
        pretax = _i(d["total_amount"])
        if pretax <= 0:
            continue
        rate = d["tax_rate"] if d["tax_rate"] is not None else 0.05
        tax = _i(pretax * rate)
        estimated += 1
        code = "IN-5" if tax else "IN-EX"
        memo = "%s 發票 %s" % (d["vendor_name"] or "", d["invoice_no"] or "")
        lines = [{"role": "COST_PROJECT", "side": "D", "amount": pretax, "memo": memo}]
        if tax:
            lines.append({"role": "INPUT_TAX", "side": "D", "amount": tax, "memo": memo, "tax_code": code})
        lines.append({"role": "AP", "side": "C", "amount": pretax + tax, "memo": memo})
        events.append({
            "source_type": "contractor_dispatch", "source_key": str(d["id"]), "event_code": "E04",
            "event_date": d["invoice_date"][:10], "doc_no": d["invoice_no"] or "", "case_no": d["quote_no"],
            "party": {"key": d["vendor_tax_id"] or d["vendor_name"] or "", "name": d["vendor_name"] or ""},
            "tax_code": code, "mode": "snapshot", "lines": lines,
            "meta": {"tax_estimated": True, "tax_rate": rate}})

    for v in vouchers:
        s = _snap(v)
        payable = _i(s.get("grandTotal"))
        if payable <= 0:
            continue
        actual = _i(v["remit_actual"]) if v["remit_actual"] is not None else payable
        fee = _i(v["remit_fee"])
        if actual != payable and (v["remit_review"] or "") != "approved":
            pending += 1
            continue
        pd = (v["paid_at"] or "")[:10]
        party = {"key": s.get("vendorTaxId") or s.get("vendorName") or "", "name": s.get("vendorName") or ""}
        memo = "%s 匯款 %s" % (s.get("vendorName") or "", v["voucher_no"])
        bank = {"role": "BANK", "side": "C", "amount": actual + fee, "memo": memo}
        if v["paid_bank_account_code"]:
            bank["account_code"] = v["paid_bank_account_code"]
        people = [q for q in (s.get("personnel") or []) if str((q or {}).get("name") or "").strip()]
        linked = sum(_i(q.get("amount")) for q in people if str(q.get("payslipNo") or "").strip())      # 已關聯勞報單的個人：付的是勞報單的應付
        lines = [{"role": "AP", "side": "D", "amount": payable - linked, "memo": memo}] if payable - linked > 0 else []
        if linked:
            lines.append({"role": "OTHER_PAYABLE", "side": "D", "amount": linked, "memo": "個人外包（勞報單）"})
        if fee:
            lines.append({"role": "FEE", "side": "D", "amount": fee, "memo": "匯款手續費（公司自付）"})
        if actual > payable:
            lines.append({"role": "EXP_OTHER", "side": "D", "amount": actual - payable, "memo": "匯款多付（已核可）"})
        elif actual < payable:
            lines.append({"role": "EXP_OTHER", "side": "C", "amount": payable - actual, "memo": "匯款少付（已核可）"})
        lines.append(bank)
        events.append({
            "source_type": "contractor_voucher", "source_key": v["voucher_no"], "event_code": "E05",
            "event_date": pd, "doc_no": v["voucher_no"], "case_no": v["quote_no"], "party": party,
            "tax_code": "", "mode": "snapshot", "lines": lines,
            "meta": {"dispatch_invoiced": v["dispatch_id"] in invoiced}})
        if v["dispatch_id"] not in invoiced:
            uninvoiced += 1
        person = _i(s.get("personnelTotal")) - linked
        if person > 0:
            no_withhold += 1
            pm = "%s 個人點工（未關聯勞報單）" % v["voucher_no"]
            events.append({
                "source_type": "contractor_voucher_personnel", "source_key": v["voucher_no"], "event_code": "E05b",
                "event_date": pd, "doc_no": v["voucher_no"], "case_no": v["quote_no"], "party": party,
                "tax_code": "", "mode": "snapshot",
                "lines": [{"role": "COST_PROJECT", "side": "D", "amount": person, "memo": pm},
                          {"role": "AP", "side": "C", "amount": person, "memo": pm}],
                "meta": {"no_withholding": True}})

    if pending:
        notices.append("%d 張匯款單實付與應付有差額且尚未核可：暫不產生分錄，核可後再執行。" % pending)
    if uninvoiced:
        notices.append("%d 張匯款單對應的派工沒有登錄發票日：付款已入帳，但應付帳款借方沒有對應的發票認列，請補發票日。" % uninvoiced)
    if no_withhold:
        notices.append("%d 張匯款單含個人點工（未關聯勞報單）：以專案成本／應付帳款認列，未扣繳所得稅與二代健保，請改開勞報單。" % no_withhold)
    if estimated:
        notices.append("%d 筆承攬商發票的進項稅額是估計稅額：依派工稅率估算（派工沒填稅率時以 5%% 估算）；實際發票稅額不同時，請在來源憑證補登（input_tax）。" % estimated)
    return {"events": events, "notice": " ".join(notices)}
