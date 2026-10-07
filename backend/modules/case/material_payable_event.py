# -*- coding: utf-8 -*-
"""叫料匯款申請 → Google 行事曆「付款待辦」（`payable_due`，第 45 班 Q3；種類開關預設關）。

[單位] case:material_payable_event    [層] L2（M01）    [穩定度] 實作
[公開介面] eligible(pay, remaining)、compose(pay, customer)、event_tuple(conn, pid)、sync(pid)（背景執行緒本體）、fire(pid)（呼叫端 commit 之後呼叫）
[不變式] ① 事件跟著「現況」走：已核准、還有剩餘應付、預定付款日合法 ⇒ upsert（預定日當天）；其餘 ⇒ delete——
           所以核准／改預定日／分次付款（仍有餘額 ⇒ 事件保留）／結清／退回／作廢／差額退回（明細刪除後回待付款）任何路徑只要 commit 後呼叫 `fire` 就收斂
        ② 事件識別＝（payable_due, `case_material:<申請 id>`）＝IP-100 的（來源, key）；實際對外呼叫經 L1 `helpers.payable_due_core.sync_event`（來源開關）
        ③ **事件不含金額、供應商、收款帳戶**（Q4：只放單號、名目、關聯案件、預定日）
        ④ 寫鎖內不呼叫（commit 後 spawn_bg_thread）；失敗只記 log
[契約題] modules/case/tests/test_material_payment_planned_t45.py
"""
import logging

from db import get_db, spawn_bg_thread
from helpers import payable_due_core as _core
from modules.case import material_payment as MP
from modules.case import payable_calendar as PC

logger = logging.getLogger(__name__)

SOURCE = "case_material"


def eligible(pay, remaining) -> bool:
    return bool(pay) and (pay["status"] or "") == MP.S_APPROVED and remaining > 0 and bool(PC.planned_date(pay))


def compose(pay, customer=""):
    ident = pay["doc_code"] or "#%s" % pay["id"]
    what = "材料申請匯款｜%s" % (MP.snapshot_of(pay).get("itemName") or "")
    lines = ["預定付款日：" + PC.planned_date(pay), "單號：" + ident, "名目：" + what]
    if pay["quote_no"]:
        lines.append("關聯案件：%s（%s）" % (pay["quote_no"], customer))
    return "付款待辦 — %s｜%s" % (ident, what), "\n".join(lines), PC.planned_date(pay)


def event_tuple(conn, pid):
    """現況合格 ⇒ (CODE, 標題, 說明, 日期, key)（出納差額退回後讓端點 upsert 用）；否則 None。"""
    pay = MP.get(conn, pid)
    if not pay or not eligible(pay, MP.remaining_of(conn, pay)):
        return None
    cust = ""
    q = conn.execute("SELECT customer_name FROM quotations WHERE quote_no=?", (pay["quote_no"],)).fetchone()
    if q:
        cust = q["customer_name"] or ""
    title, desc, day = compose(pay, cust)
    return (_core.EVENT_CODE, title, desc, day, "%s:%s" % (SOURCE, pay["id"]))


def sync(pid) -> None:
    try:
        conn = get_db()
        try:
            ev = event_tuple(conn, pid)
        finally:
            conn.close()
        _core.sync_event(SOURCE, pid, None if ev is None else ev[1:4])
    except Exception as exc:                                              # noqa: BLE001
        logger.warning("material_payable_event.sync(%s) failed: %s", pid, exc)


def fire(pid) -> None:
    spawn_bg_thread(sync, args=(pid,))
