# MOTRIX ERP — 模組：業務開發 CRM（§7.5）

> 自 `MOTRIX-ERP-QUICK.md` 拆出（2026-09-23）。§ 編號沿用原編號，程式註解裡的「QUICK.md §N」依中樞檔的對照表找到本檔。
> 內容逐字搬移，未改寫；相對連結已改為自本目錄起算。

---

### §7.5 · 業務開發 CRM（DB v27；連結報價單審核制 DB v42，見 §12 2026-08-13）

| Method | Path | 說明 |
|--------|------|------|
| GET | /dev-cases | 案件列表（`?q=` 搜尋、`?status=` 篩選；需 dev_crm 模組或 admin+；**非 admin 僅回傳自己建立或指派的案件**）**2026-08-03a**：`?status=` 伺服器端參數仍保留相容，但前端 `dev-crm.html` 已改為抓全量後完全前端篩選（狀態／年／月／逾期），不再送 `status` |
| POST | /dev-cases | 新建案件 |
| GET/PUT/DELETE | /dev-cases/{id} | 單筆操作（DELETE admin+） |
| PATCH | /dev-cases/{id}/status | 變更狀態（洽談中/成案/未成案） |
| PATCH | /dev-cases/{id}/convert | 首次連結報價單號（`{quote_no}`，同時設 status=成案）；**已有連結時回 409**，須改用下列審核流程 |
| POST | /dev-cases/{id}/request-relink-quote | 申請異動／解除已連結的報價單號（admin+；`quote_no` 留空＝申請解除連結，`reason` 選填）→ 送交 superadmin 審核，DB v42 |
| POST | /dev-cases/{id}/cancel-relink-quote | 取消連結異動申請（申請人或 superadmin） |
| POST | /dev-cases/{id}/approve-relink-quote | 審核連結異動（superadmin only；`{approve}`；核准清空時 status 一併退回洽談中） |
| POST | /dev-cases/{id}/request-delete | 申請刪除案件（admin+，設 pending_delete=1，觸發 Email） |
| POST | /dev-cases/{id}/cancel-delete | 取消刪除申請（申請人或 superadmin） |
| POST | /dev-cases/{id}/approve-delete | 審核刪除申請（superadmin only；approve=True→軟刪除+快照，False→拒絕清除旗標） |
| GET/POST | /dev-cases/{id}/logs | 記錄列表 / 新增記錄（log_by≠填單人 → needs_approval=1） |
| PUT/DELETE | /dev-logs/{id} | 編輯／刪除（發文者或 admin+） |
| PATCH | /dev-logs/{id}/approve | 審核記錄（admin+ only） |
| GET | /dev-logs/pending | 待審記錄列表（admin+ only） |
