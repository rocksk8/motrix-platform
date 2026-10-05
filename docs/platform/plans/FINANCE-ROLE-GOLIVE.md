# 財務角色（第42班）：範圍、上線步驟、回滾

使用者 2026-10-05 裁示（經 PM 轉達，覆蓋 USER-PERMISSIONS-DEFAULTS 的第 1／2 題）：

1. 財務與出納權限**只屬於「財務」角色（`users.role = 'finance'`）與 superadmin**；所有 F 類守門的 admin 直通拿掉。
2. 上線當下，既有 admin／sales 帳號 `users.modules` 內的 `cashier`／`finance`／`financial_view` 勾選**惰性**（程式不再認；資料不刪，回滾即還原）。
3. superadmin 不變式不變：財務／出納的頁面、按鈕、API、PDF、通知都能用。
4. 付款／匯款／出納類通知改寄「財務」角色＋superadmin（不再寄全體 admin）。

## 實作

- `helpers/auth.py`：`has_finance_access`／`has_cashier_access`（＝角色 ∈ {superadmin, finance}）、`user_has_module(財務三鍵)` 由角色推導、`effective_modules`（登入／`me`／選單回傳）、`finance_usernames(conn)`。
- 通知：`helpers.email_notify.finance_recipient_emails(event_key)`（在職、有 Email、未退訂的財務角色＋superadmin）；`notify_module_activity(..., audience="finance")`；`mail_types` 群組 `finance`。**給提醒類（到期前 3 天／當天）使用：`finance_usernames(conn)`（帳號）或 `finance_recipient_emails(key)`（信箱）。**
- 使用者管理：角色下拉（新增／編輯／自訂角色基礎角色）新增「財務（財務與出納）」；三個財務勾選灰色並附說明；建立／修改使用者驗證角色值；角色或財務勾選變更寫 `user.role_change` 稽核（前後值）。
- 預設模組樣板：admin／sales 不再含財務三鍵；新增 `finance` 樣板。

## 已改的 F 類端點／判斷

| 區 | 內容 |
|---|---|
| 承攬匯款 | `_require_admin`（建立／預覽／刪除／發票登錄／作廢／送審／撤銷核准／匯出）、勞報單關聯（出納）、paid-toggle（含差額核可）、`GET /api/remit-kinds` |
| 開票／請款憑證 | `invoice_vouchers`／`payment_requests` 的 `_require_admin`（建立／修改／刪除／送審／撤銷／匯出） |
| 出納 | 查看、登錄付款、完整銀行帳號、差額核可／退回、銀行對帳 |
| 會計 | T100 匯出設定讀取、傳票匯出（含預覽／確認／取消確認；確認寫入僅 superadmin 為預設 Q7，目前與匯出同為財務角色——見「未改」） |
| 案件 | 額外支出列／金額可見、付款日登錄、標記收款、整包存款項鎖、更換發票號碼、收款帳戶查詢、稅額沖銷申請／取消、財務彙總清單、`can_see_financial` 全部連動點 |
| 叫料 | 發票日登錄、取消已核准叫料單、匯款申請撤回／作廢、編輯閘 `can_edit_orders`（admin 直通拿掉） |
| 其他 | 儀表板財務數字、年度營運目標、進貨批次標記已付款、獎金金額讀取（基數／預覽／PDF；「產生」不動） |
| 前端 | `canSeeFinancial`／`canMarkPayment`／`canFinanceRole`、`cashier.js`、`reports.js`、案件頁請款／開票／沖銷／憑證操作／匯款申請區塊、匯款款別載入、叫料取消鈕 |

## 刻意沒改

- 額外支出 `_can_modify`（admin 可改別人填的單）、費用單開單入口、案件列範圍（`row_access.ADMIN_ROLES`）、簽核佇列可見範圍：屬一般管理（M），金額另有遮蔽。
- 營運報表 11 支：財務角色／superadmin **或持有 `reports` 模組者**仍可看（模組制，不是 admin 直通）；admin 樣板保留 `reports`。要收緊請另裁示。
- T100 confirm／unconfirm（Q7 預設僅 superadmin）：本班維持與匯出同一道（財務角色）；待使用者確認是否單獨收成 superadmin。
- 派工金額／發票日（vendor_contractors）、進貨批次建立／修改：維持一般管理。

## 上線步驟（正式機視窗）

1. 先跑唯讀報表：`cd backend; python tools/finance_role_impact_report.py`（`--json` 可供步驟檔存檔）。列出**上線後會失去財務／出納的帳號**，並檢查有沒有在職「財務」角色帳號（沒有 ⇒ 警告，結束碼 1；沒有 superadmin ⇒ 錯誤，結束碼 2）。
2. 讓使用者看清單；在使用者管理把負責財務／出納的人員角色改為「財務」，並確認其 Email。
3. 部署程式（無 schema 變更）；已登入的人需重新登入（側欄選單隨登入／`me` 的有效模組更新）。
4. 上線後再跑一次報表，確認 `keepFinance` 有人；用財務帳號走一遍出納頁與憑證建立；用 admin 帳號確認 403。

## 回滾

只回程式即可：`users.modules` 勾選未動，舊版程式讀到原勾選即還原 admin／sales 的舊行為；`role='finance'` 的帳號在舊版程式裡是未知角色（建議回滾前先把這些帳號改回 admin 或 sales）。
