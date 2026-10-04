# 承攬商派發成本「回推報價單」規格（第 36 班後；PM 窗口 hichan-6b；2026-10-04）

使用者原話：「承攬商派發成本要跟未對應品項的材料申請與額外支出一樣可以回推報價單，並且選擇採用，整體的顯示跟 UI UX 介面讓使用者能一眼看清楚，可先提供測試頁面給我測試」。

## 1. 目標
精算頁「未對應品項」區，除材料申請、額外支出外，新增**承攬商派發**列；每列可「對應到報價單品項」（offsets），對應後走與材料申請相同的規則 A：品項勾「採用」→ 該派發金額**取代**該品項估計成本；不採用 → 估計不變。取消對應＝刪 offsets 一列，回未對應（仍計入成本）。

## 2. 契約（兩視窗共同遵守；改動先回報 PM）
- `offsets` 新增 `kind: "dispatch"`，`ref` ＝ `contractor_dispatches.id`（字串），`itemId` ＝ 報價單品項 id。整張派發單歸單一品項。
- 金額口徑（35c 稅基 B）：每列金額＝`report`＝未稅承攬費＋外包人員；稅額只顯示、不計成本。同一排除規則（已取消、草稿、已退回不算；待審照計並標 pending）。
- `compute()` 輸出：
  - `unassigned.dispatches[]`：`{itemId(=派發 id), docCode, vendorName, name, status, amount(report), tax, grandTotal, pending}`
  - 每個品項新增 `dispatch: {amount, orders:[{…同上, assignedBy:"offset"}]}`
  - `totals.dispatchUnassignedTotal`（未對應）、`totals.dispatchAssignedTotal`（已對應進品項）；`dispatchTotal` 鍵語意不變＝全部派發 report 合計（守恆：未對應＋已對應＝dispatchTotal）。
- 規則 A 併入：品項實際＝（材料申請對應＋採購單＋派發對應）的合計取代估計（adopt 開時）；**不得重複計入** `totalActualCost`（派發被品項吸收後，總成本公式不可再加一次）。守恆測試：adopt 關時，未對應↔已對應互移，`totalActualCost` 不變。
- `validate_offsets`：派發 id 必須存在於目前未對應清單、品項存在、單一去處；凍結後不可改；完結時隨 `summary` 凍結（舊案沒有 dispatch offsets＝逐位相同）。
- 無 dispatch offsets 的案件，所有 summary 欄位與現況逐位相同（不變式）。

## 3. 分工
| 視窗 | 範圍 | 分支／worktree |
|---|---|---|
| hichan-04（後端） | `settlement_actuals.py`、`api/settlement_actuals.py`、`validate_offsets`、`_freeze`／`check_finalize`、測試（守恆、驗證、突變）、版本登記三處（manifest／changelog／模組 CHANGELOG）。**先出契約範例 JSON 給 hichan-05**（≤30 分） | `wip/t36-dispatch-offset-be`，`D:\開發測試檔\t36-dispatch-be` |
| hichan-05（前端） | `frontend/pages/settlement.html`＋`frontend/js`：①**先做獨立測試頁**（靜態、假資料、可互動；路徑 `frontend/pages/settlement-dispatch-prototype.html`，雙擊可開，給使用者先測 UX）②契約穩定後接真實 API、e2e（驗終點狀態＋截圖） | `wip/t36-dispatch-offset-fe`，`D:\開發測試檔\t36-dispatch-fe` |

## 4. UI/UX 要求（一眼看清楚）
1. 「未對應品項」區三類（材料申請／額外支出／承攬商派發）同一種列樣式，類型用色塊標籤（派發＝獨立顏色，不與材料混淆）；列首顯示：單號、廠商／名稱、**未稅金額（粗體）**、稅額（灰字小）、狀態、pending 徽章。
2. 每列右側「對應到品項」下拉（顯示品項名稱，不只編號）＋「採用」開關；已對應的列移到該品項下方，**整列背景改色（已對應＝淡綠底＋左側色條）**，並有「取消對應」鈕。（使用者 10/3 要求：已對應背景色要改。）
3. 品項列顯示三段拆解：估計成本 → 已對應（材料／採購／派發各自小計）→ 實際成本；採用時估計以刪除線、實際醒目；總成本上方一行守恆摘要：「未對應 X ＋ 已對應 Y ＝ Z」。
4. 頂部固定摘要列：未對應件數／金額（紅黃提示，0 件時綠色「全部已對應」）。
5. 手機寬度不破版；凍結（已完結）時全部唯讀並標示。

## 5. 規則
- 各自 worktree，不碰 `D:\MOTRIX-PLATFORM` 共用樹、不在正式機跑測試；測試暫存用完刪。
- 完成＝commit＋push 自己分支＋回報 PM（hichan-6b）：分支名、SHA、測試結果、未做項。**不上正式機、不建包**（PM 排班）。
- 對 PM 用精簡英文；有疑義先問 PM，不自行改契約。
