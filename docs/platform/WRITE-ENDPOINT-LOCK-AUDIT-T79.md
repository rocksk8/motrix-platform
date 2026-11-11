# 案件模組寫入端點的「樂觀鎖」覆蓋稽核（T79，2026-11-11）

> 狀態：稽核結果（分支 `feat/draft-optimistic-lock`，基底 `train/t79-int` 0911d3246）。**不是規格**：分類以讀程式碼＋函式名為依據，下面「方法與限制」寫明哪些沒有逐支讀完。

## 一句話

- 案件模組（`modules/case/api/*.py`）共 **99** 條寫入路由（POST／PUT／PATCH／DELETE；GET 不算）。
- **已有版本比對（樂觀鎖）的只有 6 條**（整份存檔 `PUT /api/quotations/{no}` 含草稿階段、case-record、款項標記、精算、完工單、複查編輯），而且 token 都是**選填**。
- **會用用戶端舊畫面整份／整欄覆蓋、卻沒有版本比對的有 15 條**（`O-高` 1、`O-中` 5、`O-低` 9）；其中真正會「靜默丟資料」的主要是 **`PATCH /api/quotations/{no}/material-orders`**（整份覆蓋叫料清單）。
- 其餘 34 條是狀態轉換／指令（狀態機在寫入交易內擋）、44 條是新增／刪除／檔案／紀錄（不覆蓋既有內容），不需要 updated_at 比對。

## 分類定義

| 類 | 意思 | 要不要樂觀鎖 |
|---|---|---|
| `L` | 已有版本比對（`_expectedUpdatedAt`／`expectedUpdatedAt`／內容指紋） | 已有；token 選填，見下方建議 |
| `O-高/中/低` | 用戶端帶一份「它畫面上的值」整份／整欄覆蓋伺服器現值，沒有版本比對 ⇒ 後存蓋先存。高＝覆蓋範圍是整份清單、會丟別人新增的列；中＝多個欄位；低＝單一欄位／順序／全域設定 | **要補或寫明接受的理由** |
| `T` | 狀態轉換／指令（送審、核准、駁回、作廢、撤回、鎖定…）。寫入交易內（`begin_write`／`BEGIN IMMEDIATE`／服務層狀態機）檢查「目前狀態」；舊畫面按下去 ⇒ 409／403，不會靜默覆蓋 | 不需要（狀態機就是版本） |
| `A` | 新增、刪除、檔案、確認／紀錄、匯出、預覽。不覆蓋既有內容；刪除一筆已被刪的 ⇒ 404 | 不需要 |

## 路由清單（99）

| 類 | 檔案 | 方法 | 路徑 | 函式 | 說明 |
|---|---|---|---|---|---|
| `L` | `completion_notes.py` | PUT | `/api/completion-notes/{note_no}` | `update_completion_note` | `expected_updated_at`（選填） |
| `L` | `quotations.py` | PATCH | `/api/quotations/{no}/payment/{idx}` | `mark_payment` | `_expectedUpdatedAt`（選填） |
| `L` | `quotations.py` | PUT | `/api/quotations/{quote_no}` | `update_quotation` | 整份存檔：比對 `_expectedUpdatedAt`（選填），前置檢查＋寫入交易內各一次 |
| `L` | `quotations.py` | PATCH | `/api/quotations/{quote_no}/case-record` | `update_case_record` | `caseRecord._expectedUpdatedAt`（選填） |
| `L` | `quotations.py` | POST | `/api/quotations/{quote_no}/review-edit` | `review_edit_quotation` | 不用 updated_at：靠內容指紋（`content_fp`）＋狀態機；待審核／簽核中才開放 |
| `L` | `settlement_api.py` | PUT | `/api/quotations/{quote_no}/settlement` | `update_settlement` | `expectedUpdatedAt`（選填） |
| `O-高` | `material_orders.py` | PATCH | `/api/quotations/{quote_no}/material-orders` | `update_material_orders` | 整份覆蓋 `caseRecord.materialOrders`（read-modify-write 在寫鎖內，但清單內容是用戶端舊畫面的整份）：兩人同時改，後存的把先存者新增／改的列抹掉 |
| `O-中` | `case_extra_expenses.py` | PATCH | `/api/quotations/{quote_no}/extra-expenses/{exp_id}` | `update_extra_expense` | 僅草稿／已駁回可改；欄位覆寫，後存蓋先存 |
| `O-中` | `case_extra_expenses.py` | PUT | `/api/quotations/{quote_no}/extra-expenses/{exp_id}/change-request` | `upsert_change_request` | 整份變更申請內容覆寫 |
| `O-中` | `material_payments.py` | PATCH | `/api/material-payments/{pid}` | `update_payment` | 匯款申請（材料）草稿欄位覆寫，`begin_write` 序列化但沒有版本比對 |
| `O-中` | `quotation_stages.py` | PUT | `/api/quotations/{quote_no}/stages/{stage_id}` | `update_case_stage` | 單一階段欄位覆寫（名稱／日期／狀態…），後存蓋先存 |
| `O-中` | `quotations.py` | PATCH | `/api/quotations/{quote_no}/assigned-users` | `update_case_assigned_users` | 整份覆蓋協作者清單 |
| `O-低` | `case_action_items.py` | PUT | `/api/quotations/{quote_no}/action-items/{item_id}` | `update_case_action_item` | 待辦文字覆寫 |
| `O-低` | `case_extra_expenses.py` | PUT | `/api/extra-expenses/po-bank-block` | `po_bank_block_set` | 全域設定開關 |
| `O-低` | `case_extra_expenses.py` | PATCH | `/api/quotations/{quote_no}/extra-expenses/{exp_id}/dates` | `set_extra_expense_dates` | 只動日期欄 |
| `O-低` | `material_orders.py` | PATCH | `/api/quotations/{quote_no}/material-orders/{item_id}/invoice-date` | `set_material_order_invoice_date` | 單列發票日期 |
| `O-低` | `overhead.py` | PUT | `/api/overhead/settings` | `put_overhead_settings` | 全域設定（非單據）；最高管理者限定 |
| `O-低` | `overhead.py` | PUT | `/api/quotations/{quote_no}/overhead-pct` | `put_quotation_overhead_pct` | 最高管理者限定；寫入更新 `updated_at`（別人手上的舊報價單表單會 409），本身不比對 |
| `O-低` | `quotation_stages.py` | PATCH | `/api/quotations/{quote_no}/stages/reorder` | `reorder_case_stages` | 整份排序覆寫（順序，不丟資料） |
| `O-低` | `quotation_stages.py` | POST | `/api/quotations/{quote_no}/stages/{stage_id}/depends-on/{candidate_id}` | `toggle_stage_dependency` | 「切換」語意：兩人同時按會互相抵銷（不丟資料） |
| `O-低` | `quotation_stages.py` | PUT | `/api/quotations/{quote_no}/stages/{stage_id}/visits/{visit_id}` | `update_stage_visit` | 單筆進場紀錄欄位覆寫 |
| `T` | `case_action_items.py` | PATCH | `/api/quotations/{quote_no}/action-items/{item_id}/approve` | `approve_case_action_item` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `case_extra_expenses.py` | POST | `/api/quotations/{quote_no}/extra-expenses/{exp_id}/approve` | `approve_extra_expense` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `case_extra_expenses.py` | DELETE | `/api/quotations/{quote_no}/extra-expenses/{exp_id}/change-request` | `cancel_change_request` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `case_extra_expenses.py` | POST | `/api/quotations/{quote_no}/extra-expenses/{exp_id}/change-request/approve` | `approve_change_request` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `case_extra_expenses.py` | POST | `/api/quotations/{quote_no}/extra-expenses/{exp_id}/change-request/reject` | `reject_change_request` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `case_extra_expenses.py` | POST | `/api/quotations/{quote_no}/extra-expenses/{exp_id}/change-request/submit` | `submit_change_request` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `case_extra_expenses.py` | POST | `/api/quotations/{quote_no}/extra-expenses/{exp_id}/reject` | `reject_extra_expense` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `case_extra_expenses.py` | POST | `/api/quotations/{quote_no}/extra-expenses/{exp_id}/submit` | `submit_extra_expense` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `case_extra_expenses.py` | POST | `/api/quotations/{quote_no}/extra-expenses/{exp_id}/void` | `void_extra_expense` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `completion_notes.py` | POST | `/api/completion-notes/{note_no}/approve` | `approve_completion_note` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `completion_notes.py` | POST | `/api/completion-notes/{note_no}/reject` | `reject_completion_note` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `completion_notes.py` | POST | `/api/completion-notes/{note_no}/revoke-approval` | `revoke_completion_approval` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `completion_notes.py` | POST | `/api/completion-notes/{note_no}/signed-toggle` | `toggle_completion_signed` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `completion_notes.py` | POST | `/api/completion-notes/{note_no}/submit` | `submit_completion_note` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `material_payments.py` | POST | `/api/material-payments/{pid}/approve` | `approve_payment` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `material_payments.py` | POST | `/api/material-payments/{pid}/reject` | `reject_payment` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `material_payments.py` | POST | `/api/material-payments/{pid}/submit` | `submit_payment` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `material_payments.py` | POST | `/api/material-payments/{pid}/void` | `void_payment` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `material_payments.py` | POST | `/api/material-payments/{pid}/withdraw` | `withdraw_payment` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `quotation_stages.py` | POST | `/api/quotations/{quote_no}/stages/apply-template` | `apply_stage_template` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `quotations.py` | POST | `/api/case-changes/{change_id}/approve` | `approve_case_change` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `quotations.py` | POST | `/api/case-changes/{change_id}/reject` | `reject_case_change` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `quotations.py` | POST | `/api/quotations/{no}/payment/{idx}/approve-writeoff` | `approve_payment_writeoff` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `quotations.py` | POST | `/api/quotations/{no}/payment/{idx}/cancel-writeoff` | `cancel_payment_writeoff` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `quotations.py` | POST | `/api/quotations/{no}/payment/{idx}/request-writeoff` | `request_payment_writeoff` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `quotations.py` | POST | `/api/quotations/{quote_no}/approve` | `approve_quotation` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `quotations.py` | POST | `/api/quotations/{quote_no}/case-lock` | `lock_case` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `quotations.py` | POST | `/api/quotations/{quote_no}/case-unlock` | `unlock_case` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `quotations.py` | PATCH | `/api/quotations/{quote_no}/deal-tag` | `update_deal_tag` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `quotations.py` | POST | `/api/quotations/{quote_no}/recall` | `recall_quotation` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `quotations.py` | POST | `/api/quotations/{quote_no}/reject` | `reject_quotation` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `quotations.py` | POST | `/api/quotations/{quote_no}/reject-final` | `reject_final_quotation` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `quotations.py` | POST | `/api/quotations/{quote_no}/signed-toggle` | `toggle_quotation_signed` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `T` | `quotations.py` | PATCH | `/api/quotations/{quote_no}/status` | `update_status` | 狀態轉換／指令：伺服器在寫入交易內檢查目前狀態，舊畫面按下去得到 409／403，不會靜默覆蓋 |
| `A` | `case_action_items.py` | POST | `/api/quotations/{quote_no}/action-items` | `create_case_action_item` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `case_action_items.py` | DELETE | `/api/quotations/{quote_no}/action-items/{item_id}` | `delete_case_action_item` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `case_extra_expenses.py` | POST | `/api/quotations/{quote_no}/extra-expenses` | `create_extra_expense` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `case_extra_expenses.py` | DELETE | `/api/quotations/{quote_no}/extra-expenses/{exp_id}` | `delete_extra_expense` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `case_extra_expenses.py` | POST | `/api/quotations/{quote_no}/extra-expenses/{exp_id}/change-request/files` | `delete_change_request_file` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `case_extra_expenses.py` | DELETE | `/api/quotations/{quote_no}/extra-expenses/{exp_id}/change-request/files/{file_id}` | `delete_change_request_file` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `case_extra_expenses.py` | POST | `/api/quotations/{quote_no}/extra-expenses/{exp_id}/files` | `delete_extra_expense_file` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `case_extra_expenses.py` | DELETE | `/api/quotations/{quote_no}/extra-expenses/{exp_id}/files/{file_id}` | `delete_extra_expense_file` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `completion_notes.py` | POST | `/api/completion-notes` | `create_completion_note` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `completion_notes.py` | DELETE | `/api/completion-notes/{note_no}` | `delete_completion_note` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `completion_notes.py` | POST | `/api/completion-notes/{note_no}/export` | `record_completion_export` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `completion_notes.py` | POST | `/api/completion-notes/{note_no}/privacy-notice/ack` | `ack_completion_privacy_notice` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `completion_notes.py` | POST | `/api/completion-notes/{note_no}/signed-files` | `delete_completion_signed_file` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `completion_notes.py` | DELETE | `/api/completion-notes/{note_no}/signed-files/{file_id}` | `delete_completion_signed_file` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `material_payments.py` | POST | `/api/material-payments/{pid}/privacy-notice/ack` | `ack_payee_privacy_notice` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `material_payments.py` | POST | `/api/quotations/{quote_no}/material-orders/{item_id}/payments` | `create_payment` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `quotation_stages.py` | POST | `/api/quotations/stage-templates/preview` | `preview_stage_template` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `quotation_stages.py` | POST | `/api/quotations/{quote_no}/stages` | `create_case_stage` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `quotation_stages.py` | DELETE | `/api/quotations/{quote_no}/stages/{stage_id}` | `delete_case_stage` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `quotation_stages.py` | POST | `/api/quotations/{quote_no}/stages/{stage_id}/assignees` | `add_stage_assignee` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `quotation_stages.py` | DELETE | `/api/quotations/{quote_no}/stages/{stage_id}/assignees/{username}` | `remove_stage_assignee` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `quotation_stages.py` | POST | `/api/quotations/{quote_no}/stages/{stage_id}/visits` | `add_stage_visit` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `quotation_stages.py` | DELETE | `/api/quotations/{quote_no}/stages/{stage_id}/visits/{visit_id}` | `delete_stage_visit` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `quotations.py` | POST | `/api/case-batch/assign` | `case_batch_assign` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `quotations.py` | POST | `/api/case-batch/export` | `case_batch_export` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `quotations.py` | POST | `/api/quotations` | `create_quotation` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `quotations.py` | POST | `/api/quotations/case-activity` | `case_activity` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `quotations.py` | POST | `/api/quotations/historical` | `create_historical_quotation` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `quotations.py` | POST | `/api/quotations/preview-html` | `preview_quotation_html` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `quotations.py` | POST | `/api/quotations/{no}/materials/{idx}/files` | `delete_material_file` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `quotations.py` | DELETE | `/api/quotations/{no}/materials/{idx}/files/{file_id}` | `delete_material_file` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `quotations.py` | POST | `/api/quotations/{no}/materials/{idx}/invoice-files` | `delete_material_invoice_file` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `quotations.py` | DELETE | `/api/quotations/{no}/materials/{idx}/invoice-files/{file_id}` | `delete_material_invoice_file` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `quotations.py` | POST | `/api/quotations/{no}/payment/{idx}/invoice-files` | `delete_payment_item_invoice_file` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `quotations.py` | DELETE | `/api/quotations/{no}/payment/{idx}/invoice-files/{file_id}` | `delete_payment_item_invoice_file` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `quotations.py` | DELETE | `/api/quotations/{quote_no}` | `delete_quotation` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `quotations.py` | POST | `/api/quotations/{quote_no}/export` | `record_export` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `quotations.py` | POST | `/api/quotations/{quote_no}/privacy-notice/ack` | `ack_quotation_privacy_notice` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `quotations.py` | POST | `/api/quotations/{quote_no}/signed-files` | `delete_quotation_signed_file` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `quotations.py` | DELETE | `/api/quotations/{quote_no}/signed-files/{file_id}` | `delete_quotation_signed_file` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `quotations.py` | POST | `/api/quotations/{quote_no}/updates` | `delete_case_update` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `quotations.py` | DELETE | `/api/quotations/{quote_no}/updates/{uid}` | `delete_case_update` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `quotations.py` | DELETE | `/api/quotations/{quote_no}/updates/{uid}/files/{file_id}` | `delete_case_update_file` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |
| `A` | `settlement_actuals.py` | POST | `/api/quotations/{quote_no}/settlement-actuals/preview` | `settlement_actuals_preview` | 新增／刪除／檔案／紀錄：不覆蓋既有內容（刪除舊目標回 404） |

## 缺口與處理

| 缺口 | 風險 | 這張票 | 後續建議 |
|---|---|---|---|
| 自動存檔（60 秒計時）撞 409 時**無聲失敗**：`apiSave()` 回 false、畫面什麼都沒有，使用者以為有存 | 高（修改一直沒進資料庫，直到手動存才發現） | **已修**：橫幅＋暫停自動存檔＋「載入最新版」鈕（V3.41）＋真瀏覽器雙人 e2e | — |
| `PATCH /material-orders` 整份覆蓋叫料清單，無版本比對 | 高 | 未改（要動後端 GET／PATCH＋`case-management-exec.js`，且該頁剛被 UX 票大改） | 另開票：GET 回 `updatedAt`、PATCH 收 `expectedUpdatedAt`（選填，409＝橫幅＋重新載入），跟本票同一套 UI 模式 |
| `O-中` 各條（協作者清單、階段、額外支出、變更申請、材料匯款草稿） | 中 | 未改 | 這些表有 `updated_at` 欄位：同一套「選填 token＋409」逐支補；優先順序：assigned-users → extra-expenses PATCH → stages PUT → material-payments PATCH |
| `O-低` | 低 | 不補 | 單欄／順序／全域設定，最壞是後存蓋先存同一個值；`toggle_stage_dependency` 是切換語意（兩人同按互相抵銷，不丟資料） |

## 「token 選填」要不要改強制

現況：`PUT /api/quotations/{no}` 帶 `_expectedUpdatedAt` 才比對；沒帶 ⇒ 不比對（舊行為）。

- **前端**：`quotation-form.html` 的 `apiSave()` 在編輯既有單時一律帶（`!isNew`）。但 `_lastUpdatedAt` 為 `null` 時（載入失敗後用本機備份繼續編輯等路徑）送出的是 `null` ⇒ 等同沒帶 ⇒ **靜默覆蓋**。這是前端自己的洞，不需要等後端強制才能補。
- **後端相容性**：直接打這支 PUT 但不帶 token 的呼叫端——後端測試 38 個檔案、任何自動化／匯入腳本、舊分頁（尚未重新整理的舊版前端）。後端一律強制會讓這些全部 4xx。
- **建議（待裁示，本票沒改）**：①前端：編輯既有單但 `_lastUpdatedAt` 為空 ⇒ 不送，先載入最新版（或直接顯示衝突橫幅）；②後端：先**量測**——對「PUT 且沒帶 token」寫一筆計數／稽核（不擋），觀察一個版本；③確認只剩測試與已知工具後，才對「來自瀏覽器表單的呼叫」強制（可用請求標頭區分），內部工具走明確的 `force=true`＋稽核。直接全域強制不建議。

## 方法與限制

- 路由由腳本掃 `modules/case/api/*.py` 的 `@router.post|put|patch|delete` 裝飾器取得（多個裝飾器疊在同一函式的各算一條）；GET 不算。基底 commit 的 `quotation_stages.py` 等檔名可能隨 god-file 拆分改動，**清單以該 commit 為準**。
- `L` 6 條與 `O-高/中`（材料申請清單、協作者、階段、額外支出、材料匯款草稿、待辦、管銷比率）已讀過處理器；`O-低`、`T`（34）、`A`（44）是依函式名＋抽樣（`begin_write`、服務層狀態機如 `MP.approve`、狀態比較）分的，**沒有逐支讀完**——若發現某條被分錯，改這份文件即可，不影響程式。
- 只含 `modules/case`。其他模組（`vendor-contractors`、`network-plan-form`、`dev-crm` 等）已各自有 `expectedUpdatedAt` 的，不在這份。
