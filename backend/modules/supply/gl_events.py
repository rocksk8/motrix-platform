# -*- coding: utf-8 -*-
"""M03 → M06 總帳事件提供者（`gl.events`，IP-GL1，契約 v1）：進貨批次 E08（入庫）、E08b（進貨發票進項稅額）、E09（進貨付款）。
設計：proposal-gl/02-events-engine.md §4、07-inventory-cost.md §3。存貨出庫成本（E10，移動加權平均）在後續批次，本檔不含。

- E08 進貨入庫（批次建立日）：借 存貨／貸 應付帳款，金額＝該批次 `stock_items.cost` 合計（未稅，設計假設 A2）。批次沒有發票資料也照樣認列存貨與應付。
- E08b 進貨發票進項稅額：批次登錄了發票號碼才產生；來源沒有發票日期與稅額欄位（R3 為可選），暫用**批次建立日**與**成本×5%（估計）**，
  `meta.tax_estimated=true`、notice 提醒；會計可在 `gl_source_annotations` 補登實際值（`input_tax`、`invoice_date`，鍵＝批次號、來源類型 `stock_batch_invoice`），引擎收集時覆寫。
- E09 進貨付款（付款日）：借 應付帳款（貨款＋進項稅額）／貸 銀行（有付款帳戶代號則帶 `account_code`）。稅額與 E08b 一致（同一個估計／補登值由引擎在
  `contract.apply_annotations` 對 E08b 覆寫，E09 讀 E08b 的同一筆補登、調整應付與銀行金額，`meta.est_tax` 記估計值）。
只讀，不寫資料。
- E10 出庫成本（出貨單核准 shipped、案件序號認領 installed）：來源只回『料號、件數、案件、日期』（mode=stock，不帶金額）；
  金額由引擎依移動加權平均（`ledger/inventory.py`）算出並組成 借營業成本（依案件）／貸存貨。退回入庫（狀態回 in_stock）⇒ 事件消失 ⇒ 引擎以原金額回沖。
  報廢（void，終態）＝出庫的一種：同樣依移動加權平均算金額，但借 存貨盤損（`INV_LOSS`）不借營業成本（來源鍵＝料號＋報廢日，`meta.via='scrap'`，L10）。
  ⚠️ 報廢日取 `stock_items.updated_at`（來源沒有獨立的報廢時間欄）；報廢後不會再被改備註動到日期（inventory.py 對 void 件不更新時間）。
"""
from db import get_db
from helpers.legal_params import round_half_up

_RATE = 0.05


def _i(x):
    return int(round_half_up(x or 0))


def _tax_for(cost, invoice_no):
    """估計稅額：有發票號碼才有進項稅額。"""
    return _i(cost * _RATE) if (invoice_no or "").strip() else 0


def gl_events(start, end, *, changed_since=""):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT sb.batch_no, sb.part_no, sb.supplier_id, sb.supplier_name, sb.invoice_no, sb.is_paid, sb.paid_at, sb.created_at, "
            "COALESCE(sb.paid_bank_account_code,'') AS bank, COALESCE(SUM(si.cost),0) AS total, COUNT(si.id) AS qty "
            "FROM stock_batches sb LEFT JOIN stock_items si ON si.batch_no=sb.batch_no GROUP BY sb.batch_no ORDER BY sb.created_at, sb.batch_no"
        ).fetchall()
    finally:
        conn.close()
    events, notices = [], []
    zero = est = 0
    out_events = _stock_out(start, end)
    events += out_events
    for r in rows:
        cost = _i(r["total"])
        if cost <= 0:
            zero += 1
            continue
        party = {"key": ("S%s" % r["supplier_id"]) if r["supplier_id"] else (r["supplier_name"] or ""), "name": r["supplier_name"] or ""}
        memo = "進貨 %s %s（%d 台）" % (r["batch_no"], r["part_no"], r["qty"])
        d = (r["created_at"] or "")[:10]
        tax = _tax_for(cost, r["invoice_no"])
        if d and start <= d <= end:
            inv_line = {"role": "INVENTORY", "side": "D", "amount": cost, "memo": memo}
            if tax:
                inv_line["tax_code"] = "IN-5"                     # 有發票的進貨：讓 401 的進項金額欄取得到這筆金額
            events.append({
                "source_type": "stock_batch", "source_key": r["batch_no"], "event_code": "E08", "event_date": d, "doc_no": r["batch_no"],
                "case_no": "", "party": party, "tax_code": "", "mode": "snapshot",
                "lines": [inv_line, {"role": "AP", "side": "C", "amount": cost, "memo": memo}],
                "meta": {"part_no": r["part_no"], "qty": r["qty"]}})
        if tax and d and start <= d <= end:
            est += 1
            events.append({
                "source_type": "stock_batch_invoice", "source_key": r["batch_no"], "event_code": "E08b", "event_date": d,
                "doc_no": r["invoice_no"], "case_no": "", "party": party, "tax_code": "IN-5", "mode": "snapshot",
                "lines": [{"role": "INPUT_TAX", "side": "D", "amount": tax, "memo": memo, "tax_code": "IN-5"},
                          {"role": "AP", "side": "C", "amount": tax, "memo": memo}],
                "meta": {"tax_estimated": True, "date_estimated": True}})
        pd = (r["paid_at"] or "")[:10]
        if r["is_paid"] and pd and start <= pd <= end:
            pay = cost + tax
            bank = {"role": "BANK", "side": "C", "amount": pay, "memo": memo}
            if r["bank"]:
                bank["account_code"] = r["bank"]
            events.append({
                "source_type": "stock_batch_payment", "source_key": r["batch_no"], "event_code": "E09", "event_date": pd, "doc_no": r["batch_no"],
                "case_no": "", "party": party, "tax_code": "", "mode": "snapshot",
                "lines": [{"role": "AP", "side": "D", "amount": pay, "memo": memo}, bank], "meta": {"tax_estimated": bool(tax), "est_tax": tax}})
    if zero:
        notices.append("%d 個進貨批次的成本合計為 0：不產生分錄（請補成本）。" % zero)
    if est:
        notices.append("%d 個進貨批次的進項稅額與發票日期為估計（成本×5%%、批次建立日）；實際值請在來源憑證補登（input_tax、invoice_date）。" % est)
    return {"events": events, "notice": " ".join(notices)}


def _stock_out(start, end):
    """出庫事件（mode=stock）：出貨單核准、案件序號認領、報廢（L10）。"""
    conn = get_db()
    try:
        shipped = conn.execute(
            "SELECT shipping_note_no, part_no, quote_no, MIN(consumed_at) AS at, COUNT(*) AS qty FROM stock_items "
            "WHERE status='shipped' AND shipping_note_no<>'' AND consumed_at<>'' GROUP BY shipping_note_no, part_no").fetchall()
        claimed = conn.execute(
            "SELECT quote_no, part_no, substr(consumed_at,1,10) AS d, COUNT(*) AS qty FROM stock_items "
            "WHERE status='installed' AND consumed_at<>'' GROUP BY quote_no, part_no, substr(consumed_at,1,10)").fetchall()
        scrapped = conn.execute(
            "SELECT part_no, substr(updated_at,1,10) AS d, COUNT(*) AS qty FROM stock_items WHERE status='void' AND updated_at<>'' GROUP BY part_no, substr(updated_at,1,10)").fetchall()
    finally:
        conn.close()
    out = []
    for r in shipped:
        d = (r["at"] or "")[:10]
        if d and start <= d <= end:
            out.append({"source_type": "stock_issue_shipping", "source_key": "%s::%s" % (r["shipping_note_no"], r["part_no"]), "event_code": "E10",
                        "event_date": d, "doc_no": r["shipping_note_no"], "case_no": r["quote_no"] or "", "party": {"key": "", "name": ""},
                        "tax_code": "", "mode": "stock", "stock_part_no": r["part_no"], "stock_qty": int(r["qty"]), "meta": {"via": "shipping_note"}})
    for r in claimed:
        d = r["d"] or ""
        if d and start <= d <= end:
            out.append({"source_type": "stock_issue_claim", "source_key": "%s::%s::%s" % (r["quote_no"], r["part_no"], d), "event_code": "E10",
                        "event_date": d, "doc_no": r["quote_no"] or "", "case_no": r["quote_no"] or "", "party": {"key": "", "name": ""},
                        "tax_code": "", "mode": "stock", "stock_part_no": r["part_no"], "stock_qty": int(r["qty"]), "meta": {"via": "claim"}})
    for r in scrapped:                                                  # L10：報廢（void，終態）⇒ 依移動加權平均把存貨減下來，借存貨盤損（INV_LOSS）
        d = r["d"] or ""
        if d and start <= d <= end:
            out.append({"source_type": "stock_scrap", "source_key": "%s::%s" % (r["part_no"], d), "event_code": "E10", "event_date": d,
                        "doc_no": r["part_no"], "case_no": "", "party": {"key": "", "name": ""}, "tax_code": "", "mode": "stock",
                        "stock_part_no": r["part_no"], "stock_qty": int(r["qty"]), "meta": {"via": "scrap"}})
    return out
