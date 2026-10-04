# 案件／精算／報價 審查報告（唯讀，無程式變更）

2026-10-04｜審查者 rev-7f｜基準 `origin/platform` @ `af722139`（正式機 `345a34cd`）｜範圍：案件模組既有的報價、精算、額外支出功能與頁面。**未碰** `wip/t36-dispatch-offset-*`、共用樹、正式機。

## 結論（先看這段）

1. **最該先修（小改、真缺陷）**：營運報表用 `netProfit or grossProfit` 取淨利，淨利剛好 0 的案件會被換成毛利顯示（F-01）。
2. **最該問使用者（口徑）**：同一張精算裡，承攬商已改未稅，但品項估計仍 ×1.05 含稅、匯款手續費卻按「已付款」才算（權責混現金）。這三處口徑不一致，會再度造成「5% 金額爭議」（F-02、F-03）。
3. **最大結構風險**：精算資料只活在 `quotations.data_json` 一包 JSON 裡，沒有版本、沒有並發版本檢查、備份只留最新一份且不含額外支出等關聯表（F-04、F-07）。
4. **長久維運**：`api/quotations.py` 6623 行，精算端點夾在其中；`reports.py` 3817 行；`settlement.html` 1495 行／91KB；多份文件超過自訂 40KB 上限（F-10）。
5. 本報告共 17 項，前 10 項排名如下；其餘列在「其他發現」。**dev 庫沒有任何報價資料**（`quotations` 0 筆），所有「成長／耗時」數字都是**推估，未量測**，已標明。

| 排名 | ID | 目標 | 標題 | 工 | 險 | 需裁示 |
|---|---|---|---|---|---|---|
| 1 | F-01 | 3 | 報表淨利為 0 時被換成毛利 | S | 低 | 否 |
| 2 | F-02 | 3 | 精算成本混用現金與權責 | S–M | 中 | **是** |
| 3 | F-03 | 3 | 品項含稅 ×1.05 與承攬商未稅並存 | M | 中 | **是** |
| 4 | F-04 | 2 | 精算存檔無並發版本檢查；整包存檔可覆蓋精算 | S–M | 低 | 否 |
| 5 | F-05 | 1 | 完結時寫鎖內重算 3 次 | S | 低 | 否 |
| 6 | F-06 | 1 | 報表／儀表板熱路徑全表掃 JSON、無快取 | M | 中 | 否 |
| 7 | F-07 | 2 | 備份只留最新一份、不含關聯表；凍結只靠一個欄位 | M | 中 | **是** |
| 8 | F-08 | 3 | 邊界：負採購、0 元實際成本、被刪品項 | S–M | 中 | **是**（0 元） |
| 9 | F-09 | 1 | 公式與常數前後端各寫一份（至少 3 處 1.05／10%／1%） | L | 中 | 否 |
| 10 | F-10 | 1 | 大檔：精算端點抽出、文件拆分 | M | 低 | 否 |

---

## 目標 3：介面顯示與邏輯

### F-01｜報表淨利為 0 被換成毛利【目標 3】
- 證據：`backend/modules/analytics/api/reports.py:406`、`:407`
  `float(settle.get("netMarginPct") or settle.get("grossMarginPct") or 0)`、`int(settle.get("netProfit") or settle.get("grossProfit") or 0)`
- 情境：完結精算 `netProfit = 0`（盈虧平衡）⇒ Python `or` 把 0 當缺值，改顯示 `grossProfit`（必定 > 0，因為還要扣管理費與公益金）。該案在業務員績效、部門績效、毛利表被高估。負數不受影響。〔讀碼確認；**未實跑**〕
- 另：回傳鍵名叫 `grossProfit` 但裝的是淨利（`:407` 的註解也承認是 netProfit）。下游（儀表板、獎金）讀同名鍵時容易誤會。
- 提案：改 `settle["netProfit"] if "netProfit" in settle else settle.get("grossProfit")`（只為「舊精算沒有 netProfit 鍵」退回）；補一題 `netProfit=0` 的測試；鍵名另開項改為 `netProfit`（介面變動，晚點做）。
- 工 S｜險 低｜裁示 否。

### F-02｜精算成本混用現金與權責【目標 3】
- 證據：`backend/modules/case/settlement_actuals.py:284`（匯款手續費只算 `paid_date != ''` 的額外支出）；同函式內其餘項目走 `R.extra_entries(conn, "accrual", …)`（`compute` 內 `R.extra_entries(conn, "accrual"…)`）。承攬商匯款手續費同理（`case.remit_fee_total` 提供者，`:287`）。模組 docstring（`:6`）自述口徑是「權責、含待審核」。
- 情境：額外支出已核准但尚未出納付款 ⇒ 本體金額已進成本，手續費要等付款日才進。完結後凍結，之後付款產生的手續費不會回補；`settlement.html` 會顯示成本偏低。手續費通常小，但是原則性的口徑混用。
- 提案：二選一——(a) 手續費也走權責（以核准時預估或以 0 並明說「付款後才有」）；(b) 在精算頁手續費列標示「依付款日」，並在完結時若有「已核准未付款」的額外支出，跳出提示。
- 工 S–M｜險 中（動到凍結金額）｜**裁示：要**（哪個口徑）。

### F-03｜品項含稅 ×1.05 與承攬商未稅並存【目標 3】
- 證據：品項估計與預設 `actualCostTaxMode:'taxed_gross'`＝`halfUp(qty*cost, 1.05)`（`frontend/pages/settlement.html:973`、`:1301`；後端 `settlement_actuals.py:19`、`:31`）；採購單／材料申請金額為含稅最終金額（`settlement.html:1287` 註解）；承攬商 35c 起未稅（`settlement_actuals.py:25`）。
- 情境：同一個「實際總成本」裡，品項（含稅）＋承攬商（未稅）＋額外支出（`taxNote:"未拆稅"`，`recognition.py:429`）＝三種稅基相加。承攬商部分已按使用者 2026-10-03 裁示改 B，但品項與額外支出沒有對應裁示；START-HERE §3 的待問事項「承攬商含稅／未稅」只解決了其中一塊。
- 提案：請使用者一次定全盤口徑（品項／採購／額外支出各是未稅還是含稅；5% 非扣抵進項稅是否仍當成本）；之後用一張「稅基矩陣」寫進 SETTLEMENT-ACTUALS-SPEC。
- 工 M｜險 中｜**裁示：要**。

### F-08｜邊界案例【目標 3】
1. **負金額採購**（折讓單、退貨）：`has = purchased > 0`（`settlement_actuals.py:144`）。同品項採購單 100 與折讓 −100 ⇒ `purchased = 0`、`has=False` ⇒ 退回用**估計**，但 `sources.purchasedTotal` 仍計入負數 ⇒ 品項金額與採購類總額對不起來。〔讀碼；未造資料驗證〕提案：`has = bool(po or mats or exs)`，金額為 0 也視為有採購；補測試。S。
2. **0 元實際成本**＝「沒填」（`settlement_actuals.py:39`、`settlement.html:1322` 的 `|| this.estimateOf`）：無法表達「這項沒花錢」（贈品、免費維保）。這是已知取捨，docstring 說「是否算缺陷第 34 班待裁示」，仍未裁。**需使用者裁示**；改法：用 `null`／缺鍵代表沒填，0 是有效值（舊存檔向後相容需遷移判定）。M。
3. **被刪品項**：載入時以報價單品項為基準重建（`settlement.html:994` `origItems.map(...)`），存檔裡已不在報價單的品項被**靜默丟棄**，其手填實際成本與備註在下次存檔時消失，頁面無任何提示（後端對應有 `item_removed` 警告，但只針對材料申請）。提案：頁面列出「存檔中有、報價單已無」的品項（唯讀），完結時併入警告。S。
4. 數量 0／負：`halfUp` 已處理負數（`legal-round.js`，遠離 0，同 Decimal），前後端一致；數量 0 的品項估計為 0，不影響。無缺陷。
5. 部分付款：精算走權責，不看付款進度；唯一例外就是 F-02。

### 其他介面／訊息（歸入目標 3，詳見「其他發現」F-14、F-15）

---

## 目標 2：儲存

### F-04｜精算存檔無並發版本檢查【目標 2】
- 證據：`backend/modules/case/api/quotations.py:4301-4380`（`PUT /settlement`）。有 `write_txn` 寫鎖，但**沒有** `expected_updated_at` 之類的比對；`SettlementIn` 只有 `settlement` 與 `reason`（`:4270`）。對照整包存檔 `:1790` 有樂觀鎖。
- 情境一：兩人（業務與財務）同時開精算頁，各自改草稿，後存者整份覆蓋前者（手填實際成本、offsets、備註全被換掉），沒有任何提示。
- 情境二：解鎖編輯的整包存檔（`:1807`）只強制保留 `settlement.status`，其餘 `settlement` 內容取自用戶端送來的整份報價 JSON。若報價單頁是舊的，會把較新的精算草稿蓋回舊版。（已成案本身被 `_LOCKED` 擋，只有解鎖編輯路徑會走到。）
- 另：每次精算存檔都會 bump `quotations.updated_at`，會讓另一人正在編輯的報價單頁在存檔時吃 409。
- 提案：`SettlementIn` 加選填 `expectedUpdatedAt`（頁面載入時帶入，衝突回 409 並提示重新載入；與 `:1790` 同做法）；整包存檔路徑改為「`settlement` 一律取資料庫現值」（與 `status` 同處理）。
- 工 S–M｜險 低（選填欄位，舊頁面仍可用）｜裁示 否。

### F-07｜備份與凍結一致性【目標 2】
- 證據：`backend/archive.py:2006-2040`：每次存檔 `spawn_bg_thread(_backup_quotation)` 把 `quotations` 單列寫成 **`{quote_no}.json` 單一檔、覆蓋**，沒有版本；只含 `quotations` 這一列，不含 `case_extra_expenses`、承攬商派發／匯款單、材料付款等精算要讀的關聯表。
- 情境：
  - 還原某張已完結報價單的 JSON 後，凍結的 `summary` 是當時的值，但關聯表是還原當下的現值 ⇒ 重算（check_finalize／過期比對）一定對不上；報表的「精算過期」提示會暴增，且無從分辨是還原造成還是真的漂移。
  - 精算被重新開啟再完結幾次，前一版完結快照只存在於 `editHistory`（只有 `rev/at/by/reason`，無數字）；稽核問「上次完結的淨利是多少」答不出來。
  - 凍結＝`settlement.status=='finalized'` 一個欄位（`quote_hot_fields`，`quotations.py:267`）；沒有 `frozenAt`／內容雜湊。超級管理員改資料庫或舊程式都可繞過。
- 提案：完結時 (a) 在 `editHistory` 該筆附上 `summary` 的關鍵數字（淨利、總成本、dispatchBasis）與輸入摘要雜湊；(b) 完結事件另寫一份帶時間戳的快照檔（不覆蓋）；(c) 備份清單補關聯表或在 `DR-SOP` 寫明「還原報價單後須重跑精算核對」。
- 工 M｜險 中（備份保留量、雲端空間）｜**裁示：要**（快照保留期限）。
- 成長：單張 `settlement` 約為品項數 × 約 15 欄 ＋ `extraItems`（見 F-12）＋ `summary`，**推估**數 KB～數十 KB；尚無實資料，未量測。寫放大主要來自「每次存檔重寫整份 `data_json`」＋「每次存檔再讀整列寫一次備份」。

### 遷移安全（觀察）
- 精算形狀有三代並存：`adoptSystem` 缺鍵（32 班前）／有鍵；`dispatchBasis` 缺鍵＝含稅（舊案）／`pretax`；`offsets` 缺鍵。程式以「缺鍵＝舊行為」處理且有 legacy parity 測試（`test_settlement_actuals_legacy_parity_2026_10_03.py`），設計得當。風險是**沒有統一的版本欄**（例如 `settlement.schemaVersion`），第四代出現時要再猜缺鍵意義。提案：下一次改形狀時順便加 `schemaVersion`。S，納入 F-07。
- 孤兒資料：`delete_quotation` 只允許草稿（`quotations.py:2442`），但 `case_extra_expenses`、`case_stages` 等沒有外鍵；草稿通常不會有額外支出，**未查到實際孤兒**（dev 庫為空，未驗證正式機；正式機唯讀查詢需另行授權）。附唯讀探針建議：`SELECT quote_no FROM case_extra_expenses WHERE quote_no NOT IN (SELECT quote_no FROM quotations)`。

---

## 目標 1：長久維運

### F-05｜完結時寫鎖內重算 3 次【目標 1】
- 證據：`quotations.py:4337-4351`。同一個 PUT 內依序呼叫 `validate_offsets`（內部 `compute`，`settlement_actuals.py:234`）、`check_finalize`（`compute`，`:308`）、`fill_downstream`（`compute`，`:380`），全在 `write_txn` 持鎖期間。
- 每次 `compute` 都重讀報價 JSON、`extra_entries`（JOIN）、`material_money_rows`、`case_extras`（派發查詢＋手續費＋自訂模組）。
- 成本：寫鎖持有時間約 ×3；案件品項多時，其他人存檔會排隊（SQLite 單寫者）。**未量測**。
- 提案：`compute` 結果在同一請求內傳遞（`check_finalize` 回傳 `d`，`fill_downstream` 重用）；`validate_offsets` 只在 offsets 有變動時算。
- 工 S｜險 低（有 finalize integrity／recheck 測試守門）｜裁示 否。

### F-06｜報表／儀表板熱路徑【目標 1】
- 證據：`reports.py:272-286` 對每列 `json_extract(data_json,'$.caseRecord')` 與 `$.settlement.summary` ＋ `quote_won_month_map`、`_live_dispatch_totals_by_quote`（`:156`）；`reports.py:512-516` 另一條全表掃（結案未精算）；`dashboard.py:30-45` 對**全部**報價單（含草稿）取 `caseRecord` JSON，再於 Python 迴圈過濾。檔內沒有 cache（`grep cache` 無命中）。
- 情境：案件數成長後，每次開營運報表／首頁都解析全部 `data_json`；`caseRecord` 是每張單最大的一塊。**未量測**（dev 庫為空）。
- 提案：(a) 首頁 SQL 先以 `deal_tag`／`status` 過濾（已有索引 `idx_quotations_deal_tag`，`db.py:1036`）；(b) 以 `(COUNT(*), MAX(updated_at))` 為鍵做 30～60 秒結果快取；(c) 長期把 `settlement.summary.netProfit` 等少數熱欄位拉成欄位（類似 `settle_status`，`db.py:1030` 已有先例）。先量測再決定做到哪一步。
- 工 M｜險 中（快取失效、權限範圍要隨使用者鍵）｜裁示 否。

### F-09｜公式與常數前後端各寫一份【目標 1】
- 證據：頁面 `calcSummary`（`settlement.html:1307` 起）與後端 `compute`＋`_expected_downstream`（`settlement_actuals.py:60`、`:331`）是兩套同式；常數 1.05：`settlement.html:973,1301`、`settlement_actuals.py:19`、`quotation-form.html:1484,1519,1529`；管理費 10%、公益金 1%：`settlement.html` 與 `settlement_actuals.py:_expected_downstream`（`:331` 起）（獎金模組 docstring 也說「係數只寫在 settlement.html」，`bonus.py:22`）。
- 現況保護：完結時用容差比對（`tol_item = max(1,#品項)`，`:309`）。代價是**每次改規則要同步改兩邊＋兩套測試**，且 35c 已因此多出 `fill_downstream`、`_freeze`、舊口徑標記等補丁。
- 提案：後端 `/settlement-actuals` 直接回完整 `summary`（含 `grossProfit…netMarginPct`），頁面只負責顯示與「手填」的即時試算；常數集中成 `helpers/legal_params` 或案件模組常數並由 API 下發。
- 工 L｜險 中｜裁示 否（但建議排在口徑裁示 F-03 之後，避免做兩次）。

### F-10｜大檔與文件【目標 1】
| 檔案 | 現況 | 守則 |
|---|---|---|
| `backend/modules/case/api/quotations.py` | 6623 行（精算端點在 `:4270-4580`） | 程式 >1500 行要拆 |
| `backend/modules/analytics/api/reports.py` | 3817 行 | 同上 |
| `backend/db.py` | 5827 行 | 同上 |
| `frontend/pages/settlement.html` | 1495 行／91KB | 同上 |
| `backend/modules/case/api/case_extra_expenses.py` | 1574 行 | 同上 |
| `backend/modules/case/CHANGELOG.md` | 103KB | 文件 >40KB 要拆 |
| `docs/quick/changelog.md` | 112KB | 同上（START-HERE §4 寫 >200KB 才搬，與 40KB 守則矛盾） |
| `backend/version_manifest.json` | 497KB | 每次啟動都載入 |
- 提案（依風險由低到高）：①精算三支端點＋`SettlementIn` 搬到 `modules/case/api/settlement.py`（純機械搬移，路由前綴不變；`settlement_actuals.py` 已是獨立檔，銜接自然）；②changelog 與模組 CHANGELOG 依月份封存；③`settlement.html` 的 `<script>` 抽成 `static/settlement.js`（需注意 Alpine 初始化與 e2e 選擇器）；④`quotations.py` 其餘部分逐主題拆。
- 工 M（①②）／L（③④）｜險 低（①②）｜裁示 否。

### F-16｜測試時間瓶頸【目標 1】
- 證據：案件模組 71 個測試檔、12 個 e2e；精算相關 17 檔共 2662 行，其中 5 個 e2e 檔（21 題）各自起 `live_server` ＋ Playwright 瀏覽器（例：`test_e2e_settlement_reopen_2026_10_04.py`）。
- 觀察：精算的規則類題目（口徑、凍結、容差）多半可以在純函式／API 層驗，真瀏覽器只需覆蓋「按鈕＋終點狀態」；目前 `settlement_actuals` 的規則題已在 unit 層（conservation、legacy parity），e2e 5 檔主要是按鈕驗證，屬合理。**耗時未量測**（本次未跑測試，避免佔用 `%TEMP%`）；建議用已有的 `--durations=30`（`IMPROVEMENT-REPORT` 提過）先量，再決定是否合併同頁面 e2e 共用一次登入／種資料。
- 工 S（量測）｜險 低｜裁示 否。

### F-11｜文件過期【目標 1】
- `docs/platform/plans/SETTLEMENT-ACTUALS-SPEC.md:161`：「**實作狀態：尚未實作於 `5d76b528`**（精算頁仍是第 34 班的 A：含稅）」——稅口徑 B 已在 35c 實作（`settlement_actuals.py:25`、`:297` 註解）。
- 同檔 `:172-173`：「`check_finalize` 目前只比對…不比對 `dispatchTotal`…」——35c F1 已擴大比對（`_check_downstream`，`settlement_actuals.py:356`）。
- 同檔 `:179`「營運報表預設口徑是現金」，而精算是權責（F-02 的背景）——讀者容易混淆，應在 §10 加一張口徑對照表。
- `backend/modules/case/SPEC.md` 只有 1114 bytes，精算規則全在 plans 文件，模組自己的 SPEC 沒有指向它。
- `START-HERE` §4 的「changelog.md 缺 10/3 條目」已過期（`changelog.md:35-58` 已有）。
- 提案：由下一個動精算的視窗順手改；提供一張「文件現況 vs 程式」對照給主持。工 S。

---

## 其他發現（未入前 10）

### F-12｜`settlement.extraItems` 舊備份每次存檔都回寫【2/1】
`settlement.html:876` 註明「搬移前的唯讀備份，不再用於計算」，但 `:986` 載入、`:1403` 存檔時整份送回。每次存檔多寫、且資料永遠停在 2026-09-11 搬移當下（`db.py:3371` 的遷移）。提案：確認遷移已在正式機完成後，頁面不再回傳（保留資料庫現值不動），日後由遷移腳本一次移除。S｜低｜否。

### F-13｜頁面載入為串行瀑布【1】
`settlement.html:1020-1030`：`loadDispatches`→`loadExtraExpenseTotals`（內含 `loadActuals`）→`loadVoucherRemitFees`→`loadCustomFinance` 逐一 `await`；當 `_actualsOk` 時後兩者實際已不需要（`:1213`、`:1200` 會直接略過或只取收入清單）。提案：獨立的請求用 `Promise.all`，僅在 actuals 失敗時才走舊路徑。耗時未量測。S｜低｜否。

### F-14｜錯誤訊息不夠具體【3】
- `settlement.html:951`：`GET /settlement` 非 401 失敗一律顯示「載入失敗」，無權檢視成本（`_require_financial_view` 的 403）、案件不存在（404）、無案件權限都看到同一句。提案：顯示後端 `detail`。S。
- `settlement.html:1426`、`:1460`：儲存／完結例外訊息為 `e.message`，網路斷線時為英文瀏覽器原文。提案：包成中文＋建議（「請檢查連線後重試，資料尚未儲存」）。S。
- `quotations.py:4326`：403「精算已完結，僅超級管理員可重新修改」未告知「向誰申請」；與 `settlement.html` 的重新開啟按鈕顯示條件是否一致**未驗證**。S。
- 做得好的：完結 409 會列出具體差異欄位與「請重新整理」（`:4346`），頁面顯示 10 秒；`xeMasked` 阻擋存檔的訊息說明了原因。

### F-15｜PUT 本文未驗證形狀與大小【2】
`SettlementIn.settlement: dict`（`quotations.py:4271`）：草稿階段的 `summary`、`items` 完全採用戶端值，無大小上限、無欄位型別檢查。只有 `status=finalized` 才重算比對。報表 `reports.py:408` 與獎金讀的是 `settlement.summary`，草稿的數字理論上可被偽造後被某些報表讀到。〔報表是否只在 finalized 才用草稿 summary：`reports.py:433` 只對 finalized 計入績效，但 `:408` 的 `settleSummary` 會帶出草稿，**其他消費端未逐一查**〕提案：PUT 時 body 上限（例如 256KB）＋非 finalized 時剝除 `summary` 的衍生欄位或標 `unverified:true`。S–M｜低｜否。

### F-17｜`tol_item` 容差隨品項數放大【2/3】
`settlement_actuals.py:309`、`:341`：容差＝max(1, 品項數) 元，總成本容差再 +3（`:341` `tol_item + 3`），淨利再 +3。100 個品項的案件允許約 ±100 元差異仍可完結。這是為了兩邊各自逐品項進位的設計（可理解），但也讓「差 50 元」的真錯誤被放過。提案：若兩邊用同一套 `halfUp`（已是），逐品項進位本應 0 誤差——嘗試把容差降為固定 1～2 元並以測試語料驗證；做完 F-09 後可直接取消容差。S｜低｜否。

---

## 建議執行順序

1. **本週（無需裁示）**：F-01、F-05、F-12、F-14、F-04（先做選填版）。
2. **同步請使用者裁示**：F-02（手續費口徑）、F-03（全盤稅基）、F-08-2（0 元實際成本）、F-07（快照保留期）。一次用表單一題一決定問完。
3. **裁示後**：F-09（回傳完整 summary）、F-17（取消容差）、F-08 其餘、F-11 文件。
4. **有空檔**：F-10①②、F-06（先量測）、F-13、F-16（先量測）。

## 查證方式與限制
- 全部以讀碼為主；**未執行任何測試、未寫入任何資料**（因此無 `%TEMP%\motrix-pytest-*` 需清理）。
- dev 庫 `D:\MOTRIX-PLATFORM\backend\motrix_erp.db`（唯讀開啟）`quotations` 為 0 筆，無法量測資料成長與查詢耗時；正式機未碰。需要正式機形狀請另行授權唯讀探針（建議以 `SETTLEMENT-ACTUALS-PROBE.sql` 為底）。
- 未審：PM 進行中的派發抵銷變更（`wip/t36-dispatch-offset-be/-fe`）。F-02、F-03 與它有口徑上的交集，裁示前建議與該分支作者對一下。
- 行號以 `af722139` 為準；
