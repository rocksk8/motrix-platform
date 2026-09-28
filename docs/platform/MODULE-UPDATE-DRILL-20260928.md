# 單一模組更新包演練報告（B55 S6，2026-09-28～29）

> 設計：docs/platform/MODULE-UPDATE-DELIVERY.md §7。工具：`tools/platform/drill_module_apply.py`。
> 正式機條件：排程開（不設 `MOTRIX_DISABLE_SCHEDULERS`）、`MOTRIX_GEO=1`、有待定位地址（塞 3 筆標案機關）、本公司資料已依 COMPANY-SETUP-GATE 正式路徑設定（最高管理員改密碼 → 存檔並「確認本公司資料」→ status configured、developer=false）。`MOTRIX_TENDER_RADAR` 關（不連政府網站）。
> 演練安裝：`%TEMP%\motrix-drill-b55\<時間>\install`（路徑不含 V9.0），埠 6755；套用腳本是演練副本，相對正式版**只改寫 `$ProdRoot`、`$Port` 兩行**（工具逐行比對，第 33、34 行）。

## 1. 最終結果

| 演練 | 演練樹 | 期待 | 結果 | 報告 |
|---|---|---|---|---|
| A 成功 | 01f2b0d6（B 7523f22f＋A 844268be＋E4 e71e904d＋drill-only 簿記） | success／applied、新版已載入 | ✅ **success／applied／up**，16.8 秒；`tender_radar 1.3.4 已載入`；套用後本公司資料檢查 configured | `%TEMP%\motrix-drill-b55\20260928_234621.report.json` |
| B 自動回滾 | d6d5ed49（同上＋B 34abcaa9） | module_unhealthy_rolled_back／restored | ✅ **module_unhealthy_rolled_back／restored／up**，68.3 秒；模組與頁面雜湊逐一等於套用前；結束時服務健康 | `…\20260928_235915.report.json` |
| C 乾跑擋下 | 1b88e9cf（B 9eb938a7＋A 3a852cdc＋E4 e71e904d） | migration_dryrun_failed／not_applied | ✅ **migration_dryrun_failed／not_applied**；安裝未動、服務健康 | `…\20260928_215743.report.json` |

- **A 的完整鏈**：ship（ship_tier 判第②級＋第②級測試 2379 passed）→ 演練金鑰簽章發布 → stage → verify（kind=module，已安裝 module_update 的 preflight ok，notes「tender_radar 1.3.3 → 1.3.4」）→ ps1：身分 → 預檢 → 本公司資料預檢 → DB 快照 → 疊加樹乾跑（OVERLAY_OK、MODULE_LOAD_OK）→ 停服 → 換檔 → 重啟 → 健檢（module_states.json＋server.log 兩道）→ 本公司資料套用後檢查 → success。
- **B**：tender_radar `__init__` 只在「uvicorn 已載入」時丟例外 ⇒ 乾跑（沒有 uvicorn）過得了；真的啟動時載入失敗、ping 照樣成功 ⇒ 健檢第一道 `STATES_FAIL tender_radar 是 failed（預期 loaded）` ⇒ 停服 → module_update rollback（回到 1.3.3）→ 兩個庫先另存再還原 → 重啟 → 驗舊版已載入 → restored。
- **C 不在最終樹重跑的理由**：乾跑在停服之前；19eda14c／844268be 改的是回滾拒絕碼處置、interrupted 分流、停用中模組拒絕更新、健檢讀 log 的編碼與範圍——都不經過 C 走的路（預檢 → 快照 → 乾跑失敗即結束）。

## 2. 演練抓到的缺陷（全部已修）

| # | 在哪 | 缺陷 | 真因 | 修 |
|---|---|---|---|---|
| 1 | ship_tier（B） | 演練工具先匯入了安裝目錄的 `core` ⇒ `from core import paths` 拿到那一份 ⇒ 頁面目錄算到 repo 外、ship_tier 匯入就失敗 | 模組快取＋sys.path | 以檔案路徑載入本 repo 的 core/paths.py（64f0c920；題＋突變） |
| 2 | module_update.manifest_lines（B） | 逐行解析 version_manifest ⇒ 較舊的多行條目丟例外（第②級測試已全綠之後才失敗） | 假設「一行一筆」，實際檔案前段一行一筆、舊條目跨多行 | 解析整份 JSON 取新條目、各輸出一行（0cd2fe08；題） |
| 3 | 演練工具（B） | 清除失敗時 rmtree 先刪了結果檔 ⇒ 報告遺失 | 〈遞迴刪除失敗≠沒刪〉 | 先寫報告到目錄外、清除重試不丟例外（0d13ae26） |
| 4 | apply_module_update.ps1（A 的 S5） | 健檢把「已載入」判成沒有 ⇒ 每次套用都自動回滾 | **PS 5.1 `Get-Content` 沒帶 `-Encoding`，以 ANSI 讀無 BOM UTF-8 的 server.log，中文比對不到**（A 實測）。〔B 當時誤判為「錨點在 Uvicorn running on 之後」，已在設計 §1.3 兩次更正、原文保留〕 | A：一律 `-Encoding UTF8`＋Get-StartupRange（844268be） |
| 5 | module_update.run_ship_tests（B） | 第②級閘門只回「2 failed」 ⇒ 要重跑十幾分鐘才知道是哪兩題 | 沒收 `-rf` | 列出失敗題名（7523f22f；題） |
| 6 | 演練工具（B） | 同一安裝連續跑 A、B：B 的版本號與 A 相同 ⇒ preflight not_higher、B 沒跑到回滾 | 版本號以 repo 為底，沒看安裝目前版本 | 以演練安裝目前版本為底再升（34abcaa9；題） |

## 3. 列車要注意（演練樹用 drill-only commit 處理、不推）

- **A（a-module-apply-ps1 系列）與 E4 同搶 core 1.67**：CHANGELOG 兩段同號（`test_changelog_sections` 紅），合流時要重新取號；演練樹暫改 A 那段為 1.68＋CORE_VERSION 1.68＋重產 L1 快照。
- **「部署工具」兩筆未出貨條目**（2026-09-28l、m）違反 VR3：合流時合成一筆。
- **apply_update.ps1 的 `$ApplyScriptVersion`**：A 844268be 為 `2026-09-28j`、E4 為 `2026-09-28i`，內容兩邊都改過 ⇒ 合流時定版號並重算 `apply_update.version.json` 的 sha256（演練樹暫取 j、依合併後內容重算 a898d7e2…）。
- 第②級測試（A）以合流後的樹實跑：2379 passed、4 skipped（處理完上面三件之後）。

## 4. 清理

- 每場演練結束：服務停止（taskkill /T）、演練 worktree 移除、演練目錄刪除（報告 json 留在 `%TEMP%\motrix-drill-b55\`）。
- 演練樹 `D:\MOTRIX-PLATFORM-B55-drill3`（本機、不推）保留到 D 最終稽核後刪。
