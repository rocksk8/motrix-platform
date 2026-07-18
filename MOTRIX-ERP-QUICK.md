# MOTRIX ERP — 開發快速參考

> 允碩整合集創（統編 60575481）｜ Tel: 04-3602-2818 ｜ info@miactw.com  
> 文件版本：**2026-07-18a**（全面安全審查 P0–P3 共 30 項修復完成）

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
| `db.py` | 連線、`init_db()`、PRAGMA WAL、熱路徑欄位／索引；Migration v11 |
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
| `frontend/js/*.js` | 各頁 Alpine 元件（Phase 3 已外置） |
| `frontend/pages/quotation-form.html` | ⚠️ Alpine function **inline**（非載入 `quotation-form.js`） |
| `frontend/pages/settlement.html` | ⚠️ Alpine function **inline**（非載入 `settlement.js`） |
| `frontend/static/sidebar.js` | Topbar + Sidebar 注入；**強制改密導向** |
| `frontend/static/notif.js` | 通知 Bell；所有動態內容用 **DOM API**（無 innerHTML） |
| `frontend/css/style.css` | CSS 變數：`--sidebar-w` `--topbar-h` `--accent` |

> **重要**：`quotation-form.js` 與 `settlement.js` 為**死碼**（不被載入），
> 邏輯修改一律在 `.html` 的 inline `<script>` 內進行。

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
| 模組例 | `project_manage` · `project_approve_eng` · `project_approve_biz` · `financial_view` |
| 報價列表過濾 | 非 admin+ 用 `sales_person_id=自己id OR (sales_person_id IS NULL AND sales_person=display_name)` |
| **稽核記錄** | `GET /api/audit-log` 限 **admin+**；viewer/sales/engineer 呼叫回 403 |
| **工作日誌** | `PUT/DELETE /api/work-logs/{id}`：非 admin 只能修改/刪除**自己**的日誌 |

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

users           -- + must_change_password, unlock_password_hash
sessions        -- token, expires_at
customers / suppliers  -- 主欄 + data_json（contacts, visits, tags）
parts, projects, project_logs
system_settings, audit_log, notifications
quote_seq       -- 月序 MQ-YYYYMM-NNN
login_rate_limit -- ip PK, locked_until（服務重啟後維持鎖定）
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

---

## §6 · Sidebar 結構

```
主選單     儀表板
業務       報價單（含簽核佇列 ?view=queue） / 案件管理 / 專案管理
廠商與採購 客戶 / 供應商 / 料號 / 採購
設備       設備登載 / 保固追蹤
財務       應收帳款 / 營運報表（admin+）
系統       使用者 / 簽核設定（superadmin）/ 歷史紀錄
```

- 簽核佇列不在 sidebar，在報價單內 tab
- 銷售訂單已移除（併入案件財務）

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
| 低 | 區網 HTTPS／反向代理 |
| 低 | 關鍵 API 自動化測試 |
| 低 | 文件拆 `CHANGELOG.md` 與本速查分離 |

---

## §12 · 變更摘要（精簡）

### 2026-07-18a — 全面安全審查 P0–P3（30 項，4 commits）

**P0（6 項）— 安全漏洞修復**
- `customers.py`、`GET /quotations/{no}`、`GET /next-quote-no`、dashboard 三端點補 `_require_user`
- deal-tag PATCH 補 `Authorization` header（前端 inline 修正）
- `DELETE /quotations/{no}` 加狀態守衛（僅草稿可刪）

**P1（12 項）— 業務邏輯修復**
- 解鎖編輯：加 superadmin 強制驗證；舊 tiers 清除後重建
- `PATCH /status` 加狀態機白名單；`PUT /quotations` 加鎖定狀態守衛
- deal_tag `已結案`不可逆（非 superadmin 禁止降回）
- settlement finalized 後非 superadmin 不可修改；API 失敗完整回滾
- `GET /auth/me` 驗 `expires_at`；case-management autoSave timer 清除
- **`quotation-form.html` inline 修復**：autoSave isDirty 時機、onDealTagChange UI revert、cancelUnlock 方法新增、confirmSubmit items 驗證

**P2（8 項）— 邊界案例**
- `mark_payment` 樂觀鎖（`_expectedUpdatedAt` → 409）
- 代理送審 `delegateNote` 寫入 audit_log
- deal_tag 已成案降級限 admin+（前後端雙重）
- `_backup_quotation` G: 不可用時本機 fallback（`quotation_instant/`）
- 登入 rate limit 持久化 `login_rate_limit` 表（DB migration v11）；啟動載入
- `notif.js` innerHTML → DOM API（消除 XSS）
- `confirmSubmit` 防重複送出 `submitting` flag
- quotations.js limit 500 → 2000

**P3（4 項）— 品質建議**
- 所有 JSON 備份改原子寫入（`_atomic_json_write`：先 `.tmp` 再 `os.replace`）
- Dashboard sparkline：假數據替換為真實 monthly 數據（quote）/ 當前實值平線（其餘三項）
- `GET /api/audit-log` 限 admin+
- `PUT/DELETE /api/work-logs/{id}` 加 owner 驗證

### 2026-07-17f — 前端照片改用短效 signed token

- **`projects.js` + `projects.html`（inline）**：`photoUrl()` 改 lazy signed-token 模式；初次呼叫回 `?token=` fallback，背景 fetch `GET /api/photo-token?path=` 取 `?pt=`；token 快取至到期前 60 秒再重取

### 2026-07-17e — 安全強化 P2（外部顧問第二輪收尾）

- audit_log 保留策略（730 天）；照片 signed token；`sales_person_id` FK + migration v10

### 2026-07-17d — 安全強化 P0/P1（外部顧問第二輪）

- 登入暴力破解 rate limiting；全域 Exception Handler；PDF 路徑可設定；Sessions 定期清理；備份排程移工作排程器

### 2026-07-17c — 架構優化

- Schema migration 版本管理；`helpers/` 套件拆分；啟動掃描節流；CORS 限縮；Edge 路徑可設定；UI 品牌更新

### 2026-07-17b — 代理報價人選取 + 送審備註

- 報價人 Select；代理徽章；送出審核 Modal；代理原因寫入審核記錄

### 2026-07-17 — 報價單 UI 強化 · PDF 直接下載 · 客戶聯絡人同步

- 動態狀態徽章；未成案/已成案鎖定；浮水印系統；PDF 直接下載；客戶聯絡人強制同步

### 2026-07-16 — 安全 · 備份 · 熱路徑 · 架構硬化

- P0 安全：`must_change_password`、弱密碼標記、安全標頭
- P0 備份：本機 SQLite 日快照 30 天；G: 失敗寫 `backup_alerts`
- P1 熱路徑：`deal_tag` / `settle_status` 欄位 + 索引；`save_quotation_json()` 統一寫入

### 2026-07-15（摘要）

案件三 Tab、並行簽核 tiers、解鎖重送審、PDF 無瀏覽器列印、editHistory、每日備份、前端 Phase 3 JS 外置

### 2026-07-11～14（摘要）

專案模組、engineer 角色、解鎖編輯、後端模組化、通知系統、客戶供應商標籤／Excel、簽核佇列嵌入報價單

---

## §13 · 目錄結構（精簡）

```
MOTRIX-ERP/
├── MOTRIX-ERP-QUICK.md          ← 本文件
├── SECURITY_AUDIT_2026-07-18.md ← P0–P3 完整審查報告（歸檔）
├── .gitignore
├── backup_alerts/               ← 備份警示（執行期產生）
├── backend/
│   ├── main.py                  ← wiring；startup 呼叫 auth.init_rate_limiting()
│   ├── db.py                    ← schema + 11 個 migrations（CURRENT_VERSION=11）
│   ├── helpers/                 ← 套件（拆自原 helpers.py）
│   │   ├── __init__.py          ← re-export 全部符號（向後相容）
│   │   ├── auth.py              ← 密碼、session、弱密碼政策
│   │   ├── settings.py          ← system_settings CRUD
│   │   ├── audit.py             ← audit log + 通知
│   │   ├── quotations.py        ← SQL 常數、save_quotation_json
│   │   ├── dates.py             ← _add_months、_warranty_expiry
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
│   ├── .initial_admin_credentials.txt  ← 僅新裝，用後刪
│   └── routers/                 ← auth, quotations, customers, system, ...
├── frontend/
│   ├── index.html · css/ · js/ · pages/ · static/
│   │   ├── js/quotation-form.js   ← ⚠️ 死碼（未載入）
│   │   ├── js/settlement.js       ← ⚠️ 死碼（未載入）
│   │   ├── pages/quotation-form.html  ← Alpine inline（真正的 quotationForm()）
│   │   ├── pages/settlement.html      ← Alpine inline（真正的 settlementPage()）
│   │   └── static/logo.png        ← MOTRIX 白字去背 PNG
├── uploads/projects/
└── 報價單PDF/
```

---

*維護提示：功能變更時先更新本檔「對應 §N 章節」，再在 §12 加一行摘要。死碼警告欄位如有整理（移除 .js、改用 include），記得更新 §2 與 §13。*
