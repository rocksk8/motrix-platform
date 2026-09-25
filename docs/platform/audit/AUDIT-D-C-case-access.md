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
| CA-M1 | | | |
| CA-S1 | | | |
| CA-S2 | | | |
| CA-O1 | | | |
