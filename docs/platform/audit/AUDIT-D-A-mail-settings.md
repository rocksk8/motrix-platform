# 稽核：A 的信件與通知收件設定（wip/a-mail，合回前稽核）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。**合回前稽核**。只審新版（CORE-SPEC 35014aaa）。
> 對象：`wip/a-mail` `73345f94`（單一 commit；工作樹 `D:\MOTRIX-PLATFORM-A6`，D 只用 `git -C` 讀 HEAD，沒有動它）。規格：CORE-SPEC「使用者裁示」信件與通知的收件人、用語（2026-09-26）①～⑤；MODULE-GUIDE §11 用語規範。
> 稽核樹 `D:\MOTRIX-PLATFORM-D2`（detached），Python `D:\MOTRIX-PLATFORM\.venv312`（只用、未改）。
> 分級：**必修**／**建議**／**觀察**。關閉規則：被稽核者回覆後，由 D 確認才關。
> 縮寫：`MT`＝`backend/helpers/mail_types.py`、`EN`＝`backend/helpers/email_notify.py`、`MS`＝`backend/routers/mail_settings.py`、`TG`＝`backend/tests/platform/test_mail_registry.py`。

## 0. 結論

- 登記表 **52 種**＝L1 49（簽核 28、業務 15、系統技術 6）＋標案雷達 3，符合主持說的數目。系統技術類的預設群組由 `register()` 強制為「僅超級管理員」（MT:56-57）。未登記的 key 在執行時寄給超級管理員並記 ERROR（fail closed）。
- **「沒登記就寄出」的漏網路徑：沒有找到**。D 的查法：
  1. 全 repo（含 .ps1、tools）grep `smtplib`／`Send-MailMessage`／`SmtpClient`／`System.Net.Mail`／`sendmail`：產品碼只有 EN 用到 smtplib。
  2. EN 以外的寄送呼叫點只有 4 處：`archive.py:551`、`helpers/geo.py:767`、`modules/tender_radar/notify.py`（3 處）、`routers/system.py:2070`。收件人都經登記表的函式，主旨都經 `subject(key, …)`。
  3. 用 AST 檢查 EN 裡每一個呼叫寄送原語的函式：**全部**都經過登記表的收件人函式（沒有自己組收件人清單的）。
- 基準 **39 passed**。D 自做突變 10 項：**8 紅、2 存活**。
- **必修 1 項**：
  - M-M1：「找不到超級管理員時，不可以退回一般管理員」這條使用者明訂的規則沒有題目守（突變 E03 存活），而舊的說明文字還寫著「會退回」。
- 建議 3 項、觀察 3 項。

## 1. 逐項驗收（使用者裁示 ①～⑤）

| # | 裁示 | 驗收 | 證據 |
|---|---|---|---|
| ① | 獨立設定頁，每一種信件都能指定收件人（帳號、角色、僅超級管理員） | ✅ | MS:32-79；`frontend/pages/mail-settings.html`；e2e `test_e2e_mail_settings_2026_09_26.py`；突變 E10（custom 可以沒有任何收件人）紅 |
| ② | 每一種信件都要登記，沒登記的寄送路徑由守門擋 | ✅ | TG 靜態掃描（收件人呼叫帶已登記的字面 key、主旨由 `subject()` 產生、`_build_html` 的 key 已登記）；突變 E06 紅；執行期 fail closed：突變 E04 紅。漏網路徑的查法見 §0 |
| ③ | 系統技術類預設只寄超級管理員，一般管理員不收 | ✅ 預設 ／ ⚠ 找不到時 | MT:56-57 強制；EN `_only_superadmins` 不退回（EN:185-191）；突變 E01、E02 紅。**找不到超級管理員時的行為沒有題目**（M-M1） |
| ④ | 個人只能退訂自己收得到的類型，不能自己加入受限類型 | ✅（清單的一個分支沒有題目） | 退訂生效：突變 E07 紅；`receivable()`（MS:82-92）在「僅超級管理員」模式下的判斷沒有題目：突變 E09 存活（M-S2） |
| ⑤ | 用語正式化：主旨前綴、固定段落、禁用詞守門 | ✅ | `SUBJECT_PREFIX`：突變 E08 紅；禁用詞：突變 E05（內文加「多半」）紅；`test_mail_body_has_the_fixed_sections` |

裁示 ③ 寫的是「**預設**只寄超級管理員」，所以超級管理員在設定頁把系統技術類改成 custom、加上「管理員」角色，屬於允許的覆寫，不列為發現。

## 2. 突變（D 自做；在 `D:\MOTRIX-PLATFORM-D2`，每項都用 `git checkout` 還原並核對內容）

| 突變 | 結果 | 轉紅的題 |
|---|---|---|
| E01 系統類可以預設給管理員（拿掉 register 的檢查） | 🔴 | `test_registry_rules` 等 2 |
| E02 `_only_superadmins` 改成查管理員＋超級管理員 | 🔴 | `test_system_mail_goes_to_superadmins_only` 等 4 |
| E03 找不到超級管理員時退回一般管理員 | 🟢 **存活** | —（M-M1） |
| E04 未登記的 key 當成業務類寄給管理員 | 🔴 | `test_unregistered_key_is_fail_closed` |
| E05 獎金信內文加入禁用詞「多半」 | 🔴 | `test_every_mail_path_is_registered_formal_and_uses_the_registry` |
| E06 收件人呼叫用未登記的 key | 🔴 | 同上 |
| E07 個人退訂不生效 | 🔴 | `test_personal_mute_only_removes_and_list_shows_receivable` 等 2 |
| E08 主旨前綴改掉 | 🔴 | `test_registry_rules` |
| E09 「僅超級管理員」模式下，人人都列為收得到 | 🟢 **存活** | —（M-S2） |
| E10 custom 可以沒有任何收件人 | 🔴 | `test_settings_endpoint_validates_and_is_superadmin_only` |

## 3. 發現

### 必修

**M-M1　「找不到超級管理員時不可以退回一般管理員」沒有題目，而舊的說明還寫著「會退回」**
- 位置：EN:185-191 `_only_superadmins`（行為正確：找不到就記 ERROR、回空清單）。但 `archive.py:530-536` 的 docstring 仍寫「`_superadmin_emails()` 找不到人時仍會 fallback 回全體 admin/superadmin，不會真的寄不出去」，已經與程式相反。
- 為什麼是必修：這是使用者的原話（「普通管理員不需要收到這類信」），主持也點名「找不到收件人時也不可以退回給一般管理員」。這一版之前的行為正好相反（退回管理員），而留在程式裡的說明還描述著舊行為。依 PLAYBOOK §C-5，新規則要配守門。D 的突變 E03（找不到時改查 `role='admin'`）存活，證明現在沒有任何題目會擋下「照著舊說明改回去」。
- 建議修法：
  - 補一題：沒有啟用中的超級管理員（或他們都沒有 email、都退訂）⇒ 系統技術類的收件人是空清單、記 ERROR、一般管理員收不到；備份告警則走 `_alert_email_failed`。
  - 用突變 E03 證明這一題會紅。
  - 更正 `archive.py` 的 docstring，保留原句並標註更正。

### 建議

- **M-S1　所有超級管理員都退訂某一種系統技術類時，那一類就沒有人收，而且只在記錄檔裡有一行 ERROR**：個人退訂（`notification_muted`）對系統技術類同樣生效。備份告警有 `_alert_email_failed` 的警示檔可以接住，其他系統技術類（憑證到期、磁碟空間、地圖額度）沒有。建議：系統技術類至少要有一位超級管理員不可以退訂；或者在設定頁顯示「目前沒有任何人會收到」。
- **M-S2　「收得到的類型」清單在「僅超級管理員」模式下沒有題目**：`receivable()` 的 `superadmin_only` 分支被改成「人人都收得到」，題目照樣綠（E09）。這份清單決定使用者管理頁能勾哪些退訂項目。它不會讓人收到信（寄送端另有判斷），但會讓畫面列出其實收不到的類型。
- **M-S3　每月營運報表的收件人有兩個來源**：`_monthly_report_recipient_emails`（EN:1442-1470）在覆寫模式是 `default` 時，讀的是舊的 `monthly_report_recipients` 設定，而設定頁對 `monthly_report` 顯示的是登記的預設群組「僅超級管理員」。只要舊設定存過一次，設定頁顯示的收件人就不是實際的收件人。建議設定頁對這一種類型顯示實際的來源，或把舊設定搬進覆寫表之後退場。

### 觀察

- **O-1　靜態守門的範圍**：TG 的 `scan()` 只看函式本體內的呼叫，而且寄送呼叫只認「第 2 個位置參數」是主旨。寫在模組層的寄送、用 `subject=` 關鍵字參數傳主旨，都不會被檢查。目前沒有這種寫法（D 查過 51 個呼叫點），記下範圍就好。
- **O-2　`_superadmin_emails` 的名稱與行為不一致**：它現在等於 `_group_emails`（EN:1437-1439），寄給「登記的預設群組」而不一定是超級管理員。所有呼叫它的 key 目前都登記成 `superadmins`，所以結果相同；但新增呼叫時容易誤解。建議改名，或加一條守門：呼叫它的 key 必須登記成 `superadmins`。
- **O-3　設定寫入沒有鎖**：`set_mail_recipients` 讀整份覆寫表、改一鍵、整份寫回（MS:70-76）。兩位超級管理員同時改不同類型時，後寫的會蓋掉先寫的。影響小，記下來。

## 4. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | D 確認 |
|---|---|---|---|
| M-M1 | | | |
| M-S1 | | | |
| M-S2 | | | |
| M-S3 | | | |
| O-1～O-3 | | | |
