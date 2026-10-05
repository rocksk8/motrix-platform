# -*- coding: utf-8 -*-
"""案件額外支出（請款）→ Google 行事曆「付款待辦」（`payable_due`，2026-10-05，預設關）。

[單位] case:payable_calendar    [層] L2（M01）    [穩定度] 實作
[公開介面] eligible(row)、fire(exp_id)（呼叫端 commit 之後呼叫）、sync(exp_id)（背景執行緒本體）
[不變式] ① 事件跟著「現況」走，不跟著動作走：已核准、未付款、未作廢、可付款類型、預定付款日是合法日期 ⇒ upsert（預定付款日當天）；
           其餘 ⇒ delete。所以核准／改預定日／清預定日／付款／作廢／付款日被更正回待付款，任何一條路徑只要在 commit 後呼叫 `fire` 就收斂
        ② 事件識別＝（payable_due, `case:<額外支出 id>`）＝IP-100 的（來源, key）——出納端付款後只用這組識別就能刪事件，不必讀本模組的表
        ③ **事件不含任何金額**（使用者 2026-10-05 裁示；與收款登錄／應收到期同一做法）
        ④ 寫鎖內不呼叫（commit 後 spawn_bg_thread）；失敗只記 log
[契約題] modules/case/tests/test_payable_planned_pay_date_2026_10_05.py
"""
import logging
import re
from datetime import date

from db import get_db, spawn_bg_thread

logger = logging.getLogger(__name__)

CODE = "payable_due"
SOURCE = "case"
_YMD = re.compile(r"\d{4}-\d{2}-\d{2}")


def event_key(exp_id) -> str:
    return "%s:%s" % (SOURCE, exp_id)


def planned_date(row) -> str:
    """合法 YYYY-MM-DD ⇒ 該字串；其餘（沒填、格式錯、不存在的日期）⇒ ''（不猜）。"""
    try:
        s = str(row["planned_pay_date"] or "")[:10]
    except (IndexError, KeyError):
        return ""
    if not _YMD.fullmatch(s):
        return ""
    try:
        date.fromisoformat(s)
    except ValueError:
        return ""
    return s


def eligible(row) -> bool:
    """這筆現在該不該有「付款待辦」事件（也是提醒信的對象判準：已核准、未付款、未作廢、要出納付款的類型、有預定付款日）。"""
    from modules.case import expense_forms as EF
    if row is None or (row["status"] or "") != "已核准":
        return False
    if (row["paid_date"] or "").strip():
        return False
    if not EF.is_payable_kind(row["kind"] or ""):
        return False
    return bool(planned_date(row))


def compose(row, customer="", project=""):
    """⇒ (標題, 說明, 日期)。標題與說明都不放金額。"""
    ident = (row["doc_code"] or "").strip() or "#%s" % row["id"]
    what = (row["description"] or row["category"] or "請款").strip()
    title = "付款待辦 — %s｜%s" % (ident, what)
    lines = ["預定付款日：" + planned_date(row), "單號：" + ident, "名目：" + what]
    if row["quote_no"]:
        lines.append("關聯案件：%s（%s%s%s）" % (row["quote_no"], customer, "／" if customer and project else "", project))
    payee = (row["payee_name"] or row["payer_name"] or "").strip()
    if payee:
        lines.append("受款人：" + payee)
    if (row["pay_terms"] or "").strip():
        lines.append("付款條件：" + row["pay_terms"].strip())
    return title, "\n".join(lines), planned_date(row)


def sync(exp_id) -> None:
    """讀現況 ⇒ upsert 或 delete 該筆的「付款待辦」事件。任何失敗只記 log。"""
    try:
        from helpers import push_event_upsert_for_module, push_event_delete_for_module
        conn = get_db()
        try:
            row = conn.execute("SELECT * FROM case_extra_expenses WHERE id=?", (exp_id,)).fetchone()
            cust = proj = ""
            if row is not None and row["quote_no"]:
                q = conn.execute("SELECT customer_name, project_name FROM quotations WHERE quote_no=?", (row["quote_no"],)).fetchone()
                if q:
                    cust, proj = q["customer_name"] or "", q["project_name"] or ""
        finally:
            conn.close()
        key = event_key(exp_id)
        if row is not None and eligible(row):
            title, desc, day = compose(row, cust, proj)
            push_event_upsert_for_module(CODE, title, desc, day, key)
        else:
            push_event_delete_for_module(CODE, key)
    except Exception as exc:
        logger.warning("payable_calendar.sync(%s) failed: %s", exp_id, exc)


def fire(exp_id) -> None:
    """commit 之後呼叫：背景執行緒對齊事件。事件種類開關關閉時 L1 不碰 Google（零流量）。"""
    spawn_bg_thread(sync, args=(exp_id,))
