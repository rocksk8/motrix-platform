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
| 會計 | T100 匯出設定讀取、傳票匯出預覽／下載＝財務角色；**確認／取消確認＝僅 superadmin**（預設 Q7；設定寫入本來就是 superadmin） |
| 案件 | 額外支出列／金額可見、付款日登錄、標記收款、整包存款項鎖、更換發票號碼、收款帳戶查詢、稅額沖銷申請／取消、財務彙總清單、`can_see_financial` 全部連動點 |
| 叫料 | **取消已核准叫料單、改成本單價＝財務角色**；材料申請的匯款申請（建立／撤回／作廢）＝財務角色；建立／送審／到貨確認／發票日仍是一般管理（admin 維持，Q6）：叫料體系改用 `material_money_visible`（superadmin／admin／財務角色），不再依賴財務金額可視 |
| 承攬派發（Q5） | 發票日（`PATCH …/invoice-date`）、發票附件上傳／刪除、以及 `PUT` 修改品項／人員金額、稅率或發票日 ⇒ 財務角色；建立／狀態／驗收仍是一般管理（admin 維持）。前端發票日欄位、上傳發票按鈕對非財務停用／隱藏 |
| 其他 | 儀表板財務數字、年度營運目標、進貨批次標記已付款、獎金金額讀取（基數／預覽／PDF；「產生」不動） |
| 前端 | `canSeeFinancial`／`canMarkPayment`／`canFinanceRole`、`cashier.js`、`reports.js`、案件頁請款／開票／沖銷／憑證操作／匯款申請區塊、匯款款別載入、叫料取消鈕 |

## 刻意沒改

- 額外支出 `_can_modify`（admin 可改別人填的單）、費用單開單入口、案件列範圍（`row_access.ADMIN_ROLES`）、簽核佇列可見範圍：屬一般管理（M），金額另有遮蔽。
- 營運報表 11 支：**使用者已裁示**維持——財務角色／superadmin **或持有 `reports` 模組者**（admin 樣板保留 `reports`）仍可看；只有「年度營運目標」設定本身是財務專屬。
- 進貨批次建立／修改：維持一般管理。

## 上線步驟（正式機視窗）

1. 先跑唯讀報表：`cd backend; python tools/finance_role_impact_report.py`（`--json` 可供步驟檔存檔）。列出**上線後會失去財務／出納的帳號**，並檢查有沒有在職「財務」角色帳號（沒有 ⇒ 警告，結束碼 1；沒有 superadmin ⇒ 錯誤，結束碼 2）。
2. 讓使用者看清單；在使用者管理把負責財務／出納的人員角色改為「財務」，並確認其 Email。
3. 部署程式（無 schema 變更）；已登入的人需重新登入（側欄選單隨登入／`me` 的有效模組更新）。
4. 上線後再跑一次報表，確認 `keepFinance` 有人；用財務帳號走一遍出納頁與憑證建立；用 admin 帳號確認 403。

## 回滾

只回程式即可：`users.modules` 勾選未動，舊版程式讀到原勾選即還原 admin／sales 的舊行為；`role='finance'` 的帳號在舊版程式裡是未知角色（建議回滾前先把這些帳號改回 admin 或 sales）。

## 已知的後續（follow-up）

- **自核自匯風險**：出納與財務合併為同一個「財務」角色後，同一個人可以登錄付款、也可以核可／退回匯款差額（預設 Q4 原本是「出納不可核差額」）。目前以稽核紀錄與通知兜底；日後做「職責角色化」（USER-PERMISSIONS-PROPOSAL §9）時可加職務分離檢查（同一人不可同時建立匯款、標記已匯款、核可差額）。
- 已登入的人要重新登入，側欄選單才會更新（後端授權即時生效）；只寫在文件，不另做強制登出。

## 使用者已裁示的取捨（上線須知）

- **精算／財務分頁／款項期別編輯**：經 `can_see_financial`，只剩財務角色與 superadmin 可開啟、儲存、完結精算與編輯款項期別；**sales／admin 失去這些**（使用者已裁示）。被遮蔽的帳號新增／刪除／重排款項期別會得到 403（`PaymentStructureChange`）。業務由報價單轉案件時不需要編輯款項結構（上線前請業務確認）。
- **營運報表**：維持 admin／`reports` 模組持有者可看（見上）。
- **自訂模組的財務類單據**：由各自的權限鍵（自訂模組定義內的角色／模組設定）決定，不受 `finance` 角色影響；本班不改。
- **獎金金額、勞報單金額與簽回檔**：財務角色與 superadmin 可看（使用者已核可；見 `modules/payroll/SPEC.md`「第42班」）。
- **報價單層級 vs 財務專屬（使用者裁示「拆開」）**：業務／管理員維持**編輯報價單、看報價總額與品項成本／毛利**（`helpers.financial_mask.quote_money_visible`＝superadmin／admin／sales／財務角色），也維持材料申請日常作業（`material_money_visible`）；**精算、款項期別（收款／付款）、財務總覽、出納**等才是財務角色專屬（`money_visible`／`can_see_financial`）。業務／管理員編輯報價單時，被遮蔽的精算與款項期別以資料庫現值補回（`restore_case_record`＋settlement），不會被空值蓋掉。重新指向的位置：`quotations.py` 的清單遮蔽、`stage-board`、單筆 GET、`PUT /api/quotations/{no}`、含成本 PDF、案件匯出金額欄；`reports.py`／`ledger_diff.py` 的金額旗標（營運報表維持 D2 的裁示）。
- **案件擁有者範圍**：財務角色與 superadmin 不受案件擁有者限制的金額面端點：額外支出（`case_owner_readable`，連帶其附件提供者）、材料申請（建立／發票日／讀取）、材料申請匯款申請、精算（`helpers.case_access.require_case_money`）；admin 維持既有直通。
