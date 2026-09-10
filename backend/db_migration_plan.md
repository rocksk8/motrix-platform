# DB 遷移計畫 — 2026-09-10

## 待實裝功能

### 1. 案件應付新增「叫料」欄位 (v70)
**需求**：案件財務應付要包含報價單的叫料，區分已付/未付，用戶可填寫

**實作方案**：
- `caseRecord.materialOrders[]` 新增至 `data_json`
  - 結構：`{itemId, itemName, quantity, unit, unitPrice, totalPrice, paidStatus('pending'|'partial'|'paid'), paidAmount, paidDate, notes}`
  - 已付/未付由用戶填寫（強制欄位）
  
- API 端點：
  - `PATCH /api/quotations/{no}/material-orders` — 新增/編輯/刪除叫料
  - 驗證：不能修改已結案案件的叫料
  
- 前端：案件財務Tab「應付」分頁新增「叫料清單」卡片
  - 新增按鈕 → Modal 填寫叫料資訊
  - 表格顯示：項目名稱、數量、單價、總價、已付狀態、已付金額

**影響範圍**：
- routers/quotations.py — 新增端點
- helpers/quotations.py — 驗證邏輯
- frontend/pages/case-management.html — 新增 UI
- frontend/js/case-management.js — 互動邏輯

---

### 2. 案件資訊新增「專案期間」+ 超期通知 (v71)
**需求**：案件資訊需填寫專案期間（start_date/end_date），超過期限自動送通知每7天提醒

**實作方案**：
- `caseRecord.projectTimeline` 新增至 `data_json`
  - 結構：`{startDate, endDate, status('on_track'|'overdue'|'completed')}`
  - 用戶可編輯（案件未結案時）

- 新增排程任務 `backend/deadline_check_job.py`
  - 每日執行（piggyback 到 `heartbeat_job.py` 或獨立排程）
  - 邏輯：掃描所有未結案案件，檢查 `endDate < today`
  - 超期當天：寄一次信 → superadmin/該案件最高管理員
  - 之後每 7 天：若仍未結案，再寄一次

- 前端：案件資訊分頁「基本資訊」新增「專案期間」卡片
  - 顯示：開始日期、預計結束日期、倒數天數（若未超期）或超期天數

**DB 無改動**（存 data_json），但需新增排程任務

**影響範圍**：
- routers/dev_crm.py — 修改案件資訊編輯邏輯
- backend/deadline_check_job.py — 新檔案
- helpers/email_notify.py — 新增通知模板
- frontend/pages/case-management.html — 新增 UI
- frontend/js/case-management.js — 互動邏輯
- backend/setup_deadline_check_task.ps1 — 新排程腳本（正式機用）

---

## 時間估計
- 叫料欄位：3-4 小時（後端2h + 前端1.5h + 測試0.5h）
- 案件期限：4-5 小時（後端2.5h + 排程1h + 前端1.5h）

**總計**: ~7-9 小時

