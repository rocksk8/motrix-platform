# M3 T1 第一天筆記（5e／T57）

> 基底 `origin/train/m2-int-r9`（c87079be2）。依 `M3-ALTQUOTE-WORK-BREAKDOWN-T56.md`（r11）T1 第一天清單。行號為本基底實測，T2 開工前仍以全文檢索為準。結論標註：**已查證**＝讀過程式；**待核**＝尚未查完，列出動作。

## 1. 已開採購單（PO）如何被撤回（P2①）— 已查證
- `backend/modules/case/api/material_orders.py` 只有三支：`PATCH …/material-orders`（:79）、`PATCH …/material-orders/{item_id}/invoice-date`（:198）、`GET`（:239）。**沒有撤銷採購單的專用端點。**
- 唯一的「撤回」＝ `PATCH :79` **整份覆蓋** `caseRecord.materialOrders`：把清單改掉、或把某筆 `poDocCode` 清空／移除即等於解除對應。限制：①已結案（`deal_tag`＝已結案）→ 400；②某筆已有付款（`paidAmount>0` 或 `paidStatus!=pending`）時不可**新增**對應採購單（:140）——但**可把既有對應清掉**（比對只擋「變成新的非空 poDocCode」）；③需 admin／財務角色／project_manage 且 `material_money_visible`。
- 結論：P2① 的「已開 PO」**不構成單向陷阱**（有出口＝改叫料清單／清 `poDocCode`），但 PO 本體在 supply 模組，案件側只持有 `poDocCode` 連結。**M3 的 P2① 只檢查『已成案』（`dealTag`）**；是否另把「叫料清單有 `poDocCode`」當擋下條件列為 **O-A（待 PM 裁示，預設：不擋，只在 409／提醒文字提示）**，避免擋下條件依賴 supply 模組。
- 成案出口：`PATCH /api/quotations/{no}/deal-tag`（quotations.py:2429；未成案↔已成案 admin+，已結案 superadmin；`dealTag` 從 `data_json` 讀，`save_quotation_json` 寫回）。

## 2. P8 出口「重開精算」— 已查證（**與 r11 假設不同**）
- r11 假設「查無可重開已精算的端點」。**實際存在**：`PUT /api/quotations/{no}/settlement`（`api/settlement_api.py:55`）。已完結（`settlement.status=="finalized"`）時：非 superadmin → 403（:85）；superadmin 存回 `status!="finalized"` 的內容即為「重新開啟」，**必填理由**（:90，無理由 422），寫 `editHistory`（`reason`、`from:"finalized"`）與稽核。精算狀態的 SQL 讀法：`SQL_SETTLE_STATUS`＝`COALESCE(NULLIF(settle_status,''), json_extract(data_json,'$.settlement.status'),'')`（`modules/case/quotations.py:18`）。
- 結論：P8① 擋下時**有出口**（superadmin 重開精算）。**P8 不需登記為『永久凍結例外』**；r11 的 backlog『重開精算』改為「**建議在 P8 的 409 文字與設定頁說明指向此路徑；UI 是否有按鈕待核**」（O-B：精算頁前端有無『重新開啟』按鈕，T9 前由 `frontend/pages` 核對）。18m 性質測試以此端點為 P8 的出口。
- 另：`case-unlock`（quotations.py:2625）只半解鎖已結案案件（不是重開精算），維持 r11 說法。

## 3. arap L1 直讀（P7／P6 守門鏈）— 部分已查證
- `core.registry.is_loaded(key)`（`core/registry.py:156`）存在；案件側既有用法樣式：`modules/case/material_change.py:59`（`bool(registry.is_loaded("supply"))`）。守門鏈用同樣寫法：`is_loaded("arap")` 為否 → 視為無下游單據。
- 兩張表欄位（已查）：`invoice_vouchers`（`voucher_no, quote_no, amount, snapshot_json, export_count, export_log, status, data_json`）、`payment_requests`（`request_no, quote_no, amount, snapshot_json, export_count, export_log, …`），皆以 `quote_no` 關聯，下游讀報價 SQL 欄位 `total／pretax`（`invoice_vouchers.py:194`、`payment_requests.py:191`、:379、:484）。
- **待核（T9 前）**：「有效單據」狀態集（排除 草稿／作廢／取消／退回）——須自兩支 API 的 status 常數取，不在案件模組寫死；做法＝在守門函式內 `SELECT DISTINCT status`＋對照 arap 端點的 DELETE／revoke／reject 實際可達狀態，結果寫入 T9 測試。缺表／`OperationalError` 降級照 H3。

## 4. P5 簽核金額基準 — 已查證
- `quote_terms.compute_approval_reasons`（`modules/case/quote_terms.py:156`）**完全不讀 `tot`**：只看 `validDays`、**每個非標題品項**的 `margin`（<30% 且 `cost>0`）、`discount`、`taxRate`、條款文字。因此「簽核原因」不依賴金額基準。
- **含擇一單的實際現況**：因逐項檢查 `items` **全部**（含未選的擇一項），低毛利的未選項今天就會被列為審核原因＝**已經是『最嚴』行為**；這與 P5① 預設（最嚴）一致，T2 改 `counted_items` 時**不得**把 `compute_approval_reasons` 改成只看計入集合（否則等於偷放寬）。
- **待核（P5②『以暫估』的實作位置）**：簽核**層級／簽核人鏈**是否依金額分流，尚未找到（`quotations.py` 內 `tot.get` 只出現在存檔 SQL 寫欄位，:1556、:1920）。動作：全文檢索簽核鏈建立處（`approval` 欄位組裝、`submit` 路徑 :1494／:1774）確認有無金額門檻；若無，P5 只作用於「原因清單」，P5② 的實際效果＝『未選項的低毛利是否列為原因』，登記說明文字需對齊（O-C，待 PM 確認）。

## 5. 寫入路徑全文檢索（P1 鎖定 fail-closed）— 已查證（函式級）
`save_quotation_json` 呼叫者（`api/quotations.py` 除另註；以函式名為準）。「可改本文？」＝可改品項／`altGroup`／`totalsByAlt`／`altPicks`／`tot`／本文備註；「is_signed」＝是否碰 `is_signed`。

| 呼叫者（行） | 可改本文 | 動 is_signed | 處置 |
|---|---|---|---|
| `update_quotation` PUT（:1691；SQL :1910 直接 UPDATE，非 save_quotation_json） | **是** | 否 | **P1 主戰場**：讀已存列加 `is_signed`，伺服器端比對 |
| `update_status` PATCH（:1975；SQL :2029/:2033 直接 UPDATE） | 否（改 status） | 否 | P3 |
| `recall_quotation`（:2053；SQL :2082 直接 UPDATE，改 草稿＋data_json） | 否 | 否 | P3（已回簽單經 unlock-edit 才會待審核） |
| `reject_quotation`（:4985；SQL :5053 改 quote_no＋草稿） | 否 | 否 | P3＋H7 舊號查守門 |
| `reject_final_quotation`（:5119 → 已拒絕） | 否 | 否 | P3b |
| `approve_quotation`（:4958、:4973） | 否（簽核鏈／狀態） | 否 | 證明不觸及鎖定集合 |
| `toggle_quotation_signed`（:1323；SQL :1363/:1369 直接 UPDATE） | 寫 `altPicks`／`tot`（T9） | **是** | T9 唯一可寫 `altPicks` 的路徑 |
| `update_deal_tag`（:2487） | 否（`dealTag`／`statusLog`） | 否 | 測試證明 |
| `update_case_record`（:3039） | 否（`caseRecord`） | 否 | 執行紀錄，不在 P1 |
| `_apply_case_change_request`（:3157/3184/3200/3216，半解鎖審核套用） | 否（`caseRecord` 款項／材料／檔案） | 否 | 執行紀錄 |
| `_sync_stages_to_json`（:3419） | 否（階段） | 否 | 執行紀錄 |
| `mark_payment`、款項發票檔上傳／刪除（:4034、:4119、:4145）、材料檔／發票檔（:4198、:4224、:4264、:4290）、沖銷申請／取消／核准（:4319、:4348、:4386） | 否（`caseRecord`） | 否 | 執行紀錄附件 → P1 放行 |
| `approval.reassign` 適配器（:6262） | 否（簽核鏈指派） | 否 | 測試證明 |
| **`_append_items_to_quotation`（:6592，IP-17 外部品項附加）** | **是（新增品項）** | 否 | 已有「僅草稿」守門（:6568）；已回簽單預設不可能在草稿（附錄 A），**仍列入 P1 比對**（fail-closed）；新增品項無 `altGroup`，不影響 `altPicks` 一致性但會改 `tot` |
| `material_orders.update_material_orders`（:178）、`set_material_order_invoice_date`（:230） | 否（`caseRecord.materialOrders`） | 否 | 執行紀錄 |
| `settlement_api.update_settlement`（:156） | 否（`settlement`） | 否 | 執行紀錄；但 `tot` 讀取點（見 P8） |

**不經 `save_quotation_json` 的直寫 `data_json`／`quotations`（遺漏風險來源，需逐一證明不碰本文）**：`case_batch_assign`（:6391，SQL :6441，`data_json`＋`assigned_user_ids`——須證明只動指派）、:1312（指派）、:1668（`create_quotation` 後處理）、:6540（`data_json` 直寫）；`case/recycle_adapter.py:508/:529`（回收筒還原／清除，直寫 `data_json`）；`case/profit_guard.py:294`（戳記重算，寫 `data_json`＋`net_margin_pct`）；`case/material_payment.py:646`、`case/material_change.py:511`（材料投影）；`db.py` 內多處維運／遷移（:1037、:1880、:1943、:1980、:1984、:2144、:4193/:4203、:4552）與 `tools/backfill_*.py`、`migrations_frozen/*`（一次性，不納入執行期鎖）。**T2 動作：逐項標註後寫成『寫入路徑守門測試』（靜態：任何新增 `UPDATE quotations` 字面或 `save_quotation_json` 呼叫者不在清單即紅）。**

## 6. 附件端點切分 — 已查證（端點層）
- **報價本文附件**：案件 API **沒有**專屬的報價本文附件上傳／刪除端點（`frontend/pages/quotation-form.html` 僅 1 處 `attachments`/files 字樣，T6 前核對是否為表單內自帶鍵）。若本文附件存於 `data_json` 的某鍵，則只能經 `PUT /api/quotations/{no}`，**被 P1 本文鍵比對覆蓋**（本文鍵清單須含該鍵；待 T6 前核對表單欄位目錄）。
- **執行紀錄附件（P1 放行）**：`POST/DELETE /api/quotations/{no}/signed-files`（:1403／:1428，客戶回簽單，明確放行）；款項發票檔（:4085／:4128）、材料檔（:4168／:4207）、材料發票檔（:4232／:4273）；`case_extra_expenses` 檔（:1209／:1264／:1506／:1550）；叫料（material_orders）、開票 `issued-files`（arap）、完工單 `signed-files`（completion_notes.py:767／:793）。
- **O-D**：`DELETE /api/quotations/{no}/updates/{uid}/files/{file_id}`（:5399，案件進度更新附件）歸執行紀錄，放行。

## 7. 設定登記表接入方式（依 PM 更新規則：P1–P8 從第一天走登記表）
- 樣式來源：`helpers/settings_registry.py`（`SettingDef`、`register_group`、`get(group, field)`）與 `helpers/settings_groups.py:85`（`show_denied`：`int` 代碼＋`choices=[(值, 中文標籤, 影響說明)]`＋`loosen="up"`＋`risk="security"`）。讀取樣式：`routers/system_hub.py:135` `sr.get("system_hub","show_denied")==1`。
- 群組 `quote_alt`（顯示名『擇一方案』）；鍵 `quote_alt.<key>`：`total_text`、`note_template`、`show_unpicked_in_pdf`、`alt_groups_max`、`combo_view_max`、`combo_view_default_open`、`alt_enabled`，與政策鍵 `lock_scope`(P1)、`cancel_after_deal`(P2)、`move_out_of_sent`(P3)、`reject_final_keep`(P3b)、`unlock_edit_signed`(P4)、`approval_basis`(P5)、`cancel_after_export`(P6)、`cancel_after_invoice`(P7)、`cancel_after_settle`(P8)。
- 『尚未提供』選項（P2②、P6②、P7②、P8②）：登記為 `choices` 內，標籤含『（尚未提供）』，`validate_values` 的 cross_check 擋下儲存，並在讀取端把非可選值夾回預設；T7 同步補 `choices` 影響說明與橫幅文字（`impact_scope` 放在影響說明欄，橫幅為 risk_text）。
- 每個政策 `loosen="up"`（選項順序嚴→寬，整數代碼 1..n）、`risk` 依門檻：暫定 P1–P8＝`money`（涉及金額與下游單據），文字範本類＝`legal`；**類別待 PM 裁示 O-E**；預設值＝使用者定案值（均為第一項）。
- 鎖定比對（P1）為 M3 自有機制，不等 F7。

## 8. 待 PM 裁示／待核彙總
| # | 項目 | 預設做法 |
|---|---|---|
| O-A | P2① 是否把『叫料清單有 poDocCode』列入擋下 | 不擋（只成案） |
| O-B | 精算頁前端有無『重新開啟』按鈕（P8 出口 UI） | T9 前核；無則 409 文字指向 superadmin 重開精算 |
| O-C | 簽核層級是否依金額；P5 作用範圍 | 先只作用於原因清單 |
| O-D | 案件進度更新附件歸執行紀錄 | 放行 |
| O-E | P1–P8 的風險類別（money／legal／security） | P1–P4、P6–P8＝money；P5＝money；`total_text`／`note_template`＝legal |
| O-F | 有效單據狀態集（arap） | T9 前自兩端點取，不寫死 |
