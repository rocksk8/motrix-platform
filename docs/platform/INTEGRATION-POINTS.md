# 模組串接點登記（INTEGRATION-POINTS）

> 每一個跨組串接點都登記在這裡。L2 模組之間不可以直接 `import` 對方的程式（CORE-SPEC §2）；
> 需要對方的能力時，由擁有方公開一個串接點，使用方只依賴這裡寫下的契約。
> 判斷準則：**對方不在時，使用方要能少一項資訊，而不是壞掉。**

每一筆都要寫明六件事：

| 欄位 | 意思 |
|---|---|
| 形式 | provider（`core.registry`）／事件／HTTP… |
| 語法 | 提供方怎麼登記、使用方怎麼取用（可以直接複製的那一行） |
| 回傳 | 形狀與使用方實際讀的欄位 |
| 對方不在時 | 使用方的退化行為（必須可用，只少資訊） |
| 契約版本 | 目前版本；欄位只准加，改名／刪除要升版 |
| 守門 | 哪一題測試會在契約被破壞時變紅 |

---

## IP-1　`dispatch.row`：派工單列序列化（M04 → M01、M06）

對應 DEPENDENCY-MAP §3 #7、#8、#9（ROADMAP A6）。原本 `helpers/recognition.py`（M01）、
`routers/vouchers.py`（M06）直接 import `routers.vendor_contractors._dispatch_row`（M04 私有函式）；
`routers/reports.py`（M08）import 了但沒有呼叫，已刪除。

| 欄位 | 內容 |
|---|---|
| 提供方 | M04 外包工班：`routers/vendor_contractors.py::_dispatch_row` |
| 使用方 | M01 `helpers/recognition.py::dispatch_entries`（應計派工成本，營運報表支出用）；M06 `routers/vouchers.py::_case_expense_sources`（傳票摘要來源的承攬商派工） |
| 形式 | provider，單一提供者（`core.registry`）。M04 尚未搬進 `modules/`，暫以 `registry.provide()` 在匯入時登記；搬遷後改寫進 `ModuleSpec.providers`，這一行刪除 |
| 語法 | 提供：`_registry.provide("dispatch.row", "subcontract", _dispatch_row)`<br>取用：`fn = registry.single_provider("dispatch.row")`；`None` ⇒ 退化。兩個以上提供者 ⇒ `RuntimeError`（兩份實作在搶，不隨便挑） |
| 回傳 | `fn(row: sqlite3.Row) -> dict`。`row` 是 `contractor_dispatches` 一列（可 JOIN `vendor_contractors.name AS vendor_name`）。使用方讀的欄位：`id`、`quoteNo`、`vendorName`、`scope`、`items`、`personnel`、`totalAmount`、`personnelTotal`、`grandTotal`（含稅承攬商費用＋外包人員）、`invoiceNo`、`acceptedAt` |
| 對方不在時 | recognition：應計派工回 `[]` 並記 WARNING ⇒ 營運報表少了承攬商這一類支出，其餘照常。現金口徑讀匯款申請快照，不受影響。<br>vouchers：案件支出來源只剩額外支出，不列承攬商派工。<br>皆不丟例外 |
| 契約版本 | 1（2026-09-25） |
| 守門 | `backend/tests/platform/test_dispatch_connector.py`：①提供者存在且回傳含全部使用欄位 ②registry 重複／多提供者規則 ③**反向控制**：同一批資料先確認派工那一類非空，拿掉提供者後三處照常回結果、只少派工 ④全 backend 不再有人 `import _dispatch_row`。突變驗證：拿掉退化判斷、拿掉 M04 登記、vouchers 不看提供者，三者皆轉紅 |

**尚未處理（不在 A6 範圍）**：`routers/reports.py::_live_dispatch_totals_by_quote` 自己又算了一次
grandTotal（直接讀 `contractor_dispatches`，沒有經過 `_dispatch_row`）。這是同一算法的第二份實作，
也是 M08 直接讀 M04 的表；應改用 IP-1，另開題。
（2026-09-25 主持裁示：等 M08 搬遷時再處理。）

---

## IP-2　`voucher.draft`＋`voucher.account_check`：建立傳票草稿（M06 → M07）

對應 DEPENDENCY-MAP §3 #19（ROADMAP A7）。原本 `helpers/bonus_vouchers.py`（M07）直接 import
`routers.vouchers.insert_draft_voucher／_line_sources／_amount_lines`、`routers.accounting_export.validate_account_code`、
`helpers.voucher.classify_category`（皆 M06）。

| 欄位 | 內容 |
|---|---|
| 提供方 | M06 會計：`routers/vouchers.py::_provide_voucher_draft`、`routers/accounting_export.py::validate_account_code` |
| 使用方 | M07 `helpers/bonus_vouchers.py`（進入待發放 ⇒ 轉帳草稿；標記已發放 ⇒ 支出草稿；科目設定頁的驗證）、`routers/bonus.py`（標記已發放時驗出納選的銀行科目） |
| 形式 | provider，單一提供者（`core.registry`；M06 尚未搬進 `modules/`，以 `registry.provide()` 在匯入時登記） |
| 語法 | 提供：`_registry.provide("voucher.draft", "accounting", _provide_voucher_draft)`、`_registry.provide("voucher.account_check", "accounting", validate_account_code)`<br>取用：`registry.single_provider("voucher.draft")(conn, voucher_date=…, summary=…, lines=[{account_code, summary, debit, credit}], created_by=…, now=…)`；`registry.single_provider("voucher.account_check")(conn, code)` |
| 回傳 | draft：`{"id": int, "voucher_no": str}`；在呼叫端的交易裡寫入 `vouchers_all`＋`voucher_lines`，**不 commit**（呼叫端的狀態與傳票連結一起成功、一起失敗）。分錄正規化與傳票類別由 M06 決定。<br>account_check：`(ok: bool, err: str)` |
| 對方不在時 | **獎金核准／標記已發放照常成立**，不產生傳票，而且明說：回傳 `notice`＝「未產生傳票：會計模組未安裝（獎金狀態照常更新；需要傳票請由會計手動開立）」（前端 `_withNotice` 顯示）。出納帶了銀行科目也不驗、不擋發放。科目設定：GET 的 `problems` 每一項為「會計模組未安裝，無法驗證科目」；PUT 回 400 並寫明原因，一個都不寫入（驗證不了就不存） |
| 契約版本 | 1（2026-09-25） |
| 守門 | `backend/tests/platform/test_voucher_connectors.py`：①提供者存在、draft 真的寫出草稿與分錄且不 commit、account_check 對錯都對 ②**反向控制**：同一條流程有 M06 時產生兩張草稿（正對照），拿掉提供者後獎金照走、零張傳票、notice／voucherNotice／problems 都有明確提示 ③M07 不再 import M06 ④頁面綁定 `detail.voucherNotice`。突變驗證：不查 M06、默默略過（notice 空）、仍驗銀行、銀行清單不處理缺席，四者皆轉紅 |

**尚未處理（不在 A7 範圍）**：`helpers/bonus_vouchers.py::withdraw_accrual`（退回時作廢轉帳草稿）與
`linked_vouchers`（明細列出連結的傳票）仍直接讀寫 M06 的 `vouchers_all`。M06 不在時表仍在（凍結 migration），
行為不會壞，但屬 M07 直接寫 M06 的表（DEPENDENCY-MAP §4）；應由 M06 再公開「作廢草稿」「查傳票狀態」兩個連接器，另開題。
➡ 2026-09-25 已處理：見 IP-4。

---

## IP-3　`accounting.settings`：會計設定（付款銀行）（M06 → M07）

對應 DEPENDENCY-MAP §3 #18（ROADMAP A7）。原本 `routers/bonus.py:1885` 函式內 import `routers.accounting_export._t100_config`。

| 欄位 | 內容 |
|---|---|
| 提供方 | M06 會計：`routers/accounting_export.py::_provide_accounting_settings` |
| 使用方 | M07 `routers/bonus.py::_payout_bank_choices`（待發放時給出納選付款銀行） |
| 形式 | provider，單一提供者（同 IP-2） |
| 語法 | 提供：`_registry.provide("accounting.settings", "accounting", _provide_accounting_settings)`<br>取用：`registry.single_provider("accounting.settings")()` |
| 回傳 | `{"bankAccounts": [{"name", "acctCode"}], "defaultBankAccountCode": str}`——**只公開這一小塊**，不給整份 T100 設定（其餘是會計內部設定） |
| 對方不在時 | 明細回 `bankAccounts: []`、`defaultBankAccountCode: ""`，並加 `voucherNotice`＝「未產生傳票：會計模組未安裝（標記已發放照常，不會產生支出傳票）」，獎金頁在「標記已發放」按鈕旁顯示 |
| 契約版本 | 1（2026-09-25） |
| 守門 | 同 IP-2 的測試檔（契約形狀＝恰好兩個鍵；反向控制檢查 `bankAccounts` 為空且 `voucherNotice` 有提示；頁面綁定） |

---

## IP-4　`voucher.void_draft`＋`voucher.status`：作廢草稿、查傳票狀態（M06 → M07）

接續 IP-2 的「尚未處理」。原本 `helpers/bonus_vouchers.py::withdraw_accrual`／`linked_vouchers`（M07）直接讀寫
M06 的 `vouchers_all`。

| 欄位 | 內容 |
|---|---|
| 提供方 | M06 會計：`routers/vouchers.py::_provide_voucher_void_draft`、`_provide_voucher_status` |
| 使用方 | M07 `helpers/bonus_vouchers.py`：`withdraw_accrual`（獎金退回 ⇒ 作廢未送審的轉帳草稿）、`linked_vouchers`（明細列出連結的傳票）、`create_accrual`（殘留草稿防護） |
| 形式 | provider，單一提供者（同 IP-2） |
| 語法 | 提供：`_registry.provide("voucher.void_draft", "accounting", _provide_voucher_void_draft)`、`_registry.provide("voucher.status", "accounting", _provide_voucher_status)`<br>取用：`registry.single_provider("voucher.void_draft")(conn, voucher_id, voided_by=…, now=…, reason=…)`；`registry.single_provider("voucher.status")(conn, voucher_id)` |
| 回傳 | void_draft：`{"result": "voided"｜"not_draft"｜"gone", "voucher_no", "status"}`——只作廢「草稿」；已送審 ⇒ `not_draft` 不動；不存在或早已作廢 ⇒ `gone`。status：`{"id", "voucher_no", "status", "voided"}`，不存在 ⇒ `None`。兩者都在呼叫端的交易裡，**不 commit** |
| 對方不在時 | **退回照常**成立；不作廢、**保留連結**（之後查得到是哪一張），回傳 `notice`＝「未作廢傳票（#id）：會計模組未安裝；退回照常，請會計另行處理那一張傳票」。明細仍列出每一張連結的傳票，標 `unavailable` 與「會計模組未安裝，無法查詢狀態」，頁面不給連結（不讓傳票從畫面消失）。<br>**M06 回來後**：再次進入待發放時，若舊連結仍是未作廢的草稿 ⇒ 不另開、不覆蓋，notice 明說「上一張轉帳傳票草稿 … 尚未作廢」；舊連結已送審 ⇒ 照原行為另開新草稿 |
| 契約版本 | 1（2026-09-25） |
| 守門 | `backend/tests/platform/test_voucher_status_connectors.py`：①void_draft 三種結果＋status 形狀＋不 commit ②**反向控制**：有 M06 時退回會作廢（正對照）；拿掉後不作廢、有提示、連結保留、M06 的表沒被動、明細標無法查詢 ③M06 回來：殘留草稿不另開不覆蓋；已送審的舊連結照常另開 ④M07 原始碼不再出現 `vouchers_all`、頁面有 unavailable 分支。突變 5 種皆轉紅（默默略過、傳票從明細消失、拿掉殘留防護、防護放太寬擋到已送審、M06 不在仍解除連結） |
