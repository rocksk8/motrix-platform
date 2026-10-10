# 財務機制設計（第 54 班）：法定參數版本表、假日曆後台、信用額度／逾期／大額付款／金額級距簽核

基準 `origin/platform` `b2486535c`；作者 ab；2026-10-11。**設計稿，不含程式。** 承接 `LONGRUN-CHURN-FINANCE-T54.md`（87 項）與使用者對它的裁示：
(1) 法定參數用**生效日版本表**（擴充 `legal_params`；負責人新增一列；舊單據保留舊值）＋『政策生效日』表收編日期型切換；(2) 假日曆由 superadmin 在系統內維護（匯入／編輯），涵蓋最後一天前 **60 天**警示，全程稽核；(3) 要做：客戶信用額度、逾期／寬限規則、大額付款警示、**簽核金額級距**（先前已裁示）；**多幣別不做**。
與 node-39 `SETTINGS-CENTER-DESIGN-T54.md`（設定群組＋設定中心）、1d `PERMISSION-MATRIX-DESIGN-T54.md`（能力矩陣、`config_ledger`）對齊，不另建第二套版本／稽核。

## 0. 結論

1. **一張核心表 `statutory_params`（kind, key, effective_from, value_json, source, entered_by, reason…）＋一個查找 API `statutory.on(kind, key, date)`**，是『法定參數』與『政策生效日』共用的唯一機制。上線當天零行為變更：今天所有寫死值作為**第一列**種入，另有等價黃金向量與『不得再出現字面 0.05／1.05』的棘輪守門（比照暫存區守門）。
2. **單據大多已經『帶著自己的稅率』**（報價 `taxRate`、派工 `tax_rate`、發票金額欄位）。所以查找表的實際工作只有兩種：**新單據的預設值**（以單據日期取當時版本）與**沒有自帶稅率的推估**（精算預設成本倍數 1.05、含稅反推 ÷1.05，用該筆來源單據的日期）。這讓『取代 15 處』變成可機械化的替換，而不是改資料。
3. **假日曆**：核心表 `calendar_days`＋匯入批次表；CSV 上傳預覽（預設不連外）、手動加減（必填原因）、公司自訂休日層、涵蓋到期前 60 天警示（儀表板＋信件＋所有用到工作日的功能標示），匯入可整批復原。**附帶抓到一個 bug**：傳票單號產生器已經會產出第 1000 張的 `-1000`，但讀取用的正則 `\d{3}` 認不得它 ⇒ 會一直產出同一個號碼（見 §3.5），一行即可修，建議立刻修（獨立於本設計）。
4. **四個新機制共用同一組骨架**：規則表（含生效日）＋ 單一檢查函式 `finance_guard.check(event, doc, user)` 回 `ok／warn／block` ＋ 覆寫（理由必填、記 `finance_overrides`、通知財務）＋ 能力（接 1d 的 `finance.credit.override` 等）。**預設全部『只警告』**（先觀察一季再決定要不要擋）。
5. **兩個前置條件不先做會做不好**：(a) 結構化付款條件（有『到期日』才有逾期與帳齡）；(b) 客戶識別——案件沒有正規化客戶 id（只在從下拉選時才有 `customerId`，很多舊案是打字的客戶名稱），信用額度要先決定『同一個客戶』怎麼認。
6. 工作量合計約 **47～59 人日**（法定參數 14～16、假日曆 7～9、付款條件＋逾期 8～10、信用額度 7～9、大額付款 3～4、金額級距 8～11），建議分五班（§5）。

## 1. 現況錨點（這些決定了設計）

| 事實 | 位置 |
|---|---|
| 扣繳／補充保費／最低工資已是『生效日版本表』，存在 `system_settings.tax_rules_versions`（JSON 清單）；已生效版本凍結；勞報單記 `tax_rules_version` | `helpers/legal_params.py:19-62,124-250`；`routers/legal_params.py`；頁 `legal-params.html` |
| 營業稅率是常數 `LEGAL_TAX_RATE = 0.05`；`0.05`／`1.05` 另散在約 15 處，前端幾乎全是抄常數 | `helpers/tax_calc.py:27`；清單見 churn 稿 FB01 |
| 報價稅率存在單據裡（`taxRate`）；派工 `tax_rate` 逐筆；發票稅額為發票欄位 | `quote_terms.py:165`、`vendor_contractors.py:85`、`tax_calc.invoice_amounts` |
| 定義文件庫 `core/definitions.py`：草稿→驗證→發布→差異→還原；node-39 設計的 `setting_group` kind 建在它上面 | `core/definitions.py`；`SETTINGS-CENTER-DESIGN-T54.md` |
| 假日曆是 `helpers/holidays_tw.json`（涵蓋 2026-01-01～2027-12-31，無後台）；`business_days.py` 以檔案 mtime 快取；到期後只認週六日；只有標案雷達在到期前 60 天警示 | `helpers/business_days.py:19-80`、`tender_radar/source.py:1107` |
| 簽核層級由 `approval_settings` 逐單據類型設定，**沒有金額欄位**；`resolve_active_flow_setting(doc_type)`→`setting_to_active_tiers(setting, conn, requester)` 產出 tiers 並快照進單據 | `helpers/tiered_approval.py:112-132,329` |
| 所有『待付款』經單一出納端點 `POST /api/cashier/pending-payables/{source}/{key}/pay` 呼叫提供者 `mark_paid`——**付款的唯一咽喉** | `modules/arap/api/cashier.py:190-250` |
| 應收帳齡以報價日為基準、依案件 `caseRecord.payment.items` 的 `received`；案件沒有正規化客戶 id | `analytics/api/reports.py:2600-2660`、`case/api/quotations.py:1132`（註解） |
| 傳票單號 `YYYYMMDD-NNN`：產生 `"%s-%03d" % (day, max+1)`；讀取正則 `^(\d{8})-(\d{3})(?:-R\d+)?$` | `accounting/voucher.py:295,298-331` |

## 2. (a) 法定參數版本表

### 2.1 範圍與值形狀（kind）

| kind | key | 值（JSON） | 今天的第一列（＝現行寫死值） |
|---|---|---|---|
| `vat` | `standard_rate` | `{"rate": 0.05}` | 0.05（生效 1986-04-01；營業稅法 §10） |
| `vat` | `zero_exempt_basis` | `{"zero":[選項…],"exempt":[選項…],"note_required":[…]}` | `legal_params.TAX_BASIS_OPTIONS` 現況 |
| `nonresident` | `rules` | `{"days":183,"low_salary_multiple":1.5}` | 183／1.5 |
| `income_types` | `list` | `[{code,label,filing_code,…}]` | 50／9A／9B 與標籤 |
| `withholding` | `remit_due` | `{"income_tax_day":10,"nhi":"month_end"}` | 次月 10 日／次月底 |
| `form401` | `format` | `{"line_names":…,"formulas":…,"media":{"fields":…}}`（以公告令為單位） | `tax401.py`／`tax401_media.py` 現況（113/04/12 令） |
| `policy_date` | `<政策鍵>` | `{"value":…}`，例：`dispatch_cost_taxed`＝true、`po_required`＝true | `DISPATCH_TAXED_FROM=2026-10-01`、`PO_REQUIRED_FROM=2026-10-04` |
| （既有）`tax_rules` | 見現行 | 扣繳率、起扣、補充保費、最低工資 | **不搬**：第一階段維持 `tax_rules_versions`，由查找 API 代理（§2.3） |

每個 kind 在程式裡登錄 `StatuteKind(kind, key, schema, validator, label, risk=legal)`（欄位型別、上下限、必填；管理者改不了）。新增 kind＝加登錄，不用改表。

### 2.2 資料表（核心 migration，`CORE NEXT` 佔位，不升 schema 版）

```
statutory_params(
  id INTEGER PK, kind TEXT, key TEXT,
  effective_from TEXT NOT NULL,            -- YYYY-MM-DD，含當天
  value_json TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT '',          -- 法源／公告令文號
  reference_url TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL DEFAULT 'draft',      -- draft | active | withdrawn
  entered_by TEXT, entered_at TEXT,
  published_by TEXT, published_at TEXT,
  reason TEXT NOT NULL DEFAULT '',
  seed INTEGER NOT NULL DEFAULT 0,          -- 1＝部署種子（今天的寫死值）
  )
-- 部分唯一索引（SQLite 支援）：CREATE UNIQUE INDEX ux_statutory ON statutory_params(kind, key, effective_from) WHERE state != 'withdrawn';
```
- **只增不改**：`active` 且 `effective_from ≤ 今天` 的列**凍結**（不可改、不可撤回）；未生效的 `draft`／`active` 列可撤回（`withdrawn`，留痕）。要『修正已生效的值』＝新增一列（新的 `effective_from`）＋原因，**不改歷史**；真的算錯要追溯，走『更正單』流程（另案，不在本稿）。
- `kind='tax_rules'` 不入此表（第一階段）：`statutory.on('tax_rules', None, date)` 代理到 `legal_params.rules_for_date`；第二階段才把 `tax_rules_versions` 搬進此表（一次性、可還原）。

### 2.3 查找 API（後端單一入口 `helpers/statutory.py`，L1）

```
statutory.on(kind, key, on_date) -> value dict         # 取 effective_from ≤ on_date 的最新 active 列；沒有 ⇒ NoApplicable（不猜）
statutory.vat_rate(on_date) -> Decimal                  # 常用捷徑；on_date 缺／壞 ⇒ 今天並 warning
statutory.vat_rate_for(doc_type, doc) -> Decimal        # 依下表『單據日期』取
statutory.upcoming(kind, key) -> 下一個已排程的列        # 給 UI 顯示『某日起改為 …』
statutory.gaps(today) -> [缺口提示]                      # 例：2027 版缺（見 §2.7）
```
**單據日期表（rate date）**——這張表就是『單據怎麼知道用哪一版』：

| 單據 | 取哪個日期 | 備註 |
|---|---|---|
| 報價單 | `quoteDate`（存檔時把解出的稅率寫進單據 `taxRate`，之後以單據為準） | 已存稅率的單據不再查表 |
| 發票／收款憑據 | 開立日 `invoiceDate` | 發票有稅額欄位時以欄位為準 |
| 承攬商派工／匯款申請 | `dispatch_date`／憑據日期 | 逐筆 `tax_rate` 為準；查表只供預設 |
| 精算預設成本倍數、含稅反推（沒有自帶稅率） | 該筆來源單據的日期（費用單據＝發票日，採購單＝單據日，品項估計＝報價日） | 取代 `ESTIMATE_RATE=1.05`、`÷1.05` |
| 總帳事件進項估算 | 事件的認列日 | `supply/gl_events.py:19` |
| 勞報單等所得稅類 | 付款／給付日 | 既有 `tax_rules_version` 機制不變 |

日期缺或讀不懂 ⇒ 用今天、記 warning、結果旁標『日期缺，已用今天稅率』（不拋例外、不靜默）。

### 2.4 前端

後端 `GET /api/statutory/public?kinds=vat,nonresident&on=YYYY-MM-DD`（登入者可讀）＋ `static/statutory-client.js`：頁面啟動時預載並同步提供 `MotrixStatute.vatRate(date)`（`calcTotals` 是同步函式，不能每次 await）；預載失敗 ⇒ 用內嵌預設（＝種子值）並在頁首顯示『法定參數載入失敗，使用預設』。**取代**把 `0.05`／`1.05` 抄進 JS（`quotation-form.html`、`settlement.html`、`case-management*.js`、`form-designer*.js`）。精算 API 本來就回 `estimateRate`，前端改用它（現在回了但前端另寫死）。

### 2.5 取代 15 處的對照（機械化）

| 現況 | 改成 |
|---|---|
| `tax_calc.LEGAL_TAX_RATE`（常數） | 保留為**別名**＝`statutory.vat_rate(today)`（一班後移除）；`tax_split(sales, type, on_date=None)` 加日期參數（缺省＝今天，行為不變） |
| `quote_terms.py:165-173`、`quotation-form.html:2608`（缺稅率→5；<5 需審核；『標準 5%』） | 標準稅率＝`vat_rate(quoteDate)`；文字由數字組出 |
| `profit_guard.py:160`（進項稅估算 `×0.05`）、`quotation-form.html:1840` | `vat_rate(quoteDate)`；『進項是否視為成本』另列政策開關 `policy_date/input_vat_as_cost`（現在＝true） |
| `settlement_actuals.py:20`（`ESTIMATE_RATE=1.05`）、`recognition.py:355`、`receivables.py:110`、`settlement.html` 10 餘處 | 單一函式 `gross_factor(on_date)=1+vat_rate`、`net_of_tax(amount, on_date)`；前端取 API 回傳的 `estimateRate` |
| 承攬商預設稅率 0.05（`vendor_contractors.py:85`… 十餘處） | `tax_calc.default_dispatch_rate(vendor, on_date)`＝廠商設定『含稅／未稅』→ `vat_rate(date)` 或 0；DB 欄位 `DEFAULT 0.05` 保留（凍結 migration） |
| `supply/gl_events.py:19`、`subcontract/gl_events.py:60` | `vat_rate(認列日)` |
| `form_templates/*.json:152`（版型公式 `* 0.05`） | 版型公式變數 `vat_rate`（版型引擎支援變數則直接用；否則版型載入時注入） |
| 稅別標籤『應稅 5%』（`tax_calc.py:26`、`reports.py:2782`、`pdf_gen.py:241`、`quotation-form.html:1623`） | 由 `vat_rate` 組字（`"應稅 %s%%"`） |

### 2.6 零行為變更的證明（三道）

1. **種子＝今天的值**：migration 只種 `seed=1` 的第一列，不改任何單據；缺列時查找函式回『程式內預設（＝種子）』並 warning（不丟例外）。
2. **等價黃金向量**：改碼前先用腳本對現行函式（`tax_split`、`tax_calc.*`、`profit_guard` 進項、`recognition.estimated_tax`、`settlement` 預設、`receivables` 反推、PDF 稅額）各產生 ≥200 筆向量存 `tests/data/statutory_equivalence_vectors.json`（含 .5 進位邊界）；改碼後逐筆比對；前端用 node 載入 `statutory-client.js` 同一份向量（比照 `profit_rules_vectors.json`）。
3. **字面值棘輪守門**（比照 `test_recyclebin_guards_t53`）：AST／正則掃產品碼的 `0.05`、`1.05`、`/ 1.05`、`'5'`（稅率語意），基線登記允許位置（DB 欄位預設、凍結 migration、種子、測試），只准縮小，新增即紅。

### 2.7 與設定中心／`config_ledger`／權限矩陣對接

- **位置**：設定中心頁（`系統 > 設定中心`）新增一個區塊『法定參數（生效日版本）』，**不放進 `setting_group`**（它需要生效日與凍結語意，`setting_group` 沒有），但沿用同一套外觀（群組樹、差異預覽、原因欄）。已有的『法規參數設定』頁（`legal-params.html`）併入此區塊作為 `tax_rules` 分頁，原網址保留轉址。
- **操作流程**（負責人加一列）：選 kind→表單由 `StatuteKind.schema` 產生→填 `effective_from`、值、`source`（必填）、`reason`（必填）→『存草稿』→預覽（**影響說明**：『從 2027-01-01 起新建的報價預設稅率 5%→5%；已存單據不變』；`vat` 變動並列出受影響的衍生（毛利估算、精算預設））→『發布』。
- **權限**：能力 `finance.statutory.edit`（存草稿）、`finance.statutory.publish`（發布；預設僅 superadmin；可由 superadmin 授給財務負責人）。1d 矩陣就緒前，沿用 `superadmin`。高風險＝法定參數發布：必填原因；`effective_from` 在 7 天內再加 `confirm`。
- **稽核與待生效**：寫 `config_ledger.record(domain='statutory:<kind>', key, changes, reason, actor, effective_at=effective_from)`（設計稿 §2 的最小介面）；舊→新差異、來源、發布者都進只增不改的明細；『待生效』狀態直接由 `effective_from > 今天` 表示，不需要另一層 24 小時機制。
- **提醒**：`statutory.gaps()` 每日檢查：下一年版缺（**10 月 1 日起**提示，取代現在的 12 月才提示）、已排程但 30 天內生效的列（給財務確認）、`form401` 超過 12 個月沒覆核（提示『請確認公告令有無更新』）。**2027 版必須在 2026-12 前完成**：最低工資（30,900 待核定）與扣繳起扣標準；`vat` 本身不需要新列。
- **稽核動作**：`statutory.draft／publish／withdraw`、`statutory.lookup_fallback`（用了程式預設）。

### 2.8 分期與工作量

| 期 | 內容 | 人日 |
|---|---|---|
| S0 | 表＋`statutory.on`＋kind 登錄＋種子＋稽核＋`tax_rules` 代理＋API＋守門骨架 | 3～4 |
| S1 | 後端 15 處替換＋黃金向量＋字面值棘輪（含承攬商預設） | 4～5 |
| S2 | 前端：`statutory-client.js`＋`quotation-form`／`settlement`／`case-management*`／`form-designer*` 取代抄本＋node 向量 | 3～4 |
| S3 | 設定中心區塊 UI（草稿、預覽、發布、時間軸）＋提醒＋`legal-params.html` 併入 | 3 |
| S4 | `form401`／`zero_exempt_basis`／`income_types`／`nonresident`／`remit_due` 逐一 kind 化（可分批） | 4～6 |
| **合計** | | **17～22**（其中 S0～S2＝『VAT 零行為變更』主幹約 10～13） |

## 3. (b) 假日曆後台

### 3.1 資料模型（核心 migration）

```
calendar_batches(id PK, kind TEXT,            -- 'seed' | 'import' | 'manual'
  source_name TEXT, source_url TEXT, fetched_at TEXT,
  year_from INT, year_to INT, row_count INT, checksum TEXT,
  entered_by TEXT, entered_at TEXT, reason TEXT, state TEXT)   -- active | reverted
calendar_days(date TEXT PK-per-layer, layer TEXT,   -- 'national'（政府公告）| 'company'（公司自訂）
  kind TEXT,          -- holiday（休）| makeup（補班日，上班）
  name TEXT, batch_id INT, entered_by TEXT, entered_at TEXT, reason TEXT,
  UNIQUE(layer, date))
calendar_coverage(layer TEXT, year INT, complete INT, batch_id INT)  -- 該年資料是否完整（官方整年已公布）
```
- **種子**：現有 `holidays_tw.json` 轉成 `seed` 批次（national 層，2026～2027，`complete=1`）；`business_days` 之後讀資料庫，**檔案保留作為資料表不存在時的退路**（模組／舊庫），行為等價（黃金：2026～2027 每一天 `is_working_day` 與舊實作逐日相同）。
- **兩層**：`national`（官方公告，匯入）＋`company`（公司自訂休日／加班日，手動）；`is_working_day = national 判斷，再套 company 覆蓋`。company 層預設空，上線零行為變更。

### 3.2 匯入與編輯（superadmin；能力 `system.calendar.edit`）

- **匯入（預設不連外）**：上傳政府公開資料 CSV（人事行政總處『政府行政機關辦公日曆表』，`data.gov.tw/dataset/14718`）→ 伺服器解析→**預覽與驗證**：每年天數、週六日是否都被標為休（官方資料已含）、補班日必為週末且不與假日重疊、跨年連續、與現有批次的**差異表**（新增／改名／刪除的日期）→ 確認＋原因 → 寫入新批次、`calendar_coverage` 更新。『一鍵抓取』做成**選配**：沿用既有對外連線開關模式（環境變數開才出現按鈕，預設關），抓回來的資料同樣先預覽。
- **手動**：月曆畫面點一天→加／改／移除（必填原因、記 `entered_by`）；company 層同。**不可改已過去超過 N 天的日期？** 否——假日曆是事實表，不凍結；但每次改動寫稽核明細（舊→新、原因），且**改過去日期時警告『會影響已寄出的提醒／已過的順延計算』**。
- **整批復原**：匯入批次可『復原』（`state=reverted`，日期回到上一批的值），不刪資料、留痕。

### 3.3 涵蓋警示（使用者：涵蓋最後一天前 60 天）

- `coverage_end = 該層最後一個 complete 年份的 12/31`。`days_left = coverage_end - 今天`。
- **60 天內**：設定中心頁首＋儀表板（對 superadmin）顯示『假日曆 N 天後到期，請匯入 YYYY 年資料』；每日工作寄一次信（mail type 新增，可個人退訂）；**到期後**每天再提示，且所有用到工作日的功能在結果旁標『假日表未涵蓋，僅排除週末』——現在只有標案雷達會標，擴到付款提醒（`payable_due_core`）、簽核催辦（`system_checks`）、行事曆順延。
- 提醒規則的 60 天寫成設定 `calendar.warn_days`（預設 60，下限 14）。

### 3.4 稽核

`calendar.import`（批次摘要＋差異）、`calendar.import_revert`、`calendar.day_add／day_edit／day_remove`（逐日，含原因）、`calendar.warn_sent`。皆為只增不改。

### 3.5 傳票每日流水 3→4 位（建議）

**發現**：`next_voucher_no` 產出 `"%s-%03d" % (day, biggest+1)`，第 1000 張會產出 `20261010-1000`（自然溢位成 4 位），但取最大值的正則 `^(\d{8})-(\d{3})(?:-R\d+)?$` 認不得 4 位 ⇒ `biggest` 停在 999 ⇒ 下一次又產出 `-1000` ⇒ **唯一索引撞號**。
**建議（獨立於本設計，可立刻修）**：
1. 正則改 `(\d{3,})`（同一個檔案裡 `_REV_SUFFIX` 等相關正則一併檢視），格式維持 `%03d`（≥1000 自然變 4 位）。**零行為變更**：現有最大每日量遠小於 999。
2. 排序：`ORDER BY voucher_no` 的字串排序在 4 位時會把 `-1000` 排在 `-999` 前面；`ledger/reports.py:179` 等處改 `ORDER BY date, length(base_no), voucher_no`（或存一欄 `voucher_seq` 整數）。
3. **待負責人確認**：外部系統（T100 匯出、會計師）對單號長度有無上限？（T100 匯出欄位寬度需查證；若有 12 碼限制，`YYYYMMDD-NNNN` 是 13 碼。）若有限制，替代方案：第 1000 張起改用 `YYYYMMDD` 加 `A001`（同樣可排序）——或單日量上限設警示。
這是『衛生債』，不需要選項。

### 3.6 與權限矩陣／設定中心

- 能力：`system.calendar.view`（全部登入者隱含）、`system.calendar.edit`（預設 superadmin；不可再委派，因為會影響付款與簽核的提醒日）。
- UI：設定中心 > 『行事曆／假日』區塊（月曆網格、批次清單、涵蓋進度條、匯入精靈）。

### 3.7 工作量

| 期 | 內容 | 人日 |
|---|---|---|
| C0 | 表＋種子＋`business_days` 改讀庫（含檔案退路）＋逐日等價測試 | 2 |
| C1 | 匯入（解析、預覽、驗證、差異）＋手動編輯＋復原＋稽核 | 3～4 |
| C2 | 涵蓋警示（儀表板、信件、各消費者標示）＋UI | 2～3 |
| **合計** | | **7～9**（傳票流水修正 0.5 另計） |

## 4. (c) 信用額度、逾期／寬限、大額付款、金額級距簽核

### 4.1 共同骨架

```
finance_guard.check(event, doc, user, *, override=None) -> Result{level: ok|warn|block, rule, message, details, can_override}
```
- **事件**（enforce 點）：`quote.approve`、`ship.submit`／`ship.approve`、`pay.execute`、`approval.submit`（金額級距）。每個事件點只加**一行呼叫**＋回應多一個 `warnings`/`blocked` 欄位；規則實作在一個模組（`modules/arap/finance_guard.py` 或獨立模組 `credit`——**待決**，見 §6）。
- **等級**：每條規則有 `mode: off | warn | block`（預設 `warn`，信用額度與大額付款上線時**不擋**；跑一季看誤報再開 block）。
- **覆寫**：被 `block` 時，持有能力 `finance.guard.override` 者可填**必填理由**後放行；寫 `finance_overrides(id, rule, event, doc_type, doc_no, amount, limit_value, reason, overridden_by, approved_by?, at)`，通知財務負責人與 superadmin；覆寫記錄進單據歷史。高金額覆寫（超過限額 2 倍）需**第二位**（財務負責人）確認——用既有簽核機制『臨時加簽』實作（待決）。
- **警告**：`warn` 不需理由，但回傳給前端顯示橘色提示，並寫 `finance_guard_log`（輕量；90 天輪替）供一季後檢討誤報率。
- **規則版本**：額度政策表（門檻、模式）屬『經營決策、需留歷史』⇒ 存 `statutory_params` 的 `kind='policy'`（有生效日、只增不改），**客戶個別額度**是資料（見 4.3）。
- **權限矩陣**：能力 `finance.credit.view`（看額度與曝險）、`finance.credit.edit_limit`（設客戶額度；高風險＝授予走 24 小時待生效）、`finance.guard.override`、`finance.payment.large_ack`、`finance.approval.tiers.edit`。1d 就緒前沿用 superadmin／財務角色。

### 4.2 前置條件一：客戶識別

案件只有 `customer_name`（文字）；`customerId` 只在從客戶下拉選時才寫入。信用額度需要『這個案件屬於哪個客戶』。建議：
1. **客戶主檔加 `credit_key`**（正規化名稱＋統一編號）；`customers.tax_id` 已有欄位。
2. 新增『客戶綁定』欄：報價單存檔時若 `customerId` 缺，伺服器以**統一編號精確比對**→**正規化名稱精確比對**嘗試綁定；綁不到的標 `unbound`，不納入額度計算並在額度頁列出『未綁定案件清單』供人工綁定（一次性補綁工具）。
3. **不做**模糊比對（猜錯＝把 A 客戶的曝險算到 B 客戶）。

### 4.3 信用額度

- **資料**：`customer_credit(customer_id PK, limit_amount, terms_days, hold INTEGER, note, set_by, set_at)`＋`customer_credit_history`（只增不改，每次變更一列：舊→新、原因、操作者）。額度 0／空＝未設定＝不檢查。
- **曝險定義**（需負責人確認）：`曝險 = 該客戶已成案案件的『未收款金額』（含稅，依 `payment.items` 未 `received`）＋ 已出貨但尚未開立發票的金額 ＋ （本次）新單金額`。預設口徑建議用『未收款＋已出貨未開票』，不含尚未成案的報價（避免報價階段誤擋）。
- **檢查點**：`ship.submit`／`ship.approve`（**主要**：出貨前最後防線，`shipping_notes.py:379,449`）、`quote.approve`（成案時，警示用）。超額 ⇒ `warn`（預設）；`mode=block` 時需覆寫。**逾期黑名單**：客戶有超過寬限的逾期款 ⇒ 另一條規則（4.4）。
- **UI**：客戶頁加『信用』分頁（額度、已用、可用、逾期、歷史、未綁定案件）；報價單／出貨單頁頂顯示『客戶可用額度』徽章；額度頁僅持 `finance.credit.view` 者可見（金額敏感）。

### 4.4 逾期／寬限規則

- **前置**：結構化付款條件（FB08 建議）——付款期數、比例、**付款日規則**（交貨後 N 天／次月某日／驗收後 N 天）。做出來後每個 `payment.items` 才有『預計收款日 `due_date`』。沒有它，逾期只能用報價日估（現況帳齡就是這樣），**所以本機制排在付款條件之後**。
- **規則表**（有生效日）：`overdue_rules(scope: global|customer, grace_days, reminder_cadence[], escalation: [{after_days, action}], ship_hold_after_days, interest_note)`。動作：`remind`（信件給業務／財務）、`flag`（客戶標記逾期）、`hold_warn`（出貨/成案時警告）、`hold_block`（預設關）。
- **狀態**：每筆應收派生 `not_due｜due_soon｜grace｜overdue(N天)`；帳齡報表改以 `due_date` 為基準（可切回報價日以對照）。
- **排程**：每日工作（08:00 補跑語意同 `payable_due_core`）；通知對象依角色（業務＝案件業務、財務）；工作日以假日曆計（寬限天數可選『日曆日／工作日』）。
- **覆寫**：個別客戶可有較長寬限（`customer_credit.terms_days` 或規則 scope=customer）；經批准的展延記 `finance_overrides`。

### 4.5 大額付款警示

- **咽喉**：`pay_pending_payable`（`cashier.py:190`）在呼叫提供者 `mark_paid` **之前**加 `finance_guard.check('pay.execute', …)`；所有待付款來源（請款單、承攬商匯款、叫料、勞報、獎金…）都經此，一處覆蓋。
- **規則**：(1) 單筆 ≥ 門檻（預設值待負責人給；建議依單據類型分別設）⇒ 警告出納並**要求勾選確認＋可選備註**；(2) 同一收款人當日／當月累計 ≥ 門檻 ⇒ 警告（防拆單）；(3) 收款人首次付款（無歷史）且金額 ≥ 較低門檻 ⇒ 警告；(4) 付款帳戶與申請時不一致 ⇒ 既有檢查，不在此。
- **等級**：預設 `warn`（出納需確認勾選，不需理由）；`block` 模式時需 `finance.guard.override` 持有者放行（不可是出納本人，建議）。記入 `cashier.payable_paid` 稽核明細（`large_ack: true`）。
- 工作量小（單一咽喉）。

### 4.6 簽核金額級距

- **模型**：在既有簽核設定（`approval_settings` 的每單據類型 flow）加 `amount_rules`：
```
amount_rules = [ {from_amount: 0,        tiers: <基礎層級，維持現行>},
                 {from_amount: 100000,   add_tiers: [<加簽一層：部門主管>]},
                 {from_amount: 1000000,  add_tiers: [<加簽：總經理>]} ]      # 依『金額基準』落入區間 ⇒ 疊加（或 replace）層級
```
  含生效日（存 `statutory_params` kind=`approval_amount_tiers`，key=`<doc_type>`）。**送審當下**依單據金額求出適用層級，**快照進單據 `approval.tiers`**（現有機制已快照 tiers，所以流程中途改規則不影響進行中的單據）。
- **金額基準表**（每單據類型一個函式 `doc_amount(doc_type, doc)`）：報價＝`tot.total`；出貨＝品項合計含稅；請款／發票憑據＝憑據金額；承攬商匯款＝應付含稅；額外支出＝總額；獎金＝總發放額；傳票＝借方合計。金額讀不到 ⇒ 套用**最高級距**並標『金額未識別』（寧嚴勿鬆）。
- **簽核人金額授權（第二期）**：能力參數 `finance.approve` 的 `max_amount`（某人最多核准多少）——與 1d 能力矩陣的『參數化能力』對接；超過 ⇒ 該層不可由他簽、自動上送。
- **互動**：金額級距只**加**簽核層，不減；現有 `check_no_tier_self_approval`、委派、組織鏈規則照舊；改單據金額（解鎖編輯）⇒ 重算適用層級並重新簽核（與現行『解鎖編輯強制重簽』一致）；級距邊界用含稅金額、半開區間 `[from, next)`。
- **上線當天零行為變更**：`amount_rules` 預設空 ⇒ 完全沿用現行層級。
- **UI**：簽核設定頁每個單據類型加『金額級距』區塊（表格＋預覽『若金額 X ⇒ 簽核鏈 …』）；單據送審畫面顯示『因金額 X 加簽：…』。

### 4.7 警告 vs 擋 與覆寫（彙整）

| 機制 | 預設 | 擋住時誰能放行 | 覆寫必填 | 通知 |
|---|---|---|---|---|
| 信用額度超額 | warn | `finance.guard.override`（財務負責人）；超額 >2 倍需第二位 | 理由 | 財務＋該客戶業務 |
| 客戶逾期（持有逾期款） | warn | 同上 | 理由 | 財務＋業務 |
| 大額付款 | warn（出納勾選確認） | 非出納本人的財務負責人 | 理由（block 模式） | 財務 |
| 金額級距簽核 | 不擋，只加簽 | 不適用（加簽即流程） | — | 加簽人 |

### 4.8 分期與工作量

| 期 | 內容 | 人日 |
|---|---|---|
| G0 | `finance_guard` 骨架＋`finance_overrides`＋能力登錄＋稽核＋設定頁區塊 | 3～4 |
| G1 | 結構化付款條件＋`due_date`＋帳齡改基準（也是 FB08 的主件） | 5～6 |
| G2 | 逾期／寬限規則＋每日工作＋UI | 3～4 |
| G3 | 客戶綁定（補綁工具）＋信用額度＋檢查點＋客戶頁分頁 | 6～8 |
| G4 | 大額付款（咽喉單點） | 2～3 |
| G5 | 金額級距簽核（規則表、金額基準、快照、UI）＋授權金額（第二期） | 8～11 |
| **合計** | | **27～36**（含 G1 的付款條件） |

## 5. 建議班次與順序

| 班 | 內容 | 人日 | 為什麼這個順序 |
|---|---|---|---|
| 甲 | 傳票流水修正（0.5）＋ S0～S2（VAT 零行為變更主幹） | 11～14 | 風險最低、價值最確定、並且是其他所有『參數』的底座 |
| 乙 | 假日曆 C0～C2＋ S3（法定參數 UI）＋ 2027 版提醒機制 | 8～11 | 有硬期限（2026-12 的 2027 版；2027 年中的假日曆） |
| 丙 | 結構化付款條件 G1＋逾期 G2 | 8～10 | 逾期與帳齡的前置；使用者早就嫌帳齡失真 |
| 丁 | G0 骨架＋大額付款 G4＋ S4 其餘 kind（401、依據、所得類別） | 9～13 | 大額付款是最便宜的內控；401 版本化趁官方下次改版前 |
| 戊 | 客戶綁定＋信用額度 G3＋金額級距 G5 | 14～19 | 最大且需要客戶資料清理；放最後，前面全部提供底座 |

## 6. 待負責人／PM 決定

1. **信用額度曝險口徑**（§4.3）：只算『未收款＋已出貨未開票』是否可接受？是否要包含已成案但尚未出貨的訂單？
2. **預設等級**：信用額度與大額付款上線時『只警告』是否同意？何時評估改為擋（建議一季後看 `finance_guard_log` 誤報率）。
3. **大額付款門檻數字**與是否分單據類型（我沒有數字，需財務給）；累計規則（當日／當月）。
4. **簽核金額級距**：各單據類型的區間與加簽人（部門主管？總經理？）；金額是含稅還是未稅（建議含稅）。
5. **模組歸屬**：`finance_guard`／額度／逾期要不要獨立模組（`credit`，可單獨販售、拿掉時各檢查點自動略過，符合『缺席要明說』），還是放 `arap`？建議獨立模組＋L1 契約（比照暫存區：檢查點只呼叫 L1 `finance_guard.check()`，模組不在 ⇒ 回 ok 並記 log）。
6. **傳票單號長度**：T100／會計師對單號長度有無上限？（§3.5）
7. **假日曆**：由誰匯入（建議出納兼系統管理者）？是否需要『公司自訂休日』層（預設空）？
8. **政策生效日**第一批收編：`dispatch_cost_taxed`、`po_required`、營運報表預設口徑——確認這三項。

## 7. 風險

- **替換 15 處稅率**是最大單一風險：靠黃金向量＋棘輪守門＋逐檔分批（先後端、再前端）緩解；任何一處漏換不會壞（仍是 5%），只是之後稅率變動時漏改——棘輪守門就是為了讓『漏』在 CI 紅燈。
- **前端同步取值**：`calcTotals` 同步，預載失敗退回內嵌預設；內嵌預設由後端建置時產生，避免兩份。
- **信用額度的資料品質**：客戶綁定不完整 ⇒ 曝險偏低（漏擋）；以『未綁定清單』與警示先行，不用模糊比對。
- **假日曆資料來源格式變動**：匯入解析器對欄位名稱容錯，且**預覽 + 驗證**後才寫入。
- **覆寫濫用**：所有覆寫進 `finance_overrides` 與稽核，並每月彙總報表給財務負責人。
- **範圍蔓延**：多幣別明確不做；『更正已生效法定參數』只留介面（新增一列＋原因），追溯更正另案。
