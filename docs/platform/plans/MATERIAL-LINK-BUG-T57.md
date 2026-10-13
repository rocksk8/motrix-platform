# 材料卡片「帶入並連結」後仍顯示（未連結）、已申購／已到料無法勾——靜態分析（僅文件）

> 日期：2026-10-13　作者：hichan-5e　依據：`origin/platform` `5af458d83`（MS1，case 1.0.180）的程式靜態閱讀＋prod 唯讀資料（1c 提供：案件 MQ-202609-012）。**未跑任何測試。**
> 結論先看：**這不是存檔被拒，而是 M2.1 熱修的設計缺口——「帶入並連結」從頭到尾沒有把任何東西送到伺服器。** 修法＝把它做成真正的『認列』（使用者意圖，1c 決定）：連結立即落地、供應商取自採購單、已申購／已到料可勾，且不繞過核准（採購單本身已核准）。

## 1. 端到端追蹤（現況）

| 步驟 | 程式 | 做了什麼 |
|---|---|---|
| 1 按鈕 | `case-management.html:1088` → `mlPickCandidate(mat, groupKey)`（`case-management-mlink.js`） | 取 `mlGroups`（`GET …/material-coverage` 的涵蓋分組）中對應的組 |
| 2 帶入 | `mlPickCandidate` → `_mlPush({...})` | 只在**頁面記憶體**的 `materialOrders` 推入一列新的材料申請：`_saved:false`、`supplierId:null`、`poDocCode/poLine/quoteItemId` 取自採購單；回傳這列的**本機新 itemId** |
| 3 連結 | `mat.orderItemId = <剛推入的本機 itemId>` | 材料**卡片**（`cr.caseRecord.materials[]`）的連結指向『還沒存在於伺服器』的列；`setDirty()` 觸發自動存檔 |
| 4 自動存檔 | `saveCaseRecord()` → `this._crForSave()`（`case-management-core.js:540`） | **刻意**把『連到未儲存材料申請列』的卡片連結在送出的快照裡換成空字串（`orderItemId:''`），並設 `_mlHeldLink=true`（訊息：『已儲存；材料卡片的連結將在材料申請儲存後送出』）。理由（程式註解）：避免後端 `_gate_materials` 回 `bad_link`（『連結的材料申請不存在』）把卡片換回舊值 |
| 5 材料申請列的儲存 | 只有 `moSave()`（`case-management-exec.js:360`，『材料申請』面板的儲存／送審）會 `PATCH /material-orders` 把 `materialOrders` 列送出 | 新列在後端 `_gate_orders` 要過：`supplier_required`（`material_order.supplier_required` 預設 1＝一律要選供應商；`moSupplierAlways` 預設 true）、`po_required`、`bad_link`；通過後建立**草稿**審核列（`MA.create_draft`） |
| 6 勾選條件 | `matCanTick(mat, flag)`（`case-management-exec.js:272`）＝`moApprovals[mat.orderItemId].status === '已核准'`（到貨另需 `receivedOn`） | 只有『卡片連到一張**已核准的材料申請**』才可勾；後端 `_gate_materials` 同一條規則（`order_not_approved`） |

## 2. 為什麼 4 次自動存檔後伺服器仍什麼都沒有（prod 事實吻合）

prod：`caseRecord.materialOrders` 0 列、`case_material_approvals` 全庫 0 列、卡片 `orderItemId=''`、4 次 `case.update` 全成功且無拒絕痕跡、零材料稽核。與下列推論逐項吻合：

1. 使用者按『帶入並連結』只改了**畫面記憶體**（步驟 2～3）。
2. 之後的 4 次自動存檔都經 `_crForSave()`（步驟 4）：**連結被當成空值送出**，伺服器的卡片 `orderItemId` 本來就是 `''` ⇒ 沒有差異、沒有拒絕（所以稽核乾淨）。`materialOrders` 分段則**不在自動存檔裡**（它走專屬端點，步驟 5）。
3. 使用者沒有到『材料申請』面板選供應商並按儲存 ⇒ 沒有 `PATCH /material-orders` ⇒ 伺服器 0 列、0 個審核列（與『全庫 0 列』吻合）。
4. 重新載入後，記憶體中的草稿列與連結一併消失 ⇒ 卡片回到（未連結）。
5. 已申購／已到料維持停用，提示是通用句（`!a` ⇒ 『需先申請請購單，再申請採購單…』，因為 `moApprovals['']` 不存在）。

## 3. 假設清單（依可能性排序）

| # | 假設 | 可能性 | 證據／反證 |
|---|---|---|---|
| **H1** | **設計缺口**：連結與草稿列只存在記憶體；自動存檔刻意扣住連結；沒人按『材料申請』儲存 ⇒ 什麼都沒送 | **確認（與 prod 資料逐項吻合）** | 見 §2；零稽核、零審核列、4 次成功存檔 |
| H2 | 即使使用者到『材料申請』按儲存，預設政策 `supplier_required=1` 且該列 `supplierId:null` ⇒ `_gate_orders` 以 `supplier_required` 拒絕整列（`rejected[]` 只在回應本文，頁面以 toast 顯示 9 秒），連結仍扣住 ⇒ 仍（未連結） | 高（若走到那一步一定發生） | 帶入列從不帶供應商；使用者早先的話：「有些沒辦法填寫供應商，從已經申請的PO單認列」 |
| H3 | 就算存成功，列是**草稿**，要送審＋走完簽核鏈才『已核准』，勾選才解鎖——對『採購單已核准』的情境是多餘的重複核准 | 高（產品語意缺口） | `matCanTick` 只認『已核准的材料申請』 |
| H4 | 前端重繪用舊資料／舊連結鍵 | 低 | 連結鍵在記憶體內一致；問題在根本沒落地 |
| H5 | (c) 採購單行沒有 `itemId` ⇒ 找不到報價品項、無法涵蓋 | 低（本案三行都有 `itemId`） | prod：3 lines each WITH itemId |
| H6 | 舊分頁（M2.1 前開啟） | 低 | 伺服器現行靜態檔含 `_crForSave`、`moSupplierAlways` |

## 4. 最小重現測試（未修前應紅）
**後端（純 API，不需瀏覽器）** `modules/case/tests/test_material_recognize_*.py`：建案件＋報價品項＋一張**已核准**採購單（`case_extra_expenses`，行帶 `itemId`）；對材料卡片送 `PATCH …/case-record`（`materials[0].poLink`＝該採購單分組、`ordered=true`）；斷言：①回應無 `rejected`；②重新 `GET` 後卡片連結仍在；③`ordered` 為真；④`arrived` 在沒有到貨確認時的規則（見修法）；⑤不產生任何 `case_material_approvals` 列。
**e2e（Edge）** 新增 `test_e2e_material_recognize_2026_10_13.py`：載入案件→按『帶入並連結』→**不按任何其他儲存**→重新整理→卡片仍顯示已對應採購單、已申購已勾、已到料可勾。

## 5. 修法（實作中；見分支 `wip/t57-material-recognize-r1`）
把『帶入並連結』改成**認列**：卡片自己持有一個**經伺服器驗證的採購單連結** `poLink`（不再建立前端草稿列、不再依賴材料申請審核列）：
- 伺服器驗證（`_gate_materials`）：`poLink.key` 必須是該案件目前『已核准採購單涵蓋分組』之一（`material_coverage_view.groups`）、尚未被其他卡片認列、且尚未有活的材料申請；寫入時由伺服器重新填入 `poDocCode／docCodes／quoteItemId／供應商名稱（取自採購單廠商欄位）`，不信用戶端。
- 勾選閘：`ordered`／`arrived` 由 false→true 的條件除了『連到已核准材料申請』外，新增『持有有效認列 `poLink`』；`arrived` 不需材料申請的到貨確認（沒有材料申請可確認），但記錄勾選者與時間。
- 不繞過核准：認列只在**採購單已核准**時成立；只連結與鏡射旗標，不建立或核准任何材料申請，不產生金額。
- 設定：`material_order.supplier_required` 語意不變（手動新增的材料申請照舊）；認列的卡片供應商取自採購單，不要求在供應商主檔內。
