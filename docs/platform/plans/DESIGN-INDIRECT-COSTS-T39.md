# 設計：報價「間接成本五項」與精算（第 39 班項目 1）

2026-10-04｜rev-7f｜基準 `origin/platform` @ `f3d2dd65`（含第 38 班）｜只讀碼＋手算，未跑任何程式。

使用者裁示（經 PM 轉述）：「照建議做，間接成本五項預設為0，由請購、採購單帶入，已經有管銷分攤」。

## 0. 結論（一段）

**精算的「實際」側今天就已經是裁示的樣子，不需要改金額。** 實際成本從不讀報價的五項（`indirectLogistics／Installation／Travel／Warranty／Other`；精算程式碼裡只有一行註解提到它們），預設就是 0；真正發生的運費、安裝、差旅等，只要有採購單／額外支出／材料申請，就已經進 `totalActualCost`（未連品項者在 `extraTotal`、未對應材料申請在 `materialUnassignedTotal`）。**真正的缺口在「原始側」**：報價的 `tot.netProfit` 已扣掉這五項（`quotation-form.html:2472-2476`），精算頁與營運報表拿它當「原始淨利／預估淨利率」，卻沒有任何一列把這五項列出來，也沒有人說明「實際側只扣單據」。結果：報價預留 5,000 的運費、實際沒有單據時，畫面會顯示「比原始多賺 5,000」，但那 5,000 只是「預留沒發生／沒登錄」，不是真的省下。建議**最小做法＝不動任何金額，只在原始側補一列「報價預留間接成本」並把差額拆開說明**，另可選做「類別→間接成本桶」的顯示分組。獎金基數（`summary.netProfit`）**不受影響**。

## 1. 單據有沒有能對應五個桶的類別？

| 單據 | 類別來源 | 能對應？ |
|---|---|---|
| 舊版額外支出（`kind=''`） | 固定清單 `CATEGORIES = 工時／材料／差旅／運費／安裝／外包／其他`（`api/case_extra_expenses.py:87`） | **大致可**：運費→Logistics、安裝→Installation、差旅→Travel、其他→Other；**沒有「保固」**；工時／材料／外包是直接成本不屬於五項 |
| 費用單據（`kind` ∈ 採購單 `purchase_order`／差旅 `travel`／零用金 `petty_cash`） | **每一明細列**的 `category`（或 `categoryName`），值來自公司的費用類別目錄 `expense_categories`（`helpers/expense_type_defs/*.json` 的 `optionsFrom`；目錄屬 **accounting 模組**，`0003_dims_and_categories.py`，**無預設資料**，由會計設定） | **可**，但目錄是會計維護的自由資料，名稱不固定；對應表要另存（見 §4） |
| 請購單（`purchase_req`） | 同上 | 只是核准文件：`payable_sql` 排除它（`expense_forms.py:37-41`），**不進任何成本**；採購單以 `data.fromPr` 引用已核准請購單（`purchase_items.py:234`） |
| 材料申請（`caseRecord.materialOrders`） | 無費用類別，只有品名／品項連結 | 不適用（材料，非間接成本） |

要點：用戶說的「由請購、採購單帶入」＝**採購單才是金額來源**（請購單本身不入帳）。若希望「已請購、尚未開採購單」也顯示，要另做提示（§5 決策 3）。

## 2. 這些單據今天有沒有算進精算？（附手算範例）

有。`compute()` 以 `R.extra_entries(conn, "accrual", quote_no=…)` 取全部已核准／審核中的額外支出與費用單據列：**連到品項的採購單列**進該品項（規則 A）、**其餘**進 `extraTotal`（可再用沖銷對應到品項）；材料申請未連採購單者進 `materialUnassignedTotal`。`totalActualCost` ＝ 品項實際＋未採用採購＋`extraTotal`＋未對應材料＋手續費＋自訂支出＋派發（`settlement_actuals.py` `compute` 末段）。**沒有任何地方讀報價的五項。**

範例（稅前收入 100,000；品項 Σqty×cost＝60,000；`inputVat`＝3,000；管理費 10%＝10,000；公益金 1%）：

| | 報價（原始） | 實際：**沒有**運費單據 | 實際：有一張運費 5,000 的額外支出（類別「運費」、已核准、未連品項） |
|---|---|---|---|
| 直接毛利 | 37,000（100,000−60,000−3,000） | 37,000（品項估計 63,000） | 32,000（總成本 63,000＋5,000） |
| 管理費 | 10,000 | 10,000 | 10,000 |
| 公益金（毛利×1%） | 370 | 370 | 320 |
| **報價預留間接成本（運費 5,000）** | **−5,000**（含在 `tot.totalIndirect`＝15,370） | **0（沒有這一列）** | 已在總成本內（上方 5,000） |
| **淨利** | **21,630** | **26,630** | **21,680** |
| 與原始差額 | — | **＋5,000（假的「多賺」）** | ＋50（只剩公益金差） |

即：有單據時兩邊**已經可比**（差 50 只是公益金 1% 跟著毛利走）；沒有單據時，差額被「報價預留的 5,000」灌水。這就是會計發現的「少算間接成本」的實際來源——**不是實際側漏算單據，而是原始側比實際側多扣一塊且沒說明**。

## 3. 原始淨利在哪裡扣五項？是否蘋果對橘子？

- 報價單 `calcTotals()`（`quotation-form.html:2468-2476`）：`directProfit = pretax − totalCost − inputVat`；`totalIndirect = adminCost + charityDonation + 五項`；`netProfit = directProfit − totalIndirect`。
- 精算頁 `calcSummary()` 原始側（`settlement.html` 約 1730-1760）：`origDirectProfit = tot.directProfit`（**不含**五項）、`origAdminCost = tot.adminCost`、`origCharity = tot.charityDonation`、`origNetProfit = tot.netProfit`（**含**五項）。第 38b 班起伺服器的 `original_side()` 也是同一組（`settlement_actuals.py`）。
- 結果：精算頁 `totalsBlocks` 的原始欄 `毛利 − 管銷 − 公益 ≠ 淨利`（差五項），而「精算後」欄 `毛利 − 管銷 − 公益 ＝ 淨利`。**兩欄的列不對稱，原始欄的加總看不出來。**
- 營運報表 `reports.py:431-440` 註解寫「與報價單 `net_margin_pct` 同口徑（淨利）… apples-to-apples」：`quotations.net_margin_pct` 欄＝`tot.netMarginPct`（含五項）。只有在實際單據已涵蓋這些間接成本時才可比；沒有單據時預估淨利率被壓低約 `五項合計 ÷ 稅前`（本例 5 個百分點）。**該註解對沒有單據的案件不成立。**

## 4. 最小設計

**原則：實際側不動（已符合裁示）；只補原始側的可見性。** 不改任何既有金額，已完結案不重算。

1. **原始側補一列「報價預留間接成本」**（資訊列）
   - 值：`tot.totalIndirect − tot.adminCost − tot.charityDonation`（舊報價缺 `totalIndirect` 時退回 0 並標「未記錄」；`original_side()` 新增鍵 `origIndirectReserve`，隨完結 summary 凍結，缺鍵＝舊案不顯示）。
   - 精算頁：`totalsBlocks` 第 ②「扣管理費／公益後」區塊在原始欄加一列「報價預留間接成本（運費／安裝／差旅／保固／其他）」，精算後欄顯示「0（以單據為準，已含於實際總成本）」；讓原始欄加得起來。
   - 「與原始差額」下方加一行拆解：`淨利差額 ＝ 預留未發生 X ＋ 其他 Y`（X＝`origIndirectReserve − 精算後已入帳的間接成本單據`，見 3；Y＝其餘）。
2. **文字更正**：`reports.py` 該註解與報表「預估淨利率」欄說明改為「預估含報價預留間接成本；實際只含單據」；PDF／Excel 的利潤分析明細在原始側加同一列。
3. **（選做，顯示用）間接成本明細：把單據類別對應到五個桶**
   - 對應表：案件模組自己存一份（`case_indirect_bucket_map`：類別代碼／名稱 → `logistics｜installation｜travel｜warranty｜other｜（空＝不屬間接）`），預設給舊清單：運費、安裝、差旅、其他；其餘不分類。不從 accounting 讀 `expense_categories`（L2 不可互相 import；只能由設定頁選代碼）。
   - 只對**未連品項、也未沖銷到品項**的額外支出列做分桶（連到品項／沖銷後的列是直接成本，不顯示為間接）；材料申請不分。精算頁在「額外支出」分頁旁顯示小計「其中屬間接成本：運費 X、差旅 Y…」，**純顯示，不改任何總額**。
   - 風險：同一類別（如「運費」）可能是材料運費（直接）也可能是專案運費（間接）；對應表是整類別，會有誤分——所以只當顯示、且可關。
4. **不做**：把報價五項帶進實際（裁示明說不要）；改 `tot`／報價表單；改 `summary.netProfit` 公式。

**要改的檔**（1＋2 為必做；3 選做）：
`backend/modules/case/settlement_actuals.py`（`original_side()` 加 `origIndirectReserve`）、`frontend/pages/settlement.html`（`totalsBlocks` 原始欄列、差額拆解）、`backend/pdf_gen.py` 與 `backend/modules/analytics/api/reports.py`（結案 PDF／利潤分析原始側列、註解）、`backend/modules/payroll/bonus_pdf.py`（獎金精算明細**不動 11 列標籤**，只在原始側無此表，故不必改）、`docs/platform/plans/SETTLEMENT-ACTUALS-SPEC.md`（口徑說明）、各模組 CHANGELOG／manifest。選做 3：`case` 新設定表＋設定頁、`api/settlement_actuals.py` 回傳分桶。

**風險**：獎金基數＝0 影響（只加資訊列，不改 `netProfit`）。舊完結案缺新鍵 ⇒ 不顯示該列（逐位不變）。已報價案 `tot.totalIndirect` 都有（`calcTotals` 一直在算），缺值只會是更早期資料。顯示差額拆解時要避免與公益金 1% 的連動被誤讀（拆解只用預留額，不重算）。

**測試**：
- 單元：`original_side()` 對 `tot` 含／不含 `totalIndirect` 的 `origIndirectReserve`；完結 summary 凍結；舊 summary 缺鍵時各讀者（pdf／reports／頁面）輸出與現況逐位相同。
- 守恆：範例的三個欄（無單據／有單據）淨利 21,630／26,630／21,680 固定為回歸題；確認 `summary.netProfit` 在加列前後不變（獎金基數不動的守門）。
- e2e（選）：原始欄「毛利−管銷−公益−預留＝淨利」加得起來；差額拆解數字。
- 若做選配 3：分桶只含未連品項未沖銷的列、關閉設定後畫面與現況相同。

**工作量**：1＋2＝S–M（約 0.5–1 班）；3＝M（再 1 班）。

## 5. 需使用者裁示

1. **原始側怎麼處理五項？**
   - ⒜ **補一列資訊並拆解差額（建議）**：原始淨利維持報價值（含預留），不改任何數字，說明清楚。
   - ⒝ 原始側改成不含五項（`原始淨利＝直接毛利−管銷−公益`），報價預留另列為資訊——「原始 vs 實際」直接可比，但**精算頁與報表的「原始／預估淨利」會與報價單上的淨利不同**，歷史比較要重算或標註。
   - ⒞ 維持現狀、只補文字說明。
2. **要不要做「間接成本明細」類別分桶（顯示用）？** ⒜ 這班做 ⒝ 下一班再做（建議，先看 1 的效果）⒞ 不做。
3. **「已請購、尚未開採購單」要不要顯示？** ⒜ 不顯示（現況：請購單不入帳）⒝ 在精算頁列為「已請購未採購（金額 X，不計成本）」的提醒 ⒞ 計入成本（承諾口徑；**會改變成本與獎金基數，不建議**）。

## 6. 查證限制
- 手算與讀碼為主，沒跑測試、沒讀正式機資料；`expense_categories` 實際內容（正式機有沒有「運費」「安裝」等代碼）**未查**，分桶預設表需先看正式機的類別目錄。
- `settlement.html` 的原始側行號以約略標示；第 38b 班 `original_side()` 已與頁面 `calcSummary` 同式（上一份複審已核對）。
