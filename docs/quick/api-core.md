# MOTRIX ERP — API 速查：共用（§7 總述、§7.1、§7.3、§7.15、§7.21）

> 自 `MOTRIX-ERP-QUICK.md` 拆出（2026-09-23）。§ 編號沿用原編號，程式註解裡的「QUICK.md §N」依中樞檔的對照表找到本檔。
> 內容逐字搬移，未改寫；相對連結已改為自本目錄起算。

---

## §7 · API 速查（base `/api`）

---

### §7.1 · Auth / Users

| Method | Path | 說明 |
|--------|------|------|
| GET | /ping | 心跳 |
| POST | /auth/login | 回傳含 `mustChangePassword`；rate limit 保護；`totp_enabled` 時改回傳 `{totpRequired,challengeToken}`，不核發 session，見 §3.3b |
| POST | /auth/login/totp | 登入第二階段：`{challenge_token, code}`，`code` 為 6 位數 TOTP 或救援碼；白名單路徑（無 Bearer） |
| GET | /auth/totp/status | 目前使用者是否已啟用 TOTP（需登入）；2026-09-11 新增 `recoveryCodesRemaining` 剩餘救援碼組數（只回組數、不回內容——DB 只存雜湊，明文從一開始就只在產生當下出現一次） |
| POST | /auth/totp/setup | 產生新密鑰＋QR code（需登入，任何角色） |
| POST | /auth/totp/enable | `{code}` 驗證後才真正啟用，回傳 10 組一次性救援碼（僅此次可見明文） |
| POST | /auth/totp/recovery-codes/regenerate | 重新產生 10 組救援碼（2026-09-11）；需 `{password}`（比照 disable 的敏感操作慣例，**不**再要驗證碼——會用這支的情境正是驗證 App 拿不到）；**整組換掉、舊碼全數失效**（非「補足到 10 組」，避免舊清單變成「某幾組還有效但不知道哪幾組」）；未啟用 TOTP 時回 400 |
| POST | /auth/totp/disable | `{password}` 確認身分後停用 |
| POST | /auth/logout | |
| GET | /auth/me | 含 `mustChangePassword`；驗 `expires_at` |
| PATCH | /auth/change-password | ≥8；清除強制改密 |
| POST | /auth/verify-unlock | superadmin 解鎖驗證 |
| GET/POST | /users | 列表／新增 |
| PUT/DELETE | /users/{id} | |
| PATCH | /users/{id}/active | |
| PATCH | /users/{id}/unlock-password | ≥8 |

---

### §7.3 · 主檔 / 專案 / 報表 / 系統

| Method | Path | 說明 |
|--------|------|------|
| CRUD | /customers · /suppliers · /parts | 供應商列表 admin+ 才有資料；需認證 |
| GET | /customers/{id} | 單一客戶詳情（含 contacts/address） |
| PATCH | /customers/{id}/visits · /suppliers/{id}/visits | 樂觀鎖 |
| GET | /company/tax/{id} · /company/search | GCIS Proxy |
| CRUD | /projects · logs · photos | |
| GET | /photo-token?path= | 取得 1h signed token |
| GET | /uploads/{path}?pt= | 照片（優先 `?pt=`；fallback `?token=`） |
| GET | /dashboard/stats · /monthly | 需認證 |
| GET | /devices · /receivables | 需認證 |
| GET | /reports/financial · /excel · /pdf | admin+ |
| GET/PUT | /settings/approval-flow | 統一簽核流程（`unified_approval_flow`），PUT 限 superadmin |
| GET/PUT | /settings/approval-flow-scope | 五種文件類型套用範圍（統一／獨立），PUT 限 superadmin，2026-08-28 |
| GET/PUT | /settings/approval-flow/{doc_type} | 該文件類型自己獨立的簽核設定（`{doc_type}_approval_flow`），doc_type ∈ quotation/shipping/invoice_voucher/payment_request/contractor_voucher，PUT 限 superadmin，2026-08-28 |
| GET/PUT | /settings/cloud-backup-target | 雲端備份目標（`local_drive`／`s3`），PUT 限 superadmin，見 §8.0，2026-09-07 |
| GET/PATCH | /notifications/* | |
| GET | /audit-log | **admin+ only**；viewer/sales/engineer → 403 |
| GET | /online-users | **限 superadmin**：目前在線成員與人數（5 分鐘內有活動，資料源 `sessions.last_active`，不另做心跳） |
| GET | /user-activity?start&end | **限 superadmin**：每位成員的活躍時數統計（DB v79 `user_activity_daily`）。**是活躍時間不是登入時長** |
| GET | /user-activity/trail?user&start&end&limit&before_id | **限 superadmin**：逐條操作軌跡（DB v80 `user_request_log`）。每筆帶 `summary`（一句人話）／`kind`／`resultLabel`／`pageLabel`／`repeat`，翻譯規則在 `trail.py`。頁面自動發的請求不記、一次點擊的連鎖請求算一次、保留 90 天 |
| POST | /edit-presence | 回報「我在編這份文件」並取回還有誰在編（`{doc_type, doc_id}`，任何登入者）；TTL 90 秒 |
| DELETE | /edit-presence | 離開編輯畫面時釋放（選用，不送也會自然過期） |
| GET/POST/PUT/DELETE | /work-logs | PUT/DELETE 非 admin 只能操作自己的 |
| GET/POST | /settings/custom-roles | 列表／新建自訂角色（POST 需 superadmin） |
| PUT/DELETE | /settings/custom-roles/{rid} | 更新／刪除（superadmin only） |
| GET | /settings/role-labels | 各角色層顯示名稱（需認證） |
| PUT | /settings/role-labels | 更新角色顯示名稱（superadmin only） |
| GET | /settings/payment-terms | 報價單「付款條件」預設文字（需認證；未設定過時回傳程式內建範本） |
| PUT | /settings/payment-terms | 更新預設文字（superadmin only） |
| GET | /system/schema-status | Schema／migration 唯讀診斷（superadmin only）；回傳目前版本、目標版本、`upToDate`、`lastAppliedAt`、完整 migration 清單 |

---

### §7.15 · 個人化清單偏好（DB v56）

| Method | Path | 說明 |
|--------|------|------|
| GET | /list-prefs/{list_key} | 讀取使用者個人清單偏好（欄位顯示/排序記憶） |
| PUT | /list-prefs/{list_key} | 更新 |

---

### §7.21 · 單據存檔版本與編輯紀錄（2026-09-14，DB 無異動）

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/api/quotations/{no}/versions` | 回 `{versions, history}` 兩條時間軸 |
| GET | `/api/quotations/{no}/versions/{seq}/download` | 下載該版本的**原始存檔 PDF**（不重新產生） |

- `versions` 來自 `data_json.docVersions[]`（由 `pdf_gen._record_doc_version()` 在 PDF 存檔成功後寫入），
  每筆含 `seq`／`at`／`event`（建立／修改／簽核／已簽核／結案）／`by`／`size`／`filename`／`available`。
- `available` 標示實體檔案現在還在不在——PDF 存檔目錄是 superadmin 可設定的路徑，可能被搬移或清理。
  **索引還在但檔案沒了要誠實標示**，不能讓人點下去才發現。
- `history` 就是 `data_json.editHistory`，`type` 有四種：`quote_update`（一般編輯，2026-09-14 新增）／
  `quote_edit`（解鎖編輯）／`settlement_finalized`／`settlement_draft`。
- 兩條時間軸**刻意不合併**：PDF 是完整快照（可以拿去對帳、給客戶看），編輯紀錄是欄位層級索引。
  硬合成一條會讓人以為每一筆編輯紀錄背後都有對應的 PDF，那不成立——一般編輯不產 PDF。
- 權限走 `_guard_case(..., allow_approver=True)`；下載端點另驗路徑不得越出 PDF base
  （比照 `routers/uploads.py::_resolve_upload_path()` 的既有慣例）。
