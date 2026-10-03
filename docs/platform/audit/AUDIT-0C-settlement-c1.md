# AUDIT-0C — 精算 35c（稅基 B＋已對應顯示）獨立稽核（C1；C2 完結重算另審）

- 對象：`origin/wip/t35c-settle-assigned` @`55242226`（顯示 `b6ff69be`／`c43d34e8`、登記 `7702591d`、稅基 B `7bc1c23a`、CHANGELOG `55242226`），對 `origin/platform` @`5d76b528`。稽核者 hichan-0c，2026-10-03。唯讀；只用 dev 測試庫與 Playwright 合成資料。
- 方法：讀碼＋沿用 settlement-recon 的獨立探針在**基準與 C1 兩棵樹各跑一次**（同夾具）＋自寫 e2e 探針（基準／C1 同跑，輸出頁面文字與計算樣式）＋作者自己的 55 題（單程序）。探針未入庫、已刪。

## 結論

**MUST-FIX 2 項：M1（顯示，僅深色主題）、M2（頁面完結存成含稅值，金額）。** 其餘金額與口徑部分 PASS。作者的 55 題全綠（精算稅基／已對應欄位／成本彙總／端點／報表過期比對／3 個 e2e 檔），但**沒有一題走真實頁面完結**——M2 因此沒被抓到（主持通知 d5 自己也發現了同一個缺陷；本報告以獨立重現確認，見 §9）。

| 級別 | # | 內容 |
|---|---|---|
| **must-fix** | M2 | 經**精算頁**完結（草稿→按完結）時，存檔 summary 是含稅 `dispatchTotal 12500`、`dispatchBasis 'taxed'`、`totalActualCost 23525`（草稿畫面是 12000／23025；營運報表權責是 12000）。新口徑在頁面完結路徑上**從不生效**，5% 爭議依然存在（§9） |
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

## 9. 頁面完結端到端（M2；補測，2026-10-03 22:3x）

探針（未入庫）：同夾具（報價未稅 21000、承攬商未稅 10000／稅 5%／人員 2000）；真實頁面草稿載入 → 按「完結精算」→「確認完結」→ 讀存檔與各下游。對象 `55242226`。

| 步驟 | 結果 |
|---|---|
| 草稿頁面 summary（完結前） | `dispatchTotal 12000`、`dispatchBasis 'pretax'`、`totalActualCost 23025` |
| **頁面完結後的存檔 summary** | **`dispatchTotal 12500`、`dispatchBasis 'taxed'`、`dispatchGrandTotal 12500`、`totalActualCost 23525`**、`netProfit -4600`（頁面無錯誤） |
| 完結後 `settlement-actuals`（凍結） | `dispatchTotal 12500`、`dispatchBasis 'taxed'`、`totalActualCost 23525` |
| 營運報表權責（該案承攬商） | **12000** |
| 偽造 PUT（`dispatchTotal 0`＋標記 `pretax`，其餘照填）| HTTP **200**（C2 未到，預期） |
| 含稅值 12500 掛 `pretax` 標記的 PUT | HTTP **200**（C2 應拒絕） |

- 成因（與 d5 自查一致，我獨立重現）：`finalize()` 先把 `status` 設為 `finalized` 再算 `calcSummary()`；此時 `dispatchBasisOld()`＝`finalized && 沒有 _frozenSummary.dispatchBasis`＝true ⇒ 走含稅口徑並把標記寫成 `'taxed'`。
- 影響：經頁面完結的**每一個**新案都落在舊口徑（多算承攬商稅額 500＝5%），與營運報表／總帳差 5%；過期比對因標記一致而不會報警，問題隱形。`netProfit` 少算 0.99×稅額（獎金基底偏低）。
- 作者測試沒抓到的原因：所有「新完結案」題都以 `_set_settlement`（直接寫 DB 的合成 summary，帶 `dispatchBasis:'pretax'`）造案，沒有任何一題走頁面完結。
- 驗收條件（待 d5 新 sha＋C2）：(a) 頁面完結後存檔 `dispatchTotal 12000`、`dispatchBasis 'pretax'`、`totalActualCost 23025`；(b) 偽造 PUT（`dispatchTotal 0`）與含稅值掛未稅標記 → 409；(c) 以上用**真實頁面完結**造案的 e2e 題入庫；(d) 重跑本報告 §1 的 S2＝16550 與 §3 的舊完結案不變。我會在新 sha 出來後以同一探針重測並更新結論。

## 10. 複審（`13183b63`：紅燈探針 `17754fdc`→C2/F1 `62a761e9`→M1/M2 修正 `6b8ce6f6`→登記 `13183b63`）— PASS

**結論：M1、M2 已修；C2（F1）通過；無新的 must-fix。** 作者新題＋稅基／已對應相關 51 題全綠（單程序）。以下全部由我獨立重跑（探針未入庫、已刪）。

### 10.1 M2（頁面完結）— 已修
- 我的探針（同夾具；真實頁面草稿→「完結精算」→「確認完結」）：存檔 `dispatchTotal 12000`、`dispatchBasis 'pretax'`、`dispatchTax 500`、`dispatchGrandTotal 12500`、`totalActualCost 23025`（＝草稿畫面）；完結後 `settlement-actuals` 凍結值同；**營運報表權責 12000＝存檔承攬商成本**；頁面無錯誤。（舊版 `55242226`：12500／`'taxed'`／23525。）
- 作者的 e2e `test_the_pages_own_finalize_payload_passes_the_server_recheck_on_the_new_basis`**真的驅動頁面**：以真實點擊「儲存草稿」「完結精算」「確認完結」，用 `expect_response` 抓頁面自己送出的 PUT 並要求 200，再讀存檔比對草稿、口徑標記與營運報表權責口徑，並驗利潤線公式（非合成 DB summary）。
- **突變（我做的）**：把 `dispatchBasisOld()` 的 `!this._finalizing &&` 拿掉 ⇒ 該 e2e 轉紅（頁面自己的 payload 被 F1 以 409 擋下：承攬商 12500 vs 12000），還原後綠。同時證明兩道防線互相獨立：只要頁面再誤送含稅，F1 會擋。
- 補：頁面完結成功後 `_frozenSummary` 設為 `dispatchBasis:'pretax'`，之後同頁顯示／過期比對認得新口徑；`_finalizing` 在 `finally` 重置。

### 10.2 M1（深色對比）— 已修
- 修法：本頁在深色模式整頁 `invert`，已對應列／徽章／圖例改寫淺色字面值（不再用 `--tone-*` 深色值）；完結後唯讀 `select:disabled` 另設字色。
- 我的量測（**真實截圖像素**，非公式；已對應列內每個儲存格：類型、單據、徽章、品項、「已計入…」說明、金額、下拉／唯讀文字）：
  | 狀態 | 淺色 最低對比 | 深色 最低對比 |
  |---|---|---|
  | 草稿（有下拉） | 4.76 | **6.63**（舊版 1.25） |
  | 已完結（唯讀） | 4.76 | **6.63** |
  全部 ≥ 4.5:1。作者的 e2e（淺／深 × 草稿／完結 4 組）以濾鏡矩陣算對比；我的像素量測與其一致方向。

### 10.3 C2／F1（完結後端全欄位重算）— 通過
讀碼：`check_finalize` 在原三塊之外加 `_check_downstream`（`dispatchTotal`、`remitFeeTotal`、`customExpenseTotal`、`totalActualCost`、`grossProfit`、`adminCost`、`charityDonation`、`netProfit`、毛利率、淨利率、`quotedPretax`），期望值由同一個 `compute()`＋伺服器上報價單的 `tot.pretax` 算出（管理費＝半捨入(稅前×10%)、公益金＝半捨入(毛利×1%)、淨利＝毛利−管理費−公益金，與頁面 `calcSummary` 同式）；沒送的欄位不拒絕但存檔前由 `fill_downstream()` 補齊並蓋 `dispatchBasis`。**只在 非完結→完結 轉換時**執行（`quotations.py` 兩處條件都帶 `existing_settlement.status != 'finalized'`）；`_freeze`／讀取路徑未動。

我的 API 探針（PUT 草稿→完結；摘要用我自己的公式、從伺服器數字獨立產生；案件 2 品項、未稅 100000、承攬商 10000／稅 5%／人員 2000＋PO 3000）：

| 竄改／情境 | 結果 |
|---|---|
| **S7**：`dispatchTotal 0`、總成本 −12000、`grossProfit 999999`、`netProfit 888888` | **409**，訊息列出 4 項差異（承攬商 0 vs 12000；總成本；毛利；淨利） |
| 只改 `netProfit 888888` | 409「淨利：頁面 888888、系統重算 73630」 |
| 毛利 +100／管理費 +2／淨利率 +1.0%／匯款手續費偽造 999／`quotedPretax` 偽造 500000 | 全部 409，各自點名欄位 |
| 含稅值 12500 掛 `pretax` 標記 | 409（承攬商 12500 vs 12000；總成本 +500） |
| 淨利 **+5** | 200（容差內） |
| 淨利 **+9** | 409（容差＝品項數＋6＝8 元；888888 遠超） |
| 誠實的頁面式 payload | 200 |
| **省略** `dispatchTotal／grossProfit／netProfit／adminCost／charityDonation／totalActualCost／quotedPretax／remitFeeTotal` | 200，存檔由伺服器補齊：12000／84475／73630／10000／845／15525／100000／0，`dispatchBasis 'pretax'`（偽造不能靠「不送欄位」繞過） |

- **真實頁面 e2e（M2 探針同一案）：竄改 PUT（承攬商 0＋淨利 888888）與含稅掛未稅標記 PUT 都回 409**，訊息為「完結前系統重算的成本與畫面不一致…差異：承攬商派發成本（未稅＋外包人員）：頁面 0、系統重算 12000；…」——點名欄位與兩邊數字，清楚。
- **容差合理性（誠實 payload 不誤拒）**：用我自己的頁面式公式產生 3 組實際夾具，**全部 200**：①4 品項半捨入（`2×25`＝52.5、`3×33.33`、`7×10.1`、`11×0.5`；未稅 12345；承攬商 3333＋稅＋人員 777）；②已付款額外支出含匯款手續費 15、**毛利為負**（未稅 9000；公益金負數半捨入）；③混合（PO 連品項、材料申請連品項＋offset、手填 700 且不採用）。另有真實頁面完結（§10.1）通過。（第一次跑時②③被擋，經查是我的探針漏帶手續費進 `extraTotal`、漏帶 `offsets` 進 PUT 本文；修正後通過——也顯示伺服器是以 PUT 本文的 `offsets` 重算，與頁面一致。）
- **轉換與凍結**：誠實首次完結 200；完結後讀取 `settlement-actuals` 與讀舊式完結案（無標記）都**不寫回**（存檔逐位不變，舊案維持 `'taxed'` 顯示口徑）。

### 10.4 殘餘觀察（非阻擋）
1. **已完結案再 PUT（超級管理員重存）不驗證、不補欄位、不蓋口徑標記**：我送偽造淨利 888888 到已完結案，回 200。這是既有「已完結僅超級管理員可重新修改」路徑；F1 只守「非完結→完結」轉換，與作者陳述一致。若要連這條也守，需把比對放到每次 `status=finalized` 的寫入（或限制只能先重開成草稿）。建議由使用者裁示；現行不構成新風險。
2. 該路徑存下的 summary 若沒有 `dispatchBasis`，之後 `_freeze` 以預設 `'taxed'` 解讀（顯示含稅）；頁面自己重存會帶標記，直接 PUT 才會。
3. 錯誤訊息前綴固定寫「採購單、材料申請或額外支出在你編輯期間有變動」，在差異只是承攬商／利潤欄位時敘述不貼切（差異清單本身是準確的）。文字微調即可。
4. **未涵蓋**：自訂模組支出（`customExpenseTotal`）的非零夾具（只驗了 0 與偽造 999 的匯款手續費）。
