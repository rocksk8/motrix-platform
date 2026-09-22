# 視窗 B — 寫手（只有 B 寫這一份）

> 開工順序：`MULTIWIN-PROTOCOL.md` → `docs/windows/STATE.md` → 這份。
> **你的角色：寫產品程式碼。你不寫任何測試。**

---

## 你能動的

- `backend/**`（**不含** `backend/tests/`）
- `frontend/**`

## 你不能動的

- `backend/tests/**` ← 那是 C 的
- 根目錄 `*.md`、`docs/**` ← 那是 A 的（**除了這一份**）

## 動之前要先在下面〈宣告〉段寫一行、等 A 回覆的鎖定檔

`backend/db.py` · `backend/main.py` · `frontend/static/sidebar.js` · `backend/helpers/__init__.py`

---

## 宣告（要動鎖定檔就寫在這）

| 時間 | 要動哪個鎖定檔 | 為什麼 | A 回覆 |
|------|--------------|--------|--------|
| 2026-09-21 | `backend/main.py` | 掛 `licensing.router` | ✅ **准**（STATE §5 回覆 B 第 1 項）。已動，只有兩行：第 25 行 import 末端加 `, licensing`、第 484 行 `app.include_router(licensing.router)`。**middleware 一個字沒碰。** |
| 2026-09-21 | `backend/helpers/__init__.py` | 條件性 re-export | ✅ **准但預設不動**（STATE §5 第 2 項）。**最後沒有動** —— C 的測試用 `from helpers import licensing as lic`，`helpers/__init__.py` 不需要改。 |
| 2026-09-21<br>第 2 輪 | `backend/main.py` | 掛授權守門 middleware。位置在 `auth_middleware` **之後**（先確認是誰，再確認這台機器有沒有買）。⚠️ **總開關做完並驗過之後才動這個檔** | ✅ **准**（STATE §5 第三次回覆）。已動，**只新增 53 行、無刪除** |
| 2026-09-21<br>第 3 輪 | **`backend/db.py`** | 加前置時間欄位與採購建議狀態。**migration 編號 `_m085_procurement_lead_time`**（目前 `CURRENT_VERSION = 84`，最後一支是 `_m084_backfill_role_bypass_modules`）。一支 migration 做三件事：①`suppliers` 加 `lead_time_days INTEGER`（預設 NULL）②`parts` 加同名欄位 ③新建 `purchase_suggestion_status` 表。⚠️ 協定 §3 明寫兩人同時加 migration 會產生兩個 `_m085_`、merge 不衝突、只在執行時撞版本號——**編號在宣告裡講死** | ✅ **准**（A 另查證 `_m085` 零命中、無人在改 `db.py`）。已動 |
| 2026-09-21<br>第 4 輪 | **`backend/db.py`** | 標案雷達四張表。**migration `_m086_tender_radar`**（`CURRENT_VERSION` 85→86）。A 已在 §3 交付物指派並說「開工吧…四張表」 | ✅ **准**（§3 交付物）。已動，實跑確認 `DB migration 86/86` |
| 2026-09-21<br>第 4 輪 | **`backend/main.py`** | 掛 `tender_radar.router`。只動 2 行 | ✅ **准**（§3 交付物列了 router） | 
| 2026-09-21<br>第 4 輪 | **`frontend/static/sidebar.js`** | ⚠️ **等 A 回覆，尚未動。** `tender-radar.html` 沒有側欄入口就只能手打網址。需要三處：`cTender = has('dev_crm')` 一類的旗標、`'tender-radar.html': 'dev_crm'` 的頁面→模組對應、`ni(pg('tender-radar.html'), …)` 的選單項。**A 沒有把 `sidebar.js` 列進 §3 交付物**，所以我停手 | ✅ **准**（`47add8e`，A 承認漏列）。已動，並依裁決**新建 key `tender_radar`** 而不是沿用 `dev_crm` |

---

## 本輪狀態

- **輪次**：**第 2 輪**（細線 1 第 3 步：擋住）
- **第 1 輪**：✅ A 端驗收通過，程式碼 `2dadfb6`、視窗紀錄 `649f07f`
- **第 1 輪全量回歸**（我跑的，非 C 的⑥）：**1,055 過／55 skip／1 紅**，合計 1,111，數字對得上
  - 紅的是 `test_pdf_concurrency_2026_09_07.py::test_semaphore_caps_concurrent_holders`
  - **單獨重跑是綠的**；該測試只碰 `EDGE_PDF_SEMAPHORE` 與執行緒，與授權零交集
  - 當下**機器上有三個 pytest 同時在跑**（另兩個不是我的），該測試的第二個斷言
    `peak == max_concurrency`（「應該至少有一批真的頂到上限」）在 CPU 被搶時會頂不到
  - ⚠️ **我無法百分之百證明是哪一行紅的**：我把輸出接了 `tail -25`，traceback 被截掉了。
    這是我的失誤，下次全量回歸不接 `tail`。C 的⑥要在機器安靜時重跑一次才算數
- **輪次**：**第 5 輪**（細線 6 第 2 步排程 ＋ 第 5 步通知）
- **狀態**：🛑 **第 5 輪停手（第三次宣告）。SHA = `0d91e8c`**（最後一個動 `backend/`／`frontend/` 的 commit）
- **N15／N16／N17／N17b 完成**（`0d91e8c`）：tender 兩支測試檔 **81 題全綠**（先前 17 綠 12 紅）
  🔴 **N15 抓到我一個設計缺陷，而且「不標記」那一半我本來是對的**：
  通知原本以「這一輪 `INSERT` 進去的標案」為鍵。投遞失敗之後再跑一次，
  `INSERT OR IGNORE` 判定那些標案**已經存在** ⇒ 新增 0 筆 ⇒ **一封都不會寄**，
  那批標案就此消失。
  🔑 **「不要記錄失敗」與「要記得重試」是兩件事，前者做對不代表後者會發生。**
  改成以「**還沒通知過的命中**」為鍵。
- **舊宣告**：`bbbbc28`（第一次）／`a45f3d9`（第二次）
- **N14／N14b 已完成**（`a45f3d9`）。tender 兩支測試檔 **75 題全綠**
  ⚠️ 順手修掉一個我自己的邊界錯誤：原本 `delta < 7` 把**第 0 天（首掃當天）**
  也算進靜默期，於是**那封樣本信永遠寄不出去**——而它正是純記錄期存在的理由。
  改成靜默第 1～7 天、第 8 天恢復。
  ⚠️ **N14b 沒有測試在守。** 我自己跑了三天的對照：
  第 0 天 1 封含該句／第 3 天 0 封／第 8 天 1 封**不含**該句。
  最後那個「不含」是 N14b 的全部內容，而**它現在只靠我這段一次性驗證**——
  建議 C 補一題（第 8 天那封不可以含「接下來 7 天」）。
- **舊宣告**：`bbbbc28`（第 5 輪第一次）
  C 可以跑⑤⑥。之後我只動 `docs/windows/B.md`。
  自查（協定 §4 的(甲)，**排除 `backend/tests`**——那是 C 的地盤）：
  `git log bbbbc28..HEAD -- backend frontend ':!backend/tests'` → 空。
  ⚠️ 取 SHA 用 `git log --format='%h %s' -1 -- backend frontend ':!backend/tests'`，
  **不用會截斷的指令**（C 今天因為 `... | tail -3` 回報過三個不存在的 SHA：
  SHA 在第一行，多檔 commit 就被 `tail` 砍掉。**截斷不會報錯，它只是安靜地少給一行，
  而那一行正好是你要的**）。
- **產品碼**：`bbbbc28`。**82 綠 3 紅，三紅全部在 C 的檔**
- **測試結果**（`test_tender_match` ＋ `test_tender_notify` ＋ prefs coverage ＋ module 一致性）：
  ```
  82 passed, 3 failed
  FAILED test_n7_quiet_period_sends_nothing        ← C 的 helper SQL 錯欄位
  FAILED test_n8_day_eight_sends                   ← 同上
  FAILED test_n10_no_enabled_recipient_means_no_send ← 與 N1/N3/N5/N6/N9/N11 互斥
  ```
- **R1 已完成**：解析 dict 鍵 `published` → `published_at`，`test_06e` 轉綠
- **動的鎖定檔**：`db.py`（`_m087_tender_notify`，86→87）、`main.py`（排程閘門加一行）

- **A 已驗過停手握手**（不是相信我，是跑 `git log a18adf9..HEAD -- backend frontend` 查空）。
  ⚠️ **握手判準看 `MULTIWIN-PROTOCOL.md` §4 的那張表，不要看這裡。**
  這一行原本抄了判準的**內容**（「`<宣告SHA>..HEAD` 對 `backend`／`frontend` 是空的」），
  而那份副本**已經過期了**——協定後來把它拆成兩個檢查，
  **(甲) 驗「B 真的停了」要排除 `backend/tests`**（C 在那個空檔補測試是正常的），
  **(乙) 驗「跑的期間沒人動」不排除任何東西**（測試本身也是受測對象）。
  🔑 **我因為手上這份副本，花了一輪去「發現」一個兩小時前就修好的洞。**
  ⇒ 教訓：**引用規則要給位置，不要抄內容**——抄進來的那一刻就產生了一份會過期的副本，
  而它不會自己作廢，還會被當成現行規則用。**我把它抄進了交接文件，所以下一棒也會中。**
- 🔴 **⑥ 跑出 1 紅，而且是我第二次撞同一道守門。**
  `test_every_table_is_either_backed_up_or_explicitly_excluded`——四張新表沒登記備份。
  ⚠️ **第 3 輪我已經撞過一次**（`purchase_suggestion_status`，`9c2e70c`），
  當時還把它寫進這份檔當教訓。**第 4 輪加四張表時我一次都沒想起來。**
  ⇒ 誠實的結論：**「新增資料表要決定備份歸屬」這件事，我到現在都是被守門提醒的，
  不是自己記得的。** 寫進視窗檔沒有讓我下次想起來——**紀錄防的是下一個人，不是我自己。**
  ⇒ 真正有效的是那道守門，而它之所以抓得到，是因為它驗的是「**每一張表都要有人做過決定**」
  而不是「某幾張表有沒有被備份」。
  ✅ 已補（`8a3612d`）：`tender_watches`／`tenders`／`tender_hits` 三張，全部 `SELECT *`。
  `tender_fetch_log` 的排除那一筆在 `backend/tests/`，是 C 的檔，**我沒有動**。
  ⚠️ 所以驗收 1 現在仍是紅的，那是**設計好的交接**，不是沒做完。
- **C 的⑤已完成：六個突變全部發火。** ⑥跑中（約 20 分鐘），由 C 回報。
- 📌 **C 查出一件關於我自己程式碼的事實，值得記著**：`_parse_row` 的形狀驗證
  **不是一道檢查，是三道**（機關含中文／機關不可像日期／截止日非空要解得出），
  C 試了四版才繞得過。**它比我自己以為的厚。**
  ⇒ 這件事的用處在未來：**下一個人看到那三行會想「這不是重複嗎」而合併掉其中兩道**，
  而合併之後反向驗證第 5 題仍然會紅（還剩一道），**看起來完全正常**。
  三道各自擋的是不同的欄序錯位組合，不是同一件事講三遍。

### 📌 使用者 2026-09-21 的三項裁示（影響我下一輪，現在不要動）

| | 裁示 | 對我的影響 |
|---|---|---|
| 正式私鑰保管 | **密碼管理器加密保存**（A 建議離線 USB，被否決） | 保管方式定案 ≠ 金鑰已產生。`_PUBKEY_PROD` 仍是空的 |
| **第 5 輪之後** | 🔴 **做完細線 6 第 6、7 步**：有興趣／不相關標記 ＋ **一鍵轉 `dev_case`** | **這是我的下一輪** |
| 授權 middleware 欠帳 | 設成**程式強制的解凍前置**，不現在補測試 | 排在細線 6 收尾之後、細線 4 之前 |

**細線順序更新**：6（做完七步）→ 4 成本閉環 → 5 售後閉環 → 7 商圈雷達。

📌 那支守門的形狀：`LICENSE_GATE_ENABLED` 改 `True` 而
`test_licensing_gate_2026_09_21.py` 不存在 ⇒ CI 失敗。
⚠️ 這是「**讓欠帳在被動用的那一刻才擋住**」的做法，不是「現在補完」——
值得記著，因為它把一個會被遺忘的待辦，變成一個**只有在真的要用時才付代價**的閘門。

### 🟢 N14b：我對 A 的新條件補的一個細節（已被採用）

N14 要求第 1 天那封信寫明「接下來 7 天是純記錄模式」。
我補的是：**那句話只能出現在「純記錄期開始」的那一封**。
每封都寫的話，第 8 天恢復之後的信也會說「接下來 7 天不會再寄信」——**而那是錯的**，
收件人會第二次以為壞掉了。
⇒ 判斷條件是「**這一封寄出去之後就要進入靜默**」，不是「現在在靜默期」
（在靜默期裡根本不寄信，後者永遠不會觸發）。
🔑 A 的總結比我準：**一個防止誤會的訊息，貼錯位置會製造它原本要防的那個誤會。**

### 🔴 N15／N16（等 C 的紅燈，**我沒有動手**）

A 追端到端鏈時發現：`_async_send` 是**射後不理**，而 `_send` 裡有**五個安靜的 return**
（功能未啟用／非正式機被擋／收件人空／SMTP 未設定／SMTP 例外），一個都傳不回來
⇒ `_mark_hits_notified()` 照樣執行 ⇒ **標案被標記已通知而信根本沒出去**。
⚠️ 最可能的觸發是「SMTP 還沒設定」——**使用者第一次啟用的那一天**。

**我補的那一半（A 採用，範圍因此擴到三支）**：
`notify_tender_fetch_failed` 走同一條路，而它的後果更嚴重——
`run_scan` 已經寫了 `recognised=NULL`，信沒出去但**邊緣被消耗掉**，
隔天 `previous["failed"]` 是 True 就不再寄。
⇒ **雷達從此瞎著，而沒有任何人會知道**，因為邊緣觸發保證了它不會再試。
🔑 **N15 是漏掉幾筆標案；這個是漏掉「雷達壞了」這件事本身。**

**我沒有照裁決直接動手，先實測**：把 `notify_tender_found` 改成 `_send_raising`
→ **6 failed, 20 passed**（C 的 `_sent` 攔的是 `_async_send`，而 `_send_raising`
是獨立同步實作、不經過它）。還原用**原始位元組比對**（sha256 相同），不用 `git checkout`。
⇒ 順序改成 **C 先我後**：C 把 `_sent` 統一攔 `_send_raising`、加 N15／N16 紅燈。

### 📌 兩條規則（A 從自己的疏漏抽出來，對我一樣適用）

1. **找到共用元件的缺陷時，要列出它所有的呼叫端，不是只看你走進來的那一個。**
   A 只追了有「標記已通知」的那一支——**那個動作把注意力吸過去了**。
2. **對另一個視窗狀態的觀察，是一份有時間戳的副本。**
   我的「N14b 無測試」在當下是對的，C 在 **62 秒後**才 commit 進去。
   ⇒ 不是「先去看它的檔案」（我看了），是**「要嘛當場重看一次，要嘛寫明『截至我讀的時候』」**。
   ⚠️ 同一家族的第三種載體：過期的規則副本、被截斷的 SHA、現在是對他人狀態的觀察。

### 🔴 第 5 輪：三紅的診斷（都在 C 的檔，我不動）

**① N7／N8 —— C 的 helper 用了不存在的欄位**

```
tests/test_tender_notify_2026_09_21.py:436
    INSERT OR REPLACE INTO system_settings (key, value) VALUES (?,?)
sqlite3.OperationalError: table system_settings has no column named value
```
實際欄位是 `key` / **`value_json`** / `updated_at`（`db.py`）。

⚠️ **而且改對欄位名還不夠**，我實測了第二層：`helpers/settings.py::_get_setting`
對值做 `json.loads`，所以寫進去的必須是 **JSON**。裸字串 `2026-09-21T09:00:00`
會讓 `json.loads` 丟例外 → `_get_setting` 記一筆 warning 並回 default。
⇒ 正確寫法是 `json.dumps("2026-09-21T09:00:00")`，或直接用 `_set_setting`。

**② N10 與 N1／N3／N5／N6／N9／N11 互斥——只能滿足一邊**

N10 把 `notify_tender_found` **整支換成計數器**，所以函式內部的收件人早退救不了它：
要讓它 0 次，**呼叫端必須先檢查有沒有收件人**。
但 `conftest` 的每測試資料庫只跑 `init_demo_account()`、**沒有任何有 email 的 admin**
（`init_default_admin` 不在 `client` fixture 裡）⇒ 加了閘門之後那六題全部變成 0 封。

我實測過兩種都做一次：
```
加閘門   → N10 綠，N1/N3/N5/N6/N9/N11 紅（6 紅）
不加閘門 → 那六題綠，N10 紅（1 紅）
```
**我選不加**，理由是既有 44 支 `notify_*` 一致的做法就是「自己解析收件人」
（`to = _admin_emails(key); if not to: return`），而守門
`test_notification_prefs_coverage.py` 掃的正是那個呼叫點。⇒ 行為是對的，
只是**在 C 選的觀測點上看不到**。

⚠️ **N10 的 patch 目標對既有結構也不成立**：它換掉 `notification_prefs.is_enabled`，
但 `email_notify.py:14` 是 `from .notification_prefs import is_enabled as _pref_enabled`
——**一份副本**，patch 打不到。
⇒ 建議 N10 改成：spy `email_notify._async_send`（真正投遞那一步）＋
patch `email_notify._pref_enabled`。那樣不必加閘門、其餘六題也不受影響。

### ⚠️ 第 5 輪審單：我有一項判斷是錯的，而且錯在方法

我向 A 提報「`daily_tasks._daily_run()` 的 13 個檢查沒包 try，第 1 個丟例外就整支排程死掉」。
**錯的。** A 要我進去看函式本身，我自己複驗了：

```
11/12 支檢查各自有頂層 try/except
第 12 支 _check_project_deadline 是 `pass` 空殼（2026-08-26 停用）
⇒ _daily_run() 丟不出例外，那支排程現在是安全的
```

**我查了呼叫端（沒有 try，屬實），沒查被呼叫的函式。**
一個真的觀察 ＋ 一個沒查的推論 ＝ 一個聽起來很具體的錯誤結論——**而具體讓它更可信**。

✅ **但 `archive._schedule_daily` 那一半是對的**：`_snapshot_sqlite()` 與
`_rotate_server_log_if_large()` 確實在 `_daily_backup()` 自己的 try 之外。
A 另外查了正式機備份資料夾（09-17～09-21 連續）⇒ **那是「一次丟例外就會靜默死亡」的潛在陷阱，
不是「已經死了」。** 我的描述把潛在講成了實況。

⚠️ **我的第二項主張也錯了具體、對了原則**：我說「看門狗住在它看守的排程裡」——
實際上 `_check_backup_freshness` 在 `daily_tasks._loop` 的 Timer 裡，
看的是 `archive._schedule_daily` 排的備份，**兩條獨立的 Timer 鏈**，archive 死掉它仍會叫。
但往上一層成立：**沒有人看 `daily_tasks._loop` 自己**，鏈條在那裡斷掉。
（`heartbeat_job.py` 是獨立行程、不 import app，但它只 ping `/api/ping`，不看排程——我查過。）

🔑 A 指出我跟 C 從兩個方向撞到同一個結構：
C 從測試涵蓋看「每一輪往上挪一層，**最上面那一層永遠沒有人驗**」；
我從執行期看「**看門狗不可以跟被看的東西共用同一個死法**」。
**防護鏈一定有最外面那一圈，而那一圈的看守者是「人剛好注意到」。**

### 📌 第 5 輪首項（A 已排定，現在**不要動**）

`published` → `published_at`：**解析 dict 的鍵**改名，與 C 的 `test_06e` **同一輪一起改**
（我單獨改會讓那題紅）。

A 清點的實況是**三種拼法橫跨三層**：
解析 dict `published`（`tender_source.py:244,381`）／DB 欄 `published_at`／API 與前端 `publishedAt`。
**API 那一層的不同是有意義的**（跨邊界，`leadTimeDays` 那次定案過）；
**解析 dict 那一層沒有**——它跟 DB insert 在相鄰兩行，中間沒有轉換層。

⚠️ **A 不現在改的理由值得抄下來**：不是它不重要，是**可出貨**。
它使用者看不到、API 看不到、DB 看不到，影響是 0；而現在改要解除停手、重新宣告、
讓 C 再等一輪——**把一個為了讓⑥有意義而設的握手，花在一件對⑥沒有影響的事上**。
🔑 **握手是用來保護驗證的，不是用來保護整潔的。**
- **第 3 輪 commit**：`4edf210` 實作 → `6613224` A 的兩項裁決 → `9c2e70c` 備份登記修補
- **自我驗證**：29/29（scratchpad 腳本，不進 repo、沒碰 `backend/tests/`）
- **全量回歸（`-full`，驗 `9c2e70c`）**：

  ```
  1056 passed, 55 skipped, 22 warnings in 1040.66s (0:17:20)
  ```

  **零 FAILED**，1056 ＋ 55 ＝ **1,111**，與基準相同。
  題數沒有增加是**對的**：這一輪我沒有寫任何測試（C 還沒寫第 3 輪的），
  新增的是一張表與兩個欄位，不是新的題目。

  ⚠️ **前一支（驗 `4edf210`）是 1 failed**，紅的就是我漏登記備份那一題，
  修掉之後這一支才是零。**兩支都記在這裡，不要只留好看的那一支** ——
  那一紅是這一輪唯一一個「自我驗證永遠抓不到」的缺口被抓到的證據。

  ⚠️ 這**仍不能取代 C 的⑥**：我跑的是 B 自己的工作樹，⑥是 C 的職責且是權威結果。
  而且這一輪 ②先於④ 破了（A 已認錯並補進協定 §4），
  所以 C 的⑤要比平常更嚴 —— **只讀開發單、不讀我的實作**。
- **條件 12 · 全量回歸**（開關 `LICENSE_GATE_ENABLED = False`，＝正式機真正會跑到的狀態）：

  ```
  1056 passed, 55 skipped, 22 warnings in 1185.52s (0:19:45)
  ```

  **1056 ＋ 55 ＝ 1,111，零失敗**，與上一輪基準相同（協定 §4 ⑥「不可少於現況」✅）。

  ⚠️ **上一次那 1 題紅（`test_semaphore_caps_concurrent_holders`）這次自己好了。**
  兩次之間我沒有改過那支測試、也沒有改過它碰的任何東西（`EDGE_PDF_SEMAPHORE`／
  `startup.py`），唯一的差別是 A 停掉了他那支背景回歸。
  **這是「CPU 搶奪造成」這個說法唯一一次真的被驗證**——先前我只能說「單獨跑是綠的」，
  那不足以下結論（單獨跑就過，正是 flaky 測試的樣子）。現在有了對照組。
  ⚠️ 但這仍**不能取代 C 的⑥**：我跑的是 B 自己的工作樹，⑥是 C 的職責且是權威結果。
- **第 2 輪 commit**：`fb329be`（開關＋kind＋快取）→ `a63cc49`（middleware）
  兩個 commit 是刻意分開的：開關沒驗過之前不掛 middleware

> ⚠️ **不要在 C 的測試紅之前開始寫碼。** 協定 §4 的②先於④是刻意的：
> 先有測試才寫碼，測試就不可能是照著你的實作長出來的。

---

## 改了哪些檔、為什麼

> 一行一個完整路徑 ＋ 一句為什麼。寫「小修」等於沒寫。
> 沒改任何檔案就寫「無」，**不要留白** —— 留白讀起來像忘了填。

（第 1 輪，`2dadfb6`）
```
backend/helpers/licensing.py   【新增】授權金鑰核心
backend/routers/licensing.py   【新增】GET /api/license/status
backend/tools/issue_license.py 【新增】離線簽發 CLI
backend/main.py                【改 2 行】掛 router
```

（第 2 輪，`fb329be` ＋ `a63cc49`）
```
backend/helpers/licensing.py   LICENSE_GATE_ENABLED（預設 False）、kind 年費/永久、
                               LICENSE_EXEMPT_PATHS 具名常數、金鑰檔快取、
                               license_blocks_request()／license_block_message() 純函式
backend/tools/issue_license.py 加 --kind 參數（預設 subscription）
backend/main.py                【新增 53 行、無刪除】license_gate_middleware
```

（第 3 輪，`4edf210`）
```
backend/db.py                  migration _m085_procurement_lead_time（84→85）：
                               suppliers/parts 各加 lead_time_days INTEGER（預設 NULL）、
                               新建 purchase_suggestion_status
backend/helpers/procurement.py 【新增】全是純函式：clean_lead_time／resolve_lead_time／
                               compute_eta／effective_status／effective_cycle／
                               validate_transition。三個 router 走同一套判定
backend/routers/suppliers.py   lead_time_days 進出；驗證移到 broad except 之外
backend/routers/parts.py       lead_time_days 進出；照既有 safety_stock 的慣用法
backend/routers/inventory.py   採購建議加 leadTimeDays／eta／status；
                               新增狀態轉移端點；_YELLOW_MULTIPLIER 提為模組常數
frontend/pages/inventory.html  三個新欄位＋狀態按鈕；更正過期的說明文字
frontend/pages/suppliers.html  前置時間（天）數值欄位
```

（第 3 輪後續，`6613224` ＋ `9c2e70c`）
```
backend/routers/inventory.py   收掉第三份黃燈門檻字面值（_stock_level 改用模組常數，
                               連 docstring 裡那句「安全庫存 * 1.5」也改成引用常數名）
frontend/pages/suppliers.html  舊「標準交期」改為遷移提示＋legacyLeadTimeCount
backend/archive.py             把 purchase_suggestion_status 登記進每日 JSON 備份
```

**私鑰放在哪、有沒有進 .gitignore**（收工檢查表要求明確回報）：

- 路徑：`backend/tools/_license_private_key_dev.pem`（Ed25519，PKCS8，未加密，chmod 600）
- 公鑰已內嵌 `helpers/licensing.py` 的 `_PUBKEY_DEV`，會進 git（公鑰本來就是公開的）
- `_PUBKEY_PROD` ＝ `b""`，**照契約留空**，驗證時略過不丟例外
- **產檔前**先跑 `git check-ignore -v`：四條金鑰路徑全部命中 `.gitignore:11`／`:13`
- **產檔後**複驗 `git status --porcelain | grep -i "pem\|license.key"` → **空輸出**
- 沒有在 repo 內留下任何 `license.key`：手測用的金鑰寫在 scratchpad，`verify_license(None)`
  現在回 `missing`（＝ `backend/license.key` 確實不存在）

**沒有新增任何相依套件**：`cryptography>=42.0.0` 本來就在 `requirements.txt:14`。
**沒有動 `db.py`、沒有 migration、沒有建資料表**（金鑰是檔案）。

---

## 給彙整（A 會收進 STATE.md）

> 發現的問題、要動別人的檔、規格對不上、需要裁決的事，寫在這裡。
> **不要自己擴充規格範圍**；覺得該多做什麼，寫在這裡讓 A 決定。

> 第 1、2 輪已結案。以下是**第 3 輪**的提報。

- 🔴 **供應商表單裡「本來就有」一個前置時間欄位，現在變成兩個，請 A 裁決怎麼收。**
  `frontend/pages/suppliers.html:636` 有 `form.leadTime`，標籤「標準交期」，
  自由文字（placeholder 寫「例：30 天、4~6 週」），存在 `data_json` 裡。
  我 grep 過整個 `backend/`：**沒有任何一行後端程式碼讀它** ——
  這就是 SPEC §5.1 說的「`lead_time` 實測 0 處」的真身：**欄位一直都在，只是沒人用**。
  這一輪加的 `lead_time_days` 是真欄位、數值、進得了計算，兩者現在並存。
  我把舊的改標成「標準交期（說明）」並註明「系統不拿它算日期」，新的標「前置時間（天）」，
  **但這只是把混淆寫清楚，沒有消除混淆**。
  ⚠️ **不做資料遷移是刻意的**：`"4~6 週"` 要怎麼變成一個整數，不是我該替使用者決定的。
  請 A 裁決：① 維持並存 ② 退休舊欄位（要先確認沒有客戶在用它記別的東西）
  ③ 做一次人工協助的遷移。
- 🟠 **我動了一行既有程式碼，單子說「不要順手重構」，所以明講。**
  `inventory.py` 原本 `yellow_multiplier = 1.5` 是函式內的字面值。我把它提成模組常數
  `_YELLOW_MULTIPLIER` 並讓那一行引用它。**只有這一行，演算法一個字沒動。**
  理由：新的狀態轉移端點要判斷「這個料號現在還缺不缺貨」，必須跟清單用同一個門檻。
  兩邊各留一份字面值的話，某天有人只改一邊，就會出現「清單上看得到、
  轉移時卻說它不缺貨」——兩邊各自都對、合起來錯。
  ⚠️ **`parts_summary()::_stock_level()` 裡還有第三份 `1.5`**，是既有的，這一輪照單子不動它。
  它跟我的兩處目前一致，但它是**下一個會漂的地方**，建議排進某一輪處理。
- 🟢 **自我驗證第一次跑就抓到兩個真的 bug，值得記下形狀。**
  1. 清單算出 `status="suggested"`（新的一輪），卻把**上一輪的** `orderedAt` 原樣回傳。
     狀態欄對、時間欄對，合起來是「這一輪還沒下單，但下單時間是 3 天前」。
     **這正是我在同一輪裡警告過 A 的形狀，然後我自己寫了出來。**
     修法不是在清單那邊補一段 if，是把判定收進 `effective_cycle()`，
     讓清單與轉移端點**走同一支** —— 補 if 只會製造第三個判斷點。
  2. `create_supplier` 的 `except Exception` 把 `clean_lead_time()` 丟的 422 吞成 409，
     負數前置時間會回「建立失敗：...」而不是說明原因。驗證移到 `try` 之外。
  ⚠️ 兩個都不會被「程式跑得起來」這件事抓到。**第一個連 12 條驗收條件都可能全綠**
  （C 若只驗 `status` 欄位就驗不到）。建議 C 的測試對第 7 題加驗 `orderedAt`。
- 🔴 **全量回歸抓到一個我的漏洞，而且是「產品碼全綠也抓不到」的那種。**
  `test_system_audit_2026_09_14::test_every_table_is_either_backed_up_or_explicitly_excluded`
  ——我加了 `purchase_suggestion_status` 卻**沒有決定它要不要進每日 JSON 匯出**。
  那題的 docstring 問得很準：「這張表的資料如果要靠 JSON 重建，重建得出來嗎？」
  **處置是「加進備份」不是「加進排除清單」**：「這個料號是哪天下單的、哪天到貨的」
  在系統裡**沒有第二個來源**——採購建議本身是即時從庫存算出來的，
  **重算得出清單、重算不出這段歷史**。已加進 `archive.py::_daily_backup()`（`9c2e70c`）。
  也查了還原路徑：整庫 `.db` 是主路徑，JSON 是 §8.3 還原優先序的「最後手段」人可讀層
  （`archive.py:1039`），沒有第二張對應表要同步維護。
  ⚠️ **這一條我的自我驗證腳本永遠抓不到**——它驗的是 API 行為，
  而這是一道跨檔案的登記守門。全量回歸不是形式。
- 🟢 **從那個漏洞看出的一件更值錢的事（A 已採納，`8e971f1`）：這道守門只擋「新表」，
  擋不到「新欄位」。** 我這輪也加了兩個欄位，但那兩張表本來就在備份清單裡、
  備份語句又是 `SELECT *`，所以新欄位自動跟著進去——**這次是運氣好**。
  哪天有人在一張備份語句是**列舉欄位**的表上加欄位，守門不會紅，
  而那個欄位從加進去那天起就沒被備份過，直到真的需要還原才會知道。
  A 查證後指出既有的 `test_every_backup_query_actually_runs` 已經在做同一件事的一半
  （拿 `cursor.description` 對 `PRAGMA table_info`，只是範圍限在 BLOB 欄位），
  所以是**延伸既有機制而不是新建一套**。
  ⚠️ 我說「它現在會是綠的」不是缺點：**綠著的守門不是沒用的守門，是還沒被觸發的那一種。**
- ⚪ 差點犯的一個小錯，記著提醒自己：我在 `inventory.html` 寫了 `class="btn-mini"`，
  **那個 CSS 類別整個專案不存在**，是我自己發明的——按鈕會變成沒有樣式的裸按鈕。
  commit 前 grep 了一次才發現。前端沒有型別檢查，寫錯的類別名不會有任何錯誤訊息。

- 🟠 **提報給 A：這個 repo 缺 `.gitattributes`，而缺它會讓「用 git 還原檔案」悄悄改掉位元組。**
  （C 在跑⑥時發現的，我在這棵樹上查證了條件成立。**不動手，等 A 決定。**）

  **查證過的事實**（我剛實際讀的，非推論）：
  ```
  core.autocrlf = true
  .gitattributes = 不存在
  磁碟上的 .py / .html = 全部 LF（含我從沒碰過的 archive.py、routers/auth.py、helpers/auth.py）
  磁碟上的 .bat / .ps1 = 全部 CRLF，需要 BOM 的都有 ← 這部分專案處理得對，不需要動
  ```

  **後果**（機制由 C 在丟棄式 repo 裡實測證明，條件在這裡成立；
  ⚠️ 我**沒有**在這棵樹上重現，因為當時 C 正在量它）：
  `git checkout -- <某支 .py>` 會把它拉回 **git 認為的樣子**＝ CRLF。
  `git diff` 看不出來（它會正規化），但磁碟上的位元組變了、內容雜湊會變。

  **真正的形狀比「git 會改行尾」深一層**（C 的講法，比我的準）：
  > 工作樹長期由「不經過 git 的工具」維護，於是它偏離了 git 認為 checkout 該產出的樣子。
  > 平常沒事，直到有人用 git 去「還原」一個檔——那一刻 git 把它拉回 git 的版本，
  > 而那跟原本磁碟上的不是同一串位元組。
  > **「還原」這個詞在這裡會騙人：它還原成 git 認為的原樣，不是你動手之前的原樣。**

  **最容易中的是突變測試**（改檔 → 跑 → `git checkout` 還原）。
  C 第 1、3 輪全走 monkeypatch 所以沒中，**但那是運氣不是設計**。

  **✅ 已由 A 加上（`e9929d1`），而且是零改寫的。**

  ⚠️ **上面那段警語我原本寫的是錯的，留在這裡當紀錄**：我抄了「它會重寫整棵樹的
  位元組 ⇒ 不可以在任何人跑回歸時做、做完要重跑一次當新基準」。
  **那是一個沒查證的假設**（A 提出、我原封不動轉述）。A 後來去查物件庫才發現
  **ODB 裡存的本來就全是 LF**，加規則只是把「checkout 該產出什麼」講清楚：
  實測 0 個追蹤檔被視為修改、`.bat`／`.ps1` 與備份逐位元組相同。

  **教訓（A 的話，我認同）：「延後的理由」也要被查證。**
  延後看起來像謹慎，而**謹慎地做錯事比急著做對事更難被質疑**。
  而那個被延後的風險在決定延後的 30 分鐘內就真的發生了（C 把 `C.md` 轉成了 CRLF）。
  ⇒ 對我的具體修正：**轉述別人的風險評估時，要嘛自己查證，要嘛標明「這是轉述、我沒查」。**
  我當時兩件都沒做。

---

## 收工檢查表

- [ ] 改的檔案都在我的歸屬範圍內（鎖定檔有宣告並拿到 A 回覆）
- [ ] `git status` 看過，`git add` 只加到檔案層級，沒有 `git add <目錄>`
- [ ] 上面〈改了哪些檔、為什麼〉填完了
- [ ] 有沒有動 `db.py` schema？有的話在〈給彙整〉明確寫出 migration 編號
- [ ] 有沒有新增相依套件？有的話寫進〈給彙整〉，**不要自己改 `requirements.txt` 就算了**
- [ ] 有沒有產生不該進 git 的檔案（私鑰、憑證、金鑰）？有沒有加進 `.gitignore`？

## 停工點宣告（第 6 輪）

- **SHA**：`efb9b91e5b29b3ba22202c068e3821859378a173`（`efb9b91`）
- **時間**：2026-09-21
- **範圍**：`backend/** ':!backend/tests'` ＋ `frontend/**`
- **複驗**：`git log efb9b91..HEAD -- backend frontend ':!backend/tests'` 為空；
  同範圍 `git status --porcelain` 亦為空。
- **狀態**：第 6 輪產品碼全部落地，B 停工，C 可對此樹跑 ⑤ 反向驗證與 ⑥ 全回歸。

### 給 C：⑥ 的執行時間有變（這是 D3 的代價，不是環境問題）

`-k tender` 這 103 題從約 40 秒變成 **225.78 秒**。
原因是 D3 要求抓明細之間要 `time.sleep(2)`，而**沒有 patch 掉 `time.sleep` 的測試會真的睡**。
這是刻意走模組屬性（`time.sleep` 而非 `from time import sleep`）才 patch 得到的那個設計，
副作用就是沒 patch 的地方會付出真實秒數。⑥ 的總時間請把這 3 分 45 秒算進去。

### 給 A：本輪有一筆「測試擋不住」的東西被放了好幾輪

`.form-input` / `.form-select` / `.form-label` 三個 class **從來沒有被定義過**，
那些欄位一直是沒有樣式的裸 input。使用者回報的「欄位跟字體字型都跟其他頁面不一樣」
就是這個，而我前一輪把它當成「自訂樣式與系統分岔」去修，修錯了方向——
**真正的問題不是我發明了一套樣式，是我引用了一套不存在的樣式。**
⚠️ 這個專案沒有全域表單樣式：`case-management` 用頁內 `.fi`、`dev-crm` 用頁內 `.dc-input`，
每頁各自帶一份。所以「沿用系統慣例」在這裡指的是**沿用同一組名字與同一組值**，
不是引用一個全域樣式表——我照後者的假設去查，才會查不到又不覺得奇怪。
📌 CSS 少一個定義不會報錯、不會紅、不會有 console 訊息，它只是看起來很醜。

## 施作慣例：跑 pytest 一律給 `--basetemp`

```
python -m pytest ... --basetemp="<自己的 scratchpad>/ptXX"
```

⚠️ **不給的話，pytest 用 `%TEMP%\pytest-of-hichan\pytest-current`，而那個路徑多個視窗共用。**
兩個 session 同時跑，一個會清掉另一個正在用的暫存資料庫。

🔑 **這件事最貴的地方是它不會以「衝突」的樣子出現：**
- 我撞到的是收尾階段 → `PermissionError [WinError 5]` on `pytest-current`，
  而且 **traceback 把測試結果那一行蓋掉了** ⇒ 我歸成「已知的 pytest 暫存毛病」。
- C 撞到的是中途 → 暫存 DB 被清掉，噴在**一支完全無關的報表測試**上的
  `sqlite3.OperationalError`，而且偶發 ⇒ 第一個診斷是「CPU 搶資源」。

**同一個根因、兩個都很合理的錯誤診斷，兩個都不會找到它。**
⇒ 判準不是「記得加」，是**把它當成指令的一部分**，跟 `-q` 一樣不用想。

~~📌 給 A 的一筆：這不是 B 一個人的問題，任何兩個視窗同時跑 pytest 都會中。
值得考慮在協定層面規定（或想辦法讓它結構上不可能……）。~~

🔴 **上面這段是錯的，2026-09-21 當天由 A 更正、我自己查證屬實。**
（留著不刪：只留結論的話，下一個人看不到我是怎麼推到錯的地方去的。）

**規則早就在 `MULTIWIN-PROTOCOL.md:226-243`（§5 第 3 條）**，而且比我寫的更精確——
它要求「**固定但分用途**」，不只是「要給 `--basetemp`」。
那一段裡甚至還記著我自己先前的自查結論：
> B 先前全量與單檔也用同一個 basetemp，只因為那兩次回歸期間剛好沒再跑 pytest 而避開
> ——靠運氣，而運氣不是防線。

⇒ **結論不是「加規則」，是「規則沒有到達」。而「再寫一次」是最沒用的處置。**

## 🔴 而且我在查證的過程中，發現另一條我也違反了

**§5 第 5 條：「全量回歸一次只能有一個人跑，跑之前要在自己的視窗檔寫一行『我開始跑了』。」**

2026-09-21 18:35:11 我起了全量回歸，**沒有宣告**，而 C 的⑤正在連續跑 pytest。
basetemp 我是隔離的（查證過，檔案沒互刪），但 **CPU 一直在搶**——
那正是這條規則存在的理由，而協定裡記的上一次踩雷，註明「當下有三個 pytest 在跑」的人**就是我**。

🔑 **我沒讀那一段，不是因為找不到，是因為我以為自己已經處理好了那個問題**
（我加了 `--basetemp`、還寫進了這個檔）。
**「我已經修好了」是停止查證最有效的理由，而它跟「真的修好了」在當下長得一模一樣。**
⚠️ 附帶：**自己寫過的規則最不會被重讀**，因為「我知道那裡寫什麼」這個感覺特別強。

## 所以這一節的正確內容是

跑 pytest 照 §5-3 的「固定但分用途」，**跑全量回歸前先在這個檔寫一行「我開始跑了」（§5-5）**。
不要在這裡重述協定的內容——[[規則副本會過期]]，指過去就好。

## 恢復施工宣告（第 6 輪 b）

- **時間**：2026-09-21 19:0x
- **前一個停工點**：`864dd75`（C 的⑤已對它跑完，八個突變全部精準咬合）
- **本次要動**：`backend/helpers/tender_source.py`、`backend/routers/tender_radar.py`
- **內容**：A 裁示 ②③ —— `radar_on()`、`run_scan` 守衛改讀它、status:292 改讀它、
  測試模式專用的 `reset-today` 端點（無環境變數時 import 時就不註冊 ⇒ 真正的 404）
- **做完**：重新宣告停工點，C 補驗 08d～08h 後跑⑥

📌 這條宣告本身是 2026-09-21 新增的慣例：**停工點宣告之後要再動產品碼，得先宣告恢復施工，
不是動完再補講。** 上一次我沒做，讓 C 的⑤跑在會動的目標上，三個突變結果作廢重跑。

## ~~🔒 佔用宣告：migration v89（§3l `company_profile.address`）~~ ✅ **已釋放 2026-09-21**

- **宣告時間**：2026-09-21
- **佔的是**：`db.py` 的 `CURRENT_VERSION 88 → 89`、新函式 `_m089_company_address`、
  `_MIGRATIONS` 清單末尾一筆
- **狀態**：⏸️ **只佔號，尚未動手**。等 C 的七步紅燈才寫。
- **查證**（不是照抄 A 的轉述）：
  - `db.py:103` `CURRENT_VERSION = 88`
  - `_MIGRATIONS` 最後一筆 `_m088_tender_detail_fields  # v88`
  - `grep -rn "v89\|_m089" docs/windows/` → 空，**沒有別人佔過**
- ⚠️ **兩人同時加 migration，git 不會衝突，只會在執行時撞版本號。** 所以要用宣告不是靠 diff。
- 📌 做完要把這一節改成「已釋放」。

### 寫的時候必須記得的兩件（已自行查證，非轉述）

**① `_seed_setting` 改不動既有資料庫**
```
db.py:3808  INSERT INTO system_settings ... ON CONFLICT(key) DO NOTHING
```
`company_profile` 目前 seed 七個鍵（name／tax_id／contact_info／bank_name／
bank_branch／bank_account_name／bank_account_number），**沒有 address**。
⇒ **把 `address` 加進那個 dict，對已經存在的資料庫一個字都不會變**（`DO NOTHING`）。✅ 這句仍然對。

~~⇒ migration 必須是讀出現有 JSON → 缺 address 才補上 → 寫回，不可以整個 dict 重寫。~~

🔴 **上面那個結論是錯的，由視窗 C 更正、我自己查證屬實 ⇒ 很可能根本不需要 migration。**
```python
routers/system.py:623
return {**_COMPANY_PROFILE_DEFAULT, **(_get_setting("company_profile", {}) or {})}
```
`_COMPANY_PROFILE_DEFAULT`（`system.py:612`）在**讀的時候**把預設蓋在存的值下面，
所以既有安裝缺的鍵**在讀取端就補好了**——銀行那四欄 2026-08-24 已經走過這條路，
而且那行的註解就是為了同一件事寫的。

🔑 **我的錯不在查證，在推論的範圍。** 我查了 `_seed_setting` 屬實，
然後直接推出「所以要靠 migration 補」——**而我沒有去查「有沒有別的地方已經解決了它」。**
⇒ 這是今天第三次同一個骨架：**查了一環，推了整條鏈。**
（前兩次：排程那 13 個檢查查了呼叫端沒查被呼叫的函式；exit 127 把兩個行程的證據合成一份。）
⚠️ 而三次的共同點是**查到的那一環都是真的**，所以推出來的結論聽起來有憑有據。

### 所以 §3l 真正要改的是三處，`db.py` 影響最小
| 檔 | 影響 |
|---|---|
| `_COMPANY_PROFILE_DEFAULT`（`system.py:612`） | 既有安裝讀得到 `address` 的**真正原因** |
| `CompanyProfile`（Pydantic，`system.py:602`） | 沒有它，**PUT 會把 address 丟掉** |
| `db.py` 的 `_seed_setting` | 只影響**全新安裝** |

### 🔴 而我另外查到一件 C 與 A 都還沒點到的
```python
system.py:627  def set_company_profile(body: CompanyProfile, ...)
system.py:629      value = body.model_dump()      ← 全欄位
system.py:630      _set_setting("company_profile", value)   ← 整筆覆蓋
```
**這是整筆覆蓋，而每個欄位都有 `= ''` 預設** ⇒ **任何沒送齊欄位的呼叫端，會把沒送的欄位清成空字串。**
🔑 **那正是我今天修的 D22／D21b 完全相同的形狀**，只是換一個檔。

前端目前**是靠巧合活下來的**：
```js
company-profile-settings.html:468   this.cfg = { ...this.cfg, ...data }
company-profile-settings.html:637   body: JSON.stringify(this.cfg)
```
它是**把 GET 回來的整包併進 cfg 再原樣送回**，不是逐欄挑 ⇒ 新欄位會自動被帶著走。
⚠️ **但那是「剛好沒事」不是「防住了」**：
一個在部署**之前**就開著的分頁，它的 `cfg` 沒有 `address`，**存檔時會把 address 清掉**，
而畫面上是「欄位都在、只是空的」——跟「還沒填」一模一樣。

**② 距離的精度天花板不是地址決定的，是資料來源決定的**
```
tender_source.py:409  return {"location": place if place in _TW_PLACES else None}
_TW_PLACES = 22 個縣市，沒有區、沒有鄉鎮
```
⇒ `tenders.location` 只可能是 22 個縣市字串之一或 NULL ⇒ **距離只能到縣市中心點。**
⚠️ **本輪不動解析器**去提高精度：詳細頁上的完整地址是**另一個欄位**（文件遞送地點），
而 C 查過那一頁「地址」出現 10 次、9 次是樣板。**看起來可以精確不代表那個值是對的。**

**③ M6 是最容易做出「安靜的錯」的一題**
`location` 是 NULL 的標案：要在清單裡、不在地圖上、**而且畫面要寫出「有 N 筆沒有地點資訊」**。
☠️ **地圖上少幾個點，跟「那些標案不存在」長得一模一樣，而且沒有人會報修。**
（同族：[[feedback-null-vs-zero]]、本檔前面那條「NULL 顯示『—』不留空白」。）

## 恢復施工宣告（L1 · 啟動 log）＋ 🔒 鎖定檔 `main.py`

- **時間**：2026-09-21 20:3x
- **前一個停工點**：`e4b25ca`（C 的⑥已對它跑完，1198/55/0）
- **要動**：**`backend/main.py`（鎖定檔）**，只加一行 `logger.info` ＋ 註解
- **紅燈來源**：C 的 `tests/test_tender_startup_log_2026_09_21.py::test_l1`（SHA `3f39568`）
- **做完**：宣告停工點，不往前跑 §3l（形狀已改兩次，動手前要重讀）

### 放置位置是這題唯一會做錯的地方
那一行**不可以**放進 `if os.getenv("MOTRIX_DISABLE_SCHEDULERS") != "1":` 裡面。
兩個獨立的理由：
1. **測試上**：C 的子行程是帶著 `MOTRIX_DISABLE_SCHEDULERS=1` 跑的 ⇒ 放在裡面 L1 永遠紅。
2. **語意上**（這個才是真正的理由）：**「這台機器會不會對外連線」與排程開不開無關**——
   排程關著時使用者按「立即掃描」照樣會連出去。
   ⚠️ 把它放進排程閘門裡，會讓一台「排程關、雷達開」的機器**不印那一行**，
   而那正是我們現在這台測試機的組態 —— **最需要被標記的那一台剛好不會被標記。**
🔑 **只靠理由 1 也會寫對，但會寫對得很脆**：哪天測試改成不設那個變數，就沒有東西擋著它被移進去。

## ✅ v89 佔號釋放 ＋ 🔒 下一個佔用：`db.py`（U5）

**v89 釋放**：§3m 實測證明升級路徑不需要額外 migration（A 對正式機備份複本實跑
`db._run_migrations()`：84→88、76→81 張表、**9,176 列前後不變**、既有列拿到 NULL 不是 0）。
`address` 走讀取端預設（`_COMPANY_PROFILE_DEFAULT`）就夠。
📌 那個佔號從頭到尾沒有被用到，**而它存在的那段時間是有價值的**——
它擋住的不是「我寫了 migration」，是「別人以為 89 沒人要」。

**下一個佔用：`db.py`（鎖定檔）**，只改 `_run_migrations` 的早退分支，加一筆 WARNING（U5）。
⏸️ **已備妥但尚未執行**：C 的⑥還在跑（67%），改 `backend/**` 會讓那一輪量到會動的樹。
⚠️ A 同一則訊息裡同時說了「你可以動」與「C 還在跑、不要跑 pytest」，**兩者有衝突**，
我取後者：⑥ 的目的正是「在什麼條件下量的」，讓它跑在會動的樹上會毀掉那個目的。
已回報 A。

## §3l 的 API 契約（從 C 的 `test_geo_2026_09_21.py` 抽出，19 支測試 / 24 題）

⚠️ 這份是**抽出來的**不是**約定的**——解鎖後動手前要再對一次測試本文。
記在這裡是因為：測試檔的中文在這台的主控台會糊掉，**抽 ASCII 識別字是唯一可靠的讀法**。

### `backend/helpers/geo.py`（新檔）
| 名字 | 形狀 |
|---|---|
| `GEO_ENABLED` | 字面值 `False`（出貨預設，M9 釘它） |
| `geo_on()` | `GEO_ENABLED or os.getenv("MOTRIX_GEO") == "1"` |
| `haversine_km(a, b)` | 純函式，對稱、自己對自己為 0（M7／M7b） |
| `geocode(...)` | **走模組屬性**才 patch 得到（M8b） |
| `USER_AGENT` / `FETCH_TIMEOUT_SECONDS` / `GEOCODE_INTERVAL_SECONDS` | 對外連線四道護欄（M8） |

🔑 **`geo_on()` 是 `radar_on()` 的第二個實例**，而 M9c 明確測了 `"true"`／`"yes"`／`"false"`
都**不可以**打開它 ⇒ `== "1"` 不是真假值。**這是今天第二次抄這個形狀，要整個抄不是抄一半。**

### `GET /api/tender-radar/map`
回傳鍵固定五個：`office`／`officeMissing`／`points`／`withoutLocation`／`googleMapsConfigured`
- `points` 的元素含 `caseNo`
- ☠️ **`withoutLocation` 是 M6**：`location` 為 NULL 的標案要**被數出來**，不是被丟掉。
  地圖上少幾個點跟「那些標案不存在」長得一模一樣，而沒有人會報修。
- `officeMissing` 是 M3：辦公室地址沒填要**講出來**，不是安靜跳過。

### 設定
`google_maps_api_key`（M12 要在既有資料庫上讀得到），對外名 `googleMapsApiKey`。
🔴 **M14：金鑰不可以進 log。** 這一題與 L1 那條「要記錄開著那一側」是相反方向的同族——
**一個要留痕跡，一個不可以留痕跡，判準都是「洩漏出去的代價」。**

### M13／M13b（前端）
金鑰空 ⇒ Google 區塊**不存在**；設了才出現。
⚠️ 我先前給 A 的提醒要自己記得：**「渲染一張沒有點的地圖」也是錯的**——
它跟 M6（有標案但沒有地點）在畫面上是同一個樣子，而兩者的處置完全相反。

## §3j 實作設計（凍結期間規劃，解凍後照這個寫）

### 三個層次，**只有最底下那一層碰系統時鐘**
```python
def now_dt():            # 唯一呼叫 datetime.now() 的地方
def scan_hours():        # 設定 tender_radar_scan_hours   → list[int]
def notify_hours():      # 設定 tender_radar_notify_hours → list[int]（允許空）
def current_slot():      # now_dt().hour if 它在 scan_hours() 裡 else None
```
🔴 **`current_slot()` 內部要讀設定**（C 的要求，理由是對的）：
他原本 patch `current_slot()`，**那會把「有沒有查設定」這件事一起 patch 掉**——
觀測手段與被測對象共用一段程式碼的第五個實例。

⚠️ **而有一個推論 C 沒講，不注意會做錯**：
**寄信時段的判斷不可以用 `current_slot()`。**
SL16 的設定是 `scan_hours=""` ＋ `notify_hours="9,12,15,18"` ⇒
`current_slot()` 在那一題**永遠回 `None`**，寄信那一段就永遠拿不到小時。
⇒ 寄信要直接問 `now_dt().hour`，抓取才問 `current_slot()`。
🔑 **兩個設定是獨立的，所以判斷時段的入口也必須是獨立的。**

### 兩個「做過了沒」的標記要放在**不同的地方**（SL7）
| | 放哪 | 為什麼 |
|---|---|---|
| 抓取側 | `tender_fetch_log`（今天 ＋ 小時 == slot）| 既有機制，`_already_fetched_today` 改成 `_already_fetched_this_slot` |
| 通知側 | `system_settings` 的 `tender_radar_notify_last_slot`（單鍵 ＋ `>=`）| **`tender_fetch_log` 不進每日備份** ⇒ 放那裡的話**每次災難還原都會重寄** |
📌 SL7 的本意就是「兩個標記不可以共用一個載體」，所以這個分法不是權宜，是它要的答案。

### 既有設定的遷移（A 裁 (乙)，SL17／SL18）
```python
raw = _get_setting("tender_radar_scan_hours")        # ← 先問「鍵在不在」
if raw is None:                                       # 不是 `or`！
    old = _get_setting("tender_radar_scan_hour")      # 第 6 輪的單數鍵
    raw = str(old) if old is not None else DEFAULT
```
🔴 **判準是「鍵存在嗎」不是「值是不是真的」。**
寫成 `new or old` 的話，**使用者把寄信時段設成空（＝不寄，SL3 明訂的合法值）
會是 falsy ⇒ 退回舊值 ⇒ 它又開始寄了。**
📌 同一形狀 D 今天在 `quotations.py:1379` 找到一個（`body.status or q.get(...)`，
而左邊有 truthy 預設 ⇒ 右邊是死碼）。**同一天、同一個形狀、兩個檔。**
⚠️ 舊的單數鍵**留著不刪**——刪掉就沒有回頭路，留著的成本是一行 fallback。

### 其他
- **SL10**：`_fetch_details` 的 `fetched` 是區域變數 ⇒ 上限實際是「每次呼叫 20」。
  一天四個時段就是 80。要改成**跨呼叫累計**（依 `tender_fetch_log` 或當日計數）。
  ⚠️ 現在「每天 20」與「每次 20」恰好相等，**那是巧合不是設計**。
- **SL13**：拿掉 `/schedule` 的 `dailyLimitNote`。
  📌 這是我寫的字串，而使用者讀到它之後裁示「我要可調整」——
  **寫在畫面上的字串沒有「待辦」狀態，它一上線就在對使用者說話。**
- **SL9**：`_seconds_until_next_run()`（915）目前直接 `datetime.now()`，**patch 不到**，要改走 `now_dt()`。

## 🔒 佔用宣告：`backend/tools/check_undefined_names.py`（新檔）

- **宣告時間**：2026-09-21，⏸️ **備妥未落地**（樹凍結中，等 C 報完回歸）
- **來源**：A 裁定做成常設守門（`287b325`）
- **內容**：純標準庫的 mini-pyflakes，找「函式裡引用了一個哪裡都沒綁定的名字」

### 它找到的兩個真實案例（都在「只有異常時才走到」的路徑上）
```
helpers/tender_source.py:912  scan_hour()           -> DEFAULT_SCAN_HOUR（不存在）
helpers/email_notify.py:1494  notify_backup_stale() -> datetime（整檔沒 import）
```
🔑 **1,175 題測試一題都沒抓到，而那不是巧合**：
**防禦與告警路徑平常永遠不執行，所以那是這類 bug 唯一能長期存活的地方。**

### 🔴 我實測了它的盲區，而不是只寫「漏報率未經查證」
造 13 個案例（含「它應該報而沒報」的對照組）：**0 誤報、3 個已知漏報**。
| 漏報 | 風險 |
|---|---|
| 模組層的程式碼 | **低**——`NameError` 在 import 當下就炸，任何 import 它的測試立刻紅 |
| class body | **低**——同上 |
| 🔴 只在巢狀函式裡綁定、外層使用 | **高**——跟那兩個真案例一樣是**執行期**才炸 |
⇒ **要改進先關第三個。** 三個都寫成 `--selftest` 的案例，
**把盲區寫成會被執行的東西，它才不會隨時間被忘掉。**

### 設計上刻意選的取捨
`_bound_by()` **連巢狀函式一起收** ⇒ 造成上表第三個漏報。
🔑 **選漏報不選誤報是有意的：一支會亂叫的守門會被關掉，而被關掉的守門連漏報都不如。**
（同 A 今天那條：**過嚴的守門不會讓人更小心，它會讓人學會怎麼關掉守門**。）

### ⚠️ D 指出而我要照抄進 docstring 的一句
> 交叉比對提高的是**精確度**，不是**召回率**——而一支守門的失敗模式是召回率。
⇒ 所以 docstring 明寫「**它找到的每一個都是真的，但它沒找到不等於沒有**」，
**不可以把它的存在讀成「這一類已經守住了」。**

## 🔴 §3j 的第一個動作（A 的條件，`6447bc3`）

```python
# helpers/email_notify.py 檔頭
from datetime import datetime
```

⚠️ **這一行要排在 §3j 的第一個 commit，不可以變成「§3j 做完順便修」。**
理由是 A 寫的，而它值得照抄：**那樣它會跟著 §3j 的任何延誤一起延。**

📌 它修的是一個**現行缺陷**（`notify_backup_stale` 的 `NameError`），
而 §3j 其餘部分是新功能。把它併進同一輪是為了省一次停工與一次回歸，
**不是因為它比較不急**——所以順序上要反過來：**最急的先落地。**

🔑 A 把「併進去等於延後一個現行缺陷」這個判斷**明著寫下來**，
理由是「**順便延後一個現行缺陷，正是最容易在事後看起來很糟的那種決定**」。
⇒ 配套：本輪的三件（import／標記順序／裸執行緒）做完**之前**不要開始 SL 系列。

## 恢復施工宣告（§3j）

- **時間**：2026-09-21 22:0x ／ **前一個停工點** `cf38f91`（C 的⑥已對 `5964ce5` 跑完）
- **本次動**：`backend/helpers/tender_source.py`、`backend/routers/tender_radar.py`
- **⏸️ 仍不碰**：`email_notify.py`／`daily_tasks.py` —— 等 C 補
  「`notify_backup_stale` 本體跑得起來」那一題的紅燈（目前無紅燈，依協定不能寫）
- **⚠️ 會撞到 C**：`_already_fetched_today` → `_already_fetched_this_slot`，
  三處既有 patch 會變 AttributeError，已告知

## 佔用宣告：`backend/routers/daily_tasks.py`（§3j 第 3 項，2026-09-21 22:5x）
只改 `_check_backup_freshness` 的告警那一段（旗標順序＋例外要留痕跡）。

## 佔用宣告：`main.py`＋`sidebar.js`＋新檔 `routers/map_points.py`（5c 端點搬遷，23:3x）
地圖脫離雷達成獨立模組：新增 `/api/map/points`、掛 router、側欄加 `map` key。

## 🔴 已知缺陷（待 C 的紅燈，凍結中不修）：CSP 擋掉圖磚

```
main.py:419   "img-src 'self' data: blob:; "
map.html      https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png
```
⇒ 按「開啟地圖」會是**一片灰**。A 實測，我複核過原始碼。

### ☠️ 而真正該記的是這一層，不是那一行設定

**我加的 `tileerror` 提示會說「底圖需要網路連線，這台機器可能沒有對外連線」——而那個診斷是錯的。**
真正的原因是同源政策，機器的網路好得很。

🔑 **今晚我一直在做的是「讓壞掉看起來像壞掉」，而這一次它壞掉了、也出聲了、但指錯了方向。**
📌 **一個會講錯原因的錯誤訊息，比沒有訊息更難查**——因為它會讓人去查網路，
而網路是對的，於是他會更困惑，然後開始懷疑別的東西。

⚠️ 成因是我**替使用者斷定了原因**：我只有一個訊號（圖磚載不出來），
卻在文案裡把它翻譯成一個特定的成因（沒有網路）。
⇒ **有 N 個可能成因而只有 1 個訊號時，就不要斷定是哪一個。**
修的時候文案要改成：
> 「底圖載入失敗。可能是沒有對外連線，或瀏覽器的安全政策擋下了 `tile.openstreetmap.org`。
> 清單與距離不受影響。」

### 修法（等 C 的兩題）
`img-src 'self' data: blob: https://*.tile.openstreetmap.org`
⚠️ 要萬用字元子網域（Leaflet 的 `{s}` 輪替 `a/b/c`）。
🔴 **不可以把 `img-src` 改成 `*`。**

### 📌 順帶更正我自己講過的一句
我說過「本系統對外部 CDN 的依賴是零」。
**那句話對的是「實際使用」，不是「政策允許」**——
`main.py:415` 的 `script-src` 裡有 `https://cdn.jsdelivr.net`，沒有任何頁面引用它，
**但政策是開著的**。⇒ 「沒有人在用」與「不可能被用」是兩件事，而我用前者講了後者。

## 🔒 佔用宣告（重新）：migration **v89** ＋ `db.py`（§3o 地理編碼快取進 DB）

- **時間**：2026-09-22 ／ ⏸️ **只佔號，等 C 的 A11–A14 才動手**
- **查證**：`db.py:103 CURRENT_VERSION = 88`、`_MIGRATIONS` 末筆 `_m088  # v88`、
  `docs/windows/` 裡 v89 只出現在**我自己先前釋放的紀錄**裡 ⇒ 沒有別人佔著
- **佔的是**：`CURRENT_VERSION 88 → 89`、新函式 `_m089_geocode_cache`、
  `_MIGRATIONS` 末尾一筆、新表 `geocode_cache`
- ⚠️ **§3m 的升級路徑要重驗**：A 先前實跑的是 84→**88**，加了這一支之後是 84→**89**

### 📌 這一次是真的要用（上次佔了沒用到）
使用者裁示把地理編碼快取存進資料庫。A 量給他看的：
```
_CACHE 是純記憶體 ⇒ 重啟就空
不重複地址最多 27 個（22 縣市＋其他＋辦公室）
autostart.bat 是無限迴圈 ⇒ 用量由「重啟幾次」決定，不是由使用者決定
```
⇒ **存進 DB ＝ 一輩子 27 次；不存 ＝ 每次重啟 27 次。**

### ⚠️ 設計要點（C 的 A11–A14 會釘，先記下來）
- **來源要分得開**：同一個地址用 OSM 與用 TGOS 查，結果不一樣 ⇒ 快取鍵要含來源
- **精度也要存**：只存座標的話，日後從「縣市中心」升級到「門牌」時，
  **舊的粗結果會被當成新的細結果用**，而畫面上看不出來
- **失敗不進永久快取**：`503`／逾時是暫時的，寫進 DB 會讓一次抖動變成永久的空白
  （記憶體版已經是這個規則，進 DB 之後更要守——**記憶體會自己忘記，資料庫不會**）

## 📌 登記（不做）：TGOS 兩件
1. **TGOS 底圖是 OSM 圖磚的替代方案**：免註冊、免費、明文可商用、無網域綁定。
   ⚠️ 但顯名標示是硬的（「**未盡顯名標示義務者，視為自始未取得授權**」）⇒ **要做進畫面**。
   現在 OSM 圖磚已經能用了（Referrer-Policy 修好之後），所以**這一輪不做**。
2. 🔴 **未知**：TGOS **Lite 版到底含不含「地址定位」**。
   我查到的是「Lite 只有 10 個 API 類別（基本地圖與標記）」，
   而「地址定位」出現在**完整版**的文件索引裡。
   ⇒ **我先前那句「它是唯一能裝好就能用的選項」，對「顯示地圖」成立，對「地址轉座標」還不知道。**
   🔑 〈答案沒錯，是題目問錯了〉：**我完整回答了一個問題，而要問的是另一個。**

## 恢復施工（§3o，2026-09-22）：動 `db.py`（v89，已佔號）＋ `helpers/geo.py` ＋ `routers/map_points.py` ＋ `frontend/pages/map.html`

## 佔用宣告：`db.py`（§3i 連線 context manager `db_conn()`）＋ `routers/dashboard.py` 九支，2026-09-22

## 佔用宣告：`db.py` §U8（`_get_version` 讀不到版本時的判斷方式），2026-09-22

- **佔的是**：`_get_version()` 函式本體 ＋ 新增 `_table_exists()` 小 helper
  （db.py 的鎖我已經持有，這一段是**告訴別人我動的是哪一塊**，不是重新上鎖）
- **不動**：`_set_version`、`_run_migrations` 的流程、任何一支 `_mNNN`
- **A 的裁定**：不要用 `except sqlite3.OperationalError: return 0`，
  **先正面查 `sqlite_master`**；`db.py:597` 的 docstring 論證留著、結論換掉
- 順手修兩句「宣稱有守門而那個人不存在」（C 抓到的）：
  `db.py:652` 指向 `test_upgrade_path_2026_09_21.py::test_u5c` —— **那支不在那個檔裡**
  （實際在 `test_spec_debts_2026_09_22.py`，而且今天才存在）；
  `db.py:668` 「Each function must be idempotent」—— U10 今天才守住它

---

# 🛑 停手宣告（2026-09-22 03:04）

```
最後一個 commit   f84333b018721df3fa16db2479a9f4e96544501e
宣告時間          2026-09-22 03:04:19（本機時間）
工作樹            乾淨（git status --porcelain 無輸出）
我最後寫入的檔    frontend/pages/tender-radar.html  02:56:15
```

**我不再寫入 `backend/` 與 `frontend/`，直到 A 說可以。**

⚠️ **這不是收工，是暫停** —— A 驗收時若發現畫面有問題，叫我解除就會繼續。

## 📌 為什麼要有這個宣告（C 的教訓）
> ⑤ 第一輪在**沒有套用任何突變**的情況下紅了三題 —— 因為 B 正在同一個工作目錄裡存檔。
> 🔑 **一個沒有套用的突變產生的紅燈，跟一個真的缺陷長得一樣。**

⇒ 打包那 27 分鐘裡我必須**真的**停手，不只是說停手了。
☠️ 否則 A 會拿到一個**無法重現的紅燈**，然後花時間查一個不存在的缺陷，**而那 27 分鐘要重跑**。

## 🔓 解除條件
A 說「可以動了」。**我自己不會解除**——包括「只是改一個註解」也不會。

## ⚠️ 停手期間仍然會變的東西（不是我寫的）
- `backend/motrix_erp.db`（**未追蹤**）—— 開發伺服器若在跑就會寫它
- `%TEMP%\motrix-pytest-B-*` 三個暫存目錄可以刪（`-adhoc`／`-adhoc2`／`-adhoc3`／`-sweep`）

## 🔓 解除停手（2026-09-22 03:33，A 通知）

**打包成功，今晚收工。** 停手期間我**沒有**寫入 `backend/` 與 `frontend/`
（`f84333b` 之後只有 `docs/` 的兩筆）。

```
包     deploy_packages/20260922_033314_c4f7c65/
測試   1440 passed / 53 skipped / 0 failed（非 e2e）＋ 53 passed（e2e）
```

### 📌 第一次打包紅了一題，而它紅得對
```
test_every_table_is_either_backed_up_or_explicitly_excluded
assert not {'geocode_cache'}
```
**`geocode_cache` 是我加的新表（v89），而沒有人為它做過「要不要備份」的決定。**
🔑 那正是〈守門要驗「有沒有人做過決定」〉——它驗的不是決定得對不對。
⚠️ 而**我加表的時候沒有想到這件事**：我想的是「快取要不要存 DB」，
不是「這張表算不算個資」。A 裁定排除，理由寫**隱私**不寫「它只是快取」。

### ☠️ 而它帶出一件範圍更大的（§3t，待使用者裁示，不擋上線）
每日備份的 `contractors` 是 `SELECT *`
⇒ 身分證號、住家地址、銀行帳號、**身分證掃描檔**每天上傳到雲端硬碟。
🔑 **A 排除的是「住家的經緯度」，而「住家地址本身」早就在那裡了。**
📌 與我今天那個 access log 是同一族：
**我們盤點的是「我們這次會寫什麼」，而既有的出口沒有人重新問過。**

## 🔒 佔用宣告：`main.py`（§3v 背景暖快取掛進排程區塊），2026-09-22

- **佔的是**：`if os.getenv("MOTRIX_DISABLE_SCHEDULERS") != "1":` 那個區塊裡
  **加一行** `geo.schedule_geocode_warm()` ＋ 兩行 import／註解
- **不動**：其他五支排程、雷達那段 log、任何 router 掛載、middleware
- **為什麼要動它**：VB8 釘「那支函式要被掛進排程」——
  🔑 不掛的話就是〈兩個都對而路不存在〉：函式寫好了而**沒有人叫它**
- ⚠️ `MOTRIX_DISABLE_SCHEDULERS=1` ⇒ 測試裡整批不跑
  ⇒ **這一行在開發機上永遠不會被執行**，正式機的證據要 A 去看
  `warm_status().lastRunAt` 會不會動

---

# 🛑 停手宣告（第二次，2026-09-22 09:58）

```
最後一個 commit   cac82b5d42138dea77fca89497b2c868e406fd2e
宣告時間          2026-09-22 09:58（本機）
工作樹            我的檔案全部已 commit
                  （只剩 C 的兩支測試檔是 modified —— 它還在改）
我最後寫入的檔    backend/routers/daily_tasks.py     09:53:22
                  backend/helpers/email_notify.py    09:53:22
```

**我不再寫入 `backend/` 與 `frontend/`，直到 A 說可以。**

## ⚠️ 打包前 A 要知道的兩件

1. **C 的測試檔正在編輯中**（`test_map_you_are_here` 的 `_draw_section`
   被刪掉而引用還在 ⇒ 6 題 `NameError`）。
   🔑 **那是 C 的工作樹，不是缺陷** —— 我量到的是它改到一半的狀態。
   ⇒ **等 C 報完再打包**，否則會拿到一個無法重現的紅燈。
2. `test_wa6` 與 `test_wa2[12]` **互相矛盾**（見下），我照 WA1／WA2 實作。

## 📌 這一輪做完的
`0e7194d` §3u（UA5 座標欄位／UA1-3c 金鑰遮蔽／UB 你在這裡）
`384a608` §3v（背景暖快取，五道防線）
`84b556c` §3x（Leaflet 0×0／自動開圖）
`f90595a` XA5（自動開圖的斷路器）
`cac82b5` §3w（提醒階梯 1/3/5/10/15…）

## 🔓 解除條件
A 說「可以動了」。**我自己不會解除。**

## 🔒 佔用宣告：`main.py`（§8 FX1a 啟動時把兩個開關的實際狀態印出來），2026-09-22

- **佔的是**：雷達那段啟動 log 旁邊**再加一段** GEO 的（目前只有雷達會印）
- **不動**：排程區塊、middleware、router 掛載、`_PUBLIC_API_PATHS`
- **為什麼**：FX1a 要的是「**這個行程實際拿到什麼**」。
  ⚠️ 而 `MOTRIX_GEO` 現在**完全沒有啟動痕跡** ——
  ☠️ 一台「以為開了而其實沒開」的機器，症狀是「地圖上沒有點」，
  🔑 而那與「地址查不到」「還沒暖快取」長得一模一樣。

## 🔒 佔用宣告：`main.py`（§8 FX21c 拿掉 `?token=` 的 middleware 旁路），2026-09-22

- **佔的是**：`main.py:329-333` 那個 `if path.startswith("/api/uploads/") and (...)`
  裡的 `token` 條件，以及上面那三行註解
- **不動**：`_PUBLIC_API_PATHS`、其餘 middleware 邏輯、`?pt=` 那一條
- **為什麼**：那條路讓**完整的 session token 走 query string** ⇒ 進 access log，
  ☠️ 而它**不是短效的**（`?pt=` 是 HMAC 簽章、1 小時、綁單一路徑）。
- **實查**：前端用 `?token=` 打 uploads **0 處**、用 `?pt=` **8 處**；
  `backend/tests/` 也沒有任何一支在用 ⇒ **一條沒有人走、而仍然打開著的路**

---

# 🛑 停手宣告（第三次，2026-09-22 12:07）

```
最後一個 commit   bf715d21130187bef0369279b9c24c50e8be1f3d
工作樹            乾淨（git status --porcelain 無輸出）
覆蓋率守門        8 passed（打包第一步會跑的那一支）
```

**我不再寫入 `backend/` 與 `frontend/`，直到 A 說可以。自己不會解除。**

## 這一輪（第三次停手之前）做完的
```
813827c  FX21  拿掉 /api/uploads 的 ?token=
3ffa7f6  FX1b  打包的「下一步」補上重跑排程工作
08748e1  FX22  掃碼登入的 challenge 改走 header，QR 網址改 fragment
cff77e2  §5    多據點（分公司）
9fad854  HC1   部署儀表板的防線搬到請求層
80eaac5  HC5   刪三支死碼＋健檢工具改用合成對照組
62bf3e5  FX24  SEND_UNKNOWN 保留標記＋記一筆
503bd15  HC6   32 個沒用到的 import → 0
292924b  HC2   requirements.txt 純 ASCII ＋ 第一次跑出相依漏洞掃描
3894358  §10   公司資料只有 superadmin 改得動，稽核記下改了什麼
```

## 🔒 佔用宣告：`frontend/static/sidebar.js`（§4 YB），2026-09-22

- **佔的是**：檔案開頭（IIFE **之前**）新增一支純函式 `acceptsSessionUpdate`
  ＋ 匯出；以及 `_refreshSession()` 裡 `:893`／`:903`／`:909` 那三行
- **不動**：其餘全部（選單建構、字級縮放、行動版側滑、旗標計算）
- **為什麼**：`:909` 的 `mods` **有**防護、`:903` 寫進 `localStorage` 的**沒有**
  ⇒ 🔑 當下那一頁自己恢復，**而存下來的值已經被洗掉** ⇒ **下一次載入才爆**。
  ☠️ 規格寫的「要載入兩次」就是**這個不對稱的指紋**。
- **為什麼放在 sidebar.js 裡而不是新開一個檔**：
  ⚠️ **53 個頁面載入 sidebar.js** ⇒ 新開一個檔要改 53 個 `<script>` 標籤，
  而漏掉一個的後果是那一頁**完全不更新權限**（fail-open，最糟的方向）。
  📌 C 明講「`sidebar.js` 我也收，匯出方式是 B 的決定」。

## 🔒 佔用宣告：`db.py`（§9 QL2 migration **v90**），2026-09-22

- **查證**：`db.py:104 CURRENT_VERSION = 89`、`_MIGRATIONS` 末筆 `_m089  # v89`；
  `docs/windows/` 裡 v90 沒有別人佔著
- **佔的是**：`CURRENT_VERSION 89 → 90`、新函式 `_m090_quotation_location`、
  `_MIGRATIONS` 末尾一筆
- **不動**：`_get_version`／`_run_migrations` 的流程、任何既有的 `_mNNN`
- ⚠️ **C 釘的是 `> 89` 不是 `== 90`** ——
  📌 釘等號的話，兩個視窗同時各加一個 migration 會讓那一題**紅在一個假的理由上**
  （〈兩人同時加 migration，git 不會衝突、只會在執行時撞版本號〉）
- ⚠️ **BR19**：migration 裡的據點導出邏輯要**inline**，
  不可以呼叫 `_migrated_locations()` 那種會演進的 helper

---

# 🟢 派工 · 2026-09-22 下午派工（停手解除，可以寫了）

> 上一包 `20260922_132359_e64a032` 已出，全量 **1658 passed / 53 skipped / 0 failed**。
> ⭐ **順序就是下面這個順序。做完一件再拿下一件，不要並行。**
> ⚠️ 每一件都要**等 C 的紅燈先到**（協定七步）。C 還沒寫到的，先做下一件。

## ① 版本紀錄 `VR1`～`VR5`（使用者今天親自提的，最優先）

規格：`STATE.md` §13。實查到的成因：
```
module_versions           361 列，最新 2026-09-15T19:10:00
version_manifest.json     358 筆，檔案 mtime = Sep 15 18:48
```
🔑 **它不是算出來的，是手寫的 JSON。9/15 之後沒有人寫。**

- `VR3` 補 2026-09-16 ～ 2026-09-22。**來源是 `git log --since=2026-09-16` 與 `STATE.md`
  這七天新增的節，不是記憶。** 一個模組一筆，不是一天一筆。
- `VR1` 把守門加進**打包流程**（不是只加一支測試）：
  manifest 最新日期 < 這一包最新 commit 日期 ⇒ **擋下來**。
- `VR5` 畫面頂端的「超過 14 天沒新紀錄」提示。
- `VR4` 先**列登記不要修**（manifest 與資料表差三列）。

## ② 備份保留 `BK2` `BK3` `BK5` `BK8` `BK9`

規格：`STATE.md` §12。使用者問的是「月的部分會保留多久」。

- `BK2` `company-profile-settings.html` 補上 `cloud_monthly_keep_days`（**0 = 永久**）
  與 `local_pre_update_keep`（**份數，不是天數**）。
- `BK3` 🔴 **PATCH 改成合併不要覆蓋** —— 現在設定頁按一次儲存會把這兩個欄位静静重設。
- `BK5` 🔴 `_monthly_backup()` 的 `.db` 複製失敗要跟 JSON 失敗同等：**不寫 `.done`**。
  理由：82 張表只有 45 張有 JSON，**剩下 37 張（含選型資料庫七類）只靠那份 `.db`**。
- `BK8` 畫面上要有一句話講完「永久保留哪些／會自動清哪些」。

## ③ 選單重整 `MN1` `MN3` `MN4` `MN5`

規格：`STATE.md` §14。使用者原話：
> 「業務內的簽核歷史、簽核佇列、簽核代理人這三項，移到工作內容」

- 搬家目標位置：`sidebar.js:704` 的 `sec('工作內容', ...)`。
- 來源：`sidebar.js:673` `674` 及簽核佇列那一行（在 `sec('業務')` 底下）。
- ⚠️ `MN1` **只搬位置，不動 `cQ` 這個顯示條件。**
- ⚠️ `MN3` `sidebar.js` 是鎖定檔 ⇒ **動之前先在這份檔宣告**。
- 🔴 `MN2`（改名）**你不要動** —— 使用者要選名字，A 已在問。先做搬家。

## ④ 地理編碼跨階短路 `GC3` `GC4` `GC5`

規格：`STATE.md` §15。☠️ **A9 從另一扇門回來了。**
`cached_only()` 跨階命中 ⇒ `_GeocodeBudget.locate()` 直接回傳 ⇒ **填了 Google 金鑰也不會升級已快取的 147 筆。**

## ⑤ 舊欠（前一輪已裁定，順序不變）

```
id 格式驗證 ^[A-Za-z0-9_-]{1,32}$   422 訊息要講出允許的型式；只驗新寫入
QL11 → QL12 → QL7 → QL5 → QL8 → QL9 → QL10 → QL13～15
FX3 2-5（剩下 14 個先標記再寄的點）
```

⚠️ **不要碰 666／6667，不要重啟伺服器** —— 那是使用者自己的動作。
