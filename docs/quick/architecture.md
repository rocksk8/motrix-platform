# MOTRIX ERP — 架構、Sidebar、前端規範、目錄結構（§2／§6／§9／§13）

> 自 `MOTRIX-ERP-QUICK.md` 拆出（2026-09-23）。§ 編號沿用原編號，程式註解裡的「QUICK.md §N」依中樞檔的對照表找到本檔。
> 內容逐字搬移，未改寫；相對連結已改為自本目錄起算。

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
| `db.py` | 連線、`init_db()`、PRAGMA WAL、熱路徑欄位／索引；**2026-09-11 更正：CURRENT_VERSION=74**（本行長期未同步更新，先前記載的 46→68 皆已過時；v69–v74 為 TOTP／WebAuthn 相關，v74 見 §3.3c；v47–v68 詳細主題見 `MOTRIX-ERP-ARCHITECTURE-MAP.md` §4「資料庫演進索引」，含請款單/組織架構/案件階段正規化/專案併入案件管理/網路架構規劃書/自動化系統選型導覽/安全庫存/簽核代理人等；v32/v33 交換器選型導覽 `switch_guide` 表結構由正式機備份還原重建，詳見 db.py `_m032_switch_guide` 註解） |
| `helpers/` | 密碼、session、audit、notify、settings、弱密碼標記、`save_quotation_json()` |
| `archive.py` | 即時／每日／週備份；本機 SQLite 快照；**原子 JSON 寫入**（`_atomic_json_write`）；G: fallback |
| `backup_job.py` | 獨立備份腳本（Windows 工作排程器，不依賴 server） |
| `pdf_gen.py` | Edge Headless PDF；路徑讀 `system_settings["pdf_base_path"]`；**2026-09-07 起**所有 Edge 子行程呼叫（含 `network_plan_export.py`／`routers/reports.py`）共用 `helpers.EDGE_PDF_SEMAPHORE`（`BoundedSemaphore(3)`）限制同時執行數量，避免短時間多人觸發匯出時單機被一堆 Edge 行程拖垮 |
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
| `frontend/static/sidebar.js` | Topbar + Sidebar 注入；**強制改密導向**；離開警示 `bindNavGuard()`；`_FILE_MODULE` 頁面→模組對應；`build()` 自動更新 `localStorage.motrix_module_seen` 清除當頁 badge |
| `frontend/static/notif.js` | 通知 Bell + 側邊欄模組 badge（`_fetchModuleCounts()`）；所有動態內容用 **DOM API**（無 innerHTML） |
| `frontend/css/style.css` | CSS 變數：`--sidebar-w` `--topbar-h` `--accent` |

> **重要**：`frontend/js/` 目錄**僅存 2 個有效檔案**（case-management.js / reports.js），
> 其餘 21 個死碼 JS 已於 2026-07-22 清除。勿在此目錄新增非必要的 JS 檔案。

---

## §6 · Sidebar 結構

```
主選單     儀表板
業務       業務開發（dev-crm.html, dev_crm 模組旗標或 admin+）/ 報價單 / 簽核佇列（approval-queue.html）/
           簽核代理人（approval-delegates.html）/ 簽核歷史（approval-history.html，2026-09-14 新增）/
           案件管理（⚠️ 「專案管理」已於 2026-08-26 併入案件管理，projects.html 已刪除，不再是獨立項目）
           ※ 簽核三兄弟（佇列／代理人／歷史）共用 `quotation` 模組或 admin+ 的顯示條件
選型資料庫  場域選型導覽 / 網路架構選型導覽 / 交換器選型導覽 / 監控系統選型導覽 /
           門禁系統選型導覽 / 自動化系統選型導覽（automation-guide.html，DB v65，2026-08-26 起第七類，
           本文件先前未記載）/ 涵蓋度總覽（selection-db-overview.html, admin+ 限定）
廠商與採購 客戶 / 供應商 / **承攬商** / 料號 / **庫存管理**（inventory.html, inventory 模組旗標或 admin+）/ 採購
設備       設備登載 / 保固追蹤 / 網路架構規劃書（network-plans.html，DB v64，可綁案件也可獨立建立，netplan_edit 模組或 superadmin，本文件先前未記載，詳見 §7.12／`NETWORK-PLAN-MODULE-DESIGN.md`）
財務       應收帳款 / 營運報表（admin+ 或含 reports 模組；**2026-08-31 起內含第 13 個頁籤「出納」**，`cashier.html` 舊網址已退役為導向 stub）
工作       工作日誌（非 viewer 或含 work_log 模組） / 每日工作事項（非 viewer 或含 daily_task 模組）
系統       使用者 / 組織架構（org-structure.html，DB v48，本文件先前未記載）/ 簽核設定（superadmin）/
           簽核代理人（approval-delegates.html，DB v67，任何人可自助設定，本文件先前未記載）/
           出貨單簽核設定（superadmin）/ 歷史紀錄 / 版本紀錄 / Schema 狀態（superadmin）
```

- ~~簽核佇列不在 sidebar，在報價單內 tab~~（已過時：2026-08-20j 整合成獨立頁 `approval-queue.html` 後就有自己的側欄項目）
- 銷售訂單已移除（併入案件財務）
- `reports`：`admin+` 或含 `reports` 模組的使用者可見
- `work_log` / `daily_task`：非 viewer 或明確帶對應模組者可見（相容既有帳號）
- `承攬商管理`：`admin+`（`cPr` 旗標，同採購）可見；`vendor-contractors.html`
- **模組通知 badge**：所有模組 nav 項目（含子項）均有藍色 `sb-mod-*` badge，由 `_fetchModuleCounts()` 根據 `motrix_module_seen` 顯示其他人的更新計數；廠商採購/設備/財務各組同步顯示同一模組計數
- **選型資料庫**（2026-08-01 獨立成頂層 sidebar 區塊，不再掛在「業務」底下；`SELECTION-DB-INDEX.md` 是這個產品線的總索引，現為**七大類**，見下）：
  - **場域選型導覽**：`env-guide.html`；檢視 `env_guide` 模組旗標或 admin+（`cEnvG` 旗標）；編輯（新增/修改/刪除場域、建議、連結）與 Excel 匯出入另需 `env_guide_edit` 模組旗標或 superadmin；`users.html` 可分別授予兩者；**無** 模組通知 badge（資料變動頻率低，未接 `_fetchModuleCounts()`）
  - **網路架構選型導覽**：`netarch-guide.html`；檢視 `netarch_guide` 模組旗標或 admin+（`cNetG` 旗標）；編輯需 `netarch_guide_edit` 或 superadmin；瀏覽邏輯與場域選型導覽不同——**先選技術族系方塊，再看世代橫向對照卡片**（非矩陣/篩選），選型資料庫第二個上線的類別
  - **交換器選型導覽**：`switch-guide.html`；檢視 `switch_guide` 模組旗標或 admin+（`cSwitchG` 旗標）；編輯需 `switch_guide_edit` 或 superadmin；選型資料庫第三個上線的類別
  - **監控系統選型導覽**：`monitor-guide.html`；檢視 `monitor_guide` 模組旗標或 admin+（`cMonitorG` 旗標）；編輯需 `monitor_guide_edit` 或 superadmin；選型資料庫第四個上線的類別（2026-08-09），資料形狀與交換器選型導覽相同（相機分類×場域情境矩陣），第一批資料為 UniFi Protect G6 世代
  - **門禁系統選型導覽**：`access-guide.html`；檢視 `access_guide` 模組旗標或 admin+（`cAccessG` 旗標）；編輯需 `access_guide_edit` 或 superadmin；選型資料庫第五個上線的類別（2026-08-09），資料形狀同上（元件分類×場域情境矩陣），第一批資料為 UniFi Access
  - **自動化系統選型導覽**：`automation-guide.html`；檢視 `automation_guide` 模組旗標或 admin+；編輯需 `automation_guide_edit` 或 superadmin；DB v65，2026-08-26 起選型資料庫第七類，資料形狀同交換器/監控/門禁（情境×分類矩陣），見 §7.14。**本文件先前完全未記載此類別，2026-09-01 補上**
  - 上述類別在**歷史紀錄**（`audit-log.html`）與**版本紀錄**（`module-versions.html`）皆已比照其餘模組補上對應的 optgroup／actionLabel／色碼（teal 色系＋🧭 圖示，共用同一識別色，強調同屬一個產品線而非各自獨立模組）
  - **涵蓋度總覽**（2026-08-09）：`selection-db-overview.html`；admin+ 限定，無獨立模組旗標；彙總「品牌/型號目錄」型類別（不含場域選型導覽——資料形狀是情境×分層文字建議而非品牌目錄）在各世代/分類底下的品牌數與產品數，紅/黃/綠三色標示完全空白／偏薄弱／足夠；**不新增後端 API**，純前端呼叫既有各類別 GET 端點彙總而成。**2026-09-11 查證：先前確實漏了自動化系統選型導覽（第七類，2026-08-26 上線），已補**——`loadAll()` 原本只撈 netarch／switch／monitor／access／gateway 五組，而 `automation-guide.html::applyDeepLink()` 早就寫好接這頁深層連結的程式碼，只差那一組 fetch。**漏掉不會有任何錯誤訊息、頁面照常渲染**，所以新增第八類時務必同時補這頁；e2e `test_e2e_selection_overview_2026_09_11.py` 會比對六個區塊標題，漏了就紅
- **簽核設定**：`approval-settings.html`；superadmin 限定；2026-08-28 起單一頁面涵蓋全部五種文件類型（報價單／出貨單／發票開立簽核單／請款單／承攬商匯款申請）——頁面上方是套用範圍多選選單，勾選的類型共用「統一簽核流程設定」，取消勾選的類型各自在同一頁展開獨立編輯區塊；不再有各自獨立的 `shipping-approval-settings.html`／`invoice-voucher-approval-settings.html`（`contractor-voucher-approval-settings.html` 仍保留獨立頁面，見 §12 2026-08-28）；出貨單本身不是獨立 sidebar 項目，掛在「案件管理」頁面內的「出貨單」分頁，沿用 `case_manage`/`cCM`/`sb-mod-case`
- **簽核代理人**（2026-08-28，DB v67）：`approval-delegates.html`；任何人可自助委託簽核權限給他人，superadmin 可代替他人設定；核心解析 `helpers/tiered_approval.py::active_delegators_for()`，見 §7.13
- **組織架構**：`org-structure.html`；DB v48，處→部門二層；`manager_user_id` 已接入簽核流程動態解析（§4.1 已更正舊註記）
- **Schema 狀態**（2026-08-01）：`schema-status.html`；superadmin 限定；**純唯讀**診斷頁，顯示目前 db 版本 / 目標版本、狀態（✓最新／⚠尚未同步）、最後更新時間、完整 migration 清單；**全頁無任何操作按鈕或表單**——migration 於伺服器啟動時自動套用，此頁不提供「觸發乾跑」之類的操作；資料來源 `GET /api/system/schema-status`

---

## §9 · 前端規範

| 項目 | 做法 |
|------|------|
| 框架 | Alpine.js（2026-09-07 起自架，見下方「外部函式庫自架」） |
| JS | `frontend/js/{page}.js`（非 defer，先於 Alpine） |
| Auth | `init()` 讀 session；無 token → login |
| 強制改密 | session.mustChangePassword 或 sidebar 導向 |
| API | `Authorization: Bearer {token}`，**PATCH deal-tag 不可遺漏** |
| 自動存 | debounce 1.5s（`setDirty`）；`isDirty=false` 需在 API 成功回調內設定 |
| 客戶選公司 | `selectCustomer()` async；每次選擇都 `GET /api/customers/{id}`，**強制覆寫**聯絡人欄位 |
| No-cache | `.html` / `.css` / `.js` 皆 no-store |
| Excel | SheetJS（2026-09-07 起自架，客戶／供應商／料號／承攬商等頁面匯出入用） |
| XSS 防護 | 動態插入 API 資料一律用 DOM API，**禁止 innerHTML 插入非靜態內容** |
| 深色模式 | 全站色彩反轉濾鏡（不是另一套色票）。**`.topbar`／`.sidebar`／`.sidebar-overlay` 必須是 `<body>` 的直接子元素**——排除清單寫成 `body > *:not(.topbar):not(.sidebar):not(.sidebar-overlay)`，多包一層容器就對不上，整條側欄會被反轉成白底，而且容器有了 `filter` 會依 CSS 規範變成其中 `position:fixed` 元素的 containing block。新頁面照抄既有頁面骨架即可；違規由 `backend/tests/test_dark_mode_chrome_structure_2026_09_13.py` 擋下（見 §12 2026-09-13） |

**外部函式庫自架（2026-09-07）**：正式機是純內網部署（172.16.10.177，無對外網路依賴設計），先前 Alpine.js／Chart.js／SortableJS／frappe-gantt／SheetJS 全部從 `cdn.jsdelivr.net` 載入，若辦公室對外網路中斷或 CDN 被擋，整套 ERP 會直接打不開——這對一個刻意做成內網系統的應用是不必要的外部單點故障。已全部改成本機靜態檔案，`frontend/static/vendor/`：

```
alpine-3.17.1.min.js        （原 alpinejs@3.x.x 浮動版號，這裡固定下來）
chart-4.4.0.umd.min.js      （reports.html 原本用浮動的 @4，一併固定）
sortable-1.15.3.min.js
frappe-gantt-0.6.1.min.js／.css
xlsx-0.18.5.full.min.js     （SheetJS）
```

`pages/*.html` 引用 `../static/vendor/...`，`index.html` 引用 `static/vendor/...`（無 `../`，維持既有其他 static 資源的相對路徑慣例）。字型（`LINE Seed TW_OTF`）本來就已經自架，不受影響。之後若要升級這些函式庫版本，直接下載新版檔案覆蓋同名檔（或改檔名+改全部引用路徑），不必再依賴 CDN。

---

## §13 · 目錄結構（精簡，2026-09-01 依實際程式碼盤點更正）

> **完整版含每個 router 的檔案:行號、API 前綴、資料表對照，見 `MOTRIX-ERP-ARCHITECTURE-MAP.md` §2。本節維持精簡，只列骨架＋容易漏找的項目。**

```
MOTRIX-ERP/
├── MOTRIX-ERP-QUICK.md              ← 本文件（行為規格＋逐日 changelog 權威來源）
├── MOTRIX-ERP-ARCHITECTURE-MAP.md   ← 架構地圖＋建議＋踩坑索引（2026-09-01 新增，互補本文件）
├── CHANGELOG.md                     ← §12 的精簡版本，按版本倒序
├── DR-SOP.md · GITFLOW.md · APPLY-UPDATE-CHECKLIST.md · HTTPS-DEPLOY-CHECKLIST.md
├── NETWORK-PLAN-MODULE-DESIGN.md · MULTI-BRANCH-AUTO-UPDATE-DESIGN.md（規劃中，未列入排程）
├── SELECTION-DB-INDEX.md · {ENV,NETARCH,SWITCH,MONITOR,ACCESS,GATEWAY}-GUIDE-CONTENT.md · SWITCH-BRAND-REFERENCE.md
├── .gitignore
├── backup_alerts/                   ← 備份警示（執行期產生）
├── backend/
│   ├── main.py                      ← wiring only；34 個 app.include_router()；3 層 middleware
│   ├── db.py                        ← schema + 74 個 migrations（CURRENT_VERSION=74，見 §2／完整主題索引見 ARCHITECTURE-MAP §4）
│   ├── version_manifest.json        ← 模組版本紀錄（重啟後同步至 DB module_versions）
│   ├── helpers/                     ← 11 個檔案（拆自原 helpers.py）
│   │   ├── __init__.py              ← re-export 全部符號
│   │   ├── auth.py · settings.py · audit.py · quotations.py · dates.py
│   │   ├── email_notify.py · google_calendar.py · notification_prefs.py
│   │   ├── uploads.py               ← save_document_files/delete_document_file（附件上傳共用）
│   │   ├── startup.py               ← 啟動檢查、Edge 路徑解析
│   │   └── tiered_approval.py       ← ⭐ 五種文件類型共用的簽核 tiers 展開＋權限檢查唯一事實來源
│   ├── archive.py                   ← 備份；_atomic_json_write()；G: fallback；_mirror_uploads()
│   ├── pdf_gen.py · photos.py · network_plan_export.py
│   ├── backup_job.py · heartbeat_job.py   ← 獨立排程腳本（不 import main）
│   ├── autostart.bat · autostart_hidden.vbs · setup_{backup,autostart,heartbeat}_task.ps1
│   ├── tools/                       ← build_deploy_package.ps1 · apply_update.ps1 · check_guide_sync.py ·
│   │                                   audit_account_permissions.py · https_setup.ps1 · local_research_pipeline.py
│   ├── motrix_erp.db（正式）+ motrix_erp_demo.db（demo 隔離）
│   ├── db_backups/YYYY-MM-DD/（30天）+ quotation_instant/（G: fallback）
│   ├── tests/                       ← 114 個測試檔、874 題（2026-09-14 實際 collect 數）
│   │                                   其中 test_system_audit_2026_09_14.py 是「跨層稽核」
│   │                                   （備份涵蓋／守門缺漏／角色字串／組織外鍵），見 §12 同日條目
│   └── routers/（34 個檔案，主檔/財務/簽核/選型資料庫/系統支援五大類，完整清單與行號見 ARCHITECTURE-MAP §2）
│       ├── 主檔：auth／customers／suppliers／parts／inventory／org_structure
│       ├── 業務流程：quotations（全庫最大）／dev_crm／shipping_notes／case_action_items／daily_tasks／payslips
│       ├── 財務：contractor_vouchers／invoice_vouchers／payment_requests／cashier（2026-08-31 併入報表頁籤）
│       ├── 承攬商/採購：vendor_contractors／contractors
│       ├── 選型資料庫（七類）：env_guide／netarch_guide／switch_guide／monitor_guide／access_guide／gateway_guide／automation_guide（v65 新增）
│       ├── 其他業務：network_plans（v64）／projects（⚠️ 已不掛載，死碼保留）
│       └── 系統支援：dashboard／reports（全庫第二大）／system／approval_delegates（v67）／uploads／search／list_prefs（v56）／module_versions
├── frontend/
│   ├── index.html                   ← 儀表板（Alpine inline）
│   ├── css/style.css                ← 含全站共用 .btn/.tab/.chip 元件（2026-08-09 統一後）
│   ├── js/case-management.js · reports.js   ← ⭐ 僅有的 2 個有效外置 JS，其餘 48 頁全 inline
│   ├── pages/（50 個 .html，完整清單見本文件標頭目錄或 ARCHITECTURE-MAP §2）
│   └── static/sidebar.js · notif.js · logo.png
├── uploads/                         ← 各類附件（照片/回簽/發票等），_demo_* 前綴為 demo 隔離
└── deploy_packages/<timestamp>_<commit>/   ← build_deploy_package.ps1 產物，人工搬移到正式機
```
