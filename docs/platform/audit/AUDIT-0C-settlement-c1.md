# AUDIT-0C — 精算 35c（稅基 B＋已對應顯示）獨立稽核（C1；C2 完結重算另審）

- 對象：`origin/wip/t35c-settle-assigned` @`55242226`（顯示 `b6ff69be`／`c43d34e8`、登記 `7702591d`、稅基 B `7bc1c23a`、CHANGELOG `55242226`），對 `origin/platform` @`5d76b528`。稽核者 hichan-0c，2026-10-03。唯讀；只用 dev 測試庫與 Playwright 合成資料。
- 方法：讀碼＋沿用 settlement-recon 的獨立探針在**基準與 C1 兩棵樹各跑一次**（同夾具）＋自寫 e2e 探針（基準／C1 同跑，輸出頁面文字與計算樣式）＋作者自己的 55 題（單程序）。探針未入庫、已刪。

## 結論

**MUST-FIX 1 項（顯示，僅深色主題）；金額與口徑部分全部 PASS。** 作者的 55 題全綠（精算稅基／已對應欄位／成本彙總／端點／報表過期比對／3 個 e2e 檔）。

| 級別 | # | 內容 |
|---|---|---|
| **must-fix** | M1 | 深色主題下「已對應」列幾乎讀不到字（單據、類型、金額對比 **1.25:1**）。淺色主題正常 |
| should-fix／確認 | S1 | 舊完結案在精算頁**數字逐位相同**，但多了 1 個欄位標題改字＋2 行說明（非「逐位元組相同」）；請確認是預期 |
| documented-by-design | D1–D3 | 報表總計混合新舊口徑；舊頁面完結仍落舊口徑；完結驗證仍未涵蓋派發（C2） |

## 1. 對帳重跑（S1–S8 基準 vs C1；單位元）

「精算」＝`totalActualCost`；「報表(權)」＝營運報表月支出權責口徑該案合計；GL＝總帳事件 `COST_PROJECT` 借方；TB＝過帳後試算表 5811。

| 情境 | 精算 基準→C1 | 報表(權) 基準→C1 | GL 基準→C1 | TB 5811 基準→C1 |
|---|---|---|---|---|
| S1 PO＋材料＋額外支出 | 4550 → 4550 | 4550 → 4550 | 4550 → 4550 | 4550 → 4550 |
| **S2 ＝S1＋承攬商 未稅10000／稅5%／人員2000** | **17050 → 16550** | 16550 → 16550 | 14550 → 14550 | 14550 → 14550 |
| S3 品項 b 無採購（估計 525） | 3525 → 3525 | 3000 → 3000 | 3000 → 3000 | 3000 → 3000 |
| S4 草稿 400＋已作廢 300 | 4550 → 4550 | 4550 → 4550 | 4550 → 4550 | 4550 → 4550 |
| S5 offset X→b、b 手填 700 不採用（D8） | 4200 → 4200 | 4550 → 4550 | 4550 → 4550 | 4550 → 4550 |
| S6 完結（凍結 4550）後再核准 PO＋200 | 4550 → 4550（凍結） | 4750 → 4750 | 4750 → 4750 | 4750 → 4750 |
| S8 第二張 PO 已付款含手續費 15 | 4765 → 4765 | 4765 → 4765 | 4750 → 4750 | 4750 → 4750 |

- **S2 在 C1：精算 16550 ＝ 營運報表權責 16550**；GL E04 ＝ 借 專案成本 10000＋借 進項稅額(1268) 500＋貸 應付帳款 10500（`gl.cost 14550 / input_tax 500 / ap 15050`；試算表 5811 14550、1268 500、2171 貸 15050）。C1 回傳 `dispatchTotal 12000`、`dispatchReport 12000`、`dispatchGrandTotal 12500`、`dispatchTax 500`、`dispatchBasis 'pretax'`，恆等式 12500＝12000＋500 成立。其餘情境逐位不變。報表(權)、GL、TB 在 C1 與基準完全相同（C1 沒動它們）。
- 數字型品項 id（S9：品項 id `7`／`8`；PO 連 7、材料 N 連 8、X 以 offset 對應到 7）：品項 7 實際 3250（PO 3000＋offset 250，`assignedBy=offset`）、品項 8 實際 800、未對應 0 ⇒ 正確。半捨入重算與前次稽核一致（53／105／74）。
- 偽造完結（S7）在 C1 仍回 200（派發 live 12000、summary 偽造 0）——**完結重算屬 C2，尚未寫**，本次不審。

## 2. 讀者盤點（作者清單 12 處；我獨立 grep）

方法：全樹（py／js／html／ps1／json，排除測試與文件）搜 `dispatchTotal|dispatchGrandTotal|dispatchReport|dispatchBasis|dispatchTax|grandTotal|totalActualCost|netProfit|itemActualTotal` 與 `dispatchTotalCost*`。**沒有找到作者漏掉的「精算派發成本」讀者**；結果如下。

| 讀者 | 讀什麼 | C1 後行為 |
|---|---|---|
| `settlement.html`（顯示、`calcSummary`、`dispatchStale`、`dispatchSplitText`） | 現算＋凍結 `dispatchTotal` | 新稿未稅；舊完結含稅（`dispatchBasisOld()`）；過期比對口徑配對 ✔ |
| `case-management-dispatch.js` `dispatchTotalCost*`／`financeDispatchStale` | 現算 | 未稅；過期比對配對 ✔ |
| `case-management.html` 外包總成本 KPI、財務分頁「精算結果」表（讀凍結 `dispatchTotal`） | 現算／凍結 | 凍結值照顯示，舊案不變 ✔（見 S1：案件頁文字逐項相同） |
| `analytics/reports.py` 過期迴圈、毛利頁（`itemActualTotal`／`totalActualCost`／`netProfit` 加總） | 凍結 summary | 口徑配對 ✔；**加總混合新舊口徑**（D1） |
| `payroll/bonus.py`、`api/bonus.py`、`bonus_pdf.py` | 凍結 `summary` 已存值 | 見 §5 |
| `pdf_gen.py` 結案報表（2562–2566） | 凍結 `summary` | 檔案**未改**；舊案由構造即逐位相同 |
| `subcontract/*`（`dispatchTotal` in vouchers／remit）、`cashier.py`、`accounting_export.py`、`approval_queue.py`、`voucher_summary.py`、`arap/*`、`quotations.py:4439` 的 `grandTotal` | 匯款／應付／出納的**含稅**單據金額 | 與精算口徑無關（付款必須含稅），C1 未動 ✔ |
| `recognition.dispatch_entries`、GL E04 | 未稅＋人員（含 E04 進項稅額） | 未動；即精算新口徑的對照基準 ✔ |
| 通知／email／ps1 工具 | — | grep 無任何讀取精算金額者（`notify_settlement_finalized` 只帶案號、客戶、使用者名） |

混合口徑檢查：同一次計算內沒有新舊混用——前端以 `dispatchBasis` 配對（`pretax`→未稅現算、無標記→含稅現算）；後端 `reports._live_dispatch_totals_by_quote(pretax=…)` 同。作者的 5 題報表過期測試（含兩個錯配方向）通過。

## 3. 舊完結案（沒有 `dispatchBasis`）

- 探針：舊式完結（`dispatchTotal 12500`、無標記）於基準與 C1 各開精算頁與案件頁財務分頁：
  - 數字：`summary.dispatchTotal 12500`、`totalActualCost 23525`、`itemActualTotal 11025`、`netProfit -23290` **基準＝C1**；C1 多出 `dispatchBasis:'taxed'`、`dispatchTax 500`、`dispatchGrandTotal 12500`（只在頁面記憶體的 summary，不寫回存檔）。
  - **假過期橫幅：精算頁 0、案件頁 `financeDispatchStale()` null（基準＝C1）**；新完結案（標記 `pretax`）與標未稅卻存含稅值的錯配都由作者 e2e 驗證通過（我重跑 55 題全綠）。
  - 案件頁（含「精算結果」）：全頁文字與基準的差異只有版本戳記（2 行），**逐項相同**。
  - **精算頁文字差異（S1）**：6 行中 4 行是版本戳記；實質 3 行——欄位標題「金額 (NT$)」→「金額 (NT$，含稅，舊口徑)」、新增分項行「舊口徑（含稅）：承攬商含稅合計＋外包人員 ＝ NT$ 12,500」、新增中性說明「此精算完結於含稅口徑…已完結的數字不改寫」。**數字完全相同**；若要求「逐位元組相同」就是偏差，請確認這是預期的說明。
- 結案報表 PDF：`pdf_gen.py` 在 diff 中**沒有改**、讀的是凍結 `summary`，舊案輸出由構造相同（未另行產 PDF 比對）。

## 4. 草稿行為

e2e 探針（舊草稿：存檔 summary `dispatchTotal 12500`、無標記）：
- 重開後以新口徑重算：`dispatchTotal 12000`、`dispatchBasis 'pretax'`、`dispatchTax 500`、`totalActualCost 23025`；一行說明可見，子元素只有 `SPAN`＋`BUTTON`，說明文字走 `x-text`。以承攬商名稱 `<img src=x onerror=window.__pwn=1>乙` 注入：**未執行**（`window.__pwn` 未定義，頁面 `img[src=x]` 數 0）。
- 按「儲存草稿」後存檔 summary：`dispatchTotal 12000`、`dispatchBasis 'pretax'`、`totalActualCost 23025`，**各項加總＝總成本**（無混合口徑）。「知道了」後 localStorage 只存 `stl_dispatch_basis_note_<案號>=1`（不含金額／內容），說明消失。
- 後端凍結缺標記預設 `taxed`（`_freeze`）：舊頁面（未重新載入 JS）在部署後完結，會落成舊口徑且自洽（存的是它自己的含稅值），不混用；但這正是 C2 應由伺服器強制口徑的理由。

## 5. 獎金

- 只讀凍結 `summary.netProfit`（已存值，不重算）。舊完結案不變（C1 不改任何存檔）。
- 新完結案獨立驗算（同夾具、頁面真值，基準 vs C1，報價未稅 0 以隔離公益金捨入）：`grossProfit −23525 → −23025`、`charityDonation −235 → −230`、`netProfit −23290 → −22795`，差 **＋495 ＝ 0.99 × 稅額 500**（毛利＋稅額 500，公益金 1%＋5）。
- 讀精算值的獎金路徑：`payroll/bonus.py::settlement_fields`（十二格含 `dispatchTotal`）、`api/bonus.py` 507–512（`base_amount_for`）、571–575、689–705（`netProfit` 已存值）、811–838（單據明細帶出）、928–931（`_plan_allocations`）、1710–1714（`_net_profit_or_error`，只在 `finalized`）、1974–2026（清單／案件狀態）、`bonus_pdf.py:208`（`itemPoUnadopted`）。全部讀已存的完結值，**沒有任何一處自行重算或讀 `dispatchTotal` 以外的派發欄位**。

## 6. 已對應顯示

- 列移動：材料 M（offset→品項 1）、材料 N（link→品項 2）、額外支出 1（offset→品項 2）出現在「已對應」表，X 與額外支出 2 留在未對應表；已對應列的目標品項文字正確（`#1 交換器…`／`#2 線材…`），金額與「已計入該品項的實際成本」說明正確；材料 N（連結）唯讀、其餘可改對應。
- **數字品項 id（`7`／`8`）錯誤確實修好**：已對應列的下拉值＝`7`／`8`、顯示 `#1 …`／`#2 …`（不再是「不對應」）。
- **伺服器端雙重對應**（`PUT …/settlement` 草稿，C1）：同一 ref 兩個去處 → 422「material Y 重複，同一筆只能有一個去處」；對已有 `quoteItemId` 連結的材料 L 設 offset → 422「不在目前的未對應清單內」；不存在的品項／ref → 422；合法單一對應 → 200。
- 色塊／徽章／圖例：圖例與「已對應」徽章存在；**淺色主題**列底 `rgb(240,253,244)`、文字 `rgb(10,10,10)` 對比 18.9:1、徽章對比 4.57:1，正常。**深色主題見 M1。**

### M1（must-fix，顯示）：深色主題「已對應」列文字幾乎不可讀
- 事實：全站深色是 `body > *` 的 `filter: invert(1) hue-rotate(180deg)`（`style.css:170`）；`style.css:1660–1666` 的註解明說：**`:root[data-theme="dark"]` 的 `--tone-*` 是給「不經過這道反轉」的頁面用的，過濾頁面若改用會被再反轉一次**。C1 的列底寫成 `var(--tone-success-bg, #ECFDF5)`，深色主題解析為 `#0F2A1A`（暗綠），再被濾鏡反轉成**淺薄荷綠** `rgb(200,227,211)`，而文字顏色（繼承的近黑）被反轉成近白 `rgb(245,245,245)`。
- 量測（深色主題截圖像素）：「單據」「類型」文字 `rgb(245,245,245)` on `rgb(200,227,211)` ＝ **1.25:1**；唯讀文字「由材料申請連結（唯讀）」 `rgb(148,148,148)` ＝ 2.22:1；徽章本身（前景與底色都來自 token，一起被反轉）正常。截圖：`e2e` 探針輸出（深色）可見列幾乎一片淺綠。
- 影響：使用者在深色主題看不到哪一筆已對應（正是這個需求要解的問題），且完全沒有紅燈（作者測試只在淺色量）。
- 建議（不動手）：在這張過濾頁面不要使用 `var(--tone-*)` 的深色值，直接寫淺色字面值（`#ECFDF5`／hover `#D1FAE5`、徽章 `#065F46`／`#D1FAE5`／`#6EE7B7`）——讓濾鏡統一反轉出「暗綠底＋淺字」；並加一題深色主題計算樣式的對比測試（正對照：列底與文字對比 ≥ 4.5）。

## 7. 可見度

重跑非財務探針（同一案件、含材料備註與額外支出附註的機密標記字串）：
- viewer：GET／POST preview 皆 **403**，回應不含任何新欄位或機密標記。
- engineer＋`expense_forms`：**403／403**，同上。
- engineer＋`financial_view`：**200／200**，回應含 `dispatchTax`、`dispatchGrandTotal`、`dispatchBasis`、材料 `notes`、額外支出 `note`（預期：新欄位只在財務閘之後）。anon 401。
- 新欄位不經營運報表、總帳或其他端點輸出（讀碼：`recognition.extra_entries`／`material_money_rows` 未動；備註與附註由 `settlement_actuals.compute` 另查，僅回在 `settlement-actuals` 兩支端點）。

## 8. 設計差異與觀察

- **D1 報表總計混合口徑**：營運報表毛利頁對各案 `settleSummary.itemActualTotal／totalActualCost／netProfit` 直接加總；舊完結案（含稅）與新完結案（未稅）混在同一個總數裡，差別＝承攬商稅額，UI 沒有標示。已完結不改寫是裁示，故屬設計；建議在總計旁註記或之後以 `dispatchBasis` 分欄。
- **D2** 舊頁面（部署前載入的瀏覽器分頁）完結 ⇒ 落舊口徑（見 §4）；C2 應由後端強制。
- **D3** 完結驗證仍不含派發（S7 仍 200）——C2 範圍，另審。
- 觀察：`totals.dispatchBasis` 對舊凍結案回字串 `'taxed'`、頁面 `summary.dispatchBasis` 也寫 `'taxed'`，但存檔裡舊案沒有該鍵——判斷一律用「無標記」，而非 `=== 'taxed'`，目前程式碼一致。

## 附錄

- 探針：`test_zz_recon_c1.py`（後端，12 題；基準與 C1 各跑；S2 預期值基準 17050／C1 16550，其餘斷言相同）、`test_zz_e2e_c1.py`（Playwright，舊完結頁面文字、草稿說明／存檔、已對應清單／主題對比；基準與 C1 同跑）。皆未入庫、已刪；`-n 1`／單程序、basetemp 已刪。
- 作者測試（C1 worktree）：`test_settlement_tax_basis`／`assigned_fields`／`cost_extras`／`actuals`／`reports_stale_dispatch_basis`＋3 個 e2e 檔，**55 passed**。
