# 管銷分攤 25%（直接毛利）＋「稅後淨利 → 營業利益」設計稿（第 48 班）

> 作者 hichan-ab（node-ab），2026-10-09，桌面作業、唯讀盤點；基底 `origin/train/t47-int` @ c107fd8fd。**本稿不改任何程式。**
> 需求（使用者經 node-d8 轉述，表單裁示）：
> 1. 管銷分攤 = **直接毛利 × 25%**（現行：報價稅前 × 10%，固定）。
> 2. 百分比不固定：**每張報價單可調，預設 25%（全域設定預設值）**；**只有 superadmin 能改**；偏離預設時 UI 要警示，且要稽核。
> 3. 「稅後淨利」→「**營業利益**」（含損益彙總、精算、報表、PDF、獎金用語、**計算**）；「淨利率」→「**營業利益率**」（= 營業利益 ÷ 未稅金額，目標門檻仍 12%：<12 紅、<20 黃、其餘綠）。
>    營業利益 = 直接毛利 − 管銷分攤 − 公益捐款（直接毛利 1%，不為負）− 運輸物流 − 安裝施工 − 差異項 − 保固預估 − 其他費用（= 今天的 `totalIndirect` 同一組）。
> 4. 範圍：**未精算**的報價單／精算用新算法重算；**已精算／結案**保留舊存值（歷史不動）。獎金（`payroll/bonus.py`）跟新定義，影響分析由 b5 做。

---

## 0. 結論先行（給決策者）

1. **只有一處公式、兩種實作的現況必須先收斂**：算式目前**散在 4 處**——`quotation-form.html calcTotals`、`settlement.html calcSummary`（前端算、存檔）、`settlement_actuals._expected_downstream`（後端完結比對）、`settlement_actuals.original_side`（報價端的後備）。再加上 `reports.py` 各處用 `net_margin_pct` 欄位。本題建議新增**單一規則**：`backend/helpers/profit_rules.py`（純函式）＋ `frontend/static/profit-rules.js`（`MotrixProfitRules`），共用一份黃金向量 JSON 做等值測試（照 `legal-round.js` 前例）。
2. **內部鍵名不改**（`adminCost`、`netProfit`、`netMarginPct`、`origNetProfit`、欄位 `net_margin_pct`、`bonus_case_awards.net_profit`）：只改**顯示用語**，避免動到已凍結的精算摘要、獎金快照、報表讀取、守門與 `BASE_FIELD = "netProfit"`。新增鍵：`overheadPct`、`formulaVer`（見 §3）。
3. **「未精算重算」建議用「一次性遷移＋版本戳記」**（§5）：遷移重寫未精算報價單的 `data_json.tot` 與 `net_margin_pct` 欄位，蓋 `formulaVer=2`；已精算／已結案不動（沒有戳記＝舊算法，報表／PDF／精算頁依戳記顯示舊標籤「管銷分攤（報價稅前 10%）」）。
4. **誠實的影響預告**：新舊相等的打平點是「直接毛利率 = 40%」（舊：稅前×10%；新：直毛×25% ⇒ 直毛率×25% = 10% ⇒ 直毛率 40%）。**直毛率 < 40% 的案子營業利益會變高、> 40% 會變低**。多數報價單直毛率若落在 25～40% ⇒ 營業利益**普遍上升**、門檻 12% 的警示會變少。請使用者確認這是預期（Q1）。
5. **必須使用者裁示的題目 9 題**（§10），其中 Q2（直毛為負時管銷是否為 0）、Q4（精算的管銷基數用哪個毛利）、Q5（已核准／已送出的報價單是否重算）會改變數字，最優先。

---

## 1. 盤點（每個檔案／函式／標籤）

> 方法：`rg` 全庫（`backend/ frontend/ docs/`）找「管銷分攤、稅後淨利、淨利、淨利率、net_margin、adminCost、netProfit」。`淨利` 全庫 293 處／65 檔（含測試）。
> **排除（會計報表的「稅後淨利」是另一個概念，不可改）**：`backend/modules/accounting/ledger/{statements,fs_lines,equity,closing,cashflow}.py`、`modules/accounting/api/ledger_reports.py`、`backend/data/account_items_112.json`（「本期稅後淨利(淨損)」是會計科目名稱）、`frontend/pages/ledger-{statements,periods,settings}.html`、`frontend/js/ledger-{periods,settings}.js`，以及其測試 `test_ledger_*`、`test_account_tree_page_*`。守門：改名清單用白名單，並加一題「會計報表仍叫『稅後淨利』」的正對照。

### 1.1 計算（公式本體）——必須收斂到單一規則

| # | 位置 | 現況 | 動作 |
|---|---|---|---|
| C1 | `frontend/pages/quotation-form.html` `calcTotals()` ≈L2461–2486 | `adminCost = halfUp(pretax,0.10)`；`charityDonation = max(0, halfUp(directProfit,0.01))`；`totalIndirect = admin+charity+五項`；`netProfit = directProfit−totalIndirect`；`netMarginPct = netProfit/pretax*100`（1 位小數）；存進 `this.tot` → `data_json.tot` | 改呼叫 `MotrixProfitRules.quote(...)`；`tot` 增 `overheadPct`、`formulaVer` |
| C2 | `frontend/pages/settlement.html` `calcSummary()` ≈L1886–1925 | `adminCost = halfUp(quotedPretax,0.10)`；`netProfit = grossProfit−admin−charity`；`origAdminCost = tot.adminCost ?? halfUp(quotedPretax,0.10)`；`origNetProfit = tot.netProfit ?? (origDirect−origAdmin−origCharity−reserve)` | 改呼叫規則；實際側管銷基數見 Q4；原始側直接用報價單 `tot` 的值（有戳記）|
| C3 | `backend/modules/case/settlement_actuals.py` `_expected_downstream()` L489–512 | 後端重算：`admin = round_half_up(pretax,0.10)`；`net = gross−admin−charity`；`check_finalize` 比對前端送來的數字，超出容差拒絕完結 | 改呼叫 `helpers.profit_rules`；百分比取**伺服器上的報價單**（不信前端）|
| C4 | `settlement_actuals.original_side()` L556–578 | `admin = tot.adminCost ?? round_half_up(pretax,0.10)`（後備 10%）；`net = tot.netProfit ?? direct−admin−charity` | 後備依 `formulaVer`：無戳記＝舊 10%（舊資料）；有戳記用存值 |
| C5 | `settlement_actuals.DOWNSTREAM_KEYS`／`_DOWNSTREAM_NAMES` L483–487 | 錯誤訊息用語：管理費、淨利、淨利率(%) | 只改顯示字；鍵名不動 |
| C6 | `backend/modules/case/api/quotations.py` L1543–1552、L1879–1888 | 存檔時直接取**客戶端送來的** `tot.directMarginPct`／`tot.netMarginPct` 寫入欄位 `direct_margin_pct`／`net_margin_pct`——**伺服器不驗**（現況信任前端）| 新增：存檔時用規則在伺服器重算並**以伺服器值為準**寫欄位（或至少驗證 `overheadPct` 權限＋與 `tot` 不一致時覆寫），見 §3.3 |
| C7 | `modules/analytics/api/reports.py` `_orig_indirect_reserve`/`_reserve_uncovered`（L292–325）| 由 `origIndirectReserve`（完結時凍結）與 `origDirectProfit`、`grossProfit` 推導，不含 10%；對帳式「預留 = totalIndirect − 管銷 − 公益」| 公式不變；但說明文字與報價端 `origIndirectReserve` 的計算（`settlement_actuals` L573 附近 `totalIndirect − admin − charity`）依新管銷自動隨動 |
| C8 | `payroll/bonus.py` `BASE_FIELD="netProfit"`、`base_amount_for()`；`payroll/bonus_case.py`（池 = floor(淨利×比率)）；`bonus_case_awards.net_profit`（db.py L4586，字串快照）| **只讀精算已存的 `summary.netProfit`**，不自己重算（檔頭 §二禁令）| 公式不動；因已精算案保留舊值、未精算案完結時才用新算法，獎金基數自然隨「完結當下的算法」。b5 分析（見 §8）|

### 1.2 顯示用語（標籤）

| 檔案 | 位置／內容 | 動作 |
|---|---|---|
| `quotation-form.html` | L1857「管銷分攤（10%，固定）」；L1912「稅後淨利」；L1922「淨利率」＋「⚠ 低於目標 12%」；L1862「公益捐款（直接毛利 1%）」（不變）| 管銷列改為可調輸入（superadmin）＋偏離警示；兩個標籤改「營業利益」「營業利益率」|
| `settlement.html` | 26 處：L389/914/917「最終淨利／精算後真實淨利」、L968「管理費＝報價×10%；公益＝毛利×1%…」、L1006–1010「管銷（10%）+ 公益（1%）／真實淨利（…%）」、L1071–1092 橋接圖「−管理費 → −公益 → 最終淨利」與 aria 文字、L1401–1408 表格列（未扣費用淨利／管銷分攤（10%）／真實淨利／真實淨利率）、L1527–1528（最終淨利／淨利比、與原始差額（淨利））、L1766 | 全改「營業利益」；管銷列文字依 `formulaVer` 顯示百分比與基數（動態）|
| `case-management.html` | L2713–2715（淨利率 KPI）、L2739/2746/2750/2780/2787/2791（管銷分攤（10%）、原始預估淨利／率、真實淨利／率）、L2804–2805（真實淨利比原始預估高／低）；`js/case-management-fin.js` L56 註解 | 同上 |
| `reports.html` | 30 處（預估／實際／年度淨利率、KPI「精算實際淨利」、客戶交易明細「毛利率（來源 net_margin_pct）」等；對照 `docs/platform/plans/NOTE-REPORT-LABELS-T38.md` 的已裁示清單 A）；`js/reports.js` L372、1027、1094、1177–1207（圖表圖例）| 全改；T38 標籤清單作為檢查表 |
| `analytics/api/reports.py` | 30 處：Excel 欄名（L1399「預估淨利率／實際淨利率／實際淨利」、L1473、L1537–1539「原始淨利率／原始預估淨利／真實淨利率／真實淨利」）、PDF HTML（L1941–1948、2157–2185「管銷分攤（10%）／原始預估淨利／真實淨利…」、2327、2415–2429）、Excel 達成率（L1048–1049「平均淨利率／年度實際淨利」）、KPI（L915）| 全改；管銷列用 `formulaVer` 分流 |
| `pdf_gen.py` | 10 處：L2633–2658（管銷分攤（10%）、原始預估淨利／率、真實淨利／率、比較句）、L2667「預估淨毛利率」、L59 差額拆解註解 | 同上；**結案 PDF 對已精算案要顯示舊版標籤**（不得用新百分比去解讀舊值）|
| `payroll/bonus.py` | L157–160 `BONUS_SETTLEMENT_ROWS`：`("adminCost","管銷分攤（10%）")`、`("netProfit","真實淨利",…"（＝獎金分潤基數）")`、`("netMarginPct","真實淨利率")`；L68–110 錯誤訊息「沒有淨利／淨利是 N」| 改「營業利益」；管銷列依 `summary.formulaVer`/`overheadPct` 動態；**舊格式訊息「沒有淨利欄位…」仍是對 `netProfit` 鍵的檢查，文字改「營業利益」**|
| `payroll/bonus_case.py`、`payroll/api/bonus.py`、`payroll/bonus_pdf.py` L236、`js/bonus.js` L291、`pages/bonus.html` | 「淨利 ≤ 0／淨利必須是數字／真實淨利」等 | 改「營業利益」；`bonus.js` 的 `field==='net_profit'` 鍵不動、只改顯示 |
| `routers/system.py` L1093、`js/cashier.js` L503、`dashboard.py` L192 | 註解 | 隨手改 |
| `helpers/financial_mask.py` | L26 `HISTORY_MONEY_FIELDS` 含歷程欄位名稱「淨利率」；`QUOTATION_MONEY_COLS` 含 `net_margin_pct` | **欄位名稱字串是遮罩白名單**：改標籤必須同步改 L26 與 `quotations.py` L115–116 的歷程欄位標籤（`("tot.netMarginPct","淨利率")`），並保留舊字串一併遮罩（歷史 `editHistory` 內已存舊標籤）⇒ 白名單同時含「淨利率」「營業利益率」|
| `version_manifest.json` | 14 處歷史條目文字 | **不改**（歷史）；新增本班一筆 |

### 1.3 儲存資料（形狀／欄位）

| 資料 | 位置 | 說明 |
|---|---|---|
| `quotations.net_margin_pct`（REAL）、`direct_margin_pct` | db.py L505；報表、儀表板（dashboard.py L41–208）、`reports.py` L357/481/516/545/2828/3119 直接讀 | **未精算案的重算必須連這個欄位一起更新**，否則報表（預估淨利率、加權平均）仍是舊值 |
| `quotations.data_json`：`tot.{adminCost, charityDonation, totalIndirect, netProfit, netMarginPct, directProfit, …}`、`indirectLogistics/Installation/Travel/Warranty/Other` | 報價單前端組、存檔時寫入 | 新增 `q.overheadPct`（輸入）與 `tot.overheadPct`、`tot.formulaVer` |
| `quotations.data_json.settlement.summary.*`：`adminCost`、`charityDonation`、`netProfit`、`netMarginPct`、`origAdminCost`、`origNetProfit`、`origNetMarginPct`、`origIndirectReserve`、`origDirectProfit`、`profitDiff` 等 | 精算完結時凍結（`settlement_api.py` L100–150；`DOWNSTREAM_KEYS`）| 已完結 ＝ 凍結；新增 `summary.overheadPct`、`summary.formulaVer`（完結時蓋）|
| `quotations.settle_status`（''／draft／finalized）、`deal_tag`（''／已成案／已結案）| db.py L515–516；`quote_hot_fields()` | 「已精算／結案」的判準（Q3）|
| `bonus_case_awards.net_profit`（TEXT 快照）、`split_json`、`pool_amount` | db.py L4586 | 已建立的獎金單保留快照，不重算 |
| 歷程 `editHistory`（欄位標籤字串）| `quotations.py` L115–116 標籤表 | 歷史文字不改；新增 `tot.overheadPct` 的標籤「管銷分攤比率」|
| `system_settings` | `helpers/settings._get_setting` | 新增鍵 `overhead_default_pct`（預設 25）|

### 1.4 匯出／文件／測試

- Excel：`reports.py`（欄名見 §1.2）；結案 PDF `pdf_gen.py`；獎金 PDF 結算表 `bonus_pdf.py`（讀 `BONUS_SETTLEMENT_ROWS`）。
- 黃金檔 `backend/tests/golden_case_page_2026_09_24.json`：內含案件頁全文快照（含「管銷分攤（10%）」「真實淨利」「淨利率（淨利 NT$ 0）」等字串）⇒ **標籤改名必然使它變紅，需重產（有等值守門）**。
- 用語帳（wording ledger）：`docs/platform/plans/NOTE-REPORT-LABELS-T38.md`、`USER-DECISIONS.md`、`docs/quick/{mod-quotation,data-model,known-limits,changelog}.md`、`docs/platform/plans/SETTLEMENT-ACTUALS-SPEC.md`（規格要補新算式）、`docs/windows/SPEC-BONUS.md` 等（歷史，不改，另加「第 48 班起」註）。
- 受影響測試（含「淨利／管銷／adminCost／netProfit／net_margin」字樣）：約 **60 個測試檔**，主要群組：`modules/case/tests/test_*settlement*`（約 15 檔，數值斷言 10%）、`modules/analytics/tests/test_{net_not_gross_fallback,original_indirect_reserve,margin_dispatch_absorbed,money_round_half_up,reports_*}`、`modules/payroll/tests/test_{bonus_*,bn1*}`（讀淨利）、`tests/test_{money_round_half_up,case_money_mask,finance_role_split,pdf_closing_dispatch_tax}`。**數值斷言要逐檔人工複核，不可批次替換**（見 §9 風險）。

---

## 2. 單一規則（前後端同一份）

```
quote(items_cost, pretax, inputVat, p, five_items) →
  directProfit  = pretax − totalCost − inputVat
  overheadBase  = max(directProfit, 0)                 # Q2：建議；與公益金「不為負」同款
  overhead      = round_half_up(overheadBase, p/100)   # p 預設 25（%）
  charity       = max(0, round_half_up(directProfit, 0.01))
  totalIndirect = overhead + charity + Σ五項
  operatingProfit = directProfit − totalIndirect
  operatingMarginPct = round1(operatingProfit / pretax * 100)   # pretax>0
settlement(pretax, actualCost, p, …):   同式，directProfit 換成「實際毛利」（Q4）
```

- 實作：`backend/helpers/profit_rules.py`（純函式、無 DB；`round_half_up` 沿用 `helpers.legal_params`）＋ `frontend/static/profit-rules.js`（`MotrixProfitRules`，沿用 `MotrixLegalRound.halfUp`）。
- **等值測試**（前例 `tests/test_money_round_half_up_2026_09_26.py`、`static/legal-round.js`）：`backend/tests/data/profit_rules_vectors.json`（≥ 40 組：含 .5 進位、directProfit 負／0／極小、p = 0/10/25/100、五項為 0 或大、pretax=0）；pytest 直接跑 Python；node 載入 JS 跑同一份（沒有 node ⇒ skip，同前例）。
- **守門（靜態）**：新增 `test_profit_rule_single_source`：掃描 `frontend/**`、`backend/**`（排除規則檔與測試）不得再出現 `halfUp(...,0.10)` 管銷樣式或 `adminCost =` 賦值（允許清單：規則檔）。照 `test_legal_params_single_source` 寫法。
- **版本戳記**：規則檔常數 `FORMULA_VER = 2`（舊＝無戳記或 1：`admin = round_half_up(pretax,0.10)`）。規則檔保留 `legacy_quote()`/`legacy_settlement()`（只給「顯示舊值的重算比對／報表標籤」用，不用來新產生資料）。

## 3. 每張報價單的百分比：資料模型

### 3.1 存放
- **`data_json` 鍵 `overheadPct`（數字，單位 %，0–100，最多 1 位小數）**，不開新欄位：報表只讀 `net_margin_pct`，不需要用百分比篩選；少一個 migration、少一個遷移面。`tot.overheadPct` 回寫一份供下游（精算頁、PDF、報表）直接用，`tot.formulaVer=2`。
- 預設值：`system_settings.overhead_default_pct`（缺鍵＝25）。新建報價單時伺服器把當時預設值蓋進 `overheadPct`（**凍結在單上**：之後全域預設改了，既有單不變；使用者若要整批跟預設走，用 superadmin 工具另案）。
- 複製為新單：沿用來源單的 `overheadPct`？**建議帶「目前全域預設」**（避免舊的特例比率被不知不覺複製）——Q8。

### 3.2 誰能寫（伺服器端，不只 UI）
- `POST/PUT /api/quotations`：把請求 body 的 `overheadPct` 與「該單目前存值（新建＝全域預設）」比較；**不同且 `user.role != 'superadmin'` ⇒ 403「只有最高管理者可調整管銷分攤比率」**（不是靜默覆寫，避免使用者以為存成功）。非法值（非數字、<0、>100、超過 1 位小數）⇒ 422。
- 全域預設：`GET/PUT /api/settings/overhead-default`（PUT＝`require_superadmin`，寫 `_audit("settings.overhead_default.update", old/new)`）；修改只影響之後新建的單。
- 舊 PUT 若 body 沒有 `overheadPct`（舊前端快取）⇒ 視為不變（保留存值）。

### 3.3 伺服器重算（建議納入本題，補現況缺口）
現況伺服器直接信任 `tot`（C6）。建議存檔時 `profit_rules.quote()` 以 `data_json.items`＋`q.indirect*`＋`overheadPct` 重算，**以伺服器值寫 `tot.*` 與 `net_margin_pct/direct_margin_pct` 欄位**；與前端送來的不一致時以伺服器為準（前端立即重新載入顯示）。理由：百分比現在是「可被調的錢相關參數」，若 tot 仍由前端算，改 DevTools 即可繞過 superadmin 限制。風險：items 欄位形狀（`qty/cost/amount`、`discount/freight/taxRate`）的後端重現要與 `calcTotals` 逐項等值（同一份黃金向量涵蓋）。若時程不允許，**最低限度**＝只驗證 `overheadPct` 權限＋偏離預設時伺服器驗算 `adminCost` 容差內一致（Q9）。

### 3.4 稽核
- 任何一次 `overheadPct` 變動（含新建時 superadmin 改離預設）：`_audit("quotation.overhead_pct_change", quote_no, {"old":x,"new":y,"default":25})`；歷程 `editHistory` 新增欄位標籤「管銷分攤比率」。
- 偏離預設的單，報表加旗標欄（營運報表 Excel 增「管銷比率」欄；PDF 只在偏離時印）——Q7（是否要給報表看到）。

## 4. 警示 UX

- 報價單「間接成本」區：管銷列改為「管銷分攤（直接毛利 [25]%）」＋金額。**非 superadmin**：百分比唯讀文字；**superadmin**：小型輸入框。
- 偏離預設（≠ `overhead_default_pct`）：該列變橘底＋行內警示「⚠ 管銷比率已調整為 N%（預設 25%）——將影響營業利益與獎金基數」，並在損益彙總處顯示同一標記；`data-testid="qf-overhead-warning"`。重設按鈕「還原預設」。
- 儲存時若偏離預設：二次確認對話（superadmin 自己改的也要），按下才送出。
- 精算頁／案件頁／PDF 只顯示結果與「（管銷 N%）」；偏離預設時加 ⚠ 圖示（顏色之外附文字，沿用精算頁無障礙慣例）。
- 營業利益率顏色門檻不動：`<12 紅`（⚠ 低於目標 12%）、`<20 黃`、否則綠；文字「營業利益率」。

## 5. 「未精算重算」怎麼做

### 5.1 判準（Q3）
已精算／結案 ＝ `settle_status='finalized'` **或** `deal_tag='已結案'`（任一）。其餘（含草稿精算 `draft`、已成案但未完結、各種簽核狀態的報價單）＝未精算 ⇒ 重算。
> 「重新開啟後再完結」是 superadmin 動作：重新開啟的案件原本有 `formulaVer` 舊戳記；**再完結時是否改用新算法？** 建議：**重新完結即用新算法並蓋新戳記**（因為此時 `check_finalize` 以伺服器目前規則比對，維持舊算法要保留兩套驗證，成本高），且完結理由欄＋稽核已強制（35c）。此點會改變該案獎金基數 ⇒ Q6。

### 5.2 機制比較

| 方案 | 做法 | 優點 | 缺點 |
|---|---|---|---|
| A. 讀取時重算（不寫庫）| 前端／API 讀到無戳記的未精算單就即時用新規則算 | 不遷移 | 報表直接讀欄位 `net_margin_pct`，要全部改成現算（8+ 處 SQL/迴圈）；儀表板篩選／排序無法用欄位；兩邊不一致風險最高 |
| **B. 一次性遷移（建議）**| 核心 migration ＋離線 dry-run 工具：對未精算報價單用 `profit_rules.quote()` 重算 `data_json.tot.*`、`net_margin_pct`，蓋 `formulaVer=2, overheadPct=預設`；寫 `tot._legacy={adminCost,netProfit,netMarginPct,formulaVer:1}` 保留舊值 | 欄位與報表立刻一致；可還原；可對帳 | 需要正式機備份；遷移要冪等（有戳記跳過）；遷移期間不得有人存檔（套用本來就停機）|
| C. 遷移＋開啟時補算 | B ＋ 載入無戳記單時由前端重算並存回 | 補漏 | 兩個入口，易重複 |

**建議 B**，並遵守 `UPGRADE-RUNBOOK`／`feedback` 既有守則：SQL 寫字面值、不呼叫活的程式碼（凍住的歷史不呼叫活的程式碼）⇒ 遷移內**不得 import `profit_rules`**，內嵌一份純 SQL/純 Python 的凍結算式（與規則檔以測試證明等值：遷移內算式 vs 規則檔對黃金向量輸出相同）。

### 5.3 報價單狀態與「已報價／已核准」的單
- 客戶看到的**價格（含稅總額、未稅金額）完全不變**——管銷是內部成本科目，不進報價單對外 PDF（本題盤點 `pdf_gen.py` 對外報價單未列出管銷／淨利列；仍須在實作期以 grep 驗證 `quote` PDF 模板）。
- 影響的是內部「營業利益率」：已送審／已核准的單，其審核當下看到的利潤會與重算後不同。建議：**重算但不重送審、不改狀態**；`tot._legacy` 與稽核紀錄（一筆彙總 `quotation.overhead_recalc_bulk`：件數、前後總和）保留可追溯；簽核頁若顯示利潤，顯示重算後值並標「口徑更新」小註（Q5）。
- 精算草稿（`settlement.status='draft'`，summary 為草稿快照）：精算頁每次載入會重算 summary ⇒ 遷移時**不改草稿 summary**，只改報價單 `tot`（原始側來源）；開啟時前端依規則重算。需實作期驗證 `calcSummary` 載入時確實覆寫草稿（見 §9 開放驗證項 V2）。

## 6. 回滾開關

- `system_settings.overhead_rule_mode`：`v2`（預設）／`legacy`。`legacy` 時規則檔 `quote()/settlement()` 回傳舊式（10% 稅前）——**只影響新算／重算，不回改已遷移資料**。
- 資料還原：遷移前備份 DB（正式機流程已規範：回滾須還原 DB 備份）；另提供 `tools/platform/overhead_rollback.py`（dry-run 預設，`--apply` 需白名單，同 R2 回滾工具作法）：依 `tot._legacy` 把未精算單還原為 `formulaVer=1` 舊值（精算完結後的單不動）。
- 前端：`legacy` 時管銷列恢復「管銷分攤（10%，固定）」唯讀顯示（旗標由 `/api/legal-params`-類唯讀端點或報價單載入 payload 帶 `ruleMode`）。

## 7. 標籤改名策略（不動鍵、動顯示）

- 對照表（單一份）：`frontend/static/profit-labels.js`（`MotrixProfitLabels`）＋ Python 側 `helpers/profit_rules.LABELS`，字串：`netProfit→營業利益`、`netMarginPct→營業利益率`、`origNetProfit→原始預估營業利益`、`adminCost→管銷分攤`（含基數說明由 `formulaVer` 決定）。各頁／匯出引用同一份，之後再改名只改一處。
- 「真實淨利／最終淨利／精算實際淨利／年度實際淨利／淨利比／未扣費用淨利」等變體：**全部改為對應的「營業利益」說法**（建議：真實營業利益、精算後營業利益、年度實際營業利益；`未扣費用淨利` 現指「毛利，尚未扣管理費、公益」⇒ 改「扣費用前（直接毛利）」更準——Q9 一併）。
- 版本分流：`formulaVer<2` 的歷史單，管銷列標籤＝「管銷分攤（報價稅前 10%）」，其餘一律用新稱呼（使用者要求「所有地方改名」）；金額不動。
- 守門：新增 `test_no_legacy_profit_wording`：白名單（會計報表、歷史文件、`version_manifest` 歷史條目、遷移檔）外，`frontend/**`、`backend/**/*.py`（非測試）不得出現「稅後淨利」「真實淨利」「淨利率」「最終淨利」（以及 `管銷分攤（10%`）；正對照：會計報表仍含「稅後淨利」。
- 遮罩白名單同時保留舊/新兩組字串（§1.2 `financial_mask`）。

## 8. 獎金（payroll）銜接（b5 另做影響分析；此處只列介面事實）

- 獎金只讀 `settlement.summary.netProfit` 已存值；已建立的 `bonus_case_awards.net_profit` 是文字快照 ⇒ **已發/已建單不變**。
- 影響面：**尚未完結、尚未建獎金單**的案件，完結時用新算法 ⇒ 獎金基數改變（多數會上升，見 §0.4）；**重新開啟再完結**的案件基數也會變（Q6）。
- `BONUS_SETTLEMENT_ROWS` 與 `bonus_pdf.py` 結算表需帶 `overheadPct`/管銷基數說明，否則 PDF 上「管銷分攤（10%）」會錯。
- b5 需回答：獎金比率是否隨基數上升而要調整（業務問題，Q 之外）；已核准未發放的獎金單是否重算（建議不重算）。

## 9. 測試計畫（含突變檢查）

1. **規則單元＋等值**：`test_profit_rules_vectors`（Python）＋`test_e2e_profit_rules_js_equivalence`（node；無 node ⇒ skip）。突變：把 Python 的 `0.25` 默認改 `0.20`、或 JS 的基數改成 `pretax` ⇒ 兩題之一必紅。
2. **單一來源靜態守門**（§2）。突變：在 `settlement.html` 加一行 `halfUp(quotedPretax, 0.10)` ⇒ 守門紅。
3. **權限**：非 superadmin（admin/sales/engineer/finance/viewer）送 `overheadPct≠存值` ⇒ 403；superadmin ⇒ 200＋稽核一筆；未帶鍵 ⇒ 保留；非法值 422；全域預設端點只允許 superadmin。突變：拿掉伺服器端角色檢查 ⇒ 紅。
4. **伺服器重算**（若納入）：前端送偽造 `tot.netMarginPct=99` ⇒ 欄位被伺服器值覆寫。
5. **遷移**：造 4 類資料（未精算／草稿精算／已完結／已結案）＋舊戳記；跑遷移：前兩類重算（欄位、tot、`_legacy`）、後兩類不動；再跑一次冪等；`overhead_rollback --apply` 還原；dry-run 差異報表對帳（總和 Δ 可手算）。突變：遷移判準少排除「已結案」⇒ 紅。
6. **精算**：`check_finalize` 後端以新規則比對，舊戳記案重新完結走新規則；完結前後 `adminCost/netProfit` 一致；負毛利案（Q2）；零收入。更新 `test_settlement_*`、`test_e2e_settlement_*` 的數值（逐檔人工）。
7. **報表一致**：同一案件在報價單、精算頁、案件頁、報表 KPI、Excel、PDF 的營業利益／率全等（沿用既有一致性測試形狀）；舊戳記案顯示舊標籤＋舊值。
8. **獎金**：b5。至少一題：已完結舊案 `base_amount_for` 取舊 `netProfit` 不變。
9. **標籤守門**（§7）＋黃金檔 `golden_case_page_2026_09_24.json` 重產（等值守門自帶）；會計報表「稅後淨利」正對照。
10. **UX e2e**：superadmin 改比率 ⇒ 警示出現＋二次確認；非 superadmin 看不到輸入框；還原預設。
11. 單檔輕量為主；`modules/case`、`analytics`、`payroll` 三組全量由列車跑（底層公式改動 ⇒ 全量）。

**開放驗證項（實作時先證實，本稿未證實）**：V1 對外報價單 PDF 模板不含管銷／淨利列；V2 精算頁載入時是否一律重算 summary（影響草稿處理）；V3（已證實）全庫非測試程式中管銷 10% 字面值只有 5 處：`quotation-form.html:2471`、`settlement.html:1886,1893`、`settlement_actuals.py:503,567`；`reports.py`/`dashboard.py` 沒有以 10% 反推的硬編碼；V4 簽核頁/佇列是否顯示淨利；V5 `quotes` 的 Excel/CSV 匯出是否含 `netMarginPct`（`reports.py` 以外）。

## 10. 風險

1. **數值普遍改變**（§0.4）：門檻 12%、獎金基數、年度目標達成率都會變；需使用者知悉（上線備註列「財務口徑變更」）。
2. **雙實作漂移**：若只改畫面不抽規則，前後端會再分岔（現況就有 4 處）。故規則抽取是本題的前置，不是優化。
3. **遷移面**：重寫大量報價單的 `data_json`；必須備份、冪等、dry-run、可還原；遷移不得依賴活程式碼。
4. **歷史一致性**：舊標籤＋舊值的案件與新案並存，報表加總（平均淨利率、年度實際）會混兩種口徑——報表需顯示「口徑混合」註記，或提供篩選（Q10）。
5. **測試大面積改數值**：約 60 檔，批次取代會造成假綠燈（斷言自己改的值）⇒ 逐檔複核＋突變檢查。
6. **權限繞過**：若不做伺服器重算，比率可由前端 tot 偽造（現況信任前端）。
7. **遮罩白名單**：改標籤若漏改 `financial_mask`/歷程標籤，會讓「營業利益率」在歷程裡洩漏給無金額權限者。
8. **重新開啟再完結改變獎金基數**（Q6）。
9. **名稱衝突**：與會計報表「稅後淨利」並存；改名守門要白名單。

## 11. 待使用者裁示（每題一個決定，附建議）

| Q | 題目 | 建議 |
|---|---|---|
| Q1 | 確認影響方向：直毛率 < 40% 的案子營業利益上升、> 40% 下降（打平 40%）。是否預期？ | 預期，照做；上線備註列出 |
| Q2 | 直接毛利為負（虧損案）時管銷分攤？ | 以 0 計（與公益金一致，不產生負管銷）|
| Q3 | 「已精算／結案」判準：`settle_status=finalized` 或 `deal_tag=已結案` 任一？ | 任一 |
| Q4 | 精算的管銷基數：用「精算實際毛利」（pretax−實際總成本）還是沿用報價端「直接毛利」？ | 精算實際毛利（與報價端同定義：該側的直接毛利）；百分比取報價單存值 |
| Q5 | 已核准／已送出的未精算報價單是否一併重算？是否需通知業務/簽核人？ | 重算、不重送審、不改狀態、遷移後在案件頁顯示「口徑更新」註記 |
| Q6 | 已完結案「重新開啟再完結」是否改用新算法（獎金基數會變）？ | 改用新算法並蓋新戳記（理由欄＋稽核已強制）；或禁止、要求另案 |
| Q7 | 偏離預設的比率是否要在營運報表／Excel 顯示欄位？ | PDF 只在偏離時印；Excel 增「管銷比率」欄 |
| Q8 | 「複製為新單」帶來源單比率還是全域預設？ | 全域預設 |
| Q9 | 是否納入「伺服器重算 tot/欄位」（§3.3）？標籤「未扣費用淨利」改為「扣費用前（直接毛利）」？ | 納入（補現況信任前端的缺口）；標籤照建議改 |
| Q10 | 報表加總混合新舊口徑時的處理：加註記？提供口徑篩選？ | 加註記；不做篩選（本班）|

---

## 附：建議實作切分（供排班）

1. S1 規則抽取（`profit_rules.py`＋`profit-rules.js`＋黃金向量＋單一來源守門）——**零行為變更**（仍 10%），先併；
2. S2 資料模型＋權限＋稽核＋全域預設端點＋伺服器重算；
3. S3 UI（報價單輸入／警示／二次確認）＋精算／案件頁／報表／PDF 顯示（含 `formulaVer` 分流）；
4. S4 標籤改名（對照表＋守門＋黃金檔）；
5. S5 遷移＋dry-run＋回滾工具；
6. S6 獎金（b5）與測試數值複核。
S1 先上線不影響任何數字，可降低 S2–S5 的風險。
