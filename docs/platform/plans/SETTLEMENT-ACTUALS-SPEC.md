# 完結精算「實際成本」單一來源規格（第 33 班；2e；docs only）

2026-10-02。起因：使用者回報「完結精算時需要帶入實際支出，有申請的料件、額外支出要顯示在精算頁；有些料件算在別處沒有沖銷，成本重複計算」。
主持裁示：**沖銷規則 A**——品項有實際採購（採用的採購單，或已對應的材料申請）⇒ 實際**取代**該品項估計；沒有採購 ⇒ 仍用估計；完結精算「採用」預設開。精算頁重做列第 33 班（不併第 32 班）。
本檔只寫規格，不改程式。

> **文件狀態（2026-10-03 更新，hichan-0c；docs only）**
> - 本檔原只存在於未併入的分支 `origin/wip/t32-material-link-spec-2e`（`9ea4c0d4`），但 `settlement_actuals.py`、`api/settlement_actuals.py`、conservation 測試都引用 `docs/platform/plans/SETTLEMENT-ACTUALS-SPEC.md`；現已併入 platform。§0–§8 為 2026-10-02 原規格內文（未改動，其中「現況」「待做」是**當時**的樣子）；**§9 已改寫為使用者裁示紀錄**；**§10 新增：實作現況與已知差異**（以 `origin/platform` @`5d76b528`＝正式機 `326e6676` 為準）。
> - 使用者裁示的完整彙整與出處在 [`USER-DECISIONS.md`](USER-DECISIONS.md)（D8／D9／D10／D13 等）。
> - 實作進度：A1–A4、B1、B2 隨第 33 班 A 包上線（`8ae8b8cc`，2026-10-03 04:32）；第 34 班（`6927e222`，2026-10-03 15:34）把派發、匯款手續費、自訂支出納入端點（`costExtras`／`totals`）。

## 0. 現況（查證結果，2026-10-02 @ wip/t32-s4a-2e）

精算頁（`frontend/pages/settlement.html`，瀏覽器內 `calcSummary()` 算，PUT 存進 `quotations.data_json.settlement`，完結後 `summary` 凍結）：

```
totalActualCost = itemActualTotal + itemPoUnadopted + extraTotal + dispatchTotal
  itemActualTotal  = Σ 品項實際（預設 ＝ 報價成本 qty×cost×1.05；手改或「採用」採購單金額才換掉）
  itemPoUnadopted  = Σ 沒採用的品項的「採購單連結金額」（32-S5）         ← 疊在估計之上 ⇒ 重複
  extraTotal       = 額外支出 extraOnlyAmount（沒連品項的）＋ 匯款手續費 ＋ 自訂模組支出
  dispatchTotal    = 派發／外包
  （材料申請：完全沒有）
```
營運報表／總帳（`recognition.material_entries`／`extra_entries`，`gl_events`）：只有實際採購、沒有估計；連到有效採購單的材料申請略過金額（S4c 單一歸屬）。

探針數字（品項 a：計畫 10、成本 1000；採購單 3×1000＝3000）：

| 情境 | 報表 | 總帳 | 精算（未採用／全採用） |
|---|---|---|---|
| 採購單連品項 | 3000 | 3000 | 14025／3525 |
| ＋同一筆又開材料申請（沒互連） | 6000（重複） | 6000（重複） | 14025／3525（材料申請被忽略） |
| 材料申請連到該採購單 | 3000 | 3000 | 14025／3525 |

結論：(a) 精算在採用前把估計與採購**同時**算（+10500）；(b) 精算完全沒有材料申請；(c) 精算與報表／總帳是三套各自的算法，會漂。

## 1. 目標與不變式

1. **單一來源**：精算頁、營運報表、總帳取「實際採購」只經同一組後端函式；精算頁不再在瀏覽器自己加總。
2. **守恆**：同一案件、同一口徑（權責），`精算的採購類金額（採用的＋未對應）＝ 報表（料件類：材料申請＋額外支出）＝ 總帳 E11＋E12`；每筆錢**只出現一次**。
3. **沖銷規則 A**：品項有實際採購 ⇒ 實際取代估計；沒有 ⇒ 估計。
4. **歷史案件逐位不變**：沒有 `itemId` 連結、沒有材料申請的案件，新算法的每個欄位與舊算法相同（§6 證明方法）。
5. 錢不憑空消失：任何一筆可計入的採購金額必須落在「某品項的實際」或「未對應清單」二者之一。

## 2. 端點：`GET /api/quotations/{quote_no}/settlement-actuals`

權限＝與 `get_settlement` 相同（`require_case` ＋ `_require_financial_view`；看不到財務金額 ⇒ 403，頁面退回舊路徑，見 §5）。只讀，不寫。

回傳（金額皆整數元，與報表同一進位：`MotrixLegalRound.halfUp` 的後端對應 `helpers.money`）：

```json
{
  "quoteNo": "MQ-…", "basis": "accrual", "asOf": "2026-10-02T15:47:00",
  "items": [{
    "itemId": "a", "description": "交換器", "planQty": 10, "unit": "台",
    "estimate": {"unitCost": 1000, "amount": 10500},
    "po":       {"amount": 3000, "lines": [{"docCode": "PO-…", "line": 1, "status": "已核准", "amount": 3000, "pending": false}]},
    "material": {"amount": 0,    "orders": [{"itemId": "<材料申請列 id>", "docCode": "MO-…", "name": "…", "status": "已核准", "amount": 0, "pending": false, "assignedBy": "link|offset"}]},
    "purchased": 3000,
    "hasPurchase": true,
    "actual": {"amount": 3000, "source": "purchase", "replacedEstimate": true}
  }],
  "extra": {"onlyAmount": 0, "rows": [{"id": 12, "docCode": "EX-…", "category": "雜項", "amount": 0, "status": "已核准", "pending": false}],
            "remitFeeTotal": 0, "customExpenseTotal": 0},
  "unassigned": {
    "materials": [{"itemId": "K", "docCode": "MO-…", "name": "…", "amount": 800, "status": "已核准", "pending": false, "noPo": true}],
    "extras":    [{"id": 12, "docCode": "EX-…", "category": "料件", "amount": 500, "status": "已核准", "pending": false}]
  },
  "offsets": [{"kind": "material|extra", "ref": "K", "itemId": "a"}],
  "totals": {"itemActualTotal": 0, "itemPoUnadopted": 0, "extraTotal": 0, "materialUnassignedTotal": 0, "purchasedTotal": 0, "pendingTotal": 0},
  "warnings": [{"code": "item_removed|over_plan|…", "ref": "…", "message": "…"}]
}
```

欄位定義：
- `estimate.amount`＝`halfUp(qty × cost, 1.05)`（精算頁現行預設；後端用同一函式，單測固定與前端同值）。
- `po.amount`＝`purchase_items.item_actuals(rows, live=…)`（採購單連品項、COUNTED 狀態；已刪品項不算——回到額外支出，既有規則）。
- `material.amount`＝**材料申請且連品項、沒有有效採購單連結**的金額（有效採購單連結者金額已在 `po`，單一歸屬）。歸屬來源：`quoteItemId`（`assignedBy=link`），或精算 `offsets`（`assignedBy=offset`，§4）。
- `purchased = po.amount + material.amount`；`hasPurchase = purchased > 0`。
- `actual`：`hasPurchase` 且 `adopt` ⇒ `{amount: purchased, source: "purchase", replacedEstimate: true}`；否則 `{amount: 手填實際（精算已存）或 estimate, source: "estimate"|"manual"}`。`adopt` 由精算資料帶（§5）；端點本身回兩種都算好（`actualIfAdopted`、`actualIfNot`），頁面切換不必再打 API。
- `unassigned.materials`：材料申請沒有 `quoteItemId`／品項已刪、也沒被 `offsets` 指派者（含 `noPo`）。`unassigned.extras`：額外支出沒連品項者（＝`extra.rows`，其中類別為料件的標示給使用者沖銷）。這兩份金額進 `totals`，**一律計入成本**（沒對應不等於不算）。
- 狀態口徑與報表一致：已核准＋待審核／簽核中（`pending:true` 標示、計入）；草稿／已退回／已取消不計。舊單（沒有疊加審核列）計入。

`totals.itemPoUnadopted`：保留鍵名（報表、獎金、PDF 讀它）。新規則下 adopt 預設開 ⇒ 通常為 0；只有使用者明確關掉採用時 ≠ 0（§5）。

## 3. 與 recognition／GL 共用函式（三處不漂）

1. 在 `recognition.py` 抽出**唯一的**逐筆判定原語（不新增第二套規則）：
   - `material_money_rows(conn, quote_no_or_None)` ⇒ 每筆材料申請 `{itemId, quoteNo, quoteItemId, amount, state: counted|pending|excluded, po_linked: bool, noPo: bool}`。`material_entries()` 改成**它的投影**（行為不變，既有 S4c 測試守住）；精算端點用同一份。
   - `extra_entries(conn, basis)` 已有 `linkedItem`／`itemId`；精算端點用它的列，不另算（`item_actuals` 與它同源已於 S3 守恆測試證明）。
2. 精算端點 `modules/case/settlement_actuals.py`（新檔）：`compute(conn, quote_no, offsets, adopt_map)` ＝ 純函式，只組合上述原語與 `purchase_items`；不含任何自己的金額規則。
3. **漂移守門測試**（合約測試，必跑）：對一組產生的情境（PO 連／不連品項、材料申請連／不連採購單、草稿／待審／核准／已取消、品項被刪、$0、舊單、手續費）逐一斷言：
   `settlement.purchasedTotal + unassigned + extra.onlyAmount ＝ Σ report(材料＋額外支出，權責) ＝ GL(E11＋E12)`；現金口徑另一組（材料申請匯款 ⇒ E12b）。任何一邊改規則而另一邊沒跟，這題立刻紅。
4. 規則改動的路徑只有一條：改 `recognition` 原語 ⇒ 三處同時變。

## 4. 沖銷動作（未對應清單 → 品項）

- 動作＝使用者在「未對應」清單對某筆材料申請／額外支出選一個報價品項。**不改原單據**（核准後的材料申請改 `quoteItemId` 屬實質欄位，要重送審；精算不該逼人重簽）。
- 存放：`settlement.offsets = [{kind, ref, itemId}]`（隨精算存；完結時隨 `summary` 凍結）。`ref`：材料申請＝其列 id；額外支出＝單據 id（整張單歸到同一品項；多品項拆分不做，列為已知限制）。
- 效果：該筆從 `unassigned` 移到該品項的 `material.orders`／`po`-類（`assignedBy=offset`），並參與規則 A；總額不變（守恆測試含 offsets 情境）。
- 後端驗證（PUT 時）：`itemId` 必須是報價現有品項；同一 `ref` 只能有一個去處；`ref` 必須存在於當前未對應清單。
- 取消沖銷＝刪 offsets 一列；回到未對應（仍計入）。

## 5. 頁面改法（`settlement.html`）

1. 載入：取代 `loadItemPo()`＋`loadExtraExpenseTotals()` 為一次 `GET settlement-actuals`（再加現有 `loadDispatches`、`loadVoucherRemitFees`、`loadCustomFinance`——派發與匯款手續費、自訂模組暫不併入端點，列為後續）。
2. 品項表：新增「採購／材料申請」欄（顯示 po／material 小計與明細展開）、「實際」欄顯示 `actual.source`（估計／採購／手填）；`採用`鈕保留：預設開（有採購的品項）；關掉＝手填實際並顯示「採購金額 X 未採用」警示。
3. 新區塊「未對應品項的材料申請與額外支出」：清單＋每列「對應到品項」下拉（寫入 offsets）；列出 `noPo` 標註（沿用「該材料申請未申請採購單」）。
4. 彙總 `calcSummary()`：`itemActualTotal` ＝ Σ `actual.amount`（依 adopt 狀態取兩組預算好的值）；`extraTotal` ＝ `extra.onlyAmount`（扣掉已被 offsets 取走者）＋手續費＋自訂；`materialUnassignedTotal` 併進 `extraTotal` 顯示行「未對應材料申請」；`itemPoUnadopted` 僅在關掉採用時 ≠ 0。**鍵名與既有 summary 完全一致**（`reports.py`、`bonus*.py`、`pdf_gen.py` 讀的鍵不動）。
5. 失敗退回：端點失敗／無財務檢視 ⇒ 沿用舊路徑（`totalAmount`，不讓錢消失）並顯示警示「採購資料未載入」。
6. 已完結且有凍結 summary：只讀凍結值，**不重算**（歷史完結案數字不變）；超級管理員重開（status≠finalized）才用新算法。
7. 已存草稿的 `adoptSystem` 三態：未設（新品項）⇒ 預設開；明確 `false`（舊草稿使用者自己關過）⇒ 保持關，頁頂提示「有 N 個品項的採購金額未採用」。

## 6. 對歷史案件的相容與證明方法

不變式：**沒有 `itemId` 連結、沒有材料申請、沒有 offsets 的案件 ⇒ 新算法每個 summary 欄位與舊算法逐位相同。**
證明方式（三層）：
1. **參考實作對照（金標準）**：測試內保留舊公式的 Python 參考實作 `legacy_total(settlement_saved, extras, remit, custom, dispatch)`（逐字照搬現行 `calcSummary()`）；對一個語料（既有測試夾具＋以正式機形狀合成的案件：手填實際、含稅模式三種、額外支出各狀態、手續費、派發）逐案斷言 `new == legacy`。
2. **頁面對照**：e2e 開同一案件，讀 `summary` 全部鍵，與 `legacy_total` 比（延續既有 `test_history_case_without_links_settlement_is_unchanged`，增加三種含稅模式與已存草稿）。
3. **完結案凍結**：對已 `finalized` 的語料，頁面顯示的 `summary` 與 DB 內凍結值逐位相同，且不呼叫新端點算出的值覆寫。
另：新端點在無連結案件回 `po.amount=0、material.amount=0、hasPurchase=false` ⇒ `actual=estimate`，`unassigned.extras` ＝ 全部額外支出（與舊 `extraTotal` 同額）。

## 7. 測試與 e2e 清單

後端（每檔單程序）：
- `test_settlement_actuals_shape`：回傳形狀、權限（無財務檢視 403、他案 404）、金額型別。
- `test_settlement_actuals_rule_a`：有採購取代估計；無採購用估計；部分採購（A：仍取代）；採用開／關兩組預算值。
- `test_settlement_actuals_conservation`（漂移守門）：§3.3 全情境，三處金額相等；含權責與現金、offsets、品項被刪、$0、待審。
- `test_settlement_actuals_legacy_parity`：§6.1 語料逐位對照。
- `test_settlement_offsets_api`：PUT 驗證（品項存在、單一去處、ref 存在）、凍結後不可改。
- `test_recognition_primitive_projection`：`material_entries` ＝ `material_money_rows` 投影（既有 S4c 全過）。
- 突變：規則 A 判斷、單一歸屬、offsets 移轉、狀態口徑（草稿計入）、舊單；每個都要被至少一題殺掉。
e2e（一檔一流程＋截圖）：採購單連品項＋材料申請（連／不連）→ 精算頁看到取代規則與未對應清單 → 沖銷 → 採用開／關 → 存草稿重開 → 完結 → 報表與總帳同額；另一題歷史案件不變（含完結凍結）。

## 8. 分片與估時（單人，含測試與突變）

| 片 | 內容 | 估時 |
|---|---|---|
| 33-A1 | recognition 原語抽出（`material_money_rows`）＋投影測試（行為零變化） | 0.5 天 |
| 33-A2 | `settlement_actuals.py` 純函式＋端點＋形狀／規則 A 測試 | 1 天 |
| 33-A3 | 漂移守門測試＋歷史語料對照＋突變 | 1 天 |
| 33-A4 | offsets（PUT 驗證、凍結、存放）＋測試 | 0.5 天 |
| 33-B1 | 精算頁改版（載入、品項欄、未對應區塊、彙總、退回路徑、三態採用） | 1.5 天 |
| 33-B2 | e2e 兩檔＋截圖＋歷史不變頁面對照 | 1 天 |
| 33-C | 文件、CHANGELOG、modules.json、版本、d7／c7 接洽（字級與守門） | 0.5 天 |
合計約 6 天；A1–A4 可先上線而不動頁面（端點與合約測試先行，頁面隨 B 片）。

## 9. 使用者裁示紀錄（原「需要使用者再裁示的口徑」；2026-10-03 改寫）

原 §9 的七題在 2026-10-02 夜～深夜由使用者以選單裁示（出處見 [`USER-DECISIONS.md`](USER-DECISIONS.md)）。下表「裁示」欄為 `TRAIN31-BACKLOG.md`「使用者裁示 2026-10-02 夜（第33班；全部採建議選項）」段的原文；其餘欄為本檔補充。**沒有逐字紀錄的項目標明「預設」或「推導」，不當成使用者原話。**

| # | 題目（原 §9） | 裁示 | 日期／出處 | 實作位置 |
|---|---|---|---|---|
| 1（＝D8） | 關掉「採用」時採購金額怎麼算 | 「D8 手填實際取代、採購金額不另加（只警示）」 | 2026-10-02 夜；BACKLOG | `settlement_actuals.compute`：`UNADOPTED_IGNORE`（預設）；`itemPoUnadopted` 新模式恆 0 |
| 2 | 部分採購（採購 3／10） | **推導，非單獨裁示**：依規則 A，實際只算已採購部分；完結時頁面提示「已採購數量低於計畫」（USER-DECISIONS-TRAIN33 §A：「規則 A 的直接結果，不再問」） | 2026-10-02；a3 彙整 | `compute`：`has and adopt ⇒ purchased` |
| 3（＝D9） | 完結時未對應清單不為空 | 「D9 未對應支出只警示不擋完結」 | 2026-10-02 夜；BACKLOG | 未對應列計入成本、完結不擋 |
| 4 | 額外支出整張歸單一品項 | **預設，未見使用者推翻紀錄**（USER-DECISIONS-TRAIN33 §C：「可接受；多品項混合單據留在『未對應』」，標註「使用者回來可推翻」） | 2026-10-02；a3 彙整 | `offsets`：`kind=extra` 整張單一個去處 |
| 5（＝D10） | 完結時後端重算比對 | 「D10 後端重算，差異超過進位誤差拒絕完結」 | 2026-10-02 夜；BACKLOG | `check_finalize`（33-A5；範圍見 §10.2） |
| 6 | 派發、匯款手續費、自訂支出是否併入端點 | 排第 34 班（USER-DECISIONS-TRAIN33 §A）；稅口徑：第 34 班裁示 A「維持頁面口徑、歷史不變」，端點同時輸出 `dispatchGrandTotal`（含稅）與 `dispatchReport`（未稅）供漂移守門；**之後使用者改裁 B，見下一段** | 2026-10-02～10-03；BACKLOG「第35班待問使用者：精算頁承攬成本含稅／未稅口徑」 | `case_extras()`（`costExtras`、`totals.dispatchTotal`／`dispatchReport`／`remitFeeTotal`／`customExpenseTotal`） |
| 7（＝D13） | 待審核（簽核中）金額 | 「D13 待審核計入並標示，完結有待審核只警示不擋」 | 2026-10-02 夜；BACKLOG | `pending` 標示；`pendingTotal` |

**稅口徑 B（2026-10-03，使用者裁示；經主持轉述，原話待主持補入 `USER-DECISIONS.md`）**：精算頁承攬成本改依**正式口徑＝未稅承攬費＋外包人員**，與營運報表／`recognition.dispatch_entries`／總帳一致；稅額在總帳是進項稅額（資產），不是成本。**實作狀態：尚未實作於 `5d76b528`**（精算頁仍是第 34 班的 A：含稅 `grandTotal`）。同一裁示並含「完結時後端重算（D10）」與「財務／出納脫鉤之後再決定」（後者與本規格無關）。

## 10. 實作現況與已知差異（2026-10-03；`origin/platform` @`5d76b528`＝正式機 `326e6676`）

### 10.1 與 §0–§8 對照的實作位置
- 端點：`GET /api/quotations/{no}/settlement-actuals`、`POST …/settlement-actuals/preview`（`modules/case/api/settlement_actuals.py`；權限＝案件可見＋`can_see_financial`，看不到案件＝404、無財務檢視＝403）。
- 計算：`modules/case/settlement_actuals.py::compute`（純組合，只用 `recognition.material_money_rows`、`recognition.extra_entries`）；沖銷驗證 `validate_offsets`；完結比對 `check_finalize`；凍結 `_freeze`。
- 總成本式（與頁面 `calcSummary` 同一條）：`totalActualCost = itemActualTotal + itemPoUnadopted + extraTotal + materialUnassignedTotal + remitFeeTotal + customExpenseTotal + dispatchTotal`。

### 10.2 與原規格內文的差異（均為功能等價或後續班次的增補，非缺陷）
1. §2 回傳形狀：`remitFeeTotal`／`customExpenseTotal` 實作在 `totals` 與 `costExtras`（第 34 班併入），不在 `extra` 內。
2. §9 Q6 已納入端點：`totals.dispatchTotal`（含稅 `grandTotal`＋人員）與 `dispatchReport`（未稅＋人員）並列；稅口徑改 B 見 §9。
3. **§9 Q5／D10 的比對範圍**：`check_finalize` 目前只比對 `itemActualTotal`、`itemPoUnadopted`、`extraTotal`（含未對應材料申請）、`purchasedTotal`；`dispatchTotal`、`remitFeeTotal`、`customExpenseTotal`、`totalActualCost`、`grossProfit`／`netProfit` **不比對**（2026-10-03 對帳稽核 F1：偽造 `summary` 可完結並凍結）。擴大比對範圍已交 35c（d5），以本檔 §9 D10「後端重算，差異超過進位誤差拒絕完結」為準。
4. `manual_actual`：0、空字串、null 一律視為「沒填」（歷史相容；0 元實際成本在頁面上本來就無法持久）；是否算缺陷仍待使用者裁示。
5. `unadopted=add`（舊行為，採購另加）模式在程式裡保留但未被任何呼叫使用。

### 10.3 營運報表與精算的比對口徑（請讀這段再比數字）
- 精算**固定權責口徑**（含待審核，標 `pending`）。
- 營運報表**預設口徑是現金**（`helpers/recognition_basis.py`：`DEFAULT_BASIS = "cash"`；使用者 2026-09-30 裁示：預設現金口徑，依收付款日、含稅；權責保留在切換裡）：材料申請未付款不入、承攬商要有已匯款單才入。
- ⇒ 拿預設報表對精算會看到差異屬正常。**要比對請把報表右上「口徑」切到「權責」**：採購類金額（PO＋材料申請＋額外支出）在精算、認列層、報表（權責）、總帳事件、過帳後試算表逐位相等。
- 對帳算例（2026-10-03 稽核；單位元；探針用合成資料）：

| 情境 | 精算 | 報表（權責） | 報表（預設現金） | 說明 |
|---|---|---|---|---|
| S1 PO 3000＋PO 額外支出 500＋材料申請連品項 800＋未對應 250 | 4550 | 4550 | 3500 | 現金口徑＝材料申請未付款不入 |
| S2 ＝S1＋承攬商未稅 10000（稅 5%）＋人員 2000 | 17050 | 16550 | 3500 | 精算含承攬商稅 500；改稅口徑 B 後兩者相等 |
| S3 只有品項 a 採購、b 無採購 | 3525 | 3000 | 3000 | 差 525＝b 的估計（規則 A，設計如此） |
| S5 手填 700 且不採用（採購 1050 被取代） | 4200 | 4550 | 3500 | D8：採購金額不進精算，差 350 |
| S6 完結後再核准採購單 +200 | 4550（凍結） | 4750 | 3700 | 完結＝快照；`live` 欄提示 |

- 完整對帳表與重現方式：`docs/platform/audit/AUDIT-0C-settlement-recon.md`（分支 `origin/audit/settlement-recon-0c`，尚未併入 platform）。

### 10.4 仍待處理
- 稅口徑 B 的實作（§9）。
- `check_finalize` 比對範圍擴大（§10.2-3；35c）。
- 規格與裁示檔本次併入 platform；後續新裁示請同步寫進 `USER-DECISIONS.md`。
