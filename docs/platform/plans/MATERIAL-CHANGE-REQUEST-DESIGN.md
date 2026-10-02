# 33-M2 材料申請「變更申請」：覆核表／遷移／核准差異（d7；設計；2026-10-03；承 2e 規格 rev.2 §B）

## 0. 結論先行
- **新表 `case_material_changes`（遷移 `0006_material_changes.py`）＋新簽核單據類型 `material_change`**（單號 `MC-YYYYMMDD-NNNN`），不把變更塞進 `case_material_approvals` 的狀態機：原已核准版本的狀態、成本、到貨、可出貨量**完全不動**（使用者裁示 N3），變更是另一張單，核准後才**原子切換**。
- 已核准內容照常有效直到變更核准；駁回／撤回 ⇒ 原版本不動；**一筆材料申請同時最多一個進行中的變更**（部分唯一索引擋底）。
- 核准差異詳情並列「原版本／變更後」；金額欄位照 L1 規則由財務檢視權遮蔽。
- 範圍切割：**我（31-C 檔）＝表、狀態機、簽核（流程／佇列／通知／詳情／稽核）、原子套用、守門**；2e（案件側）＝提案內容的組成（涵蓋快照 `poSnapshot`、數量預設、「有 N 筆新採購單行尚未納入」提示與按鈕、畫面）。介面見 §4。

## 1. 資料模型
```
case_material_changes (
  id INTEGER PK AUTOINCREMENT,
  quote_no TEXT NOT NULL, item_id TEXT NOT NULL,            -- 對應的材料申請（與 case_material_approvals 同鍵）
  doc_code TEXT NOT NULL UNIQUE,                            -- MC-YYYYMMDD-NNNN
  status TEXT NOT NULL,                                     -- 草稿／待審核／簽核中／已核准／已退回／已撤回
  base_version INTEGER NOT NULL,                            -- 提案時原版本號（case_material_approvals.version）；套用時必須仍相同（防競態）
  proposal_json TEXT NOT NULL,                              -- 變更後的內容（實質欄位：quantity/unit/unitPrice/totalPrice/poSnapshot/notes…）
  base_json TEXT NOT NULL,                                  -- 提案當下的原內容（簽核人看差異用；之後原版本不會變，仍存一份避免反推）
  diff_json TEXT NOT NULL,                                  -- [{label, before, after}]（送審時由伺服器算；金額欄標記 money:true 供遮蔽）
  approval_json TEXT NOT NULL DEFAULT '{}',                 -- 既有分層簽核格式（tiers／currentTier／history）
  reason TEXT NOT NULL DEFAULT '',                          -- 變更原因（必填）
  created_by, created_at, submitted_by, submitted_at, approved_at, applied_at, updated_at )
UNIQUE INDEX one_live_change ON case_material_changes(quote_no, item_id) WHERE status IN ('草稿','待審核','簽核中')
```
只新增、冪等、不回填；沒有變更列＝沒有變更（現狀）。

## 2. 狀態機與規則
- 建立（草稿）：原申請必須是**已核准**（或規則上線前的「舊單／grandfather」不走變更申請，維持 31-C 的「核准後改＝回草稿」，見 §5）；內容由案件側（2e）組好 `proposal`，我驗證：數量／金額非負、小計＝數量×單價（沿用 `_valid_order`）、必填原因、**不得低於已出貨＋占用量**（呼叫 L1 提供者 `shipping.material_shipped`，沒有提供者＝不檢查；訊息 `change_below_shipped`）、與原版本相同 ⇒ 400「沒有任何變更」。
- 送審：重新驗證、算 `diff_json`、套用既有分層簽核（`setting_to_active_tiers`；doc type `material_change`，unified）；沒設簽核層＝自動核准並立即套用。
- 撤回／退回：回「已撤回／已退回」，**不改原版本**；退回後可修改再送審（草稿態同）。
- **核准（原子套用，同一個寫入交易）**：① 檢查 `base_version` 仍等於目前版本（否 ⇒ 409，變更作廢請重提）；② 檢查下限（已出貨＋占用）；③ 把 `proposal` 寫入 `caseRecord.materialOrders[該列]`（直接寫 `quotations.data_json`，同 `sync_order_paid` 的「系統自己的投影」，不經 `material_guard`）；④ `case_material_approvals`：`version+1`、`approval_json.history` 推一筆 `changed`（含 MC 單號與差異摘要）、`content_hash` 重算、**`received_*` 保留**（已確認到貨的不重置；新增部分的到貨確認由 E5 的到貨量機制處理，屬 S 線）；⑤ 變更列 `status=已核准、applied_at`；⑥ 稽核。任一步失敗 ⇒ 整個交易回滾（變更維持「簽核中最後一層」之前的狀態）。
- 已有匯款申請（活的）：變更不得改金額使「已申請額度」超過新小計（沿用 `room_for`；超過 ⇒ 409 `change_below_committed`）；有採購單有效涵蓋的申請本來就不開匯款（E3），不受影響。

## 3. 簽核整合（31-C 同一份清單，逐項要有守門）
1. 單據類型註冊 `material_change`（`TA.APPROVAL_DOC_TYPES`／標籤「材料申請變更」）＋`approval scope`（`EXPECTED_SCOPE`／`FULL_SCOPE_BODY`）。
2. 佇列提供者（`approval.queue_items`，名稱含字面值 `"material_change"`，覆蓋守門掃字面值）＋詳情提供者（差異表）；佇列卡片標題「材料申請變更 MC-…」，標註「原 N → 變更後 M」。
3. 通知 4 種（待審核／輪到您／已核准／被退回；字串照字表，前綴【材料申請】）。
4. 稽核動作：`material_changes.create／submit／withdraw／approve／reject／apply`。
5. 路由前綴登記（module.json、docs/platform/modules.json）、`case_read_scope`、pii（無個資欄位，免）。
6. 簽核人詳情 `fields[]`：變更單號、案件、品名、原因、**差異表**（品名／數量／單價／小計／涵蓋採購單行：前→後；金額列依財務檢視權遮蔽）、「原版本仍有效至核准」說明。

## 4. 與 2e 的介面（建議）
- 2e 提供 `purchase_items.change_proposal(conn, quote_no, item_id) -> {quantity, unit, unitPrice, totalPrice, poSnapshot, uncoveredLines:[…]}`（目前已核准採購單行組成的新內容；`poSnapshot` 為涵蓋快照）；我只驗證與保存，不自己組內容。
- 我提供：`POST /api/quotations/{q}/material-orders/{item}/changes`（body：`proposal`、`reason`）、`GET …/changes`、`POST …/changes/{id}/submit|withdraw`、`POST …/changes/{id}/approve|reject`（簽核人）；回應含 `docCode`、`status`、`diff`。
- 守門：M1 之後，**非 grandfather 的已核准申請，實質欄位直接修改被拒（`use_change_request`）**，要求改走變更申請；grandfather／舊單維持現行行為。

## 5. 風險與決定點
1. **不溯及既往**：正式機材料申請 0 筆，影響面為零；grandfather 單（M1 定義）仍用 31-C「核准後改＝回草稿」，不混用兩條路。
2. **帳少一筆風險消除**：核准前原版本照舊計入報表／總帳（這是用變更單取代「改完回草稿」的主要理由）；a3 D7 的風險在新流程下不再成立。
3. **競態**：`base_version` 檢查＋部分唯一索引；套用在單一交易內。
4. **下限依賴 S 線**：`shipping.material_shipped` 提供者尚未存在時下限檢查略過（記錄在回應 `warnings`），S1 完成後自動生效；測試用假提供者。
5. 待使用者／主持確認：變更申請是否也要「撤銷已核准的變更」（回到前一版）——預設**不做**（要回復就再提一張變更）。

## 6. 切片與估時（單人，含測試／突變／e2e）
| 片 | 內容 | 天 |
|---|---|---|
| M2a | 遷移＋`material_change.py` 狀態機／驗證／diff／原子套用＋單元測試與突變（18 條起：base_version、下限、一次一個、自動核准、套用回滾、received 保留…） | 1.5 |
| M2b | API／簽核整合（註冊、佇列、詳情差異、通知、稽核、scope／覆蓋守門、路由登記）＋`use_change_request` 守門 | 1.5 |
| M2c | e2e（核准前原版本仍計入報表、核准後切換、退回不動、差異詳情遮蔽）＋文件／版號 | 1.0 |
合計 **4 天**（規格 rev.2 估 3.5；多出的 0.5 是 31-C 簽核整合清單與 `use_change_request` 守門）。
