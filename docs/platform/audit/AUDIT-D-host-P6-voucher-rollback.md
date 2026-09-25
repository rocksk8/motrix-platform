# 稽核：主持的 P6 事件匯流排、傳票第二筆金額連動、完整回滾預覽（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。
> 對象：`8d19378c`（P6 `core.events`，規格 CUSTOMIZATION-SPEC §6）、`c2913a80`（傳票同一行換支出項時金額跟著換）、`4fb1c7be`（儀表板：完整回滾前必須先預覽）。
> 稽核基準 origin/platform `09f8fc70`，稽核樹 `D:\MOTRIX-PLATFORM-D`（detached），Python `D:\MOTRIX-PLATFORM\.venv312`（只用、未改）。
> 分級：**必修**／**建議**／**觀察**。關閉規則：被稽核者回覆後，由 D 確認才關。
> 縮寫：`EV`＝`backend/core/events.py`、`VJ`＝`frontend/js/voucher.js`、`DD`＝`backend/tools/deploy_dashboard.py`、`RP`＝`backend/tools/_dashboard_remote.ps1`。

## 0. 結論

- 三項的主要行為都做到了，各有題目。D 自做突變 8 項：**7 紅、1 存活**。
  - 完整回滾預覽：無預覽、預覽過期、預覽帶 `--yes` 三種突變都紅；`upgrade.py` 讀碼確認預覽不會真的執行回滾。
  - 傳票：「不換金額」「蓋掉手改的金額」兩種突變在 e2e 都紅，轉紅的原因正確（金額停在 5000，應為 800）。
- **必修 1 項**：
  - H-M1：P6 的「給副本」只複製最上層（`dict(payload)`）。巢狀的清單或 dict，第一個訂閱者改了，下一個訂閱者與發佈方都會看到。規格明寫「訂閱者改 payload 不影響下一個訂閱者」，測試只用了平的 payload（屬於「證明的是另一件事」）。
- 建議 4 項、觀察 3 項。
- 基準：`test_core_events` 9 passed、`test_deploy_dashboard_upgrade` 20 passed、傳票 e2e `test_second_expense_on_the_same_line_brings_its_own_amount` 1 passed（單程序、低優先權）。

## 1. 逐項驗收

### P6（CUSTOMIZATION-SPEC §6）

| 規則 | 驗收 | 證據 |
|---|---|---|
| 宣告即契約；同名不同契約報錯 | ✅ | EV:43-51；`test_conflicting_declarations_are_refused` |
| 發佈在 commit 之後 | ⚠ 無法驗 | 產品碼目前**沒有任何** `publish`／`subscribe`／`declare` 的呼叫（D grep `backend/` 扣掉 EV 與它的測試：0 筆）⇒ 這條規則還沒有任何呼叫端可以驗，也沒有守門（H-O1） |
| 訂閱：模組沒載入就沒有訂閱 | ✅（依賴「停用要重啟」） | `helpers/module_switches.py:3`「重啟後生效」 |
| 隔離：訂閱者失敗不影響發佈方、其他訂閱者；記最近失敗 | ✅ 例外 ／ ❌ 時間 | EV:97-107；但訂閱者是**同步**執行，一個慢的訂閱者會直接拖住發佈方的回應（D 實測：訂閱者 sleep 2 秒 ⇒ `publish` 耗時 2.0 秒）（H-S2） |
| 給副本：訂閱者改 payload 不影響下一個 | ❌ 巢狀 | EV:99 `dict(payload)` 是淺拷貝（H-M1） |
| 契約檢查：預設記 ERROR 照送、嚴格模式 raise | ✅ | EV:87-95 |
| 「最近失敗」供管理頁顯示 | ⚠ | 函式有；沒有任何端點或頁面讀它（H-O1） |

### 傳票（c2913a80）

| 規則（commit 說明＋使用者裁示） | 驗收 | 證據 |
|---|---|---|
| 同一行換成另一筆支出 ⇒ 金額跟著換 | ✅ | VJ:263-271；e2e `test_second_expense_on_the_same_line_brings_its_own_amount` |
| 手改過的金額保留（N12） | ✅ | 同一題後半段 |
| 新的一筆沒有金額 ⇒ 不留上一筆 | ⚠ 沒有題目 | VJ:269；突變 H08 見 §2 |
| `_autoDebit` 不送後端 | ✅（證據範圍見 H-O3） | |
| 從支出換成「案件」 | ❌ | 見 H-S3 |

### 完整回滾預覽（4fb1c7be）

| 規則 | 驗收 | 證據 |
|---|---|---|
| 沒預覽、預覽失敗、預覽早於轉換 ⇒ 409 | ✅ | DD:1395-1401；`test_rollback_full_needs_a_preview_after_the_latest_convert` |
| 預覽是唯讀的 | ✅ | `tools/platform/upgrade.py:238-244`：`--mode full` 沒有 `--yes` 時，**無條件**先列清單、return 4，不會走到 `rollback_and_ping`（D 讀碼確認：沒有「沒有變更就直接執行」的分支） |
| exit 4 視為成功 | ✅（只驗文字，見 H-O2） | RP:365-366 |
| 逾時 10 分鐘、可以直接中止 | ✅ | DD:495 |

## 2. 反向控制與突變

| 突變 | 結果 | 轉紅的題 |
|---|---|---|
| H01 `handler(payload)`（拿掉副本） | 🔴 紅 | `test_subscribers_run_in_order_and_get_a_copy` |
| H02 只接 ZeroDivisionError（拿掉隔離） | 🔴 紅 | `test_failing_subscriber_is_isolated_and_recorded` |
| H03 完整回滾不檢查預覽 | 🔴 紅 | `test_rollback_full_needs_a_preview_after_the_latest_convert` |
| H04 不檢查預覽是否早於轉換 | 🔴 紅 | 同上 |
| H05 預覽帶 `--yes` | 🔴 紅 | `test_preview_is_readonly_and_treats_exit4_as_success` |
| H06 傳票：換支出項不換金額（`autoUntouched=false`） | 🔴 紅 | e2e：`debit '5000' == '800'` 失敗 |
| H07 傳票：手改過的也換（不比對 `_autoDebit`） | 🔴 紅 | e2e 後半段（手改 4321 被蓋掉） |
| H08 傳票：新的一筆沒有金額時留著上一筆 | 🟢 **存活** | —（H-S4） |

探針（直接呼叫 `core.events`，不寫檔）：
- 巢狀 payload `{"items": ["原本"]}`：第一個訂閱者 `append` ⇒ 第二個訂閱者看到 `['原本', '被第一個訂閱者加的']`，**發佈方的物件也被改了** ⇒ H-M1。
- 訂閱者 `sleep(2)` ⇒ `publish` 耗時 2.0 秒 ⇒ H-S2。

## 3. 發現

### 必修

**H-M1　P6「給副本」是淺拷貝：巢狀資料會被訂閱者改掉**
- 位置：EV:99 `handler(dict(payload or {}))`。
- 規格：CUSTOMIZATION-SPEC §6「隔離」一列＋EV:99 的註解「給副本：訂閱者改 payload 不影響下一個訂閱者」。
- 為什麼是必修：事件的典型 payload 會帶明細（報價的品項、獎金的成員名單）。一個訂閱者整理或補欄位時，會悄悄改掉後面訂閱者、**以及發佈方自己**手上的資料。發佈方是在 commit 之後才發佈，但如果它接著把同一個物件拿去回應或寫紀錄，就會帶著別人改過的內容。而 `test_subscribers_run_in_order_and_get_a_copy` 只用 `{"id": 7}`，綠燈證明的是「最上層的鍵不互相影響」。
- 重現：見 §2 探針。
- 建議修法：`copy.deepcopy(payload)`；或者宣告時規定 payload 只能放 JSON 可序列化的值，發佈時 `json.loads(json.dumps(payload))`，同時守住「可以序列化」這條契約，之後跨行程也用得上。補一題巢狀反向控制。

### 建議

- **H-S1　「發佈在 commit 之後」沒有守門，也還沒有任何呼叫端**：產品碼 0 筆 `publish`／`subscribe`／`declare`（D grep）。第一個呼叫端出現時，才會知道這條規則有沒有被遵守。建議在 `publish` 內檢查：呼叫當下如果還有同一條執行緒開著的 `core.txn` 寫交易（`_WRITE_TXNS`），嚴格模式就 raise、產品記 ERROR。這與「契約檢查」同一套旗標。
- **H-S2　訂閱者同步執行：慢的訂閱者會拖住發佈方**：規格「不影響發佈方」目前只對例外成立，對時間不成立（探針 2.0 秒）。訂閱者如果寄信、呼叫外部 API，發佈方的 HTTP 回應就會跟著慢。建議規格寫明「訂閱者必須在 N ms 內返回，慢工作自己丟背景」；或者由匯流排提供 `subscribe(..., background=True)`。
- **H-S3　同一行從自動帶入的支出換成「案件」時，金額留著**：VJ:263 只在 `source_type !== 'case'` 時處理借方。一行原本自動帶入支出 5,000，改點案件之後，摘要變成案件，借方仍是 5,000（`_autoDebit` 也還在）。這就是這次使用者回報的「摘要與金額對不上」，只是發生在另一個方向。D 依讀碼判定，未跑 e2e。建議：換成案件時，如果借方是未手改的自動值，就清空，並補一題。
- **H-S4　「新的一筆沒有金額 ⇒ 不留上一筆」沒有題目（突變 H08 存活）**：VJ:269。建議在 e2e 補一筆金額為 0 或空白的支出。

### 觀察

- **H-O1　`recent_failures()` 沒有端點或頁面讀它**：規格寫「供管理頁顯示」。目前失敗只存在行程記憶體裡，重啟就消失，也沒有人看得到。等 P1 能力目錄或模組管理頁接上。
- **H-O2　「exit 4 視為成功」只驗了腳本的文字**：`test_preview_is_readonly_and_treats_exit4_as_success` 用正規表示式比對 ps1 原始碼，沒有跑到 PowerShell。屬於結構題，可以接受，但它證明的是「這行字在」，不是「儀表板把預覽記成 ok」。另外，預覽之後、按下完整回滾之前，服務如果已經啟動，而且有人寫入資料，這些資料不會出現在預覽清單裡，回滾時卻會一起消失。預覽只要求「在最近一次轉換之後」，沒有要求「足夠新」。建議在確認對話框顯示預覽時間，或要求服務在停止狀態。
- **H-O3　`_autoDebit` 不送後端的證據範圍**：e2e 斷言存檔之後的行沒有 `_autoDebit`。但後端只把固定欄位逐欄寫進分錄表（`routers/vouchers.py:340-347`、`:1358-1362`），多出來的鍵本來就不會存下來，所以即使前端送了，這個斷言照樣綠。它證明的是「後端沒存」，不是「前端沒送」。產品結果正確，只是標註證據的範圍。另外，`4fb1c7be` 的作者 email 是 `t@t`，與其他 commit 不同，建議確認 git 設定。

## 4. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆 | commit | D 確認 |
|---|---|---|---|
| H-M1 | 修正。副本改成 JSON 來回（每個訂閱者拿到完整獨立的副本，發佈方的物件也不會被改），同時守住「payload 只能放 JSON 可序列化的值」的契約（違反時測試 raise、產品記 ERROR）。新增巢狀反向控制：第一個訂閱者改巢狀清單 ⇒ 第二個訂閱者與發佈方都看不到。突變：改回 `dict(payload)` ⇒ 紅 | 本分支 | ✅ 2026-09-26 01:57 關閉。基準 origin `9450ea4a`（修正 `f4e7db63`），相關 3 檔 42 passed。D 突變 R01（改回 `dict(payload)`）⇒ `test_nested_payload_…` 紅。附帶見 N-2（型別被改寫） |
| H-S1 | 修正。`publish` 檢查同一條執行緒是否還開著 `core.txn.begin_write` 的寫交易（`begin_write` 多記一個 thread id，沒有新增公開介面），有的話就違反契約。補兩題：交易內 ⇒ raise、commit 後 ⇒ 照送；另一條執行緒的交易不影響（反向控制）。突變：拿掉檢查 ⇒ 紅；不比對執行緒 ⇒ 3 紅 | 本分支 | ✅ 2026-09-26 01:57 關閉。D 突變 R02（拿掉檢查）⇒ 紅 1；R03（不比對執行緒）⇒ 紅 3。範圍見 N-3 |
| H-S2 | 部分採納。規格寫明「訂閱者必須很快返回，慢工作自己丟背景」；超過 0.2 秒記 WARNING（附訂閱者名稱與秒數），並補題。**不做** `background=True`：背景執行會把「隔離與失敗紀錄」的語意分成兩套，等第一個真正需要背景的訂閱者出現再設計 | 本分支 | ✅ 2026-09-26 01:57 接受部分採納。理由成立（背景執行會分裂隔離與失敗紀錄的語意）；WARNING 已寫進規格並有題目，D 突變 R04（拿掉警告）⇒ 紅 |
| H-S3 | 修正。換成「案件」時，借方如果是沒被手改過的自動值就清空；手改過的照舊不動。新增 e2e | 本分支 | ✅ 2026-09-26 01:57 關閉。新 e2e `test_auto_amount_does_not_linger_…`；D 突變 R05（換成案件不清）⇒ 紅。⚠ 回覆寫「手改過的照舊不動」，但沒有題目：D 突變 R07（換成案件時連手改的也清）存活 ⇒ N-4 |
| H-S4 | 補題。同一支 e2e 補「換成沒有金額的支出 ⇒ 不留上一筆的金額」。突變：H-S3、H-S4 的分支各改成 false ⇒ 各自轉紅 | 本分支 | ✅ 2026-09-26 01:57 關閉。D 突變 R06（原 H08，沒有金額時留著舊值）⇒ 這次轉紅 |
| H-O1～O3 | O1：同意，排在 P1 能力目錄合回之後，由模組管理頁顯示 `recent_failures()`。O2：確認畫面加上預覽時間與「預覽之後若服務曾經寫入資料，回滾時也會消失」的提示（`data-testid=up-preview-age`）。O3：證據範圍的標註同意；作者 email 是 `t@t` 的原因已查到：共用 repo 的 .git/config 在 09-25 23:00～23:09 被加了本機的 `user.email=t@t`，那段期間所有人的 commit 都受影響。已經移除（全域設定 rockskt9@gmail.com 恢復生效），推上去的 commit 不改寫歷史 | 本分支 | ✅ 2026-09-26 01:57 接受。O1 排在 P1 之後；O2 畫面已加預覽時間與提示（`deploy_dashboard.html`，沒有題目，屬觀察層級，不要求）；O3 的 `t@t` 成因已查明並移除 |

### D 確認時的新發現（2026-09-26 01:57；不擋上面的關閉）

- **N-1（建議）L1 行為改變沒有寫 `backend/core/CHANGELOG.md`**：`f4e7db63` 改了 `core.events` 的行為（副本改成 JSON 來回、交易內發佈算違約、慢訂閱者記 WARNING），以及 `core.txn.begin_write` 的內部狀態（多記一個 thread id）。介面不變，但依 CORE-SPEC §9d，L1 行為改變要記在 CHANGELOG（例如 1.8 那一節「修改行為，介面不變」的寫法）。目前 CHANGELOG 只有 P6 當初新增的那一條。
- **N-2（觀察）JSON 來回會靜默改寫型別**：`{1: 'a'}` 變成 `{'1': 'a'}`，tuple 變成 list，而且不報任何契約違反（D 實測）。這些值 `json.dumps` 得過，所以不算違約，但訂閱者拿到的鍵型別和發佈方不同。建議在規格 §6 寫明「payload 的鍵一律是字串、序列一律是 list」，或者在契約檢查時要求 `json.loads(json.dumps(p)) == p`。
- **N-3（觀察）交易內發佈的檢查只認得 `begin_write` 開的交易**：直接 `conn.execute(INSERT…)` 由 sqlite 隱式開交易、之後才 `commit()` 的路徑（很多 router 是這樣寫的），在 commit 前發佈不會被抓到。等第一個呼叫端出現時，一併決定要不要讓 `publish` 接受 `conn` 參數來檢查 `conn.in_transaction`。
- **N-4（建議）「換成案件時，手改過的金額保留」沒有題目**：D 突變 R07（條件改成只看 `source_type === 'case'`）⇒ 2 passed。建議在 e2e 補一段：手改金額之後換成案件 ⇒ 金額還在。
