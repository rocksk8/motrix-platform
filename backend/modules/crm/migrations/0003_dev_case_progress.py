# -*- coding: utf-8 -*-
"""crm v3（2026-11-04，業務開發案件「指派／進度回報」重設計，見 docs/platform/plans/DEV-CASE-PROGRESS-REDESIGN-PLAN.md）：

1. 新表 `dev_case_progress(id, case_id, author_id, owner_unit_id, content, created_at)`：進度回報改成只增不改不刪的歷史表；
   `owner_unit_id INTEGER NOT NULL DEFAULT 1` 隨案件的單位（單位守門 test_unit_scope_guard_t6：新表直接加，不再宣告豁免；同 dev_logs）。
2. `dev_cases.assigned_at`／`assigned_by`：只在換人（含首次指派、取消指派）時更新，供「自指派之後有沒有回報」的逾期判斷。
3. 既有資料：`dev_cases.progress_report` 非空 ⇒ 搬成該案的第一筆進度（作者＝搬遷當下的 `assigned_to`，沒有被指派人就留空；時間＝`updated_at`）；
   已被指派的案件 `assigned_at` 設成 `updated_at`、`assigned_by` 留空（舊資料不知道是誰指派的）。
   這樣搬完那一刻不會因為「assigned_at 很舊、沒有進度」把一批既有案件誤判逾期。

- 舊的 `progress_report` 欄位保留不刪（模組 migration 只增不破壞；回退到舊程式碼時舊程式碼照常讀它）。
- 冪等：表／欄位已在就不重建；搬資料只搬「該案還沒有任何進度列」的案件，重跑不會重複搬；`assigned_at` 只補還是空的。
- 這是 L2 遷移，失敗會讓 crm 整模組下線 ⇒ 表不在（不該發生：V9 建）回原因字串＝未完成（版號不前進、下次啟動再補），其他例外往外丟。
- 不自己 commit；SQL 寫在這裡，不 import 任何會演進的程式碼（守門 tests/platform/test_module_migrations.py）。
"""


def up(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(dev_cases)").fetchall()}
    if not cols:
        return "dev_cases 表不存在（應由 V9 建立），這次不補、下次啟動再試"
    if "assigned_at" not in cols:
        conn.execute("ALTER TABLE dev_cases ADD COLUMN assigned_at TEXT")
    if "assigned_by" not in cols:
        conn.execute("ALTER TABLE dev_cases ADD COLUMN assigned_by INTEGER")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS dev_case_progress ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " case_id INTEGER NOT NULL,"
        " author_id INTEGER,"
        " owner_unit_id INTEGER NOT NULL DEFAULT 1,"
        " content TEXT NOT NULL,"
        " created_at TEXT NOT NULL)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dev_case_progress_case ON dev_case_progress(case_id, id)")

    unit = "COALESCE(d.owner_unit_id, 1)" if "owner_unit_id" in cols else "1"       # 單位欄由 core migration 加；舊／簡化的庫沒有就用根單位
    if "progress_report" in cols and "assigned_to" in cols:       # 0002 之後一定有；防呆（人工搬動的庫）
        conn.execute(
            "INSERT INTO dev_case_progress (case_id, author_id, owner_unit_id, content, created_at) "
            "SELECT d.id, d.assigned_to, " + unit + ", d.progress_report, COALESCE(NULLIF(d.updated_at, ''), d.created_at, '') "
            "FROM dev_cases d "
            # TRIM 預設只去空格；換行、tab 也要當空白
            "WHERE TRIM(COALESCE(d.progress_report, ''), ' ' || char(9) || char(10) || char(13)) <> '' "
            "AND NOT EXISTS (SELECT 1 FROM dev_case_progress p WHERE p.case_id = d.id)"
        )
        conn.execute(
            "UPDATE dev_cases SET assigned_at = COALESCE(NULLIF(updated_at, ''), created_at) "
            "WHERE assigned_to IS NOT NULL AND (assigned_at IS NULL OR assigned_at = '')"
        )
    return None
