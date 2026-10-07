# -*- coding: utf-8 -*-
"""承攬商匯款的預定付款日：行事曆「付款待辦」事件與提醒信的薄接線（第 45 班；使用者 Q3／Q8）。

[單位] subcontract:payable_due    [層] L2（M04）    [穩定度] 實作
[公開介面] eligible(row)、event_tuple(row)、sync(voucher_no)、fire(voucher_no)（commit 之後呼叫）、run_reminders(today=None)（`daily.check` 由 `run_daily_checks` 呼叫）
[不變式] ① 事件跟著「現況」走：已核准、未匯款、未作廢、預定付款日合法 ⇒ upsert（預定日當天）；其餘 ⇒ delete——核准／退回／撤銷核准／作廢／標記已匯款／取消已匯款／
           差額退回／改預定日，任何一條路徑 commit 後呼叫 `fire` 就收斂。事件識別＝（payable_due, `subcontract_voucher:<單號>`）
        ② 事件、提醒信、站內通知**不含金額、承攬商人員姓名、廠商名**（Q4：只放單號、名目、關聯案件、預定日）
        ③ 日期規則、guard、寄送迴圈、站內通知全在 L1 `helpers.payable_due_core`；本檔只查自己的待付款列。信件類型由 M01 登記（M01 不在 ⇒ 寄信 fail-closed，已知取捨）
[契約題] modules/subcontract/tests/test_voucher_planned_pay_date_t45.py
"""
import logging
import re
from datetime import date

from db import get_db, spawn_bg_thread
from helpers import payable_due_core as _core

logger = logging.getLogger(__name__)

SOURCE = "subcontract_voucher"
_YMD = re.compile(r"\d{4}-\d{2}-\d{2}")


def planned_date(row) -> str:
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
    if row is None or (row["status"] or "") != "已核准" or row["is_paid"] or (row["voided_at"] or ""):
        return False
    return bool(planned_date(row))


def _what(row) -> str:
    kn = (row["kind_name"] or "").strip() if "kind_name" in row.keys() else ""
    seq = row["seq"] if "seq" in row.keys() else 0
    return "承攬商匯款" + ("｜%s 第 %d 期" % (kn, seq) if kn and seq else "")


def compose(row):
    day = planned_date(row)
    lines = ["預定付款日：" + day, "單號：" + row["voucher_no"], "名目：" + _what(row)]
    if row["quote_no"]:
        lines.append("關聯案件：" + row["quote_no"])
    return "付款待辦 — %s｜%s" % (row["voucher_no"], _what(row)), "\n".join(lines), day


def event_tuple(row):
    """現況合格 ⇒ (CODE, 標題, 說明, 日期, key)；否則 None（差額退回後讓出納端點 upsert 用）。"""
    if not eligible(row):
        return None
    t, d, day = compose(row)
    return (_core.EVENT_CODE, t, d, day, "%s:%s" % (SOURCE, row["voucher_no"]))


def sync(voucher_no) -> None:
    try:
        conn = get_db()
        try:
            row = conn.execute("SELECT * FROM contractor_payment_vouchers WHERE voucher_no=?", (voucher_no,)).fetchone()
        finally:
            conn.close()
        ev = event_tuple(row) if row is not None else None
        _core.sync_event(SOURCE, voucher_no, None if ev is None else ev[1:4])
    except Exception as exc:                                              # noqa: BLE001
        logger.warning("subcontract.payable_due.sync(%s) failed: %s", voucher_no, exc)


def fire(voucher_no) -> None:
    spawn_bg_thread(sync, args=(voucher_no,))


def run_reminders(today=None) -> int:
    """提醒信（3 天前／當天／逾期）與站內通知；規則與案件額外支出同一支 L1 庫。任何例外只記 log。"""
    try:
        from helpers import business_days as _bd
        today = today or date.today()
        is_wd = _bd.is_working_day
        cands = _core.candidate_planned_dates(today, is_wd)
        if not cands:
            _core.prune_guards(today)
            return 0
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT * FROM contractor_payment_vouchers WHERE status='已核准' AND is_paid=0 AND COALESCE(voided_at,'')='' AND substr(planned_pay_date,1,10) IN (%s)"
                " ORDER BY id" % ",".join("?" for _ in cands), cands).fetchall()
        finally:
            conn.close()
        items = []
        for r in rows:
            if not eligible(r):
                continue
            no, planned = r["voucher_no"], planned_date(r)
            info = [("單號", no), ("名目", _what(r)), ("預定付款日", planned)]
            if r["quote_no"]:
                info.append(("關聯案件", r["quote_no"]))
            items.append({"guard_id": "%s.%s" % (SOURCE, no), "planned": planned, "ident": "%s %s" % (no, _what(r)), "rows": info,
                          "source": SOURCE, "key": no})
        return _core.run_scan(items, today, is_wd=is_wd)
    except Exception as exc:                                              # noqa: BLE001
        logger.warning("subcontract.payable_due.run_reminders failed: %s", exc)
        return 0


def run_daily_checks(mode: str = "daily") -> None:
    """`daily.check` 提供者（IP-11）：daily／startup 做一樣的事。"""
    run_reminders()
