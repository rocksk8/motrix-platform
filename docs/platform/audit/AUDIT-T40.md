# 稽核：第 40 班（合併 40＋41＋42；合回前）（rev-7f 稽核，2026-10-05）

> 對象：`origin/train/t40` `3032f7ca`（先看過 `f4c7cef6`；兩者只差登記檔兩處；基底＝正式機 `4b144d85`；case 1.0.138、analytics 1.0.33）。稽核者沒寫過受稽核程式碼。
> 環境：自己的樹 `D:\開發測試檔\aud-7j`（另開 `aud-7j-old` 於 `4b144d85` 做搬移前對照，已刪）、`.venv312`、`-n 0`。建包鎖出現多次（擋掉第一輪的突變 3、4），**我沒有覆寫守門**，排隊等鎖放掉再重跑，只跑目標檔。未跑 e2e、未碰正式機。

## 0. 結論
**必修 0；建議 2；觀察 6。可以合回。**
- 搬移是真的逐字：除了預期的成本入口（成案檢查）外零差異；路由表黃金檔是用搬移前的程式重建的，逐項相同（774 筆）；儀表板「速度修整不改輸出」的黃金題在**修整前的程式上也是綠的**（證明黃金檔不是事後編的）。
- 4 個突變（成案檢查、財務檢視條件、預過濾、路由註冊）全部被既有題抓到並已還原。
- 建議項：結案 PDF 的品項成本欄漏改（v2 的 0 會印成「未填寫」）；前端稅基標籤有四個鍵名對不上伺服器。

## 1. 搬移（`api/settlement_api.py`）
| 檢查 | 結果 |
|---|---|
| 逐字？ | 把 `4b144d85` 的 `quotations.py`「Settlement」區塊（151 行）與新檔同區塊 `diff`：**只有兩處差異**——`SELECT … updated_at, deal_tag`（多取一欄）與新增 5 行成案檢查；其餘（含所有註解）逐字相同。`quotations.py` 對應刪除 148 行、加 1 行註解。 |
| 路由表／operationId／相依／驗證 | 我用搬移前的程式（`4b144d85`）重跑作者的路由表產生器（`T40_WRITE_GOLDEN=1`，在舊樹）⇒ **774 筆與作者的黃金檔 `==` 完全相同**（方法＋路徑＋operationId＋參數＋requestBody＋security）。黃金檔確為搬移前產生。 |
| 註冊順序不遮蔽 | `__init__.py` 在 `_api_quotations.router` 後立刻掛 `_api_settlement_api.router`（其餘順序不變）；`test_settlement_urls_are_still_served_by_the_settlement_endpoints_first` 以「第一個完全匹配的路由名稱」驗證，綠。 |
| import／循環 | `settlement_api` 從 `quotations` 取 `_require_financial_view`、`quotations` 不 import `settlement_api` ⇒ 無循環；`__init__` 於 `quotations` 之後匯入。 |
| 行為變更 | 僅有成案檢查（見 §2）。 |
| 登記檔（`3032f7ca`） | `docs/platform/modules.json` 加 `mod:case/api/settlement_api`；`case_read_scope.json` 的 `get_settlement` 改指 `modules/case/api/settlement_api.py`（`row_access`）。**完整**：repo 內其他以檔案路徑為鍵的登記（`dep_graph.json`、`UNIT-INDEX.md`＝工具產生）已含 `settlement_api` 且路由／行號正確；`update_settlement` 是 PUT，不在讀取範圍清單。守門 `test_case_read_scope`、`test_module_boundaries`、`test_dep_scan_controls`＋路由表題共 **37 passed**。殘留的 `get_settlement` 字樣只在註解／docstring（`quotations.py` 另一函式的說明、`api/settlement_actuals.py` 檔頭），無程式引用。 |

## 2. 完結成案檢查
- `settlement_api.py`：`status=='finalized'` 且 `deal_tag ∉ {已成案,已結案}` ⇒ **409**「還沒成案…」；放在 `require_case`／`_require_financial_view` **之後**、樂觀鎖與「已完結僅 superadmin」**之前**。看不到的案件仍先 404／403，**不洩漏案件狀態**。
- 「已結案」可完結：重新開啟（草稿）→ 再完結走通（`test_refinalize_after_reopen_is_allowed_on_a_closed_case`）。草稿存檔不受影響。
- 繞過路徑：整份存檔 `update_quotation` 強制沿用資料庫 `dealTag`（T38）；新建 `create_quotation` 已清掉 `dealTag`（T38b）；`PATCH deal-tag` 自己有狀態機。**競態**：檢查在 `write_txn` 寫鎖內讀同一列的 `deal_tag`，與 PATCH 序列化。
- `_t40_won.py`（autouse）只被 6 個「要完結」的測試檔 import，把 `W` 夾具報價單設成已成案；成案檢查有**獨立題檔**（`test_settlement_t40_be`，明確設 `deal_tag=""` 驗 409）。**突變 M1（拿掉檢查）⇒ `test_finalize_is_refused_until_the_quote_is_won` 紅**，證明 autouse 沒有蓋掉它。
- 觀察：檢查只讀 `deal_tag` **欄**；其他地方以 `COALESCE(NULLIF(deal_tag,''), json $.dealTag)` 容錯。欄位由 `save_quotation_json`／各寫入路徑同步，m006 也回填；理論上欄位空而 JSON 有值的列會被擋——N-1。

## 3. 儀表板收緊（`fin_ok = 原條件 AND can_see_financial`）
- `fin_ok = can_finance and can_see_financial(u)`；兩邊都是布林運算 ⇒ `financeVisible` 恆為 `bool`。公司全域口徑、無逐案過濾（照使用者裁示）。
- 矩陣題（作者，31 題）：superadmin／admin／sales（有無財務模組、有無 financial_view）／viewer／engineer（有無 finance 與 financial_view）。**M2（`fin_ok = can_finance`）⇒ 4 題紅**（`fin_noview`、`eng_fin_noview` 的卡片與旗標）。
- 受保護卡片：`paymentItems`、`marginTop5`、`marginComparison`、`settledSummary`、`receivableSummary`（含 total／received／unreceived／feeTotal／netReceived）——回空值，不報錯。其餘回應欄位：`pendingList`（可見者＝`can_quotation`；含 `total`、核准 `reasons`）、`warrantyWarnings`、`projectSummary`（只有狀態計數）、各計數——**不含成本／毛利／應收**。
- 前端：`index.html` 應收款項面板（內含 `paymentItems` 清單）以 `showReceivables = canFinance && financeVisible` 隱藏；`receivedPct` 在不可見時回 `null`（目前頁面未使用，不會顯示「null%」）；舊 API 無此鍵時維持原樣。
- **仍對非財務帳號洩漏全公司金額的端點（只回報，使用者另有待辦）**：
  1. `GET /api/dashboard/monthly`、`/expenses-monthly`：只用 `can_finance`（角色或 finance 模組），**沒有** `can_see_financial` ⇒ 只有 finance 模組、沒有財務金額可視者，仍取得全公司月收款／月支出。
  2. `GET /api/dashboard/funnel`：`can_quotation` 即可，回報價單金額（待追蹤、到期報價）與贏單率，全公司。
  3. `stats.pendingList`：`can_quotation` 即可，含各待審報價 `total` 與核准理由（理由文字可能含淨利率門檻）。
  4. `GET /api/materials-summary`（`procurement`／`case_manage`）：材料單價類金額，全公司。
  5. `/api/dashboard/activity-feed`、`/api/devices`：未見金額欄位（未逐欄檢查；列為待查）。

## 4. 預過濾速度修整
- 輸出相同：作者的黃金檔「由修整前的程式產生」——我**在 `4b144d85`（修整前）把該黃金題複製進去跑：通過**（⇒ 黃金檔是真的修整前輸出，不是事後依新程式編的）；新樹同題通過；鍵＝「使用者|部門」含 admin／sales／viewer 與部門篩選。
- 解析一次：`_cr_memo` 以 `id(r)` 為鍵、例外也存起來各段照舊吞掉；結構題（每列只解析一次）通過。
- 舊列：`approval_json` 只對 `status IN (待審核,簽核中)` 取、`settlement_json` 只對 `deal_tag IN (已成案,已結案)` 取，其餘 NULL；回應端本來就只在這些列讀它們（`json.loads(r["approval_json"] or "{}")` 對 NULL 得 `{}`）⇒ 等價。
- **M3**（把預過濾的 `status IN ('待審核','簽核中')` 改成只剩 `'待審核'`）⇒ 黃金題**紅**。

## 5. 稅基／PDF 稅基說明行（文字、不改數字）
- 稅基標示只加文字：`TAX_BASIS` 靜態字典、`_cost_basis_note`（PDF）與前端 `.stl-basis*` 標籤；`SETTLEMENT_ROWS` 11 個標籤逐字不變（守門 `test_settlement_rows_labels_are_untouched` 綠）；`ESTIMATE_RATE == 1.05` 與 `estimate_amount(10,1000)=10500` 被釘住。舊精算（無 `dispatchBasis`）才加「承攬商：含稅（舊精算口徑）」說明；新口徑已有稅額說明行不重複。
- **S-2（建議）｜前端稅基標籤的鍵名與伺服器不一致。** 伺服器 `TAX_BASIS` 鍵是 `itemEstimate`／`purchase`／`material`／`extra`／`dispatch`／`remitFee`／`customExpense`；前端 `taxBasis(key)` 查的是 `estimate`／`po`／`material`／`extra`／`dispatch`／`remit`／`custom`。只有 `material`、`extra`、`dispatch` 對得上；`estimate`、`po`、`remit`、`custom` **永遠退回前端常數**。目前文字剛好同義，但一旦伺服器改字，四項不會跟，且畫面上會出現兩種寫法（伺服器長句 vs 前端短句）混在一起。提案：前端查表前先把鍵對應（`estimate→itemEstimate`、`po→purchase`、`remit→remitFee`、`custom→customExpense`），並補一題「前端查得到的每個鍵伺服器都有」。S。

## 6. 零值顯示讀者（`schemaVersion >= 2`）與公益金文字
- 已改且一致：案件頁（`case-management-fin.js` `caseSettleItemFilled`／`caseSettleCharityText`）、營運報表詳情（`reports.js` `stlItemFilled`／`stlCharityText`）、結算頁（`Number(saved.schemaVersion) >= 2`，修掉上輪 N-1）。三處資料路徑相同（`selected.data.settlement`、`settlement.settlement`）。
- **S-1（建議）｜結案報表 PDF 的品項成本欄漏改。** `pdf_gen.py:2655`：`money(it.get("actualTotalCost")) if it.get("actualTotalCost") else "未填寫"`——v2 精算裡**明確填 0 的品項會印成「未填寫」**，與案件頁／報表／結算頁（顯示 0）不一致，而這份 PDF 是給人簽核留存的。提案：同一規則（`settlement.schemaVersion>=2` ⇒ 數字含 0＝已填；舊存檔 0＝未填）。S。
- 公益金文字：負值（36–38 班凍結的舊值）顯示帶號金額、不再「− −50」；≥0 維持「− 金額」。

## 7. 其他讀者／上輪項目複查
- 上輪 T39 S-1：PDF／報表的預留說明改為「原始預估已扣預留 R；其中未被實際成本抵用 Y；其他 Z」，Y＝clamp(R − max(C,0),0,R)，C＝原始直接毛利−實際毛利；數字題（5,000／0／+50、3,000／+20）通過。**N-2**：C 含所有「實際直接成本比報價多」的來源（品項超支、承攬商等），不只間接成本單據——是「先抵用」的啟發式（程式註解已寫「不做類別對應」）。
- 上輪 T39 S-2：`original_side()` 對報價存的負公益金也取下限 0，預留隨之重算、原始淨利不變（作者題通過）。
- **N-3**：營運報表 Excel「毛利分析」第 23、24 欄的語意在 T39 上線後又改了（23：預留→「預留未被實際成本抵用」、24：差額−預留→差額−未抵用），表頭字也改；若有人工具依賴 T39 的欄意會看到數值變動（欄位位置沒動）。
- **N-4**：作者的 e2e（稅基標籤、成案檢查頁面行為）與其他會完結精算的 e2e（`test_e2e_settlement_*`）我沒跑（建包期間）；它們若不在 `_t40_won` 範圍而依賴「W 夾具可完結」，要靠列車全量證實。
- **N-5**：`frontend/index.html` 的 `receivedPct` getter 目前沒有任何使用者（死碼）；無害。

## 8. 突變
| # | 突變 | 結果 |
|---|---|---|
| M1 | 拿掉成案檢查（`settlement_api.py`） | **紅 1**（`test_finalize_is_refused_until_the_quote_is_won`） |
| M2 | `fin_ok = can_finance`（拿掉 `can_see_financial`） | **紅 4**（矩陣＋旗標題） |
| M3 | 預過濾少一個狀態（`'簽核中'`） | **紅 1**（修整前黃金題） |
| M4 | `settlement_api.router` 不註冊 | **紅 2**（路由表黃金、精算網址順序題） |
各突變後 `git diff --stat` 為 0 行（已還原）。

## 9. 清理
`%TEMP%\motrix-pytest-aud7j`、背景腳本／輸出已刪；`aud-7j-old` 樹已移除；本樹僅本報告。建包鎖檔未動。
