# -*- coding: utf-8 -*-
"""預定付款日提醒信（2026-10-05，使用者裁示）：預定付款日的前 3 天與當天，寄給財務。

[單位] case:payable_reminders    [層] L2（M01）    [穩定度] 實作
[公開介面] run(today=None)（`daily.check` 每日 08:00／啟動補跑，由 `case_deadlines.run_daily_checks` 呼叫）
[對象] 已核准、未付款、未作廢、要出納付款的類型（`payable_calendar.eligible`）且 `planned_pay_date` 是合法日期的案件額外支出
       （kind='' 舊版＋採購單／差旅／零用金；請購單不進出納 ⇒ 不提醒）。沒填預定付款日 ⇒ 不提醒。
[時機] 名義日：預定日 − 3 天 ⇒ `payable_due_soon`；預定日當天 ⇒ `payable_due_today`。**名義日不是工作日（週六、週日）就提前到前一個工作日寄**
       （使用者 2026-10-05：週末到期 ⇒ 週五寄；3 天前落在週末 ⇒ 前一個週五寄）。若「3 天前」與「當天」折到同一個寄信日 ⇒ **只寄一封**（當天那封，
       內文為「今日到期」），兩把 guard 都寫。非工作日這天不寄任何提醒（延到前一個工作日已寄過）。
       預定日距今不到 3 天才填／核准 ⇒ 沒有「3 天前」那封；寄信日已過的不補發。
       **工作日＝週一至週五**（`is_working_day`）。⚠ 國定假日**尚未**納入：repo 內唯一的官方假日表在 M11 標案雷達
       （`modules/tender_radar/calendar_tw.py`＋`holidays_tw.json`，2026～2027），M01 不得 import 其他 L2 模組；要納入需先把假日表提到 L1 或加提供者（待裁示），
       接上之後只改 `is_working_day` 這一支。
[冪等] 每封一把 guard key（`payable_due_notif.<id>.<soon|today>.<預定日>.<實際寄信日>`，寫進 system_settings）：重啟補跑、同天重跑都不重寄；
       改了預定日 ⇒ key 變了、依新日期重新發。過期（寄信日早於今天 7 天以上）的 key 每次掃描順手清掉。
[收件人] 信件類型 `payable_due_soon`／`payable_due_today` 登記在「財務」群組（`mail_types` group `finance`），寄信一律 `to_group=True`、**不另帶 usernames**：
         收件人＝`helpers.email_notify.finance_recipient_emails`（在職、有 Email、**未退訂**該類型的財務角色＋最高管理者），並套超級管理員在
         「信件與通知收件設定」頁的覆寫（僅超管／自訂）。沒有收件人 ⇒ 不寄、**不寫 guard**（下次有收件人再發）。
[信內容] 不放金額（使用者裁示：金額可見性只給簽核人／申請人／財務；信件走外部郵件系統）。
"""
import logging
from datetime import date, timedelta

from db import get_db
from helpers import _get_setting, _set_setting
from helpers import email_notify as _en
from helpers import mail_types as _mt

logger = logging.getLogger(__name__)

_mt.register("payable_due_soon", "預定付款日將到（3 天前）", "business", "finance", "財務",
             "請款的預定付款日將到，到期未付款會影響對廠商或受款人的付款承諾。", "請登入系統，於出納的「待付款申請」確認並安排付款。", owner="case")
_mt.register("payable_due_today", "預定付款日當天", "business", "finance", "財務",
             "請款的預定付款日就是今天，尚未登錄付款。", "請登入系統，於出納的「待付款申請」登錄付款；若需改期請更新預定付款日。", owner="case")

SOON_DAYS = 3
_GUARD = "payable_due_notif."


def is_working_day(d: date) -> bool:
    """寄信用的工作日判斷：週一至週五。TODO：國定假日（見檔頭〔時機〕）——接上假日表只改這一支。"""
    return d.weekday() < 5


def effective_send_day(nominal: date, limit: int = 14) -> date:
    """名義日 ⇒ 實際寄信日：本身是工作日就是它，否則往前找最近的工作日（`limit` 天內找不到 ⇒ 原日期，不無窮迴圈）。"""
    d = nominal
    for _ in range(limit):
        if is_working_day(d):
            return d
        d -= timedelta(days=1)
    return nominal


def due_kind(planned: str, today: date) -> tuple:
    """⇒ (要寄哪一封 '' ／soon／today, 要寫 guard 的 [(kind, 寄信日)])。折到同一天 ⇒ 只回 today，但兩把 guard 都要寫。"""
    p = date.fromisoformat(planned)
    e_soon, e_today = effective_send_day(p - timedelta(days=SOON_DAYS)), effective_send_day(p)
    if e_soon == e_today:
        return ("today", [("soon", e_soon), ("today", e_today)]) if e_today == today else ("", [])
    if e_today == today:
        return "today", [("today", e_today)]
    if e_soon == today:
        return "soon", [("soon", e_soon)]
    return "", []


def _candidate_planned_dates(today: date) -> list:
    """今天可能要寄的預定日：寄信日＝今天的名義日（今天 ＋ 其後連續的非工作日）及其 +3 天。今天不是工作日 ⇒ []。"""
    if not is_working_day(today):
        return []
    span = [today]
    d = today + timedelta(days=1)
    while not is_working_day(d) and len(span) < 14:
        span.append(d)
        d += timedelta(days=1)
    return sorted({(x + timedelta(days=k)).isoformat() for x in span for k in (0, SOON_DAYS)})


def _mail(kind, rows, link, ident):
    """字面 key 呼叫 send_registered（守門逐一核對）；不放金額。收件人＝財務群組（見檔頭〔收件人〕），不另帶 usernames。"""
    if kind == "soon":
        return _en.send_registered("payable_due_soon", title="預定付款日將到", rows=rows, to_group=True,
                                   badge_text="3 天後到期", badge_color="#D97706", link=link, button_text="前往出納",
                                   reason=ident, note="您好，以下請款的預定付款日還有 3 天，請安排付款。")
    return _en.send_registered("payable_due_today", title="預定付款日當天", rows=rows, to_group=True,
                               badge_text="今日到期", badge_color="#DC2626", link=link, button_text="前往出納",
                               reason=ident, note="您好，以下請款的預定付款日就是今天，尚未登錄付款。")


def run(today=None) -> int:
    """⇒ 這次寄出幾封（測試用）。任何例外只記 log，不影響其他每日檢查。"""
    sent = 0
    try:
        from modules.case import payable_calendar as PC
        today = today or date.today()
        t0 = today.isoformat()
        cands = _candidate_planned_dates(today)
        if not cands:
            _prune_guards(today)
            return 0
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT e.*, q.customer_name AS _cust, q.project_name AS _proj FROM case_extra_expenses e"
                " LEFT JOIN quotations q ON q.quote_no = e.quote_no"
                " WHERE e.status = '已核准' AND COALESCE(e.paid_date, '') = '' AND substr(e.planned_pay_date, 1, 10) IN (%s)"
                " ORDER BY e.id" % ",".join("?" for _ in cands), cands).fetchall()
        finally:
            conn.close()
        for r in rows:
            if not PC.eligible(r):
                continue
            planned = PC.planned_date(r)
            kind, guards = due_kind(planned, today)
            if not kind:
                continue
            keys = ["%s%s.%s.%s.%s" % (_GUARD, r["id"], k, planned, e.isoformat()) for k, e in guards]
            if any(_get_setting(k) for k in keys if k.split(".")[-3] == kind):
                continue
            ident = (r["doc_code"] or "").strip() or "#%s" % r["id"]
            what = (r["description"] or r["category"] or "請款").strip()
            info = [("單號", ident), ("名目", what), ("預定付款日", planned)]
            if r["quote_no"]:
                info.append(("關聯案件", "%s（%s）" % (r["quote_no"], r["_cust"] or "")))
            if _mail(kind, info, "%s/pages/cashier.html" % _en._base_url(), "%s %s" % (ident, what)):
                for k in keys:                                  # 有收件人、已排入寄送才寫 guard；沒有收件人 ⇒ 不寫，下次有人再發
                    _set_setting(k, t0)
                sent += 1
            else:
                logger.warning("payable_reminders: 沒有財務收件人，#%s 的預定付款日提醒略過（不寫 guard）", r["id"])
        _prune_guards(today)
    except Exception as exc:
        logger.warning("payable_reminders.run failed: %s", exc)
    return sent


def _prune_guards(today: date) -> None:
    """清掉寄信日早於今天 7 天以上的 guard key（key 最後一段是實際寄信日）。"""
    cutoff = (today - timedelta(days=7)).isoformat()
    conn = get_db()
    try:
        stale = [r["key"] for r in conn.execute("SELECT key FROM system_settings WHERE key LIKE ?", (_GUARD + "%",)).fetchall()
                 if r["key"].rsplit(".", 1)[-1] < cutoff]
        if stale:
            conn.executemany("DELETE FROM system_settings WHERE key=?", [(k,) for k in stale])
            conn.commit()
    finally:
        conn.close()
