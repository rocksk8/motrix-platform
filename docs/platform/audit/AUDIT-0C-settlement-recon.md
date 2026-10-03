# AUDIT-0C — 案件精算端到端對帳稽核（方式／價格／報表／總帳／財報）

- 對象：`origin/platform` @`5d76b528`（＝正式機 `326e6676` 的程式碼）。稽核者 hichan-0c，2026-10-03。唯讀；全部數字取自 dev 測試庫的合成情境（pytest 夾具＋HTTP API），**未碰正式機**。
- 方法：(1) 讀碼（`settlement_actuals.py`、`recognition.py`、`api/settlement_actuals.py`、`settlement.html calcSummary`、`reports.py`、`gl_events.py`、`ledger/*`）＋對規格；(2) 自寫探針（未入庫，已刪；附錄）逐情境把**手算預期值**對上每個下游；(3) 下游＝精算端點 → 認列層（`material_entries`／`extra_entries`／`dispatch_entries`）→ 營運報表月支出（權責與現金兩口徑）→ 總帳事件（`gl.events`）→ 傳票過帳後試算表／損益表。

## 結論（最重要的先講）

**沒有發現「金額算錯」或「同一筆錢重複計」。** 8 個情境，手算＝精算端點；採購類金額（PO＋材料申請＋額外支出）在精算、認列層、營運報表（權責）、總帳事件、過帳後試算表五處**逐位相等**。所有不一致都能用已記載的設計決策解釋；其中 **2 項建議列 should-fix**（一個完整性缺口、一個文件缺口）。依要求，承攬商含稅 vs 未稅的稅差只量化、不裁示。

| 級別 | # | 內容 |
|---|---|---|
| must-fix（金額錯／重複計） | — | 無 |
| should-fix | F1 | 完結（finalize）後端只重算「品項／額外支出／採購類」三塊；**派發、匯款手續費、自訂支出、總成本、毛利／淨利不驗**，偽造 `summary` 可完結並凍結（S7）。營運報表的毛利直接讀這份 `summary.netProfit` |
| should-fix（文件） | F2 | 程式碼與測試處處引用的 `docs/platform/plans/SETTLEMENT-ACTUALS-SPEC.md` 與「USER-DECISIONS D8–D10」**不在 `origin/platform`**（規格只存在於未併入的 `origin/wip/t32-material-link-spec-2e`，USER-DECISIONS 檔名在整個樹裡找不到） |
| documented-by-design | D1 | 承攬商含稅 vs 未稅（5% 稅差），量化見 §3 |
| documented-by-design | D2–D6 | 估計值、手填取代採購（D8）、完結凍結、預設現金口徑、手續費科目 |

## 1. 方式（規則實況與規格對照）

**精算總成本**（`settlement_actuals.compute`；頁面 `calcSummary` 同式）：

```
totalActualCost = Σ品項實際 + itemPoUnadopted(新模式恆 0) + extraTotal(未對應額外支出) + materialUnassignedTotal
                + remitFeeTotal + customExpenseTotal + dispatchTotal(承攬商含稅 grandTotal + 外包人員)
品項實際 = 有採購且採用 ⇒ 採購金額（PO 連品項＋材料申請歸屬＋offset 額外支出）取代估計；
          否則 手填(非0) ⇒ 手填；否則 估計 = half-up(qty×cost×1.05)
```

| 規則 | 實際行為（碼） | 規格／裁示 | 對得上？ |
|---|---|---|---|
| 規則 A：採購取代估計 | `has and adopt ⇒ purchased`；無採購 ⇒ 估計（S3：未採購品項 b 仍算估計 525） | §1.3 | ✔ |
| D8 手填取代／未採用採購不計 | `UNADOPTED_IGNORE` 預設：`itemPoUnadopted=0`，被手填取代的採購金額**不進精算任何欄**（只在 `purchasedTotal`、頁面警示） | §9.1 建議值 | ✔（S5：精算 4200 vs 實付 4550，差 350＝被手填 700 取代的採購 1050 − 700） |
| D9 未對應只警示 | 未對應材料申請／額外支出**計入成本**、完結不擋 | §9.3 建議值 | ✔ |
| D10 完結容差 | `check_finalize`：品項 ±(品項數)元、其餘 ±1 元；比對品項／未採用／額外支出（含未對應材料）／`purchasedTotal` | §9.5 | ✔，但範圍見 F1 |
| 連結／offset | `quoteItemId`＝link；`offsets` 只收存在的品項、單一去處；品項已刪 ⇒ 回未對應＋警告（錢不消失） | §4 | ✔ |
| 凍結 | `finalized` ⇒ `_freeze`：取存檔 `actualTotalCost`／`summary`，現算值放 `live` | §5.6 | ✔（S6） |
| 作廢／草稿／退回 | 不計（S4：草稿 400、已作廢 300，五處皆不計） | §2 | ✔ |
| 手填 0＝沒填 | `manual_actual`（歷史相容；註記「是否算缺陷列第 34 班待裁示」） | — | 既有；0 元實際成本無法持久，建議使用者裁示 |
| 材料申請範圍 | `material_money_rows` 只含「已成案／已結案」案件；額外支出不限 | §2 | ✔（精算與報表同函式，不會漂） |

規格與碼的差異：規格 §2 把 `remitFeeTotal`／`customExpenseTotal` 放在回傳 `extra` 內，實作放在 `costExtras`／`totals`（第 34 班併入；功能等價，非缺陷）；規格 §9.5「完結重算驗證」只談採購類，第 34 班加入派發等成本後驗證範圍沒有跟著擴大 ⇒ F1。

## 2. 價格（獨立重算）

- **半捨入**：品項估計 `halfUp(qty×cost×1.05)`。以我自己的 `Decimal(ROUND_HALF_UP)` 重算：`2×25×1.05＝52.5 ⇒ 53`（銀行家捨入會是 52）、`3×33.33×1.05＝104.9895 ⇒ 105`、`7×10.1×1.05＝74.235 ⇒ 74`；API 回 53／105／74，**逐位相同**。數字型品項 id（`7`）正確鍵成 `"7"`、非 unkeyed。
- 稅：精算「品項」成本以未稅×1.05 估計（5% 非扣抵進項稅假設）；手填的含稅模式（`taxed`＝÷1.05、`taxed_gross`＝×1.05）是**頁面獨有**邏輯，已由既有 `test_manual_actuals_in_all_three_tax_modes`（對舊式參考實作）覆蓋；本稽核未在瀏覽器重跑 JS。
- 手續費：S8 第二張 PO（品項 b，2×100）已付款含手續費 15 ⇒ 精算 `remitFeeTotal=15`、總成本 4765；營運報表（權責）「其他支出」含 15（總 4765）；總帳 15 入 7243（手續費科目，不在 5811 工程成本）⇒ 5811 4750＋7243 15＝4765 ✔。
- 多張 PO：品項 b 的 PO 200＋材料申請 N 800＝1000（S8 品項 b 實際＝1000）✔。

## 3. 對帳表（案件情境 × 下游 × 金額 × 是否相符）

單位：元。「精算」＝`totalActualCost`；「報表(權)」＝營運報表月支出（`basis=accrual`）該案合計；「報表(現)」＝預設現金口徑；「GL」＝總帳事件 `COST_PROJECT` 借方；「TB」＝過帳後試算表 5811 借方（工程成本）。

| 情境（手算預期） | 精算 | 認列層 | 報表(權) | 報表(現,預設) | GL 成本 | TB 5811 | 相符？ |
|---|---|---|---|---|---|---|---|
| S1 PO3000＋PO額外500＋材料N800(連b)＋X250未對應；K3000 連PO不重複（4550） | 4550 | 4550 | 4550 | 3500 | 4550 | 4550（2171 貸 4550） | ✔ 五處＝4550；現金口徑 3500＝材料未付款 |
| S2 ＝S1＋承攬商 未稅10000／稅5%／個人2000（17050） | **17050** | 4550＋**12000** | **16550** | 3500 | **14550**（＋進項稅 500） | **14550**（1268 借 500；2171 貸 15050） | ✘ 見 D1：精算比報表多 **500**、比總帳成本多 **2500**（500 稅＋2000 個人點工入帳時點） |
| S3 只有品項 a 採購、b 無採購（3000＋b 估計 525＝3525） | 3525 | 3000 | 3000 | 3000 | 3000 | 3000 | ✔ 差 525＝估計值，設計 D2 |
| S4 ＝S1＋草稿400＋已作廢300（4550） | 4550 | 4550 | 4550 | 3500 | 4550 | 4550 | ✔ 草稿／作廢不計，五處皆不變 |
| S5 ＝S1，offset X→b，b 手填 700 且不採用（4200） | **4200** | 4550 | 4550 | 3500 | 4550 | 4550 | ✘ 差 **350**，設計 D8（手填取代採購；`purchasedTotal` 仍 4550） |
| S6 完結（凍結 4550）後又核准 PO b＋200 | **4550（凍結）**；`live` 4750 | 4750 | 4750 | 3700 | 4750 | 4750 | ✘ 差 **200**，設計：完結＝快照，`live` 供頁面提示（§5.6） |
| S7 偽造完結：`dispatchTotal=0`、`totalActualCost=4550`、`netProfit=888888`；實際派發 12500／實際總成本 17050 | 以偽造值存檔，HTTP **200** | — | — | — | — | — | ✘ **F1** |
| S8 ＝S1＋PO2（b 2×100）已付款含手續費 15（4765） | 4765 | 4750＋15 | 4765 | 3715 | 4750（手續費另在 7243＝15） | 5811 4750／7243 15 | ✔ 總額 4765 五處相同 |

**D1 承攬商稅差完整算例**（S2：未稅 10000、稅率 5%、外包人員 2000）：

```
精算 dispatchTotal   = 10000×1.05 + 2000 = 12500   （含稅 grandTotal＋人員；頁面歷史算法，使用者裁示 A「歷史精算不變」）
認列層／營運報表(權) = 10000 + 2000        = 12000   （未稅＋人員；差 500 ＝ 承攬商稅額 10000×5%）
總帳 E04             = 借 專案成本 10000、借 進項稅額(1268) 500、貸 應付帳款 10500
總帳 人員 2000       = 派發當下不入帳（歷史匯款走 E05b＝付款時；新資料個人點工走勞報單 E06）
試算表 5811          = 14550；損益表營業成本 14550
結果：精算總成本 17050；報表 16550；總帳成本 14550
      差 ＝ 稅 500（精算 vs 報表）＋ 人員 2000（報表 vs 總帳；入帳時點）
```
稅額在總帳是**可扣抵進項稅額（資產）**，在精算被當成成本；這就是已知差異，本稽核只量化：精算比報表多 **5% × 未稅承攬費**。

## 4. 發現（依嚴重度）

### F1 — should-fix：完結只驗三塊，派發／手續費／自訂支出／總成本／淨利可偽造
- 事實：`check_finalize` 只比對 `itemActualTotal`、`itemPoUnadopted`、`extraTotal`（含未對應材料）、`purchasedTotal`。S7：用財務檢視帳號直接 `PUT …/settlement` 送 `dispatchTotal=0`、`totalActualCost=4550`、`netProfit=888888`（實際派發 12500、實際總成本 17050）⇒ **HTTP 200，完結並凍結**。
- 影響：營運報表毛利直接讀 `settlement.netProfit`／`grossProfit`（`reports.py:401-402`）；獎金（`payroll/bonus`）與結案報表 PDF 讀同一份 summary。報表「毛利」可以與總帳完全對不起來而沒有檢查；僅 `staleSettlementCount`（`reports.py:529-545`）會因 `dispatchTotal` 凍結值≠即時值而提示，手續費、自訂支出、淨利、毛利沒有比對。
- 範圍：需持有財務檢視權限的帳號直接打 API（頁面本身會送正確值）；屬完整性／防呆缺口，不是現行資料錯誤。
- 建議（不動手）：`check_finalize` 比照 `case_extras()` 再比對 `dispatchTotal`、`remitFeeTotal`、`customExpenseTotal`、`totalActualCost`；`grossProfit`／`netProfit` 由後端以報價未稅與同一公式（管理費 10%、公益 1%）重算比對。

### F2 — should-fix（文件）：規格與使用者裁示檔不在 `origin/platform`
- `settlement_actuals.py`、`api/settlement_actuals.py`、conservation 測試的 docstring 皆引用 `docs/platform/plans/SETTLEMENT-ACTUALS-SPEC.md`；該檔只在 `origin/wip/t32-material-link-spec-2e`（`9ea4c0d4`），**未併入 platform**。「USER-DECISIONS D8／D9／D10」在整個樹內沒有對應檔案；規格 §9 把它們列為「需要使用者再裁示」，之後的裁示只散在程式註解與測試名。
- 影響：「碼 vs 文件」只能對那份分支上的規格；正式機維運者看不到。建議把規格併入 platform，並把 D8–D10 的最終裁示寫回檔內。

### 設計決策造成的差異（documented-by-design；已量化）
- **D1** 承攬商含稅 vs 未稅（§3，S2：500）；個人點工在總帳是付款／勞報單時點（S2：2000）。
- **D2** 精算含**估計**（無採購品項 ×1.05），報表／總帳只有實際採購（S3：525）。
- **D3** D8：手填取代採購，採購金額不進精算（S5：350），頁面警示。
- **D4** 完結凍結：完結後新核准的採購單在報表／總帳立即出現，精算只提示 `live`（S6：200）。
- **D5** 營運報表**預設現金口徑**（`DEFAULT_BASIS="cash"`，使用者 2026-09-30 裁示）：材料申請未付款不入、承攬商要有已匯款單才入；精算固定權責（含待審核）。S1：報表(預設) 3500 vs 精算 4550。切到「權責」才逐位相同。
- **D6** 手續費總帳走 7243（非工程成本 5811），報表權責併入「其他支出」，精算單列 `remitFeeTotal`；總額一致、科目不同。

## 5. 未涵蓋（誠實列出）

- 未在瀏覽器重跑 `settlement.html` 的 JS（含稅三模式 `taxed`／`taxed_gross`、`MotrixLegalRound`）；以既有 parity／e2e 測試為憑。
- 未做：現金口徑下已付款承攬商匯款（`contractor_payment_vouchers`）情境、`custom_finance` 自訂支出、獎金／結案 PDF 的下游數字、跨月／跨年度歸月差異、已取消派發（讀碼：精算、認列層、報表即時比對皆用 `status != 'cancelled'` 且「草稿／已退回不計」，同一述詞）。
- 數字型品項 id 只驗了估計與鍵化（`"7"`），未驗 PO／材料申請連結與 offset 在 int id 下的行為。

## 附錄 — 重現與探針說明

- 探針（未入庫，跑完已刪）：在 `origin/platform` worktree 的 `backend/` 以 `PROBE_OUT=<json> .venv312\Scripts\python.exe -m pytest -q -p no:cacheprovider modules/case/tests/test_zz_recon_main.py`；9 題全 passed，每題先 `assert` 手算預期＝精算端點，再寫出各下游數字。
- 下游呼叫：`material_entries`／`extra_entries`／`dispatch_entries`、`GET /api/reports/expenses-monthly?basis=accrual|cash`、`ledger.contract.collect`（`gl.events`）、`/api/ledger/engine/run`＋`batch`（過帳）、`reports.trial_balance`；損益表檢核 `ni_equals_trial_balance`／`trial_balance_balanced` 皆 true（探索跑）。
- 夾具注意：既有測試的「已成案」夾具只設 `deal_tag` 欄、資料 JSON 沒有 `dealTag`，`save_quotation_json` 依 JSON 重算欄位，完結後案件會被認列層排除——這是夾具問題（探針已改成同時寫 JSON；正式資料兩者同步），不是產品缺陷。
