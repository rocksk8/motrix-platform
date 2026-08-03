# MOTRIX ERP — 變更記錄

> 允碩整合集創股份有限公司  
> 按版本倒序排列。開發速查請見 `MOTRIX-ERP-QUICK.md`。

---

### 2026-08-03c — 案件管理介面優化（5 項）

**緣起**：針對案件管理介面提出的 5 點建議，使用者確認後依序落實。

- `frontend/pages/case-management.html`：執行進度／叫料管控／設備登錄／保固備注 四個一級分頁合併為
  「執行管理」+ 二層子分頁（沿用既有但從未使用的 `.cm-subtabs` CSS），一級分頁 9→6 個；`.cm-tabs`/
  `.cm-subtabs` 補上手機版橫向捲動；拿掉與叫料管控分頁重複的「叫料到料」KPI；卡片新增「負責業務」欄位
- `backend/routers/quotations.py` 新增 `POST /api/quotations/case-activity`：彙整 `case_updates`/
  `work_logs`/`daily_task_completions` 三個不會觸發 `quotations.updated_at` 的動態來源，供案件卡片顯示
  「有新動態」未讀提示；`frontend/js/case-management.js` 比照業務開發 CRM 的「未讀游標＋一鍵已讀」設計
- 實測時發現並修正一個 bug：任務 1 一開始誤改到 `case-management.html` 裡的死碼 `__noop_stub()`（見
  2026-08-02c 條目警告），真正邏輯在 `frontend/js/case-management.js`；已修正並重新驗證
- 無 DB migration

### 2026-08-03b — 業務開發 CRM 新增一鍵已讀／只看未讀篩選

**緣起**：使用者反映業務開發模組「有更新」提示會不斷累積、清不完。追查後發現舊機制的已讀基準
是「上一次頁面載入的時間點」而非「離開時間點」，自己剛編輯的案件下次造訪仍會被判定為未讀，且
該提示原本只有 admin+ 看得到。

- `frontend/pages/dev-crm.html`：已讀基準改為模組專屬的 `localStorage` 游標，只能靠手動點擊
  「一鍵已讀」位移；開放給所有可用本模組的角色；新增「只看未讀」篩選與未讀彙總列；卡片欄寬
  300px→340px，新增業務開發／專案規劃人員姓名顯示
- 實測時發現並修正一個 bug：未讀判斷原本用字串比較時間戳，因後端格式（空格分隔）與
  `toISOString()`（`T` 分隔）在 ASCII 排序下不一致，導致同一天的更新恆判定為「未大於」而永遠不會
  顯示未讀；已改用正規化後的 `Date` 物件比較
- 未改動 `sidebar.js`/`notif.js`，其他模組共用的 sidebar 數字徽章機制不受影響
- 已用 demo 帳號實機驗證：未讀標示／一鍵已讀／只看未讀篩選／持久化皆正常運作

### 2026-07-30c — 場域選型導覽新增「簡易／進階」瀏覽切換

**緣起**：網路架構選型導覽上線後，使用者反應場域選型導覽原本的矩陣＋五組篩選＋搜尋太複雜，
希望比照網路架構選型導覽的「先選方塊、再看卡片」介面。討論後決定：不拿掉原本的進階瀏覽
（跨場域比較、風險/品牌篩選仍有價值），改成**新增一個可切換的簡易模式，兩種並存**。

- `frontend/pages/env-guide.html`：
  - 新增 `browseMode`（'simple'｜'advanced'）狀態，`.envg-hd` 新增「簡易／進階」分頁切換，預設 `simple`
  - 簡易模式：場域方塊（依大類分組：一般物流場/冷鏈/戶外/化工石化/延伸/通用）→ 點選後橫向顯示該場域所有分層的建議卡片（入門/建議/高端＋業界慣例＋特別注意＋產品連結＋缺口/關鍵/需外箱 badge），資料直接複用既有 `envRows`/`recRows`/`linkRows`（Alpine reactive），不碰資料庫、不碰原本的 vanilla JS 渲染邏輯
  - 進階模式：原本的矩陣／卡片／表格／搜尋／五組篩選／縮放／深淺色切換，原封不動保留
  - 簡易模式的卡片樣式與配色直接沿用網路架構選型導覽的 `.fam-tile`/`.gen-card`/`.tag-pill` 等 class（MOTRIX 系統配色，不受 ◐ 深色切換影響，因為這些 class 不在 `.envg` 命名空間內）

### 2026-07-30b — 新增「網路架構選型導覽」（選型資料庫第二類別）

**緣起**：場域選型導覽上線後，確立 ERP 要逐步擴充成涵蓋多產品線的「選型資料庫」（無人載具／
網路架構／監控／門禁／自動化系統…）。網路架構是第二個上線的類別，用來驗證：不同類別的內容
形狀可以差很多，不必硬塞進同一張表——這類是「技術族系→世代演進→產品」（如 Wi-Fi 6→6E→7、
4G→5G→5G mmWave），而非場域選型導覽的「情境×分層×三級」。

**後端（DB v30 → v31）**
- `backend/db.py`：新增 `_m031_netarch_guide` migration，建立 `netarch_families` / `netarch_generations`（FK family_code）/ `netarch_products`（FK generation_id）三表
- `backend/netarch_guide_seed.py`（新檔）：第一批資料——Wi-Fi（6/6E/7）、行動網路（4G LTE/5G Sub-6/5G mmWave），以 UniFi／Omada／Peplink／Netgear 實際產品驗證欄位設計
- `backend/routers/netarch_guide.py`（新檔）：`/api/netarch-guide/{families,generations,products}` CRUD，讀取任何登入者皆可，寫入需 superadmin 或 `netarch_guide_edit` 模組
- `backend/main.py`：掛載 `netarch_guide.router`

**前端**
- `frontend/pages/netarch-guide.html`（新檔）：瀏覽模式改用**先選族系方塊、再看世代橫向對照卡片**的簡化互動（不是場域選型導覽那套矩陣/篩選/搜尋），每張世代卡片含核心規格、比上一代進步、典型情境＋標籤、建議售價區間、依賴/相關備註、注意事項、對應產品；從一開始就用 MOTRIX 系統淺色配色（`--accent`/`--text-*`/`--border-light`），不再像場域選型導覽先做深色再改
- `frontend/static/sidebar.js`：新增 `cNetG` 模組旗標、`netg` 圖示、「業務」區塊新增「網路架構選型導覽」nav 項目
- `frontend/pages/users.html`：`allModules` 新增 `netarch_guide`（檢視）／`netarch_guide_edit`（新增修改刪除）

**文件**
- 新增根目錄 `SELECTION-DB-INDEX.md`（選型資料庫總索引：分類邏輯、類別清單、提需求格式）與 `NETARCH-GUIDE-CONTENT.md`（本類別內容維運手冊）

### 2026-07-30a — 新增「場域選型導覽」模組（原單機工具整合進 ERP）

**緣起**：`場域選型導覽.html` 原為 Claude Desktop 本機代理模式產出的獨立參考工具（無人自動化載具 30 個部署場域 × 分層三級設備建議，Sbjlink／Teltonika／iEi／Southco 原廠規格），資料寫死在 JS 陣列裡。今日整合進 MOTRIX ERP，資料庫化並開放後台編輯。

**後端（DB v29 → v30）**
- `backend/db.py`：新增 `_m030_env_guide` migration，建立 `env_guide_environments` / `env_guide_recommendations`（FK env_code, ON DELETE CASCADE）/ `env_guide_links` 三表；種子資料只在表為空時寫入一次（不覆蓋後續編輯）
- `backend/env_guide_seed.py`（新檔）：原工具的 30 筆場域／80 筆建議／44 筆連結，轉存為 JSON 字串常數供 migration 解析
- `backend/routers/env_guide.py`（新檔）：`/api/env-guide/{environments,recommendations,links}` 讀寫 CRUD；讀取任何登入者皆可，寫入需 superadmin 或 `env_guide_edit` 模組（沿用 `parts.py`／`contractors.py` 慣例，`_require_user`/`_audit`）
- `backend/main.py`：掛載 `env_guide.router`

**前端**
- `frontend/pages/env-guide.html`（新檔）：瀏覽模式完整保留原工具的搜尋／篩選／矩陣／卡片／表格／抽屜互動（vanilla JS 原樣搬遷，只把寫死陣列改成 `fetch()` API 資料），套上 MOTRIX topbar/sidebar 殼；新增「管理」模式做場域/建議/連結的新增修改刪除（Alpine + modal）
- 配色：`.envg` CSS 變數改對應 MOTRIX 系統色票（`--accent`/`--text-*`/`--border-light`/`--font-zh` 等），預設（`data-th="light"`）＝系統配色，原本的深色調保留為 `data-th="dark"` 備用切換（點 ◐ 圖示）
- **Excel 匯出／匯入**：僅 superadmin 可見（`session.role==='superadmin'`），3 個工作表（環境/建議/連結），匯入以代碼／ID 比對更新或新增，沿用單筆 CRUD API（做法比照 `customers.html`）
- `frontend/static/sidebar.js`：新增 `cEnvG` 模組旗標、`envg` 圖示、「業務」區塊新增「場域選型導覽」nav 項目（無 badge）、`_FILE_MODULE` 對應
- `frontend/pages/users.html`：`allModules` 新增 `env_guide`（檢視）／`env_guide_edit`（新增修改刪除，含 Excel 匯出入前提）二選項；`ROLE_MODULES.admin`／`.superadmin` 預設含 `env_guide`

### 2026-07-28a — 系統字體全面改為 LINE Seed TW_OTF（自架字型）

**字型自架（`frontend/fonts/`，新增目錄）**
- 複製 4 個字重的 OTF：`LINESeedTW-Thin.otf` / `-Regular.otf` / `-Bold.otf` / `-ExtraBold.otf`
- 由 `backend/main.py` 既有 `StaticFiles(FRONTEND_DIR)` 掛載自動於 `/fonts/*.otf` 提供，區網各台電腦免個別安裝字型即可看到一致外觀

**`frontend/css/style.css`**
- 新增 4 組 `@font-face`（`font-family: 'LINE Seed TW_OTF'`，`font-weight` 依 Thin 100-300 / Regular 400 / Bold 500-700 / ExtraBold 800-900 對應）
- `--font-en` / `--font-zh` 統一改為 `'LINE Seed TW_OTF', system-ui, sans-serif`（原分別為 Google Fonts CDN 的 `Inter` 與 `'Noto Sans TC', 'Inter'`）

**全站頁面／腳本（34 個 `.html` + `js/*.js` + `static/*.js`）**
- 移除所有頁面 `<head>` 內的 Google Fonts `<link>`（`fonts.googleapis.com` / `fonts.gstatic.com`，涵蓋 Inter / Noto Sans TC / Noto Serif TC）
- 所有內嵌 `font-family: Inter, sans-serif`（及各種空白/引號變體）、`'Noto Sans TC', sans-serif`、`'Noto Serif TC', serif` 統一替換為 `LINE Seed TW_OTF`（含 `quotation-form.html` 報價單 PDF 匯出樣式）
- Chart.js 全域字型設定（`index.html` / `js/reports.js` 的 `Chart.defaults.font.family`）同步更新

**批次取代衍生的字串斷裂修正**
- 以正則批次取代 `Inter,sans-serif` 時，凡原本落在**單引號分隔的 JS 字串**內（`static/sidebar.js` 8 處、`static/notif.js`、`index.html`、`pages/sales-orders.html`、`pages/quotation-form.html` 的 `style.cssText = '...'` 與 Alpine `:style="'...'"` 動態綁定），取代字串本身帶的單引號會提前把 JS 字串截斷、造成語法錯誤
- 修正方式：CSS 允許多字詞 `font-family` 值不加引號（`font-family:LINE Seed TW_OTF, sans-serif` 等價於加引號寫法），故在會截斷字串的位置一律改用不加引號形式
- 驗證：4 個獨立 `.js` 檔以 `node --check` 全數通過；全站所有 `.html` 內嵌 `<script>` 區塊以 `new Function()` 逐一語法解析，全數通過；`curl` 確認 `/fonts/LINESeedTW-Regular.otf` 回應 200（5.2MB）

### 2026-07-21g — 品質掃尾批次（Quality Sweep）

**L2 — SortableJS item key 碰撞修復（`frontend/pages/quotation-form.html`）**
- `addItem()` / `addHeader()` 的 `const id = Date.now()` → `crypto.randomUUID()`
- 複製模板路徑：`id: Date.now() + Math.random()` → `id: crypto.randomUUID()`
- API 載入後補 normalize：`this.q.items.forEach(it => { if (!it.id) it.id = crypto.randomUUID() })`（向後相容無 id 的舊報價單）

**L3 — pytest 覆蓋率擴充（`backend/tests/test_core.py`）**
- 新增 4 個測試類別，共 48 tests（原 25）
  - `TestStepsToTiers`（6 cases）：空陣列 / 單步驟 / 順序 / displayName fallback / userId default / 不保留 status
  - `TestActiveTiers`（5 cases）：空 / modern tiers passthrough / 舊 steps backward-compat / 預設 pending / tiers 優先於 steps
  - `TestCurrentTierIdx`（4 cases）：currentTier / currentStep / 預設 0 / 優先順序
  - `TestPasswordHelpers`（8 cases）：PBKDF2 hash+verify / 錯誤密碼 / 不同 salt / 舊 SHA256 相容 / 弱密碼策略

**確認已施作（無需動作）**
- L1：`notif.js:68` 鈴鐺 unread badge 已排除 `type==='approval_request'`，sidebar 角標與通知鈴鐺互不干擾
- E2：Login 速率限制（5 fails → 15 min lockout）在 `routers/auth.py` 已完整實作，含 DB 持久化
- E3：Session 清理（`_cleanup_sessions()`）在啟動時執行，已在 `helpers/startup.py` 實作

---

### 2026-07-21f — 可靠性強化批次（Reliability Patch Batch）

**H3 — 備份失敗 Email 告警（`archive.py`）**
- 新增 `_send_backup_error_email(reason, ts)` 函式
- `_write_backup_alert()` 在 `level=="ERROR"` 且同日尚未發送時呼叫之
- 收件者：`helpers.email_notify._admin_emails()`（所有 admin/superadmin 的 email）
- 發送方式：`_async_send()`（非同步，不阻塞備份流程）；若 Email 未啟用或無收件人則靜默跳過

**H4 — 匯出端點速率限制（`routers/reports.py`）**
- 新增模組級 `_export_times: dict`、`_export_lock: threading.Lock`、常數 `_EXPORT_COOLDOWN = 60`
- 新增 `_check_export_rate(user_id)` — 60 秒冷卻，違反回傳 HTTP 429
- `GET /api/reports/financial/excel` 和 `GET /api/reports/financial/pdf` 均在 auth 後立即呼叫

**M1 — steps→tiers 共用函式（`helpers/quotations.py` + 兩處呼叫端）**
- 新增 `_steps_to_tiers(steps: list) -> list`（無 status 欄位，純格式轉換）
- `helpers/__init__.py` re-export 新函式
- `routers/system.py._normalize_flow()` 改呼叫 `_steps_to_tiers()` 取代原本 inline comprehension
- `routers/quotations._setting_to_active_tiers()` 改呼叫 `_steps_to_tiers()` 取代原本 `[{"order": i, "approvers": [s]}]`
- `_active_tiers()` 維持獨立（需保留 status/approvedAt，不共用）

**M3 — pytest 單元測試（`backend/tests/test_core.py`）**
- 新增 `backend/pytest.ini`（`pythonpath = .`、`testpaths = tests`）
- 新增 `backend/tests/__init__.py`（空白，標記 package）
- 新增 `backend/tests/test_core.py`：25 個測試全部通過（1.31s）
  - `TestParsePeriod`（9 cases）：年度 / 月份 / 季度 / 閏年解析
  - `TestComputeAchievement`（6 cases）：空目標 / 年份不符 / 單案件 / 業務員分解 / 收款率 / 年份過濾
  - `TestCalc`（10 cases）：扣繳稅率 / 二代健保 / 外籍低薪率 / 有工會免補充費

---

### 2026-07-21e — 安全修補批次（Security Patch Batch）

**1. CSP Header（`main.py`）**
- `security_headers` middleware 新增 `Content-Security-Policy` 標頭（常數 `_CSP`）
- script-src 允許 `unsafe-inline`/`unsafe-eval`（Alpine.js 需求）+ `cdn.jsdelivr.net`；object-src `none`；frame-ancestors `self`

**2. Session Idle Timeout 8h（`main.py` + `db.py` + `routers/auth.py`）**
- DB migration v17：sessions 表新增 `last_active TEXT`
- 登入時（`auth.py`）INSERT 帶 `last_active = now`
- `auth_middleware`：若 `last_active` 已設且閒置 > 8h → 刪除 session + 401（`detail: "閒置超過 8 小時，請重新登入"`）
- 閒置 > 5 分鐘才更新 `last_active`（限制 DB 寫頻率）；首次請求（`last_active IS NULL`）直接 stamp 不拒絕

**3. `_PHOTO_SECRET` 持久化（`routers/projects.py`）**
- 原 `_PHOTO_SECRET = secrets.token_bytes(32)` 改為 `_get_photo_secret()` 函式
- 讀 `system_settings.photo_secret`；不存在時生成 32-byte hex 並儲存；以 `_PHOTO_SECRET_CACHE` 模組快取

**4. `PUT /api/settings/operating-targets` Pydantic Schema（`routers/system.py`）**
- 新增 `OperatingTargetsBody` / `_AnnualTarget` / `_SalespersonTarget` Pydantic 模型
- 替換 `body: dict = Body(...)` → 強型別驗證；同時寫入 audit_log（操作人、年度）

**5. HTML 逸出 in PDF 報表（`routers/reports.py:_build_report_html()`）**
- 函式內新增 `esc()` wrapper（`html.escape(str(v))`）
- 所有 period items / outstanding / case / sales / warranty / achievement 行的使用者資料欄位均套用 `esc()`

**6. AR 帳齡端點（`routers/reports.py`）**
- 新增 `GET /api/reports/ar-aging`（admin+ 權限）
- 返回：`{ asOf, note, bands:[{label, key, count, amount, items:[]}], total:{count,amount} }`
- 帳齡以案件報價日為基準分四區間；不含已收款項目

---

### 2026-07-21d — 財務報表：圖表分析 Tab

**新增 CDN（`reports.html`）**
- `<script src="https://cdn.jsdelivr.net/npm/chart.js@4">` 置於 `reports.js` 之前

**新增 Tab「圖表分析」（`reports.html`）**
- Tab 按鈕加於「目標達成率」之後；面板以 `x-show` 渲染（canvas 始終在 DOM，不影響 `x-ref` 解析）
- CSS 新增 `.chart-2col`（2:1 雙欄格線）、`.chart-card`（白底圓角卡）、`.chart-card__title`；RWD ≤800px 自動退為單欄

**`reports.js` 圖表方法**
- `_charts: {}`：chart 實例倉，供 destroy/resize 生命週期管理
- `initCharts()`：銷毀舊實例 → 設定全域字型（Inter/Noto Sans TC）→ 依序呼叫 5 個 `_build*Chart()`
- `_buildTrendChart()`：近 12 月成案趨勢，混合圖（Bar 件數左軸 + Line 合約金額右軸）；資料從 `casesAll.quoteDate` 分月聚合
- `_buildStatusChart()`：案件狀態分佈（Doughnut 65% cutout）；進行中（#F59E0B）vs 已結案（#6B7280）
- `_buildSalesPerfChart()`：業務員績效比較（Horizontal Grouped Bar）；合約總額 vs 已收款；最多顯示 8 人；高度依人數自動計算（max 180, count×52）
- `_buildTargetChart()`：年度目標達成率（Horizontal Bar + 紅虛線 100% 參考線）；6 指標色碼同 KPI Tab（綠/橘/紅）；`hasTargets=false` 時不渲染
- `_buildMarginChart()`：毛利率比較（Grouped Bar）；依業務員分組平均預估 vs 實際精算毛利率；`marginCases` 為空時不渲染
- `$watch('activeTab')`：切回 charts Tab 時，若實例已存在 → `resize()`；若初次進入 → `initCharts()`
- `$watch('data')`：期間切換後資料更新 → 在 charts Tab 時自動重新產圖

---

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

**歷史紀錄功能**
- `GET /api/daily-tasks/{id}/history?page=&per_page=`：所有歷史 occurrence 分頁，軟刪除後仍可讀
- `GET /api/daily-tasks/{id}/history/export`：UTF-8 BOM CSV（7 欄位）
- 右面板 Tab 切換「本次紀錄」/「歷史紀錄」；歷史 timeline 可展開每人狀態 + 回報；「載入更多」分頁；匯出 CSV 以 `Authorization: Bearer` fetch 再 blob download

**回報彙整視圖（全面重設計）**
- 從頂部按鈕切換，佔滿主畫面；分割面板：左 256px 任務列表 + 右詳情
- 回報文字永遠顯示於人員名稱正下方；當前登入人員的行以紫色左側條標記
- 日期選擇：年份/月份 select + ← → 日期導航；全文搜尋：即時搜尋任務名稱/分類/回報內容

**Email 商務文案全面改版（`helpers/email_notify.py`）**
- 所有 9 個 `notify_*` 函式改用 `【MOTRIX】` 主旨前綴，加 `intro` 問候段落，自訂 `button_text`

---

### 2026-07-21a — 每日工作事項全改版

**Req 1 — `pages/daily-tasks.html` 全新設計**
- UI：固定頂部工具列（月份導航）+ 左右雙欄佈局（左面板 300px 搜尋+任務卡片 / 右面板任務詳情）
- 新增/編輯 Modal：日期/優先級/標題/分類/說明 + 排程設定（單次/每週 + 星期幾圓形按鈕）+ 卡片型式人員選取
- 解鎖 Modal：輸入密碼 → POST /api/auth/verify-daily-task-unlock；428=未設定→自動解鎖；403=錯誤

**Req 2 — 管理視角存取控制**
- DB v15：`users.daily_task_pw_hash TEXT NOT NULL DEFAULT ''`
- 後端 `routers/auth.py`：新增 `POST /api/auth/verify-daily-task-unlock`、`PATCH /api/users/{id}/daily-task-password`

**Req 3 — `pages/users.html` 兩項擴充**
- 每列操作區新增「工作事項」按鈕；編輯 superadmin Modal 新增每日工作事項密碼區塊

**後端修復：週排程（DB v14）**
- `_m014_weekly_recurrence`：`daily_tasks` 新增 `recurrence_type/days/end_date`；重建 `daily_task_completions`（UNIQUE 由 (task_id, username) 改為 (task_id, occurrence_date, username)）

---

### 2026-07-20v — 每日工作事項 + 簽核繞過修復

**每日工作事項（`工作內容` 分類下新頁）**
- DB v13：`_m013_daily_tasks` 新增 `daily_tasks` + `daily_task_completions` + 索引
- 後端 `routers/daily_tasks.py`（新）：6 端點（CRUD + PATCH complete）
- 前端 `pages/daily-tasks.html`（新）：左右雙欄；月份導航；superadmin 人員篩選；完成回報 form

**簽核繞過修復（`routers/quotations.py`）**
- `PATCH /api/quotations/{no}/status` 加前置檢查：若 body.status=="已送出" 且尚有未完成簽核層 → 403

---

### 2026-07-20u — 同一層簽核人必須按順序簽核

- 同層內的審核人必須照陣列順序逐一簽核（1號簽完 → 2號才能簽）
- 後端：先確認用戶在當層，再找 `first_pending`；不是第一位 → 403
- 前端 `quotation-form.html` / `approval-queue.html`：改為只看 `firstPending`

---

### 2026-07-20t — 簽核每層加入拒絕結案鎖死功能

- `quotation-form.html` 新增「拒絕結案」Modal（工具列按鈕 + 預覽 Modal 底部）
- 必填原因 textarea；確認後呼叫 `POST /api/quotations/{no}/reject-final`

---

### 2026-07-20s — 退回改版報價單全狀態 returnInfo 顯示

- 移除 `q.status === '草稿'` 限制，改為 `x-show="q.returnInfo"`，所有狀態均顯示退回橫幅
- `reject_quotation()` 中 `previousItems` 快照新增 `type` 和 `brand` 欄位

---

### 2026-07-20r — 案件管理匯入選取功能 + PDF 隱藏欄位修復

- 「從報價單匯入」改為選取式 Modal（checkbox 品項清單，可全選/清除）
- `pdf_gen.py`：修復 `pdfShow` 設定被完全忽略的問題；6 個欄位改為條件式輸出

---

### 2026-07-20p — 專案管理成員分配功能

- DB v12：`projects.assigned_user_ids TEXT DEFAULT '[]'`
- 後端存取控制：非 admin 使用者只看到其 ID 在 `assigned_user_ids` 內的專案
- 新端點 `PATCH /api/projects/{id}/assigned-users`

---

### 2026-07-20o — 使用者管理模組同步修復

- `case_manage` 補入 allModules；ROLE_MODULES 同步更新
- 空 modules 陣列 bug 修復：`hasAccess()` 改用 length 判斷
- equipment 模組 sidebar gating；`dashboard` 模組支援；ntfy icon 補全
- Async session 同步：每頁背景呼叫 `GET /api/auth/me`，有變動立即更新 localStorage 並重建 sidebar

---

### 2026-07-20n — case-management 端點驗證 + §7.1 修正

- 全 9 端點驗證通過（零斷線）
- 移除錯誤標注的 `PATCH /payment/{idx}`（舊版殘留）

---

### 2026-07-20m — case-management 執行 Tab 扁平化

- 移除「執行」父 Tab 及子 Tab 列；4 個原子 Tab 晉升為頂層

---

### 2026-07-20l — case-management 同步 UI/UX 升級

- 左側卡片色條（CSS `:has()` 選擇器）+ Tab 計數 Badge
- Header 3 列化；狀態變更 Popover；日誌卡片視覺強化

---

### 2026-07-20k — projects.html UI/UX 全面重新設計

- 狀態篩選列改 flex-wrap Pill；卡片左色條（CSS `:has()`，7 種狀態色）
- 右側 Header 3 列化；狀態 Popover；日誌卡片 32px 日期 Icon Block
- JavaScript 0 改動

---

### 2026-07-20j — 報價單列表未成案分類

- 「全部」改名「全部(不含未成案)」並排除未成案
- 新增「未成案」Tab

---

### 2026-07-20i — 簽核 bug 修復、狀態手動調整、設備群組匯入

- 移除「自動跳過自身 tier-0 簽核」邏輯（此邏輯在唯一簽核人即申請人時造成 stuck）
- superadmin 狀態手動調整下拉；設備群組區塊式顯示（可折疊，按 qty 建立 N 台）

---

### 2026-07-20h — reject-final 對接、品項標題行、單項毛利欄、拖曳排序

- `approval-queue.html` 前端對接「拒絕結案」（Modal + API）
- `quotation-form.html` 新增 `type:'header'` 品項；`addHeader()`；`real_idx` 跳過標題行
- 單項毛利欄（amount − qty × cost × 1.05）；SortableJS v1.15.3 拖曳排序
- `pdf_gen.py`：識別標題行，輸出藍色全欄標題行

---

### 2026-07-20g — 退回修改完整流程

- `notify_returned()` / `notify_resubmit_requester()`（新）
- `returnInfo` 快照（退回人/時間/原因/前版品項）
- `quotation-form.html`：退回通知橫幅 + 退回修改 Modal + 簽核按鈕重構

---

### 2026-07-20f — 簽核功能完善版

- 收回草稿（`POST /api/quotations/{no}/recall`）
- Email `from_name` 統一為 `"MOTRIX營運系統"`
- Email 靜默丟棄改為 warning log
- Photo token `@error` retry

---

### 2026-07-20e — 修正版

- 死碼清除：刪除 `frontend/js/` 21 個未被載入的 JS 檔
- settlement.html / approval-settings.html / projects.html 補實作與修正

---

### 2026-07-20d — 驗證修正版

- §2/§7/§9/§11/§13 全面修正（死碼標示、幽靈頁面、SQL fallback、雙路徑風險）

---

### 2026-07-20c — 架構梳理交付版

- 全面讀取後端 11 個 router + 6 個 helpers + archive/pdf_gen
- 新增 §5/§6/§7/§15（共用函式庫、API 端點列表、前端→API 對應、資料流呼叫鏈）

---

### 2026-07-20b — UX P3：簽核佇列警示 + 案件執行階段標籤 + 待精算篩選

- 儀表板 Onboarding 引導條；「待精算」篩選 Tab；簽核佇列紅色警示

---

### 2026-07-20 — UX P1/P2：簽核待辦儀表板 + sidebar 角標 + 通知拆分

- 儀表板「等我簽核」KPI；sidebar 簽核佇列角標；`GET /api/approval-queue/count`

---

### 2026-07-19b — Email 通知修復 + 舊代碼清除

- `is_new_submission` 改查 DB 舊狀態；OPTIONS 放行修正；restart.bat 改 PowerShell

---

### 2026-07-19 — Email 通知功能

- `helpers/email_notify.py`（新）：Gmail SMTP 非同步發信；5 事件函式

---

### 2026-07-18a — 全面安全審查 P0–P3（30 項）

**P0 — 安全漏洞**：多個端點補 `_require_user`；deal-tag 補 Auth header；DELETE 僅草稿

**P1 — 業務邏輯**：解鎖 superadmin 驗證；狀態機白名單；deal_tag 已結案不可逆；settlement 回滾；GET /auth/me 驗 expires_at

**P2 — 邊界案例**：mark_payment 樂觀鎖；delegateNote 寫 audit；已成案降級限 admin+；G: fallback；rate limit 持久化；notif.js DOM API；防重複送出 flag

**P3 — 品質**：JSON 原子寫入；Dashboard sparkline 真實資料；audit-log admin+ only；work-log owner 驗證
