# 寫死項目盤點（HARDCODE-CENSUS，t62）— 朝「管理者能設定所有寫死的東西」前進

> 作者 hichan-1f，2026-10-14。基準 `origin/train/t60-int`（c917bebbc）。**靜態盤點，未跑任何測試。**
> 方法：用 grep 在前端頁面與後端找「使用者看得到、卻寫死在程式裡」的清單、門檻、文案、編號、狀態與顏色；對照已有的切片（S0–S8、BP-1～BP-5、設定中心）排除已涵蓋者。
> **不是窮盡盤點**：薪資、會計報表、地圖、開發記錄（CRM）等模組只做了抽樣（見末段「覆蓋度與盲點」）。`file:line` 是我實際開過的行號；前面有「~」的是只看到檔案、行號為大略。
> 欄位說明：想改頻率＝一般管理者多常會想改（高／中／低，是我的判斷，不是統計）；風險＝plain（純顯示）／money（影響金額、簽核或可見度）／ledger（影響帳務完整性）／legal（法定）。工量：S＝半天～1 天、M＝2～4 天、L＝5 天以上。

## 一、最優先 30 項（依「想改頻率 × 風險低 × 工量小」綜合排序）

| # | 項目 | 位置 | 模組 | 想改頻率 | 風險 | 建議落點 | 工量 |
|---|---|---|---|---|---|---|---|
| 1 | **報價單送審門檻**：有效期限 >30 天、單項毛利率 <30%、含折讓、稅別非 5% 都會要求主管審核 | `frontend/pages/quotation-form.html:1181,1533,2830–2845`（前端判斷；後端是否同一組要另外確認） | case | 高 | money | BP-2 規則（先「標記」型，擋下型過試跑）或設定中心數值；門檻放設定、提示文字走規則文案 | M |
| 2 | **單據編號前綴**：客戶 C、供應商 S、承攬商 V、請款 PR、開票 IV、完工 CN、出貨 DN、網路規劃 NP、承攬傳票 PV、進貨批次 PO；報價單 `MQ-YYYYMM-NNN` | `backend/db.py:5840`（`next_entity_code`）；呼叫端：`customers.py:80`、`suppliers.py:105`、`vendor_contractors.py:307`、`payment_requests.py:439`、`invoice_vouchers.py:445`、`completion_notes.py:425`、`shipping_notes.py:308`、`netplan/api.py:180`、`contractor_vouchers.py:458`、`inventory.py:449`；報價單 `quotations.py:213,713` | 多模組 | 中 | ledger（編號唯一性、已發出的編號不能變） | 設定值：只允許改**前綴**（英數 1～4 字）、**只影響之後新開的單**；格式（年月＋3 碼序號）固定。編號是法定／稽核證據者見第二段 | M |
| 3 | **狀態的顯示名稱與顏色**（晶片色對照） | `frontend/static/status-chip.js:6–17`；各模組狀態常數 `accounting/voucher.py:36`、`approval_queue.py:26`、`completion_notes.py:60`、`netplan/api.py:59`、`payslips.py:181` | 多模組 | 中 | plain（只改顯示字與顏色） | BP-5 狀態語意標籤（**程式用的狀態鍵不可改，只改顯示字與顏色**）；顏色先做成設定表 | M |
| 4 | **下拉選項清單（客戶類型）** `一般／VIP／潛在` | `frontend/pages/customers.html:898` | crm | 高 | plain | S5 欄位目錄的「選項清單」定義（一個清單、多處引用） | S |
| 5 | **下拉選項清單（供應商類別）** `原廠／代理商／製造商／服務商／其他` | `frontend/pages/suppliers.html:967` | supply | 高 | plain | 同 #4 | S |
| 6 | **料件分類與料號前綴**（網通設備 NET、監控 CCTV、交換器 SW、伺服器/工控 SVR、線材 CAB、其他 OTH） | `backend/helpers/part_catalog.py:12–19` | parts（L1） | 高 | ledger（前綴進料號、已有料號不能改） | 選項清單＋「新增分類只增不改前綴」；既有分類鎖前綴 | S |
| 7 | **報價單 PDF 的條款標題與固定用語**（付款條件／交貨條件／保固條件／驗收標準） | `backend/pdf_gen.py:356–363,2238–2241` | case／PDF | 高 | plain（客戶可見文字） | BP-3 PDF 宣告式範本（目前只做了頁尾／浮水印預設文字）；擴成「條款區塊標題＋預設內容」，仍走預設清單＋治理核准 | M |
| 8 | **通知文案**（簽核送審／下一層／核准／退回，共約 40 支 `notify_*`：報價單、出貨、承攬傳票、開票、請款、自訂單據、獎金…） | `backend/helpers/email_notify.py:509–1060`（每支函式內寫死主旨與內文） | 多模組 | 高 | plain | BP-4「通知動作」＋文案範本（占位符只收白名單：單號、客戶、層級、日期）；先做一套「簽核事件文案」覆蓋全部 | L |
| 9 | **預警天數**：保固到期 90 天、郵件 7 天／30 天兩級、憑證到期 30 天 | `analytics/api/reports.py:962,1697`；`helpers/email_notify.py:1538–1539`；`helpers/company_setup.py:470` | analytics／通知 | 中 | plain | 設定中心數值（有下限／上限） | S |
| 10 | **站內通知保留天數** 90 天 | `backend/helpers/audit.py:167` | 核心 | 低 | plain | 併入設定中心「保存期限」群組（已有 8 項，這是第 9 項） | S |
| 11 | **密碼最短長度**（8）與登入有效期（30 天／1 天兩種） | `backend/helpers/auth.py:54`；`routers/auth.py:439,539` | 核心 | 中 | legal／安全（只准加嚴不准放寬到下限以下） | 設定中心，**下限寫死**（例：長度不得低於 8、有效期不得高於 30 天） | S |
| 12 | **角色預設模組**（各角色樣板勾哪些模組） | `backend/helpers/module_registry.py:83`（`ROLE_TEMPLATES`） | 核心 | 中 | money（可見度／權限） | 權限勾選制計畫（2b 設計）；放寬需第二位最高管理者核准 | M |
| 13 | **逐單項毛利警示 30%**（紅字／警示） | `frontend/pages/quotation-form.html:1533`（與 #1 同組；專案毛利%已有 `project_margin.warn_pct`） | case | 高 | money（顯示警示，不改金額） | 併入 #1 的規則；與 `project_margin` 對齊成同一個設定 | S |
| 14 | **獎金分潤預設比率** 10% | `backend/modules/payroll/bonus_case.py:21`（`DEFAULT_RATE_BP = 1000`） | payroll | 中 | money | 設定中心數值（含上下限）；已建案件凍結當時比率 | S |
| 15 | **供應商／客戶匯出的欄位集**（SheetJS 三頁：客戶、料號、供應商） | `customers.html:983–999`、`parts.html:608–623`、`suppliers.html:1053–1068` | crm／parts／supply | 中 | money（料號含成本、定價欄） | BP-3（需先把這三個匯出搬到伺服端，見 BP3 設計 §2.10） | L |
| 16 | **網路規劃書的選項清單**（狀態、類別、PoE 模式、DHCP、動作等 15+ 個 `options`） | `frontend/pages/network-plan-form.html:488–619`；`topology-quick.html:248,254` | netplan | 低 | plain | 選項清單定義；但選項值被匯入／匯出與拓樸圖使用，**只開放「新增」不開放「改名／刪除」** | M |
| 17 | **完工單項目狀態** `完成／部分完成／未施作` 與預設狀態 | `modules/case/api/completion_notes.py:60`（`ITEM_STATUSES`）；`completion_note.default_status` 已在設定中心 | case | 低 | ledger（完工認列用到） | 顯示名稱可改；狀態鍵鎖死（認列邏輯用） | S |
| 18 | **費用單「急迫性」選項** `一般／急件／特急` | `frontend/js/expense-types.js:18` | case（費用單據類型） | 低 | plain | 費用單據類型編輯器已存在（`expense_type` kind）——把內建欄位的選項也變成可編輯 | S |
| 19 | **稽核紀錄頁的動作篩選清單**（189 個 `<option>`） | `frontend/pages/audit-log.html`（~） | audit | 低 | plain | 由後端稽核動作登記表產生，不再手寫（順手修，不是管理者設定） | S |
| 20 | **料件／供應商預設值**：單位預設「台」、幣別預設 NTD、付款條件預設文字 | `parts.html:186,382`；`suppliers.html`（~）；報價單「設為預設付款條件」已有 | parts／supply | 中 | plain | 設定中心「預設值」群組 | S |
| 21 | **Excel／PDF 匯出冷卻秒數**（5／30） | `backend/helpers/xlsx_out.py:18–19` | 核心 | 低 | plain | 設定中心數值（下限 1 秒） | S |
| 22 | **每日任務的類別與優先級**（預設「一般」） | `backend/modules/daily_tasks/api.py:53`（`DailyTaskIn.priority`）；頁面選單（~） | daily_tasks | 中 | plain | 選項清單 | S |
| 23 | **儀表板的 KPI 卡與圖表組合** | `frontend/index.html`（`kpi-card`／`chart-card` 區塊，~） | 首頁 | 中 | money（含金額指標） | 「儀表板建構器」：KPI 目錄（寫死）＋版面（可配）；金額 KPI 沿用現有權限 | L |
| 24 | **營運報表的工作表與欄位組成**（總覽、收支、帳齡、保固、利潤分析…約 9 張工作表） | `analytics/api/reports.py:850–1827`（單檔約 4000 行） | analytics | 中 | money／ledger（財務報表口徑） | BP-3 匯出範本延伸（先開放「選工作表／欄位」，口徑公式不開放） | L |
| 25 | **頁面欄位標籤與列表欄位** — 目前只有 5 頁接上版面引擎（供應商、案件管理、採購、設備、承攬商） | `docs/platform/plans/T60-BP1-LAYOUT-LIMITS-NOTE.md`；其餘頁（客戶、料號、報價單清單、應收應付、薪資…）尚未登記可自訂點 | 多模組 | 高 | plain（金額欄仍受權限遮蔽） | 沿用 P9 版面引擎，逐頁在 `module.json` 登記可自訂點 | M／頁 |
| 26 | **案件階段的預設清單**（案件建立時的階段樣板） | `frontend/js/case-management-core.js:4034–4057`（~；階段預設與「無階段時」行為） | case | 高 | plain | 階段樣板定義（宣告式）；需先確認現況是否已有樣板設定 | M |
| 27 | **客戶／供應商的標籤與別名詞彙** | `customers.html`、`suppliers.html`（`tags`、`alias`，~） | crm／supply | 低 | plain | 欄位目錄的選項清單 | S |
| 28 | **日期與金額顯示格式** | `frontend/static/motrix-date.js`；各頁 `toLocaleString` | 前端共用 | 低 | plain | 設定中心「顯示格式」（千分位、日期順序）；金額四捨五入規則**不在內**（法定，見第二段） | S |
| 29 | **郵件主旨前綴／署名、系統名稱** | `email_notify.py`（~，主旨格式）；頁面 `<title>`「MOTRIX 專案管理系統」 | 通知／全站 | 低 | plain | 品牌設定（公司資料頁已有部分） | S |
| 30 | **自訂模組欄位型別預設與模組建構器預設文字**（`選項一／選項二`） | `frontend/js/module-builder-elements.js:190,224` | module-builder | 低 | plain | 不需要管理者設定（建構器自己的佔位文字），列此只為完整 | S |

## 二、法定／帳務完整性：**不開放設定**（列出以免被誤當成待辦）

| 項目 | 位置 | 理由 |
|---|---|---|
| 營業稅率 5%、稅別（應稅／零稅率／免稅）、起徵點 | `backend/helpers/tax_calc.py:27`（`LEGAL_TAX_RATE`、`TAX_TYPES`）；`helpers/legal_params.py:34` | 稅法；法定參數走 `legal_params`（有版本與生效日），不是管理者設定 |
| 金額四捨五入規則（`round_half_up`）與分攤 | `helpers/legal_params.round_half_up`（多處使用） | 法定進位；改了會讓帳對不起來 |
| 二代健保補充保費、扣繳率與起扣點 | `modules/payroll/bonus_deductions.py:72` 起 | 法定費率，隨公告更新（由開發者依公告改 `legal_params`） |
| 傳票狀態機（草稿→待審核→簽核中→已核准→已過帳）與過帳後不可改 | `modules/accounting/voucher.py:36,41,51`；`ledger/periods.py:17` | 帳務完整性（H 層寫死） |
| 單據編號的**格式**（年月＋流水號、唯一、不重用）與已發出編號不可改 | `db.py:5840` | 稽核證據鏈；只開放前綴（#2），格式與規則鎖死 |
| 統一發票號碼 | （外部發票系統） | 法定外部編號 |
| 稽核留存的下限、稽核不可改的觸發器 | `helpers/audit.py`；DB 觸發器 | 威脅模型 H 層 |
| 金額遮蔽機制與「沒有金額權限看不到金額」 | `helpers/financial_mask.py` 等 | 權限核心；任何範本／版面都不能繞過 |
| 密碼長度、登入有效期的**界線**（只准加嚴） | `helpers/auth.py:54` | 安全下限（#11 只開放在下限之上調整） |
| 簽核層語意（誰能簽、自簽層是否允許）的**底線** | `helpers/tiered_approval.py`（~） | 流程狀態機建構器（BP-5）的硬護欄；其餘規則可調 |

## 三、已有切片涵蓋、不重複列入的項目（對照用）
| 已涵蓋 | 切片 |
|---|---|
| 側欄名稱、分組、順序 | BP-1 選單建構器 |
| 5 個頁面的欄位顯示／順序／名稱 | S4（版面引擎）；其餘頁見 #25 |
| 內建畫面（案件資訊、供應商）加自己的欄位 | S5 欄位目錄 |
| 供應商頁工具列按鈕（開頁、執行匯出） | S6 動作目錄 |
| 每日任務歷程 CSV、外包名冊 Excel、開票申請憑據 PDF 的欄位／頁首頁尾／浮水印（預設文字） | BP-3 |
| 費用單據類型、匯款款別、自訂模組 | 既有定義文件庫（expense_type、remit_kinds、custom_module） |
| 下載檔名、保存期限、上傳容量、擇一報價、材料卡片認列、完工單預設、專案毛利% | 既有設定中心群組（15 組） |
| 輸出版型（開票申請憑據、勞務報酬單的區塊版型） | 既有 `output_template` 版型引擎 |
| 公司抬頭、據點身分 | 公司資料（`company_identity`） |

## 四、建議的下一步（依價值／工量）
1. **選項清單定義**（#4、5、6、20、22、27、16、18）：一個「清單」定義種類＋S5/S6 同款編輯器，一次解掉 8 項、風險低、使用者最常問。
2. **簽核門檻規則**（#1、#13）：先把前端寫死的 30 天／30% 抽成設定，再接 BP-2 的規則；**先確認後端是否有同一組判斷**（若只有前端判斷，這也是一個守門缺口）。
3. **通知文案範本**（#8）：單一「簽核事件」文案範本套全部 40 支，占位符白名單。
4. **單據編號前綴**（#2）：只改前綴、只影響新單；需要與回收桶預留號、編號查詢頁一起驗。
5. **狀態顯示字與顏色**（#3）：與 BP-5 一起做，現況顏色表集中在 `status-chip.js` 一個檔案，起點低。
6. 其餘 S 項（#9、10、11、14、21、28）併成一次「設定中心補齊」。

## 五、覆蓋度與盲點（誠實版）
- 掃過：後端 `*_STATUSES` 常數、`next_entity_code` 呼叫、數值常數（`*_DAYS／MAX_／LIMIT／TTL`）、`notify_*` 函式清單、`pdf_gen.py` 的條款區塊、角色樣板、密碼與登入有效期、前端頁面的 `options`／下拉陣列、狀態晶片色表、報價單送審判斷、儀表板檔案。
- **沒有逐檔細讀**：`modules/payroll`（薪資單、獎金文案與扣項）、`modules/accounting` 報表與科目預設、`modules/lodging`、`modules/crm` 開發記錄、地圖頁、各頁面的表格欄位標題（算入 #25 的「逐頁登記可自訂點」）、郵件模板 HTML 內文逐支內容。
- 有些項目要先確認才能定工量：#1（後端有沒有同一組判斷）、#2（報價單號產生的位置與 revision `-R1` 規則）、#26（階段樣板現況）、#15（三頁 rows 與伺服端遮蔽是否一致）。
- 頻率與風險欄是我的判斷；建議用這份表請使用者勾「最想先改的 5 項」，再排班。
