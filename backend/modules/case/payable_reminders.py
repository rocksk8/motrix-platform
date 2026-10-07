# -*- coding: utf-8 -*-
"""預定付款日提醒信（2026-10-05，使用者裁示）：預定付款日的前 3 天與當天，寄給財務。

[單位] case:payable_reminders    [層] L2（M01）    [穩定度] 實作
[公開介面] run(today=None)；日期規則、guard、寄送迴圈、站內通知已搬到 L1 `helpers.payable_due_core`（第 45 班 Q8；本檔只保留「查案件額外支出＋叫料匯款的待付款列」與信件類型登記）
[公開介面（相容）] due_kind(planned, today)、effective_send_day(nominal)、is_working_day(d)（測試換假日接縫的唯一入口）（`daily.check` 每日 08:00／啟動補跑，由 `case_deadlines.run_daily_checks` 呼叫）
[對象] 案件額外支出與叫料匯款申請（已核准、還有剩餘應付、`planned_pay_date` 合法；承攬商匯款由 M04 自己的薄接線呼叫同一支 L1 庫）。額外支出：已核准、未付款、未作廢、要出納付款的類型（`payable_calendar.eligible`）且 `planned_pay_date` 是合法日期的案件額外支出
       （kind='' 舊版＋採購單／差旅／零用金；請購單不進出納 ⇒ 不提醒）。沒填預定付款日 ⇒ 不提醒。
[時機] 逾期（Q2，第 45 班）：預定日後第 1 個工作日寄 1 封 `payable_due_overdue`，不週提。規則細節見 `helpers/payable_due_core.py`。
[時機] 名義日：預定日 − 3 天 ⇒ `payable_due_soon`；預定日當天 ⇒ `payable_due_today`。**名義日不是工作日（週六、週日）就提前到前一個工作日寄**
       （使用者 2026-10-05：週末到期 ⇒ 週五寄；3 天前落在週末 ⇒ 前一個週五寄）。若「3 天前」與「當天」折到同一個寄信日 ⇒ **只寄一封**（當天那封，
       內文為「今日到期」），兩把 guard 都寫。非工作日這天不寄任何提醒（延到前一個工作日已寄過）。
       預定日距今不到 3 天才填／核准 ⇒ 沒有「3 天前」那封；寄信日已過的不補發。
       **工作日＝`helpers.business_days.is_working_day`**（週末＋國定假日／補假；補班日算上班日；假日表 `helpers/holidays_tw.json` 未涵蓋的年份只排除週六日）。
       名義日落在假日 ⇒ 同樣提前到前一個工作日寄（T−3、T0 皆然）。
[冪等] **先寄、結果確定才記 guard**（照 `helpers/system_checks.py` 的前例）：`SEND_SENT`、`SEND_UNKNOWN`（等不到結果，重寄可能雙寄）、`SEND_PERMANENT_FAIL`（永遠寄不出去，重試只是天天失敗）
       ⇒ 寫 guard（後兩種另記 ERROR log 讓人看見）；只有 `SEND_TRANSIENT_FAIL`（SMTP 暫時失敗）、`SEND_SKIPPED`（未設定／被擋）、沒有財務收件人 ⇒ 不寫，之後再跑會重試。
       每封一把 guard key（`payable_due_notif.<id>.<soon|today>.<預定日>.<實際寄信日>`，寫進 system_settings）：重啟補跑、同天重跑都不重寄；
       改了預定日 ⇒ key 變了、依新日期重新發。過期（寄信日早於今天 7 天以上）的 key 每次掃描順手清掉。
[重試窗口] **只有「寄信日當天」**：候選項目只取「寄信日＝今天」者（`_candidate_planned_dates`），而執行時機只有每日 08:00 與啟動補跑兩次；暫時失敗的信當天若兩次都沒寄成，
       **隔天不補**（寄信日已過，不補發）。
[等待上限] 每封最多等 `SEND_WAIT_TIMEOUT_SECONDS`（45 秒）；一次掃描**總共最多等 `MAX_WAIT_SECONDS_PER_RUN`**（超過就停止寄送，剩下的不寫 guard、等下一次重試），
       且出現 `SEND_UNKNOWN`（SMTP 卡住）就立刻停止本次掃描——後面的信多半也會卡。每日檢查在排程執行緒裡循序執行，不能被卡死的 SMTP 拖住。
[收件人] 信件類型 `payable_due_soon`／`payable_due_today` 登記在「財務」群組（`mail_types` group `finance`），寄信一律 `to_group=True`、**不另帶 usernames**：
         收件人＝`helpers.email_notify.finance_recipient_emails`（在職、有 Email、**未退訂**該類型的財務角色＋最高管理者），並套超級管理員在
         「信件與通知收件設定」頁的覆寫（僅超管／自訂）。沒有收件人 ⇒ 不寄、**不寫 guard**（下次有收件人再發）。
[信內容] 不放金額（使用者裁示：金額可見性只給簽核人／申請人／財務；信件走外部郵件系統）。
"""
import logging
import time
from datetime import date

from db import get_db
from helpers import business_days as _bd
from helpers import email_notify as _en
from helpers import mail_types as _mt
from helpers import payable_due_core as _core

logger = logging.getLogger(__name__)

_mt.register("payable_due_soon", "預定付款日將到（3 天前）", "business", "finance", "財務",
             "請款的預定付款日將到，到期未付款會影響對廠商或受款人的付款承諾。", "請登入系統，於出納的「待付款申請」確認並安排付款。", owner="case")
_mt.register("payable_due_today", "預定付款日當天", "business", "finance", "財務",
             "請款的預定付款日就是今天，尚未登錄付款。", "請登入系統，於出納的「待付款申請」登錄付款；若需改期請更新預定付款日。", owner="case")
_mt.register("payable_due_overdue", "預定付款日已逾期", "business", "finance", "財務",
             "請款的預定付款日已過（之後第 1 個工作日提醒一次），尚未登錄付款。", "請登入系統，於出納的「待付款申請」登錄付款，或更新預定付款日。", owner="case")

SOON_DAYS = _core.SOON_DAYS
MAX_WAIT_SECONDS_PER_RUN = _core.MAX_WAIT_SECONDS_PER_RUN          # 一次掃描等寄送結果的總時間上限（秒）；測試可 monkeypatch 本檔的值（run 時傳給核心）
_monotonic = time.monotonic              # 測試可 monkeypatch
_GUARD = _core.GUARD_PREFIX


def is_working_day(d: date) -> bool:
    """寄信用的工作日判斷：L1 `helpers.business_days`（週末＋官方國定假日＋補班日；假日表未涵蓋的年份只排除週六日）。測試可 monkeypatch 這一支。"""
    return _bd.is_working_day(d)


def _wd(d: date) -> bool:
    return is_working_day(d)             # 每次呼叫才解析模組全域名稱：測試換掉 is_working_day 要生效


def effective_send_day(nominal: date, limit: int = 14) -> date:
    return _core.effective_send_day(nominal, _wd, limit)


def due_kind(planned: str, today: date) -> tuple:
    """⇒ (要寄哪一封 '' ／soon／today／overdue, 要寫 guard 的 [(kind, 寄信日)])。折到同一天 ⇒ 只回 today，但兩把 guard 都要寫。"""
    return _core.due_kind(planned, today, _wd)


def _candidate_planned_dates(today: date) -> list:
    return _core.candidate_planned_dates(today, _wd)


def _mail(kind, rows, link, ident, out=None):
    """字面 key 呼叫 send_registered（守門逐一核對）；不放金額。收件人＝財務群組（見檔頭〔收件人〕），不另帶 usernames。"""
    if kind == "soon":
        return _en.send_registered("payable_due_soon", title="預定付款日將到", rows=rows, to_group=True,
                                   badge_text="3 天後到期", badge_color="#D97706", link=link, button_text="前往出納",
                                   reason=ident, wait=True, out=out, note="您好，以下請款的預定付款日還有 3 天，請安排付款。")
    if kind == "overdue":
        return _en.send_registered("payable_due_overdue", title="預定付款日已逾期", rows=rows, to_group=True,
                                   badge_text="已逾期", badge_color="#7F1D1D", link=link, button_text="前往出納",
                                   reason=ident, wait=True, out=out, note="您好，以下請款的預定付款日已過，尚未登錄付款；請安排付款或更新預定付款日。")
    return _en.send_registered("payable_due_today", title="預定付款日當天", rows=rows, to_group=True,
                               badge_text="今日到期", badge_color="#DC2626", link=link, button_text="前往出納",
                               reason=ident, wait=True, out=out, note="您好，以下請款的預定付款日就是今天，尚未登錄付款。")


def _expense_items(conn, cands):
    """案件額外支出（來源 `case`）：guard_id 沿用舊格式（純 id），相容切換前已寫的 guard。"""
    from modules.case import payable_calendar as PC
    out = []
    for r in conn.execute(
            "SELECT e.*, q.customer_name AS _cust, q.project_name AS _proj FROM case_extra_expenses e"
            " LEFT JOIN quotations q ON q.quote_no = e.quote_no"
            " WHERE e.status = '已核准' AND COALESCE(e.paid_date, '') = '' AND substr(e.planned_pay_date, 1, 10) IN (%s)"
            " ORDER BY e.id" % ",".join("?" for _ in cands), cands).fetchall():
        if not PC.eligible(r):
            continue
        ident = (r["doc_code"] or "").strip() or "#%s" % r["id"]
        what = (r["description"] or r["category"] or "請款").strip()
        planned = PC.planned_date(r)
        info = [("單號", ident), ("名目", what), ("預定付款日", planned)]
        if r["quote_no"]:
            info.append(("關聯案件", "%s（%s）" % (r["quote_no"], r["_cust"] or "")))
        out.append({"guard_id": str(r["id"]), "planned": planned, "ident": "%s %s" % (ident, what), "rows": info, "source": "case", "key": str(r["id"])})
    return out


def _material_items(conn, cands):
    """叫料匯款申請（來源 `case_material`）：已核准、還有剩餘應付。內容只放單號、品名（名目）、預定日、關聯案件；不放供應商與金額。"""
    from modules.case import material_payment as MP
    from modules.case import payable_calendar as PC
    out = []
    for r in conn.execute(
            "SELECT p.*, q.customer_name AS _cust FROM case_material_payments p LEFT JOIN quotations q ON q.quote_no = p.quote_no"
            " WHERE p.status=? AND substr(p.planned_pay_date, 1, 10) IN (%s) ORDER BY p.id" % ",".join("?" for _ in cands),
            [MP.S_APPROVED] + list(cands)).fetchall():
        pay = dict(r)
        planned = PC.planned_date(pay)
        if not planned or MP.remaining_of(conn, pay) <= 0:
            continue
        ident = pay["doc_code"] or "#%s" % pay["id"]
        what = "材料申請匯款｜%s" % (MP.snapshot_of(pay).get("itemName") or "")
        info = [("單號", ident), ("名目", what), ("預定付款日", planned)]
        if pay["quote_no"]:
            info.append(("關聯案件", "%s（%s）" % (pay["quote_no"], r["_cust"] or "")))
        out.append({"guard_id": "case_material.%s" % pay["id"], "planned": planned, "ident": "%s %s" % (ident, what), "rows": info,
                    "source": "case_material", "key": str(pay["id"])})
    return out


def run(today=None) -> int:
    """⇒ 這次寄出幾封（測試用）。任何例外只記 log，不影響其他每日檢查。"""
    try:
        today = today or date.today()
        cands = _candidate_planned_dates(today)
        if not cands:
            _core.prune_guards(today)
            return 0
        conn = get_db()
        try:
            items = _expense_items(conn, cands) + _material_items(conn, cands)
        finally:
            conn.close()
        return _core.run_scan(items, today, is_wd=_wd, monotonic=lambda: _monotonic(), send=_mail,
                              max_wait=MAX_WAIT_SECONDS_PER_RUN)
    except Exception as exc:
        logger.warning("payable_reminders.run failed: %s", exc)
        return 0
