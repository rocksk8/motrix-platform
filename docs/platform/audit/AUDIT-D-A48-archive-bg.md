# 稽核：A48（B54-S2）每日／每週備份第一輪移到背景（wip/a-archive-bg 1ac3ee48，基底 0af16ad1）（D，2026-09-28）

- **結論：放行，必修 0；建議 1、觀察 2。** 這關掉 D 在第十六班留下的 B54-S2
- D 在拋棄式 worktree 跑 `test_archive_schedule_async_2026_09_28.py`：6 passed（含子行程真的 `import main`，所有排程工作都睡 45 秒時 import 仍在時限內）

**讀碼**
- `_schedule_daily`／`_schedule_weekly` 立即返回；第一輪在背景 Timer（每日 30 秒、每週 90 秒）；工作包在 try、**重排在 finally**（原本重排在工作之後且沒有 try ⇒ 丟一次例外排程就靜默停掉，這一點修得好）✔
- 每日第一輪先 `_ensure_archive_dirs()` 再 `_daily_backup()`＋`_cleanup_sessions()` ✔
- `main.py` 不再同步呼叫 `_ensure_archive_dirs`：依它自己的 docstring，各寫入端本來就 `makedirs(exist_ok=True)`，這支只負責「提早告警雲端碟不見」⇒ 延後 30 秒不影響任何寫入 ✔
- 每日（「每日備份/」）與每週（「週備份/」）原本在啟動時依序同步跑，現在各自在背景執行緒。雲端慢到每日第一輪超過 60 秒時兩者會重疊；兩者寫不同資料夾、各自開 DB 連線讀資料，唯一共用的是告警檔 `_write_backup_alert`，重疊不會壞資料（觀察 AB-O1）

**建議**
- **AB-S1　子行程題別寫開發機樹裡的帳密檔**：子行程 `import main` 時，`init_default_admin()` 對暫存庫建管理員，並把 `backend/.initial_admin_credentials.txt` 寫在**這棵樹**（`_paths.INITIAL_ADMIN_CREDENTIALS` 沒有被導到暫存）。D 在拋棄式 worktree 跑完就多了這個檔；共用主樹 `D:\MOTRIX-PLATFORM\backend\.initial_admin_credentials.txt` 的 mtime 是今天 23:07，與這類題目的執行時間吻合 ⇒ 開發機的初始帳密檔會被換成暫存庫的內容（被 git 忽略，不會進 commit；只影響開發機）。B54 的 `test_geocode_warm_async` 是同一種寫法。建議兩題的子行程腳本都把 `INITIAL_ADMIN_CREDENTIALS`（與 logs 目錄）一起導到 `_tmp`

**觀察**
- **AB-O1**：見上方「每日與每週重疊」；若日後兩者要共用暫存檔或鎖，要加一把鎖
- **AB-O2**：A 回報 `tender_radar/source.py:1312` 的註解（「不可以抄 archive._schedule_daily 的形狀」）修完後已不成立；那是 L2 檔，由模組擁有者更新
