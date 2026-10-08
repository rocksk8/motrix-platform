# 管銷分攤 25%（直接毛利）→ 獎金影響分析（第 48 班）

作者：b5（桌面／唯讀分析；基底 `origin/train/t47-int` c107fd8fd）。需求來源：node-d8 轉述使用者（管銷分攤 10%×稅前 → 25%×直接毛利；「稅後淨利」→「營業利益」；淨利率→營業利益率，門檻仍 12%；未完結重算、已完結／結案保留舊值；獎金跟新定義）。總體設計由 ab 負責，本檔只回答「獎金受什麼影響、哪裡要改、哪些測試釘舊數字」。

## 0. 結論（先看這段）
1. **獎金本身不重算任何係數**：獎金基數＝`settlement.summary.netProfit` 的**已存值**（`payroll/bonus.py::BASE_FIELD`、`api/bonus.py::_net_profit_or_error`）。10% 只在**產生那個已存值的地方**進入。所以「獎金跟新定義」＝**精算存檔算式改了，獎金自動跟**；獎金程式碼只有顯示文字要改。
2. **建立獎金要求精算 `finalized`**（`_net_profit_or_error`）⇒ 依「已完結保留舊值」，**既有獎金單與可建立的獎金基數不會因上線而變**（情境 A：差額 0）。
3. **真正的曝險＝重新開啟再完結**：已完結精算被「重新開啟」後再完結，伺服器 `fill_downstream` 會用**新式**覆蓋所有下游欄位 ⇒ `netProfit` 變新值 ⇒ 若該案獎金單仍在草稿／待審核，下一次按「儲存」（`PUT`，`api/bonus.py` ~2105–2175）會把 `net_profit` 重讀成新值、重算獎金池與每人金額（待發放以後不可改，不受影響）。
4. **方向**：新式管銷＝0.25×毛利，舊式＝0.10×稅前；毛利率 <40% 時新式**較小** ⇒ 營業利益**變大** ⇒ 獎金池變大（毛利率 >40% 反之）。一般工程案毛利率多在 40% 以下 ⇒ **多數案件獎金會增加**，請使用者知情。
5. **必須先裁示的規則缺口**見 §6（毛利為負時管銷怎麼算、新舊口徑標記、12% 門檻比的是誰）。

## 1. 現況：獎金用到哪些欄位與算式
```
精算頁（settlement.html calcSummary ~1886）／伺服器 settlement_actuals._expected_downstream（~503）同式：
  adminCost       = round_half_up(quotedPretax, 0.10)          ← 10% 唯一進入點（精算側）
  charityDonation = max(0, round_half_up(grossProfit, 0.01))   ← 完結後凍結（frz.charityDonation）
  netProfit       = grossProfit − adminCost − charityDonation  ← 獎金基數
  netMarginPct    = netProfit / quotedPretax × 100
報價單側（quotation-form.html ~2471，存進 data_json.tot 與 quotations.net_margin_pct）：
  adminCost = round_half_up(pretax, 0.10)；totalIndirect = adminCost + 公益 + 運費/安裝/差旅/保固/其他；
  netProfit = directProfit − totalIndirect；介面 netMarginPct<12 ⇒「⚠ 低於目標 12%」（1923–1924）
```
- **新版案件獎金**（`bonus_case_awards`）：`pool = floor(net × rate_bp/10000)`；`net_profit` 以字串快照；類別／個人金額見 `payroll/bonus_case.py::allocate`。比率 10%（1000bp）是**獎金比率，與管銷 10% 無關**，不可跟著改。
- **舊版模板獎金**（`bonus_awards`）：`base_amount`＝`netProfit`，`base_source` 凍進每筆；每人＝`floor(floor(base×total_pct/10000)×person_pct/10000)`。
- 後端讀 `netProfit` 的其他消費者（跟著變）：`analytics/api/reports.py`（營運報表、`actualIsGross` 舊精算退回毛利）、`dashboard.py`（用 `quotations.net_margin_pct` 欄位與 summary.netProfit）、`pdf_gen.py`（結案 PDF 2612–2651）、`helpers/financial_mask.py`（`net_margin_pct` 遮罩欄）。

## 2. 影響報告工具（唯讀）
`tools/platform/overhead_impact_report.py --db <檔> [--rate 0.25] [--top N] [--csv 檔]`：以 `file:…?mode=ro` 開檔（寫入會失敗）、檔案不存在拒絕（`_dbbind.require_file`）、`--csv` 不可等於 `--db`。逐案列舊／新營業利益、差額、已完結旗標、來源（精算 summary 或報價 tot）；獎金列出舊／新金額（情境 A 差額必為 0；情境 B＝重新開啟再完結的曝險）。
**開發庫實測（2026-10-09）**：`D:\MOTRIX-PLATFORM\backend\motrix_erp.db` **沒有任何資料**（quotations／bonus 各 0 筆、users 0、user_version 0；只有空 schema），所以報告為 0 筆，**沒有可信的數字可報**。工具以我手造的 3 案＋1 張獎金單的合成庫驗過（不是真資料）：完結案舊 197,000→新 222,000，獎金 9,850→11,100（情境 B）；跑完前後開發庫 md5 不變。**要數字請對正式機庫的複本跑**（使用者在正式機執行或給複本）。

## 3. 獎金相關「必須改」的程式
| # | 位置 | 要改什麼 |
|---|---|---|
| 1 | `settlement_actuals._expected_downstream`（~503）＋`original_side`（~567）＋`fill_downstream` | 新式 `admin = round_half_up(max(0,gross)×rate)`；**完結檢核 `_check_downstream` 用同式**，否則頁面與伺服器不一致 ⇒ 409「完結前系統重算的數字與畫面不一致」。`rate` 取該案可由最高管理者個別覆寫的值（需求），要隨 summary 凍結（新增 `adminRate`／口徑標記）。 |
| 2 | `settlement.html` calcSummary（~1886、1893 origAdminCost、1404/1006/1527 文字） | 同上；標籤「管銷分攤（10%）」改「管銷分攤（毛利×25%）」；「真實淨利」→「營業利益」。 |
| 3 | `payroll/bonus.py` `SETTLEMENT_ROWS`（管銷分攤（10%）、公益捐款（1%）、真實淨利＋「（＝獎金分潤基數）」、真實淨利率） | 改文字；**管銷列標籤不可寫死比率**（每案可不同）⇒ 改成「管銷分攤」＋由 summary 帶出的比率顯示，或標籤隨 `adminRate` 組。`bonus_pdf.py`、`bonus.html`/`bonus.js` 的 `bn-settle` 同源（唯一一份定義）。 |
| 4 | `BASE_FIELD = "netProfit"` | **建議鍵名不改**（改鍵＝全庫 summary 搬遷＋獎金／報表／PDF 全跟著動，風險大且沒有收益）；只改顯示名「營業利益」。若 ab 決定改鍵，須同時維護舊鍵讀取（`LEGACY_SETTLEMENT_MESSAGE` 邏輯：缺鍵＝拒絕）。 |
| 5 | `LEGACY_SETTLEMENT_MESSAGE`／`_net_profit_or_error` 訊息中的「淨利」 | 文字改「營業利益」（拒絕訊息是使用者唯一看得到的說明）。 |
| 6 | 新舊口徑辨識 | 完結 summary 需有口徑標記（現有 `dispatchBasis` 同型）以分辨「10% 舊式」與「25% 新式」；否則重新開啟再完結後，報表／PDF 的「原始 vs 精算」差異（`profitDiff`、`origNetProfit`）會拿舊報價 tot（10%）去比新精算（25%）而失真。 |
| 7 | 報價單 `tot`／`quotations.net_margin_pct` | 「未完結重算」：報價側也要新式（quotation-form ~2471），且**已存的未完結報價**的 `tot.netProfit`／`net_margin_pct` 欄位要重算（遷移或讀取時算）；否則儀表板／報表（讀欄位）與精算頁不一致。已成交且已完結者保留。 |
| 8 | 12% 門檻（quotation-form 1919–1924） | 比的值改為營業利益率；常數 12 不變。 |

不需要改：`bonus_case.allocate`／`pool_amount`／`split_award`（吃的是基數）、獎金比率 10%、傳票分錄邏輯、簽核流程。

## 4. 會釘舊數字／舊文字的測試（需改或補，依搜尋；未逐一執行）
- 管銷 10%、`round_half_up(pretax, 0.10)`、完結檢核：`case/tests/test_settlement_t38_be`、`t39_be`、`t40_be`、`test_settlement_finalize_integrity`、`test_settlement_dispatch_offset`、`test_settlement_export_breakdown`、`test_e2e_settlement_t38_fe`／`_zero_and_loss`／`_tax_basis`／`_dispatch_offset`、`tests/test_money_round_half_up`（及 analytics 同名）。
- 獎金：`payroll/tests/test_bn11_bonus_pdf_settlement_table`（**逐字釘 `管銷分攤（10%）`／`公益捐款（1%）`／`真實淨利`／`真實淨利率` 標籤；兩邊文字一致守門**）、`test_bn12_award_preview_and_recall`（`"真實淨利" in html`）、`test_bn10_award_detail`、`test_bonus_award_2026_09_23`（docstring 與斷言引用 `settlement.html:946 … 0.10`）、`test_bonus_settlement_preview`（刻意存非 10% 值，驗「讀已存值不重算」——**這條要保留，它正是守住「獎金不自己算」**）。
- 報表／儀表板：`analytics/tests/test_net_not_gross_fallback_2026_10_04`、`test_original_indirect_reserve_2026_10_05`、`test_margin_dispatch_absorbed_2026_10_04`、`test_reports_logic_fixes_2026_08_28`、`test_dashboard_*`；`pdf_gen`：`tests/test_pdf_closing_dispatch_tax_2026_10_04`。
- 頁面：`backend/tests/golden_case_page_2026_09_24.json`（案件頁黃金錄製，若案件頁顯示淨利）、報價單相關 e2e（`quote_*`、`copy_to_new`）含「稅後淨利」「12%」文字。
- 新增建議：①獎金在新式精算下的端到端（完結→建單→重新開啟→再完結→草稿單儲存後基數跟新值、待發放不可改）；②已完結舊 summary（無口徑標記）仍可建獎金單且數字不變；③毛利為負時管銷＝0 或依裁示。

## 5. 數字影響的預期（無真實資料，僅算式）
管銷 `0.25×G` vs `0.10×P`（G 毛利、P 稅前）：毛利率 G/P＝40% 時相等；30% ⇒ 管銷 7.5%P（比舊少 2.5%P）；20% ⇒ 5%P（少 5%P）。營業利益率提高幅度＝`0.10 − 0.25×毛利率`（毛利率 <40% 為正）。可能由「<12% 低於目標」翻成「達標」的案件會增加；毛利率 >40% 的案件反向、淨利會降。

## 6. 需要使用者／ab 裁示的缺口
1. **毛利為負（或 0）時管銷**：0.25×負數＝負管銷（會讓營業利益變好，不合理）。建議 `max(0, 毛利)×rate`（與公益同下限 0）。工具以此假設計算。
2. **每案管銷係數可由最高管理者覆寫**：覆寫值要隨 summary 凍結並稽核；獎金顯示表標籤不可寫死 25%。覆寫後獎金單（草稿／待審核）是否自動重算（目前「儲存」才重讀）？建議維持「儲存時重讀」，不新增自動連動。
3. **「其他間接成本」**：需求式含「其他間接成本」。精算「實際」側現在不扣報價預留（只顯示 `origIndirectReserve` 資訊列）；若新式要在**精算側**也扣其他間接成本，則營業利益會再降、獎金基數隨之變小，且需定義實際值來源。請 ab 明確：精算側是否扣、扣什麼。
4. **「未完結」界定**：以 `settlement.status != finalized` 為準；報價成交但尚未開精算者只有報價 tot（需求的「重算」要不要動報價已核准單上的數字與列印出的報價單？報價單對客戶不含這些，應只影響內部欄位）。
5. **既有已完結案「重新開啟」**：開啟後再完結即套新式（獎金跟變）。是否要在重新開啟時提示「此案舊值將被新管銷式取代，獎金單草稿會隨之改變」，建議要。
6. **上線備註**：已完結案舊值保留靠口徑標記＋不批次改寫；**不寫 migration 改既有 summary**。
