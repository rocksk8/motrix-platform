# MOTRIX ERP — 開發快速參考

> 允碩整合集創（統編 60575481）｜ Tel: 04-3602-2818 ｜ info@miactw.com  
> 文件版本：**2026-07-22k**（全面更新：死碼清除 + 驗收流程 + Git Flow）

---

<!-- ╔══════════════════════════════════════════╗
     ║  目錄（§ 段落快速跳轉）                   ║
     ╚══════════════════════════════════════════╝

  §1  啟動與位址           §8  備份與還原
  §2  系統架構總覽          §9  前端規範
  §3  安全                 §10 成本公式
  §4  資料模型             §11 已知限制
  §5  核心業務流程          §12 變更摘要
  §6  Sidebar 結構         §13 目錄結構
  §7  API 速查
-->

---

## §1 · 啟動與位址

| 項目 | 值 |
|------|-----|
| 開發啟動 | `backend\start.bat` |
| 更新後重啟 | `backend\restart.bat` |
| 本機 | http://localhost:666 |
| 區網 | http://172.16.11.211:666 |
| SQLite | `backend\motrix_erp.db`（WAL 模式） |

```
依賴關係：
  db.py ← helpers/ ← archive.py / pdf_gen.py / photos.py
                   ← routers/*.py ← main.py（wiring only）
```

**新增功能規則**

- API → 對應 `routers/xxx.py`，勿塞進 `main.py`
- 共用邏輯 → `helpers/`（拆 6 個子模組）
- 表結構 → `db.py:init_db()` + `_mNNN_xxx()` migration
- 備份 → `archive.py`（所有 JSON 寫入須用 `_atomic_json_write()`）
- PDF → `pdf_gen.py`；照片水印 → `photos.py`（PIL 可選）

---

## §2 · 系統架構總覽

```
┌──────────── Frontend (Alpine.js + 靜態 HTML) ────────────┐
│  pages/*  +  js/*  +  static/sidebar.js / notif.js       │
│  Session: localStorage.motrix_session (Bearer token)     │
└──────────────────────┬───────────────────────────────────┘
                       │ HTTP :666
┌──────────────────────▼───────────────────────────────────┐
│  FastAPI main.py                                         │
│  middleware: auth · must_change_password · security hdr  │
│  routers: auth / quotations / customers / suppliers /    │
│           parts / projects / dashboard / system / reports│
└──────────────────────┬───────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   SQLite (WAL)   Edge PDF      G: 雲端 + 本機快照
   motrix_erp.db  pdf_gen.py    archive.py
```

### 後端模組

| 模組 | 職責 |
|------|------|
| `db.py` | 連線、`init_db()`、PRAGMA WAL、熱路徑欄位／索引；**CURRENT_VERSION=25**（25 個 migrations） |
| `helpers/` | 密碼、session、audit、notify、settings、弱密碼標記、`save_quotation_json()` |
| `archive.py` | 即時／每日／週備份；本機 SQLite 快照；**原子 JSON 寫入**（`_atomic_json_write`）；G: fallback |
| `backup_job.py` | 獨立備份腳本（Windows 工作排程器，不依賴 server） |
| `pdf_gen.py` | Edge Headless PDF；路徑讀 `system_settings["pdf_base_path"]` |
| `photos.py` | 專案照片水印 |
| `routers/*` | 業務 API |
| `main.py` | CORS、middleware、全域 Exception Handler、startup、static |

### 前端

| 路徑 | 說明 |
|------|------|
| `frontend/js/case-management.js` | 案件管理 Alpine 元件（唯一有效的外置 JS） |
| `frontend/js/reports.js` | 營運報表 Alpine 元件（唯一有效的外置 JS） |
| `frontend/pages/quotation-form.html` | ⚠️ Alpine function **inline**（邏輯在 `<script>` 內，勿找外置 JS） |
| `frontend/pages/settlement.html` | ⚠️ Alpine function **inline**（邏輯在 `<script>` 內，勿找外置 JS） |
| `frontend/pages/*.html` | 其餘頁面 Alpine 亦均為 inline，**無對應外置 .js** |
| `frontend/static/sidebar.js` | Topbar + Sidebar 注入；**強制改密導向**；離開警示 `bindNavGuard()` |
| `frontend/static/notif.js` | 通知 Bell；所有動態內容用 **DOM API**（無 innerHTML） |
| `frontend/css/style.css` | CSS 變數：`--sidebar-w` `--topbar-h` `--accent` |

> **重要**：`frontend/js/` 目錄**僅存 2 個有效檔案**（case-management.js / reports.js），
> 其餘 21 個死碼 JS 已於 2026-07-22 清除。勿在此目錄新增非必要的 JS 檔案。

---

## §3 · 安全（2026-07-18 強化後）

### §3.1 · 帳號與密碼

| 規則 | 說明 |
|------|------|
| **禁止明文密碼寫入文件／UI** | 歷史預設已移除 |
| 密碼長度 | ≥ **8**；拒絕已知弱密碼 |
| 雜湊 | PBKDF2-SHA256（260k）；舊 sha256 登入時升級 |
| 新建使用者 | 一律 PBKDF2；`must_change_password=1` |
| 管理員重設密碼 | 同樣標記強制改密 |
| 全新安裝 `jeff` | 隨機臨時密碼 → `backend/.initial_admin_credentials.txt`（用後刪） |
| 既有弱密碼 | 啟動 `flag_weak_passwords()` 標記；登入後強制改密 |

**強制改密流程**

```
登入 → mustChangePassword=true
  → 前端導向 change-password.html?forced=1
  → middleware 僅放行：/api/auth/me · change-password · logout · ping
  → 改密成功 → must_change_password=0 → 重新登入
```

### §3.2 · 解鎖密碼（報價單解鎖編輯）

- 僅 superadmin；與登入密碼獨立
- **不再自動寫入共用預設**
- 啟動若偵測歷史弱預設 → **清空 hash**，需至使用者管理重新設定
- 未設定：`POST /api/auth/verify-unlock` 回錯誤提示先設定
- 解鎖成功後：顯示「取消解鎖」按鈕（`cancelUnlock()`），防止意外觸發重送審

### §3.3 · Session 與 API 保護

| 項目 | 值 |
|------|-----|
| Session | `sessions` 表，預設 30 天；`expires_at` 中介層 + `/auth/me` 雙重驗證 |
| 白名單 | `/api/ping` · `/api/auth/login` · `/api/auth/logout` |
| 其餘 `/api/**` | 需 `Authorization: Bearer {token}` |
| 回應標頭 | `X-Content-Type-Options` · `X-Frame-Options` · `Referrer-Policy` |
| **登入暴力破解** | per-IP rate limiting；5 次失敗鎖 15 分鐘；HTTP 429 含倒數；**鎖定狀態持久化** `login_rate_limit` 表（DB v11），重啟不失效 |

### §3.4 · 角色與模組

```
superadmin > admin > sales > engineer > viewer
```

| 角色重點 | 說明 |
|----------|------|
| `engineer` | 預設無 `financial_view`，不可看金額／財務 |
| 模組例 | `project_manage` · `project_approve_eng` · `project_approve_biz` · `financial_view` · `reports` · `work_log` · `daily_task` |
| 報價列表過濾 | 非 admin+ 用 `sales_person_id=自己id OR (sales_person_id IS NULL AND sales_person=display_name)` |
| **稽核記錄** | `GET /api/audit-log` 限 **admin+**；viewer/sales/engineer 呼叫回 403 |
| **工作日誌** | `PUT/DELETE /api/work-logs/{id}`：非 admin 只能修改/刪除**自己**的日誌 |
| **自訂角色** | superadmin 可建立自訂角色（名稱 + 基礎角色層 + 模組清單）；儲存於 `system_settings`；使用者 Modal 快速套用 chips 顯示 |
| **角色名稱** | superadmin 可在「角色名稱設定」自訂各層顯示名稱（`GET/PUT /api/settings/role-labels`）；DB 內 `role` 欄位仍儲存系統名稱 |

---

## §4 · 資料模型

### §4.1 · 主要資料表

```sql
quotations      -- 熱路徑欄位 + data_json 完整物件
  quote_no PK, status, deal_tag, settle_status,
  customer_name, project_name, total, pretax,
  direct_margin_pct, net_margin_pct,
  sales_person (顯示名稱，歷史相容), sales_person_id FK→users.id,
  quote_date, valid_days, data_json, created_at, updated_at, ...

users           -- + must_change_password, unlock_password_hash, daily_task_pw_hash
sessions        -- token, expires_at, last_active
customers       -- code(C-YYYYMM-NNN) + 主欄 + data_json（contacts, visits, tags）
suppliers       -- code(S-YYYYMM-NNN) + 主欄 + data_json
parts, projects, project_logs
system_settings, audit_log, notifications
quote_seq       -- 月序 MQ-YYYYMM-NNN
login_rate_limit -- ip PK, locked_until（服務重啟後維持鎖定）
module_versions  -- 模組版本紀錄（同步自 version_manifest.json）
daily_tasks / daily_task_completions / daily_task_edit_log

vendor_contractors   -- code(V-YYYYMM-NNN), name, tax_id, contact, data_json(visits/tags/category)
contractor_dispatches -- quote_no, vendor_id, status, items_json, total_amount, tax_rate,
                         accepted_at, accepted_by（DB v25）
```

**索引**：`deal_tag` · `settle_status` · `sales_person` · `sales_person_id`

### §4.2 · data_json 與熱路徑同步

- 巢狀結構（品項、簽核、案件、精算）仍在 `data_json`
- **`deal_tag` / `settle_status` 為正規欄位**，列表／報表／儀表板優先讀欄位
- 寫入統一走 `helpers.save_quotation_json()`（自動同步欄位 + `updated_at`）
- 讀取相容：`SQL_DEAL_TAG` / `SQL_SETTLE_STATUS`（欄位為空時 fallback `json_extract`）

```
create / put / deal-tag / settlement / payment / case-record / approve / reject
  → save_quotation_json() 或同等步邏輯
```

### §4.3 · 樂觀鎖（併發保護）

| 端點 | 欄位 | 行為 |
|------|------|------|
| `PATCH .../case-record` | `_expectedUpdatedAt` | 不符 → **409** |
| `PATCH .../customers/{id}/visits` | `expectedUpdatedAt` | 不符 → **409** |
| `PATCH .../suppliers/{id}/visits` | 同上 | 不符 → **409** |
| `PATCH .../vendor-contractors/{id}/visits` | `expectedUpdatedAt` | 不符 → **409** |
| `PATCH .../payment/{idx}` | `_expectedUpdatedAt` | 不符 → **409** |

回傳皆含 `updated_at`，前端可回寫後再送。

---

## §5 · 核心業務流程

### §5.1 · 報價狀態機

```
草稿 → 待審核（送出）→ 已送出（簽核完成）
         ↑ 解鎖編輯儲存後強制回到待審核
```

- 單號：`MQ-YYYYMM-NNN`（`/api/next-quote-no`）
- 僅**草稿**可刪；其他狀態回 403
- **已送出**預設鎖定；superadmin 解鎖密碼後可改，儲存後重鎖並重送審
- 送出前驗證：`customerName` + `projectName` + **至少一項品項說明**不得空白
- 防重複送出：`submitting` flag，按鈕期間不可再觸發

### §5.2 · 案件進度 dealTag

```
未提供 → 已提供 → 未成案
                 → 已成案（確認後 UI 鎖定）
                 → 已結案（僅案件管理「完結案」）
```

- 欄位同步：`quotations.deal_tag`
- 日誌：`data_json.statusLog[]`；**`delegateNote` 寫入 audit_log**
- **未成案 / 已成案**（設為）：限 admin+ 操作
- **已成案 → 其他（降級）**：限 **admin+**（前後端雙重 guard）
- **已結案 → 其他**：限 **superadmin**
- UI revert：取消確認時用 `$nextTick` 回滾 `_prevDealTag`

### §5.2b · 報價清單動態徽章（quotations.html）

`dealDisplayStatus(q)` 回傳 `{text, cls}`，依 `status + deal_tag` 組合：

| status | deal_tag | text | cls |
|--------|----------|------|-----|
| 草稿 | — | 草稿 | badge--draft |
| 待審核 | — | 審核中 | badge--pending |
| 簽核中 | — | 簽核中 | badge--signing |
| 已核准 | — | 已核准 | badge--approved |
| 已取消 | — | 已取消 | badge--danger |
| 已拒絕 | — | 已退回 | badge--rejected |
| 已送出/已確認 | 未提供/已提供 | 報價中 | badge--sent |
| 已送出/已確認 | 已提供 | 待決定 | badge--sent |
| 已送出/已確認 | 已成案 | 執行中 | badge--running |
| 已送出/已確認 | 未成案 | 未成案 | badge--lost |
| 已送出/已確認 | 已結案 | 已結案 | badge--settled |

### §5.2c · 報價單 PDF 匯出

**工具列按鈕邏輯**（三擇一顯示）：

| 條件 | 按鈕 | 說明 |
|------|------|------|
| `!q.quoteNo`（新增未儲存） | 預覽報價單（neutral） | 讓使用者確認版型格式 |
| `q.dealTag === '未成案'` | 預覽報價單（紅色） | 禁止匯出 |
| 其餘已儲存且非未成案 | 匯出 PDF（`directExport()`） | 系統後端產生，瀏覽器直接下載 |

管理員另有 **匯出次數** 獨立按鈕（`showExportLog()`，僅 admin+）。

### §5.3 · 簽核（tiers 並行層）

```
設定：system_settings.approval_flow → { tiers:[{order, approvers:[]}] }
送出：快照至 data_json.approval.tiers[]
規則：同層全員 approved → currentTier++；末層完成 → status=已送出 + PDF
退回：清除 approval，status=草稿
舊 steps[]：執行期動態轉 tiers
```

- 有流程：允許自簽（比對當層 username）
- 無流程（預設超管）：**禁止申請人自簽**
- 代理送審：`approval.delegateSubmitter` + `delegateNote` 同步寫入 audit_log

### §5.4 · 案件管理三主 Tab

| Tab | 內容 |
|-----|------|
| 商務 | 合約資訊 + 收款管理（%／含稅／未稅雙向） |
| 執行 | 進度 / 叫料 / 設備 / 保固備注 |
| 財務 | KPI + 精算結果（需 `canSeeFinancial`） |

### §5.5 · 成本精算 settlement

- 入口：已成案／已結案 → `settlement.html?no=`
- 存於 `data_json.settlement`；欄位 `settle_status` = `draft` \| `finalized`
- 每次儲存寫入 `editHistory[]`
- `finalized` 後：非 superadmin 不可再修改；API 失敗時**完整回滾** status + finalizedAt + finalizedBy

### §5.6 · 專案

- `projects` + `project_logs`；與報價 M:N（`linked_cases`）
- 確認事項兩階段：`project_approve_eng` → `project_approve_biz`
- 照片：Pillow 水印 + GPS EXIF → `uploads/projects/...`

### §5.7 · 承攬商派發狀態機

```
草稿(draft) → 已送出(sent) → 已確認(confirmed)
                                   ↓
                              待驗收(pending_acceptance)   ← 快速按鈕：「待驗收」
                                   ↓
                              已驗收(accepted)             ← 快速按鈕：「✓ 確認驗收」
                                   ↓                         記錄 accepted_by + accepted_at
                              完工(completed)

任意非終態 → 已取消(cancelled)
```

- 狀態轉換：`PATCH /api/contractor-dispatches/{id}/accept`（`action=pending_acceptance` 或 `action=accepted`）
- 流程違規（如跳過待驗收直接已驗收）→ **409**
- 已驗收後：卡片底部顯示綠色橫條，含驗收人姓名 + 時間
- 狀態亦可透過 Modal 下拉直接設定（彈性操作，不走 `/accept` endpoint）

---

## §6 · Sidebar 結構

```
主選單     儀表板
業務       報價單（含簽核佇列 ?view=queue） / 案件管理 / 專案管理
廠商與採購 客戶 / 供應商 / **承攬商** / 料號 / 採購
設備       設備登載 / 保固追蹤
財務       應收帳款 / 營運報表（admin+ 或含 reports 模組）
工作       工作日誌（非 viewer 或含 work_log 模組） / 每日工作事項（非 viewer 或含 daily_task 模組）
系統       使用者 / 簽核設定（superadmin）/ 歷史紀錄
```

- 簽核佇列不在 sidebar，在報價單內 tab
- 銷售訂單已移除（併入案件財務）
- `reports`：`admin+` 或含 `reports` 模組的使用者可見
- `work_log` / `daily_task`：非 viewer 或明確帶對應模組者可見（相容既有帳號）
- `承攬商管理`：`admin+`（`cPr` 旗標，同採購）可見；`vendor-contractors.html`

---

## §7 · API 速查（base `/api`）

### §7.1 · Auth / Users

| Method | Path | 說明 |
|--------|------|------|
| GET | /ping | 心跳 |
| POST | /auth/login | 回傳含 `mustChangePassword`；rate limit 保護 |
| POST | /auth/logout | |
| GET | /auth/me | 含 `mustChangePassword`；驗 `expires_at` |
| PATCH | /auth/change-password | ≥8；清除強制改密 |
| POST | /auth/verify-unlock | superadmin 解鎖驗證 |
| GET/POST | /users | 列表／新增 |
| PUT/DELETE | /users/{id} | |
| PATCH | /users/{id}/active | |
| PATCH | /users/{id}/unlock-password | ≥8 |

### §7.2 · 報價 / 簽核 / 精算

| Method | Path | 說明 |
|--------|------|------|
| GET | /next-quote-no | 認證必填 |
| GET/POST | /quotations | 列表（角色過濾）／建立 |
| GET/PUT/DELETE | /quotations/{no} | DELETE 僅草稿；PUT 鎖定狀態需解鎖 |
| PATCH | /quotations/{no}/status | superadmin + 白名單狀態 |
| PATCH | /quotations/{no}/deal-tag | 同步 `deal_tag`；已成案降級需 admin+；已結案需 superadmin |
| PATCH | /quotations/{no}/case-record | 樂觀鎖 `_expectedUpdatedAt` → 409 |
| PATCH | /quotations/{no}/payment/{idx} | 收款標記；樂觀鎖 `_expectedUpdatedAt` → 409 |
| GET/PUT | /quotations/{no}/settlement | 精算；finalized 後非 superadmin 不可改 |
| GET | /quotations/{no}/pdf-download | Edge PDF |
| POST | /quotations/{no}/export | 記錄匯出人/時間 |
| GET | /approval-queue | 認證必填 |
| POST | /quotations/{no}/approve \| reject | 並行層簽核 |

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
| GET/PUT | /settings/approval-flow | |
| GET/PATCH | /notifications/* | |
| GET | /audit-log | **admin+ only**；viewer/sales/engineer → 403 |
| GET/POST/PUT/DELETE | /work-logs | PUT/DELETE 非 admin 只能操作自己的 |
| GET/POST | /settings/custom-roles | 列表／新建自訂角色（POST 需 superadmin） |
| PUT/DELETE | /settings/custom-roles/{rid} | 更新／刪除（superadmin only） |
| GET | /settings/role-labels | 各角色層顯示名稱（需認證） |
| PUT | /settings/role-labels | 更新角色顯示名稱（superadmin only） |

### §7.4 · 承攬商管理（DB v22–v25）

| Method | Path | 說明 |
|--------|------|------|
| GET | /vendor-contractors | 承攬商列表（admin+；`?q=` 搜尋 name/tax_id/phone/contact、`?active_only=` 篩選） |
| POST | /vendor-contractors | 新建承攬商（admin+；`data{}` 存 category/tags/notes/visits） |
| GET | /vendor-contractors/selectable | 輕量下拉（需認證，非 admin 亦可；供案件管理下拉） |
| GET/PUT | /vendor-contractors/{id} | 單筆查詢／更新（PUT admin+；PUT 合併 data_json 保留 visits） |
| DELETE | /vendor-contractors/{id} | 刪除（有派發紀錄 → 409，建議改停用） |
| PATCH | /vendor-contractors/{id}/active | 停用／啟用切換（admin+） |
| PATCH | /vendor-contractors/{id}/visits | 往來紀錄更新（樂觀鎖 `expectedUpdatedAt` → 409） |
| GET | /contractor-dispatches | 派發列表（`?quote_no=` 過濾；無參數返回最新 200 筆） |
| POST | /contractor-dispatches | 新建派發（需認證；自動計算 total_amount） |
| GET/PUT/DELETE | /contractor-dispatches/{id} | 單筆操作（DELETE admin+） |
| PATCH | /contractor-dispatches/{id}/accept | 驗收流程：`action=pending_acceptance`（draft/sent/confirmed→待驗收）或 `action=accepted`（待驗收→已驗收，記錄 accepted_by/accepted_at）；違規轉換 → 409 |
| POST | /contractor-dispatches/{id}/import-to-quote | 回推品項至報價單 `items[]`（報價單非草稿 → 409） |

---

## §8 · 備份與還原

### §8.1 · 路徑

```
雲端（需 G: 掛載）
  G:\我的雲端硬碟\系統存檔\
    即時備份\報價單|客戶|供應商\
    每日備份\YYYY-MM-DD\  （JSON 七表 + motrix_erp.db）
    週備份\YYYY-WNN\

本機（不依賴 G:，務必保留）
  backend\db_backups\YYYY-MM-DD\motrix_erp.db   ← SQLite Online Backup，保留 30 天
  backend\db_backups\quotation_instant\          ← G: 不可用時的即時報價單 JSON fallback
  backup_alerts\BACKUP_ALERT.txt                ← 雲端異常醒目警示
  backup_alerts\YYYY-MM-DD.log
```

### §8.2 · 排程架構（雙層）

| 層 | 機制 | 觸發時間 | 說明 |
|----|------|---------|------|
| **主**（可靠） | Windows 工作排程器 | 每日 02:00 | `backup_job.py`；server crash 也跑；開機後補執行 |
| **冗餘** | `threading.Timer` | 每 2h 日備；每 6h 週備 | server 在線時提供即時觸發 |

`.done` marker 確保同日/週不重複備份。設定：`setup_backup_task.ps1`（初次部署執行一次）。

### §8.3 · 行為

| 條件 | 行為 |
|------|------|
| G: 正常 | 即時 JSON（**原子寫入**）+ 每日 JSON + 雲端 DB 副本 + 本機快照 |
| G: 未掛載 — 即時備份 | 寫至 `db_backups/quotation_instant/{no}.json`（本機 fallback） |
| G: 未掛載 — 排程備份 | 寫 `BACKUP_ALERT.txt` + audit `backup.alert`；**仍做本機 SQLite 快照** |
| 恢復正常 | 清除 sticky 警示檔 |
| Server crash | Task Scheduler 仍在 02:00 執行本機快照 |

**原子寫入**：所有 JSON 備份均先寫 `.tmp` 再 `os.replace()`，崩潰時不產生損毀檔。

Audit：`backup.daily_ok` · `backup.weekly_ok` · `backup.sqlite_snapshot` · `backup.alert`

**audit_log 保留**：每次每日備份後執行 `_prune_audit_log(keep_days=730)`，自動刪除 2 年前舊紀錄（先備後刪，雲端 JSON 永久保存）。

**還原優先序**：本機 `db_backups` 整庫 → 雲端 `motrix_erp.db` → JSON 重建（最後手段）

---

## §9 · 前端規範

| 項目 | 做法 |
|------|------|
| 框架 | Alpine.js CDN |
| JS | `frontend/js/{page}.js`（非 defer，先於 Alpine） |
| Auth | `init()` 讀 session；無 token → login |
| 強制改密 | session.mustChangePassword 或 sidebar 導向 |
| API | `Authorization: Bearer {token}`，**PATCH deal-tag 不可遺漏** |
| 自動存 | debounce 1.5s（`setDirty`）；`isDirty=false` 需在 API 成功回調內設定 |
| 客戶選公司 | `selectCustomer()` async；每次選擇都 `GET /api/customers/{id}`，**強制覆寫**聯絡人欄位 |
| No-cache | `.html` / `.css` / `.js` 皆 no-store |
| Excel | SheetJS CDN（客戶／供應商） |
| XSS 防護 | 動態插入 API 資料一律用 DOM API，**禁止 innerHTML 插入非靜態內容** |

---

## §10 · 成本公式（報價）

```
售價 = CEILING(成本 × 1.05 / (1 − 毛利率), 5)
管銷分攤 = 稅前售價 × 10%
公益捐款 = 直接毛利 × 1%
```

`FORM_VERSION`：模板版號常數（如 V1.1），與單筆資料無關；改版型時手動遞增。

---

## §11 · 已知限制與後續建議

| 優先 | 項目 |
|------|------|
| 🔴 | 區網 HTTPS／反向代理（Nginx + mkcert，Bearer Token 目前區網明文） |
| ✅ | ~~死碼 JS 清除~~（21 個死碼 .js 已刪，`frontend/js/` 僅剩 2 個有效檔） |
| ✅ | ~~關鍵 API 自動化測試~~（48 tests 全通過，`backend/tests/test_core.py`） |
| ✅ | ~~文件拆 `CHANGELOG.md` 與本速查分離~~（已完成，見根目錄 `CHANGELOG.md`） |
| ✅ | ~~Git Flow 分支規則~~（`develop` 分支 + `GITFLOW.md` 規範已建立） |
| 低 | SQLite → PostgreSQL（資料量 > 1 GB 或同時連線數 > 5 時評估） |

---

## §12 · 變更摘要（最新兩版）

> 完整版本歷史請見 [`CHANGELOG.md`](CHANGELOG.md)（根目錄）

### 2026-07-22k — 文件全面更新（本次 session 整合）

- **§2 前端表**：更新為 `js/` 目錄僅剩 2 個有效檔說明；移除已刪除的 `quotation-form.js` / `settlement.js` 死碼警告
- **§4.1 資料表**：補入 `vendor_contractors` / `contractor_dispatches`（含 accepted_at/by）；修正 `db.py` 版本標示 v11 → v25；補入 `module_versions` / `daily_task*` 等表
- **§4.3 樂觀鎖**：補入承攜商往來紀錄端點
- **§5.7**：新增承攬商派發狀態機說明
- **§7.4**：標題更新為 `DB v22–v25`
- **§11**：標記 ✅ 死碼清除 / ✅ Git Flow；補入 HTTPS 為 🔴 高優先；新增 SQLite 擴展建議
- **§13**：目錄結構全面更新（CURRENT_VERSION=25、GITFLOW.md、版本 manifest、tests/、刪除死碼、承攬商頁面）
- **Git Flow**：`develop` 分支建立 + `GITFLOW.md` 規範文件
- **死碼清除**：21 個死碼 JS 正式 git commit 刪除（commit `fbbbbda`）

### 2026-07-22j — 承攬商驗收流程節點

- **DB migration v25**：`contractor_dispatches` 新增 `accepted_at TEXT` / `accepted_by TEXT`
- **新端點 `PATCH /api/contractor-dispatches/{id}/accept`**：`action=pending_acceptance`（可由 draft/sent/confirmed 觸發）/ `action=accepted`（限由 pending_acceptance 觸發，記錄驗收人姓名+時間）；流程不合規回 409 含說明文字
- **狀態流**：`草稿 → 已送出 → 已確認 → 待驗收 → 已驗收 → 完工`（已取消可由任意非終態觸發）
- **前端**：dispatch 卡片依狀態顯示「待驗收」（綠框）/ 「✓ 確認驗收」（綠底）快速按鈕；已驗收後底部顯示綠色驗收人+時間橫條；Modal 狀態下拉補入兩個新選項；`case-management.js` 新增 `markPendingAcceptance()` / `acceptDispatch()` 方法

### 2026-07-22i — 實體編號系統 + 日曆回報自動展開

- **DB migration v24（`db.py`）**：`customers`/`suppliers`/`vendor_contractors` 新增 `code TEXT NOT NULL DEFAULT ''`；以 `created_at` 月份分組、`id` 順序回填既有資料（格式 `C-YYYYMM-NNN`/`S-`/`V-`）；建立 UNIQUE partial index（`WHERE code != ''`）；新增 `next_entity_code(conn,table,prefix)` helper
- **後端三路由**：`create_customer`/`create_supplier`/`create_vendor_contractor` 建立後自動生成 code 並回傳；GET list/detail 均含 `code` 欄位；承攬商伺服端搜尋加入 `code LIKE ?`
- **前端三頁面**：列表 name 欄下方顯示 code 徽章（灰底/承攬商紫底）；詳細面板 header 同步顯示；前端搜尋 filter 加入 code 比對
- **日曆模式切換卡片自動展開回報（`daily-tasks.html`）**：點擊任務卡片時，若當前使用者為指派對象且尚未回報，自動設定 `calEditTaskId=task.id` 展開填寫表單，無需再手動點「提交回報」

### 2026-07-22h — 日曆回報修正 + 信件按鈕 + 統編查詢錯誤分類

- **日曆模式回報表單（`daily-tasks.html`）**：切換工作事項卡片後仍無法輸入回報的根因為 Alpine.js 巢狀 `x-if` 在外層條件持續 truthy 時不重建內層 DOM；全改為 `x-show` 常駐 DOM，切換卡片後「提交回報」按鈕與 textarea 即時顯示並可操作
- **信件按鈕對比度（`email_notify.py`）**：`.btn` 顏色改為 `#1D4ED8`；`color:#ffffff !important`；所有 `<a class="btn">` 補 `style="..."` inline 屬性，防止 Gmail 等覆蓋連結字色，共修正 4 處
- **統編查詢錯誤分類（`dashboard.py` + 三個前端頁面）**：`_gcis_get` 新增 `(data, status)` 回傳格式，區分 `not_found`/`network_error`；連線失敗回 HTTP 503；客戶／供應商／承攬商頁面分別加入 503 提示「政府資料庫連線失敗，請確認伺服器對外網路」；加入 `User-Agent` 標頭與 `logger.warning` 記錄

### 2026-07-22g — 業務員績效欄位對齊修正

- **CSS specificity 衝突修復**：`reports.html` 內 `.data-table th { text-align:left }` specificity `(0,1,1)` 壓過 `.r { text-align:right }` 的 `(0,1,0)`，導致所有 `<th class="r">` 標題被強制靠左，但 `<td class="r">` 資料靠右，業務員績效（7/8 欄均為數字）視覺錯位最為明顯；新增 `.data-table th.r { text-align:right }` 與 `.data-table th.c { text-align:center }`（specificity `(0,2,1)`），全頁數字欄位標題對齊一次修正
- **業務員績效 Tab 結構簡化**：移除 `<template x-if>` + `<div class="table-scroll">` 雙層包裝，改用 `x-show` 直接套用於 `.empty-state div` 與 `<table>`，與其他 Tab（本期收款、未收款等）結構保持一致

### 2026-07-22f — 顧問建議全實施（6 項）

- **收款率改用 actualAmount**：`_collect()` `recv_amt` 從 `amt`（合約分期）改為 `aa if aa is not None else amt`（實收金額），使案件及業務員層級收款率反映真實入帳
- **業務員毛利率改收入加權平均**：`sm[k]` 從 `mSum/mCnt` 簡單平均改為 `mRevSum/mProfitSum`（稅前收入加權），避免小案件毛利率拉偏整體均值；實際毛利率同步改為 `amRevSum/amProfitSum`
- **帳齡分析 Tab**：`reports.html` 新增「帳齡分析」Tab 按鈕；`reports.js` 新增 `showArTab()` lazy fetch `GET /api/reports/ar-aging`；Panel 包含四區間 KPI 卡片（0–30/31–60/61–90/90+）+ 每區間展開明細表（含已超 N 天色標）
- **已結案未精算警示橫幅**：`_collect()` 新增查詢已結案未 finalized 案件 → `settleOverdue[]`；前端 `settleOverdue` getter；KPI 區塊下橙色警示橫幅（顯示案號列表）
- **在製訂單 Backlog KPI**：`_collect()` 計算 `backlog = sum(total-receivedAmount for 已成案)`；summary 加 `backlog` 欄位；業績核心 KPI 網格新增藍色「在製訂單」卡片；PDF 報告同步加入
- **近 12 月 MoM 趨勢**：新增 `GET /api/reports/monthly-trend?months=12`（回傳每月 newCases / revenue / collected / avgMarginPct）；`showChartsTab()` lazy fetch；`_buildTrendChart()` 可用時加入「實收金額」橙色折線（按 receivedAt 月份，非 quoteDate）

### 2026-07-22d — Excel + PDF 毛利分析精算比較欄

- **Excel「毛利分析」Sheet**：新增「預估毛利（NT$）」欄（= 報價稅前 × 預估淨毛利率）、「差異金額（NT$）」欄（= 實際毛利 − 預估毛利；Excel 格式 `+#,##0;-#,##0`）；新增合計行（深色底）顯示三個金額加總；差異欄字體色標（正數綠 / 負數紅）
- **PDF 報告**：新增獨立「毛利分析」段落（頁面分隔，紫色標題），欄位同前端：預估毛利率 / 預估毛利 / 實際毛利率 / 實際毛利 / 差異(pp) / 差異金額；末行合計；無精算案件時顯示說明文字

### 2026-07-22b — 日曆快速回報 + 毛利分析金額欄

- **`daily-tasks.html`**：新增 `selectCalDayTask(date, taskId)`，點選「今日未完成事項」任務卡後直接導航至該任務並自動展開 inline 回報表單（若本人尚未提交）；已提交者僅選中顯示，不強制打開編輯
- **`reports.html`（毛利分析 tab）**：新增「預估毛利（NT$）」欄（= 報價稅前 × 預估淨毛利率）與「差異金額（NT$）」欄（= 實際毛利 − 預估毛利；綠正/紅負色標），與既有差異(pp)欄共同呈現精算落差
- **`reports.js`**：新增 `fmtDiff()`（帶正/負號 NT$ 格式化）、`estGrossProfit(mc)`（計算預估毛利額）兩個 helper

### 2026-07-22a — 承攬商管理：功能補強

- **`vendor-contractors.html`**：新增政府統編查詢帶入（`GET /api/company/tax/{id}`，查到後可手動覆蓋）、承攬商類型下拉（機電/**弱電**/消防/空調/裝修/水電/IT/土木/其他）、內部標籤（多標籤新增/移除，以逗號分隔存入 `data_json.tags`）、匯出 Excel / 匯入 Excel（SheetJS xlsx@0.18.5 CDN）
- **匯入欄位**：`承攬商名稱 | 承攬商類型 | 統一編號 | 聯絡人 | 電話 | Email | 地址 | 內部標籤（逗號分隔）| 備注`；依統編或名稱比對：存在→PUT(更新)，不存在→POST(新增)
- **`backend/routers/vendor_contractors.py` PUT**：改為合併 `data_json`，若呼叫端未傳 `visits`，自動保留既有往來紀錄（避免匯入覆蓋）
- **搜尋優化**：`GET /api/vendor-contractors?q=` 新增 `tax_id LIKE` 條件（原僅搜 name/phone/contact_name）
- **往來紀錄保護**：`openEdit(v)` 擷取 `v.visits` 存入 `_pendingVisits`，PUT 時一併傳入，確保手動儲存前的既有紀錄不被 Modal 存檔覆蓋

### 2026-07-21aa — 承攬商管理模組（全新）

- **DB v22**：新增 `vendor_contractors`（承攬商主檔：名稱/統編/聯絡人/電話/Email/地址/往來紀錄/停用）與 `contractor_dispatches`（派發紀錄：報價品項 JSON、狀態、合計金額、建立人）兩張表
- **`backend/routers/vendor_contractors.py`**（新建）：
  - 承攬商 CRUD：`GET /api/vendor-contractors` · `GET /api/vendor-contractors/selectable`（輕量列表供下拉） · `GET/POST/PUT/DELETE /api/vendor-contractors/{id}` · `PATCH .../active` · `PATCH .../visits`（樂觀鎖）
  - 派發 CRUD：`GET/POST /api/contractor-dispatches` · `GET/PUT/DELETE /api/contractor-dispatches/{id}`
  - 回推端點：`POST /api/contractor-dispatches/{id}/import-to-quote` — 將承攬商報價品項（含 header 區塊）附加至報價單 `items[]`，僅草稿狀態可操作
- **`frontend/pages/vendor-contractors.html`**（新建）：雙欄佈局（左列表 / 右詳情），承攬商 CRUD Modal，往來紀錄樂觀鎖儲存，右欄顯示該承攬商之全部派發歷程
- **`frontend/js/case-management.js`**：新增 `vendors[]`, `dispatches[]`, `dispatchesLoading`, `showDispatchModal` 等狀態及 `loadVendors()` / `loadDispatches()` / `openNewDispatch()` / `openEditDispatch()` / `saveDispatch()` / `deleteDispatch()` / `importDispatchToQuote()` / `addDispatchItem()` / `onDispatchItemPrice()` 等方法；`init()` 呼叫 `loadVendors()`；`selectCase()` 呼叫 `loadDispatches(quoteNo)`
- **`frontend/pages/case-management.html`**：新增「承攬商」Tab（位於保固備注後）：外包總成本 KPI、派發卡片清單（含品項明細表）、「↩ 回推報價單」按鈕、派發 Modal（承攬商選擇 / 日期 / 狀態 / 工作範圍 / 品項報價表格含自動金額計算 / 備注）
- **`frontend/static/sidebar.js`**：廠商與採購區段新增「承攬商管理」連結（`vendor-contractors.html`，`admin+` 可見）

### 2026-07-21z2 — 回報修改標示（UI + DB）

- **DB v21** (`db.py`): `daily_task_completions` 新增 `report_edit_count INTEGER NOT NULL DEFAULT 0`；`ON CONFLICT DO UPDATE SET` 子句加入 `report_edit_count=report_edit_count+1` — 每次覆寫自動計數
- **`daily_tasks.py`**: 三個 `SELECT` 查詢加入 `report_edit_count`；comp_map 輸出 `editCount` 欄位
- **`daily-tasks.html`**: 四處顯示黃色「已修改」徽章（`editCount > 0`）：一般任務詳情每人 ag-card、本人已完成 notice、日曆日期詳情每人列、回報彙整每人列；hover `title` 顯示「已修改 N 次」

### 2026-07-21z — 工作事項回報編輯

- **`daily-tasks.html`（一般任務詳情）**：`isAssignedToMe() && completed` 區塊新增「修改回報」按鈕（`editingMyReport` flag 控制）→ 展開 dt-complete-form 可覆寫原有回報；`submitCompletion()` 成功後重置 `editingMyReport`，toast 訊息依模式顯示；`selectTask/selectWeeklyTask/switchOccurrence` 切換任務自動重置
- **`daily-tasks.html`（日曆日期詳情）**：指派人卡片底部新增「修改回報」（已完成）/ 「提交回報」（未提交）按鈕，展開 inline textarea；`calSubmitReport()` → `PATCH /daily-tasks/{id}/complete` → `loadReportData()` 重載；`calEditTaskId/calEditReport/calEditSubmitting` 狀態，切換日期或任務自動重置
- **新增狀態**：`editingMyReport: false`, `calEditTaskId: null`, `calEditReport: ''`, `calEditSubmitting: false`
- **新增方法**：`calSubmitReport(taskId, occDate, text)`（純前端，無後端改動）

### 2026-07-21y — 工作事項編輯紀錄 + 月報當月範圍

- **DB v20** (`db.py`): 新增 `daily_task_edit_log` 表（task_id, changed_by, changed_at, changes_json 儲存欄位差異陣列）
- **`daily_tasks.py`**: `_compute_task_diff()` 比對 10 個欄位（標題/說明/日期/分類/優先級/指派對象/主管/週期/排程/案件）；`update_daily_task` 儲存 diff + email 通知主管（`notify_daily_task_edited`）；新增 `GET /api/daily-tasks/{id}/edit-log`（superadmin/指派人/主管可查）
- **`email_notify.py`**: 新增 `notify_daily_task_edited()`，信件含異動前後對照表（舊值刪除線→新值加粗）
- **前端 `daily-tasks.html`**: 編輯按鈕移出解鎖限制（superadmin 直接可用），刪除仍須解鎖；任務詳情底部顯示「編輯紀錄」區塊（編輯人頭像+姓名+時間 + 每個欄位舊→新差異列表）；儲存後自動重載 edit-log
- **`reports.py` `_send_monthly_report_for`**: 月報寄送改為當月範圍獨立 — casesAll→casesPeriod、outstanding/allItems 過濾同月案件、summary 重算；六月報告 → 七月一日 08:00 寄出，guard `monthly_report_last_sent` 防重複

### 2026-07-21v — 保固追蹤納入已成案

- **`warranty.html`**：移除 API 呼叫中的 `?deal_tag=已結案` 過濾參數，改為呼叫 `/api/devices`（與設備登載頁相同），使所有登載了保固時間的案件設備（含已成案）均顯示於保固追蹤頁；副標題更新為「含已成案 / 已結案」

### 2026-07-21u — 月報自動寄送

- **`helpers/email_notify.py`**：新增 `_superadmin_emails()`（查詢 `role='superadmin'`，fallback to admin emails）、`_send_with_attachments()`（multipart/mixed；RFC 5987 UTF-8 filename encoding for Chinese filenames）、`notify_monthly_report(period_label, period_str, excel_bytes, pdf_bytes)` — 非阻塞 daemon thread 寄送 Excel+PDF 附件給所有 superadmin
- **`helpers/__init__.py`**：匯出 `notify_monthly_report`
- **`routers/reports.py`**：新增 `_prev_month_str()`、`_send_monthly_report_for(period_str)` — 產 Excel+PDF 並呼叫 `notify_monthly_report`（PDF 失敗不中斷 Excel 寄送）、`_catchup_monthly_reports()` — 從 `monthly_report_last_sent + 1` 逐月補寄至上月（首次執行只補上月，不回補全部歷史）、`schedule_monthly_report()` — 啟動時執行補寄、排定每月 1 日 08:00 自動寄送；guard key `monthly_report_last_sent`
- **`main.py`**：啟動序列新增 `reports.schedule_monthly_report()`

### 2026-07-21t — 主管頁面載入修復 + 離開警示 + 開機補寄

- **主管頁面載入修復**（`daily_tasks.py`）：`_user_filter_sql` 對 superadmin 加 username 參數時改為同時檢查 `assigned_to OR supervisors`；修正從使用者管理頁點「查看每日工作事項」跳轉後，superadmin 主管看不到自己監督任務的問題；`get_task_history` 403 同步放行 supervisors 成員
- **全模組離開警示**（`sidebar.js`）：新增 `bindNavGuard()` — 在 DOMContentLoaded 後攔截所有 `<a>` 點擊（非 # / javascript: / 同路徑）；`beforeunload` 防頁面刷新/關閉；全域監聽 `input`/`change` 事件自動設 `window.motrixIsDirty = true`（排除 type=search、readonly、disabled 及 class 含 search/filter 的輸入）；`fetch` 攔截器：成功的 POST/PUT/PATCH/DELETE 自動清除 dirty；提示文案：「您有尚未儲存的輸入內容，離開此頁面將導致資料遺失，確定要離開嗎？」
- **開機補寄機制**（`daily_tasks.py`）：`schedule_overdue_check` 改為每次啟動執行 `_startup_catchup()`，從 `last_check + 1` 逐日補發至昨日；移除舊版 `hour >= 8` 限制；`_check_overdue_and_notify` 加 `check_date` 參數可指定日期；多日停機情境（如週末未開機）亦可全補，不再只補昨日

### 2026-07-21s — 負責主管可查看被指派人工作事項

- **Backend `_user_filter_sql()`**（`daily_tasks.py`）：非 superadmin 使用者若在 `supervisors` 欄位，也可撈到該任務（原只看 `assigned_to`，現改 `OR EXISTS supervisors`）
- **Backend `get_daily_task()`**（`daily_tasks.py`）：403 存取檢查同步放行 `supervisors` 成員
- **任務卡片「主管」badge**（`daily-tasks.html`）：使用者被列為主管但非指派人時，卡片 footer 顯示紫色「主管」chip（一般任務卡 + 週期任務卡 + 日曆 dashboard 今日任務卡三處同步）
- **任務詳情回報可視性**（`daily-tasks.html`）：指派人回報文字對主管（`supervisors`）開放，等同本人與 superadmin 解鎖
- **主管提示橫幅**（`daily-tasks.html`）：非指派人但為主管時，詳情底部顯示「您為此工作事項的負責主管，可查看所有人員的回報情況」藍紫提示框

### 2026-07-21r — 本期未完成日升序排列

- **本期未完成日改為升序**（`daily-tasks.html`）：`calPeriodPendingDates()` sort 改為 `a - b`，日期最早的顯示在最上方；`calPeriodPendingByWeek()` 週排序同步改升序，最早週在最上

### 2026-07-21q — 本期未完成日週分組 + 逾期通知確認

- **本期未完成日改週分組顯示**（`daily-tasks.html`）：`calPeriodPendingByWeek()` 以週一為起點分組；週標頭顯示日期範圍（`MM/DD（一）– MM/DD（日）`）+ 該週未完成天數；每週內各日顯示完成進度，可點擊跳轉；新增 `_weekMondayOf()` 用本地時間 accessor（避免 UTC+8 偏移）
- **逾期 Email 通知確認**（`daily_tasks.py`）：機制已完整，不需額外修改
  - `_check_overdue_and_notify()` 每日 08:00 掃描昨日所有 incomplete 指派人
  - 每個未完成的（任務, 指派人）發 `notify_daily_task_overdue` email
  - 收件人：被指派人 + 任務主管（若無主管則發給所有 admin/superadmin）
  - Guard key `dt_overdue_last_check` 防重複，重啟不會重發

### 2026-07-21p — 日曆視圖右側 dashboard

- **每日工作事項日曆 dashboard**（`daily-tasks.html`）：未選取日期時右側顯示三個區塊
  - **今日未完成事項**：自動載入當日任務，列出尚未全員完成的任務卡片；每個卡片顯示各指派人完成/待完成 chip（黃=待完成、綠=已完成）；點擊跳轉到今日詳情
  - **本期未完成日**：從 `calData` 提取 `done < total` 的日期，每列顯示日期、星期、完成進度（橙/紅），可點擊跳轉該日
  - **本期已完成日**：`done === total` 的日期以綠色 chip 方式列出，可點擊跳轉
  - 技術：`loadCalendarData()` 改為 3 個並行 fetch（上月/本月/今日），今日任務存入 `calDashData`；新增 `calDashTodayStr/calDashPendingTasks/calPeriodPendingDates/calPeriodDoneDates` helper methods

### 2026-07-21o — 介面過濾與日曆視圖

- **案件管理「全部」Tab 排除已結案**（`case-management.js` + `case-management.html`）：`filterCases()` 在 `listTab==='all'` 時 `filter(c => c.deal_tag !== '已結案')`；「全部」徽章計數同步排除；已結案仍可點獨立 Tab 查看
- **專案管理「全部」pill 排除完工**（`projects.html`）：`filteredProjects` getter 加 `filterStatus==='全部' && p.status==='完工'` 短路排除；完工 pill 仍可獨立篩選
- **每日工作事項日曆視圖**（`daily-tasks.html`）：
  - 頂部「日曆視圖」按鈕，桌機版（`window.innerWidth >= 768`）**預設自動開啟**
  - 左側雙月曆（上月 + 本月）：週一起始，今日藍色圓底；每格色標（綠底=全完成 / 黃底=部分完成 / 紅底=未完成）+ `已/總` 數字
  - 右側：點擊日期載入當日所有任務，顯示人員 chips（完成率色點）、搜尋輸入、任務清單 + 回報詳情
  - 月份切換同步重載兩個月資料；與「回報彙整」模式互斥
  - **Bug fix**：`calMonthDays()` 改用 `getFullYear/Month/Date` 本地時間，修正 `toISOString()` UTC 偏移在 UTC+8 環境差一天的問題

### 2026-07-21n — 角色管理全面升級

- **角色名稱自訂**（`system.py` + `users.html`）：superadmin 可在「角色名稱設定」面板（可摺疊）自訂 superadmin/admin/sales/engineer/viewer 五層的顯示名稱；儲存於 `system_settings`；`GET/PUT /api/settings/role-labels`；使用者列表、快速套用 chips、角色下拉選單均即時反映；DB `role` 欄位不變
- **自建角色管理**（`system.py` + `users.html`）：superadmin 可建立自訂角色（名稱 + 基礎角色層 + 模組清單）；`GET/POST/PUT/DELETE /api/settings/custom-roles`；資料存於 `system_settings key custom_roles`；使用者 Modal 角色快速套用列顯示系統預設 chips + 自訂角色 chips（虛線框區隔）
- **存取模組補全**（`users.html`）：`allModules` 新增 `reports`（營運報表）、`work_log`（工作日誌）、`daily_task`（每日工作事項），使用者編輯 Modal 的模組勾選列現已涵蓋全部側欄項目
- **Sidebar 模組閘控**（`sidebar.js`）：`reports` → `admin+` 或含 `reports` 模組；`work_log` / `daily_task` → 非 viewer 或含對應模組（相容既有帳號）
- **報價清單「全部」Tab 排除已結案**（`quotations.html`）：`tabCount()` 及 `filteredQuotes` getter 雙重排除；已結案僅顯示於「已結案」分類 Tab
- **端點安全強化**：`customers.py`（create/update/visits/delete 4 端點）、`parts.py`（create/update/delete 3 端點）、`quotations.py`（case-record PATCH / payment PATCH 2 端點）補加 `_require_user()` 角色檢查

### 2026-07-21m — P3 客戶交易歷史彙整

- **新 API**：`GET /api/reports/customer-history`（`routers/reports.py`，admin+ 限制）
  - 掃描所有非草稿報價，依 `customer_name` 分組聚合
  - 傳回每客戶：`wonCount` / `lostCount` / `winRate` / `totalWonAmount` / `collectedAmount` / `collectionRate` / `lastActivity` / `salesPerson` + `transactions[]`
  - 按成案總金額降序排列
- **`reports.js`**：新增 `custHistory` / `custLoading` / `custLoaded` / `custSearch` / `custSort` / `selectedCust` 狀態；`showCustTab()` 懶載入；`filteredCusts` getter（支援搜尋 + 四種排序）；`selectCust()` / `custAmtFmt()`
- **`reports.html`**：新增「客戶歷史」Tab button（懶載入，不影響主要 loadData 速度）
  - 左欄：可搜尋 + 可排序的客戶卡片列表（成案/未成案/追蹤中 chip + 成案率色標）
  - 右欄：選中客戶後顯示 5 個 KPI（總金額/已收/收款率/成案率/最後活動）+ 交易明細表（案件號超連結、狀態標籤、毛利率色碼）

### 2026-07-21l — P2 營運效率：三項改善

**P2-1：每日工作事項掛案件編號**

- **DB v19**：`daily_tasks` 新增 `case_no TEXT DEFAULT ''`（`_m019_daily_task_case_no`）
- **API**：`DailyTaskIn.case_no`；`GET /api/daily-tasks?case_no=` 篩選；`POST/PUT` 寫入 `case_no`
- **daily-tasks.html**：`loadActiveCases()` 載入已成案列表 → modal「關聯案件」下拉；任務卡片藍色 `case_no` badge
- **case-management.html**：右下「今日相關任務」mini strip（`_loadCaseTasks(quoteNo)` 於 selectCase 時呼叫）

**P2-2：保固到期前 30/7 天主動 Email**

- `helpers/email_notify.py`：`notify_warranty_expiry(device_name, customer, quote_no, days_left, expiry_date, sales_person)` — 7 天紅色 / 30 天橙色
- `helpers/__init__.py`：匯出 `notify_warranty_expiry`
- `routers/daily_tasks.py`：`_check_warranty_expiry()` 掃描 `deal_tag='已成案'` 案件 devices[]；per-device+threshold guard（`system_settings` key `warranty_notif.{no}_{sn}_{7|30}`）；`schedule_overdue_check` 改為每日同時呼叫兩個檢查器

**P2-3：採購叫料廠商交期追蹤**

- `case-management.html` 叫料管控 mat-card：叫料中且未到料時顯示「廠商名稱」輸入 + 「預計到料日」date input + 交期逾期紅標
- 資料存於 `data_json.caseRecord.materials[].supplier/.expectedDate`（無需 DB schema 變動）

### 2026-07-21k — P1 業績可視化：銷售漏斗 + 待追蹤報價

- **新 API**：`GET /api/dashboard/funnel`（`routers/dashboard.py`）
  - 傳回 `funnel`（totalSubmitted / won / lost / pendingResponse / winRate）
  - 傳回 `followUpQuotes`（已送出 ≥ 14 天未確認，按天數降序，最多 10 筆）
  - 傳回 `expiringQuotes`（有效期剩 ≤ 3 天，最多 5 筆）
  - 僅限 quotation 以上角色；銷售人員可見自身負責報價
- **儀表板 `index.html`**：
  - 載入後非同步呼叫 `loadFunnel()`（fire-and-forget，不阻塞主 loading）
  - **有效期警示 banner**（紅色）：每份剩 ≤ 3 天的已送出報價獨立一行，附「前往更新」按鈕
  - **待追蹤報價 banner**（橙色）：彙整顯示 ≥ 14 天未回應報價（最多 4 行 + 摺疊提示）；附「查看全部」連結
  - **Win Rate 漏斗條**（白底卡片，KPI 下方、圖表上方）：成案率 % ＋ 成案 / 評估中 / 未成案 三數值 ＋ 比例分色長條圖

### 2026-07-21j — 每日工作事項 UI 全面升級

- **頂部按鈕**：`btn` / `btn-ghost` / `btn-primary` CSS 補充定義（原本無樣式）；`回報彙整` 改用 `.dt-bar-act-report`（紫色 pill，激活為實色）；`解鎖管理視角` 改用 `.dt-bar-act-lock`（amber 警示色）；`新增工作事項` 改用 `.dt-bar-act-add`（藍色主按鈕）
- **回報彙整**：
  - 人員 chip 列：載入後自動顯示當日所有被派人員，帶完成率色點（綠/橙/紅）及 `(N/M)` 計數；點擊快速切換只看該人員任務
  - 「今日」快速按鈕：一鍵跳回當日並清除篩選
  - 年/月切換時自動清除人員篩選
  - 搜尋提示邏輯：人員篩選 OR 文字搜尋時均顯示符合筆數

### 2026-07-21i — 每日工作事項歷史介面重設計

- **daily-tasks.html**：歷史紀錄 Tab 全面改版
  - 工具列：`月 ｜ 週` 切換 + `← 期間 →` 導航（← → 各退/進一週或一月）
  - **月視圖**（預設）：依 ISO 週分帶狀組（`第N週 M/D–M/D`），帶內按日列行，collapse 展開回報內容
  - **週視圖**：顯示 Mon–Sun 7 天，有任務者顯示人員 chip + 進度；無任務日顯示 `— 無任務`（半透明）
  - 進度 badge 三色：全部完成（綠）/ 部分完成（橙）/ 未完成（紅）
  - 改為一次性載入最多 500 筆（`per_page=500`），廢除 load-more 分頁；tab 標頭仍顯示總筆數
- **左面板 stat-strip**：仿採購管理配置，顯示「今日任務 / 今日待辦 / 本月完成率」三格數值卡（含顏色警示）

---

### 2026-07-21h — 介面優化批次（UI / CEO Dashboard）

- **sidebar.js**：`每日工作事項` 側欄項目加入 `sb-dt-badge`（今日待辦數，紫色徽章）
- **notif.js**：加入 `_fetchDailyTaskCount()` 背景抓取今日未完成任務並更新 badge；`actionLabel` 補齊 `daily_task.*` 系列動作標籤
- **reports.js / reports.html**：營運報表 CEO 視角重編排
  - Tab 順序改為：目標達成率 → 圖表分析 → 業務員績效 → 本期收款 → 未收款 → 案件清單 → 毛利分析 → 保固預警
  - 預設開啟 `目標達成率` tab；年報模式自動切換至此 tab
  - KPI grid 依策略優先序分兩群：「業績核心」（新成案/本期收款/精算毛利/覆蓋率）+ 「財務概況」（應收/已收/實收淨/未收/手續費/保固預警）
  - 保固預警有警示時自動轉紅色卡片

---

### 2026-07-21g — 品質掃尾批次（Quality Sweep）

- **L2** `quotation-form.html`：`addItem()` / `addHeader()` / 複製模板改用 `crypto.randomUUID()`；API 載入後補 id normalize
- **L3** `backend/tests/test_core.py`：48 tests 全過（TestStepsToTiers / TestActiveTiers / TestCurrentTierIdx / TestPasswordHelpers）
- **確認已施作**：L1 sidebar 角標（notif.js:68 已排除 approval_request）/ E2 Login 速率限制（auth.py）/ E3 Session 清理（startup.py）

---

### 2026-07-21f — 可靠性強化批次（Reliability Patch Batch）

- **H3** `archive.py`：備份 ERROR 時發 Email 告警（`_send_backup_error_email()`，每日節流，`_async_send` 非同步）
- **H4** `routers/reports.py`：Excel/PDF 匯出 60 秒每用戶冷卻（`_check_export_rate()`，429 on violation）
- **M1** `helpers/quotations.py`：提取 `_steps_to_tiers()` 共用 helper；`system.py._normalize_flow()` + `quotations._setting_to_active_tiers()` 均改呼叫
- **M3** `backend/tests/test_core.py`：25 tests 全過（TestParsePeriod / TestComputeAchievement / TestCalc）

---

## §13 · 目錄結構（精簡）

```
MOTRIX-ERP/
├── MOTRIX-ERP-QUICK.md          ← 本文件
├── GITFLOW.md                   ← Git Flow 分支規則（develop 分支 + commit 規範）
├── .gitignore
├── backup_alerts/               ← 備份警示（執行期產生）
├── backend/
│   ├── main.py                  ← wiring；startup 呼叫 auth.init_rate_limiting()
│   ├── db.py                    ← schema + 25 個 migrations（CURRENT_VERSION=25）
│   ├── version_manifest.json    ← 模組版本紀錄（重啟後同步至 DB module_versions）
│   ├── helpers/                 ← 套件（拆自原 helpers.py）
│   │   ├── __init__.py          ← re-export 全部符號（向後相容）
│   │   ├── auth.py              ← 密碼、session、弱密碼政策
│   │   ├── settings.py          ← system_settings CRUD
│   │   ├── audit.py             ← audit log + 通知
│   │   ├── quotations.py        ← SQL 常數、save_quotation_json
│   │   ├── dates.py             ← _add_months、_warranty_expiry
│   │   ├── email_notify.py      ← Email 通知（月報、逾期、保固、備份告警）
│   │   └── startup.py           ← 啟動檢查、Edge 路徑解析
│   ├── archive.py               ← 備份；_atomic_json_write()；G: fallback
│   ├── pdf_gen.py · photos.py
│   ├── backup_job.py            ← 獨立備份腳本（Task Scheduler 呼叫）
│   ├── setup_backup_task.ps1    ← 工作排程器設定（初次部署執行一次）
│   ├── motrix_erp.db
│   ├── db_backups/
│   │   ├── YYYY-MM-DD/          ← 本機整庫 SQLite 快照（保留 30 天）
│   │   └── quotation_instant/   ← G: 不可用時即時報價單 JSON fallback
│   ├── logs/backup_job.log
│   ├── tests/test_core.py       ← 48 自動化測試（全通過）
│   ├── .initial_admin_credentials.txt  ← 僅新裝，用後刪
│   └── routers/
│       ├── auth.py · quotations.py · customers.py · suppliers.py
│       ├── parts.py · projects.py · dashboard.py · system.py · reports.py
│       ├── daily_tasks.py · warranty.py
│       └── vendor_contractors.py  ← 承攬商 + 派發 CRUD + accept + import-to-quote
├── frontend/
│   ├── index.html               ← 儀表板（Alpine inline）
│   ├── css/style.css
│   ├── js/
│   │   ├── case-management.js   ← ✅ 有效（案件管理 Alpine 元件）
│   │   └── reports.js           ← ✅ 有效（營運報表 Alpine 元件）
│   ├── pages/
│   │   ├── quotation-form.html  ← Alpine inline（真正的 quotationForm()）
│   │   ├── settlement.html      ← Alpine inline（真正的 settlementPage()）
│   │   ├── case-management.html ← 含承攬商派發 + 驗收流程 Tab
│   │   ├── vendor-contractors.html ← 承攬商管理（雙欄；vendorContractorsPage()）
│   │   └── *.html               ← 其餘頁面均 Alpine inline，無對應外置 JS
│   └── static/
│       ├── sidebar.js           ← Topbar + Sidebar + 離開警示
│       ├── notif.js             ← 通知 Bell + daily_task badge
│       └── logo.png             ← MOTRIX 白字去背 PNG
├── uploads/projects/
└── 報價單PDF/
```

---

---

## 維護規則（每次修改必讀）

### 版本紀錄登記（強制）

**每次功能變更完成後，必須同步更新以下兩處：**

1. **`backend/version_manifest.json`** — 新增一筆條目，格式如下：

   ```json
   {
     "module": "模組中文名",
     "version": "YYYY-MM-DDx",
     "date": "YYYY-MM-DD",
     "time": "HH:MM",
     "content": "簡要說明（繁中，60–120 字）"
   }
   ```

   | 欄位 | 說明 |
   |------|------|
   | `module` | 對應系統模組（報價單 / 案件管理 / 使用者管理 / 系統設定 / 系統安全 / 前端介面 / …） |
   | `version` | 日期 + 小寫後綴字母（同日第二筆加 `a`，第三筆加 `b`，依序遞增） |
   | `date` | `YYYY-MM-DD` |
   | `time` | **實際完成修改的時間**，24h 制 `HH:MM`（不可省略） |
   | `content` | 說明做了什麼，不要只寫「更新」，要寫具體改動 |

2. **本檔 §12** — 在最新版本區塊加入摘要行。

> **⚠️ 伺服器重啟後**，`_sync_module_versions()` 自動將 manifest 條目同步至 DB `module_versions` 表（UPDATE 邏輯同步修改過的欄位，不影響使用者手動新增的條目）。若修改了已存在條目的 `time` 或 `content`，下次重啟即生效。

### 其他維護提醒

- 功能變更時先更新本檔「對應 §N 章節」，再在 §12 加摘要。
- 死碼警告欄位如有整理（移除 .js、改用 include），記得更新 §2 與 §13。
