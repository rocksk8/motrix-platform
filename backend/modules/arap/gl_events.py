# -*- coding: utf-8 -*-
"""M05 → M06 總帳事件提供者（`gl.events`，IP-GL1，契約 v1）：銷項發票（E01／E01b）與客戶收款（E03）。設計：proposal-gl/02-events-engine.md §4。

- E01 開立發票（使用者裁示：依開立發票日認列）：借 應收帳款（含稅）／貸 銷貨收入（未稅）＋銷項稅額。金額以收款登錄時填的發票未稅／稅額為準，
  沒填才依報價單稅別拆（同 `collect_tax_invoices`）。先收款後開票 ⇒ 同一事件再加一對「借 預收貨款／貸 應收帳款」沖轉。
- E03 客戶收款（W2 語意，`helpers.tax_calc.receipt_amounts`）：借 銀行＝實收（銀行入帳，已扣客戶內扣手續費）＋借 手續費／貸 應收帳款＝實收＋手續費（含稅收入）；
  收款日早於發票日（或尚未開票）⇒ 貸 預收貨款。
- 事件鍵用款項期別的不可變 `id`（quotations.data_json 裡按陣列索引存取，索引會變）；沒有 id 的舊資料退回索引並標 `weak_key`。
- 不猜：實收與發票含稅不一致、缺開立日期都在 notice 明說，帳上 AR 餘額如實保留（由會計處理），不自行沖差額。
只讀，不寫資料。
"""
import json

from db import get_db
from helpers.legal_params import round_half_up
from modules.arap.receivables import collect_income_items, collect_tax_invoices

#: 與營運報表、E03（`collect_income_items`）同一口徑：案件狀態要是「已成案／已結案」才入帳（L8，W2 寫入串接矩陣）
_DEAL_OK = ("已成案", "已結案")


def _deal_ok_quotes(quote_nos):
    """⇒ 案件狀態（deal_tag，欄位優先、退回 data_json.dealTag）是已成案／已結案的報價單號集合。
    data_json 在 Python 裡逐列解析（不用 SQL json_extract：一列壞 JSON 會讓整個查詢失敗）。"""
    nos = sorted({q for q in quote_nos if q})
    if not nos:
        return set()
    conn = get_db()
    try:
        out = set()
        for i in range(0, len(nos), 500):
            chunk = nos[i:i + 500]
            for r in conn.execute("SELECT quote_no, deal_tag, data_json FROM quotations WHERE quote_no IN (%s)" % ",".join("?" * len(chunk)), chunk):
                tag = (r["deal_tag"] or "").strip()
                if not tag:
                    try:
                        tag = str((json.loads(r["data_json"] or "{}") or {}).get("dealTag") or "")
                    except (TypeError, ValueError, AttributeError):
                        tag = ""
                if tag in _DEAL_OK:
                    out.add(r["quote_no"])
        return out
    finally:
        conn.close()


_TAX_CODE = {"taxable": "OUT-5", "zero": "OUT-0", "exempt": "OUT-EX", "legacy": "OUT-LEGACY"}


def _i(x):
    return int(round_half_up(x or 0))


def _item_key(itemId, idx):
    return (itemId or "idx%d" % idx), (not itemId)


def gl_events(start, end, *, changed_since=""):
    invoices = collect_tax_invoices()
    receipts = collect_income_items("0001-01-01", "9999-12-31")
    inv_by_no = {(r["quoteNo"], r["invoiceNo"]): r for r in invoices}
    rec_by_item = {}
    for r in receipts:
        rec_by_item[(r["quoteNo"], _item_key(r.get("itemId"), r.get("itemIdx", 0))[0])] = r
    events, notices = [], []
    no_date = weak = diff = not_deal = 0
    deal_ok = _deal_ok_quotes({i["quoteNo"] for i in invoices})

    for inv in invoices:
        d = inv["invoiceDate"]
        if not d or not (start <= d <= end):
            continue
        if inv["quoteNo"] not in deal_ok:               # L8：案件降級後（不再是成案／結案）與 E03、報表同口徑 ⇒ 不入帳；已過帳的引擎判來源消失、產生反向草稿
            not_deal += 1
            continue
        pretax, tax = _i(inv["amountPretax"]), _i(inv["taxAmount"])
        total = pretax + tax
        if total <= 0:
            continue
        ikey, is_weak = _item_key(inv.get("itemId"), inv.get("itemIdx", 0))
        rec = rec_by_item.get((inv["quoteNo"], ikey))
        from_receipt = bool(inv["date"]) and inv["invoiceDate"] == inv["date"] and not rec_invoice_date_recorded(inv)
        code = _TAX_CODE.get(inv["taxType"], "OUT-5")
        memo = "%s 發票 %s" % (inv.get("customer") or "", inv["invoiceNo"])
        lines = [{"role": "AR", "side": "D", "amount": total, "memo": memo},
                 {"role": "REV_SALES", "side": "C", "amount": pretax, "memo": memo, "tax_code": code}]
        if tax:
            lines.append({"role": "OUTPUT_TAX", "side": "C", "amount": tax, "memo": memo, "tax_code": code})
        if rec and rec["receivedAt"] and rec["receivedAt"] < d:                       # 先收款後開票：預收貨款轉應收帳款
            reclass = min(total, _i(rec["amount"]))
            if reclass > 0:
                lines += [{"role": "ADV_RCPT", "side": "D", "amount": reclass, "memo": "預收轉銷 " + inv["invoiceNo"]},
                          {"role": "AR", "side": "C", "amount": reclass, "memo": "預收轉銷 " + inv["invoiceNo"]}]
        weak += 1 if is_weak else 0
        events.append({
            "source_type": "quotation_invoice", "source_key": "%s::%s" % (inv["quoteNo"], inv["invoiceNo"]), "event_code": "E01",
            "event_date": d, "doc_no": inv["invoiceNo"], "case_no": inv["quoteNo"],
            "party": {"key": inv.get("taxId") or inv.get("customer") or "", "name": inv.get("customer") or ""},
            "tax_code": code, "mode": "snapshot", "lines": lines,
            "meta": {"weak_key": is_weak, "date_from_receipt": from_receipt, "tax_note": inv.get("taxNote") or ""}})
        if from_receipt:
            no_date += 1

    for r in receipts:
        rat = r["receivedAt"]
        if not rat or not (start <= rat <= end):
            continue
        bank, fee, gross = _i(r["netAmount"]), _i(r["feeAmount"]), _i(r["amount"])
        if gross <= 0:
            continue
        ikey, is_weak = _item_key(r.get("itemId"), r.get("itemIdx", 0))
        inv = inv_by_no.get((r["quoteNo"], r.get("invoiceNo") or ""))
        invoiced = bool(inv) and inv["invoiceDate"] and inv["invoiceDate"] <= rat
        credit = "AR" if invoiced else "ADV_RCPT"
        memo = "%s 收款 %s" % (r.get("customer") or "", r.get("type") or "")
        bank_line = {"role": "BANK", "side": "D", "amount": bank, "memo": memo}
        if r.get("bankAccountCode"):
            bank_line["account_code"] = r["bankAccountCode"]
        lines = [bank_line]
        if fee:
            lines.append({"role": "FEE", "side": "D", "amount": fee, "memo": "客戶內扣手續費"})
        lines.append({"role": credit, "side": "C", "amount": gross, "memo": memo})
        if invoiced and abs(_i(inv["amountPretax"]) + _i(inv["taxAmount"]) - gross) > 0:
            diff += 1
        weak += 1 if is_weak else 0
        events.append({
            "source_type": "quotation_receipt", "source_key": "%s::%s" % (r["quoteNo"], ikey), "event_code": "E03",
            "event_date": rat, "doc_no": r.get("invoiceNo") or ikey, "case_no": r["quoteNo"],
            "party": {"key": (inv or {}).get("taxId") or r.get("customer") or "", "name": r.get("customer") or ""},
            "tax_code": "", "mode": "snapshot", "lines": lines, "meta": {"weak_key": is_weak, "advance": not invoiced}})

    if not_deal:
        notices.append("%d 張發票所屬案件目前不是「已成案／已結案」（例如已降級）：暫不入帳（與收款、營運報表同口徑）；若之前已過帳，引擎會產生反向草稿。" % not_deal)
    if no_date:
        notices.append("%d 張發票沒有填開立日期，暫以收款日認列（請補開立日期後，引擎會產生更正組）。" % no_date)
    if diff:
        notices.append("%d 筆收款的含稅收入與發票含稅金額不一致：應收帳款餘額如實保留，請會計處理（折讓、短收、稅額沖銷）。" % diff)
    if weak:
        notices.append("%d 筆款項期別沒有不可變的 id（舊資料），暫用陣列索引當事件鍵；款項順序若被調整，引擎會偵測為來源變動。" % weak)
    return {"events": events, "notice": " ".join(notices)}


def rec_invoice_date_recorded(inv):
    """發票列的 invoiceDate 是否為使用者填的（collect_tax_invoices 缺值時退回收款日，兩者相等）——由 itemHasInvoiceDate 標示。"""
    return bool(inv.get("hasInvoiceDate"))
