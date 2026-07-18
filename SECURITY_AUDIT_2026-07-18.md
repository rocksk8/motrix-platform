# MOTRIX ERP — 全面審查報告

> 審查日期：2026-07-18  
> 審查角度：流程顧問（業務邏輯）+ 系統顧問（技術實作）  
> 基準版本：`4d015b8`（fix: 修復簽核佇列兩個 bug）

---

## P0 — 立即修復（安全 / 資料損毀）

| # | 角色 | 問題描述 | 位置 |
|---|------|---------|------|
| 1 | 系統 | `customers.py` 全部端點未呼叫 `_require_user`，客戶資料（含稅籍、拜訪記錄）完全未認證可讀寫 | `routers/customers.py` |
| 2 | 系統 | `GET /api/quotations/{quote_no}` 未認證，quote_no 格式固定（`MQ-YYYYMM-NNN`）可枚舉，完整報價含成本毛利公開可讀 | `routers/quotations.py:227` |
| 3 | 系統 | `GET /api/devices`、`GET /api/sales-orders`、`GET /api/materials-summary` 未認證，設備 SN/保固/銷售數據公開 | `routers/dashboard.py` |
| 4 | 系統 | `GET /api/next-quote-no` 未認證，外部可呼叫並汙染月序號（每次呼叫均 INSERT quote_seq） | `routers/quotations.py:142` |
| 5 | 流程 | `quotation-form.js` 的 deal-tag PATCH 請求遺漏 `Authorization` header，未登入者可改案件進度 | `frontend/js/quotation-form.js:385` |
| 6 | 流程 | `DELETE /api/quotations/{quote_no}` 無狀態守衛，任何狀態（含已送出、已成案、簽核中）均可被刪除 | `routers/quotations.py:489` |

---

## P1 — 本週修復（業務邏輯錯誤）

| # | 角色 | 問題描述 | 位置 |
|---|------|---------|------|
| 7 | 流程 | 解鎖編輯時 `approval.tiers` 未清除，舊 tiers（含已 approved 人員）殘留，不會從設定重建 | `routers/quotations.py:337` |
| 8 | 流程 | `PATCH /api/quotations/{quote_no}/status` 無狀態機白名單，可直接跳過簽核將草稿設為「已送出」 | `routers/quotations.py:429` |
| 9 | 流程 | `PUT /api/quotations/{quote_no}` 未檢查「已送出」狀態，可繞過解鎖流程直接覆蓋正式報價單 | `routers/quotations.py:387` |
| 10 | 流程 | deal_tag「已結案」可被 admin 直接改回其他狀態（如「已成案」），已完成帳務記錄會錯亂 | `routers/quotations.py:454` |
| 11 | 流程 | settlement `finalized` 後仍可無限次修改，甚至傳入 `{"status":"draft"}` 降回草稿 | `routers/quotations.py:622` |
| 12 | 流程 | `autoSave()` 在 API 回傳前即設 `isDirty = false` 並顯示「已儲存」，API 失敗時資料靜默遺失 | `frontend/js/quotation-form.js:232` |
| 13 | 流程 | `onDealTagChange`：`oldTag` 在 return 之後才 assign，使用者取消「已成案」確認後 select UI 與 model 不同步 | `frontend/js/quotation-form.js:372` |
| 14 | 流程 | 解鎖密碼驗證成功後無「取消解鎖」出口，任何後續手動儲存都會觸發強制送審（`_isUnlockEdit=true` 殘留） | `frontend/js/quotation-form.js:405` |
| 15 | 流程 | 送審前只驗 `customerName`/`projectName`，品項 `description` 空白時仍可送進審核流程 | `frontend/js/quotation-form.js:659` |
| 16 | 系統 | `GET /api/auth/me` 不驗 `expires_at`，session 過期後仍可回傳使用者資訊（在白名單內繞過 middleware） | `routers/auth.py:172` |
| 17 | 系統 | `case-management.js` 的 `selectCase()` 未清除 autoSave timer，切換案件後舊 timer 觸發可用舊資料覆蓋新案件 | `frontend/js/case-management.js:102` |
| 18 | 系統 | `settlement.js finalize()` API 失敗時只還原 `status`，`finalizedAt`/`finalizedBy` 未清空，UI 顯示不一致 | `frontend/js/settlement.js:240` |

---

## P2 — 下週修復（邊界案例）

| # | 角色 | 問題描述 | 位置 |
|---|------|---------|------|
| 19 | 流程 | `mark_payment` 無 optimistic lock，多人同時標記同一筆 payment 有 last-write-wins race condition | `routers/quotations.py:557` |
| 20 | 流程 | 代理送審的 `delegateNote` 後端完全不處理，稽核記錄無法追蹤代理責任 | `routers/quotations.py` 全域 |
| 21 | 流程 | 前端 deal_tag select 未阻擋「已成案」降級，只擋「設置為」未成案/已成案，從已成案往回轉無保護 | `frontend/js/quotation-form.js:362` |
| 22 | 系統 | `_backup_quotation`（即時備份）在 G: 失敗時直接 return，不做本機備份；兩次排程之間新建的單只有 WAL 保護 | `backend/archive.py:228` |
| 23 | 系統 | 登入 rate limiting 使用 in-memory `_rl_state`，服務重啟後清零，可繞過 15 分鐘鎖定 | `routers/auth.py:29` |
| 24 | 系統 | `notif.js` 使用 innerHTML 插入 API 回傳值（`count`），後端若被 compromise 可注入 HTML | `frontend/static/notif.js:161` |
| 25 | 系統 | `submitQuote()`、`saveDraft()`、`approveQuote()` 無防重複提交 flag，快速雙擊可送兩次請求 | `frontend/js/quotation-form.js` |
| 26 | 系統 | 報價清單固定 `limit=500` 無分頁，資料量大時效能惡化，`tabCount()` 每次全量 filter | `frontend/js/quotations.js:144` |

---

## P3 — 品質建議

| # | 問題描述 | 位置 |
|---|---------|------|
| 27 | `archive.py` 的 JSON 備份非原子寫入，崩潰時可能產生損毀的 JSON，建議先寫臨時檔再 `os.replace()` | `backend/archive.py` |
| 28 | `dashboard.js` 的 sparkline 折線圖使用硬編碼假數據，管理者看到的趨勢圖為虛構資料 | `frontend/js/dashboard.js:145` |
| 29 | `list_audit_log` 所有已登入角色（含 viewer）均可讀取完整稽核記錄，應限制 admin+ | `routers/system.py:109` |
| 30 | `work_log` update/delete 無 owner 驗證，任意使用者可修改或刪除他人工作日誌 | `routers/system.py:191` |

---

## 無問題確認清單

| 項目 | 結論 |
|------|------|
| SQL Injection | 全部使用參數化查詢，無實際注入路徑 |
| 密碼雜湊（PBKDF2 260k + salt） | 正常 |
| 強制改密流程（middleware + 前端） | 正常 |
| Session 過期（非 /me 端點） | middleware 正確驗 `expires_at` |
| 簽核人不得自審（no-tiers fallback） | 正常（`requestedBy == username` 有守衛） |
| 退回/拒絕的角色驗證 | 正常（當層 approvers 或 superadmin） |
| Settlement UI finalized 鎖定 | 前端 disabled 正確，後端需補（見 #11） |
| 401 統一導向登入頁 | 各 JS 均有處理 |
| Authorization token 不出現於 URL | 正常（photos `?pt=` 為設計意圖） |
| 備份 SQLite 本機快照（daily/weekly） | 正常，不依賴 G: |
| PDF 生成失敗有 log | `_pdf_audit` + `logger.exception`，無 retry |
| 外鍵約束 `PRAGMA foreign_keys=ON` | 正常 |
| Superadmin 帳號刪除/停用保護 | 正常（`jeff` username 守衛） |
| 解鎖密碼安全性 | 僅 superadmin 可設定/驗證，正常 |

---

## 修復優先排程

| 階段 | 問題編號 | 說明 |
|------|---------|------|
| 立即（今天） | #1–6 | P0：6 個安全漏洞 |
| 本週 | #7–18 | P1：12 個業務邏輯錯誤 |
| 下週 | #19–26 | P2：8 個邊界案例 |
| 下版本 | #27–30 | P3：4 個品質建議 |
