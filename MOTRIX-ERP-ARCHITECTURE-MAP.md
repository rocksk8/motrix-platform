# MOTRIX ERP — 架構地圖與模組建議書

> 產出日期：2026-09-01｜依據：實際程式碼盤點（`db.py` CURRENT_VERSION=68、`git log` 最新 commit `8f40e4e`）
> 交叉核對 `MOTRIX-ERP-QUICK.md`（文件版本標記 2026-08-20，§7 API 清單只到 v46/25 個 router，已落後程式碼 22 個 migration／9 個 router）
> **用途**：①未來要改哪個功能，先查本文件 §2 找到檔案位置與行號範圍，再進 `MOTRIX-ERP-QUICK.md` 對應 §N 查行為規格細節 ②新對話開場快速建立系統全貌 ③§6 是依專業軟體慣例给出的優化建議清單，供排優先序參考 ④§5 已知限制／§8 踩坑教訓，動工前先掃一眼避免重蹈覆轍
> 本文件不取代 `MOTRIX-ERP-QUICK.md`（那份仍是「行為規格與逐日 changelog」的權威來源），本文件是「結構地圖＋建議＋待辦清單＋踩坑索引」四合一的補充文件，兩份互補，一起讀

---

## §0 · 規模統計（2026-09-01 實測）

| 項目 | 數值 |
|---|---|
| 後端 routers | 34 個檔案，21,401 行，約 260+ 個 API 端點 |
| 後端 helpers | 11 個檔案，3,318 行（另有 audit.py/uploads.py 未在 QUICK.md §2 舊清單中） |
| `db.py` | 2,859 行，68 個 migration（v1→v68），schema 演進橫跨約 45 天高強度開發 |
| 前端頁面 | 50 個 `.html`（`frontend/pages/`），其中僅 2 個有外置 JS（`case-management.js`/`reports.js`），其餘全 inline |
| 測試 | `backend/tests/` 45 個測試檔（依 memory 記錄近期為 308/308 全過，本次盤點粗抓約 245+ test 函式，實際數字以最新 `pytest tests/` 結果為準） |
| 部署模式 | 半自動「打包→人工搬移→套用」（§15），無 CI/CD、無多開發者協作流程 |

**核心結論**：這不是一個小型工具，是一套涵蓋 CRM／報價簽核／專案執行／庫存／承攬商採購／HR／六大類技術選型知識庫／財務憑證流的完整企業應用，單人以 AI 協作方式在約一個半月內從零建到目前規模。§6 的建議會反映這個事實——多數「專業軟體會怎麼做」的答案是「MOTRIX 已經做到了，甚至比很多中小企業採購的套裝軟體更貼合實際流程」，真正的落差集中在**基礎設施韌性**（單機、無 CI、消費級雲端硬碟備份）而非業務邏輯深度。

---

## §1 · 技術棧與依賴關係

```
Frontend: Alpine.js (CDN) + 純 HTML/CSS，無建置流程、無框架打包
          frontend/static/sidebar.js  → topbar/sidebar/離開警示/模組 badge
          frontend/static/notif.js    → 通知 bell/模組活動計數
          frontend/js/case-management.js, reports.js  → 唯二外置頁面元件
          其餘 48 個頁面：Alpine 邏輯 inline 在各自 <script> 內（勿找外置 JS）
                    │ Bearer token（localStorage.motrix_session）
Backend:  FastAPI (main.py, 275 行, wiring only)
          ├─ 3 層 middleware：no_cache_static → auth_middleware(含閒置逾時) → security_headers
          ├─ 34 個 routers（app.include_router x34，main.py:232-265）
          ├─ helpers/（11 檔）：auth/audit/dates/email_notify/google_calendar/
          │                     notification_prefs/quotations/settings/startup/
          │                     tiered_approval/uploads
          ├─ archive.py（備份，原子寫入）
          ├─ pdf_gen.py（Edge headless PDF）／photos.py（Pillow 水印）
          └─ db.py（2859行，68 migrations，CURRENT_VERSION=68）
                    │
SQLite (WAL)  motrix_erp.db（正式）+ motrix_erp_demo.db（demo 隔離）
                    │
備份: G:\我的雲端硬碟（即時/每日/週）+ 本機 db_backups/
```

**認證流程**：`main.py:76-159 auth_middleware()` — Bearer token → `sessions` 表查詢 → 角色分流閒置逾時（superadmin/admin 2h，其餘 8h）→ `must_change_password` 白名單檢查。Demo 帳號在 token 前綴 `DEMO_` 時於此處（`main.py:97`）切換 `contextvars` 路由到隔離 DB，此後全鏈路 `get_db()` 自動導向。

---

## §2 · 模組地圖（依業務領域分組）

> 每個模組列出：**後端檔案(行數)** ｜ **前端頁面** ｜ **核心資料表** ｜ **API 前綴** ｜ 現況重點。行號為 2026-09-01 盤點時的實際行號，供快速定位。

### 2.1 認證與使用者 `auth.py` (653行)
- 前端：`login.html`、`users.html`、`change-password.html`
- 資料表：`users`、`sessions`、`login_rate_limit`
- API：`/api/auth/*`、`/api/users/*`（`auth.py:176-627`）
- 重點：PBKDF2-SHA256(260k)、per-IP rate limit（5 敗鎖 15 分）、自訂角色（`system_settings.custom_roles`）、角色顯示名稱可自訂（`role_labels`）。**無 MFA**（見 §6.9）。

### 2.2 業務開發 CRM `dev_crm.py` (1038行)
- 前端：`dev-crm.html`（雙欄，`devCrmPage()` inline）
- 資料表：`dev_cases`、`dev_logs`
- API：`/dev-cases/*`、`/dev-logs/*`（`dev_crm.py:250-922`，DB v27，連結審核制 v42）
- 重點：洽談中→成案→未成案 狀態機；連結報價單走審核制（`request-relink-quote`/`approve-relink-quote`）非直接改；非 admin 僅見自己/被指派案件（`_can_access_case()`）；軟刪除+待審核；久未追蹤自動偵測（`schedule_dev_case_stale_check()`，main.py:226）。

### 2.3 報價單與簽核引擎 `quotations.py` (3656行，全庫最大檔案)
- 前端：`quotations.html`、`quotation-form.html`（inline `quotationForm()`）、`approval-queue.html`
- 資料表：`quotations`（熱路徑欄位+`data_json`）
- API：`/api/quotations/*`、`/api/approval-queue*`（`quotations.py:431-3068`，草稿/簽核核心邏輯區）
- 重點：草稿→待審核→簽核中(並行tiers)→已送出；單號 `MQ-YYYYMM-NNN`；解鎖編輯需 superadmin 密碼；成本公式見 §5 §10（QUICK.md）。簽核 tiers 純邏輯已抽到 `helpers/tiered_approval.py`（v22 起五種文件類型共用）。

### 2.4 案件管理（報價單延伸的執行層，非獨立資料表）
- 後端仍在 `quotations.py`：案件記錄整包存檔 `case-record`（L1480-1720）、案件階段 CRUD `stages`（L1982-2259，DB v51 起有獨立 `case_stages`/`case_stage_visits` 表，**雙向同步中**，未完全遷移，見 §5 已知限制）、款項 `payment/{idx}`（L2287-2670）、精算 `settlement`（L2670-2815）、解鎖/半解鎖 `case-unlock`/`case-lock`（L1410-1480，DB v61）、案件變更審核佇列 `case-changes`（L1720-1769）
- `case_action_items.py` (213行)：`/api/quotations/{quote_no}/action-items`（代辦事項）
- 前端：`case-management.html`（唯一有外置 JS `case-management.js` 支援）、`case-stage-board.html`（跨案看板+時間軸）
- 重點：五個 Tab（案件資訊/執行進度/承攬商/動態/財務）；動態 Tab 合併 5 種來源（見 QUICK.md §5.4b）；已結案案件半解鎖走 `case_change_requests` 排隊表（DB v61，僅 8 端點支援排隊，13 端點直接 403）。

### 2.5 出貨單 `shipping_notes.py` (708行)
- 前端：`case-management.html` 內「出貨單」Tab（無獨立頁面/sidebar 項目）
- 資料表：`shipping_notes`（DB v34）
- API：`/api/shipping-notes/*`（`shipping_notes.py:92-692`）
- 重點：草稿→待審核→簽核中→已核准，另有獨立於狀態機的「已回簽」toggle；一案多單分批出貨；品項不含金額。

### 2.6 承攬商 / 外包人員 `vendor_contractors.py` (822行) + `contractors.py` (322行)
- 前端：`vendor-contractors.html`（承攬商往來）、`contractors.html`（外包名冊）
- 資料表：`vendor_contractors`、`contractor_dispatches`、`contractors`
- API：`/api/vendor-contractors/*`、`/api/contractor-dispatches/*`（`vendor_contractors.py:164-748`）、`/api/contractors/*`（`contractors.py:151-287`）
- 重點：派發狀態機 draft→sent→confirmed→pending_acceptance→accepted→completed（任意非終態可 cancelled）；外包名單人員可個別計費（`personnel_json` 快照）；承攬商欄位選填（純點工案件）。

### 2.7 財務憑證三兄弟：匯款申請／發票開立／請款單
| 模組 | 後端 | 前端 | 表 | DB版本 |
|---|---|---|---|---|
| 承攬商匯款申請 | `contractor_vouchers.py` (683行) | `case-management.html` 承攬商Tab | `contractor_payment_vouchers` | v45 |
| 發票開立簽核單 | `invoice_vouchers.py` (687行) | `case-management.html` 案件資訊Tab | `invoice_vouchers` | v46/v47 |
| 請款單 | `payment_requests.py` (798行) | `payment-request-form.html` | `payment_requests` | v53 |

三者架構高度一致（草稿→待審核→簽核中→已核准，snapshot_json 凍結、PDF、export_log），簽核流程可選「統一 `unified_approval_flow`」或各自獨立（`/api/settings/approval-flow-scope`，2026-08-28 起）。**這是全系統唯一稱得上「準會計憑證流」的部分**，見 §6.1 建議。

**2026-09-01 起新增第四個角色：`accounting_export.py`**——不是憑證流本身，是憑證流的**下游匯出層**：把已核准/已收款/已匯款的事件轉成 T100（鼎新）標準傳票 Excel（現金基礎，借貸自動平衡），供財務手動匯入 T100。三個事件來源：①已收款發票（`quotation_payment`）②已匯款承攬商費用（`contractor_voucher`）③已付款料件/設備進貨（`stock_batch`，DB v70 `stock_batches`，見 §2.9）。`GET/PUT /api/settings/t100-export-config`（科目代號對照，superadmin 維護）＋ `GET /api/reports/t100-export/vouchers`（Excel）＋ `GET .../preview`（JSON 預覽）＋ `POST .../confirm`／`POST .../unconfirm`（財務標記「已實際匯入 T100」，DB v69 `t100_export_confirmations`，標記後永久排除於之後匯出/預覽，避免重複匯入）＋ `GET .../confirmed`（稽核清單）。這是 §6.1 建議「先做批次匯出、不做即時 API 對接」的實作，詳見 §6.1 更新說明。

**科目代號分維度（2026-09-01 同輪，DB v71）**：使用者要求銀行帳戶與料件分類分開設定科目代號。**銀行帳戶採快照模式**（不是查表）——`contractor_payment_vouchers`/`stock_batches` 新增 `paid_bank_account_name/code` 欄位、報價單款項 JSON 新增 `bankAccountName/Code`，標記已付款/已收款當下直接把選的帳戶寫死在那筆交易上，之後設定頁的銀行帳戶清單怎麼改都不會回頭影響舊交易（`bankAccounts` 設定清單純粹是給 UI 下拉選單用）。**料件分類則是即時查表**（`inventoryExpenseAccounts: {分類: 代號}`）——分類本身不變，財務事後更正代號會套用到所有未確認的舊事件，跟其餘固定科目走同一套邏輯。三個「標記已付款/已收款」UI 都已加上銀行帳戶下拉（`case-management.html`／`reports.html`出納分頁／`inventory.html`）。

**銀行帳戶欄位自動帶入預設值（2026-09-02）**：使用者要求「須帶入當時填寫或是預設的匯款帳戶」——三個標記 Modal 開啟時依序嘗試①該對象（承攬商/供應商/客戶）上次標記用的帳戶（三支新查詢端點：`contractor_vouchers.py::get_last_paid_bank_account()`／`inventory.py::get_last_paid_bank_account()`／`quotations.py::get_last_received_bank_account()`，皆純讀取）②`t100-export-config.defaultBankAccountCode`（系統預設，設定頁銀行帳戶清單可點 ☆ 指定）③兩者皆無才空白；使用者仍可手動覆蓋。無 DB migration。

### 2.8 出納 `cashier.py` (276行，2026-08-28 新增，QUICK.md 舊版完全沒記載)
- 前端：併入「營運報表」頁籤（非獨立 sidebar 項目）
- API：`/api/cashier/payable-queue`、`receivable-queue`、`summary`、`execution-history`、`export`（`cashier.py:117-192`）
- 重點：應付佇列（已核准未匯款的承攬商匯款申請）＋應收佇列彙總視圖，本質是 §2.7 三憑證流的**唯讀彙總層**，不是獨立資料源。

### 2.9 客戶／供應商／料件／庫存
| 模組 | 後端 | 資料表 |
|---|---|---|
| 客戶 | `customers.py` (161行) | `customers`（`C-YYYYMM-NNN`） |
| 供應商 | `suppliers.py` (145行) | `suppliers`（`S-YYYYMM-NNN`） |
| 料件主檔 | `parts.py` (169行) | `parts`（含 v66 `safety_stock`） |
| 序號級庫存 | `inventory.py` | `stock_items`（DB v38）＋ `stock_batches`（DB v70，2026-09-01 新增批次表頭） |

重點：序號級庫存（`stock_items`）與批次進貨（`batch_no`）＋安全庫存水位燈號（2026-08-28 新增）已是相對成熟的進銷存邏輯；扣庫存掛勾在出貨單核准與設備登載兩處（`_sync_device_stock()`）。**2026-09-01 新增**：`stock_batches` 批次表頭補上供應商/發票號/付款狀態（`is_paid`/`paid_by`/`paid_at`，比照承攬商匯款申請模式），既有批次回填但 `is_paid` 預設 0（過去從未追蹤，非假設已付款）；`qty`/`total_cost` 仍即時從 `stock_items` 群組加總不信任表頭快取。這是 §2.7 財務憑證下游 `accounting_export.py` 的第三個事件來源。

### 2.10 專案管理 `projects.py` (592行)
- 前端：無獨立頁面（2026-08-26 `_m062_case_project_merge` 已併入案件管理，`projects.html` 已刪除，僅保留舊 API 供內部沿用）
- 資料表：`projects`、`project_logs`
- 重點：**已被案件管理吸收**，之後若在文件或程式碼看到「專案」一詞，先確認是不是在講已併入 case-stage-board 的東西，不要重新開發。

### 2.11 網路架構規劃書 `network_plans.py` (338行，DB v64，2026-08-26 新增)
- 前端：`network-plans.html`（列表）、`network-plan-form.html`（10 分頁表單）
- 資料表：`network_plans`
- API：`/api/network-plans/*`（`network_plans.py:59-338`），含 Excel/PDF 匯出、Excel 匯入
- 重點：可綁案件也可獨立建立；10 個分頁涵蓋 WAN/設備清單/VLAN/IP/PortProfile/交換器Port/防火牆/IP-Port群組/無線SSID/線路幹線；MAC/序號可挑選現有庫存。**注意與 §2.12 選型資料庫的 `netarch_guide` 是完全不同的兩個東西**（QUICK.md 已明確標註過這個易混淆點）。

### 2.12 選型資料庫（七大類，公司獨有知識庫產品線）
| 類別 | 後端 | 資料形狀 | DB版本 |
|---|---|---|---|
| 場域選型導覽 | `env_guide.py` (255行) | 情境×分層×三級建議 | v30 |
| 網路架構選型導覽 | `netarch_guide.py` (233行) | 技術族系→世代→產品 | v31 |
| 交換器選型導覽 | `switch_guide.py` (306行) | 情境×分類矩陣 | v32/v33 |
| 監控系統選型導覽 | `monitor_guide.py` (306行) | 情境×分類矩陣 | v39 |
| 門禁系統選型導覽 | `access_guide.py` (306行) | 情境×分類矩陣 | v40 |
| 閘道器/控制器選型導覽 | `gateway_guide.py` (306行) | 情境×分類矩陣 | v41 |
| 自動化系統選型導覽 | `automation_guide.py` (306行，**QUICK.md 舊版完全未記載**) | 情境×分類矩陣 | v65 |

各類編輯需對應 `*_guide_edit` 模組旗標或 superadmin；`selection-db-overview.html` 為六類（不含場域）品牌/產品數涵蓋度總覽（automation_guide 是否已納入需查證，本次盤點未逐一確認前端涵蓋度頁是否更新到七類）；雙機同步用 `backend/tools/check_guide_sync.py`。**這條產品線是 MOTRIX 相對於一般套裝 ERP 最獨特的資產**——是把公司多年技術選型 know-how 結構化成可查詢資料庫，見 §6.7。

### 2.13 組織架構 `org_structure.py` (243行，DB v48)
- 前端：`org-structure.html`
- 資料表：`divisions`、`departments`
- API：`/api/org/*`（`org_structure.py:40-228`）
- 重點：僅二層（處→部門），`manager_user_id` 目前已接入簽核流程動態解析（`helpers/tiered_approval.py:77-148 resolve_department_manager/resolve_division_manager`），QUICK.md §11 舊版寫「尚未接進簽核」已過時，實際上已完成。

### 2.14 人資 / 薪資 `payslips.py` (445行)
- 前端：`payslips.html`、`payslip-form.html`
- API：`/api/payslips/*`、`/api/tax-rules`（`payslips.py:127-431`）
- 重點：勞報單 PDF 存檔＋歷程 archive；含稅務規則 API。

### 2.15 每日工作事項 `daily_tasks.py` (1348行，routers 中第二大)
- 前端：`daily-tasks.html`
- 資料表：`daily_tasks`、`daily_task_completions`、`daily_task_edit_log`
- 重點：週期性任務（recurrence）、逾期檢查排程（`schedule_overdue_check()`）、簽核逾期催辦邏輯 `_check_approval_reminders()` 也掛在這個檔案裡（雖然邏輯上屬於簽核引擎，物理位置在此，查找時容易漏找）。

### 2.16 儀表板與營運報表 `dashboard.py` (1104行) + `reports.py` (3189行，全庫第二大)
- 前端：`index.html`（儀表板）、`reports.html`（唯一有外置 JS `reports.js` 支援）
- API：`/api/dashboard/*`（漏斗/活動feed/月支出/告警）、`/api/reports/*`（財務/AR帳齡/資金水位/稅務匯出/銀行對帳/客戶歷史/月趨勢）
- 重點：`reports.py` 是全系統業務邏輯密度最高的檔案之一（`_collect()`/`_compute_achievement()`/`monthly_trend()` 為核心），近期多輪金額同步稽核（稅額沖銷/精算快照過期/動態排序）都集中修在這裡，見 memory 記錄。**改這個檔案前務必先讀 memory 裡 2026-08-28 那幾輪稽核記錄**，很多「看起來像 bug」的地方已經查證過是正確設計。

### 2.17 系統設定 / 簽核設定 / 稽核 `system.py` (1001行) + `approval_delegates.py` (131行)
- 前端：`approval-settings.html`（2026-08-28 起單一頁涵蓋五種文件類型）、`audit-log.html`、`notification-settings.html`、`schema-status.html`、`company-profile-settings.html`、`google-calendar-settings.html`
- API：`/api/settings/*`、`/api/audit-log`、`/api/work-logs/*`、`/api/notifications/*`、`/api/approval-delegates/*`（DB v67，2026-08-28 新增，QUICK.md 舊版未記載）
- 重點：簽核代理人機制（委託人可自助設定，superadmin 可代設）；Schema 狀態頁純唯讀診斷；`/api/system/schema-status` 顯示目前/目標版本。

### 2.18 通用支援模組
| 模組 | 用途 |
|---|---|
| `uploads.py` (97行) | 簽名 URL 服務 `/api/uploads/{path}`、photo-token，全站附件下載共用出口 |
| `search.py` (75行) | `/api/search` 全域搜尋（跨客戶/供應商/報價單/業務開發案/料號） |
| `list_prefs.py` (64行，DB v56) | 使用者個人化清單偏好（欄位顯示/排序記憶） |
| `module_versions.py` (121行) | 版本紀錄頁資料來源，同步自 `version_manifest.json` |

---

## §3 · 橫向關注點（跨模組共用機制）

### 3.1 簽核引擎（五種文件類型共用）
`helpers/tiered_approval.py` (319行) 是全系統簽核邏輯的單一事實來源：`resolve_active_flow_setting()` 判斷該文件類型走統一還是獨立設定 → `setting_to_active_tiers()` 展開 tiers（含部門/處主管動態解析）→ `check_approve_permission()`/`check_reject_permission()`（v67 起支援代理人 `conn` 參數）→ `check_no_tier_self_approval()`。**任何簽核相關 bug，先查這個檔案，不要在各 router 裡各自為政地找**（歷史上這正是修復 memory 記錄裡好幾輪 bug 的教訓）。

### 3.2 Demo 隔離
`main.py:97` token 前綴判斷 → `contextvars` 切換 → 所有 `get_db()` 自動導向 `motrix_erp_demo.db`。三個直接寫實體檔案的例外（照片/PDF/勞報單存檔）各自手動檢查 `is_demo_mode()`。**新增任何寫磁碟功能務必檢查這一條**（QUICK.md §3.5 已記錄過踩坑）。

### 3.3 樂觀鎖
`_expectedUpdatedAt` 模式用於 5 個高併發端點（case-record/customers visits/suppliers visits/vendor-contractors visits/payment），409 statuscode，前端需回寫 `updated_at` 後重試。

### 3.4 備份與 DR
三層：即時 JSON（原子寫入）＋每日/週排程（Windows Task Scheduler 為主、`threading.Timer` 為輔）＋本機 SQLite 快照。雲端目標是 **G: 掛載的個人 Google Drive**——這正是 2026-08-24 那次「連續三週備份靜默失效」事故的根因（磁碟機代號漂移），見 §6.10。

### 3.5 部署（半自動 CI/CD 替代品）
`build_deploy_package.ps1`（開發機，強制 git clean + pytest 全過才出包）→ 人工搬移 → `apply_update.ps1`（正式機，db 快照＋migration 乾跑驗證＋安全停服＋健康檢查＋失敗自動回滾）。這套自製流程的成熟度**已經超過很多小型團隊手動部署的做法**，唯一缺口是兩機間傳輸仍是人工複製（§14.3 已列為已知限制）。

### 3.6 多分公司／自動更新（規劃中，`MULTI-BRANCH-AUTO-UPDATE-DESIGN.md`，未列入排程）
2026-08-31 定案方向：連線架構傾向**集中式 VPN**（優先於分散式多節點）；若真的要走分公司各自跑本機服務，更新套用**刻意不做無人值守自動化**（沿用 `apply_update.ps1` 但加一層排程窗口＋人工核准 canary 發佈），理由是健康檢查抓不到邏輯 bug、多站點同時套用壞版本的爆炸半徑遠大於單站。這個判斷是對的，見 §6.11。

---

## §4 · 資料庫演進索引（v1→v68，依主題分組）

| 版本區間 | 主題 |
|---|---|
| v1–v21 | 基礎建設：session/密碼/報價熱路徑欄位、客戶供應商舊資料遷移、樂觀鎖前身、login rate limit、daily_tasks 誕生與週期性任務、module_versions 雛型 |
| v22–v29 | 承攬商管理誕生：`vendor_contractors`/`contractor_dispatches`/稅率/存簿影本/軟刪除；`dev_crm`（業務開發 CRM） |
| v30–v41 | 六大類選型資料庫依序上線：env(v30)→netarch(v31)→switch(v32/33)→shipping_notes(v34，插隊)→module_versions去重(v35)→dispatch personnel(v36)→vendor optional(v37)→inventory(v38)→monitor(v39)→access(v40)→gateway(v41) |
| v42–v47 | 業務開發連結審核制(v42)、notification_prefs(v43)、dispatch invoice_no(v44)、承攬商匯款申請(v45)、發票開立簽核單(v46/v47) |
| v48–v56 | 組織架構 divisions/departments(v48/49)、project department(v50)、**案件階段正規化開始**：case_stages 表(v51)+修正(v52)、請款單(v53)、payment_request_stage(v57，插隊)、deal_won_at 回填(v58/59)、user_list_prefs(v56) |
| v57–v68 | 收尾與補洞：dispatch files(v60)、案件半解鎖(v61)、**專案併入案件管理**(v62)、work_log contact_type(v63)、network_plans(v64)、automation_guide(v65)、parts safety_stock(v66)、approval_delegates(v67)、dispatch payable date/invoice files(v68) |

**觀察**：migration 編號不完全按時間順序寫入（如 v57 payment_request_stage 出現在 v67 之後才被 grep 到的位置，代表開發時曾插入舊版號補漏），`db.py` 本身有一段歷史debt——版號分配不連續（實際文件內函式定義順序與版號大小不完全對應），這是純技術債，功能上因為每個 migration 是冪等且 `CURRENT_VERSION` 是唯一權威判斷依據，不影響正確性，但**未來若要重構 `db.py`，先別急著「排序整理」，這是特意保留的歷史軌跡，也是唯一的 schema 變更 audit trail**。

---

## §5 · 已知限制（來自 QUICK.md §11 + 本次盤點交叉核對）

| 優先 | 項目 | 現況 |
|---|---|---|
| 🔴 | 區網 HTTPS | ✅ 已完成（`https_setup.ps1`，2026-08-27），但 memory 記錄正式機**尚未實際執行 mkcert 產證＋重啟**這個手動步驟——即部署了工具但沒有真正啟用，這是文件與現實最容易混淆的一格，下次處理前先在正式機確認 `backend/certs/` 是否有內容 |
| 🟡 | caseRecord.stages 正規化 | 進行中（① ② ③a 已完成雙向同步），③b（前端真正改呼叫新端點，~18 個函式）風險最高、尚未做，是現存最大的一筆技術債 |
| 🟡 | 組織架構僅二層 | 使用者不能「只屬於處、不屬於任何部門」，如果之後有純處級主管無下轄部門的組織需求會卡住 |
| 🟡 | 已結案半解鎖範圍刻意收斂 | 13 個端點直接 403 不支援排隊；2026-08-28 已加 audit log 供之後用真實數據決定是否擴大 |
| 🟡 | 多分公司架構＋自動核版更新 | 規劃中未列入排程，見 `MULTI-BRANCH-AUTO-UPDATE-DESIGN.md`（2026-08-31）。4 項待決：集中式 vs 分散式連線架構、分公司對總部 API 認證方式、排程套用窗口是否可調、跨分公司資料彙總是否需要（若需要屬獨立大工程）。技術判斷本身已合理（見 §6.9），純粹尚未動工 |
| 🟡 | 災難復原（DR）從未實際演練過 | `DR-SOP.md` §6 演練紀錄表完全空白——備份機制本身做得不錯，但「整台機器硬體故障」情境下能否真的在估計時間內重建，從未驗證過，RTO 目前只是估計值 |
| 🟢 | PDF 存檔未納入雲端備份範圍 | 報價單/出貨單/勞報單 PDF 目前不在 `_mirror_uploads()` 涵蓋範圍內，`DR-SOP.md` §5 已列為待改進，可沿用同一套機制擴充 |
| 🟢 | CORS 白名單寫死 IP，未改用環境變數 | 換機器/換 IP 需要改 code 重新部署，`DR-SOP.md` §5 已列為待改進 |
| 🟢 | `routers/projects.py`（592行）疑似死碼 | 2026-08-26 專案管理併入案件管理後刻意保留檔案本體「當歷史/備用程式碼」，不再掛載於任何前端流程；文件自己標註「之後確認不需要可整個移除」，目前仍在，尚未清理 |
| 🟢 | 報表/儀表板部門篩選覆蓋不全 | activity-feed 目前只有「案件留言板」區塊套用部門篩選，其餘活動來源尚未涵蓋 |
| — | QUICK.md 文件落後程式碼 | 本次盤點發現的具體落差：§7 API 清單缺 cashier/case_action_items/list_prefs/uploads/network_plans/approval_delegates/automation_guide/org_structure 共 8 個 router 的完整記載（部分僅存在於 memory 而非 QUICK.md 正文）；§13 目錄結構仍寫 "42 個 migrations"（實際 68）；文件版本標記 2026-08-20（實際程式碼到 2026-09-01）。**§11 表格本身也有已過時卻未更新的標記（如 HTTPS 那筆）**——下次要依 §11 判斷前，先查 `git log --oneline -5 -- <相關檔案>` 再下結論，不要只信文件 |
| 🟢 | 無自動化 CI（GitHub Actions 等） | 純本機 `pytest` + 打包前置檢查，單人開發下夠用，多人協作時會是缺口 |
| 🟢 | 無 MFA | 全站無二階段驗證，含 superadmin |
| 🟢 | 備份雲端目標為消費級 Google Drive（磁碟機代號掛載） | 已發生過三週靜默失效事故，見 §6.4／§6.10 |

---

## §6 · 依專業軟體慣例的建議（分模組）

> 原則：**不建議推翻重做已經運作良好的部分**——MOTRIX 的簽核引擎、案件狀態機、Demo 隔離、部署安全閘門，這些設計已經達到、甚至超過很多中小企業採購套裝軟體的實作品質。以下建議聚焦在「專業軟體通常會有、MOTRIX 目前沒有或較弱」的具體缺口，並標明優先序。

### 6.1【高】財務憑證流：不要自建複式記帳，改做單向匯出　**✅ 2026-09-01 第一階段已實作**
`invoice_vouchers`/`payment_requests`/`contractor_payment_vouchers`/`cashier.py` 這一組已經是相當完整的「應收/應付準憑證流」，但終究不是複式記帳（沒有借貸科目、沒有總分類帳）。**專業做法（如多數 CRM/ERP 週邊系統對接 QuickBooks/Xero/鼎新/正航的模式）是不要在 MOTRIX 內重造會計系統**，而是：
- 已有的 `tax-export`（銷項發票 Excel）、`bank-reconcile`（CSV 寬鬆比對）已經是正確方向的第一步
- 下一步建議做**定期批次匯出成目標會計系統可匯入的格式**（多數會計軟體支援 CSV/Excel 匯入傳票），而非投入資源做即時 API 對接或自建總帳——這個規模的公司請會計師事務所處理報稅，會計師慣用的工具（鼎新/正航/自己的 Excel 範本）才是終點，MOTRIX 角色應該停在「產生乾淨、可核對的原始憑證資料」

**實作進度**：使用者確認目標是鼎新 T100，且明確選擇「先做批次匯出、不做 API 對接」（T100 API 需要貴公司自行申請存取權限，沒有真實憑證無法測試）。已完成：`accounting_export.py`（現金基礎傳票匯出，見 §2.7）＋已匯入確認追蹤（`t100_export_confirmations`，DB v69）＋料件/設備進貨付款狀態追蹤與納入匯出（`stock_batches`，DB v70），三類事件來源皆已涵蓋。科目代號留白待財務填入。**尚未做**：①科目代號實際填入（需財務/鼎新顧問提供）②若之後升級 API 即時推送，需先取得 T100 API 存取權限③既有進貨批次的付款狀態全部預設「未知/未付款」，財務需回頭逐批確認歷史資料④請款單/客戶供應商主檔等仍非涵蓋範圍（非金流事件或屬主檔同步，性質不同）。

### 6.2【高】MFA 與敏感操作二次驗證
superadmin 目前是「密碼 + Bearer token in localStorage」單一因子。專業做法（比照 Okta/Google Workspace 對管理員帳號的要求）：至少對 superadmin 角色加 TOTP（`pyotp` 套件，不需要外部服務）。這比 2 小時閒置逾時（已做，見 §3）更能防範憑證外洩情境，是相對低成本、高投資報酬的一項。

### 6.3【中】Session 安全：Bearer-in-localStorage → 考慮 httpOnly Cookie
目前 XSS 防護靠「全站禁止 innerHTML 插入動態內容」的紀律（DOM API only），這個紀律本身做得不錯，但屬於「靠自律」而非架構性防護。專業 Web 應用（銀行/SaaS 常見模式）用 httpOnly + Secure + SameSite cookie 存 session，即使真的出現 XSS 漏洞也偷不到 token。**這是架構級改動，不建議現在動**（牽動全站 API 呼叫方式），但若之後要做外網暴露（例如業務出差用手機連線），這個改動的優先序會大幅提升。

### 6.4【中】備份目標：消費級 Google Drive → 專業物件儲存
G: 磁碟機掛載模式已經證實脆弱（磁碟機代號漂移事故）。專業 3-2-1 備份的「異地」那一份，建議改用 **Backblaze B2 / AWS S3 / 或至少 Google Workspace 服務帳號＋Shared Drive**（不透過磁碟機掛載，直接用 API 上傳），可以用既有的 `archive.py` 上傳邏輯改接 `boto3`/`google-cloud-storage` SDK，不必等磁碟機掛載，也不受個人帳號容量/權限影響。這比繼續加固「偵測掛載失敗」的告警邏輯更能根治問題。

### 6.5【中】專案時程視覺化：目前是清單/看板，缺真正的甘特圖
`case-stage-board.html` 已有跨案時間軸與看板五欄，但沒有依賴關係的視覺化甘特圖（`depends-on` 目前只是資料關聯，沒有畫成箭頭）。若要往這個方向做，**不建議重造甘特圖渲染引擎**，可评估輕量嵌入（如 `frappe-gantt`，MIT License、零依賴、可直接吃現有 `case_stages` 資料）。優先序中等——目前的看板+時間軸已經涵蓋多數日常需求，甘特圖是「更好」而非「缺」。

### 6.6【中】庫存管理：已有安全庫存燈號，缺自動採購建議
`parts.safety_stock`（v66）已經做到「低於安全庫存」篩選，專業進銷存軟體（Zoho Inventory/inFlow）下一步通常是「自動生成採購建議清單」（依安全庫存缺口 + 供應商前置時間），目前 MOTRIX 的 `procurement.html` 是否已有這個邏輯本次未深入盤點，若沒有，這是一個中優先、資料已齊備、開發成本不高的功能。

### 6.7【低，但價值高】選型資料庫：這是差異化資產，值得往外延伸
七大類選型導覽（§2.12）是市面上少見的「把公司多年產品選型知識結構化」的做法，多數同業還停留在 Excel 或 PDF 型錄。這部分**不需要參考專業軟體**，因為這本身已經接近專業水準（比照 Cisco/Ubiquiti 官方配置器的資料形狀）。建議方向反而是**往外延伸應用場景**：
- 業務出差時的行動裝置友善檢視（目前 Alpine.js 純桌面設計，未評估 RWD 適配程度）
- 未來可能的「客戶自助配置器」——把選型邏輯包裝成客戶能自己操作的報價試算工具，這會是真正的商業差異化，但屬於長期規劃，非近期建議

### 6.8【低】CI/CD：目前是單人手動流程，暫不需要動
`apply_update.ps1`/`build_deploy_package.ps1` 這套已經包含專業 CI/CD 的核心要素（測試閘門、乾跑驗證、自動回滾）。**不建議現在導入 GitHub Actions 等外部 CI**——單人開發、正式機在內網無法被外部 CI runner 直接觸達，導入會增加維運負擔而非降低。若未來團隊擴編到 2 人以上同時提交程式碼，才是重新評估的時機點。

### 6.9【觀察】多分公司規劃方向正確，維持現有判斷即可
`MULTI-BRANCH-AUTO-UPDATE-DESIGN.md` 裡「不做無人值守自動套用」「集中式優先於分散式」這兩個決策，跟企業軟體業界對多站點部署的標準做法一致（比照 SaaS 廠商的 canary release + 人工核准 gate）。**這份規劃書的技術判斷已經是對的，不需要外部建議修正**，唯一要提醒的是文件本身已註明「動工前重新確認是否仍走純集中式」，若後續真的啟動，先回頭確認這個前提還成立。

### 6.10【低】文件维护：QUICK.md 與程式碼的落差需要一次性同步
本次盤點發現的 8 個未完整記載的 router（§5 已列）建議找一個時間點把 QUICK.md §2/§7/§13 更新到 v68 現況，避免下次新對話又要重新盤點。這不是「專業軟體建議」而是專案自身維護規則（QUICK.md 文件本身就寫了「每次修改必讀」章節），純粹是落實既有規則。

---

## §7 · 快速查找索引（常見問題 → 檔案位置）

| 我要找… | 去哪裡 |
|---|---|
| 報價單狀態機/簽核送出/退回 | `quotations.py:938-1238`（送出/狀態）、`:2815-3306`（approve/reject/佇列） |
| 案件精算 settlement | `quotations.py:2670-2815` |
| 案件記錄整包存檔（樂觀鎖） | `quotations.py:1480-1720` |
| 案件階段 CRUD（新表） | `quotations.py:1982-2259`，db.py `_m051_case_stages_normalize` |
| 已結案半解鎖 | `quotations.py:1410-1480`，db.py `_m061_case_semi_unlock`（docstring 有完整設計說明） |
| 簽核 tiers 展開/權限檢查 | `helpers/tiered_approval.py`（五種文件類型共用，唯一事實來源） |
| 承攬商派發狀態機 | `vendor_contractors.py:703-748` |
| 財務三憑證（匯款/發票/請款） | `contractor_vouchers.py` / `invoice_vouchers.py` / `payment_requests.py`，架構完全平行 |
| 出納彙總視圖 | `cashier.py`（唯讀彙總，不是資料源） |
| 營運報表核心邏輯 | `reports.py::_collect()`/`_compute_achievement()`/`monthly_trend()`（**先查 memory 近期稽核記錄再動手**） |
| Demo 隔離判斷 | `helpers/startup.py`/`db.py set_demo_mode`，`main.py:97` |
| 閒置逾時/session 中介層 | `main.py:76-159` |
| 備份邏輯 | `archive.py`（原子寫入）、`backup_job.py`（獨立排程腳本） |
| DB migration 歷史 | `db.py:576-2859`（`_mNNN_xxx` 函式），版本常數 `db.py:81` |
| 部署套用流程 | `backend/tools/apply_update.ps1`（正式機）、`build_deploy_package.ps1`（開發機） |
| 選型資料庫（六/七大類） | `routers/{env,netarch,switch,monitor,access,gateway,automation}_guide.py`，皆同一套 CRUD 樣板 |
| 通知 Email 樣板 | `helpers/email_notify.py`（1367行，全庫最大 helper，逐事件各一函式） |
| 簽核逾期催辦 | `daily_tasks.py::_check_approval_reminders()`（邏輯屬簽核但物理位置在此，易漏找） |

---

## §8 · 踩坑教訓索引（長期參考，非流水帳）

> 篩選自 QUICK.md §12 逐日 changelog 中真正有「下次還會用到」價值的教訓，依主題分組，非按時間排列。

**部署與基礎設施**

1. **PowerShell `.ps1` 含中文註解務必存 UTF-8 BOM**：Windows PowerShell 5.1 沒有 BOM 會 fallback 系統非 Unicode 編碼（此機器是 Shift-JIS），曾讓「只能在正式機執行」的身分守門判斷式本身解析錯亂、`exit 1` 沒真的執行到——這是會讓**安全機制本身失效**的隱性風險，不是亂碼美觀問題。`.bat` 檔則反過來要求存 **CRLF**（LF-only 會讓 cmd.exe 批次解析器直接報語法錯誤且不留任何 log）。
2. **Migration 部署要「先在副本乾跑，失敗才中止」**：`apply_update.ps1` 把新版 migration 先複製一份到 temp 目錄跑過一次，失敗直接中止、正式庫全程不受觸碰，避免正式庫變成第一個試跑新 migration 的地方。
3. **健康檢查判斷「失敗」前要先排除自癒重試的雜訊**：停服後若沒等 port 真正釋放，crash-restart 迴圈會搶著重啟並自行重試成功；健康檢查邏輯需要「只看最後一次成功啟動之後」的 log，否則會把已自癒的暫時性錯誤誤判成更新失敗、觸發不必要的自動回滾。
4. **磁碟機代號不能寫死**：Google 雲端硬碟掛載代號會漂移（G:↔H: 曾在同一天內反向漂移兩次），寫死路徑導致備份靜默失敗長達三週沒人發現；已修正為每次呼叫時動態掃描 A-Z 尋找目標資料夾（30 秒快取）。這正是 §6.4 建議改用物件儲存的根因事故。

**資料與同步一致性**

5. **`(module, version)` 缺 UNIQUE 限制會讓表無限增生**：DB v35 之前 `module_versions` 表用 `INSERT OR IGNORE` 卻沒有唯一鍵限制，導致每次伺服器重啟都整份 manifest 重複插入一次，正式機曾實測膨脹到 626,725 列（僅 143 種真實組合），佔掉每日備份 300+MB 的絕大部分。
6. **選型資料庫「內容」跟「程式碼」是兩條不同步的軌道**：既有類別（如交換器選型導覽）透過 API/管理後台新增的內容只存在單機 db 檔案，不會隨 `build_deploy_package.ps1`/`apply_update.ps1` 的程式碼部署自動同步到另一台機器；只有全新類別的「第一批」種子資料（包在 migration/seed.py）會隨部署自動灌入。雙機比對用 `backend/tools/check_guide_sync.py`。
7. **同步腳本的查重鍵必須跟來源腳本邏輯完全一致，不能想當然爾加嚴**：曾把 `(brand, model)` 兩欄查重誤改成 `(category_code, brand, model)` 三欄，導致誤判「不存在」而重複插入 2 筆規格空白列。
8. **文件裡的「已知限制」表格會過時而不自知**：見上方 §5 最後一條，任何要依文件標記做判斷的場景，先查 `git log` 再下結論。

**前端 Alpine.js / UI**

9. **Chart.js 實例不能放進 Alpine 的 reactive `x-data`**：Alpine 會把整個物件樹遞迴包成 reactive Proxy，Chart.js 內部大量 getter/循環參照被包住後會直接 `RangeError: Maximum call stack size exceeded`；同一頁面若同一張圖表短時間內被建立兩次（先用退回資料畫、真實資料抓到再重建），前一次未畫完的 `requestAnimationFrame` 動畫對已清空的 canvas 繼續畫會噴錯——全域關閉 `Chart.defaults.animation` 可排除這類「跨影格未完成繪製」的 race。
10. **`scrollIntoView` 太早觸發會被非同步 UI 注入打斷**：`sidebar.js`/`notif.js` 非同步注入 topbar/sidebar 造成版面重排，若頁面載入 80ms 內就捲動會被沖回原點——解法是延後到 250ms 並在 800ms 補一次保險捲動。
11. **甘特圖類渲染避免「畫完 SVG 再回頭用 DOM 手術修正座標」**：跨案時間軸最終改成「畫之前就先把位置/寬度/層數全部算好」的純資料驅動方案，額外好處是可以完全脫離瀏覽器、直接在 Node.js 用真實資料跑座標數學驗證有無重疊。

**測試與工具**

12. **`from module import CONST` 會繞過測試環境的 monkeypatch**：`conftest.py` 只 patch 模組本身的屬性（如 `helpers.uploads.UPLOADS_ROOT`），若別的模組用 `from helpers.uploads import UPLOADS_ROOT` 把值「by value」import 進自己的命名空間，測試時會意外寫進本機真實目錄而非隔離的 tmp_path。正確做法是 `import module`，所有存取都走 `module.CONST` 即時查找。
13. **本機 Ollama 推理模型（qwen3.6/deepseek-r1 等）呼叫 `/api/generate` 要加 `"think": false`**：否則內容會被塞進獨立的 `thinking` 欄位、`response` 留空，容易誤判成「模型沒輸出任何東西」；程式邏輯應該 `response` 優先，空的話 fallback 讀 `thinking`。
14. **process-global 狀態（rate-limit 字典等）也要在 `conftest.py` 裡重置，不是只有 DB/檔案路徑才算隔離**（2026-09-01 發現）：`reports.py::_check_export_rate()` 用模組級 `_export_times` dict 以 `(user_id, fmt)` 為 key 做匯出冷卻，`client` fixture 每個測試都建全新空 DB（`user_id` 從 1 重新編號），但這個 dict 本身跨測試從未重置——兩個各自獨立、彼此不相關的測試只要剛好都建立了「第 N 位使用者」又都呼叫同一個匯出端點、且真實時間差在冷卻窗口內，就會讓後一個測試莫名其妙 429。只在單一測試檔案跑測試時完全重現不出來，只有跑全套 `pytest tests/` 才會間歇性出現，容易誤判成「不穩定的測試」。修法：`conftest.py` 的 `client` fixture 用 `monkeypatch.setattr(reports_module, "_export_times", {})` 比照既有的 `UPLOADS_ROOT` 隔離模式一併重置。**Why：** 之後新增任何「模組級可變狀態」（尤其是這種 dict/計數器/lock），只要沒有隨 `client` fixture 重置，都可能是下一個間歇性、只在全套測試才浮現的 flaky 測試來源，不要等它發作才想到查。
