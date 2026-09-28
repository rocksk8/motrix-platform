# 稽核：開關誤報＋模組健檢編碼（A；wip/a-switch-warn aec09a2e、wip/a-module-apply-ps1-2 844268be）（D，2026-09-28）

- **結論：兩件都放行，必修 0；觀察 1。** 這也關掉第十八班最終審的 T18F-O2（「開關沒有生效：MOTRIX_GEO」每次誤報）

**① apply_update 開關檢查（aec09a2e）**
- 根因成立：開關那一行在 main.py import 時印，早於「Uvicorn running on」；舊檢查只掃後者之後 ⇒ 永遠看不到（T14／T16／T17／T18 的演練 log 都有這個誤報）
- 新起點＝最後一次「Uvicorn running on」往前最近的「MOTRIX ERP starting」：
  - 這一行由 autostart.bat 寫入 server.log；repo（aec09a2e）、正式機現況（3e061d6f）、822286ed 的 autostart.bat 都有，而 apply_update 會保留正式機自己的 autostart.bat ⇒ 正式機上找得到
  - 演練 server.log：起點到「Uvicorn running on」約 32 行，`-Tail 200` 足夠
  - echo 那一行的日期是 cp950 位元組（混在 UTF-8 檔裡），但錨點是 ASCII，以 `-Encoding UTF8` 讀仍然比得到
- 找不到起點 ⇒ `$null`，印「驗不到，不代表生效」，不退回整段 tail（避免回滾後檢查吃到上一個行程的那一行而假綠）✔
- D 在拋棄式 worktree 跑 `test_apply_update_startup_range_2026_09_28.py`：7 passed（題目實際以 PowerShell 執行腳本的函式）

**② 模組 ps1（844268be）**
- `Get-LogCheck` 改用 UTF-8 讀＋同一支 `Get-StartupRange`；`Get-StartupRange` 列入 `SHARED` 逐字守門 ✔；沒有起點 ⇒ 健檢判「驗不到」（不當通過）
- D 跑 startup_range＋模組 ps1 兩個題檔：45 passed、4 skipped（2 格等 B55 的 §10、2 格等 E4 的 Invoke-CompanySetupCli，原因都寫明）

**觀察**
- **SW-O1**：腳本版本 aec09a2e 用 `2026-09-28j`，E4 已用 `28i`（段①）⇒ 兩線合流時 `$ApplyScriptVersion` 與 `apply_update.version.json` 會衝突；合流那一班要取一個新值，並重算 version.json 的雜湊（AH-O7）
