# -*- coding: utf-8 -*-
"""案件款項 → Google 行事曆事件「收款登錄」「應收到期提醒」（2026-10-05，使用者裁示；兩種都預設關）。

[單位] case:receipt_calendar    [層] L2（M01）    [穩定度] 實作
[公開介面] events_for_change(old_items, new_items) → [(op, code, ident, item)]；push_after_commit(quote_no, old_items, new_items)
[限制] 事件只在「款項期別有變動」的那次存檔才對齊：把事件種類**打開**之前就已存在的款項不會回補（要等該期別下一次變動）；
       事件內容用到的欄位（收款日／入帳帳戶／款項名稱；到期＝預計日／款項名稱）改了才會更新說明。
       客戶名稱、專案名稱等案件層欄位改了不會回頭更新既有事件。
[不變式] ① 只在 commit 之後、背景執行緒推（INTEGRATION-POINTS IP-6「新事件的寫法」）；不在寫鎖內
        ② 事件以 (代碼, 案號::期別 id) 為唯一識別（L1 push_event_upsert／delete_for_module，與日期無關）：重複存檔不會重複建立，
           改日期＝移動同一筆，收款／取消收款／刪期別＝刪掉對應事件
        ③ **事件不含任何金額**（使用者 2026-10-05 裁示：公司行事曆看得到的人不一定有財務金額可視）：標題與說明都只放案號、客戶、專案、款項名稱、日期、入帳帳戶、登錄人
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


def _label(it):
    return str(it.get("type") or it.get("label") or "")


def _receipt_sig(it):
    """事件內容會用到的欄位（任何一個變了都要更新事件說明）：收款日、入帳帳戶、款項名稱。**不含金額**——金額不進事件，金額變動不必同步。"""
    return (_ymd(it.get("receivedAt")), it.get("bankAccountName") or "", _label(it))


def _due_sig(it):
    """到期提醒事件內容用到的欄位：預計收款日、款項名稱（不含金額）。"""
    return (_ymd(it.get("expectedReceiptDate")), _label(it))


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
            if not _is_due(o) or _due_sig(o) != _due_sig(it):
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


def _compose(code, quote_no, customer, project, it):
    """⇒ (標題, 說明, 日期)。**不放任何金額**（見檔頭③）。"""
    label = it.get("type") or it.get("label") or "款項"
    head = "\n".join(["案件：%s" % quote_no, "客戶：%s" % customer, "專案：%s" % project, "款項：%s" % label])
    if code == RECEIPT:
        day = _ymd(it.get("receivedAt"))
        lines = [head, "收款日：" + day]
        if it.get("bankAccountName"):
            lines.append("入帳帳戶：" + str(it["bankAccountName"]))
        if it.get("receivedBy"):
            lines.append("登錄人：" + str(it["receivedBy"]))
        return "收款登錄 — %s（%s）%s" % (quote_no, customer, label), "\n".join(lines), day
    day = _ymd(it.get("expectedReceiptDate"))
    return "應收到期 — %s（%s）%s" % (quote_no, customer, label), "\n".join([head, "預計收款日：" + day]), day


def push_after_commit(quote_no, old_items, new_items) -> None:
    """背景執行緒的本體（呼叫端 commit 之後 spawn_bg_thread(push_after_commit, args=(…))）。
    任何失敗只記 log，不影響存檔。"""
    try:
        from db import get_db
        from helpers import push_event_upsert_for_module, push_event_delete_for_module
        events = events_for_change(old_items, new_items)
        if not events:
            return
        customer = project = ""
        if any(op == "upsert" for op, *_ in events):
            conn = get_db()
            try:
                r = conn.execute("SELECT customer_name, project_name FROM quotations WHERE quote_no=?",
                                 (quote_no,)).fetchone()
            finally:
                conn.close()
            if r:
                customer, project = r["customer_name"] or "", r["project_name"] or ""
        for op, code, ident, it in events:
            key = "%s::%s" % (quote_no, ident)
            if op == "delete":
                push_event_delete_for_module(code, key)
                continue
            title, desc, day = _compose(code, quote_no, customer, project, it)
            push_event_upsert_for_module(code, title, desc, day, key)
    except Exception as exc:
        logger.warning("receipt_calendar.push_after_commit(%s) failed: %s", quote_no, exc)


def snapshot(items):
    """寫入前取款項期別的深拷貝（之後原地修改也不影響比對）。"""
    return copy.deepcopy(items or [])
