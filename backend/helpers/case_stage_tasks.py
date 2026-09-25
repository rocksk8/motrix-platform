"""案件執行進度 → 「每日工作事項」月曆的鏡射（2026-09-11）。

使用者交辦第 3 項要求「兩邊都要」：勾選執行進度時，除了 Google 行事曆
（`google_calendar.py::push_event_for_case_stage_done()`），系統內
「每日工作事項 → 月曆總覽」那張月曆上也要看得到「案件名稱＋進度」。

那張月曆的資料源就是 `daily_tasks`（`daily-tasks.html::monthCalWeeks()` 讀
`/api/daily-tasks?year_month=`），沒有別的來源——所以要出現在上面，就得真的
產生一列 `daily_tasks`。

**三個一定要注意的地方**（每一個猜錯都會變成使用者被系統騷擾）：

1. **一定要指派人**。`daily_tasks` 的列表端點對非 superadmin 會過濾成「我是
   負責人或監督人」（`daily_tasks.py::_user_filter_sql()`），`assigned_to` 空的
   那列只有 superadmin 看得到——等於幫使用者做了一個他看不見的東西。所以：
   階段負責人優先，沒有負責人就掛在**勾選的人**身上。

2. **建立的當下就要標成已完成**。`_check_overdue_and_notify()` 每天掃前一天
   的 `once` 任務，只要負責人沒有 `daily_task_completions` 的完成紀錄就寄
   逾期通知。這列是「已經做完的事」的紀錄，不標完成的話，隔天全部負責人都會
   收到一封「你逾期未完成」的信。

3. **取消勾選要收回**。用 `case_stages.daily_task_id`（DB v76）記住是哪一列，
   取消勾選時 soft delete（`is_deleted=1`，跟使用者自己刪任務同一條路徑），
   不是靠標題比對去猜——標題含案件名稱，案件改名就對不上了。

跟 `google_calendar.py` 的三個 push 一樣是 fire-and-forget：包在最外層
try/except，任何失敗只記 log，絕不能讓「月曆沒同步」擋住勾選這個主要動作。

🔑 2026-09-25（ROADMAP A11，INTEGRATION-POINTS IP-5）：本檔（M01）**不再直接寫**
`daily_tasks`／`daily_task_completions`（M12 的表），改走 M12 公開的
`daily_task.external` 提供者；本檔只讀自己的 `case_stages`／`quotations`、決定任務內容，
並把任務 id 記回 `case_stages.daily_task_id`。M12 未安裝 ⇒ 勾選照常存檔，只是不產生
每日任務，`daily_task_notice()` 回「未建立每日任務：每日任務模組未安裝」。
"""
import json
import logging
from datetime import date, datetime

from core import registry as _registry

logger = logging.getLogger(__name__)

CATEGORY = "案件進度"
NOTICE_NO_DAILY_TASKS = "未建立每日任務：每日任務模組未安裝"
# 取消勾選／刪除階段時，原本建立過的每日任務收不回來（M12 不在時 M01 不碰 M12 的表）。
# 任務 id 留在 case_stages.daily_task_id：M12 裝回來之後再勾選／取消勾選，會收斂到同一筆任務，不會多出一筆。
NOTICE_NOT_WITHDRAWN = "未收回每日任務：每日任務模組未安裝，原本建立的任務仍在"


def _tasks():
    """M12 的 IP-5 提供者；未安裝 ⇒ None。"""
    return _registry.single_provider("daily_task.external")


def daily_task_notice(done=True, had_task=False):
    """給呼叫端放進回應的提示（AUDIT-X-C-batch1 B-1）；M12 在的時候回 None。

    M12 不在時：勾選（done=True）⇒ 沒有建立每日任務；取消勾選或刪除階段（done=False）⇒ 原本有任務
    （had_task）才要說「沒有收回」，原本就沒有任務就沒有什麼要說的。"""
    if _tasks() is not None:
        return None
    if done:
        return NOTICE_NO_DAILY_TASKS
    return NOTICE_NOT_WITHDRAWN if had_task else None


def sync_daily_task_for_case_stage(stage_id: int, actor_username: str = "",
                                   actor_display: str = "") -> None:
    """依 `case_stages.done` 建立／更新／收回對應的每日工作事項。"""
    try:
        tasks = _tasks()
        if tasks is None:
            logger.info("sync_daily_task_for_case_stage(%s)：%s", stage_id, NOTICE_NO_DAILY_TASKS)
            return
        from db import get_db
        conn = get_db()
        row = conn.execute("""
            SELECT cs.id, cs.label, cs.done, cs.done_at, cs.quote_no, cs.assigned_to,
                   cs.daily_task_id, q.customer_name, q.project_name
            FROM case_stages cs JOIN quotations q ON q.quote_no = cs.quote_no
            WHERE cs.id=?
        """, (stage_id,)).fetchone()
        if not row:
            conn.close()
            return

        task_id = row["daily_task_id"] or 0
        now = datetime.now().isoformat()

        if not row["done"]:
            if task_id:
                tasks.withdraw(conn, task_id, now)
                conn.execute("UPDATE case_stages SET daily_task_id=0 WHERE id=?", (stage_id,))
                conn.commit()
                logger.info("sync_daily_task_for_case_stage: stage %s 取消勾選，收回任務 %s",
                            stage_id, task_id)
            conn.close()
            return

        done_at = (row["done_at"] or "").strip()[:10]
        try:
            task_date = date.fromisoformat(done_at).isoformat() if done_at else date.today().isoformat()
        except ValueError:
            task_date = date.today().isoformat()

        try:
            assignees = [u for u in json.loads(row["assigned_to"] or "[]") if u]
        except Exception:
            assignees = []
        # 見模組 docstring 第 1 點：沒有負責人就掛勾選的人，不能留空
        if not assignees and actor_username:
            assignees = [actor_username]

        cname = row["customer_name"] or ""
        pname = row["project_name"] or ""
        case_name = pname or row["quote_no"]
        stage_label = row["label"] or "執行階段"
        # 見模組 docstring 第 2 點：完成紀錄由提供者一併寫（不標完成，隔天每個負責人都會收到逾期通知）
        new_id = tasks.upsert(
            conn, task_id=task_id, task_date=task_date,
            title=f"{case_name}｜{stage_label}",
            description=(f"案件執行進度「{stage_label}」已完成。\n"
                         f"案件編號：{row['quote_no']}\n客戶：{cname}\n"
                         f"（本列由案件管理勾選執行進度時自動建立）"),
            category=CATEGORY, assignees=assignees, created_by=actor_username or "",
            case_no=row["quote_no"],
            completion_report=(f"案件管理勾選「{stage_label}」完成"
                               + (f"（{actor_display}）" if actor_display else "")),
            now=now)
        if new_id != task_id:
            conn.execute("UPDATE case_stages SET daily_task_id=? WHERE id=?", (new_id, stage_id))
        conn.commit()
        conn.close()
        logger.info("sync_daily_task_for_case_stage: stage %s -> daily_task %s (%s)",
                    stage_id, new_id, task_date)
    except Exception as exc:
        logger.warning("sync_daily_task_for_case_stage(%r) failed: %s", stage_id, exc)


def delete_daily_task_for_case_stage(task_id: int) -> None:
    """階段本身被刪除時呼叫（呼叫端已從即將刪除的 row 取出 daily_task_id）。"""
    if not task_id:
        return
    try:
        tasks = _tasks()
        if tasks is None:
            return
        from db import get_db
        conn = get_db()
        tasks.withdraw(conn, task_id, datetime.now().isoformat())
        conn.commit()
        conn.close()
        logger.info("delete_daily_task_for_case_stage: soft-deleted task %s", task_id)
    except Exception as exc:
        logger.warning("delete_daily_task_for_case_stage(%r) failed: %s", task_id, exc)
