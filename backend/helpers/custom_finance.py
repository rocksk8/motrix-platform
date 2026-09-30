# -*- coding: utf-8 -*-
"""自訂模組的金流（收入／支出）串接（建構器第三輪 S2.5；使用者 2026-09-30：「只要有收入、支出項，都需要跟營運報表或是相關模組數據串接」）。

[單位] plat:custom-finance    [層] L1    [穩定度] 契約（只增）
[公開介面] EVENT_POSTED, EVENT_REVERSED, case_finance, expense_entries, income_items, on_transition, post_states, undated_counts
[不變式]
  - 金額欄位＝欄位屬性 `finance:{kind: income|expense, dateField, cashDateField, caseField, cashAmountField}`；
    入帳狀態＝模組 `finance.postStates`（沒指定 ⇒ 簽核核准後的終態）。**即時算**：單據在入帳狀態就計入、離開就不計，不建分錄表
  - 單據凍結在建立時的定義版本 ⇒ 金流欄位對映用**單據自己那一版**的定義
  - 修訂（-R）：舊版在「新版也入帳」之後不再計入（避免同一筆算兩次）；新版回到草稿期間舊版照舊計入
  - 權責日＝dateField；現金日＝cashDateField、現金金額＝cashAmountField（沒設 ⇒ 與權責同金額）。沒有對應日期的筆 ⇒ 不計入該口徑，
    列「待補登」計數（`undated_counts`），報表明說，不可以靜默少列
  - 收入：關聯案件（caseField）指到**內建案件**（quotations）⇒ 收入由內建報價單認列，這裡略過並計入 dupSkipped（不重複計入）；
    支出：不做這種判斷（內建額外支出／承攬派工與這裡是不同來源），歸屬到案件成本與部門而已
  - 進出 outbox 事件（`custom_record_finance_outbox`）：入帳狀態進入／離開時，與狀態變更同一個交易寫入，供 W4 總帳消費
[契約題] tests/test_builder3_finance_2026_09_30.py
"""
import json

from . import custom_builder_support as _S

EVENT_POSTED = _S.EVENT_FINANCE_POSTED
EVENT_REVERSED = _S.EVENT_FINANCE_REVERSED


def post_states(body) -> set:
    """入帳狀態：`finance.postStates`；沒指定 ⇒ 簽核核准後的終態（同發布驗證的推導）。"""
    from . import custom_modules as CM
    ps = (body.get("finance") or {}).get("postStates")
    return set(ps) if isinstance(ps, list) and ps else set(CM._derive_post_states(body))


def _finance_fields(body) -> list:
    return [f for f in body.get("fields", []) if isinstance(f, dict) and isinstance(f.get("finance"), dict)
            and f["finance"].get("kind") in ("income", "expense")]


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _lines(body, data) -> list:
    """一張單據的金流行：`[{kind, field, label, amount, date, cashDate, cashAmount, case}]`；金額空（None）的欄位不列。"""
    out = []
    for f in _finance_fields(body):
        fin = f["finance"]
        amt = _num(data.get(f["key"]))
        if amt is None:
            continue
        cash = _num(data.get(fin["cashAmountField"])) if fin.get("cashAmountField") else None
        out.append({"kind": fin["kind"], "field": f["key"], "label": f.get("label") or f["key"], "amount": amt,
                    "date": str(data.get(fin.get("dateField")) or "")[:10] if fin.get("dateField") else "",
                    "cashDate": str(data.get(fin.get("cashDateField")) or "")[:10] if fin.get("cashDateField") else "",
                    "cashAmount": cash if cash is not None else amt,
                    "case": str(data.get(fin["caseField"]) or "") if fin.get("caseField") else ""})
    return out


def on_transition(conn, body, rec, frm, to) -> None:
    """狀態改變時（`custom_modules._enter_state`，同一個交易內）：進入入帳狀態 ⇒ 寫 POSTED；離開 ⇒ 寫 REVERSED。
    沒有金流欄位、或入帳與否沒變 ⇒ 什麼都不做。同一張單反覆進出，每次事件的 dedupe_key 帶序號，不會被冪等吃掉。"""
    if not _finance_fields(body):
        return
    ps = post_states(body)
    was, now = frm in ps, to in ps
    if was == now:
        return
    event = EVENT_POSTED if now else EVENT_REVERSED
    seq = conn.execute("SELECT COUNT(*) FROM custom_record_finance_outbox WHERE module_key=? AND record_id=?",
                       (rec["module_key"], rec["id"])).fetchone()[0]
    lines = _lines(body, rec.get("data") or {})
    kinds = sorted({ln["kind"] for ln in lines}) or [""]
    _S.emit_finance_event(conn, event, rec["module_key"], rec["id"], rec["record_no"], "+".join(kinds),
                          {"module": rec["module_key"], "recordNo": rec["record_no"], "from": frm, "to": to, "lines": lines},
                          dedupe_key="%s:%s:%s:%d" % (event, rec["module_key"], rec["id"], seq))


def _posted(conn):
    """入帳中的單據 ⇒ 迭代 `(rec_row, body, lines)`：每張用自己那一版的定義判斷入帳狀態；已被「也入帳的新修訂」取代的舊版略過。"""
    from . import custom_modules as CM
    defs, post = {}, {}
    rows = conn.execute("SELECT * FROM custom_records ORDER BY id").fetchall()
    for r in rows:
        k = (r["module_key"], r["def_version"])
        if k not in defs:
            try:
                defs[k] = CM._load_def(conn, r["module_key"], r["def_version"])["body"]
            except CM.CustomModuleError:
                defs[k] = None
            post[k] = post_states(defs[k]) if defs[k] and _finance_fields(defs[k]) else set()
    posted_ids = {r["id"] for r in rows if r["status"] in post[(r["module_key"], r["def_version"])]}
    superseded = {r["supersedes_id"] for r in rows if r["supersedes_id"] and r["id"] in posted_ids}
    for r in rows:
        if r["id"] in posted_ids and r["id"] not in superseded:
            body = defs[(r["module_key"], r["def_version"])]
            try:
                data = json.loads(r["data_json"] or "{}")
            except (TypeError, ValueError):
                continue
            yield r, body, _lines(body, data)


def _case_dept(conn, case_no):
    r = conn.execute("SELECT u.department_id AS d FROM quotations q LEFT JOIN users u ON u.id=q.sales_person_id WHERE q.quote_no=?",
                     (case_no,)).fetchone()
    return r["d"] if r else None


def expense_entries(conn, start, end) -> list:
    """IP-9 `expense.entries` 提供者（名稱 `custom_module`）：`[{date, quoteNo, desc, amount, category, cashDate, cashAmount}]`。
    `date`＝權責日；`cashDate`／`cashAmount`＝現金口徑（**新增的選填鍵**，舊消費端不認得就忽略）。權責日或現金日任一落在
    [start, end] 就回（由消費端依口徑取用）；兩個日期都沒有 ⇒ 不回（計入 `undated_counts`）。"""
    out = []
    for r, body, lines in _posted(conn):
        for ln in lines:
            if ln["kind"] != "expense":
                continue
            if not any(d and start <= d <= end for d in (ln["date"], ln["cashDate"])):
                continue
            out.append({"date": ln["date"], "quoteNo": ln["case"], "amount": ln["amount"],
                        "desc": "%s %s（%s）" % (body.get("name", ""), r["record_no"], ln["label"]),
                        "category": body.get("name") or r["module_key"],
                        "cashDate": ln["cashDate"], "cashAmount": ln["cashAmount"]})
    out.sort(key=lambda e: (e["date"] or e["cashDate"], e["desc"]))
    return out


def income_items(conn, start, end, basis, department_id=None) -> list:
    """自訂模組的收入逐筆（形狀同 `receivables.income_items`／`case.recognition.accrual_income_items`，營運報表直接併進去）。
    權責＝權責日、金額＝欄位值（未稅）；現金＝現金日、金額＝現金金額（含稅）。關聯案件是內建案件 ⇒ 略過（由內建報價單認列）。
    有部門篩選 ⇒ 只留關聯案件的業務屬於該部門的（沒有關聯案件無法歸屬 ⇒ 排除，同支出的作法）。"""
    cash = basis != "accrual"
    out = []
    for r, body, lines in _posted(conn):
        for ln in lines:
            if ln["kind"] != "income":
                continue
            d = ln["cashDate"] if cash else ln["date"]
            if not d or not (start <= d <= end):
                continue
            if ln["case"] and conn.execute("SELECT 1 FROM quotations WHERE quote_no=?", (ln["case"],)).fetchone():
                continue                                                    # dupSkipped：內建案件自己認列
            if department_id and (not ln["case"] or _case_dept(conn, ln["case"]) != department_id):
                continue
            amt = ln["cashAmount"] if cash else ln["amount"]
            out.append({"quoteNo": ln["case"], "customer": str(body.get("name") or ""), "project": r["record_no"], "salesPerson": r["created_by"],
                        "type": ln["label"], "amount": amt, "receivedAt": d, "recognizedAt": d, "actualAmount": None, "feeAmount": 0,
                        "netAmount": amt, "invoiceNo": "", "taxNote": "含稅" if cash else "未稅", "customModule": r["module_key"],
                        "recordNo": r["record_no"]})
    out.sort(key=lambda x: x["receivedAt"], reverse=True)
    return out


def undated_counts(conn, basis) -> dict:
    """入帳中、但缺該口徑日期的金流行數 `{income: n, expense: n}`（報表明說「待補登」，不可以靜默少列）。"""
    cash = basis != "accrual"
    out = {"income": 0, "expense": 0}
    for _r, _b, lines in _posted(conn):
        for ln in lines:
            if not (ln["cashDate"] if cash else ln["date"]):
                out[ln["kind"]] += 1
    return out


def dup_skipped(conn) -> list:
    """收入行因關聯到內建案件而略過的 `[{module, recordNo, case, amount}]`（讓使用者看得到「為什麼這張沒進報表」）。"""
    out = []
    for r, _body, lines in _posted(conn):
        for ln in lines:
            if ln["kind"] == "income" and ln["case"] and conn.execute("SELECT 1 FROM quotations WHERE quote_no=?", (ln["case"],)).fetchone():
                out.append({"module": r["module_key"], "recordNo": r["record_no"], "case": ln["case"], "amount": ln["amount"]})
    return out


def case_finance(conn, case_no) -> dict:
    """某案件（關聯案件欄位＝該單號）的入帳金流：`{expense: {total, items}, income: {total, items, skippedTotal}}`；金額取權責金額。
    支出＝案件成本的「自訂模組」一列；收入：案件是內建案件 ⇒ 由內建報價單認列，這裡的收入行標 `skipped` 並累計 `skippedTotal`（供對照，不進 total）。"""
    out = {"expense": {"total": 0, "items": []}, "income": {"total": 0, "items": [], "skippedTotal": 0}}
    builtin = bool(case_no) and conn.execute("SELECT 1 FROM quotations WHERE quote_no=?", (case_no,)).fetchone() is not None
    for r, body, lines in _posted(conn):
        for ln in lines:
            if ln["case"] != case_no:
                continue
            side = out[ln["kind"]]
            item = {"module": r["module_key"], "moduleName": body.get("name", ""), "recordNo": r["record_no"], "label": ln["label"],
                    "amount": ln["amount"], "date": ln["date"], "cashDate": ln["cashDate"], "cashAmount": ln["cashAmount"]}
            if ln["kind"] == "income" and builtin:
                item["skipped"] = True                                   # 內建報價單已認列 ⇒ 不重複計入（與營運報表同一個判準）
                side["skippedTotal"] += ln["amount"]
            else:
                side["total"] += ln["amount"]
            side["items"].append(item)
    return out
