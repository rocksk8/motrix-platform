# 每日任務 更新紀錄

## 1.0.0 — 2026-09-26
- 模組化：自 `routers/daily_tasks.py` 搬入 `modules/daily_tasks/api.py`（PLAYBOOK §B；搬自基底 84c53670，原檔拆成本檔與 L1 三檔，`git log --follow` 追不到，請以此查舊歷史）
- 每日 08:00 排程拆出：系統健康檢查下沉 L1（`helpers/system_checks.py`）、案件類檢查歸 M01（`helpers/case_deadlines.py`）、執行器在 L1（`helpers/daily_checks.py`）；本模組只留逾期與區間到期，以 IP-10 `daily.check` 登記
- 簽核催辦失敗的端點 `/api/settings/reminder-send-failures` 移到 L1 `routers/system.py`
- 提供者（IP-5、IP-10）改由 `ModuleSpec.providers` 宣告：模組未載入即不登記
