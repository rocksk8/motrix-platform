# 業務開發 更新紀錄

## 1.0.0 — 2026-09-26
- 模組化：自 `routers/dev_crm.py` 搬入 `modules/crm/api.py`（PLAYBOOK §B）；路由自帶 `/api` 前綴，由載入器掛載；每日 08:00 的停滯／暫緩到期檢查改由 `ModuleSpec.schedulers` 宣告
- 新增串接點 IP-11 `crm.quote_deleted`：報價單刪除時解除轉建連結改由本模組提供（原本 M01 直寫 `dev_cases`）
