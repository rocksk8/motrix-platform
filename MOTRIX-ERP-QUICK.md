# MOTRIX ERP — 開發快速參考

> 允碩整合集創（統編 60575481）｜ Tel: 04-3602-2818 ｜ info@miactw.com  
> 文件版本：**2026-07-17c**（架構優化：Schema migration 版本管理 + helpers 套件拆分 + CORS 限縮 + Edge 路徑可設定 + 報價單英文公司名稱更新）

---

## 1. 啟動與位址

| 項目 | 值 |
|------|-----|
| 開發啟動 | `backend\start.bat` |
| 更新後重啟 | `backend\restart.bat` |
| 本機 | http://localhost:666 |
| 區網 | http://172.16.11.211:666 |
| SQLite | `backend\motrix_erp.db`（WAL 模式） |

```
依賴關係：
  db.py ← helpers.py ← archive.py / pdf_gen.py / photos.py
                     ← routers/*.py ← main.py（wiring only）
```

**新增功能規則**

- API → 對應 `routers/xxx.py`，勿塞進 `main.py`
- 共用邏輯 → `helpers.py`
- 表結構 → `db.py:init_db()`
- 備份 → `archive.py`
- PDF → `pdf_gen.py`；照片水印 → `photos.py`（PIL 可選）

---

## 2. 系統架構總覽

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
| `db.py` | 連線、`init_db()`、PRAGMA WAL、熱路徑欄位／索引 |
| `helpers.py` | 密碼、session、audit、notify、settings、弱密碼標記、`save_quotation_json()` |
| `archive.py` | 即時／每日／週備份、本機 SQLite 快照、備份警示 |
| `pdf_gen.py` | Edge Headless PDF |
| `photos.py` | 專案照片水印 |
| `routers/*` | 業務 API |
| `main.py` | CORS、middleware、startup、static |

### 前端

| 路徑 | 說明 |
|------|------|
| `frontend/js/*.js` | 各頁 Alpine 元件（Phase 3 已外置） |
| `frontend/static/sidebar.js` | Topbar + Sidebar 注入；**強制改密導向** |
| `frontend/static/notif.js` | 通知 Bell |
| `frontend/css/style.css` | CSS 變數：`--sidebar-w` `--topbar-h` `--accent` |

---

## 3. 安全（2026-07-16 起強制）

### 3.1 帳號與密碼

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

### 3.2 解鎖密碼（報價單解鎖編輯）

- 僅 superadmin；與登入密碼獨立
- **不再自動寫入共用預設**
- 啟動若偵測歷史弱預設 → **清空 hash**，需至使用者管理重新設定
- 未設定：`POST /api/auth/verify-unlock` 回錯誤提示先設定

### 3.3 Session 與 API 保護

| 項目 | 值 |
|------|-----|
| Session | `sessions` 表，預設 30 天 |
| 白名單 | `/api/ping` · `/api/auth/login` · `/api/auth/logout` |
| 其餘 `/api/**` | 需 `Authorization: Bearer {token}` |
| 回應標頭 | `X-Content-Type-Options` · `X-Frame-Options` · `Referrer-Policy` |

### 3.4 角色與模組

```
superadmin > admin > sales > engineer > viewer
```

| 角色重點 | 說明 |
|----------|------|
| `engineer` | 預設無 `financial_view`，不可看金額／財務 |
| 模組例 | `project_manage` · `project_approve_eng` · `project_approve_biz` · `financial_view` |
| 報價列表過濾 | 非 admin+ 僅見 `sales_person = 自己 display_name` |

> 已知限制：業務歸屬用顯示名稱，改名會影響歷史過濾（後續可改 `sales_person_id`）。

---

## 4. 資料模型

### 4.1 主要資料表

```sql
quotations      -- 熱路徑欄位 + data_json 完整物件
  quote_no PK, status, deal_tag, settle_status,
  customer_name, project_name, total, pretax,
  direct_margin_pct, net_margin_pct, sales_person,
  quote_date, valid_days, data_json, created_at, updated_at, ...

users           -- + must_change_password, unlock_password_hash
sessions        -- token, expires_at
customers / suppliers  -- 主欄 + data_json（contacts, visits, tags）
parts, projects, project_logs
system_settings, audit_log, notifications
quote_seq       -- 月序 MQ-YYYYMM-NNN
```

**索引**：`deal_tag` · `settle_status` · `sales_person`

### 4.2 data_json 與熱路徑同步

- 巢狀結構（品項、簽核、案件、精算）仍在 `data_json`
- **`deal_tag` / `settle_status` 為正規欄位**，列表／報表／儀表板優先讀欄位
- 寫入統一走 `helpers.save_quotation_json()`（自動同步欄位 + `updated_at`）
- 讀取相容：`SQL_DEAL_TAG` / `SQL_SETTLE_STATUS`（欄位為空時 fallback `json_extract`）

```
create / put / deal-tag / settlement / payment / case-record / approve / reject
  → save_quotation_json() 或同等步邏輯
```

### 4.3 樂觀鎖（併發）

| 端點 | 機制 |
|------|------|
| `PATCH .../case-record` | body 可帶 `_expectedUpdatedAt`；不符 → **409** |
| `PATCH .../customers/{id}/visits` | body 可帶 `expectedUpdatedAt` → **409** |
| `PATCH .../suppliers/{id}/visits` | 同上 |

回傳皆含 `updated_at`，前端可回寫後再送。

---

## 5. 核心業務流程

### 5.1 報價狀態

```
草稿 → 待審核（送出）→ 已送出（簽核完成）
         ↑ 解鎖編輯儲存後強制回到待審核
```

- 單號：`MQ-YYYYMM-NNN`（`/api/next-quote-no`）
- 僅**草稿**可刪
- **已送出**預設鎖定；superadmin 解鎖密碼後可改，儲存後重鎖並重送審

### 5.2 案件進度 dealTag

```
未提供 → 已提供 → 未成案
                 → 已成案（確認後 UI 鎖定）
                 → 已結案（僅案件管理「完結案」）
```

- 欄位同步：`quotations.deal_tag`
- 日誌：`data_json.statusLog[]`
- **未成案 / 已成案**：限 admin+ 操作；選未成案強制跳確認 Modal（可填原因）
- 取消時自動還原 `deal_tag` 舊值

### 5.3b 報價清單動態徽章（quotations.html）

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

### 5.3c 報價單 PDF 匯出（quotation-form.html）

**工具列按鈕邏輯**（三擇一顯示）：

| 條件 | 按鈕 | 說明 |
|------|------|------|
| `!q.quoteNo`（新增未儲存） | 預覽報價單（neutral） | 讓使用者確認版型格式 |
| `q.dealTag === '未成案'` | 預覽報價單（紅色） | 禁止匯出 |
| 其餘已儲存且非未成案 | 匯出 PDF（`directExport()`） | 系統後端產生，瀏覽器直接下載 |

管理員另有 **匯出次數** 獨立按鈕（`showExportLog()`，僅 admin+）。

**directExport() 流程**：
1. 先 `POST /api/quotations/{no}/export` 記錄匯出（日期、時間、使用者 displayName）→ 更新 `q.exportCount`
2. 同時 `GET /api/quotations/{no}/pdf-download` 取得 PDF blob
3. `URL.createObjectURL(blob)` → `<a download>` 觸發下載
4. 按鈕期間顯示旋轉 Spinner，`exporting` 狀態防重複點擊

**PDF 浮水印（quotation-form.html 預覽 & pdf_gen.py 後端 PDF）**：

| 條件 | 文字 |
|------|------|
| `dealTag === '未成案'` | 本案報價未成立 / 僅供存查備存使用 |
| 其他非已送出/已確認 | 報價單預覽稿 / 尚未正式生效 |
| 已送出/已確認（非未成案） | 無浮水印 |

前端：CSS grid 3×4（12格）+ Alpine `x-for="n in 12"`，所有文字 `rgba(185,28,28,...)` 紅色，旋轉 -28°。  
後端 `pdf_gen.py`：同樣條件加浮水印至 Edge Headless 生成 HTML。

**四、報價合計** 標題在 PDF 預覽（`#pdf-preview-content`）與後端 PDF 中均有加入。

### 5.3 簽核（tiers 並行層）

```
設定：system_settings.approval_flow → { tiers:[{order, approvers:[]}] }
送出：快照至 data_json.approval.tiers[]
規則：同層全員 approved → currentTier++；末層完成 → status=已送出 + PDF
退回：清除 approval，status=草稿
舊 steps[]：執行期動態轉 tiers
```

- 有流程：允許自簽（比對當層 username）
- 無流程（預設超管）：**禁止申請人自簽**

### 5.4 案件管理三主 Tab

| Tab | 內容 |
|-----|------|
| 商務 | 合約資訊 + 收款管理（%／含稅／未稅雙向） |
| 執行 | 進度 / 叫料 / 設備 / 保固備注 |
| 財務 | KPI + 精算結果（需 `canSeeFinancial`） |

### 5.5 成本精算 settlement

- 入口：已成案／已結案 → `settlement.html?no=`
- 存於 `data_json.settlement`；欄位 `settle_status` = `draft` \| `finalized`
- 每次儲存寫入 `editHistory[]`

### 5.6 專案

- `projects` + `project_logs`；與報價 M:N（`linked_cases`）
- 確認事項兩階段：`project_approve_eng` → `project_approve_biz`
- 照片：Pillow 水印 + GPS EXIF → `uploads/projects/...`

---

## 6. Sidebar 結構

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

## 7. API 速查（base `/api`）

### Auth / Users

| Method | Path | 說明 |
|--------|------|------|
| GET | /ping | 心跳 |
| POST | /auth/login | 回傳含 `mustChangePassword` |
| POST | /auth/logout | |
| GET | /auth/me | 含 `mustChangePassword` |
| PATCH | /auth/change-password | ≥8；清除強制改密 |
| POST | /auth/verify-unlock | superadmin 解鎖驗證 |
| GET/POST | /users | 列表／新增 |
| PUT/DELETE | /users/{id} | |
| PATCH | /users/{id}/active | |
| PATCH | /users/{id}/unlock-password | ≥8 |

### 報價 / 簽核 / 精算

| Method | Path | 說明 |
|--------|------|------|
| GET | /next-quote-no | |
| GET/POST | /quotations | 列表（角色過濾）／建立 |
| GET/PUT/DELETE | /quotations/{no} | |
| PATCH | /quotations/{no}/status | |
| PATCH | /quotations/{no}/deal-tag | 同步 `deal_tag` 欄位 |
| PATCH | /quotations/{no}/case-record | 可樂觀鎖 |
| PATCH | /quotations/{no}/payment/{idx} | 收款標記 |
| GET/PUT | /quotations/{no}/settlement | 精算 |
| GET | /quotations/{no}/pdf-download | Edge PDF |
| POST | /quotations/{no}/export | |
| GET | /approval-queue | |
| POST | /quotations/{no}/approve \| reject | 並行層簽核 |

### 主檔 / 專案 / 報表

| Method | Path | 說明 |
|--------|------|------|
| CRUD | /customers · /suppliers · /parts | 供應商列表 admin+ 才有資料 |
| GET | /customers/{id} | 單一客戶詳情（含 contacts/address，供報價單選公司時 fresh fetch） |
| PATCH | /customers/{id}/visits · /suppliers/{id}/visits | 可樂觀鎖 |
| GET | /company/tax/{id} · /company/search | GCIS Proxy |
| CRUD | /projects · logs · photos | |
| GET | /uploads/{path}?token= | 照片（img 用 query token） |
| GET | /dashboard/stats · /monthly | |
| GET | /devices · /receivables | |
| GET | /reports/financial · /excel · /pdf | admin+ |
| GET/PUT | /settings/approval-flow | |
| GET/PATCH | /notifications/* · /audit-log | |

---

## 8. 備份與還原

### 路徑

```
雲端（需 G: 掛載）
  G:\我的雲端硬碟\系統存檔\
    即時備份\報價單|客戶|供應商\
    每日備份\YYYY-MM-DD\  （JSON 七表 + motrix_erp.db）
    週備份\YYYY-WNN\

本機（不依賴 G:，務必保留）
  backend\db_backups\YYYY-MM-DD\motrix_erp.db   ← SQLite Online Backup，保留 30 天
  backup_alerts\BACKUP_ALERT.txt                ← 雲端異常醒目警示
  backup_alerts\YYYY-MM-DD.log
```

### 行為

| 條件 | 行為 |
|------|------|
| G: 正常 | 即時 JSON + 每日 JSON + 雲端 DB 副本 + 本機快照 |
| G: 未掛載 | **不再靜默**：寫 `BACKUP_ALERT.txt` + audit `backup.alert`；**仍做本機 SQLite 快照** |
| 恢復正常 | 清除 sticky 警示檔 |
| 排程 | 啟動 + 每 2h 日備；每 6h 週備 |

Audit：`backup.daily_ok` · `backup.weekly_ok` · `backup.sqlite_snapshot` · `backup.alert`

**還原優先序**：本機 `db_backups` 整庫 → 雲端 `motrix_erp.db` → JSON 重建（最後手段）

---

## 9. 前端規範

| 項目 | 做法 |
|------|------|
| 框架 | Alpine.js CDN |
| JS | `frontend/js/{page}.js`（非 defer，先於 Alpine） |
| Auth | `init()` 讀 session；無 token → login |
| 強制改密 | session.mustChangePassword 或 sidebar 導向 |
| API | `Authorization: Bearer {token}` |
| 自動存 | debounce 1.5s（`setDirty`） |
| 客戶選公司 | `selectCustomer()` 為 async；每次選擇都 `GET /api/customers/{id}` 取最新資料，**強制覆寫**聯絡人欄位（姓名、電話、Email、傳真） |
| No-cache | `.html` / `.css` / `.js` 皆 no-store |
| Excel | SheetJS CDN（客戶／供應商） |

---

## 10. 成本公式（報價）

```
售價 = CEILING(成本 × 1.05 / (1 − 毛利率), 5)
管銷分攤 = 稅前售價 × 10%
公益捐款 = 直接毛利 × 1%
```

`FORM_VERSION`：模板版號常數（如 V1.1），與單筆資料無關；改版型時手動遞增。

---

## 11. 已知限制與後續建議

| 優先 | 項目 |
|------|------|
| 中 | 業務歸屬改 `sales_person_id`（勿綁 display_name） |
| 中 | 照片 URL 改短時效 signed URL（避免長效 token 進 query） |
| 中 | `quotation-form` 殘餘顯示亂碼（對照 `.recovered` 修 UTF-8） |
| 低 | 區網 HTTPS／反向代理 |
| 低 | 關鍵 API 自動化測試 |
| 低 | 文件拆 `CHANGELOG.md` 與本速查分離（本檔已精簡 changelog） |

---

## 12. 變更摘要（精簡）

### 2026-07-17c — 架構優化（外部顧問建議 P0/P1）

- **Schema migration 版本管理**：`schema_version` 表 + 9 個具名 migration（`db.py`）；取代原本 `try/except ALTER TABLE` 亂序堆疊；新增欄位只需加 `_mNNN_xxx()` 函數並遞增 `CURRENT_VERSION`
- **`helpers/` 套件拆分**：`helpers.py`（507 行，7 職責）→ `helpers/{auth,settings,audit,quotations,dates,startup}.py`；`__init__.py` 完整 re-export，現有 import 無需修改
- **啟動掃描節流**：`flag_weak_passwords` / `init_unlock_passwords` 每日只跑一次（`system_settings` 記錄日期），避免每次重啟跑 PBKDF2
- **Legacy migration 一次化**：`fix_legacy_*` / `migrate_legacy_visits` 改為 migration 7-9，永遠只跑一次
- **CORS 限縮**：`allow_origins=["*"]` → 明確限 `localhost:666` + `172.16.11.211:666`
- **Edge 路徑可設定**：移除硬碼 `C:\Program Files (x86)\...msedge.exe`；新增 `GET/PATCH /api/settings/edge-path`；`_get_edge_path()` 優先讀 DB，fallback 兩個候選路徑
- **前端安全**：刪除 `quotation-form.html.bak2` 與 `.recovered`（曾被靜態伺服器 serve）
- **UI 更新**：Topbar 標題 `ERP 營運管理系統` → `Motrix 營運系統`；Logo 換新版白字去背 PNG；報價單英文公司名稱 `MARGIN INTEGRATED AGGREGATES CO., LTD.` → `MOTRIX Synergy Integration Corp.`（4 處）

### 2026-07-17b — 代理報價人選取 + 送審備註

- **報價人 Select**：草稿 / 解鎖狀態下顯示 `<select>` 列出所有啟用使用者；鎖定狀態 fallback readonly
- **自動帶入**：新建時 `salesPerson/Phone/Email/Username` 自動填為當前登入者；舊資料開啟時依 displayName 反查 `salesPersonUsername`
- **代理徽章**：`isSalesPersonChanged`（`salesPersonUsername !== session.username`）為 true 時欄位標籤顯示橙色「代理」小徽章
- **送出審核 Modal**：取代 `confirm()`，顯示報價單／客戶／報價人摘要；若代理則額外顯示送出人，並強制填寫代理原因（空白則阻止送出）
- **代理原因寫入審核記錄**：`approval.reasons[0]` 插入「代理送出：由 X 代 Y 送出，原因：…」；`approval.delegateSubmitter/delegateNote` 額外欄位存檔
- **toast 方法**：補上 `toast(msg, duration)` 解決既有呼叫遺漏問題
- 修改 `data_json.q.salesPersonUsername`（新增欄位，無需 DB migration）

### 2026-07-17 — 報價單 UI 強化 · PDF 直接下載 · 客戶聯絡人同步

- **動態狀態徽章**：`dealDisplayStatus(q)` 依 status＋deal_tag 組合顯示 11 種文案（含「已退回」取代「已拒絕」）
- **未成案 / 已成案 鎖定**：限 admin+；選未成案跳確認 Modal（可填原因）；取消自動還原舊值
- **浮水印系統**：前端預覽 CSS grid 3×4 十二宮格；後端 pdf_gen.py 同步；紅色旋轉字組；兩種條件（未成案 / 非已送出）
- **四、報價合計** 標題加入 PDF 預覽與後端 PDF
- **PDF 直接下載**（`directExport()`）：先 `POST /export` 記錄匯出人/時間，再 `GET /pdf-download` blob 下載；按鈕三態（新建→預覽 / 未成案→紅預覽 / 一般→匯出PDF）
- **匯出次數** 獨立按鈕（admin+），顯示完整匯出 log（倒序）
- **客戶聯絡人強制同步**：`selectCustomer()` 改 async，每次選公司呼叫 `GET /api/customers/{id}`，**強制覆寫**所有聯絡欄位
- **後端新端點**：`GET /api/customers/{cid}`（`routers/customers.py`）

### 2026-07-16 — 安全 · 備份 · 熱路徑 · 架構硬化

- **P0 安全**：`must_change_password`、弱密碼標記、≥8、解鎖不再共用預設、文件去密、安全標頭
- **P0 備份**：本機 SQLite 日快照 30 天；G: 失敗寫 `backup_alerts` + audit
- **P1 熱路徑**：`deal_tag` / `settle_status` 欄位 + 索引；`save_quotation_json()` 統一寫入
- **硬化**：SQLite WAL；收款／簽核／案件／精算寫入同步；visits／case-record 樂觀鎖 409

### 2026-07-15（摘要）

案件三 Tab、營運報表＋精算 Modal、並行簽核 tiers、解鎖重送審、PDF 無瀏覽器列印、editHistory、毛利率對比、每日備份、前端 Phase 3 JS 外置

### 2026-07-11～14（摘要）

專案模組、engineer 角色、解鎖編輯、後端模組化、通知系統、客戶供應商標籤／Excel、簽核佇列嵌入報價單

---

## 13. 目錄結構（精簡）

```
MOTRIX-ERP/
├── MOTRIX-ERP-QUICK.md          ← 本文件
├── .gitignore
├── backup_alerts/               ← 備份警示（執行期產生）
├── backend/
│   ├── main.py                  ← wiring
│   ├── db.py                    ← schema + 9 個 migrations（CURRENT_VERSION）
│   ├── helpers/                 ← 套件（拆自原 helpers.py）
│   │   ├── __init__.py          ← re-export 全部符號（向後相容）
│   │   ├── auth.py              ← 密碼、session、弱密碼政策
│   │   ├── settings.py          ← system_settings CRUD
│   │   ├── audit.py             ← audit log + 通知
│   │   ├── quotations.py        ← SQL 常數、save_quotation_json
│   │   ├── dates.py             ← _add_months、_warranty_expiry
│   │   └── startup.py           ← 啟動檢查、Edge 路徑解析
│   ├── archive.py · pdf_gen.py · photos.py
│   ├── motrix_erp.db
│   ├── db_backups/YYYY-MM-DD/   ← 本機整庫快照
│   ├── .initial_admin_credentials.txt  ← 僅新裝，用後刪
│   └── routers/                 ← auth, quotations, customers, ...
├── frontend/
│   ├── index.html · css/ · js/ · pages/ · static/
│   │   └── static/logo.png      ← MOTRIX 白字去背 PNG
├── uploads/projects/
└── 報價單PDF/
```

---

*維護提示：功能變更時先更新本檔「對應章節」，再寫第 12 節一行摘要。細節 changelog 勿再堆進檔首。*
