# 營運分析 更新紀錄

## (next) — 2026-09-30（暫用號，列車取號；wip/w3-export-pdf）
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
