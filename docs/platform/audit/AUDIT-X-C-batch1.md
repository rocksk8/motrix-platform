# 稽核：C 的第一批合回（A11／STATES 高風險 5 項／A8c／升級只補空值／company_identity／CORE_VERSION 1.3）（X 稽核，2026-09-25）

> 依 CORE-SPEC §9d、PLAYBOOK §E。稽核者 X 沒有參與這批程式。
> 對象（已合回 platform）：
>
> | commit | 內容 |
> |---|---|
> | `1bd70225` | A11：IP-5 `daily_task.external`、IP-6 `calendar.writeback` |
> | `3c2213f6` | STATES 高風險 5 項：S-CD02／S-CC07／S-CC06／S-CN03／S-CU10 |
> | `0f1d029a` | A8c：公司聯絡資料改從 company_identity 取 |
> | `11e85578` | 升級轉換只補空值 |
> | `a4b81042` | company_identity 認得 `name`／`contact_info` |
> | `fceaadde` | CORE_VERSION 1.3 |
>
> 同時核對 `docs/platform/INTEGRATION-POINTS.md` 的 IP-5、IP-6。
> 基準：platform `507a76ea`，稽核在 detached worktree `D:\MOTRIX-PLATFORM-AUD` 進行。產品程式碼一行都沒改：突變都已還原，臨時題目已刪除，`git status` 乾淨。
> 分級：**必修**／**建議**／**觀察**。關閉規則：被稽核者回覆後，由 X 確認才關。
> 路徑前綴 `backend/`。縮寫：
> - `A`＝`archive.py`
> - `GC`＝`helpers/google_calendar.py`
> - `CST`＝`helpers/case_stage_tasks.py`
> - `CI`＝`helpers/company_identity.py`
> - `CU`＝`core/upgrade.py`
> - `Q`＝`routers/quotations.py`
> - `TSD`＝`tests/test_states_data_ops_2026_09_25.py`
> - `TCS`＝`tests/platform/test_case_stage_connectors.py`
> - `TA8`＝`tests/test_company_contact_a8c_2026_09_25.py`
>
> 重現環境同 `AUDIT-X-9c-module-select.md`（`PYTHONDONTWRITEBYTECODE=1`；basetemp `%TEMP%\motrix-pytest-AUD-adhoc`）。

## 0. 結論

- 六筆的主要行為都有做到：
  - IP-5／IP-6 在提供者不在時照常運作，並且有明說（API 回 `notice`，log 記 WARNING）。
  - 損毀的庫在預檢被擋下、快照拒收、舊快照保留。
  - 告警的四個管道各自獨立，寄成功才寫節流。
  - 升級只補本公司安裝、已有值的欄位不動。
  - CORE_VERSION、CHANGELOG 與 G1 快照一致。
- **必修 3 項**：
  1. A-1：時鐘往前跳時，實作是「保留最新 7 份，其餘照刪」，不是 STATES 寫的「不清理並告警」。X 實測：跳的當天，30 份真實快照剩 6 份；第 7 天之後一份都不剩；告警只出現在第一天。
  2. A-2：S-CD02「啟動時做 quick_check」的守門題是假綠燈：把呼叫刪掉，那一題照綠。
  3. A-3：IP-6 的守門有兩個洞：
     - 「兩個欄位分開寫回」那一題兩邊寫的是同一個值，驗不出寫反；
     - invoice／payment／shipping 三支回寫沒有任何題目執行過，突變後整份照綠。
- 建議 4 項、觀察 7 項。
- 驗證：本批相關題目 **137 passed**：`TSD`、`TCS`、`TA8`，以及 `tests/platform/test_core_upgrade.py`、`test_l1_interface_snapshot.py`、`test_backup_retention_policy_2026_09_14.py`、`test_cloud_storage_2026_09_07.py`。合併基準（`tests/platform` 全部加上本批與 §9c 的相關檔）**437 passed**。

## 1. 逐項驗收

| 項目 | 規格／宣稱 | 驗收 | 證據 |
|---|---|---|---|
| IP-5 提供者 | M12 在匯入時登記，M01 不再直接寫 `daily_tasks`／`daily_task_completions` | ✅ | `routers/daily_tasks.py:2092-2142`；`TCS::test_m01_and_l1_no_longer_write_foreign_tables`；`table_write_exceptions.json` 刪了 7 筆 |
| IP-5 對方不在時 | 勾選照常存檔，回應 `notice` 明說，零筆任務 | ✅（API 層）／⚠（畫面沒有顯示，見 B-1） | Q:3350-3365；`TCS::…without_m12…`；X 補跑：取消勾選與刪除階段都回 200（§3 R3） |
| IP-6 回寫 | 擁有模組拿寫鎖、重讀，只寫 event id | ✅（quotation／case_stage）／⚠（其餘三支沒有測試，見 A-3） | GC:234-244；Q:6868-6895；`routers/invoice_vouchers.py:803-820` 等 |
| IP-6 對方不在時 | 事件照建、不回寫、記 WARNING | ✅ | `TCS::…without_owner…`；X 補跑 case_stage 那一種：`event_id=''`、WARNING（§3 R4） |
| INTEGRATION-POINTS IP-5／IP-6 六項 | 形式／語法／回傳／對方不在時／契約版本／守門 | ✅ 內容與程式一致（見 C-3） | X 逐一核對了 8 個 capability 名稱與簽章 |
| S-CD02 | 快照與啟動做 quick_check，不過 ⇒ 不寫 `.done`、不清舊快照、ERROR | ✅ 行為／❌ 啟動那一題是假綠燈（A-2） | A:1014-1018；main.py:551-568；`TSD::test_state_cd02_*` |
| S-CC07 | 清理前檢查差距，**差距異常 ⇒ 不清理並告警**；永遠保留最新 N 份 | ⚠ 只做到後半（A-1） | A:1401-1436；STATES-DATA-OPS S-CC07「應有行為」 |
| S-CC06 | 同日重試月備份，上月缺漏告警 | ✅ | A:2325-2334、A:2158-2180；`TSD::test_state_cc06_*` |
| S-CN03 | 四個管道各自 try；寄成功才節流；寄不出去另留痕跡 | ✅（寄不出去的痕跡沒有速率上限，見 B-4） | A:415-510；`TSD::test_state_cn03_*`。X 核對了假的 `_Handle` 與真的 `SendHandle.wait()` 介面一致（`helpers/email_notify.py:290-325`），測試替身沒有替自己開後門 |
| S-CU10 | 預檢跑 quick_check，不過 ⇒ problem | ✅ | CU:295-297；`TSD::test_state_cu10_*` |
| A8c | 報表、網路規劃、拓樸不再寫死聯絡資料 | ✅（掃描範圍見 C-4） | `TA8::test_no_hardcoded_company_contacts_left` |
| 升級只補空值 | 只補本公司安裝；已有值不動；驗證只接受補上的欄位 | ✅（有一個邊界不一致，見 B-2） | CU:529-575、CU:592-597。X 重現：別家公司 ⇒ `skipped`；本公司、統編有值 ⇒ 補 3 欄且驗證接受 |
| company_identity 認得 `name`／`contact_info` | 設定頁最上方的欄位也要印得出來 | ✅（`contact_info` 的拆法見 B-3） | CI:63-73、CI:115-125；`TA8::test_top_level_settings_fields_reach_the_documents` |
| CORE_VERSION 1.3 | 新增介面就升次版號；CHANGELOG 與 G1 快照一致 | ✅ | `core/registry.py:14`；`core/CHANGELOG.md` 1.3 段；`l1_interface_snapshot.json` 含 `quick_check`、`fill_company_profile_blanks`、`contact_line` 等；G1 綠 |

## 2. 發現

### 必修

**A-1　時鐘往前跳：保留 7 份之外照刪，而且告警只響第一天**
- 位置：A:1417-1436（`_prune_select`）。STATES-DATA-OPS S-CC07 的「應有行為」：「差距異常（例：今天比最新快照晚 >2 天而中間沒有快照）⇒ **不清理**並告警；永遠保留最新 N 份」。實作只做了後半。
- X 的實測（臨時題，已刪除）：
  - 設定：30 份真實日期的本機快照；時鐘往前跳 40 天；接著照常每天快照＋清理，共 10 天。
  - 結果（第幾天，總份數，真實日期份數，當天告警數）：`(1,7,6,1) (2,7,5,0) (3,7,4,0) (4,7,3,0) (5,7,2,0) (6,7,1,0) (7,7,0,0) (8,8,0,0)…`
  - ⇒ 跳的當天就刪掉 **24 份**真實快照。第 2 天起，`others` 裡有了前一天那份未來日期的快照，告警條件（A:1431）不再成立，**之後都是安靜的**。第 7 天時，真實日期的快照全部消失。
- 為什麼是必修：
  - 本機 30 天的時間點還原能力，在跳的當天縮成 6 天，而且之後沒有任何訊號。
  - 未來日期的快照內容是正確的（現在的庫），所以不是「全毀」。但這一項原本是「高、缺守門」，規格要的「不清理」沒做到。
  - `TSD::test_state_cc07_clock_jump_keeps_newest_and_alerts` 只造了 10 份快照、只跑一天，所以 10→7 看起來像「有保護」，看不出 30→6，也看不出第 2 天之後告警就消失。
- 建議修法：
  - 判定異常（最新的非今天快照早於 cutoff，或日期間有超過保留天數的空洞）⇒ 那一層**這一輪不刪任何東西**，只告警。
  - 異常狀態要持續可見，例如記一個「偵測到時鐘跳動」的標記，直到有人確認；不能靠隔天重新推算。
  - 補多日模擬題（本稽核的模擬即可改寫成題目）。

**A-2　S-CD02「啟動做 quick_check」的守門題是假綠燈**
- 位置：`TSD:83-88`。這題用 `src.index("_startup_integrity_check()", i_init)` 找呼叫，但 main.py:553 的 `def _startup_integrity_check():` 本身就含有這個子字串，所以永遠找得到。
- X 的突變：刪掉 main.py:568 的呼叫 `_startup_integrity_check()`（`def` 保留）⇒ 這題 **1 passed**。
- 為什麼是必修：這是 STATES「高」項的守門，寫著驗「啟動接線」，實際上什麼都沒驗。
- 修法：用 `ast` 找模組層級的 `Expr(Call(Name('_startup_integrity_check')))`，而且位置在 `init_db(DEMO_DB_PATH)` 之後。或者把接線抽成函式，用子行程驗證。

**A-3　IP-6 守門：「欄位分開」驗不出寫反；三支回寫沒有任何題目執行**
- `TCS:148-160` `test_calendar_writeback_case_stage_slots_are_separate`：
  - 假的 Google 對 due 與 done 都回 `"evt-ip6"`，斷言兩欄都等於 `"evt-ip6"` ⇒ 兩欄寫反也驗不出來。
  - X 的突變：Q 的 `_STAGE_EVENT_COLUMNS` 把 due／done 對調 ⇒ `TCS` **9 passed**。
  - 目前會被較早的 `tests/test_case_stage_done_calendar_2026_09_11.py` 抓到（2 紅），所以產品上有保護。但這一題本身證明不了題名說的事。
- `invoice_voucher`／`payment_request`／`shipping_note` 三支回寫（`routers/invoice_vouchers.py:803-820`、`payment_requests.py:889-906`、`shipping_notes.py:761-778`）：
  - `TCS` 只驗它們有登記（`test_calendar_writeback_every_owner_registers_its_writeback`），沒有任何一題執行過它們。
  - `grep -rln "push_event_for_invoice_voucher\|push_event_for_payment_request\|push_event_for_shipping_note" tests` 只找到快照 JSON。
  - X 的突變：三支都改寫成 `"WRONG"` ⇒ `TCS` **9 passed**。
- 為什麼是必修：
  - A11 把這三張表的寫入搬到三支新函式，**搬移之後沒有任何驗證**。INTEGRATION-POINTS IP-6 的「守門」欄只寫了 quotation／case_stage 的正對照，沒有說明另外三個 kind 沒有守門。
  - 回寫失敗的後果是 event id 沒記下來 ⇒ 下一次推送會建出重複的行事曆事件，而且沒有人會發現。
- 修法：
  - 對 5 個 kind 參數化正對照：假的 Google 對每一次呼叫回**不同**的 id，驗證那一張表的那一欄。
  - 另補「回寫期間別人改過單據，不被蓋回」的 lost-update 題（目前只有 quotation 有）。

### 建議

- **B-1　IP-5 的 `notice` 只存在於 API，畫面沒有顯示；取消勾選時訊息也不對**：
  - 前端 `frontend/js/case-management-exec.js:432-441` 的 `updateStage` 只做 `Object.assign(st, await r.json())`，沒有讀 `notice`（勾選入口在 `frontend/pages/case-management.html:848`）。PLAYBOOK §B-4 的要求是「明白告知**使用者**」。
  - X 的補充反向控制：M12 在的時候勾選（建立任務 1），之後 M12 不在時取消勾選 ⇒ 200，但 `notice='未建立每日任務：每日任務模組未安裝'`（取消勾選時這句話不對）。任務 1 仍然是「已完成」，而且 `case_stages.daily_task_id` 還留著 1。再刪除階段 ⇒ 200，任務還在。
  - 目前 M12 還在 `routers/`，拿不掉（STATES P-DT-03），所以沒有實際影響。**M12 搬進 `modules/` 之前必修**：畫面要顯示 `notice`；取消勾選和刪除要各自有一句正確的訊息（例：「未收回每日任務：每日任務模組未安裝」）。
- **B-2　「只補空值」與驗證的判準不一致：鍵存在但值是空字串時，補值會被驗證判成改寫**：
  - `fill_company_profile_blanks` 把 `""` 當成空值並覆寫（CU:549-555）。`_additive_json_change` 只接受「新增的鍵」，要求既有鍵的值完全相同（CU:565-574）。
  - X 的重現：`{"name":"允碩整合集創股份有限公司","tax_id":"","contact_info":""}` ⇒ 補了 `tax_id` 等 4 欄 ⇒ 驗證回 **False**，也就是 `verify_conversion` 會報「既有設定被改寫或刪除：company_profile」，進入回滾。
  - 正式機的統編有值（m106 以此為判斷依據），所以觸發機率低。但兩個判準應該相同。修法：驗證也接受「原值是空字串或只有空白、新值是補值」；補一題。
- **B-3　`contact_info` 是自由文字，拆解會印出錯誤的電話**（CI:115-125，與 CU:519-526 相同）。X 的重現：
  - `'台中市西屯區XX路1號'` ⇒ `phone='台中市西屯區XX路1號'`，單據會印成「Tel: 台中市西屯區XX路1號」；
  - `'info@x.com Tel: 04-1234'` ⇒ `phone=''`，電話不見；
  - `'04-1234-5678, info@x.com'` ⇒ `phone='04-1234-5678,'`。

  這只是最後的後備，但印出來的東西會寄給客戶。建議電話只接受以數字為主的片段（例 `[\d\-\s()+#轉]{6,}`），不符合就留空；補上這幾種案例的測試（兩份拆法要一起改，比對題已經有）。
- **B-4　告警信寄不出去時留下的痕跡沒有速率上限**：
  - `SEND_SKIPPED` 也算失敗（A:546-556）。開發機的 `.no_email_send`，或新客戶還沒設 SMTP ⇒ **每一次** ERROR 告警都會新增一筆 `backup.alert_email_failed` audit，並在 `BACKUP_ALERT.txt` 追加一行，還會重試寄信。
  - 每日備份每 2 小時跑一輪，所以每一種原因每天最多約 12 筆，不會無限增長。但這違反了「告警必須有速率上限」的原則，也會讓開發機的警示檔一直長。
  - 建議：失敗痕跡同原因每日一筆；`SEND_SKIPPED` 要寫明「這台機器設定成不寄信」，和「寄了但失敗」分開。

### 觀察

- **C-1　IP-6 的「對方不在時」在結構上還到不了**：回寫的提供者和觸發推送的呼叫端在同一個模組裡（例：quotation 的推送由 Q 自己觸發）。所以反向控制測的狀態，要等推送搬離擁有模組之後才可能發生。這題不是錯，但它證明的是一個還不存在的情境。真正還存在的相依是 L1 行事曆**直接讀** 5 張 L2 表，INTEGRATION-POINTS IP-6 末段已經寫明。
- **C-2　IP-5「提供者在但失敗」是安靜的**：X 的補充反向控制讓 `upsert` 丟例外 ⇒ 階段存檔 200、`done=True`、`notice=None`、零筆任務，只有 WARNING log。這是既有的 fire-and-forget 設計（CST 的 docstring 寫明），但 INTEGRATION-POINTS 的「對方不在時」只寫了「不在」，沒有寫「在但失敗」。建議補一行。
- **C-3　INTEGRATION-POINTS 與程式的一致性沒有守門**：CORE-SPEC §5 寫「由守門測試驗證與程式碼一致」，但沒有任何測試讀這份文件（`grep -rln INTEGRATION-POINTS tests` 只找到 3 支 docstring）。X 手動核對：程式裡的 8 個 capability（`dispatch.row`、`voucher.draft`、`voucher.account_check`、`accounting.settings`、`voucher.void_draft`、`voucher.status`、`daily_task.external`、`calendar.writeback`）目前都有登記。
- **C-4　A8c 的寫死掃描只看 3 個檔**（`TA8:19-23`）。其餘的在 ROADMAP A8d，但 A8d 的清單漏了：
  - `frontend/pages/users.html:482`、`:486`：placeholder 用本公司的 email 與電話；
  - `frontend/pages/users.html:619`：**畫面上直接顯示預設解鎖密碼 `miac@60575481`**，和 A8d 第一項（高，安全）是同一件事，應該一起列入。
- **C-5**：CU:339 `p.rstrip("\/")` 在 Python 3.13 產生 `SyntaxWarning: invalid escape sequence '\/'`（X 執行時看到）。將來的 Python 會把它變成 SyntaxError，到時升級工具會 import 失敗。這不是這批改的，順帶記下。
- **C-6**：`fill_company_profile_blanks` 判斷「已有值」時不看 `locations[]`，但 company_identity 會先讀據點的欄位。主要據點已有值、頂層是空的時候，升級仍然會在頂層補上 V9 的值。因為據點優先，這不會影響輸出，只是「已有值」的定義和讀取端不一致。
- **C-7**：S-CD02 的啟動 quick_check 是同步的全庫掃描（main.py:568），正式機的庫要花多久沒有量過。建議記錄耗時，並寫進 RUNBOOK「換版後第一次啟動會比較慢」。

## 3. 反向控制與假綠燈檢查（X 實際跑過）

| # | 做了什麼 | 結果 |
|---|---|---|
| R1 | 多日時鐘跳動模擬（臨時題） | 跳的當天 30→6 份真實快照；第 7 天剩 0；告警只有第 1 天 ❌（A-1） |
| R2 | 突變：刪掉 main.py 的 `_startup_integrity_check()` 呼叫 | 守門題 1 passed ❌（A-2） |
| R3 | IP-5：M12 不在時取消勾選、刪除階段；M12 在但 `upsert` 丟例外 | 全部 200，沒有丟例外 ✅；訊息錯誤與殘留（B-1）、失敗時安靜（C-2） |
| R4 | IP-6：拿掉 `case_stage` 的回寫提供者 | 不丟例外、`event_id=''`、WARNING「擁有模組未安裝」 ✅ |
| R5 | 突變：case_stage 的 due／done 欄位對調 | `TCS` 9 passed ❌；舊題 `test_case_stage_done_calendar` 2 failed（產品有保護）（A-3） |
| R6 | 突變：invoice／payment／shipping 回寫寫錯值 | `TCS` 9 passed，沒有其他題目涵蓋 ❌（A-3） |
| R7 | 升級補空值：別家公司／本公司統編有值／本公司統編是空字串 | 不補 ✅／補 3 欄且驗證接受 ✅／補 4 欄但驗證拒絕 ⚠（B-2） |
| R8 | `contact_info` 拆解 5 種寫法 | 3 種拆錯 ⚠（B-3） |
| R9 | 本批相關題目＋對照組；合併基準：`tests/platform` 全部＋STATES／A8c／行事曆／lost-update／保留政策＋§9c e2e | 137 passed；合併基準 **437 passed**（5 分 42 秒，platform `507a76ea`） |

- **假綠燈**：
  - A-2：子字串比對到了自己的定義。
  - A-3：斷言兩邊用同一個假值；「有登記」被當成「有作用」。
  - `TA8::test_upgrade_filled_profile_reproduces_v9_output_byte_for_byte` 的「V9 輸出」是題目裡自己寫的字串常數，驗的是 helper 的字串格式，不是實際的 xlsx／html 輸出。逐位元組的比對只在 commit 訊息裡做過一次。題名寫的比它證明的多，建議改名，或另存 V9 的輸出當基準檔。
  - A-1 的題目只造了 10 份、只跑一天，所以證明不了保留底線在第 2 天之後還成立。
- **回滾路徑**：升級補空值與 `verify_conversion` 的相容性見 B-2（驗證不過會自動進入回滾）。S-CU10 在預檢就擋下，沒有動任何東西（`TSD::test_state_cu10_preflight_blocks_corrupt_db` 綠）。

## 4. 回覆欄（被稽核者填；X 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | X 確認 |
|---|---|---|---|
| A-1 | | | |
| A-2 | | | |
| A-3 | | | |
| B-1 | | | |
| B-2 | 修正（由 X-9b 修正者處理，併 X-9b M-1）：判準改成與 `fill_company_profile_blanks` 相同——原值是空值（None／空字串／只有空白）而新值等於補值 ⇒ 接受；新鍵也必須等於補值；刪鍵、改有值的欄位、補成非補值的值 ⇒ 仍算改寫。轉換後與啟動後共用 `U.settings_changes()`。補題：空字串／只有空白被補 ⇒ 通過；反向控制 4 題 ⇒ 紅。突變（空值不算可補）⇒ 紅 | eda4d3cb | |
| B-3 | | | |
| B-4 | | | |
| C-1 | | | |
| C-2 | | | |
| C-3 | | | |
| C-4 | | | |
| C-5 | | | |
| C-6 | | | |
| C-7 | | | |
