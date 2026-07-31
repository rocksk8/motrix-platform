# MOTRIX ERP — 開發快速參考（交付版）

> 允碩整合集創股份有限公司（統編 60575481）｜ Tel: 04-3602-2818 ｜ info@miactw.com
> 文件版本：**2026-07-21c**（財務報表新增「營運目標及達成率」：設定端點 + YTD 計算 + Excel 新分頁 + PDF 章節 + 前端 Tab + 目標設定 Modal）

---

<!-- ╔══════════════════════════════════════════════════════╗
     ║  目錄（§ 段落快速跳轉）                               ║
     ╚══════════════════════════════════════════════════════╝

  §1  啟動與位址           §9   前端規範
  §2  系統架構總覽          §10  成本公式
  §3  安全                 §11  已知限制
  §4  資料模型（DB Schema） §12  變更摘要
  §5  共用函式庫            §13  目錄結構
  §6  API 端點完整列表      §14  Email 通知
  §7  前端頁面 → API 對應表 §15  資料流：完整呼叫鏈
  §8  備份架構             §16  Sidebar 結構
-->

---

## §1 · 啟動與位址

| 項目 | 值 |
|------|-----|
| 開發啟動 | `backend\start.bat` |
| 更新後重啟 | `backend\restart.bat`（PowerShell `Stop-Process` + uvicorn） |
| 本機 | http://localhost:666 |
| 區網 | http://172.16.11.211:666 |
| SQLite | `backend\motrix_erp.db`（WAL 模式，timeout=30s） |
| 進入點 | `backend/main.py` → `uvicorn main:app --port 666 --host 0.0.0.0` |

**新增功能規則**

- API → 對應 `routers/xxx.py`，勿塞進 `main.py`
- 共用邏輯 → `helpers/`（6 子模組）
- 表結構 → `db.py:init_db()` + `_mNNN_xxx()` migration
- 備份 → `archive.py`（所有 JSON 寫入須用 `_atomic_json_write()`）
- PDF → `pdf_gen.py`；照片水印 → `photos.py`（PIL）

---

## §2 · 系統架構總覽

```
┌──────────── Frontend (Alpine.js + 靜態 HTML) ────────────┐
│  pages/*  +  js/*  +  static/sidebar.js / notif.js       │
│  Session: localStorage.motrix_session (Bearer token)     │
└──────────────────────┬───────────────────────────────────┘
                       │ HTTP :666
┌──────────────────────▼───────────────────────────────────┐
│  FastAPI  backend/main.py                                 │
│  Middleware 執行順序（外→內）：                             │
│    1. security_headers（最外層）                           │
│    2. auth_middleware（Token 驗證 + must_change_password） │
│    3. no_cache_static（HTML/CSS/JS no-store）             │
│  Exception Handler: RequestValidationError → 422         │
│                     Exception → 500                       │
│  routers: auth / quotations / customers / suppliers /    │
│           parts / projects / dashboard / system /        │
│           reports / contractors / payslips / daily_tasks │
└──────────────────────┬───────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   SQLite (WAL)   Edge PDF      G: 雲端 + 本機快照
   motrix_erp.db  pdf_gen.py    archive.py
```

### 後端模組一覽

| 檔案 | 職責 | 關鍵位置 |
|------|------|---------|
| `main.py` | 啟動、CORS、middleware、路由掛載、startup 呼叫 | 全檔 |
| `db.py` | `get_db()` 連線工廠、`init_db()`、11 個 migration | `db.py:17`（get_db）、`db.py:31`（init_db） |
| `helpers/__init__.py` | re-export 全部符號（向後相容） | 全檔 |
| `helpers/auth.py` | 密碼雜湊（PBKDF2-SHA256）、session 驗證、弱密碼政策 | `auth.py:93`（_require_user）、`auth.py:42`（_hash_pw） |
| `helpers/settings.py` | `system_settings` CRUD（`_get_setting`/`_set_setting`） | `settings.py` |
| `helpers/audit.py` | `_audit()`（寫 audit_log）、`_notify()`（寫 notifications） | `audit.py:11`（_notify）、`audit.py:27`（_audit） |
| `helpers/quotations.py` | `save_quotation_json()`、`quote_hot_fields()`、SQL 常數 | `quotations.py:24`（save_quotation_json） |
| `helpers/dates.py` | `_add_months()`、`_warranty_expiry()` | `dates.py` |
| `helpers/email_notify.py` | Gmail SMTP；5 事件函式；`_send_raising()`（test 用） | `email_notify.py:91`（_send）、`email_notify.py:119`（_async_send） |
| `helpers/startup.py` | `init_default_admin()`、`flag_weak_passwords()`、`_get_edge_path()` | `startup.py` |
| `archive.py` | 即時/日/週備份；本機 SQLite 快照；`_atomic_json_write()` | `archive.py:31`（_atomic_json_write） |
| `backup_job.py` | 獨立備份腳本（Windows 工作排程器，不依賴 server） | 全檔 |
| `pdf_gen.py` | Edge Headless PDF；`generate_pdf_bytes()`；`generate_payslip_pdf_bytes()` | `pdf_gen.py:21`（_get_pdf_base） |
| `photos.py` | 專案照片水印（Pillow） | 全檔 |
| `routers/auth.py` | 登入/登出/me/改密/解鎖密碼/使用者 CRUD；rate limiting | 全檔 |
| `routers/quotations.py` | 報價 CRUD、簽核、deal-tag、精算、PDF、付款 | 全檔 |
| `routers/customers.py` | 客戶 CRUD + 拜訪紀錄 | 全檔 |
| `routers/suppliers.py` | 供應商 CRUD + 往來紀錄 | 全檔 |
| `routers/parts.py` | 料號主檔 CRUD | 全檔 |
| `routers/projects.py` | 專案 CRUD + 工作日誌 + 照片 | 全檔 |
| `routers/dashboard.py` | 儀表板統計、月報、設備、應收帳款、GCIS 查詢 | 全檔 |
| `routers/system.py` | 簽核流程設定、通知、稽核日誌、工作日誌、Email 通知設定 | 全檔 |
| `routers/reports.py` | 財務報表 JSON/Excel/PDF（openpyxl + Edge） | 全檔 |
| `routers/contractors.py` | 外包人員 CRUD + 身分證影本浮水印（PIL） | 全檔 |
| `routers/payslips.py` | 勞報單 CRUD + 稅務計算 + PDF + 存檔 | 全檔 |
| `routers/daily_tasks.py` | 每日工作事項 CRUD + 完成回報 + Email/in-app 通知 | 全檔 |

### 前端

| 路徑 | 說明 |
|------|------|
| `frontend/pages/*.html`（絕大多數頁） | ⚠️ Alpine 邏輯 **inline `<script>`**（系統真實主流架構） |
| `frontend/js/case-management.js` | ✅ 由 `case-management.html` 載入（non-defer，先於 Alpine CDN） |
| `frontend/js/reports.js` | ✅ 由 `reports.html` 載入（non-defer，先於 Alpine CDN） |
| `frontend/static/sidebar.js` | Topbar + Sidebar 注入；強制改密導向 |
| `frontend/static/notif.js` | 通知 Bell；`_fetchApprovalCount()`；所有動態內容用 DOM API |
| `frontend/css/style.css` | CSS 變數：`--sidebar-w` `--topbar-h` `--accent` |

> **CDN 依賴（quotation-form.html 額外載入）**：SortableJS v1.15.3（品項拖曳排序），非 defer，置於 Alpine CDN 之前。

> **⚠️ 死碼警告（重要）**：`frontend/js/` 目錄共 23 個 JS 檔，其中 **21 個不被任何 HTML 載入**。
> 唯一有效的兩個：`case-management.js`（case-management.html 載入）、`reports.js`（reports.html 載入）。
> 系統真實架構：**幾乎所有頁面 Alpine 邏輯均 inline 在 HTML `<script>` 中**。
> 修改邏輯一律在對應 `.html` 的 inline `<script>` 內進行，不要修改 `js/` 目錄的死碼。

---

## §3 · 安全

### §3.1 · Middleware 鏈（main.py）

執行順序（FastAPI middleware 後掛先執行 = 外層先執行）：

```
Request 進入
  → security_headers（main.py:108）：所有回應加安全標頭
    → auth_middleware（main.py:64）：
        OPTIONS → 放行（CORS preflight）
        /api/* 公開路徑 → 放行（_PUBLIC_API_PATHS = {/api/auth/login, /api/auth/logout, /api/ping}）
        /api/uploads/  + ?pt= 或 ?token= → 放行（由 route handler 自行驗 token）
        其餘 → 驗 Bearer token + sessions.expires_at + users.active
        must_change_password=1 → 僅放行 _MUST_CHANGE_PW_ALLOWED（main.py:44）
      → no_cache_static（main.py:53）：.html/.css/.js 加 no-store
        → 路由處理
```

### §3.2 · 帳號與密碼（helpers/auth.py）

| 規則 | 程式位置 | 說明 |
|------|---------|------|
| 密碼長度 ≥ 8 | `auth.py:33`（MIN_PASSWORD_LEN） | 拒絕短密碼 |
| 拒絕弱密碼 | `auth.py:59`（is_weak_password） | 含 7 個已知弱密碼 |
| 雜湊 PBKDF2-SHA256 | `auth.py:42`（_hash_pw）260k iterations | salt+dk 存入 users.password_hash |
| 舊 sha256 升級 | `routers/auth.py:192` | 登入時自動升級 |
| 新建使用者 | `routers/auth.py:314`（create_user） | must_change_password=1 |
| 管理員重設密碼 | `routers/auth.py:363`（update_user） | 同上 |
| 既有弱密碼 | `helpers/startup.py:flag_weak_passwords()` | 啟動時標記 |

**強制改密流程**：登入 → `mustChangePassword=true` → 前端導向 `change-password.html?forced=1` → middleware 僅放行白名單 → 改密 → `must_change_password=0`

### §3.3 · 解鎖密碼（報價單解鎖）

- 僅 superadmin；`users.unlock_password_hash`（獨立於登入密碼）
- `POST /api/auth/verify-unlock`（`routers/auth.py:438`）
- 啟動時 `init_unlock_passwords()`（startup.py）：偵測歷史弱預設 → 清空

### §3.4 · Session 與 Rate Limiting

| 項目 | 位置 | 值 |
|------|-----|-----|
| Session 存取 | `helpers/auth.py:93`（_require_user） | token → sessions JOIN users |
| 有效期 | `routers/auth.py:197` | expires_at = now + 30 天 |
| Rate limiting | `routers/auth.py:29-128` | per-IP，5 次失敗鎖 15 分鐘 |
| 鎖定持久化 | `db.py:499`（login_rate_limit 表） | 重啟不失效 |
| 啟動載入 | `routers/auth.py:67`（init_rate_limiting） | main.py 呼叫 |

### §3.5 · 角色與權限

```
superadmin > admin > sales > engineer > viewer
```

| 角色 | 報價可見性 | 財務資料 | 供應商 |
|------|----------|---------|--------|
| superadmin / admin | 全部 | ✓ | ✓ |
| sales / engineer / viewer | 僅自己的（sales_person_id = 自身 OR sales_person = display_name） | ✗ | ✗ |

- `engineer` → 預設無 `financial_view`
- 稽核記錄 `GET /api/audit-log` → admin+ only（`system.py:118`）
- 工作日誌 `PUT/DELETE` → 非 admin 只能操作自己（`system.py:201`）

---

## §4 · 資料模型（DB Schema）

DB: `backend/motrix_erp.db`（SQLite WAL），版本管理在 `db.py`，CURRENT_VERSION=16

### §4.1 · 資料表清單

| 表名 | 主要欄位 | 說明 |
|------|---------|------|
| `quotations` | `quote_no PK, status, deal_tag, settle_status, customer_name, project_name, total, pretax, direct_margin_pct, net_margin_pct, sales_person, sales_person_id FK, quote_date, valid_days, data_json, created_at, updated_at, created_by, export_count, export_log` | 報價單主表；巢狀資料在 data_json |
| `quote_seq` | `month PK, seq` | 月序號產生器 |
| `users` | `id PK, username UNIQUE, password_hash, display_name, role, email, phone, modules, active, created_at, unlock_password_hash, must_change_password, daily_task_pw_hash` | 使用者帳號 |
| `sessions` | `token PK, user_id FK, username, created_at, expires_at` | 登入 Session |
| `customers` | `id PK, name, tax_id, phone, data_json, created_at, updated_at` | 客戶主檔 |
| `suppliers` | `id PK, name, tax_id, phone, data_json, created_at, updated_at` | 供應商主檔 |
| `parts` | `id PK, part_no UNIQUE, name, brand, unit, cost, list_price, category, note, active, created_at, updated_at` | 料號主檔 |
| `audit_log` | `id PK, at, user_id, username, display_name, action, target_type, target_id, target_label, detail` | 稽核記錄（730天保留） |
| `system_settings` | `key PK, value_json, updated_at` | 系統設定 key-value |
| `notifications` | `id PK, username, type, ref_id, ref_label, message, is_read, created_at` | In-app 通知 |
| `projects` | `id PK, code UNIQUE, name, status, description, linked_cases, created_at, created_by, data_json` | 專案 |
| `project_logs` | `id PK, project_id FK, log_date, work_content, attendees, action_items, materials_used, photos, log_status, created_at, created_by, updated_at` | 專案工作日誌 |
| `work_logs` | `id PK, log_date, user_id FK, content, hours, created_at, created_by` | 個人工作日誌 |
| `contractors` | `id PK, name, id_number, nationality, has_union_insurance, phone, email, address, line_id, bank_*, notes, active, id_card_image, id_card_image_back, created_at, updated_at` | 外包人員 |
| `payslips` | `id PK, slip_no UNIQUE, contractor_id FK, contractor_name, income_type, gross_amount, tax_withheld, nhi_supplement, net_amount, payment_method, slip_date, status, tax_rules_version, export_count, export_log, data_json, created_by, created_at, updated_at` | 勞報單 |
| `payslip_seq` | `month PK, seq` | 勞報單月序號 |
| `login_rate_limit` | `ip PK, locked_until` | 登入失敗鎖定持久化（DB v11） |
| `daily_tasks` | `id PK, task_date, title, description, category, priority, assigned_to JSON, supervisors JSON, created_by, created_at, updated_at, is_deleted, recurrence_type, recurrence_days JSON, recurrence_end_date` | 每日工作事項主表（DB v13+v14 週排程+v16 supervisors） |
| `daily_task_completions` | `id PK, task_id FK, occurrence_date, username, completed, report, completed_at` `UNIQUE(task_id, occurrence_date, username)` | 人員完成回報記錄（DB v14 重建，occurrence_date 支援週排程） |
| `schema_version` | `id=1 PK, version, applied_at` | DB migration 版本追蹤 |

### §4.2 · data_json 結構（quotations）

```json
{
  "quoteNo": "MQ-202507-001",
  "customerName": "...", "projectName": "...",
  "salesPerson": "...", "salesPersonId": null,
  "quoteDate": "YYYY-MM-DD", "validDays": 30,
  "items": [{ "description":"", "brand":"", "qty":1, "unit":"台", "cost":0, "margin":0, "unitPrice":0, "amount":0, "notes":"" }],
  "tot": { "total":0, "pretax":0, "directMarginPct":0, "netMarginPct":0 },
  "dealTag": "已成案",            // 同步至 quotations.deal_tag
  "settlement": { "status":"finalized", "summary":{...}, "editHistory":[...] },  // 同步 settle_status
  "approval": {
    "requestedBy":"", "requestedByDisplay":"", "requestedAt":"",
    "tiers":[{ "order":0, "approvers":[{"userId":1,"username":"","displayName":"","status":"pending","approvedAt":null}] }],
    "currentTier": 0,
    "status":"approved", "approvedBy":"", "approvedByDisplay":"", "approvedAt":""
  },
  "caseRecord": {
    "stages":[{"id":1,"label":"","done":false}],
    "devices":[{"name":"","sn":"","mac":"","warrantyStart":"","warrantyMonths":12}],
    "materials":[{"id":1,"name":"","model":"","qty":1,"ordered":false,"arrived":false}],
    "payment":{ "items":[{"type":"頭款","pct":30,"received":false,"receivedAt":"","receivedBy":"","actualAmount":null,"feeAmount":0,"invoiceNo":""}] },
    "roles":{},  "milestones":[],
    "_expectedUpdatedAt":"..."   // 樂觀鎖（送出時帶，API 驗後移除）
  },
  "editHistory":[{ "rev":1, "at":"", "by":"", "byDisplay":"", "type":"quote_edit" }],
  "statusLog":[{ "at":"","user":"","from":"","to":"","note":"" }]
}
```

### §4.3 · 熱路徑欄位同步（helpers/quotations.py）

- `deal_tag` / `settle_status` 為正規欄位，列表/報表/儀表板優先讀欄位
- 讀取兼容：`SQL_DEAL_TAG` = `COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '')`
- 所有寫入統一走 `save_quotation_json()`（`helpers/quotations.py:24`）→ 自動同步 + 更新 `updated_at`

### §4.4 · 樂觀鎖

| 端點 | 請求欄位 | 衝突回應 |
|------|---------|--------|
| `PATCH /quotations/{no}/case-record` | `_expectedUpdatedAt` | 409 |
| `PATCH /quotations/{no}/payment/{idx}` | `_expectedUpdatedAt` | 409 |
| `PATCH /customers/{id}/visits` | `expectedUpdatedAt` | 409 |
| `PATCH /suppliers/{id}/visits` | `expectedUpdatedAt` | 409 |

### §4.5 · Migration 清單

| 版本 | 函式 | 內容 |
|------|------|------|
| v1 | `_m001_export_columns` | quotations.export_count / export_log |
| v2 | `_m002_sessions_expires` | sessions.expires_at |
| v3 | `_m003_contractor_images` | contractors.id_card_image / back |
| v4 | `_m004_unlock_password` | users.unlock_password_hash |
| v5 | `_m005_must_change_password` | users.must_change_password |
| v6 | `_m006_hot_columns` | quotations.deal_tag / settle_status + 索引 |
| v7 | `_m007_fix_legacy_display_names` | 顯示名稱歷史修正 |
| v8 | `_m008_fix_legacy_owner_names` | jeff 顯示名稱修正 |
| v9 | `_m009_migrate_legacy_visits` | 客戶拜訪格式遷移 |
| v10 | `_m010_sales_person_id` | quotations.sales_person_id FK + 索引 |
| v11 | `_m011_login_rate_limit` | login_rate_limit 表 |
| v12 | `_m012_project_assigned_users` | projects.assigned_user_ids JSON 欄位 |
| v13 | `_m013_daily_tasks` | daily_tasks + daily_task_completions 表 + 索引 |
| v14 | `_m014_weekly_recurrence` | daily_tasks 加 recurrence 欄位；daily_task_completions 重建加 occurrence_date，UNIQUE 改為 (task_id, occurrence_date, username) |
| v15 | `_m015_daily_task_password` | users.daily_task_pw_hash（每日工作事項管理視角解鎖密碼） |
| v16 | `_m016_daily_task_supervisors` | daily_tasks.supervisors TEXT NOT NULL DEFAULT '[]'（負責主管 username 陣列） |

---

## §5 · 共用函式庫（helpers/）

### §5.1 · helpers/auth.py — 認證與授權

| 函式 | 位置 | 說明 |
|------|-----|------|
| `_hash_pw(password)` | `auth.py:42` | PBKDF2-SHA256 260k，回傳 `salt_hex:dk_hex` |
| `_verify_pw(password, stored)` | `auth.py:48` | 支援舊 sha256（無`:`）和新 PBKDF2 |
| `_hash(password)` | `auth.py:38` | 舊式 sha256（僅遺留用途） |
| `is_weak_password(password)` | `auth.py:59` | len<8 或在黑名單 |
| `_require_user(authorization, require_superadmin=False)` | `auth.py:93` | 驗 Bearer token → 回傳 user dict；失敗拋 401/403 |
| `_tok(auth)` | `auth.py:115` | 從 "Bearer xxx" 提取 token 字串 |

### §5.2 · helpers/audit.py — 稽核與通知

| 函式 | 位置 | 說明 |
|------|-----|------|
| `_audit(token, action, target_type, target_id, target_label, detail)` | `audit.py:27` | 寫入 audit_log；token 可為空（system） |
| `_notify(username, type_, ref_id, ref_label, message)` | `audit.py:11` | 寫入 notifications（in-app 通知） |

### §5.3 · helpers/quotations.py — 報價熱路徑

| 函式/常數 | 位置 | 說明 |
|----------|-----|------|
| `SQL_DEAL_TAG` | `quotations.py:8` | 讀 deal_tag 的 SQL 片段（欄位 → JSON fallback） |
| `SQL_SETTLE_STATUS` | `quotations.py:9` | 讀 settle_status 的 SQL 片段 |
| `quote_hot_fields(q_dict)` | `quotations.py:14` | 從 data dict 提取 (deal_tag, settle_status) |
| `save_quotation_json(conn, quote_no, data, status=None, updated_at=None)` | `quotations.py:24` | 統一寫入 quotations：data_json + deal_tag + settle_status + (optional)status |

### §5.4 · helpers/settings.py — 系統設定 CRUD

| 函式 | 說明 |
|------|------|
| `_get_setting(key, default=None)` | 讀 system_settings；回傳 Python dict/value |
| `_set_setting(key, value)` | 寫 system_settings（JSON 序列化） |

常用 key：`approval_flow`、`email_notify`、`edge_path`、`pdf_base_path`、`company_profile`、`tax_rules`、`operating_targets`（年度目標達成率）、`dt_overdue_last_check`（每日工作事項逾期 guard）

### §5.5 · helpers/email_notify.py — Email 通知

| 函式 | 觸發時機 | 收件人來源 |
|------|---------|----------|
| `notify_approval_request(quote_no, customer, approver_usernames)` | PUT /quotations 首次/一般送審 | 當層 approvers `users.email` |
| `notify_next_tier(quote_no, customer, tier_no, total, approver_usernames)` | 前層全員通過 → 輪到下一層 | 下一層 approvers |
| `notify_approved(quote_no, customer, approved_by, requester_username)` | 全員通過 → 已送出 | 申請人 + admin/superadmin |
| `notify_returned(quote_no, new_quote_no, customer, note, requester_username)` | `POST /reject`：退回修改 | 申請人（含退回原因 note） |
| `notify_resubmit_requester(new_no, orig_no, customer, requester, approver_names)` | `PUT /quotations`：退回改版重送 | 申請人（確認信，列等待簽核人） |
| `notify_settlement_finalized(quote_no, customer, finalized_by)` | 精算 finalized | admin/superadmin |
| `notify_daily_task_assigned(task_id, title, task_date, assignee_usernames)` | 工作事項建立/新指派 | 被指派使用者 `users.email` |
| `notify_daily_task_completed(task_id, title, task_date, completed_by, display, report, supervisor_usernames=None)` | 人員回報完成時 | 若 supervisors 設定：僅通知指定主管；否則通知所有 admin/superadmin |
| `notify_daily_task_overdue(task_id, title, task_date, username, display, supervisor_usernames=None)` | 每日 08:00 掃昨日未完成 | 被指派人 + 指定主管（若有）；否則 + 所有 admin/superadmin |
| `_build_html(..., intro='', button_text='前往系統查看')` | 內部 HTML 模板 | 支援 intro 段落 + 自訂按鈕文字 |
| `_admin_emails()` | 計算值（唯讀） | `users` WHERE role IN (admin, superadmin) AND email != '' |
| `_async_send(to, subject, html)` | 非同步（daemon thread） | — |
| `_send_raising(to, subject, html)` | 測試端點同步呼叫（拋出例外） | — |

### §5.6 · helpers/startup.py — 啟動流程

啟動順序（main.py:144-152）：
```
init_db()                → db.py:31（建表 + migration）
init_default_admin()     → startup.py（新裝時建 jeff + 寫臨時密碼檔）
flag_weak_passwords()    → startup.py（掃描所有帳號，弱密碼標記 must_change_password=1）
init_unlock_passwords()  → startup.py（清除歷史弱解鎖密碼）
_cleanup_sessions()      → startup.py（清除過期 session）
_ensure_archive_dirs()   → archive.py（建立備份目錄）
_schedule_daily()        → archive.py（每 2h Timer）
_schedule_weekly()       → archive.py（每 6h Timer）
auth.init_rate_limiting()→ routers/auth.py:67（從 DB 還原鎖定狀態）
```

---

## §6 · API 端點完整列表

### §6.1 · 認證與使用者（routers/auth.py）

| Method | Path | 位置 | 權限 | 說明 |
|--------|------|-----|------|------|
| GET | `/api/ping` | `auth.py:164` | 無 | 心跳 |
| POST | `/api/auth/login` | `auth.py:169` | 無（rate-limited） | 登入；回傳 token + mustChangePassword |
| POST | `/api/auth/logout` | `auth.py:219` | Bearer | 刪 session |
| GET | `/api/auth/me` | `auth.py:231` | Bearer | 目前 session 資訊 |
| PATCH | `/api/auth/change-password` | `auth.py:257` | Bearer | 修改密碼；清除其他 session |
| POST | `/api/auth/verify-unlock` | `auth.py:438` | superadmin | 驗解鎖密碼（報價編輯前） |
| GET | `/api/users` | `auth.py:297` | Bearer | 使用者列表 |
| POST | `/api/users` | `auth.py:314` | superadmin | 建立使用者 |
| PUT | `/api/users/{id}` | `auth.py:350` | superadmin | 更新使用者（含重設密碼） |
| DELETE | `/api/users/{id}` | `auth.py:383` | superadmin | 刪除使用者 |
| PATCH | `/api/users/{id}/active` | `auth.py:404` | superadmin | 啟用/停用帳號 |
| GET | `/api/users/selectable` | `auth.py:426` | Bearer | 可選使用者清單（for 簽核設定） |
| PATCH | `/api/users/{id}/unlock-password` | `auth.py:458` | superadmin | 設定解鎖密碼 |
| POST | `/api/auth/verify-daily-task-unlock` | `auth.py` | superadmin | 驗每日工作事項管理密碼（428=未設定，403=錯誤） |
| PATCH | `/api/users/{id}/daily-task-password` | `auth.py` | superadmin | 設定每日工作事項密碼（僅允許對 superadmin 帳號設定） |

**登入資料流**：
```
POST /api/auth/login  { username, password }
→ auth.py:169：_rl_check(ip)
→ SELECT users WHERE username=? AND active=1
→ _verify_pw() → PBKDF2 驗證
→ 弱密碼？→ must_change_password=1
→ 舊 sha256？→ 升級雜湊
→ INSERT sessions (token, expires_at=+30天)
→ _rl_clear(ip) + _audit('auth.login')
← { token, userId, username, displayName, role, modules, mustChangePassword }
```

### §6.2 · 報價單（routers/quotations.py）

| Method | Path | 位置 | 權限 | 說明 |
|--------|------|-----|------|------|
| GET | `/api/next-quote-no` | `quotations.py:144` | Bearer | Peek 下一個單號（不保留） |
| GET | `/api/quotations` | `quotations.py:163` | Bearer | 列表（角色過濾；含 deal_tag / settle_status / current_stage） |
| POST | `/api/quotations` | `quotations.py:256` | Bearer | 建立草稿；觸發備份 |
| GET | `/api/quotations/{no}` | `quotations.py:242` | Bearer | 單筆完整資料 |
| PUT | `/api/quotations/{no}` | `quotations.py:325` | Bearer | 更新（含解鎖編輯）；送審時建 tiers；觸發備份 |
| DELETE | `/api/quotations/{no}` | `quotations.py:549` | Bearer | 刪除（僅草稿） |
| PATCH | `/api/quotations/{no}/status` | `quotations.py:477` | superadmin | 直接變更狀態（白名單） |
| PATCH | `/api/quotations/{no}/deal-tag` | `quotations.py:507` | Bearer（限制） | 更新案件進度（未成案/已成案 需 admin+，已結案需 superadmin） |
| PATCH | `/api/quotations/{no}/case-record` | `quotations.py:568` | Bearer | 更新案件記錄（樂觀鎖） |
| PATCH | `/api/quotations/{no}/payment/{idx}` | `quotations.py:622` | Bearer | 標記收款（樂觀鎖） |
| GET | `/api/quotations/{no}/settlement` | `quotations.py:674` | Bearer | 讀精算資料 |
| PUT | `/api/quotations/{no}/settlement` | `quotations.py:690` | Bearer | 寫精算（finalized 後 superadmin only） |
| POST | `/api/quotations/{no}/export` | `quotations.py:594` | Bearer | 記錄 PDF 匯出（更新 export_count） |
| GET | `/api/quotations/{no}/pdf-download` | `quotations.py:1051` | Bearer | Edge 產 PDF 並下載（?internal=true 含成本） |
| GET | `/api/approval-queue` | `quotations.py:741` | Bearer | 全部待審清單（依申請人分組） |
| GET | `/api/approval-queue/count` | `quotations.py:801` | Bearer | 輪到我的件數（sidebar badge 用） |
| POST | `/api/quotations/{no}/approve` | `quotations.py:828` | Bearer（簽核人） | 簽核通過（並行層） |
| POST | `/api/quotations/{no}/reject` | `quotations.py:923` | Bearer（簽核人） | 退回修改（升版 -Rn，清 approval，回草稿） |
| POST | `/api/quotations/{no}/reject-final` | `quotations.py:1095` | Bearer（簽核人） | 拒絕結案（永久鎖定，status=已拒絕）✅ 前端已對接 |
| POST | `/api/quotations/{no}/recall` | `quotations.py:~450` | Bearer（原申請人） | 收回草稿：待審核/簽核中 → 草稿，清 approval，僅 requestedBy 可執行 |

**報價單建立/更新資料流（PUT /api/quotations/{no}）**：
```
前端 Alpine.js quotationForm() / saveQuotation()
→ PUT /api/quotations/{no}
  body: { status, data: {quoteNo, customerName, projectName, salesPerson, items[], tot, approval:{...}, ...}, created_by }
→ quotations.py:325 update_quotation()
  → q.pop('_isUnlockEdit')  // 解鎖旗標
  → 若 is_unlock_edit：驗 superadmin + append editHistory + force 待審核
  → 若 new_status=待審核：
      → 讀 DB 舊狀態（判斷是否為新送審）
      → 若無 tiers：從 _get_setting('approval_flow') 讀設定 → _setting_to_active_tiers()
      → 寄通知至 currentTier 的 pending approvers：_notify() + notify_approval_request/next_tier()
  → quote_hot_fields(q) → (deal_tag, settle_status)
  → UPDATE quotations SET data_json=JSON, deal_tag=?, settle_status=? ...
  → threading.Thread(_backup_quotation)  // 非同步備份
  → _audit('quotation.update')
← { quote_no, updated_at, status }
```

### §6.3 · 簽核流程（routers/quotations.py）

**簽核通過資料流（POST /approve）**：
```
前端 approval-queue.html approveQuote() 或 quotation-form.html
→ POST /api/quotations/{no}/approve  { approvedByDisplay, note }
→ quotations.py:828 approve_quotation()
  → 讀 data_json.approval → _active_tiers() / _current_tier_idx()
  → 找自己在當層 approvers（username match）
  → my_entry.status = "approved", approvedAt = now
  → tier_done？→ appr.currentTier++
      → all_done？→ status=已送出 + save_quotation_json()
                 → _generate_quotation_pdf() async
                 → notify_approved()
      → 否則 → notify_next_tier() + _notify() 下層
  → _audit('quotation.approve')
← { ok, allDone }
```

**退回修改資料流（POST /reject）**：
```
→ quotations.py reject_quotation()
  → _next_revision_no(quote_no)  // MQ-202501-001 → MQ-202501-001-R1
  → 寫入 data_json.returnInfo = { returnedBy, returnedByDisplay, returnedAt, note, originalQuoteNo, previousItems[] }
  → 清 approval, 升版 quoteNo, status=草稿
  → UPDATE quotations SET quote_no=new_no, status='草稿' ...
  → _notify(requester) + notify_returned()  // 申請人收退回通知（含退回原因）
← { ok, new_quote_no }

重新送審（退回改版）資料流：
PUT /api/quotations/MQ-xxx-R1  { status:'待審核', data:{ ...q, returnInfo:{...} } }
→ is_new_submission = True（DB status='草稿'）
→ label = "（退回改版）"（因 q.returnInfo 存在）
→ 載入 approval_flow tiers → 通知簽核人（標題含「退回改版」）
→ notify_resubmit_requester()  // 申請人收確認信（「您的修改版已送審，等待 XXX 簽核」）
← 正常 { quote_no, updated_at, status }
```

### §6.4 · 客戶與供應商（routers/customers.py, suppliers.py）

| Method | Path | 位置 | 權限 | 說明 |
|--------|------|-----|------|------|
| GET | `/api/customers` | `customers.py:24` | Bearer | 全部客戶（含 data_json 展開） |
| GET | `/api/customers/{id}` | `customers.py:44` | Bearer | 單一客戶詳情 |
| POST | `/api/customers` | `customers.py:60` | Bearer | 建立；觸發備份 |
| PUT | `/api/customers/{id}` | `customers.py:81` | Bearer | 更新；觸發備份 |
| DELETE | `/api/customers/{id}` | `customers.py:131` | Bearer | 刪除；觸發備份 |
| PATCH | `/api/customers/{id}/visits` | `customers.py:100` | Bearer | 更新拜訪紀錄（樂觀鎖）；觸發備份 |
| GET | `/api/suppliers` | `suppliers.py:24` | admin+ | 非管理員回空陣列 |
| POST | `/api/suppliers` | `suppliers.py:46` | Bearer | 建立 |
| PUT | `/api/suppliers/{id}` | `suppliers.py:68` | Bearer | 更新 |
| DELETE | `/api/suppliers/{id}` | `suppliers.py:88` | Bearer | 刪除 |
| PATCH | `/api/suppliers/{id}/visits` | `suppliers.py:105` | Bearer | 更新往來紀錄（樂觀鎖） |

**客戶選取資料流（報價單選客戶）**：
```
前端 quotation-form.html selectCustomer(cid)
→ GET /api/customers/{id}
→ 回傳 { id, name, taxId, phone, contacts:[], address, ... }
→ Alpine 強制覆寫 q.customerName / q.contactName / q.contactPhone 等
（每次選取都重新 fetch，不使用快取）
```

### §6.5 · 儀表板與統計（routers/dashboard.py）

| Method | Path | 位置 | 權限 | 說明 |
|--------|------|-----|------|------|
| GET | `/api/now` | `dashboard.py:40` | 無 | 伺服器時間 |
| GET | `/api/company/tax/{tax_id}` | `dashboard.py:46` | 無 | GCIS 統編查詢（外部 API） |
| GET | `/api/company/search?q=` | `dashboard.py:59` | 無 | GCIS 公司名稱搜尋 |
| GET | `/api/dashboard/stats` | `dashboard.py:72` | Bearer | KPI + 待審清單 + 收款/保固/毛利 |
| GET | `/api/dashboard/monthly` | `dashboard.py:302` | admin+ | 近 12 月成案趨勢 |
| GET | `/api/devices` | `dashboard.py:344` | Bearer | 設備列表（含保固剩餘天數） |
| GET | `/api/receivables` | `dashboard.py:414` | admin+ | 應收帳款明細 |
| GET | `/api/sales-orders` | `dashboard.py:497` | Bearer | 銷售訂單（已成案/已結案） |
| GET | `/api/materials-summary` | `dashboard.py:554` | Bearer | 叫料追蹤摘要 |

**儀表板 stats 計算重點**（dashboard.py:72）：
- `waitingForMe`：遍歷所有 status IN (待審核, 簽核中) → `tiers[currentTier].approvers` 包含當前 user → count
- `paymentItems`：已成案/已結案 → `caseRecord.payment.items` → 未收款項目
- `warrantyWarnings`：`caseRecord.devices` → `_warranty_expiry()` → daysLeft ≤ 90
- `marginTop5`：狀態=已送出 或 deal_tag=已成案/已結案 → net_margin_pct 排序前 5

### §6.6 · 系統設定（routers/system.py）

| Method | Path | 位置 | 權限 | 說明 |
|--------|------|-----|------|------|
| GET/PUT | `/api/settings/approval-flow` | `system.py:46/53` | GET:Bearer；PUT:superadmin | 簽核流程 tiers 設定 |
| GET | `/api/settings/operating-targets` | `system.py` | Bearer | 讀年度目標設定（`operating_targets` key） |
| PUT | `/api/settings/operating-targets` | `system.py` | superadmin | 寫年度目標（`{ year, annual:{revenue,newCases,collectionAmount,collectionRate,avgNetMarginPct,grossProfit}, salesperson:[{name,revenue,cases}] }`） |
| GET | `/api/notifications/mine` | `system.py:66` | Bearer | 我的通知（最近 50 筆） |
| PATCH | `/api/notifications/{id}/read` | `system.py:81` | Bearer | 標記已讀 |
| PATCH | `/api/notifications/read-all` | `system.py:93` | Bearer | 全部標記已讀 |
| GET | `/api/audit-log` | `system.py:108` | admin+ | 稽核記錄（可篩 action/q） |
| GET/POST/PUT/DELETE | `/api/work-logs` | `system.py:140-233` | Bearer | 工作日誌（PUT/DELETE 非 admin 只能自己） |
| GET/PUT | `/api/settings/company-profile` | `system.py:244/250` | GET:Bearer；PUT:superadmin | 公司資料（用於勞報單） |
| GET/PATCH | `/api/settings/edge-path` | `system.py:263/273` | superadmin | Edge 瀏覽器路徑 |
| GET/PATCH | `/api/settings/pdf-base-path` | `system.py:288/296` | superadmin | PDF 存檔路徑 |
| GET | `/api/settings/email-notify` | `system.py:322` | superadmin | Email 設定（密碼遮蔽為 ••••••••） |
| PUT | `/api/settings/email-notify` | `system.py:335` | superadmin | 儲存 Email 設定（傳遮蔽值不更新密碼） |
| POST | `/api/settings/email-notify/test` | `system.py:349` | superadmin | 寄測試信（SMTP 失敗回 502） |

### §6.7 · 報表（routers/reports.py）

| Method | Path | 位置 | 權限 | 說明 |
|--------|------|-----|------|------|
| GET | `/api/reports/financial` | `reports.py` | admin+ | 財務報表資料（JSON；含 `targets`、`achievement` 欄位） |
| GET | `/api/reports/financial/excel` | `reports.py` | admin+ | 下載 Excel（openpyxl，8 Sheet；新增「目標達成率」分頁） |
| GET | `/api/reports/financial/pdf` | `reports.py` | admin+ | 下載 PDF（Edge headless；含年度目標達成率章節） |

查詢參數：`?period=YYYY-MM` 或 `?period=YYYY-QN`（預設當月）

**報表資料收集（`_collect()`，reports.py:52）**：
- 所有 deal_tag IN (已成案, 已結案) 的報價單
- 計算：本期收款、未收款、案件清單、業務員績效、毛利分析、保固預警

**年度目標達成率（`_compute_achievement()`，reports.py）**：
- 從 `system_settings.operating_targets` 讀取年度目標（`_augment_with_targets()` 在 3 個端點中統一注入）
- 篩選 `casesAll` 中 `quoteDate` 以目標年份開頭的 YTD 案件
- 計算 6 大指標的 actual / target / rate / prorata（按時間比例目標）
- 達成率色碼：≥95% 綠色 / 80-94% 橘色 / <80% 紅色
- `targets.year` 需與報表期間年份相符才顯示達成率（否則 `hasTargets: false`）

### §6.8 · 料號（routers/parts.py）

| Method | Path | 位置 | 說明 |
|--------|------|-----|------|
| GET | `/api/parts` | `parts.py:14` | 列表（無需認證） |
| POST | `/api/parts` | `parts.py:32` | 建立 |
| PUT | `/api/parts/{id}` | (後續 route) | 更新 |
| DELETE | `/api/parts/{id}` | (後續 route) | 停用（active=0） |

### §6.9 · 專案（routers/projects.py）

| Method | Path | 位置 | 說明 |
|--------|------|-----|------|
| GET | `/api/projects` | `projects.py:56` | 列表（可篩 status/q/case_no） |
| POST/PUT/DELETE | `/api/projects/{id}` | projects.py | CRUD |
| GET/POST/PUT/DELETE | `/api/project-logs` | projects.py | 專案工作日誌 |
| POST | `/api/project-logs/{id}/photos` | projects.py | 照片上傳（Pillow 浮水印） |
| GET | `/api/photo-token?path=` | `projects.py:24`（_make_photo_token） | 取 1h HMAC signed token |
| GET | `/api/uploads/{path}?pt=` | projects.py | 照片（`?pt=` 優先；`?token=` fallback） |

### §6.10 · 外包人員（routers/contractors.py）

| Method | Path | 位置 | 權限 | 說明 |
|--------|------|-----|------|------|
| GET | `/api/contractors` | `contractors.py:115` | superadmin | 列表（不含 id_card 圖片） |
| POST | `/api/contractors` | `contractors.py:136` | superadmin | 建立 |
| GET/PUT | `/api/contractors/{id}` | `contractors.py:162/173` | superadmin | 單筆/更新 |
| PATCH | `/api/contractors/{id}/active` | `contractors.py:200` | superadmin | 啟停 |
| GET/PUT | `/api/contractors/{id}/id-card` | `contractors.py:218/233` | superadmin | 身分證影本（PUT 自動加浮水印） |

### §6.11 · 勞報單（routers/payslips.py）

| Method | Path | 位置 | 權限 | 說明 |
|--------|------|-----|------|------|
| GET | `/api/tax-rules` | `payslips.py:115` | superadmin | 稅率設定（from system_settings） |
| GET | `/api/next-slip-no` | `payslips.py:121` | superadmin | Peek 下一勞報單號 PS-YYYYMM-NNN |
| GET | `/api/payslips` | `payslips.py:134` | superadmin | 列表（?month / ?contractor_id） |
| POST | `/api/payslips` | `payslips.py:165` | superadmin | 建立（自動計算稅款） |
| GET/PUT/DELETE | `/api/payslips/{no}` | `payslips.py:230/243/285` | superadmin | CRUD |
| POST | `/api/payslips/{no}/export` | `payslips.py:302` | superadmin | 匯出 + 產 PDF 存檔 + status=已匯出 |
| GET | `/api/payslips/{no}/archive/{idx}` | `payslips.py:366` | superadmin | 調閱歷史 PDF（fallback 重產） |
| GET | `/api/payslips/{no}/pdf-download` | `payslips.py:389` | superadmin | 即時產 PDF |

**稅務計算（`_calc()`，payslips.py:50）**：
- 輸入：gross, income_type（50/9A/9B）, nationality（居民/非居民）, has_union_insurance
- 計算：withholding tax（依申報類別 + 門檻）+ 二代健保補充費（非工會加保者）
- 規則讀 `system_settings.tax_rules`（可由 superadmin 更新）

### §6.12 · 每日工作事項（routers/daily_tasks.py）

| Method | Path | 權限 | 說明 |
|--------|------|------|------|
| GET | `/api/daily-tasks` | Bearer | 列表（`?date=YYYY-MM-DD` 或 `?year_month=YYYY-MM`；非 superadmin 只看指派給自己的；`?username=` 限 superadmin 過濾） |
| GET | `/api/daily-tasks/{id}` | Bearer | 單筆（含 assignees + completions + supervisors 欄位） |
| POST | `/api/daily-tasks` | superadmin | 建立並派發（自動 in-app + Email 通知被指派人） |
| PUT | `/api/daily-tasks/{id}` | superadmin | 更新（只對新增的指派對象發通知） |
| DELETE | `/api/daily-tasks/{id}` | superadmin | 軟刪除（`is_deleted=1`） |
| PATCH | `/api/daily-tasks/{id}/complete` | Bearer（被指派人） | 回報完成：`{ completed:true, report:"...", occurrence_date:"YYYY-MM-DD" }`；通知指定主管（若無則通知全體 admin/superadmin） |
| GET | `/api/daily-tasks/{id}/history` | Bearer（被指派人或 superadmin） | 分頁歷史回報（軟刪除後仍可讀）；`?page=&per_page=`；回傳 `{task, total_occurrences, occurrences:[{occurrence_date, weekday, done_count, total, all_done, completions}]}` |
| GET | `/api/daily-tasks/{id}/history/export` | Bearer | CSV 下載（UTF-8 BOM）：工作事項/日期/星期/指派人員/完成狀態/完成時間/回報內容 |

**`_enrich()` 擴充欄位**：每筆 task 回傳時補齊 `assigned_to`（list）、`assignees`（含 displayName）、`completions`（含 completed/report/completedAt/displayName）、`supervisors`（username list）、`supervisors_info`（含 displayName）

**週排程 (`recurrence_type="weekly"`)**: `recurrence_days`（0=Mon…6=Sun），每月 GET 時展開成多筆 occurrence；`occurrence_date` 帶入 completions UNIQUE key；`recurrence_end_date` 可選截止

**管理視角解鎖**：superadmin 需先 POST `/api/auth/verify-daily-task-unlock` 成功後，前端記 `sessionStorage('dt_unlocked','1')`，才可看全體任務 / 新增 / 編輯 / 刪除；鎖定時 GET 自動帶 `?username=自身`

**逾期通知機制**：`schedule_overdue_check()` 在 main.py 啟動時呼叫；每日 08:00 執行 `_check_overdue_and_notify()`；guard key `dt_overdue_last_check`（system_settings）寫在 email 發送 **之前**，防止重啟重寄；08:00 前重啟不觸發 catch-up

---

## §7 · 前端頁面 → API 對應表

### §7.1 · 核心業務頁面

> **JS 來源說明**：除 case-management.html 和 reports.html 外，其餘頁面 Alpine 邏輯均為 **inline `<script>`**（不載入 `js/` 目錄）。

| 頁面 | JS 來源 | 主要 API 呼叫 |
|------|---------|-------------|
| `index.html`（儀表板） | inline `<script>` | GET /api/dashboard/stats, GET /api/dashboard/monthly |
| `pages/quotations.html` | inline `<script>` | GET /api/quotations, PATCH /deal-tag, GET /api/users/selectable；**篩選 Tab**：「全部(不含未成案)」預設排除 `deal_tag=未成案`，新增「未成案」Tab（`isDealTag:true`） |
| `pages/quotation-form.html` | inline `<script>` + **SortableJS CDN** | GET/POST/PUT /api/quotations/{no}, **PATCH /status**（superadmin 手動調整）, GET /api/customers/{id}, POST /verify-unlock, GET /api/next-quote-no, POST /api/quotations/{no}/export, GET /pdf-download |
| `pages/approval-queue.html` | inline `<script>` | GET /api/approval-queue, POST /approve, POST /reject, POST /reject-final（✅ 已對接） |
| `pages/case-management.html` | **`js/case-management.js`**（✅ 唯一外部載入之一） | GET /api/auth/me（驗證）, GET /api/users/selectable, GET /api/quotations?deal_tag=已成案,已結案（列表）, GET /api/quotations/{no}（單筆）, GET /api/projects?case_no=（查關聯專案）, POST /api/projects（建立關聯專案）, PATCH /quotations/{no}/case-record（儲存，含付款資料）, PATCH /quotations/{no}/deal-tag（完結案用）, POST /api/auth/logout；⚠️ `/payment/{idx}` 不再單獨呼叫，付款資料統一隨 case-record 儲存 |
| `pages/settlement.html` | inline `<script>` | GET/PUT /api/quotations/{no}/settlement（從 case-management.html「前往精算頁面」按鈕進入） |
| `pages/customers.html` | inline `<script>` | GET/POST/PUT/DELETE /api/customers, GET /api/company/tax/{id} |
| `pages/customer-log.html` | inline `<script>` | GET /api/customers/{id}, PATCH /visits |
| `pages/suppliers.html` | inline `<script>` | GET/POST/PUT/DELETE /api/suppliers |
| `pages/supplier-log.html` | inline `<script>` | GET /api/suppliers/{id}, PATCH /visits |
| `pages/parts.html` | inline `<script>` | GET/POST/PUT/DELETE /api/parts |
| `pages/projects.html` | inline `<script>` | GET/POST/PUT/DELETE /api/projects, /project-logs, /photos |
| `pages/reports.html` | **`js/reports.js`**（✅ 唯一外部載入之二） | GET /api/reports/financial（JSON）, /excel, /pdf |
| `pages/receivables.html` | inline `<script>` | GET /api/receivables |
| `pages/devices.html` | inline `<script>` | GET /api/devices |
| `pages/procurement.html` | inline `<script>` | GET /api/materials-summary（dashboard.py:554） |
| `pages/warranty.html` | inline `<script>` | GET /api/devices?deal_tag=已結案（dashboard.py:344） |
| `pages/work-log.html` | inline `<script>` | GET/POST/PUT/DELETE /api/work-logs |
| `pages/daily-tasks.html` | inline `<script>` | GET/POST/PUT/DELETE/PATCH /api/daily-tasks（superadmin 全功能；其他人員唯讀 + 完成回報） |
| `pages/audit-log.html` | inline `<script>` | GET /api/audit-log（admin+） |

**幽靈頁面（2026-07-20e 已全部修復）**

| 頁面 | 狀態 | 處置 |
|------|------|------|
| `pages/sales-orders.html` | ✅ 已加 sidebar 入口（財務區） | sidebar.js 新增 `ni(pg('sales-orders.html'), 'order', '銷售訂單', ...)` |
| `pages/settlement.html` | ✅ 已補 notif.js + API 修正 | 從 case-management.html「前往精算頁面」按鈕進入 |

### §7.2 · 系統管理頁面

| 頁面 | JS 來源 | 主要 API 呼叫 |
|------|---------|-------------|
| `pages/users.html` | inline `<script>` | GET/POST/PUT/DELETE/PATCH /api/users, PATCH /unlock-password, PATCH /daily-task-password；superadmin 行操作多「工作事項」按鈕（→ daily-tasks.html?username=xxx）；編輯超管帳號時新增「每日工作事項密碼」設定區塊 |
| `pages/approval-settings.html` | inline `<script>` ⚠️ `API=''` 模式 | GET/PUT /api/settings/approval-flow, GET /api/users/selectable |
| `pages/notification-settings.html` | inline `<script>` | GET/PUT /api/settings/email-notify, POST /test |
| `pages/contractors.html` | inline `<script>` | GET/POST/PUT/PATCH /api/contractors, GET/PUT /id-card |
| `pages/payslips.html` | inline `<script>` | GET /api/payslips, GET /next-slip-no |
| `pages/payslip-form.html` | inline `<script>` | GET/POST/PUT /api/payslips/{no}, GET /api/tax-rules, POST /export, GET /pdf-download |
| `pages/login.html` | inline `<script>` | POST /api/auth/login |
| `pages/change-password.html` | inline `<script>` | PATCH /api/auth/change-password |

> **⚠️ approval-settings.html API 模式偏差**：此頁使用 `const API = ''`，呼叫寫法為
> `fetch(\`${API}/api/settings/approval-flow\`)` → 實際 URL `/api/settings/...` ✅ 正確，但
> 與其他頁面的 `const API = '/api'` + `fetch(\`${API}/settings/...\`)` 模式不同。
> 從此頁複製代碼到其他頁面會造成 `/api/api/...` 雙前綴 404 錯誤。

### §7.3 · 全域載入（所有頁面必須）

```html
<!-- index.html（根目錄頁面） -->
<script src="static/notif.js"></script>
<script src="static/sidebar.js"></script>

<!-- pages/*.html（子目錄頁面） -->
<script src="../static/notif.js"></script>
<script src="../static/sidebar.js"></script>
```

- `notif.js:init()`：呼叫 GET /api/notifications/mine + GET /api/approval-queue/count（每頁載入時執行）
- `sidebar.js`：注入 Sidebar/Topbar HTML；偵測 mustChangePassword → 導向 change-password.html
- ⚠️ 注意：鈴鐺 unread badge 排除 `approval_request` 型通知；sidebar 角標（簽核數）來源獨立，兩者計數可能不一致

---

## §8 · 備份與還原

### §8.1 · 路徑

```
雲端（需 G: 掛載）
  G:\我的雲端硬碟\系統存檔\
    即時備份\報價單\{quote_no}.json
    即時備份\客戶\customers.json
    即時備份\供應商\suppliers.json
    每日備份\YYYY-MM-DD\  （7 表 JSON + motrix_erp.db）
    週備份\YYYY-WNN\

本機（不依賴 G:）
  backend\db_backups\YYYY-MM-DD\motrix_erp.db   ← SQLite Online Backup，保留 30 天
  backend\db_backups\quotation_instant\          ← G: 不可用時即時報價單 JSON fallback
  backup_alerts\BACKUP_ALERT.txt                ← 雲端異常警示
  backend\export_archive\{slip_no}_{idx}.pdf    ← 勞報單 PDF 存檔
```

### §8.2 · 觸發時機

| 觸發源 | 時機 | 函式 |
|--------|------|------|
| POST/PUT/DELETE /quotations | 每次寫入 | `threading.Thread(_backup_quotation)` → `archive.py` |
| POST/PUT/DELETE /customers | 每次寫入 | `threading.Thread(_backup_customers)` |
| POST/PUT/DELETE /suppliers | 每次寫入 | `threading.Thread(_backup_suppliers)` |
| `_schedule_daily()` Timer | 每 2h | 全量 JSON + SQLite 快照（.done marker 防重複） |
| `_schedule_weekly()` Timer | 每 6h | 同上（週目錄） |
| Windows 工作排程器 | 每日 02:00 | `backup_job.py`（server crash 也跑） |

**原子寫入**：所有 JSON 備份均先寫 `.tmp` 再 `os.replace()`（`archive.py:31`）

**audit_log 保留**：每次每日備份後執行 `_prune_audit_log(keep_days=730)`

---

## §9 · 前端規範

| 項目 | 規則 | 說明 |
|------|------|------|
| 框架 | Alpine.js CDN | x-data / x-bind / x-on |
| JS 載入順序 | `case-management.js` / `reports.js` 先於 Alpine CDN | non-defer；其餘頁面 inline Alpine（無外部 js/ 載入） |
| Auth | `init()` 中讀 localStorage.motrix_session | 無 token → 導向 login.html |
| API 呼叫 | `Authorization: Bearer {token}` header | **PATCH deal-tag 等所有 PATCH 均不可遺漏** |
| 自動存 | debounce 1.5s（`setDirty`） | `isDirty=false` 需在 API 成功回調內設定 |
| 客戶選取 | `selectCustomer()` async | 每次都 GET /api/customers/{id}，**強制覆寫**聯絡人 |
| No-cache | `.html/.css/.js` 皆 no-store | middleware 加 header，不需頁面自行處理 |
| Excel | SheetJS CDN | 客戶/供應商列表頁面 |
| 拖曳排序 | SortableJS v1.15.3 CDN（非 defer） | 僅 `quotation-form.html`；`initSortable()` 在 `init()` 末端 `$nextTick` 呼叫；鎖定時 `disabled` |
| XSS 防護 | 動態插入 API 資料一律用 DOM API | **禁止 innerHTML 插入非靜態內容** |

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
| 中 | ⚠️ **Photo token 重啟失效**：`_PHOTO_SECRET = secrets.token_bytes(32)`（projects.py）每次 process 啟動重新產生。既有 `<img ?pt=TOKEN>` 標籤在後端重啟後立即 401，直到用戶重新整理頁面觸發 re-fetch。前端無自動 retry 機制，圖片靜默顯示破圖。 |
| 中 | ⚠️ **Email 三條靜默丟棄路徑**（均無 log）：① `enabled=false`（預設值）→ 所有事件靜默跳過；② 被通知者 `users.email` 欄位空 → `_lookup_emails()` 回傳 `[]` → 不送；③ 無任何 admin/superadmin 設 email → `_admin_emails()` 回傳 `[]` → 不送。看起來正常但通知永遠收不到。 |
| 中 | ⚠️ **steps→tiers 兩處獨立轉換邏輯**：舊資料格式轉換存在於 `system.py:31 _normalize_flow()`（設定讀取）和 `quotations.py _active_tiers()`（簽核執行）兩處，互不呼叫。修改 tiers 結構時必須同步更新兩處，否則「設定頁顯示正確，實際簽核行為不同」。 |
| ~~低~~ | ~~`approval-settings.html` 使用 `const API = ''` 模式~~ — **已修復（2026-07-20e）**：改為 `const API = '/api'`，fetch URL 已同步修正。 |
| 低 | Sidebar 簽核角標（`/api/approval-queue/count`，即時狀態）與通知鈴鐺 unread count（`/api/notifications/mine`，歷史狀態）來源不同，會出現角標歸零但鈴鐺仍有 approval_request 未讀的視覺不一致。 |
| ~~低~~ | ~~`pages/sales-orders.html` 無 sidebar 入口~~ — **已修復（2026-07-20e）**：財務區新增導覽入口。 |
| ~~低~~ | ~~`pages/settlement.html` 無 API 呼叫~~ — **已修復（2026-07-20e）**：補 notif.js + API 模式，從 case-management 連結進入。 |
| 低 | `SQL_DEAL_TAG` / `SQL_SETTLE_STATUS` fallback（pre-v6 rows）：任何新增的直接 `SELECT deal_tag` 查詢（繞過 `quote_hot_fields()`）對舊資料靜默回傳空字串。 |
| 低 | `sales_person_id` 永久雙路徑（pre-v10 rows，FK=NULL）：新篩選查詢若僅用 `sales_person_id=?` 會靜默丟失所有舊資料。 |
| 低 | ⚠️ **品項 `type:'header'` PDF 行號**：`pdf_gen.py` 以 `real_idx` 計數（跳過標題行），但 `data_json.items` 中舊資料若無 `type` 欄位則全視為一般品項，行號正確；若日後從其他路徑直接讀 items 序號需注意跳過 `type==='header'`。 |
| 低 | ⚠️ **SortableJS 與 Alpine `x-for` key**：拖曳結束後由 `onEnd` 更新 `q.items` 陣列，Alpine 以 `:key="item.id"` 差異更新 DOM。若 item.id 重複（Date.now 在極快速新增下可能碰撞），排序結果可能錯位。 |
| **高** | ⚠️ **uvicorn 綁定 0.0.0.0:666，ERP 可從公網訪問**：`restart.bat:35` 使用 `--host 0.0.0.0`，若路由器有連接埠轉發或機器有公有 IP，外部 IP 可直接存取系統（已觀測到 `18.116.101.220`（AWS）等外部 IP 取得 200 OK on `/`）。短期處理：Windows 防火牆新增輸入規則，僅允許 `172.16.0.0/12` + `127.0.0.1` 存取 TCP 666；或取消路由器 Port 666 轉發。 |
| 低 | 區網 HTTPS／反向代理 |
| 低 | 關鍵 API 自動化測試 |
| 低 | 文件拆 `CHANGELOG.md` 與本速查分離 |

---

## §12 · 變更摘要（精簡）

### 2026-07-21c — 財務報表：營運目標及達成率

**新 API 端點（`routers/system.py`）**
- `GET /api/settings/operating-targets`：讀年度目標（Bearer 即可）
- `PUT /api/settings/operating-targets`：寫年度目標（superadmin；body: `{year, annual:{revenue,newCases,collectionAmount,collectionRate,avgNetMarginPct,grossProfit}, salesperson:[{name,revenue,cases}]}`）

**後端計算（`routers/reports.py`）**
- 新增 `_compute_achievement(year, targets, cases_all)`：計算 6 大年度指標的 YTD 實績 vs 目標（含達成率、按時間比例目標）+ 業務員個人配額達成
- 新增 `_augment_with_targets(data, d0)`：從 `system_settings` 讀 `operating_targets`，計算 `achievement`，注入 `data["targets"]` / `data["achievement"]`（3 個端點統一呼叫）
- `_build_excel()`：新增 Sheet 2「目標達成率」（6 指標表 + 業務員配額表；達標/追趕/落後三色背景）；原 Sheet 2-7 順移為 Sheet 3-8
- `_build_report_html()`：PDF 新增「年度目標達成率」章節（6 格 KPI 卡片 + 進度條 + 業務員表格）；注入 `{acv_html}` 於執行摘要後

**前端（`reports.html` + `reports.js`）**
- `reports.js`：新增 `targets` / `achievement` getters；`acvGrade/acvColor/acvBarPct` 輔助函式；`openTargetModal / addSpTarget / removeSpTarget / saveTargets` 方法；`targetModal / targetForm / targetSaving` 狀態
- `reports.html`：新增 Tab「目標達成率」（6 大指標 KPI 卡片 + 進度條 + 業務員達成率表格）；目標設定 Modal（superadmin only：年度 + 6 大指標 + 動態業務員配額行）；CSS 新增 `.acv-grid / .acv-card / .acv-bar-track / .acv-bar-fill / .btn-set-target / .tgt-2col / .tgt-sp-row`

**達成率計算邏輯**
- YTD 案件：篩選 `casesAll` 中 `quoteDate` 以目標年份（`d0[:4]`）開頭者
- 按時間比例目標：`target × (今日為今年第 N 天 / 全年天數)`；收款率 / 毛利率無按比例
- 平均淨毛利率：基於 `settleStatus=finalized` 的 YTD 精算案件
- `targets.year` 不符合報表期間年份 → `hasTargets: false` → 顯示「尚未設定」提示

---

### 2026-07-21b — 每日工作事項大幅擴充 + Email 商務改版

**常駐任務（週排程折疊）**
- 左面板拆成「常駐任務」（`.recurring-card`，黃底，每週排程去重只顯示一次）和「單次任務」（日期分組）兩區塊
- 常駐任務卡片：本日 N/M 進度 + `monthRate()` 本月完成率 badge + 指派人員 chips
- `filteredWeeklyTasks()` 去重：同 task.id 只取今日 occurrence（或當月首筆）；`weeklyTodayOcc()` 輔助

**跨日逾期通知**
- `_check_overdue_and_notify()` 每日 08:00 掃描昨日所有任務（once + weekly）所有指派人
- 通知對象：被指派人 + 指定主管（若有，嚴格不 fallback 至所有 admin）；主管無 email 時記 warning
- **修復重啟重寄 Bug**：`_set_setting("dt_overdue_last_check", yesterday)` 移至 try block **之前**（guard 先寫），任何例外都不會重置 guard → 重啟不會重寄
- `schedule_overdue_check()`：新增 `if datetime.now().hour >= 8` 條件，深夜重啟不觸發 catch-up

**指派主管 Email 精確路由**
- `daily_tasks` 新增 `supervisors TEXT NOT NULL DEFAULT '[]'`（DB v16 `_m016_daily_task_supervisors`）
- `notify_daily_task_completed` / `notify_daily_task_overdue`：若 `supervisor_usernames` 有值→ 僅通知指定主管（不 fallback 至全體 admin）；主管無 email 時 log warning 並 return
- `_enrich()` 補 `supervisors`（username list）和 `supervisors_info`（含 displayName）

**歷史紀錄功能**
- `GET /api/daily-tasks/{id}/history?page=&per_page=`：所有歷史 occurrence 分頁，軟刪除後仍可讀
- `GET /api/daily-tasks/{id}/history/export`：UTF-8 BOM CSV（7 欄位）
- 右面板 Tab 切換「本次紀錄」/「歷史紀錄」；歷史 timeline 可展開每人狀態 + 回報；「載入更多」分頁；匯出 CSV 以 `Authorization: Bearer` fetch 再 blob download

**回報彙整視圖（全面重設計）**
- 從頂部按鈕切換，佔滿主畫面
- **分割面板**：左 256px 任務列表（快速掃描完成狀態）+ 右詳情（選定任務所有人員回報）
- 回報文字**永遠顯示**於人員名稱正下方（縮排 34px 對齊），完成為綠色左框、未回報為虛線淡色
- 當前登入人員的行以紫色左側條（`.mine`）標記
- **日期選擇**：年份 / 月份 `<select>` + ← → 日期導航，可快速跳至任意過往日期
- **全文搜尋**：即時搜尋任務名稱、分類、回報內容；顯示「N 項符合」提示
- **統計列**：「N 項 · K/M 人完成」動態色碼（全綠 / 部分黃 / 未開始灰）
- 非 superadmin 存取：自動帶 `username` 只看自己被指派的任務和回報
- 自動選中：載入時優先選第一個有未完成人員的任務

**Email 商務文案全面改版（`helpers/email_notify.py`）**
- `_build_html()` 新增 `intro: str = ""` 和 `button_text: str = "前往系統查看"` 可選參數
- CSS 新增 `.intro` 樣式（段落文字，14px，灰色，1.7 行距）
- 所有 9 個 `notify_*` 函式改用 `【MOTRIX】` 主旨前綴，加 `intro` 問候段落，自訂 `button_text`
- 頁尾改為「本郵件由 MOTRIX 營運管理系統自動發送，請勿直接回覆。如有疑問，請聯絡系統管理員。」

---

### 2026-07-21a — 每日工作事項全改版

**Req 1 — `pages/daily-tasks.html` 全新設計**
- **UI**：參考 customers.html 企業風格；固定頂部工具列（月份導航 `< 2026年7月 >`）+ 左右雙欄佈局
- **左面板（300px）**：搜尋輸入 + 人員篩選下拉（解鎖後才顯示）+ 依日期分組任務卡片（優先級色點 + 週排程 badge + 進度 N/M）
- **右面板**：任務標題 + metadata chips + 說明文字方塊 + 指派人卡片 grid（`.ag-grid/.ag-card`，含完成狀態 badge / 完成時間 / 回報內容）；被指派且未完成者顯示回報 textarea + 送出按鈕（提示通知主管）
- **新增/編輯 Modal**：日期 / 優先級 / 標題 / 分類 / 說明 + 排程設定（單次 / 每週 + 星期幾圓形按鈕 + 截止日期）+ 卡片型式人員選取（`.usr-grid/.usr-card` 頭像 + 名稱 + 角色，點選切換勾選）
- **解鎖 Modal**：輸入密碼 → POST /api/auth/verify-daily-task-unlock；428（未設定）→ 自動解鎖 + 提示設定密碼；403（錯誤）→ 顯示錯誤；成功 → `sessionStorage('dt_unlocked','1')` + 載入全部人員和任務
- **完成回報**：送出後自動背景 Email 通知所有 admin/superadmin

**Req 2 — 管理視角存取控制**
- **DB v15**：`users.daily_task_pw_hash TEXT NOT NULL DEFAULT ''`
- **後端 `routers/auth.py`**：新增 `POST /api/auth/verify-daily-task-unlock`（428=未設定 / 403=錯誤 / 200=成功）、`PATCH /api/users/{id}/daily-task-password`（僅允許對 superadmin 帳號設定）
- **前端鎖定行為**：鎖定時（含 superadmin）GET 自動帶 `?username=自身`；解鎖後可選擇人員篩選或看全部
- **完成 Email**：`notify_daily_task_completed()` → `_admin_emails()` → 主旨 `[MOTRIX] 工作完成：{名稱}・{標題}（{日期}）`

**Req 3 — `pages/users.html` 兩項擴充**
- 每列操作區新增「工作事項」按鈕（紫色，superadmin 才顯示）→ `daily-tasks.html?username=xxx`
- 編輯超管帳號 Modal 新增「每日工作事項密碼」區塊（含確認欄位）→ PATCH `/api/users/{id}/daily-task-password`

**後端修復：週排程 (`DB v14`)**
- `_m014_weekly_recurrence`：`daily_tasks` 新增 `recurrence_type/days/end_date`；重建 `daily_task_completions`（UNIQUE 由 (task_id, username) 改為 (task_id, occurrence_date, username)）
- 修復前：同週期同帳號不同日期衝突導致週排程無法正常記錄完成；修復後：每次 occurrence 獨立記錄

**Email 通知新增**
- `helpers/email_notify.py`：`notify_daily_task_completed(task_id, title, task_date, completed_by_username, completed_by_display, report)`
- `helpers/__init__.py`：匯出到 `__all__`
- `routers/daily_tasks.py`：`complete_daily_task()` 回報完成後 daemon thread 呼叫

---

### 2026-07-20v — 每日工作事項 + 簽核繞過修復

**每日工作事項（`工作內容` 分類下新頁）**
- **Sidebar**：`sidebar.js` 將 `sec('出勤')` → `sec('工作內容')`；新增 `ni(pg('daily-tasks.html'), 'dtask', '每日工作事項', ...)`
- **DB v13**：`_m013_daily_tasks(conn)` 新增 `daily_tasks`（欄：task_date/title/description/category/priority/assigned_to_json/created_by/is_deleted）+ `daily_task_completions`（UNIQUE(task_id,username)）+ 索引
- **後端 `routers/daily_tasks.py`**（新）：6 端點（CRUD + PATCH complete）；`_enrich()` 補 assignees/completions；POST/PUT 在有新被指派人時發 in-app `_notify()` + 背景 Email `notify_daily_task_assigned()`；完成用 `ON CONFLICT DO UPDATE` upsert；使用 `json_each(assigned_to)` 查成員
- **Email `notify_daily_task_assigned()`**：`helpers/email_notify.py`；收件人 = 被指派人 email；主旨 `[MOTRIX] 工作事項指派：{title}（{date}）`；Email 連結直接指向 `daily-tasks.html`（`_build_html(quote_no="", base_url=task_page)`）
- **前端 `pages/daily-tasks.html`**（新）：左右雙欄（`.dt-layout`）；左：月份導航 `< YYYY年M月 >`、superadmin 人員篩選、依日期分組工作清單（優先級 badge + 進度 N/M）；右：任務詳情（標題/元資料/描述/指派人+完成狀態）、superadmin 的編輯/刪除按鈕、被指派人的完成回報 form（textarea 必填）、新建/編輯 Modal（日期/標題/分類/優先級/說明/多選被指派人）

**簽核繞過修復（`routers/quotations.py`）**
- **漏洞**：`PATCH /api/quotations/{no}/status` 允許任意 superadmin 直接設 status→"已送出"，完全繞過簽核流程
- **修復 1（主要）**：在 `update_status()` 加前置檢查：若 `body.status=="已送出"` 且當前 status IN (`待審核`,`簽核中`) 且 `_active_tiers(appr)` 有未完成層（`ct_idx < len(tiers)`），回傳 403 `"此報價單尚有 N 層待完成的簽核，請透過正式簽核流程完成審核"`
- **修復 2（防線）**：`approve_quotation()` else 分支（quotation 缺 tiers 時）新增：讀取 `_get_setting("approval_flow")`，若全域有設定 tiers，拒絕 fallback 並提示申請人收回重送以套用新設定

### 2026-07-20u — 同一層簽核人必須按順序簽核

- **問題**：同一簽核層（tier）內多人並聯，任何人都可搶先簽，與預期不符
- **規則**：同層內的審核人必須照陣列順序逐一簽核（1號簽完 → 2號才能簽）
- **後端 `approve_quotation`**：先確認用戶在當層，再找 `first_pending`；不是第一位 → 403 `請等待 X 先完成簽核（簽核順序固定）`
- **前端 `quotation-form.html`**：`isCurrentTierApprover()` / `pendingApproverLabel()` 改為只看 `firstPending`
- **前端 `approval-queue.html`**：`canApprove()` / `waitingForText()` 改 `firstPending`；`mine-turn` / step badge 改用 `canApprove(item)`；新增 `approverSublabel()` 區分「等待簽核中」vs「等待前一位完成」

### 2026-07-20t — 簽核每層加入拒絕結案鎖死功能

- **問題**：`approval-queue.html` 有「拒絕結案」，但 `quotation-form.html` 沒有，簽核人只能在佇列頁才能永久鎖定
- **後端**：`POST /api/quotations/{no}/reject-final` 已支援所有當層簽核人（`is_in_tier`），無需改動
- **前端 `quotation-form.html`** 新增三處：
  1. **State**：`showRejectFinalModal: false`、`rejectFinalNote: ''`、`rejectingFinal: false`
  2. **工具列按鈕**：當 `isCurrentTierApprover()` 時顯示「拒絕結案」黑色按鈕（與「退回修改」並列）；退回修改 = 紅淡色可修改，拒絕結案 = 全黑不可逆
  3. **預覽 Modal 底部按鈕**：同條件下，預覽完後也可直接「拒絕結案」（與「退回修改」「確認簽核」並列）
  4. **拒絕結案 Modal**：黑色標頭、不可撤銷警示條、必填原因 textarea；`confirmRejectFinal()` 呼叫 `/reject-final`，成功後 `loadQuote()` 刷新並顯示 toast
- **權限**：與原有機制相同，僅當層簽核人或 superadmin 可執行，後端 403 防護已就位

### 2026-07-20s — 退回改版報價單全狀態 returnInfo 顯示

- **根本原因**：`quotation-form.html` 中 `returnInfo` 橫幅條件為 `q.returnInfo && q.status === '草稿'`，重新送審後狀態變為「待審核／簽核中」，橫幅消失，審核人看不到退回原因和前版品項
- **修復 `quotation-form.html`**：
  - 移除 `q.status === '草稿'` 限制，改為 `x-show="q.returnInfo"`，橫幅在所有狀態下（草稿/待審核/簽核中/已送出）均顯示
  - 標題依狀態動態切換：草稿 → 「此報價單由簽核人退回修改，請修改後重新送審」；非草稿 → 「此為改版報價單（已重新送審）」
  - 新增「改版」badge（橙底暗紅字）跟隨標題
  - 前版品項展開表格新增「廠牌 / 型號」欄位，標題行（type==='header'）高亮顯示
- **修復 `backend/routers/quotations.py`**：`reject_quotation()` 中 `previousItems` 快照新增 `type` 和 `brand` 欄位；過濾掉空描述且非標題行的空白列
- **`quotations.html` 列表**：報價單號後方新增「改版」badge（以 `/\-R\d+$/` 正則偵測），讓列表也能一眼識別改版單

### 2026-07-20r — 案件管理匯入選取功能 + PDF 隱藏欄位修復

- **案件管理 — 叫料管控 / 設備登錄「從報價單匯入」改為選取式 Modal**
  - **新增 state**：`showImportModal: false`、`importMode: 'materials'|'devices'`、`importSelectedItems: {}`（取代舊 `showImportPanel`）
  - **新增方法**（`js/case-management.js`）：`quoteItemsForImport()`（過濾標題行和空描述）、`openImportModal(mode)`（開啟 modal、預設全選）、`toggleImportItem(idx)`、`selectAllImportItems(val)`、`doImport()`（依 mode 分流：materials 呼叫 `addMaterialFromQuote(qi)`、devices 複用原 group 邏輯）
  - **移除**：`importAllFromQuote()`（舊全部匯入）、`importDevicesFromQuote()`（舊設備全部匯入）；兩者邏輯統一進 `doImport()`
  - **HTML（`pages/case-management.html`）**：叫料「從報價單匯入」按鈕改呼叫 `openImportModal('materials')`；移除舊 `showImportPanel` 內嵌面板；設備「從報價單品項匯入」改呼叫 `openImportModal('devices')`；新增共用 Modal（位於 `app-shell` 外，`x-cloak`，含標題列、全選/清除工具列、checkbox 品項清單、取消/匯入按鈕）；`__noop_stub` 同步更新
- **PDF 匯出 pdfShow 隱藏欄位修復（`backend/pdf_gen.py`）**
  - 根本原因：`_build_quote_html` 的客戶資訊區塊完全忽略 `pdfShow` 設定，所有欄位無條件輸出
  - 修復：函式開頭讀取 `ps = q.get('pdfShow') or {}`，六個可控欄位改為條件式輸出，邏輯與前端 client-side preview 對齊：
    - `taxId / contactName / contactPhone / contactEmail`：預設顯示，`false` 時隱藏
    - `contactFax`：預設隱藏，`true` 時才顯示
    - `deliveryAddress`（即「送貨地址 / 發票地址」欄位）：預設顯示，`false` 時隱藏
  - 順帶補入 PDF 原本缺少但前端已有的 `contactEmail` 和 `contactFax` 欄位
  - 無 `pdfShow` 的舊報價單向下相容（按各欄位預設值處理）

### 2026-07-20p — 專案管理成員分配功能

- **DB v12**：`projects` 表新增 `assigned_user_ids TEXT DEFAULT '[]'`（migration `_m012_project_assigned_users`）；現有專案預設為空陣列（僅管理員可見）
- **後端 `GET /api/projects` 存取控制**：非 admin/superadmin 使用者只看到其 user ID 在 `assigned_user_ids` 內的專案；admin/superadmin 不受限
- **新端點 `PATCH /api/projects/{id}/assigned-users`**：admin/superadmin 設定專案可見的 user ID 清單；寫入 audit_log
- **前端 `projects.html` — 成員分配 UI**：`GET /api/auth/me` 驗證後，info tab 顯示「成員分配」卡（僅 admin/superadmin 可見）；`assignableUsers` getter 過濾出持有 project_manage / project_approve_eng / project_approve_biz 模組的非管理員使用者；checkbox 勾選後點「儲存分配」呼叫 PATCH 端點
- **資料流**：管理員建立專案 → 切換至「專案資訊」tab → 在成員分配區勾選使用者 → 儲存 → 被選中的使用者下次 `GET /api/projects` 即可看到此專案

### 2026-07-20o — 使用者管理模組同步修復

- **`case_manage` 補入 allModules**：`users.html allModules` 新增 `{key:'case_manage', label:'案件管理'}`；sidebar.js 早已使用此 key 控制案件管理顯示，但使用者設定頁面缺此選項，導致無法透過 UI 授予案件管理存取
- **ROLE_MODULES 同步更新**：superadmin/admin/sales/engineer 各自加入 `case_manage` 預設值
- **空 modules 陣列 bug 修復**：`hasAccess()` 與 `openEdit()` 改用 length 判斷（`user.modules.length > 0`）取代 truthy 判斷；JS 中 `[]` 為 truthy，舊用戶 modules=null→API 回傳 `[]`→form 顯示全空→儲存寫入空陣列→chips 全灰
- **equipment 模組 sidebar gating**：`sidebar.js` 新增 `cEq = mods.indexOf('equipment') >= 0 || ad`；設備登載、保固追蹤 兩個 nav item 及「設備」section 改為 `show=cEq`（原為無條件顯示）
- **`dashboard` 模組支援**：`canDash` 新增 `mods.indexOf('dashboard') >= 0` 分支（allModules 中已有此 key 但 sidebar 未讀取）
- **`ntfy` icon 補全**：`ic` 物件新增 `ntfy`（信封圖示），修正通知設定 sidebar 項目 SVG 顯示為 undefined 的問題
- **Async session 同步**：`sidebar.js` 每頁載入後背景呼叫 `GET /api/auth/me`，若 role/modules/displayName 有變動立即更新 localStorage 並重建 sidebar（修復：超管變更他人模組後，對方導航到下一頁即時生效，不需重新登入）
- **allModules 標籤更新**：各模組說明更精確對應到其控制的 sidebar 功能（如「報價單／簽核佇列」、「供應商／料號／採購」）

### 2026-07-20n — case-management 端點驗證 + §7.1 修正

- **全 9 端點驗證通過**：`GET /api/auth/me`（auth.py:231）、`GET /api/users/selectable`（auth.py:426）、`GET /api/quotations?deal_tag=...`（quotations.py:163）、`GET /api/quotations/{no}`（quotations.py:242）、`GET /api/projects?case_no=`（projects.py:56）、`POST /api/projects`（projects.py）、`PATCH /case-record`（quotations.py:568）、`PATCH /deal-tag`（quotations.py:507）、`POST /auth/logout`（auth.py:219）— 全數存在，零斷線
- **§7.1 修正**：移除錯誤標注的 `PATCH /payment/{idx}`（為舊版殘留；現行 JS 付款資料統一走 `PATCH /case-record`，從未單獨呼叫 /payment 端點）；補齊實際呼叫的 `GET /api/auth/me`、`GET /api/users/selectable`、`GET /api/quotations/{no}`、`GET /api/projects?case_no=`、`POST /api/projects`、`POST /api/auth/logout`

### 2026-07-20m — case-management 執行 Tab 扁平化

- 移除「執行」父 Tab 及其子 Tab 列（`.cm-subtabs`）和內層 `padding:20px` 包裝
- 4 個原子 Tab 晉升為頂層：`activeTab===` `'progress'` / `'materials'` / `'devices'` / `'warranty'`
- 頂層 Tab 順序：商務 / 執行進度 / 叫料管控 / 設備登錄 / 保固備注 / 財務
- `case-management.js`：移除 `execSubTab` 狀態、`selectCase()` 移除 `execSubTab='progress'`、`syncMaterialsToDevices()` 改 `this.activeTab='devices'`
- `__noop_stub` 同步更新（3 處），無 `execSubTab` 殘留

### 2026-07-20l — case-management 同步 UI/UX 升級

**Batch 1 — 左側卡片色條 + Tab 計數 Badge：**
- `case-management.html` CSS：`.cm-card` 新增 `border-left:3px solid transparent`；`:has(.cm-card__tag--active)` 綠色、`:has(.cm-card__tag--stage)` 黃色、`:has(.cm-card__tag--closed)` 紫色
- Tab 計數 Badge：`.cm-list__tab-badge`；「待精算」用 `.orange`（橘紅），其餘跟隨 Tab active 色
- 空狀態：加 SVG 圖示 + `.cm-empty__sub` 動態提示文字（依 search/listTab 切換）

**Batch 2 — Header 層次重構：**
- 舊：`.cm-header__main`（單行 flex-wrap 塞所有元素）→ 新：`.cm-header__row1`（代號+狀態Badge+專案鈕+儲存+完結鈕）+ `.cm-header__row2`（大客戶名 + 專案子標題）
- 狀態 Badge 整合：`.deal-tag-badge--active/stage/closed`（單一 badge 依 stages 動態切換，不再分兩個 template 分別顯示）
- `.cm-project-btn` 取代 inline style 專案按鈕

**Batch 3 — 端點驗證 + Stub 修正：**
- 全 9 個 API 端點確認存在：`/api/auth/me`、`/api/users/selectable`、`/api/quotations`、`/api/quotations/{no}`、`/api/projects?case_no=`、`/api/projects`、`/api/quotations/{no}/case-record`、`/api/quotations/{no}/deal-tag`、`/api/auth/logout`
- Stub（HTML `__noop_stub()`）6 處修正：`activeTab:'progress'→'biz'`、補 `selectableUsers:[]` / `execSubTab:'progress'`、`filterCases()` 補 `project_name` 搜尋、`selectCase()` 補 `execSubTab='progress'`、`ensureCaseRecord()` 補 `contract/roles` 初始化、`syncMaterialsToDevices()` 補 `execSubTab='devices'`

### 2026-07-20k — projects.html UI/UX 全面重新設計

- **狀態篩選列**：`overflow-x:auto` 橫捲 Tab → `flex-wrap:wrap` 包覆式 Pill，一次看全 8 個狀態（`projects.html` CSS `.pj-filter-pills`）
- **卡片左色條**：CSS `:has(.st-xxx)` 選擇器，7 種狀態各對應顏色，0 個 JS 改動（`.pj-card:has(.st-planning)` 等）
- **右側 Header 3 列化**：單行混排 → 代號+Popover 狀態+操作 / 大標題（18px）/ 描述+Metadata（建立人、日期、關聯案件）
- **狀態變更 UX**：`<select value="">` reset placeholder 換法 → `x-data="{statusOpen:false}"` nested scope Popover，點擊狀態 Badge 展開（`.status-popover` + `.status-pop-item`）
- **日誌卡片視覺**：新增 32px 日期 Icon Block（月份/日）；收合時顯示 60 字內容預覽；action items 進度 Chip + 照片數 Chip
- **Section 標題**：`.section-label::after` 橫線分隔；`工作內容` / `出勤人員` / `確認事項` / `物料使用紀錄` / `施工照片` 各自獨立區塊
- **空狀態強化**：專案列表空狀態 + 日誌空狀態 各加 SVG 圖示 + 副說明文字
- **Tab 計數 Badge**：「工作日誌」Tab 在 `logs.length > 0` 時顯示紫色 Pill 計數
- **JavaScript 0 改動**：`projectsPage()` 函式與所有 API 呼叫完全保持不變，`API = ''` 不變

### 2026-07-20j — 報價單列表未成案分類

- **「全部」改名**：`quotations.html:331` `tabs` 陣列第一項 label 由 `'全部'` → `'全部(不含未成案)'`
- **「全部」預設排除未成案**：`quotations.html:380`（`filtered` getter）`activeTab==='all'` 時 matchTab 改為 `(q.deal_tag||'') !== '未成案'`（原為 `true`）；`quotations.html:346`（`tabCount('all')`）計數改為排除 `deal_tag=未成案` 的筆數
- **新增「未成案」Tab**：`quotations.html:339` 追加 `{ key:'未成案', label:'未成案', isDealTag:true }`；`tabCount` / `filtered` 既有 `isDealTag` 分支（`q.deal_tag === key`）自動支援，無需額外邏輯

### 2026-07-20i — 簽核 bug 修復、狀態手動調整、設備群組匯入

- **簽核自動通過 bug 修復**：`quotations.py:407-422` 移除「自動跳過自身 tier-0 簽核」邏輯。原本送審時若 requestedBy 是 tier-0 唯一簽核人，currentTier 會自動推進到 1（超出 tier 範圍），導致 `canApprove()` 永遠返回 false，整張報價單無人可簽核（stuck）。現在送審者須從 approval-queue 明確點擊「確認簽核」完成流程。
- **狀態手動調整下拉（superadmin）**：`quotation-form.html` 頁面頂欄狀態 badge，superadmin 看到的是 styled `<select>` 下拉（外觀與 badge 相同）。選項：草稿、待審核、已送出、已取消、已拒絕（對應後端 `_STATUS_PATCH_WHITELIST`）。`patchStatus(newStatus, sel)` 函式：confirm 對話 → PATCH /api/quotations/{no}/status → 成功更新 `q.status`；取消/失敗時 `$nextTick(() => sel.value = old)` 還原 select 顯示。
- **設備群組匯入**：`case-management.html` 設備登錄 tab 新增「從報價單品項匯入」按鈕（僅在 `selected.data.items` 有有效品項時顯示）。每個品項按 qty 建立 N 個 device 物件，共用 `_groupId` / `_groupName` / `_groupIdx` / `_groupTotal` 欄位（上限 50 台/項）。
- **設備區塊式顯示**：替換原本的線性 x-for，改為 `deviceDisplayList()` 函式輸出 `{type:'group'|'device'}` 結構。群組顯示藍色可折疊標題欄（chevron icon + 品名 × 數量 + 已填台數 badge）；點擊展開各子設備卡；`toggleDevGroup(groupId)` 以 spread-assign 觸發 Alpine 響應；`removeDeviceGroup(groupId)` 一次刪整組；`removeDeviceByObj(dev)` 按 id 找索引刪個台。新增 case 時 `_openDevGroups = {}` 重置。
- **⚠️ 架構注意**：`case-management.html` 的 Alpine 邏輯來源是 **外部 `js/case-management.js`**（`app()` 函式），HTML 內含 `__noop_stub()` 僅為 IDE 自動補全用途（不被 Alpine 執行）。所有新增函式和 state 必須同時寫入 **`js/case-management.js`**。
- **單位選單更新**：`m` 改為 `米`；新增 捲、箱、包、人月、人日、次、年、月、式（整批）（整合業常用）。

### 2026-07-20h — reject-final 對接、品項標題行、單項毛利欄、拖曳排序

- **`reject-final` 前端對接**：`approval-queue.html` 新增「拒絕結案」按鈕（canApprove 區塊、superadmin 僅退回區塊、底部 action bar 三處）；獨立 Modal（必填原因、不可逆紅色警告、確認鈕在輸入前 disabled）；`doRejectFinal()` 呼叫 `POST /api/quotations/{no}/reject-final { note }`；成功 toast「已永久拒絕結案」
- **品項區段標題行**：`quotation-form.html` 新增 `type:'header'` 品項類型；`addHeader()` 函式（僅存 `{id, type:'header', description:''}`）；「新增區段標題」按鈕（藍色）；標題行 `#` 欄只顯示拖曳把手，一般品項序號排除標題行計數；CSS 強制隱藏標題行所有 input/select/cell-display；`calcItem()`、`checkApproval()` 跳過標題行；`removeItem()` 允許刪除標題行（非標題品項至少保留一項）
- **單項毛利金額欄**：`showCostCols`（內部視角）在「金額」右側新增「單項毛利」欄，公式 `amount − qty × cost × 1.05`（直接毛利，含進項稅）；正值綠色（`#15803D`）、負值紅色；成本未填不顯示
- **SortableJS 拖曳排序**：`quotation-form.html` 引入 SortableJS v1.15.3 CDN（非 defer，置 Alpine 前）；`initSortable()`（`$nextTick` 呼叫）；品項 `#` 欄 hover 顯示六點拖曳把手；拖曳動畫 150ms；`onEnd` 更新 `q.items` 陣列並觸發 `calcTotals()` + `setDirty()`；鎖定狀態（`已送出 && !unlocked`）自動 disable，`$watch` 解鎖後恢復
- **`pdf_gen.py` 標題行支援**：識別 `item.type === 'header'`，輸出藍色全欄標題行（`#EFF6FF` 背景，`#1D4ED8` 字色）；`real_idx` 計數跳過標題行，PDF 品項序號正確
- **架構事實確認**（本次完成）：所有頁面 notif.js/sidebar.js 載入正確（login.html 除外）；`approval-settings.html` API 模式已修正；`approval-queue.html` / `projects.html` `API=''` 實際 URL 正確；`steps→tiers` 雙路徑已有交叉注解且邏輯一致；`reject-final` 現已完整對接（前次文件標注的斷線端點）

### 2026-07-20g — 退回修改完整流程

- **退回理由確認信（申請人）**：`notify_returned()` 已存在；退回後申請人收到包含退回原因的 email（退回人、原單號、新單號、原因 note 高亮顯示）
- **退回改版重送確認信（申請人 + 簽核人）**：新增 `notify_resubmit_requester()` — 申請人重送後收到確認信（等待誰簽核）；簽核人收到的通知標題加 `"（退回改版）"` 以區分首次送審
- **`returnInfo` 快照**：`reject_quotation` 退回時在 `data_json` 中寫入 `returnInfo = { returnedBy, returnedByDisplay, returnedAt, note, originalQuoteNo, previousItems[] }`；重送後保留至通過或再次退回
- **退回通知橫幅**：`quotation-form.html` 草稿狀態顯示橙色橫幅，顯示退回人/時間/原因；可展開前版品項對照表
- **退回修改 Modal**：`quotation-form.html` 新增「退回修改」按鈕（`isCurrentTierApprover()` 判斷顯示）；textarea 填退回原因（必填）；確認後呼叫 `POST /api/quotations/{no}/reject`，導向新版本 `?id=MQ-xxx-R1`
- **簽核按鈕重構**：`isCurrentTierApprover()` 方法統一判斷（配置層 approver 或無配置時任意 superadmin）；`approveQuote()` 改呼叫 `POST /api/quotations/{no}/approve` API（舊版直接 saveDraft 已移除）
- **`loadQuote()` 輔助函式**：`approveQuote()` 後 reload 頁面取得最新 tiers 狀態

### 2026-07-20f — 簽核功能完善版

- **收回草稿**：`POST /api/quotations/{no}/recall`（`quotations.py`）；前端 `quotation-form.html` 新增「收回草稿」按鈕（待審核/簽核中 + requestedBy===自己時顯示）；`recallQuote()` 函式
- **等待審核人名稱**：`quotation-form.html` `pendingApproverLabel()` — 顯示 currentTier 中尚未通過的 approver displayName，取代固定文字「主管」
- ~~**自動跳過自身 tier-0 簽核**：送審時若 requestedBy 在 tier-0 approvers 中，自動標記已通過~~ — **2026-07-20i 已撤除**：此邏輯在唯一簽核人即申請人時造成 stuck，改為必須明確簽核
- **Email from_name**：`email_notify.py` + `system.py` + DB `email_notify.from_name` 一律改為 `"MOTRIX營運系統"`
- **Email 靜默丟棄改為 warning log**：`_send()` 及所有 5 個 `notify_*` 函式，空收件人/未設 SMTP 改為 `logger.warning(...)` 記錄
- **Photo token @error retry**：`projects.html` 圖片 `@error` 改為清快取後重試（`clearPhotoCache()`），不再顯示破圖 SVG
- **cross-reference 注解**：`system.py _normalize_flow()` ↔ `quotations.py _active_tiers()` 互相標注平行邏輯；`SQL_DEAL_TAG` 加 backward-compat 說明

### 2026-07-20e — 修正版

- **死碼清除**：刪除 `frontend/js/` 目錄中 21 個未被載入的 JS 檔，僅保留 `case-management.js`、`reports.js`
- **settlement.html 補實作**：新增 `notif.js` 載入（sidebar bell 修復）；`API` 變數統一為 `const API = '/api'`；fetch URL 格式統一
- **sales-orders.html 加 sidebar 入口**：`sidebar.js` 財務區新增「銷售訂單」（`cFi` 權限，icon: order）
- **approval-settings.html API 模式統一**：`const API = ''` → `const API = '/api'`；所有 fetch URL 前綴修正；補 `notif.js` 載入
- **projects.html 補 notif.js**：補全缺失的通知 Bell 載入

### 2026-07-20d — 驗證修正版

- **§2 死碼警告**：修正為 21/23 個 `js/` 檔案未被載入（前版僅標示 2 個）；說明 case-management.js / reports.js 為唯二有效外部 JS
- **§7 前端→API 對應表**：全面更正 JS 來源欄為 inline；補充 procurement.html / warranty.html / sales-orders.html 的真實 API 對應；新增幽靈頁面段落
- **§7.2** 補充 approval-settings.html 的 `API=''` 模式偏差警告
- **§7.3** 修正全域載入路徑格式（根目錄 vs pages/ 子目錄的相對路徑差異）；補充鈴鐺/角標計數不一致說明
- **§9** 修正 JS 載入順序說明
- **§11** 新增：Photo token 重啟失效、Email 三條靜默丟棄路徑、steps→tiers 雙路徑風險、幽靈頁面、SQL fallback 約束、sales_person_id 永久雙路徑
- **§13** 修正 `js/` 目錄說明

### 2026-07-20c — 架構梳理交付版

- 全面讀取後端 11 個 router + 6 個 helpers + archive/pdf_gen
- 新增 §5 共用函式庫完整對應表（函式名稱 + 檔案行號）
- 新增 §6 API 端點完整列表（所有 endpoint + method + 檔案位置 + 資料流）
- 新增 §7 前端頁面 → API 對應表
- 新增 §15 關鍵資料流詳細呼叫鏈
- 更新 §4 DB Schema 為完整 18 張資料表

### 2026-07-20b — UX P3：簽核佇列警示 + 案件執行階段標籤 + 待精算篩選

**P3 — 首次登入 Onboarding 引導條**
- `frontend/index.html`：引導條（totalQuotes===0 && activeCases===0），三個快捷入口；存 `localStorage('motrix_onboarding_banner_dismissed')`

**P3 — 案件管理「待精算」篩選 Tab**
- `frontend/pages/case-management.html`：第 4 個 Tab「待精算」（橘色角標）
- filter：`settle_status === 'draft'`（精算已開始但未完結）

**案件管理：執行階段標籤**
- `backend/routers/quotations.py`：list 端點 SQL 加 `json_extract(data_json,'$.caseRecord.stages') as stages_json`
- `frontend/pages/case-management.html`：卡片/detail header 顯示「待 X」黃色標籤（未完成 stage.label）

**簽核佇列：紅色警示**
- `frontend/pages/approval-queue.html`：`get myPendingCount()` computed；頂部紅色警示條；`.aq-item.mine-turn`（橘底紅框）

**Bug 修復**
- `approval-queue.html`：補 notif.js 載入；「開啟報價單」連結 `?q=` 修正為 `?id=`

### 2026-07-20 — UX P1/P2：簽核待辦儀表板 + sidebar 角標 + 通知拆分

**P1 — 儀表板「等我簽核」KPI**
- `backend/routers/dashboard.py`：`waitingForMe` 計數
- `frontend/index.html`：第 5 個 KPI 卡（canQuotation 才顯示，5 欄 grid）

**P1 — Sidebar 簽核佇列 + 角標**
- `frontend/static/sidebar.js`：「簽核佇列」入口 + `id="sb-approval-badge"`
- `backend/routers/quotations.py`：`GET /api/approval-queue/count` 輕量端點
- `frontend/static/notif.js`：`_fetchApprovalCount()`；鈴鐺 badge 不計 approval_request 型通知

**P2 — approval-queue.html 底部操作列**

**P2 — 通知設定頁 checklist**（4 項 computed getter）

### 2026-07-19b — Email 通知修復 + 舊代碼清除

- `routers/quotations.py`：`is_new_submission` 改查 DB 舊狀態
- `main.py`：OPTIONS 放行修正 CORS preflight
- `restart.bat`：改 PowerShell Stop-Process

### 2026-07-19 — Email 通知功能

- `helpers/email_notify.py`（新）：Gmail SMTP 非同步發信
- `routers/quotations.py`：5 觸發點
- `routers/system.py`：email-notify 設定端點

### 2026-07-18a — 全面安全審查 P0–P3（30 項）

**P0 — 安全漏洞**：多個端點補 `_require_user`；deal-tag 補 Auth header；DELETE 僅草稿

**P1 — 業務邏輯**：解鎖 superadmin 驗證；狀態機白名單；deal_tag 已結案不可逆；settlement 回滾；GET /auth/me 驗 expires_at

**P2 — 邊界案例**：mark_payment 樂觀鎖；delegateNote 寫 audit；已成案降級限 admin+；G: fallback；rate limit 持久化；notif.js DOM API；防重複送出 flag

**P3 — 品質**：JSON 原子寫入；Dashboard sparkline 真實資料；audit-log admin+ only；work-log owner 驗證

---

## §13 · 目錄結構（精簡）

```
MOTRIX-ERP/
├── MOTRIX-ERP-QUICK.md          ← 本文件（交付版）
├── .gitignore
├── backup_alerts/               ← 備份警示（執行期產生）
├── backend/
│   ├── main.py                  ← wiring；startup 呼叫鏈
│   ├── db.py                    ← schema + 11 個 migrations（CURRENT_VERSION=11）
│   ├── helpers/
│   │   ├── __init__.py          ← re-export 全部符號
│   │   ├── auth.py              ← 密碼、session、弱密碼
│   │   ├── settings.py          ← system_settings CRUD
│   │   ├── audit.py             ← _audit() + _notify()
│   │   ├── quotations.py        ← SQL 常數、save_quotation_json
│   │   ├── dates.py             ← _add_months、_warranty_expiry
│   │   ├── email_notify.py      ← Gmail SMTP；5 事件函式
│   │   └── startup.py           ← 啟動檢查、Edge 路徑解析
│   ├── archive.py               ← 備份；_atomic_json_write()；G: fallback
│   ├── pdf_gen.py               ← Edge Headless PDF（報價單 + 勞報單 + 報表）
│   ├── photos.py                ← 專案照片水印（Pillow）
│   ├── backup_job.py            ← 獨立備份（Windows Task Scheduler）
│   ├── setup_backup_task.ps1    ← 初次部署執行一次
│   ├── motrix_erp.db
│   ├── db_backups/
│   │   ├── YYYY-MM-DD/          ← SQLite 快照（30 天）
│   │   └── quotation_instant/   ← G: 不可用時即時 JSON fallback
│   ├── export_archive/          ← 勞報單 PDF 存檔（{slip_no}_{idx}.pdf）
│   ├── logs/backup_job.log
│   ├── .initial_admin_credentials.txt  ← 新裝時臨時密碼，用後刪
│   └── routers/
│       ├── auth.py              ← /api/auth/* + /api/users/*
│       ├── quotations.py        ← /api/quotations/* + /api/approval-queue/*
│       ├── customers.py         ← /api/customers/*
│       ├── suppliers.py         ← /api/suppliers/*
│       ├── parts.py             ← /api/parts/*
│       ├── projects.py          ← /api/projects/* + /api/uploads/*
│       ├── dashboard.py         ← /api/dashboard/* + /api/company/* + /api/devices/* + /api/receivables/*
│       ├── system.py            ← /api/settings/* + /api/notifications/* + /api/audit-log + /api/work-logs
│       ├── reports.py           ← /api/reports/*
│       ├── contractors.py       ← /api/contractors/*
│       └── payslips.py          ← /api/payslips/* + /api/tax-rules + /api/next-slip-no
├── frontend/
│   ├── index.html               ← 儀表板
│   ├── css/style.css
│   ├── js/                      ← ⚠️ 23 個 JS 檔，21 個為死碼（未被任何 HTML 載入）
│   │   ├── case-management.js   ← ✅ 由 case-management.html 載入
│   │   ├── reports.js           ← ✅ 由 reports.html 載入
│   │   └── 其餘 21 個 .js       ← ⚠️ 死碼（含 quotations.js, dashboard.js, settlement.js 等）
│   ├── pages/
│   │   ├── quotation-form.html  ← Alpine inline（真正的 quotationForm()）
│   │   └── settlement.html      ← Alpine inline（真正的 settlementPage()）
│   └── static/
│       ├── sidebar.js           ← Topbar + Sidebar 注入
│       ├── notif.js             ← 通知 Bell + approval count badge
│       └── logo.png             ← MOTRIX 白字去背 PNG
├── uploads/projects/            ← 專案照片
└── 報價單PDF/                    ← Edge PDF 輸出目錄（預設）
```

---

## §14 · Email 通知

### §14.1 · 架構

```
routers/quotations.py  ─┐
                         ├─ notify_*()  ←  helpers/email_notify.py
routers/system.py  ──────┘                 ├── _async_send() → daemon thread
                                           ├── _send()        → SMTP，失敗只 log
                                           └── _send_raising()→ SMTP，失敗拋錯（test 端點）
```

設定儲存：`system_settings` key=`email_notify`（JSON）

### §14.2 · 設定欄位

| 欄位 | 說明 | 預設 |
|------|------|------|
| `enabled` | 啟用開關 | `false` |
| `smtp_host` | SMTP 主機 | `smtp.gmail.com` |
| `smtp_port` | 連接埠 | `587` |
| `smtp_user` | Gmail 帳號 | — |
| `smtp_password` | App Password（16 碼） | — |
| `from_name` | 寄件人顯示名稱 | `MOTRIX ERP` |
| `base_url` | 信件連結前綴 | `http://172.16.11.211:666` |

GET 回傳 `admin_email_preview`（唯讀，動態查 users 表）；密碼遮蔽為 `••••••••`

### §14.3 · 事件對應

| 事件 | 函式 | 收件對象 | 主旨格式 |
|------|------|---------|---------|
| 新報價/解鎖改版/退回改版送審 | `notify_approval_request` | 當層簽核人 | `【MOTRIX】報價單待審核 — {no}（{客戶}）` |
| 前層通過→下一層 | `notify_next_tier` | 下一層簽核人 | `【MOTRIX】報價單審核通知（第N/M層）— {no}（{客戶}）` |
| 全員通過→已送出 | `notify_approved` | 申請人 + admin/superadmin | `【MOTRIX】報價單審核完成 — {no}（{客戶}）` |
| 退回修改（簽核人操作） | `notify_returned` | 申請人 | `【MOTRIX】報價單退回修改 — {no}（{客戶}）`，含退回原因 note |
| 退回改版重新送審（申請人操作） | `notify_resubmit_requester` | 申請人（確認信） | `【MOTRIX】修改版報價單已送審 — {new_no}（{客戶}）` |
| 精算 finalized | `notify_settlement_finalized` | admin/superadmin | `【MOTRIX】成本精算完結 — {no}（{客戶}）` |
| 工作事項指派 | `notify_daily_task_assigned` | 被指派人 | `【MOTRIX】工作事項指派通知 — {title}（{date}）` |
| 工作事項完成回報 | `notify_daily_task_completed` | 指定主管（若無則全體 admin） | `【MOTRIX】工作事項完成回報 — {name} · {title}（{date}）` |
| 工作事項逾期未完成 | `notify_daily_task_overdue` | 被指派人 + 指定主管（若無則全體 admin） | `【MOTRIX】工作事項逾期未完成 — {name} · {title}（{date}）` |

---

## §15 · 資料流：完整呼叫鏈

### §15.1 · 報價單完整生命週期

```
[新建]
  前端 quotation-form.html (inline quotationForm())
    → GET /api/next-quote-no  (quotations.py:144)
    → POST /api/quotations    (quotations.py:256)
        → quote_hot_fields() → INSERT quotations
        → threading.Thread(_backup_quotation)
        → _audit('quotation.create')

[存草稿]
  → PUT /api/quotations/{no}  (quotations.py:325)
      status=草稿，data={...}
      → save_quotation_json() (helpers/quotations.py:24)
      → _backup_quotation() async

[送審]
  → PUT /api/quotations/{no}
      status=待審核，data.approval={requestedBy, requestedAt}
      → 查 DB 舊狀態（is_new_submission 判斷）
      → _get_setting('approval_flow') → _setting_to_active_tiers()
      → data.approval.tiers = [...], currentTier=0
      → 對第 0 層每位 approver：_notify() + notify_approval_request() (email)
      → UPDATE quotations

[簽核]
  → POST /api/quotations/{no}/approve (quotations.py:828)
      → my_entry.status='approved'
      → tier_done？→ currentTier++
      → all_done？→ save_quotation_json(status='已送出')
                 → _generate_quotation_pdf() async
                 → notify_approved() (email)
             否則：notify_next_tier() (email)

[退回]
  → POST /api/quotations/{no}/reject (quotations.py:923)
      → _next_revision_no()
      → UPDATE quote_no=新號, status=草稿
      → notify_returned() (email)

[解鎖編輯]
  → POST /api/auth/verify-unlock (auth.py:438)
  → PUT /api/quotations/{no}
      data._isUnlockEdit=true
      → 驗 superadmin
      → append editHistory
      → status=待審核（重新送審）

[成案]
  → PATCH /api/quotations/{no}/deal-tag (quotations.py:507)
      body: { deal_tag:'已成案', log_entry:{...} }
      → 驗 admin+
      → save_quotation_json() → deal_tag 欄位更新

[精算]
  → PUT /api/quotations/{no}/settlement (quotations.py:690)
      body: { settlement:{status:'finalized', summary:{...}} }
      → finalized 後 superadmin only
      → save_quotation_json() → settle_status='finalized'
      → notify_settlement_finalized() (email)

[PDF 匯出]
  → GET /api/quotations/{no}/pdf-download (quotations.py:1051)
      → generate_pdf_bytes() → pdf_gen.py
          → _get_edge_path() (startup.py)
          → _build_quote_html() → Edge headless --print-to-pdf
      ← StreamingResponse PDF bytes
  → POST /api/quotations/{no}/export (quotations.py:594)
      （記錄匯出次數）
```

### §15.2 · 通知系統資料流

```
Server 觸發 _notify(username, type, ref_id, message)
    → INSERT notifications (audit.py:11)

前端 notif.js (每頁載入)
    → GET /api/notifications/mine (system.py:66)
    → 更新鈴鐺 badge（count 不含 approval_request 型）
    → GET /api/approval-queue/count (quotations.py:801)
    → 更新 sb-approval-badge

使用者點鈴鐺
    → PATCH /api/notifications/{id}/read
    → 或 PATCH /api/notifications/read-all
    （注意：read-all 不清除 sidebar approval badge）
```

### §15.3 · PDF 產生系統（pdf_gen.py）

```
_get_pdf_base()
    → _get_setting('pdf_base_path') or _PDF_BASE_DEFAULT（../報價單PDF/）

generate_pdf_bytes(quote_no, internal=False)
    → 讀 quotations WHERE quote_no=?
    → _build_quote_html(q, tot, internal)
    → Edge headless --print-to-pdf（tempfile）
    ← bytes

_generate_quotation_pdf(quote_no, actor_name, event_type)
    → 存檔至 _get_pdf_base()/{YYYY-MM}/{quote_no}_{event_type}_{actor}.pdf
    （自動建目錄）

generate_payslip_pdf_bytes(slip_no)
    → 讀 payslips
    → _build_payslip_html()
    → Edge headless
    ← bytes
```

### §15.4 · 簽核設定儲存與讀取

```
[設定端]
  前端 approval-settings.html
    → PUT /api/settings/approval-flow (system.py:53)
        body: { tiers:[{order, approvers:[{userId, username, displayName}]}] }
        → _set_setting('approval_flow', value)
        → INSERT/UPDATE system_settings SET value_json=JSON

[送審時讀取]
  PUT /api/quotations/{no} (status=待審核)
    → _get_setting('approval_flow')  (settings.py)
        → SELECT system_settings WHERE key='approval_flow'
    → _setting_to_active_tiers(flow_setting)  (quotations.py:41)
        → 展開 tiers，每位 approver 加 status:'pending', approvedAt:null
    → data.approval.tiers = active_tiers
    → data.approval.currentTier = 0
```

---

## §16 · Sidebar 結構

```
主選單     儀表板（index.html）
業務       報價單（quotations.html）
           簽核佇列（approval-queue.html）  [角標 sb-approval-badge]
           案件管理（case-management.html）
           專案管理（projects.html）
廠商與採購 客戶（customers.html）/ 供應商（suppliers.html）
           料號（parts.html）/ 採購（procurement.html）
設備       設備登載（devices.html）/ 保固追蹤（warranty.html）
財務       應收帳款（receivables.html）/ 銷售訂單（sales-orders.html）/ 營運報表（reports.html）admin+
工作內容   每日工作事項（daily-tasks.html）← superadmin 建立派發；一般人員查看+回報
系統       使用者（users.html）
           簽核設定（approval-settings.html）superadmin
           通知設定（notification-settings.html）superadmin
           歷史紀錄（audit-log.html）admin+
           外包人員（contractors.html）superadmin
           勞報單（payslips.html）superadmin
           工作日誌（work-log.html）
```

- 角標 `id="sb-approval-badge"` 由 `notif.js → _fetchApprovalCount()` 更新
- 鈴鐺 badge 只計非 `approval_request` 型通知
- ⚠️ **每頁必須同時載入 notif.js 和 sidebar.js**

---

*維護提示：功能變更時先更新「對應 §N 章節」，再在 §12 加一行摘要。死碼警告如有整理，更新 §2 和 §13。新增 API 端點時更新 §6 和 §7。*
