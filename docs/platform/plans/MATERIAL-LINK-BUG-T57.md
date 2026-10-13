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

## 5. 修法（r2：併入 0d 設計稽核 M1–M4／S1–S5 與使用者 10-13 加碼）
把『帶入並連結』改成**認列**：卡片自己持有一個**經伺服器驗證的採購單連結** `poLink`（不再建立前端草稿列、不依賴材料申請審核列）。實作集中在 `modules/case/material_recognize.py`，由唯一的閘 `material_guard._gate_materials` 呼叫（端點、整份存檔漏斗、已結案變更核准三條路徑共用；漏斗對同一份資料會再過一次閘，稽核以連線專屬 TEMP 表去重）。

**使用者加碼（10-13，逐字）**：「照正常流程開發即可，他能自動帶入採購單，如果非超級管理員自動帶入要把它取消，要寄信通知管理員」。
- 誰可以認列／取消認列：預設**只有最高管理者**（設定中心群組 `material_recognition.who_may`：1＝只有最高管理者〔預設〕／2＝有案件權限的人；放寬＝高影響，確認期間＋另一位最高管理者核准）。
- 其他人嘗試 ⇒ **整件取消**：該卡片的 `poLink` 與旗標（含序號）維持原值，同一份資料其他欄位照存；`rejected[]` 回 `recognize_denied`（白話訊息）；同交易寫稽核 `material.recognize_denied`；依 `on_denied`（1＝取消並寄信〔預設〕／2＝只取消）寄信給管理員。
- 信：類型 `material_recognize_denied`（系統技術類、預設僅最高管理者，收件人只能在「信件與通知收件設定」覆寫——收件人只有一個來源，不另設收件人欄位）；固定範本，只有案件編號、卡片編號、嘗試者帳號、時間；沒有金額、廠商、採購單明細；欄位值去掉所有換行。去重＋上限查**稽核表**（資料庫狀態、在寫入交易內）：同 (帳號, 案件, 分組) 於 `mail_window_minutes`（預設 60）內已寄過 ⇒ 不寄；視窗內總寄信達 `mail_cap`（預設 10）⇒ 不寄；稽核每次都寫。寄信失敗只記 log，不影響拒絕。
- `actor=None`（系統／已結案變更核准）：不接受新的或變更的 poLink（記 denied 稽核、不寄信），只保留原本有效的；不可代為翻旗標。

**0d 設計稽核對應**
| 項 | 做法 |
|---|---|
| M1 到貨無確認步驟 | 勾『已到料』必填到貨日（`normalize_date`）；`arrivedBy`／`arrivedAt` 由伺服器記，用戶端帶的忽略；被拒時序號（devices）維持原值；取消已到料清掉到貨記錄並記 `recognize_unarrived`（序號不自動移除，與其他取消旗標一致，稽核記序號數） |
| M2 認列唯一 | 以已存卡片（寫入交易內重讀）＋同一份資料內逐張累計的 `taken` 判斷；同一張重送冪等；測試含正對照（第一張成立、第二張被拒） |
| M3 雙向占用／過期 | 認列時分組不得已有活的材料申請（含草稿）；反向：認列中的分組不能再建立／連結材料申請（`claimed_conflict` 掛在 `_link_problem`）。每次存檔重新驗證，採購單不再是『已核准涵蓋』⇒ `poLink.stale=true`：旗標歷史保留、不能再勾（`recognize_stale`）、涵蓋檢視不再算占用、畫面顯示『採購單已變更』 |
| M4 稽核 | `material.recognize`／`recognize_undo`／`recognize_arrived`／`recognize_unarrived`／`recognize_denied`，在閘內同交易寫入（`_gate_materials` 新增 actor 參數） |
| S1 授權 | 認列＝上述設定；勾旗標＝可寫案件記錄者（同 `/receive`，端點的 `require_case`）；`poLink` 只有非金額欄位（單號、分組鍵、品名、廠商名稱、品項 id） |
| S2 偽造 | 用戶端只有 `key` 與 `arrivedOn` 會被採用，其餘由伺服器填；沒帶 `poLink` 欄位＝舊頁面，保留伺服器值；明確 `null`＝取消認列（旗標一併取消，除非另有已核准材料申請支撐） |
| S3 跨案件 | 分組鍵只對**該案件**的涵蓋分組驗證；訊息不洩漏其他案件 |
| S4 消費者 | 儀表板材料清單加 `recognized`；認列不建立 `case_material_approvals`／匯款路徑（測試斷言） |
| S5 回滾 | 見下方 |

**回滾注意（發行說明）**：`poLink` 存在卡片 JSON 內，無遷移。程式回滾後舊閘不認識 `poLink`：旗標保留（舊閘只檢查 false→true），但舊的涵蓋檢視不知道已認列的分組 ⇒ 同一組可能再被建立材料申請而**重複涵蓋**。回滾後、建立材料申請前，請先檢查案件的材料卡片是否已認列同一採購單。
