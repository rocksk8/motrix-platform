# -*- coding: utf-8 -*-
"""自訂模組單據入帳 → 總帳事件提供者（`gl.events`，source＝`custom_modules`，C7；設計 proposal-gl/02-events-engine.md「自訂模組與 outbox」）。

資料來源：`helpers.custom_finance.gl_lines(conn)`——入帳中（在該模組的入帳狀態、且未被「也入帳的新修訂」取代）單據的金流行。
「反轉」不需要另一個事件：單據離開入帳狀態（退回、作廢、被新修訂取代）⇒ 這裡不再回那筆事件 ⇒ 引擎判來源消失、
自動產生反向草稿（已過帳）或作廢草稿；outbox（`custom_record_finance_outbox`）只是喚醒訊號，本提供者不依賴它的處理狀態（漏收也補得回）。

事件（每個金流行至多兩個）：
- **E20 入帳（權責日＝該欄位的 dateField）**：收入 借 應收帳款（AR）／貸 其他營業收入（REV_OTHER）；支出 借 其他費用（EXP_OTHER，有關聯案件時 COST_PROJECT）／貸 應付帳款（AP）。
  會計在 `gl_custom_field_map`（模組＋欄位）指定 `debit_account`／`credit_account`／`tax_code` 時以指定的科目為準（其餘維持預設角色）。
- **E20b 收付款（現金日＝cashDateField，金額＝cashAmountField，沒設＝同權責金額）**：收入 借 銀行／貸 應收；支出 借 應付／貸 銀行。
略過並明說：
- 收入行關聯到**內建案件**（由內建報價單認列，E01 已記，與營運報表同一判準）；
- 沒有對應日期的行（不產生該口徑的事件，列入 notice 的『待補登』數，不可以靜默少列）；
- 金額為 0。
稅額（G3，2026-10-01；規則同費用單據，**待使用者確認**）：欄位屬性 `finance.taxField`（稅額欄位 key）與 `finance.docTypeField`（憑證種類欄位 key）為選填；
  金額欄位＝**含稅總額**。有 `taxField` 且值 >0 且 < 總額：憑證種類是統一發票（`docTypeField` 的值是 invoice／統一發票／發票／電子發票；**沒設 `docTypeField` 視為統一發票**）⇒
  支出 借 成本（總額−稅額）＋借 進項稅額 INPUT_TAX（稅碼 IN-5）／貸 應付；收入 借 應收（總額）／貸 收入（總額−稅額）＋貸 銷項稅額 OUTPUT_TAX（稅碼 OUT-5）。
  收據、國外憑證等非統一發票 ⇒ 稅額併入成本／收入、不拆稅；**沒有稅額欄位 ⇒ 含稅全額入帳（與 G3 之前完全相同）**。稅額欄位填了不合理的值（非數字、≥ 總額）⇒ 不拆、notice 提醒。
  `gl_custom_field_map.debit_account／credit_account` 只指定成本／收入那一行；`tax_code` 有指定時覆蓋預設稅碼。
🔑 對象：自訂單據沒有統編／往來對象，事件對象只帶模組名稱。只讀，不寫資料。
"""
from db import get_db
from helpers.legal_params import round_half_up


def _i(x):
    return int(round_half_up(x or 0))


_INVOICE_TYPES = {"invoice", "統一發票", "發票", "電子發票"}


def _split_tax(ln, data, amt):
    """回 `(tax, note)`：tax＝要拆出的稅額（整數元，0＝不拆）；note＝不拆的原因（空字串＝沒有需要說明的）。
    規則見模組說明；只讀 `ln["finance"]`（L1 helper 原樣帶出的屬性字典）與單據資料。"""
    fin = ln.get("finance") or {}
    tf = fin.get("taxField")
    if not tf:
        return 0, ""
    raw = data.get(tf)
    if raw in (None, ""):
        return 0, ""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return 0, "稅額欄位不是數字"
    tax = _i(raw)
    if tax <= 0:
        return 0, ""
    if tax >= amt:
        return 0, "稅額不小於含稅總額"
    dtf = fin.get("docTypeField")
    if dtf and str(data.get(dtf) or "").strip().lower() not in {x.lower() for x in _INVOICE_TYPES}:
        return 0, "非統一發票：稅額併入"
    return tax, ""


def gl_events(start, end, *, changed_since=""):
    from helpers import custom_finance as _cf
    conn = get_db()
    try:
        recs = _cf.gl_lines(conn)
        maps = {(r["module_key"], r["field_key"]): dict(r) for r in conn.execute("SELECT * FROM gl_custom_field_map WHERE is_active=1")}
    finally:
        conn.close()
    events, notices = [], []
    undated = dup = split = 0
    bad_tax = []
    for rec in recs:
        for ln in rec["lines"]:
            if ln["skipped"]:
                dup += 1
                continue
            amt = _i(ln["amount"])
            if amt <= 0:
                continue
            m = maps.get((rec["module"], ln["field"])) or {}
            income = ln["kind"] == "income"
            memo = "%s %s（%s）" % (rec["moduleName"] or rec["module"], rec["recordNo"], ln["label"])
            key = "%s::%s::%s" % (rec["module"], rec["recordNo"], ln["field"])
            party = {"key": "", "name": rec["moduleName"] or rec["module"]}
            meta = {"module": rec["module"], "field": ln["field"], "kind": ln["kind"], "record_id": rec["recordId"]}

            def _line(role, side, amount, account=""):
                d = {"role": role, "side": side, "amount": amount, "memo": memo}
                if account:
                    d["account_code"] = account
                if ln["case"]:
                    d["case_no"] = ln["case"]
                return d
            d = ln["date"]
            if not d:
                undated += 1
            elif start <= d <= end:
                tax, why = _split_tax(ln, rec.get("data") or {}, amt)
                if why:
                    bad_tax.append(why)
                if income:
                    if tax:
                        lines = [_line("AR", "D", amt, m.get("debit_account", "")), _line("REV_OTHER", "C", amt - tax, m.get("credit_account", "")),
                                 _line("OUTPUT_TAX", "C", tax)]
                    else:
                        lines = [_line("AR", "D", amt, m.get("debit_account", "")), _line("REV_OTHER", "C", amt, m.get("credit_account", ""))]
                else:
                    cost_role = "COST_PROJECT" if ln["case"] else "EXP_OTHER"
                    if tax:
                        lines = [_line(cost_role, "D", amt - tax, m.get("debit_account", "")), _line("INPUT_TAX", "D", tax), _line("AP", "C", amt, m.get("credit_account", ""))]
                    else:
                        lines = [_line(cost_role, "D", amt, m.get("debit_account", "")), _line("AP", "C", amt, m.get("credit_account", ""))]
                if tax:
                    split += 1
                    meta = dict(meta, tax_split=tax)
                ev_tax = m.get("tax_code", "") or (("OUT-5" if income else "IN-5") if tax else "")
                events.append({"source_type": "custom_record", "source_key": key, "event_code": "E20", "event_date": d, "doc_no": rec["recordNo"],
                               "case_no": ln["case"], "party": party, "tax_code": ev_tax, "mode": "snapshot", "lines": lines, "meta": meta})
            cd = ln["cashDate"]
            if cd and start <= cd <= end:
                camt = _i(ln["cashAmount"])
                if camt > 0:
                    lines = ([_line("BANK", "D", camt), _line("AR", "C", camt)] if income else [_line("AP", "D", camt), _line("BANK", "C", camt)])
                    events.append({"source_type": "custom_record_cash", "source_key": key, "event_code": "E20b", "event_date": cd, "doc_no": rec["recordNo"],
                                   "case_no": ln["case"], "party": party, "tax_code": "", "mode": "snapshot", "lines": lines, "meta": meta})
    if undated:
        notices.append("%d 筆自訂模組金流行沒有權責日期：不產生入帳事件（請在單據補日期）。" % undated)
    if dup:
        notices.append("%d 筆自訂模組收入關聯到內建案件：由內建報價單認列，不重複入帳。" % dup)
    if bad_tax:
        notices.append("%d 筆自訂模組金流行的稅額欄位未拆稅（%s）：含稅全額入帳。" % (len(bad_tax), "、".join(sorted(set(bad_tax)))))
    if events:
        notices.append("自訂模組單據的金額視為含稅總額；有設稅額欄位且為統一發票者拆進項／銷項稅額（%d 筆已拆），其餘含稅全額入帳；科目預設為應收／其他營業收入、其他費用／應付，"
                       "要改用別的科目請洽系統維護人員設定欄位對應。" % split)
    return {"events": events, "notice": " ".join(notices)}
