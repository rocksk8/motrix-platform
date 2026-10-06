# 營運分析 更新紀錄

## (next) — 2026-10-06（wip/t43-shipped-qty）：報價品項「已出貨數量」（匯出兩欄）；欄序已出貨在前
- 財務報表 Excel 的「毛利分析」工作表最右新增兩欄「報價品項數量合計」「已出貨數量合計」（只有數量；經 `case.shipped_summary` 提供者，M01 不在 ⇒ 留白）。既有欄位位置不動。

## (next) — 2026-10-06（wip/t43-settle-tax）：營運報表加稅額欄位
- 營運報表（收支報表）新增稅額欄位：年度月支出矩陣與月／季／年範圍合計加「稅額（確定）／稅額（推估）／未拆稅金額」；逐筆明細帶 `tax`／`taxKind`；Excel／PDF 同步。稅額已含在各類支出內（不另加）；推估與未拆稅金額另列，不混進確定稅額。承攬商派發自派發日期 ≥ 2026-10-01 起含稅計入（見案件管理 CHANGELOG），之前月份數字不變。
- `ledger_diff`：應計口徑切換日後承攬商含稅的稅額獨立成 `tax` 分桶。

## 1.0.34 — 2026-10-05（wip/t42-finance-role）：財務角色
- 儀表板財務數字（stats／monthly／財務圖表）改由「財務」角色決定；營運報表存取＝財務角色／superadmin 或持有「營運報表」模組者（admin 直通拿掉）。

## 1.0.33 — 2026-10-05（wip/t40-analytics-f9）：儀表板財務卡片只給財務檢視權限者；儀表板讀取變快；預留抵用規則（S-1）
- **財務卡片收緊（使用者裁示「首頁改成只給財務檢視權限者」）**：`/api/dashboard/stats` 的收款項目、預估 vs 實際、前五高毛利、結算摘要、應收摘要，條件由「superadmin／admin 或財務模組」改為「同上 **且** `can_see_financial`」；不符者回空值（不報錯）。仍是全公司口徑（不加逐案可見）。失去卡片的只有「有財務模組、但角色不是 admin／sales 且沒有財務金額可視」的帳號。新增回應鍵 `financeVisible`（布林＝上述條件），前端用它隱藏應收款項面板與收款百分比。待審核清單、保固預警、純計數、月度收入與支出端點不變。
- **儀表板讀取變快（稽核 F-06；輸出不變）**：核准流程／精算 JSON 只對回應會用到的列取出（其餘列取 NULL）；每列 caseRecord 一次請求只解析一次（原本付款、保固、設備、應收四段各一次）。量測（`tests/bench_dashboard_stats.py`，2 萬筆假報價單、7 次中位數）：**0.970 s → 0.663 s（−32%）**。特徵題用修整前的輸出逐值比對（含混合狀態／成交標籤／部門／superadmin 與 admin）。`reports.py` 的 `_collect` 本來就有 `WHERE 成案／結案`（含 COALESCE 舊資料退路），不需改。
- **利潤分析預留抵用規則（稽核 T39 S-1）**：實際直接成本比原始多出 C（原始直接毛利 − 真實毛利）先抵用報價預留 R，未被抵用 Y ＝ clamp(R − max(C,0), 0, R)。Excel「毛利分析」第 23 欄改名「其中：預留未被實際成本抵用」＝Y，第 24 欄「其他」＝差異 − Y（第 1–21 欄不動）；PDF 差額列改為「原始預估已扣報價預留間接成本 R（實際只計單據）；其中未被實際成本抵用 Y；其他 Z」。不做類別對應，C 含所有多出的直接成本。
- 結果快取本班不做，提案見 `docs/platform/plans/NOTE-DASHBOARD-CACHE-T40.md`。
- 測試：儀表板特徵題＋讀取結構題 2、財務卡片矩陣（10 種帳號）、financeVisible、預留抵用 5 種情況。

## 1.0.32 — 2026-10-05（wip/t40-fe-05）：報表的結案精算明細顯示真的 0、公益金不再出現「− −50」（純前端）
- `reports.html` / `reports.js` 的「成本品項」依 `settlement.schemaVersion`（`Number(sv) >= 2`）：數字（含 0）＝有填，顯示 `NT$ 0`，`null`／空顯示「—」；舊存檔（沒有標記）0 仍視為未填。公益金列：≥0 照舊「− 金額」，舊的已凍結負值顯示帶號金額。不改任何公式與後端。測試：`tests/test_settlement_item_cost_display_2026_10_05.py`。

## 1.0.31 — 2026-10-05（wip/t39-analytics-f9）：利潤分析原始側列出「報價預留間接成本」並拆解淨利差額
- 精算摘要新鍵 `origIndirectReserve`（報價 tot.totalIndirect − 管銷 − 公益；M01 完結時凍結）。Excel「毛利分析」表（**工作表名與既有欄號都不變**）在最右側新增群組「報價預留間接成本」三欄：「報價預留間接成本」「其中：報價預留間接成本」「其中：其他」（後兩欄相加＝差異金額；含合計列）；PDF 利潤分析明細的原始側多一列「報價預留間接成本」，差額列尾註明「其中 報價預留間接成本 X（實際以單據為準）；其他 Y」。畫面利潤分析表沒有原始側分項，不變。
- 純資訊與差額拆解：不改任何金額、不影響獎金基數、實際側不變（沒有類別對應）。舊精算沒有該鍵 ⇒ 0，PDF 不多任何列。
- 既有 21 欄的位置與表頭一律不動（依賴這份匯出的人或工具不受影響），有測試鎖定。
- 註解更正：`actualMarginPct` 與報價 `net_margin_pct` 的「可比」只在實際單據已涵蓋報價預留的間接成本時成立。
- 測試 5 題（`test_original_indirect_reserve_2026_10_05.py`）。

## 1.0.30 — 2026-10-04（wip/t38-analytics-f9）：精算實際利潤不再在淨利 0 時退回毛利；儀表板只算完結並比淨利率
- `reports._settle_actual_profit_margin()`：有 `netProfit` 鍵就用淨利（含 0／負數），沒有鍵的舊精算才退回毛利；`_collect()` 的 `actualMarginPct`／`grossProfit` 改走它，下游（業務績效、年度達成、毛利表、Excel／HTML）同步。金額 `int()` 截斷改 `round()`。
- 儀表板 `marginComparison`／`settledSummary`：只計 `settlement.status=='finalized'`（草稿 summary 為前端暫存值），並比淨利率（`netMarginPct`／`netProfit`）對報價單 `net_margin_pct`；舊完結案（無淨利鍵）仍用毛利，值不改寫。
- **使用者可見字樣（使用者裁示）**：營運報表畫面／Excel／PDF 的「預估毛利率／實際毛利率／預估毛利／實際毛利／精算實際毛利／平均淨毛利率／年度實際毛利」改稱「…淨利…」，分頁「毛利分析」改「利潤分析」；**Excel 工作表名「毛利分析」不改**。「真實毛利(率)」「原始直接毛利」「原始毛利率」是真的毛利，維持。舊精算（摘要沒有 `netProfit`）的實際率／實際金額旁加註「（舊精算為毛利）」（案件 `actualIsGross`），數字不變。清單見 `docs/platform/plans/NOTE-REPORT-LABELS-T38.md`。
- 利潤分析的成本分項加得回「實際總成本」：精算摘要新鍵 `dispatchAbsorbedTotal`（已併入品項實際成本的承攬金額）⇒ 未併入＝dispatchTotal − 它；Excel「毛利分析」表併進「額外支出」欄（含合計列），PDF 明細另列「承攬商（未併入品項成本）」並在已併入>0 時註明「其中 X 已併入品項實際成本」。沒有該鍵的舊精算輸出不變；t36／t37 完結的案件只帶頁面鍵 `dispatchAbsorbed` ⇒ 沒有總計鍵時退回讀它（唯讀、不改資料）。
- 測試 19 題（`test_net_not_gross_fallback_2026_10_04.py` 15、`test_margin_dispatch_absorbed_2026_10_04.py` 4）。

## 1.0.29 — 2026-10-03（wip/t35c-settle-assigned）：精算快照「過期」比對口徑對口徑（精算稅基 B 的配套）
- `_live_dispatch_totals_by_quote(conn, pretax=False)`：新增 `pretax` 參數（預設不變＝含稅 grandTotal，既有三處呼叫與測試不動）；`pretax=True` ＝未稅承攬費＋外包人員。
- `_collect()` 的 `staleSettlementCount`：完結 summary 帶 `dispatchBasis='pretax'`（精算新口徑）⇒ 跟未稅現算值比；沒有（舊完結案、含稅口徑）⇒ 跟含稅現算值比。舊案不會因口徑切換全部誤報過期；口徑錯配與真正的完結後異動仍會被抓到。
- 營運報表的金額口徑**沒有改**（權責＝未稅＋人員、現金＝實付含稅，原樣）；測試 5 題（`test_reports_stale_dispatch_basis_2026_10_03.py`）。

## 1.0.28 — 2026-10-02 15:29（wip/t32-s4a-2e）：併入 d7 的「材料申請」改字（報表畫面字）
- 合併 `wip/t32-wording-d7`：營運報表的使用者可見字串「叫料」改稱「材料申請」（鍵名不動）；S4c 的備註與 `noPo` 不變。
## 1.0.27 — 2026-10-02 13:49（wip/t32-s4a-2e）：營運報表叫料明細標註「未申請採購單」（32-S4c）
- 營運報表「料件」叫料逐筆明細：來源列 `noPo` 為真時備註加「｜未申請採購單」並帶 `noPo`；金額與歸桶不變。

## 1.0.26 — 2026-10-02（wip/t32-wording-d7：叫料→材料申請改字）
- 使用者可見字串「叫料」一律改稱「材料申請」（analytics）：程式內部 key（material_order、materialOrders…）不變；只改畫面、通知、稽核顯示與報表字樣。

## 1.0.25 — 2026-10-02 09:14（wip/t32-prpo-s1-2e）：營運報表精算區塊與 Excel 的採購單分項（32-S5 追補）
- 營運報表 HTML 精算區塊在 `itemPoUnadopted > 0` 時多一列「採購單（品項尚未採用）」；Excel 毛利表的固定欄位把未採用金額併入「品項實際成本」（含合計），分項加總＝實際總成本；歷史精算不變。

## 1.0.24 — 2026-10-02 04:56（wip/t32-prpo-s1-2e）：營運報表支出桶依來源列的 bucket（32-S3）
- 營運報表「支出」逐筆（`expenses-monthly`）：額外支出來源列若帶 `bucket`（連到案件品項的採購單列＝`material`）就計入該桶，沒有帶 ⇒ 仍是「其他」（行為不變）。

## 1.0.23 — 2026-10-01 23:40（wip/t31-dispatch-approval-2e）：派發審核對報表的影響（31-A）
- 營運報表「承攬商派發」明細：派發待審核者標「｜派發待審核」並計入 `pending`；精算快照過期比對的即時派發總額（`_live_dispatch_totals_by_quote`）不計草稿／已退回派發（與應計成本同一條規則）。

## 1.0.22 — 2026-10-01（暫用號，列車取號；fix/dept-follows-sales-owner：案件部門跟業務負責人）
- 案件部門改跟業務負責人（`caseRecord.roles.sales`），不是開單者（使用者裁示 2026-10-01）：新增 `reports._case_dept／_load_user_index／_row_cr`；部門績效、部門篩選、未收款項、收款異常、支出彙總、月趨勢與首頁（stats、月趨勢、最新動態留言）同口徑。負責人只有名字或查無帳號 ⇒ 「未分類」；未填業務負責 ⇒ 開單者部門（同舊行為）。新查詢不用 json_extract（Python 逐筆解析）。

## 1.0.21 — 2026-10-01（暫用號，列車取號；wip/w3-dept-dim）
- 支出報表的部門維度（A2 無案件支出）：`_collect_expenses` 依「提供者明示的 departmentId（送出當下凍結）＞案件業務的部門＞未分類」解析部門，篩選與明細共用同一解析（篩選開啟時，無案件但明示該部門的支出不再被排除）；明細列多 `deptId`／`deptName`，回傳多 `byDepartment`（Σ＝總額，未分類排最後），各期別切片（`monthExpenseItems`／`quarterExpenseItems`）多 `byDepartment`。`departmentId` 是選填鍵：舊提供者沒有 ⇒ 行為同舊版（無案件＋篩選 ⇒ 排除）。
- 營運報表「收支」分頁：新增「支出・依部門」表與明細「部門」欄。守門：`tests/test_dept_dimension_2026_10_01.py`（7 題）、`tests/test_e2e_expense_dept_2026_10_01.py`。

## 1.0.20 — 2026-10-01（暫用號，列車取號；wip/w3-local-date）
- 本地日期（使用者 2026-10-01：凌晨建的單日期變前一天）：頁面的「今天／當月」預設值改用本地日期（共用 static/motrix-date.js）：台灣 00:00–08:00 不再得到前一天（使用者 2026-10-01 回報）；報表頁、每日任務日報等。

## 1.0.19 — 2026-09-30（暫用號，列車取號；wip/w2-recon3：與總帳差異（Part B））
- 新增 `api/ledger_diff.py`：`GET /api/reports/ledger-diff?year=&basis=`（唯讀）：逐月、逐類別 營運報表 vs 總帳已過帳金額、差額與原因分桶（未過帳草稿／稅額／手工傳票／獎金傳票／其餘）；總帳模組不在 ⇒ `glAvailable:false` 說明。營運報表頁新增「與總帳差異」頁籤（頁內巢狀元件，不動 js）。

## 1.0.18 — 2026-09-30（暫用號，列車取號；wip/w3-t27fix2）
- 匯出 PDF 姊妹的歸屬區改用常數 `_EXPORT_AREA`（不寫 module 等號字串字面量：test_module_keys_consistency 的後端掃描器會把它當權限 key）；只動寫法，行為與稽核內容不變。

## 1.0.17 — 2026-09-30（暫用號，列車取號；wip/w3-export-pdf）
- 匯出規則（使用者 2026-09-30）：銷項發票清單匯出加 PDF 姊妹；營運報表 Excel／PDF、銷項發票清單每次匯出寫稽核。

## 1.0.16 — 2026-09-30（暫用號，列車取號；wip/w1-menu-split 選單拆分）
- 選單：「營運報表」由「財務」群組搬到新群組「經營分析」（label 不變、perm 不變）；頁面加副標「管理用・即時計算（非會計帳）」。

## 1.0.15 — 2026-09-30（暫用號，列車取號；wip/w1-builder3 建構器 S2.5）
- 營運報表併入自訂模組（建構器）的金流：支出走 IP-9 `expense.entries`（提供者 `custom_module`；**現金口徑改用 entries 的選填鍵 `cashDate／cashAmount`**，沒有這兩個鍵的舊提供者行為不變）；收入（`_custom_income`）併進權責／現金兩口徑的收入逐筆，關聯到內建案件的略過（不重複計入）；缺該口徑日期的筆不列入，並在 `unavailable`（支出）與 `incomeNotice`（收入）明說「待補登」。

## 1.0.14 — 2026-09-30（暫用號，列車取號；wip/w2-report-cash）
- 營運報表預設改**現金口徑**（依收付款日、含稅；權責保留在「口徑」切換，月／季／年、Excel／PDF、月報信件同步；L1 `DEFAULT_BASIS`）。
- 收款手續費不重複扣（使用者 2026-09-30，正式機案件 MQ-202607-045：實收 263,813（銀行入帳，已扣客戶內扣手續費 15）被報表再減 15 成 263,798，且 9 月當月收入是 0（預設權責））：收款彙總的實收淨額／本期淨額＝銀行入帳、不再減手續費；手續費另以「收款手續費」列支出，損益＝收入（入帳＋手續費）－手續費－其他支出＝銀行入帳；首頁 dashboard 的實收淨額與月收款同步；報表頁「當月收入」卡片標註「現金口徑・含稅（含客戶內扣手續費）」。
## 1.0.13 — 2026-09-30（暫用號，列車取號；W1 稽核補修）
- 營運報表支出明細：現金口徑「差額待審核」的承攬商匯款與其手續費照計，但明細標 `pending`＋備註「差額待審核」（`expense.entries` 提供者可帶 `pending`）

## 1.0.12 — 2026-09-29（暫用號，列車取號；wip/payslip-void-signed）
- 收款日期歸月改用 L1 `norm_ymd`（收入明細、月收入趨勢、首頁收款月統計；「2026/09/01」等寫法不再被排除）。
- 收款資料異常清單新增兩種：`received_bad_date`（已收款但日期讀不懂）、`case_not_won`（已收款且有日期，但案件不是已成案／已結案，收入報表不算）。
- 營運報表權責視圖新增「實收對照」（`monthCashReceiptItems`／`quarterCashReceiptItems`／`yearCashReceiptItems`，依收款日、含稅，標 `recognized`）：階段比例未設或尾款未結清而權責認列 0 的已收款看得見；權責數字不動，現金口徑不附。頁面 `reports.html`／`reports.js` 顯示。
- 營運報表成本納入已付款勞報單（IP-9 `expense.entries` 名稱 `payslip`，併入「其他支出」、類別「勞報單」；報表程式不需改）。

## 1.0.11 — 2026-09-28（暫用號，列車取號；E4 wip/e-company-gate-impl 第三段）
- 本公司資料設定閘門第二道（COMPANY-SETUP-GATE §5；D CG5-M1）：每月報表排程信：開頭先問第二道，被擋 ⇒ 不寄、系統告警（每日一次）、`monthly_report_last_sent` 不前進（設定完成後補寄）；報表 Excel／PDF 的抬頭經 `company_heading`／`contact_line`（已含第二道）

## 1.0.10 — 2026-09-28（第十四班列車取號，原暫用 1.0.9；B；wip/b-payreq：請款流程）
- 月支出「其他支出」的註解更新：草稿與已駁回不計（篩選在 M01 `recognition.extra_entries`，2026-09-27 使用者裁示）；程式行為不在本模組變
## 1.0.9 — 2026-09-27 23:02（暫用號；H10 品牌設定，主持派工）
- 頁面的分頁圖示（favicon）改讀 `/api/system/branding/favicon`（L1 品牌設定，可在公司資料設定更換；沒上傳回預設圖）：`reports.html`、`devices.html`、`warranty.html`、`procurement.html`

## 1.0.8 — 2026-09-26（C；第九班之後 rebase 重編，原暫用 1.0.6，列車取號）
- 成案月份改取 M01 `case.recognition.won_month_map`（M01-PLAN §3-8 CA-O4：`helpers` 不再再匯出 M01 的 `quote_won_month_map`）；M01 不在 ⇒ {}。`norm_at`、`summarize_payment_items` 仍自 `helpers` 取用（已是 L1）

## 1.0.7 — 2026-09-26（C；第九班之後 rebase 重編，原暫用 1.0.5，列車取號）
- 收入認列、支出歸月、待補登改取 M01 的 `case.recognition`（M01-PLAN §3-6），口徑標籤改自 L1 `helpers.recognition_basis`——本模組不再 import M01 的 `helpers.recognition`。M01 不在 ⇒ 權責口徑收入附 `incomeNotice`、支出 `unavailable` 列出案件類（叫料／額外支出／派工），待補登為空；頁面的收入提示改為只顯示那一句（現金／權責兩種原因共用）

## 1.0.6 — 2026-09-26（C；第九班之後 rebase 重編，原暫用 1.0.4，列車取號）
- 稽核 D M5-S1：從 `reports.html?tab=cashier` 進來時，出納頁籤的待付款／待收款 404 也記原因（`payableSnapMissing`），快照不畫 NT$ 0

## 1.0.5 — 2026-09-26（C；第九班之後 rebase 重編，原暫用 1.0.3，列車取號）
- 頁面（`frontend/pages/reports.html`、`js/reports.js`）：M05 不在 ⇒ 收支分頁顯示 `incomeNotice`（`data-testid=income-unavailable`，比照 X-1 的支出）；財務快照的應收應付在出納佇列 404 時顯示原因（端點帶的說明，或「應收應付模組未安裝」），不畫成 NT$ 0

## 1.0.4 — 2026-09-26（C，M05；第九班之後 rebase 重編，原暫用 1.0.2，列車取號）
- M05 搬遷：`POST /api/reports/bank-reconcile` 收回 M05（`modules/arap/api/cashier.py`，路徑不變），本模組只留一行指路註解；它的 8 題隨之搬進 `modules/arap/tests`
- 收款／銷項發票改取 M05 provider（`receivables.income_items`／`receivables.tax_invoices`）；M05 不在 ⇒ 現金口徑收入附 `incomeNotice`（PDF 空表說明同句）、稅務匯出 404 並明說——不是「這個月沒有收款」

## 1.0.3 — 2026-09-26（列車取號；原暫用 1.0.2，與 c-tax-calc-2 的 1.0.2 交會，本段改 1.0.3）
- `_compute_achievement(…, name_to_id=None)`：名字⇒帳號對照可由呼叫端給；沒給才查 `users`（行為不變）。原本無條件查資料庫 ⇒ `test_achievement_uses_same_attribution_as_performance` 不帶 client 單獨跑就紅（A 在 M03 反向控制查到，主持轉 M08）；該題改給空對照，另加「給了對照就用 id 比對」一題（含解析不到的正對照）

## 1.0.2 — 2026-09-26（第八班列車取號；原暫用 1.0.1）
- 只改 import 來源（行為不變）：`api/reports.py` 的稅額函式（quote_tax_type、tax_split、LEGACY_TAX_NOTE、invoice_amounts）改自 L1 `helpers.tax_calc` import（C 的 T：稅額純函式自 M01 下沉 L1）⇒ 本模組對 M01 `helpers.quotations` 少一條相依

## 1.0.1 — 2026-09-26
- 稽核 ⑰（AUDIT-X-B-M08-move）建議與觀察：
  - `sales-orders.html`（轉址到案件管理）改歸 M01：資料端點本來就在 M01，模組不在時舊書籤不應看到「需要營運分析」（S-8）
  - `permissions` 補上本模組頁面實際檢查的 `finance`、`equipment`、`procurement`（O-4；`cashier`、`case_manage` 屬其他模組，不列）
  - dashboard.py 拿掉 GCIS 搬走後沒有用到的 urllib（O-5）
  - `tables_note`／README 寫明：精算快照過期檢查列出有效派工仍直讀 M04 的 `contractor_dispatches`、`vendor_contractors`（S-4，待 M04 提供者）

## 1.0.0 — 2026-09-26
- 模組化：自 `routers/dashboard.py`、`routers/reports.py` 搬入 `modules/analytics/api/`（PLAYBOOK §B，M08）
- 切相依（搬檔前）：
  - GCIS 統編查詢與 `/api/now` 拆到 L1 `routers/company_lookup.py`
  - 應收收入／銷項發票收集下沉 L1 `helpers/receivables.py`（M05／M06 不再 import 本模組）
  - `/api/sales-orders` 移到 M01（資料屬於 M01）
  - 精算快照過期檢查改走 IP-1 `dispatch.row`
  - 首頁、出納頁在本模組不在時明說
- 選單：營運報表、設備登載、保固追蹤、採購管理四項自 `core/menu_l1.json` 移到本模組 `pages[].menu`（欄位逐字不變）；sidebar `MODULE_PAGES` 登記本模組五頁
- `customization` 先寫 schema＋空清單：五頁的可自訂點尚未盤點（待辦，與 SPEC 分號一起）
- `provides.probes`（產品演練用）：`/api/dashboard/stats`、`/api/devices`、`/api/materials-summary`、`/api/reports/ar-aging`（稽核 ⑰ M-3）
- 首頁在本模組不在時，「有效期將屆」「90 天內到期」兩格顯示「—」＋明說，不顯示 0＋「沒有…」（稽核 ⑰ M-4）
- 地圖（map_points、map.html）歸 L1，不隨本模組搬
- V9 之前的歷史見 `docs/quick/changelog*.md`
