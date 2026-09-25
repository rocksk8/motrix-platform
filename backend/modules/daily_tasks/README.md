# M12 每日任務（daily_tasks）

工作事項的指派、完成回報、編輯紀錄、逾期與區間到期提醒。

## 端點

前綴 `/api/daily-tasks`，權限 key `daily_task`（或 `case_manage`）。詳細清單見 `api.py`。

## 資料（依 MODULE-GUIDE §3 分類）

| 名稱 | 類別 | 說明 |
|---|---|---|
| `daily_tasks` | T1 | 工作事項本體 |
| `daily_task_completions` | T1 | 各負責人各日期的完成回報 |
| `daily_task_edit_log` | T1 | 編輯紀錄 |

## 串接點

| 方向 | 串接點 | 說明 |
|---|---|---|
| 提供 | IP-5 `daily_task.external` | 別組（M01 案件執行進度）建立／同步／收回任務 |
| 提供 | IP-10 `daily.check`（名稱 `daily_tasks`） | 逾期與區間到期檢查，由 L1 `helpers/daily_checks.py` 每天 08:00 呼叫；啟動補跑依 `dt_overdue_last_check` 逐日補 |

## 本模組不在時

- `/api/daily-tasks/*` 回 404；側欄入口隱藏（`module.json` 的 `pages`）。
- M01 案件執行進度勾選完成照常存檔，回應 `notice` 明說「未建立每日任務：每日任務模組未安裝」（IP-5）。
- 每日 08:00 的系統健康檢查（憑證、備份、磁碟、暫存、簽核催辦）與案件提醒**照常**：它們已不在本模組（2026-09-26 拆出，見 IP-10）。
