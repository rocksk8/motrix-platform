# 稽核：C 的案件存取守門下沉 L1 `helpers/case_access.py`（合回前稽核）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。**合回前稽核**，搭第四班列車。只審新版（CORE-SPEC 35014aaa）。
> 對象：`origin/wip/c-case-access` `7c056468`（`920a83db` 下沉、`7c056468` UNIT-INDEX）。規格：DEPENDENCY-MAP §3.2（主持裁示 2026-09-26）。
> 稽核樹 `D:\MOTRIX-PLATFORM-D2`（detached），Python `D:\MOTRIX-PLATFORM\.venv312`（只用、未改）。
> 分級：**必修**／**建議**／**觀察**。關閉規則：被稽核者回覆後，由 D 確認才關。
> 縮寫：`CA`＝`backend/helpers/case_access.py`、`TL`＝`backend/tests/platform/test_case_access_l1.py`。

## 0. 結論

- 下沉本身正確：規則只有一份（`helpers.quotations`、`helpers`、`row_access` 拿到的是同一個物件），IDOR 守門有 API 層的題目守（D 突變 CA2「擋下改成放行」、CA3「擁有者規則失效」各讓 4、7 題紅）。M03／M04／M05／M10 對 M01 的 import 邊少了 4 條。
- 主持點名的兩件事：
  1. **「M01 不在時回 404，不可以放行」：只有「案件表不存在」時成立，而案件表在每一個安裝裡都存在** ⇒ 必修 CA-M1。
  2. **「L1 讀 quotations 的例外守門是否嚴密」：現有的 L1 檔都有抓到（與 dep_scan 比對一致），但對之後的新寫法有 5 種漏網** ⇒ 建議 CA-S1。
- **必修 1 項**。建議 2 項、觀察 1 項。

## 1. 驗收

| 項目 | 驗收 | 證據 |
|---|---|---|
| 同一份規則 | ✅ | `test_same_rule_everywhere` |
| M03／M04／M05／M10 不再依賴 M01 | ✅ | `l2_import_baseline.json` 刪 4 條邊 |
| IDOR 守門（403） | ✅ | D 突變 CA2（CA:107-109 擋下改成放行）⇒ `test_module_permission_fixes_2026_09_13::test_case_action_items_not_readable_by_outsiders` 等 4 紅；CA3（owner 規則永遠成立）⇒ 7 紅 |
| M01 不在 ⇒ 404 | ⚠ | CA:96-106 只在 `OperationalError`（表不存在）時 404；突變 CA1 ⇒ `test_without_m01_access_is_404_never_allowed` 紅。但見 CA-M1 |
| L1 新增讀 quotations 只准經 case_access | ⚠ | TL 以正則 `\b(FROM|JOIN)\s+quotations\b` 計數；見 CA-S1 |
| L1 行為改變寫 CHANGELOG | ✅ | `backend/core/CHANGELOG.md` |

## 2. 發現

### 必修

**CA-M1　「M01 不在 ⇒ 404」的判準是「案件表不存在」，而這張表在每個安裝都存在**
- 位置：CA:96-106；規格 DEPENDENCY-MAP §3.2「M01 不在（案件表不存在）⇒ `guard_case_access` 一律 404」；TL:74 的反向控制用 `sqlite3.connect(":memory:")`，也就是一個**空庫**。
- 事實：`db.py:447` 的 `init_db` 無條件 `CREATE TABLE IF NOT EXISTS quotations`（凍結的 V9 schema）。M01 被停用、未授權，或之後搬進 `modules/` 而不在安裝包裡時，**表照樣存在、資料照樣在** ⇒ `guard_case_access` 照 owner 規則放行，M03／M04／M05／M10 仍然可以依 quote_no 讀到案件。
- 為什麼是必修：主持的條件是「M01 不在時回 404，不可以放行」。現在的實作把「M01 不在」換成了一個在真實安裝裡不會發生的條件，而反向控制題用的是測試自己擺的空庫，所以綠燈證明的是另一件事（〈假綠燈：夾具是自己擺的〉）。
- 建議修法：
  - 判準改成「M01 有沒有載入」，例如 `registry.is_loaded(<M01 key>)`；M01 還沒搬進 `modules/` 的這段期間，可以用它的模組啟停狀態或授權判定。
  - 反向控制題改用真實 schema 的庫（`client` 夾具），在「表在、M01 不在」的情況下驗 404。
  - DEPENDENCY-MAP §3.2 的定義同步更正，並保留原句。
- 範圍說明：M01 目前還沒搬進 `modules/`，所以今天不會真的發生「M01 不在」；但 §3.2 是寫給之後的搬遷用的契約，一旦 M01 搬家就會生效。

### 建議

- **CA-S1　「L1 新增讀 quotations」守門的正則漏掉 5 種寫法**：D 直接呼叫 TL 的 `readers()`：
  - 抓得到：`JOIN quotations`、子查詢 `IN (SELECT … FROM quotations)`。
  - **抓不到**：逗號 join `FROM cases c, quotations q`、加引號的表名 `FROM "quotations"`、隱式字串串接 `"SELECT * FROM " "quotations"`、f-string 變數 `f"… FROM {T}"`，以及寫入 `UPDATE quotations`／`INSERT INTO quotations`。
  - 現況：D 用 repo 既有的 `dep_scan.sql_tables(string_chunks(...))` 對 L1 的 58 個檔重算，「哪些檔讀 quotations」與正則的結果一致，基線沒有低估。另外，`db.py`（9 處）、`pdf_gen.py`（1 處）會**寫入** quotations，這一點守門沒有看。
  - 建議改用 `dep_scan.sql_tables`（與 dep_graph 同一個判準，不必再維護一份正則），並把寫入一起納入基線。
- **CA-S2　`OperationalError` 全部都當成「表不存在」**：CA:101 接住任何 `sqlite3.OperationalError`，資料庫被鎖（`database is locked`）也會回「報價單不存在」的 404，使用者會以為單號打錯。建議只在訊息是 `no such table` 時回 404，其餘照舊丟出（503 或 500）。

### 觀察

- **CA-O1　守門只掃 modules.json 的 L1 單位**（router、helper、backend 頂層檔），L0 的 `backend/core/` 不在範圍內。D 查過：`core/` 裡只有 `txn.py` 在註解中提到 quotations，沒有實際讀取。

## 3. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | D 確認 |
|---|---|---|---|
| CA-M1 | 修正：判準改成「M01 有沒有登記 `case.present`」（新串接點 IP-15；M01 在 `routers/quotations.py` 匯入時登記，搬進 modules/ 後改寫進 ModuleSpec ⇒ 停用、未授權、不在包內就沒有登記），不看表。M01 不在 ⇒ `guard_case_access` 404、`case_access_allowed` False，表與資料在、超級管理員也一樣。反向控制改用真實 schema（`client` 夾具、案件列在、擁有者＋超級管理員）：`test_without_m01_access_is_404_even_though_the_table_and_row_exist`。DEPENDENCY-MAP §3.2 原句劃掉並加〔更正〕。突變 4 項皆紅（guard／allowed 不看、判準改回、M01 不登記） | wip/c-case-access a82da8ec || ✅ 2026-09-26 06:38 D 在 `wip/c-case-access-2` a82da8ec 確認：判準改看 `case.present` 登記；loader 對停用／未授權模組不 import（`core/loader.py::load_all`）⇒ 搬進 modules/ 後登記也不會發生，判準成立。D 突變 6/6 紅（永遠當在、allowed 不看、guard 不看、空登記當在、M01 不登記〔另帶紅 test_module_permission_fixes 8 題〕、鎖也當查無）；基準 5 檔 106 passed ⇒ **關閉** |
| CA-S1 | 修正：守門改用 dep_scan 的 `string_chunks`＋`sql_tables`（與 dep_graph 同一份判準），寫入一併納入基線（db、pdf_gen 為 rw）。dep_scan 也不認得逗號 join ⇒ 守門另補一條；加引號、隱式串接、寫入 dep_scan 本來就認得。f-string 插入的表名靜態無從得知，寫明為已知限制。解析器題 9 例（含 2 個反向控制）；突變 2 項皆紅（不看逗號 join、寫入不算） | wip/c-case-access a82da8ec || ✅ 關閉。D 探測：f-string 內的靜態表名、`+` 串接、f-string 寫入都抓得到（解析器題未列，建議補進參數）；抓不到的是表名放變數與大寫 `Quotations`（SQLite 表名不分大小寫）⇒ 記觀察 CA-O2，不擋 |
| CA-S2 | 修正：只有 `no such table` 當成查無此案（404）；其他 `OperationalError`（例 `database is locked`）照樣丟出。題：`test_missing_table_is_404_and_a_locked_database_is_not`；突變 1 項紅 | wip/c-case-access a82da8ec || ✅ 關閉（D 突變 CM4「鎖也當查無」紅） |
| CA-O1 | 採納：守門範圍加上 L0 `backend/core/*.py`（目前沒有讀取，列入掃描後照樣綠） | wip/c-case-access a82da8ec || ✅ 關閉 |

## 4. 關閉確認後的觀察（D，2026-09-26 06:38）

- **CA-O2　守門的兩個盲點**：①表名放在變數裡（`t="quotations"; f"… FROM {t}"`）；②大小寫不同（`FROM Quotations`，SQLite 視為同一張表）。這兩種寫法 `access()` 都回空。①是靜態掃描本來就做不到的；②建議在 `dep_scan.sql_tables` 比對時忽略大小寫（會影響 dep_graph，由 B 決定）。
- **CA-O3　模組 import 成功但 spec 驗證失敗的情形**：M01 搬進 modules/ 之後，如果仍然在 import 時登記 `case.present`，那麼「import 成功、`MODULE` 缺漏或 key 不符 ⇒ STATE_FAILED」的時候，登記已經留下了 ⇒ `case_module_present()` 會回 True。IP-15 已寫明「改寫進 `ModuleSpec.providers`」，照這樣做就沒有這個問題；M01 搬遷的稽核會驗這一點。

## 5. c-case-access-3 複核（D，2026-09-26 07:58）

- 對象：`origin/wip/c-case-access-3` `0da9d647`。主持裁示只留一個訊號：`case_module_present()` 改看 A 的 `case.access`（`helpers/quotations.py:556` 登記），`case.present`（IP-15）刪除；新增 `test_both_paths_agree_when_m01_is_absent`（L1 guard 與網路規劃書路徑同為 404）。
- D 突變：`case_module_present` 恆 True、空登記當在 ⇒ 兩項都紅（2 failed：原 404 題＋兩條路一致題）⇒ **CA-M1 維持關閉**。
- **CA-O4（觀察，CA-O3 變成必要條件）**：`case.access` 在 `helpers/quotations.py` 匯入時登記，而這支檔案被 L1 的 `pdf_gen.py`、`routers/system.py`（以及 M05、M08 的 router）匯入 ⇒ 只要這些檔被載入，訊號就一定亮。現在 M01 拿不掉，所以沒有影響；但 M01 搬遷時必須①改由 `ModuleSpec.providers` 登記（CA-O3），②切斷 L1 對 `helpers.quotations` 的匯入，否則「M01 不在 ⇒ 404」會退回 CA-M1 修正前的狀態（照擁有者規則放行）。建議併入 ROADMAP 的 M01 條目。

## 6. 事後稽核：第六班列車在 L1 讀 quotations 基線加的兩筆（D，2026-09-26 12:38）

對象：`test_case_access_l1.KNOWN_L1` 新增 `helpers/receivables.py`、`routers/map_points.py`（列車 a51bf3b9；主持裁示「有到期條件的例外」，RUN-PLAN §6 12:25）。

**①是不是原有讀取改了歸屬：是。**
- `receivables.py`：與第五班合回點 a6dc4be6 的 `routers/reports.py`（M08）逐函式比對：`collect_income_items` **完全相同**；`collect_tax_invoices` 只差一行四捨五入函式名（`_round_half_up` → `round_half_up_invoice`），讀 quotations 的查詢不變。
- `map_points.py`：a6dc4be6 與現在的 quotations SQL **完全相同**（3 行）；modules.json 歸屬由 **M08 → L1**（地圖歸 L1 的使用者裁示）。
⇒ 兩筆都是既有讀取；因為歸屬改成 L1，才進入這道守門的掃描範圍。

**②到期條件夠不夠具體：不夠（建議 CA-S3）。**
- 裁示說兩個到期條件「寫進 ROADMAP 的 M05、M01 條目」：D 查 origin/platform 73d8ba63 的 ROADMAP，receivables 在 A8b／M01 條目有提到（「M05 搬遷時收回」），但**沒有「移出本基線」**；map_points 與 `case.summary` 在 ROADMAP **完全沒有**。
- `case.summary`（M01-PLAN §3-4）：**M01-PLAN 不在 repo 裡**（只在 RUN-PLAN 提到「C 的 M01-PLAN §3 順序」），到期條件指向一份看不到的文件。
- **沒有機械式的到期**：`excess()` 只擋「新增」；基線條目的檔案不再讀 quotations（或不再是 L1 檔）時，這一筆會安靜留在基線上。M05 收回 receivables、M01 公開 case.summary 之後，沒有任何守門會紅，只能靠有人記得。
- **CA-S3（建議）**：①兩個到期條件寫進 ROADMAP 的 M05、M01 條目，寫明「完成後自 `test_case_access_l1.KNOWN_L1` 刪除」；②`case.summary` 的定義寫進 INTEGRATION-POINTS（預留 IP）或 ROADMAP，不要只指向 M01-PLAN；③守門加一條「基線條目必須仍是 L1 檔、而且仍讀或寫 quotations」，過期即紅（比照 core-only 已知紅清單的「轉綠未刪 ⇒ 紅」）——這樣到期條件就會自己觸發。
- 〔12:42 D 確認：wip/h-cas3 02f8f521 加 `stale()`＋`test_known_l1_baseline_is_not_stale`（不再是 L1 檔／不再讀寫／權限縮小 ⇒ 紅）＋ROADMAP 寫明兩筆到期條件與 case.summary 定義。基準 17 passed；D 突變 ST1（stale 恆空）、ST2（不檢非 L1）、ST3（基線加不存在的檔）、ST4（權限寫大）⇒ 皆紅 ⇒ **CA-S3 關閉（02f8f521）**。M01-PLAN 等步驟表由 C 放進 docs/platform/plans/（主持已派）〕

