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
⚠️ 稅額：自訂模組欄位沒有稅額拆分（開放事項 A6），金額一律視為**未稅、不拆稅**，notice 提醒；需要稅額請在 `gl_custom_field_map.tax_code` 指定稅碼或改用手工傳票。
🔑 對象：自訂單據沒有統編／往來對象，事件對象只帶模組名稱。只讀，不寫資料。
"""
from db import get_db
from helpers.legal_params import round_half_up


def _i(x):
    return int(round_half_up(x or 0))


def gl_events(start, end, *, changed_since=""):
    from helpers import custom_finance as _cf
    conn = get_db()
    try:
        recs = _cf.gl_lines(conn)
        maps = {(r["module_key"], r["field_key"]): dict(r) for r in conn.execute("SELECT * FROM gl_custom_field_map WHERE is_active=1")}
    finally:
        conn.close()
    events, notices = [], []
    undated = dup = 0
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
                if income:
                    lines = [_line("AR", "D", amt, m.get("debit_account", "")), _line("REV_OTHER", "C", amt, m.get("credit_account", ""))]
                else:
                    lines = [_line("COST_PROJECT" if ln["case"] else "EXP_OTHER", "D", amt, m.get("debit_account", "")), _line("AP", "C", amt, m.get("credit_account", ""))]
                events.append({"source_type": "custom_record", "source_key": key, "event_code": "E20", "event_date": d, "doc_no": rec["recordNo"],
                               "case_no": ln["case"], "party": party, "tax_code": m.get("tax_code", ""), "mode": "snapshot", "lines": lines, "meta": meta})
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
    if events:
        notices.append("自訂模組單據的金額視為未稅、不拆稅（自訂欄位沒有稅額）；科目預設為應收／其他營業收入、其他費用／應付，要改用別的科目請洽系統維護人員設定欄位對應。")
    return {"events": events, "notice": " ".join(notices)}
