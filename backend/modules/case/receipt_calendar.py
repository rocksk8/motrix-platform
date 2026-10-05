# -*- coding: utf-8 -*-
"""案件款項 → Google 行事曆事件「收款登錄」「應收到期提醒」（2026-10-05，使用者裁示；兩種都預設關）。

[單位] case:receipt_calendar    [層] L2（M01）    [穩定度] 實作
[公開介面] events_for_change(old_items, new_items) → [(op, code, ident, item)]；push_after_commit(quote_no, old_items, new_items)
[不變式] ① 只在 commit 之後、背景執行緒推（INTEGRATION-POINTS IP-6「新事件的寫法」）；不在寫鎖內
        ② 事件以 (代碼, 案號::期別 id) 為唯一識別（L1 push_event_upsert／delete_for_module，與日期無關）：重複存檔不會重複建立，
           改日期＝移動同一筆，收款／取消收款／刪期別＝刪掉對應事件
        ③ 標題不含金額；金額只在說明（同 invoice_voucher／payment_request 的先例）
        ④ 沒有 id 的舊期別不推（沒有穩定識別，不猜）
[資料] caseRecord.payment.items[]：received／receivedAt／expectedReceiptDate／actualAmount／feeAmount／bankAccountName／type
[寫入點] update_case_record（整包存）、mark_payment（出納標記收款）、半解鎖審核套用（case_record_update／payment_mark）
[契約題] modules/case/tests/test_receipt_calendar_2026_10_05.py
"""
import copy
import logging
import re
from datetime import date

logger = logging.getLogger(__name__)

RECEIPT = "receipt_logged"
DUE = "receivable_due"
_YMD = re.compile(r"\d{4}-\d{2}-\d{2}")


def _ymd(v) -> str:
    """合法 YYYY-MM-DD ⇒ 該字串；其餘 ⇒ ''（不猜日期）。"""
    s = str(v or "")[:10]
    if not _YMD.fullmatch(s):
        return ""
    try:
        date.fromisoformat(s)
    except ValueError:
        return ""
    return s


def _ident(it):
    return None if not isinstance(it, dict) or it.get("id") is None else str(it["id"])


def _receipt_sig(it):
    return (_ymd(it.get("receivedAt")), it.get("actualAmount"), it.get("feeAmount") or 0, it.get("bankAccountName") or "")


def _is_receipt(it) -> bool:
    return bool(it and it.get("received") and _ymd(it.get("receivedAt")))


def _is_due(it) -> bool:
    return bool(it and not it.get("received") and _ymd(it.get("expectedReceiptDate")))


def events_for_change(old_items, new_items) -> list:
    """比對款項期別的前後狀態 ⇒ [(op, code, ident, item)]，op ∈ upsert／delete；沒變就不產生（不打 Google）。"""
    old_by = {i: it for it in (old_items or []) if (i := _ident(it)) is not None}
    new_by = {i: it for it in (new_items or []) if (i := _ident(it)) is not None}
    out = []
    for ident, it in new_by.items():
        o = old_by.get(ident)
        if _is_receipt(it):
            if not _is_receipt(o) or _receipt_sig(o) != _receipt_sig(it):
                out.append(("upsert", RECEIPT, ident, it))
        elif o is not None and _is_receipt(o):                      # 取消收款（或收款日被清掉）
            out.append(("delete", RECEIPT, ident, it))
        if _is_due(it):
            if not _is_due(o) or _ymd(o.get("expectedReceiptDate")) != _ymd(it.get("expectedReceiptDate")):
                out.append(("upsert", DUE, ident, it))
        elif o is not None and _is_due(o):                          # 已收款／清空預計日 ⇒ 到期提醒收回
            out.append(("delete", DUE, ident, it))
    for ident, o in old_by.items():
        if ident in new_by:
            continue                                                # 期別被刪除：兩種事件都收回
        if _is_receipt(o):
            out.append(("delete", RECEIPT, ident, o))
        if _is_due(o):
            out.append(("delete", DUE, ident, o))
    return out


def _money(v) -> str:
    try:
        return "NT$ {:,.0f}".format(float(v))
    except (TypeError, ValueError):
        return ""


def _compose(code, quote_no, customer, project, it, receivable, actor=""):
    label = it.get("type") or it.get("label") or "款項"
    head = "案件：%s\n客戶：%s\n專案：%s\n款項：%s" % (quote_no, customer, project, label)
    if code == RECEIPT:
        day = _ymd(it.get("receivedAt"))
        lines = [head, "收款日：" + day]
        if it.get("bankAccountName"):
            lines.append("入帳帳戶：" + str(it["bankAccountName"]))
        if receivable is not None:
            actual = it.get("actualAmount")
            fee = it.get("feeAmount") or 0
            lines.append("應收：" + _money(receivable))
            lines.append("實收：" + _money(actual if actual is not None else receivable - float(fee or 0)))
            if fee:
                lines.append("手續費：" + _money(fee))
        if it.get("receivedBy") or actor:
            lines.append("登錄人：" + str(it.get("receivedBy") or actor))
        return "收款登錄 — %s（%s）%s" % (quote_no, customer, label), "\n".join(lines), day
    day = _ymd(it.get("expectedReceiptDate"))
    lines = [head, "預計收款日：" + day]
    if receivable is not None:
        lines.append("應收：" + _money(receivable))
    return "應收到期 — %s（%s）%s" % (quote_no, customer, label), "\n".join(lines), day


def push_after_commit(quote_no, old_items, new_items) -> None:
    """背景執行緒的本體（呼叫端 commit 之後 spawn_bg_thread(push_after_commit, args=(…))）。
    任何失敗只記 log，不影響存檔。"""
    try:
        from db import get_db
        from helpers import push_event_upsert_for_module, push_event_delete_for_module
        from modules.case.quotations import payment_item_amounts
        events = events_for_change(old_items, new_items)
        if not events:
            return
        customer = project = ""
        total = pretax = None
        if any(op == "upsert" for op, *_ in events):
            conn = get_db()
            try:
                r = conn.execute("SELECT customer_name, project_name, total, pretax FROM quotations WHERE quote_no=?",
                                 (quote_no,)).fetchone()
            finally:
                conn.close()
            if r:
                customer, project, total, pretax = r["customer_name"] or "", r["project_name"] or "", r["total"], r["pretax"]
        amounts = {}
        try:
            items = list(new_items or [])
            for it, amt in zip(items, payment_item_amounts(float(total or 0), items, pretax)):
                if _ident(it) is not None:
                    amounts[_ident(it)] = amt
        except Exception as exc:                                    # 金額算不出來 ⇒ 說明不帶金額，事件照推
            logger.info("receipt_calendar: 金額略過：%s", exc)
        for op, code, ident, it in events:
            key = "%s::%s" % (quote_no, ident)
            if op == "delete":
                push_event_delete_for_module(code, key)
                continue
            title, desc, day = _compose(code, quote_no, customer, project, it, amounts.get(ident))
            push_event_upsert_for_module(code, title, desc, day, key)
    except Exception as exc:
        logger.warning("receipt_calendar.push_after_commit(%s) failed: %s", quote_no, exc)


def snapshot(items):
    """寫入前取款項期別的深拷貝（之後原地修改也不影響比對）。"""
    return copy.deepcopy(items or [])
