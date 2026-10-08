# 採購單缺廠商收款帳戶 → 擋付款（第 48 班設計備忘）

> 使用者裁示（Q2，2026-10-07/08，經 node-d8 轉述）：採購單的廠商銀行資料已在第 47 班可填；現在**只對「新採購單」缺資料時擋付款**，舊單不受影響。
> 預設**關閉**（開關在 `system_settings`），所以出貨安全；不改任何權限；Q3：自然人廠商只提示，不強制。

## 規則
- 開關：`system_settings.po_bank_block_since`＝本地時間字串 `YYYY-MM-DDTHH:MM:SS`；**缺鍵／空字串＝關閉**。
- 一張單會被擋，須同時成立：開關已開 ∧ `kind='purchase_order'` ∧ `created_at >= since`（切換時間點之後建立）∧ 收款人類型是廠商（`payee_type` 為 `vendor` 或空——採購單預設就是廠商）∧ **銀行名稱或帳號任一為空**（`payee_bank`／`payee_account`；去空白後判斷）。
- 舊單（`created_at < since`）、其他單據類型（差旅、零用金、無 kind 的舊額外支出）完全不受影響。
- 補資料的路：**既有的變更申請**（第 47 班；核准後 `payee_*` 才生效）。不新增任何權限或編輯入口。補齊後 `_po_bank_missing` 為假，即可付款。
- 自然人廠商（Q3）：不強制勾選；擋付款訊息與出納清單的提示文字多一句「廠商若為自然人，請確認已告知收款人」。

## 行為
| 位置 | 變更 |
|---|---|
| `payables._Payables.mark_paid`（出納 `POST /api/cashier/pending-payables/case/{key}/pay` 的唯一寫入點） | 符合規則 ⇒ 丟 `PoBankMissing`（`ValueError`，`status=409`）：「缺廠商收款帳戶：…」；沒寫任何東西；開關關＝零差異 |
| `payables.pending`（出納待付款清單） | 每列新增 `blocked`（bool）、`blockReason`（字串，不擋＝空）；原有 `payeeNote` 警示照舊 |
| `cashier.html` | 有 `blockReason` ⇒ 紅字顯示，「登錄付款」按鈕停用（後端 409 是最後防線） |
| `GET /api/extra-expenses/po-bank-block` | 財務角色／最高管理者：目前開關、切換時間、目前被擋的待付款張數 |
| `PUT /api/extra-expenses/po-bank-block` | **只有最高管理者**：`{"enabled": true}`＝切換時間點設為『現在』（可選 `since` 指定本地時間，不得是未來）；`{"enabled": false}`＝關閉。每次變更寫稽核 `settings.po_bank_block.update`（舊值→新值） |

## 風險與取捨
- 切換時間點用伺服器本地時間與 `created_at`（同為本地 isoformat）比字串；時區一致。時間點之前已建立、尚未付款的舊單永遠不擋（使用者裁示）。
- 關閉後再開：新的切換時間點會把「關閉期間建立的單」也納入——這是預期（由最高管理者決定時間點，稽核可追）。
- 出納端 `payee_info`（查看收款人銀行資料）不變。

## 測試
舊單不擋、新單擋（缺銀行／缺帳號各一）、補齊後可付、開關關＝無差異、其他單據類型不擋、清單有原因欄、`PUT` 權限（非最高管理者 403）與稽核、`since` 驗證（格式、未來）、突變（拿掉擋付款檢查 ⇒ 紅）。

## 稽核 #5 補強
- **寫入付款日的路徑（全盤點）**：`paid_date` 只有三處寫入——`payables.mark_paid`（出納登錄付款）、`PATCH …/extra-expenses/{id}/dates`（`set_extra_expense_dates`，財務角色／最高管理者可直接設付款日）、`payables` 的退回清除（清空，不是設定）。前兩處都套同一道檢查；清除不受擋。沒有其他 UPDATE（匯入、批次、叫料匯款是別的表）。
- 述詞同時放進兩處 `UPDATE … WHERE`（`payables.po_bank_block_sql`）：讀→寫之間若剛好有變更申請把收款資料清空，寫入本身仍然擋住（rowcount 0 ⇒ 409，什麼都不寫）。
- **已知取捨**：收款人類型被改成 `employee` 的採購單不套這條規則（員工收款走員工帳戶規則；畫面永遠送 `vendor`）。若日後要連這條也堵，把述詞的 `payee_type` 條件拿掉即可（會連員工代墊型採購單一起擋，需另行裁示）。
