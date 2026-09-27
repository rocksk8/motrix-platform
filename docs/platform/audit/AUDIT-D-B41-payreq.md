# 稽核：B41 請款 L0（wip/b-payreq 88e7d1df）——registry／loader／core.migrations＋module_startup＋EM1（D，2026-09-28）

> 範圍：`git diff origin/platform...88e7d1df` 中的 L0／L1 啟動段（core/loader.py、core/migrations.py、core/registry.py、
> helpers/module_startup.py、main.py 兩處）與 EM1 凍結訊息。業務面（付款日、出納、挑案件）由 A 兩輪稽核過，這裡不重做。
> 第一輪 A：AUDIT-A-B41-payreq（d0158060）。只讀碼；探針與突變在拋棄式 worktree（detached 88e7d1df）跑，暫存已刪，`git status` 乾淨。

## 0. 結論

- **必修 1、建議 1、觀察 3。EM1 凍結訊息的改動成立。**
- 基準：`test_module_migrations`＋`test_migration_incomplete`＋`test_module_startup` 共 32 題，全部通過。
- 突變 7 個，紅 5、**存活 2**（B4、B6）：

| 突變 | 結果 |
|---|---|
| B1 載入不檢查 migrations 形狀 | 紅 |
| B2 未完成後同模組後面的版號照跑 | 紅 |
| B3 沒跑過也回空 dict | 紅 |
| B4 incomplete 的路徑不做 normcase | **存活** |
| B5 demo 未完成也下線 | 紅 |
| B6 main.py middleware 不查 demo 缺席 | **存活** |
| B7 未完成的模組不下線 | 紅 |

## 1. 必修

**PM1（必修）　一個 L2 模組的 migration 丟例外 ⇒ 整台起不來；被停用的模組的 migration 永遠不會被乾跑**

- 證據：
  - `run_all`（core/migrations.py:67）呼叫 `per[v](conn)` 時沒有接例外；`init_db`（db.py:761）與 main.py 的模組層 `init_db()`（:575）也都沒有接
  - loader 的不變式寫的是「載入失敗一律不載入＋記 ERROR，不讓伺服器起不來」（core/loader.py:5）。1.58 把 L2 的程式碼（模組 migration）放進啟動的必經路徑，卻沒有同一條保護
- 探針（拋棄式 worktree；scratchpad `probe_b41.py`）：登記 `aaa_mod` v1（丟 OperationalError）與 `zzz_mod` v1 ⇒
  - `run_all` 丟出 OperationalError
  - 排在後面的 `zzz_mod` 沒有跑
  - `incomplete(該庫)` 回 `{}`（「全部完成」的形狀，A 的 AB-S4 至今未修）
- 為什麼乾跑擋不住：只有**已載入**的模組會登記 migration（loader.py:148-149，這是設計）⇒ apply_update 乾跑時被停用的模組不會跑 ⇒ 日後在模組管理頁重新啟用、重啟時，才第一次對正式庫跑。這時如果丟例外：
  - autostart 迴圈會無限重啟
  - 停用清單存在 DB 裡，要從模組管理頁改，而頁面進不去 ⇒ 只能手動改 DB
- 修法（L0，CORE 1.58 同包）：
  - `run_all` 對 `core` 以外的模組逐支用 `SAVEPOINT` 包住。丟例外 ⇒ `ROLLBACK TO` 該 savepoint、記 `todo[module] = (v, "例外：<型別>: <訊息>")`、ERROR、`break` 該模組、繼續下一個模組
  - `core` 的例外照舊往上丟（core 不完整就不該起來）
  - 效果：與「回原因字串」走同一條路，main.py 經 `fail_incomplete_modules` 讓該模組下線，其他模組與服務照常；乾跑經 `incomplete` 非空判失敗；AB-S4 一併關閉
  - 補題：①丟例外的模組 ⇒ incomplete 有它、版號不前進、後面的模組照跑、`run_all` 不丟；②core 丟例外 ⇒ 照舊丟；③savepoint 讓丟例外之前的寫入被撤回（先 CREATE TABLE 再丟 ⇒ 表不在）
  - ⚠ 模組 migration 自己呼叫 `conn.commit()`（例：case 0001 的 :18）會讓 savepoint 失效。`test_module_migrations` 的「migration 檔不准 import」守門旁邊，建議加一條「不准 commit」（run_all 負責 commit）；或在 CORE-SPEC §6 寫明「先檢查後動手、最後才 commit」並由題目守
- 另建議（不擋關閉）：乾跑工具（H12 migrate_like_startup）加一個選項，把**被停用的模組**的 migration 也登記、在副本上跑一次，專門找「日後重新啟用才會炸」的那一種

## 2. 建議

**PS1　main.py 的 demo 缺席接線沒有題**
- 突變 B6（`if _demo_why:` 改成 `if False:`）存活：`test_module_startup` 只驗 `demo_absent_reason` 函式本身，沒有驗 middleware 真的呼叫它、回 404
- 建議：用 TestClient 補一題——demo token 打到只有 demo 庫未完成的模組前綴 ⇒ 404＋原因；正式 token 打同一個路徑 ⇒ 照常（反向控制）

## 3. 觀察

- **PO1**：突變 B4（`_norm` 拿掉 normcase）存活。main.py 呼叫 `init_db` 與 `fail_incomplete_modules` 用的是同一個路徑字串，所以目前對得上。但對不上時，`incomplete` 回 None，而 `fail_incomplete_modules` 對 None 的處理是「不算」⇒ **模組照常上線**（fail-open），與乾跑工具「None＝失敗」的方向相反。建議補一題「大小寫不同的路徑查得到同一份」
- **PO2**：EM1 的新訊息「附件已上鎖（發票可以直接補上傳）」在 `_guard_files_editable`（case_extra_expenses.py:692）發出，而這一步在 403 權限檢查之前（:716）。沒有補發票權限的人上傳其他類附件時，也會看到「發票可以直接補上傳」，改傳發票後才被 403。建議改寫成「發票可由填寫人、管理員或出納補上傳」；要不要改由 B 決定，EM1 凍結清單要跟著更新
- **PO3**：A 的 AB-O1（`_REGISTRY` 是行程全域的）在 H12 的 migrate_like_startup 一個行程只載一次，不受影響；PM1 修法新增的逐模組 savepoint 也不受它影響

## 4. EM1 凍結訊息（主持指定複核）

- 改動：`_UNTOUCHED` 裡 case_extra_expenses 那一句加上「（發票可以直接補上傳）」，並把「補憑證」改成「補其他憑證」。原句保留在註解，註明依據是 CORE-SPEC 請款流程的使用者裁示②
- 行為對照：`_guard_files_editable(row, kind)` 在已核准時只放行 `kind == "invoice"`；刪除一律擋 ⇒ 訊息與行為一致
- **判定：成立。** 這是使用者裁示帶來的行為變更，不是順手改字；更正格式也符合（留原句）。措辭建議見 PO2

## 5. 重現

```
git worktree add --detach D:\MOTRIX-PLATFORM-D14m 88e7d1df
cd D:\MOTRIX-PLATFORM-D14m\backend
D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe -m pytest tests/platform/test_module_migrations.py tests/platform/test_migration_incomplete.py tests/platform/test_module_startup.py -q -n 2 --basetemp=%TEMP%\motrix-pytest-d-b41
# PM1 探針：core.migrations.register 兩個模組（前者丟例外），對 %TEMP% 的臨時庫 run_all，看例外、後者有沒有跑、incomplete
```

## 6. 第二輪複核：wip/b-payreq 1a544510（範圍 88e7d1df...1a544510）（D，2026-09-28）

> 四個題檔共 76 題通過；突變 7 個全紅（P1 模組例外往上丟、P2 不 ROLLBACK TO、P3 拿掉自己 commit 的防線、P4 主庫 None 改回 fail-open、P5b demo 庫 None 改回不算、P6 middleware 不查 demo 缺席、P7 core 也吞例外）。

| 項目 | 結果 | 判定 |
|---|---|---|
| PM1 | core 以外逐支 SAVEPOINT；例外或回原因 ⇒ ROLLBACK TO、記進 incomplete、不往上丟；core 的例外照舊往上丟。migration 自己 commit 讓 RELEASE 失敗時，記成「違規」的未完成、不往上丟（B 以突變 PM1c 自己抓到並補上）。repo 內「不准自己 commit」有守門；case 0001 拿掉了 `conn.commit()`。`init_db` 在 `run_all` 之前沒有提早 return（讀碼），所以 PO1 的 fail-closed 在正常啟動不會誤觸 | 成立 |
| PS1 | TestClient 驗 middleware 對 demo token 回 404＋原因，正式 token 照常（P6 紅） | 成立 |
| PO1 | 主庫查不到紀錄 ⇒ 所有已載入模組下線；demo 庫查不到 ⇒ demo 模式全部明說缺席（P4、P5b 紅） | 成立 |
| PO2 | 訊息改成「發票可由填寫人、管理員或出納補上傳」，EM1 凍結清單同步更新 | 成立 |
| 契約題更正 | 回傳 Cursor 的 `lambda c: c.execute(...)` 從 1.58 起會被判成「寫錯＝未完成」。契約題已改成明確回 None，CHANGELOG 補了更正、原句保留。產品碼 grep：模組 migration 只有 case 0001（`up` 回 None），沒有 lambda 寫法 | 成立。影響只在 repo 外的第三方模組，而且看得見（ERROR、模組下線），不會靜默 |

**D2-O2（觀察）**：PO1 改成 fail-closed 之後，只要 `PRAGMA database_list` 回的路徑與 main.py 傳入的路徑正規化後對不上，**所有模組都會下線**。後果比先前的 fail-open 大，但方向正確，訊息也帶著路徑。正式機的路徑是普通的本機路徑，目前沒有已知的誤觸情境；日後若支援 subst 磁碟、junction 或 UNC 路徑安裝，要先驗這一點。

### 關閉紀錄（標準格式，PLAYBOOK §E-6）

- ✅ PM1 關閉（1a544510）——模組 migration 逐支 SAVEPOINT，例外與自己 commit 都記成未完成、不拖垮整台；core 照舊往上丟
