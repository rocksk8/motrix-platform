# D7 最終轉移升級驗證報告

> 正式 D7 在 D1～D6 完成後執行（RUN-PLAN §3），用 `tools/platform/final_drill.py` 產生結果。
> 下面「預演」是 2026-09-26 用同一支工具、在 D1～D6 完成前跑的；正式執行時保留預演段落，在上面補正式結果。

## 正式執行

（待 D1～D6 完成後執行）

## 預演（2026-09-26，C）

- 來源：`C:\Users\hichan\Desktop\MOTRIX-ERP`（V9 開發目錄，只讀；結束後 `git status` 乾淨、沒有 -wal／-shm）。
- 演練目錄：`D:\MOTRIX-FINAL-DRILL-REHEARSAL`（跑完已刪，含 source-backup——預演不保留；正式 D7 保留到使用者回來）。
- 新版程式：`git archive origin/platform`（第 4 次 cdf41cc0、第 5 次 8efb5f15）。不是部署包；正式 D7 用 `--package`。
- 共跑 5 次；前 3 次各抓到一個問題，修完才跑到底；第 5 次依稽核 D K-M1 改順序重跑：

| 次 | 停在 | 原因 | 處置 |
|---|---|---|---|
| 1 | 4a 預檢 | V9 開發機有未處理的備份告警（「找不到雲端備份路徑」：開發機沒有掛雲端） | 工具在**演練複本**裡封存告警，內容寫進報告；正式機升級前仍要由人處理 |
| 2 | 4c 轉換 | 工具沒寫 `backup_verify.json`（轉換只認已驗證的備份） | 工具補寫（兩次備份都寫） |
| 3 | 4d 驗證 | 🔴 新版啟動後「改寫了既有設定」`security.last_weak_pw_scan`／`last_unlock_pw_scan`。這是每日掃描的節流日期，新版一啟動就寫今天；真實庫是舊日期 ⇒ 驗證不過 ⇒ **正式機升級會被判失敗而回滾**。合成演練的庫是新建的、日期本來就是今天，所以一直沒看到 | `core.upgrade.RUNTIME_STATE_SETTINGS`：只有這兩個鍵、值是日期且沒有往回走才放行；守門要求 startup.py 寫入的設定鍵都要分類（wip/c-d7 a75aaaf8，突變 3 項皆紅） |
| 4 | — | 跑到底（舊順序：先只回程式、再完整回滾） | 稽核 D K-M1：完整回滾用的是**第二份**備份（已轉換過一次的庫），沒有驗到「還原回原始 V9 庫」 |
| 5 | — | 跑到底（K-M1 新順序，見下表） | — |

第 4 次結果（總計約 3.7 分鐘）：

第 5 次（K-M1 順序；完整回滾用第一份備份，並在 V9 啟動前比對與原始庫的邏輯內容）：

| # | 步驟 | 結果 | 耗時（秒） | 摘要 |
|---|---|---|---|---|
| 1 | 備份來源（唯讀） | ✅ | 6.3 | 4 個資料庫、821 個資料檔 |
| 2 | 建演練安裝目錄 | ✅ | 9.4 | 1,844 個檔；開發機舊告警已封存 |
| 3 | 取新版程式 | ✅ | 2.9 | origin/platform 8efb5f15 |
| 4a | 預檢 | ✅ | 0.1 | 無問題 |
| 4b | 備份＋試還原 | ✅ | 20.1 | 無問題；寫 backup_verify.json |
| 4c | 轉換 | ✅ | 12.5 | migration OK |
| 4d | 驗證（新版啟動） | ✅ | 34.0 | 無問題 |
| 5 | 冒煙 | ✅ | 13.9 | 15／15 項 200（演練帳號 `final_drill_admin`，只存在演練複本） |
| 6a | 完整回滾（第一份備份） | ✅ | 48.7 | 還原後 `backend/motrix_erp.db` 與原始庫**邏輯內容相同**（iterdump 逐行 sha256，V9 啟動前比對）；V9 啟動 ping 200 |
| 6b | 再轉換（只回程式前） | ✅ | 56.3 | 第二份備份試還原、轉換、驗證皆過 |
| 6c | 只回程式 | ✅ | 19.6 | V9 啟動 ping 200、雜湊比對無問題 |

- 冒煙 15 項（第 4 次 16 項；`/api/definitions/custom_module` 已先拿掉，第二批合回後加回）：首頁、登入頁、報價單列表、案件管理頁、傳票列表、傳票頁、獎金分潤項目、獎金分潤頁、出納待付、請款單列表、營運報表、營運報表頁、模組管理、自訂模組清單、版本。
- 第 4 次唯一的 404 `/api/definitions/custom_module` 是第二批（P8 缺口 #5）才加的端點，預演用的 origin 程式本來就沒有 ⇒ 預期中。冒煙清單另有守門：每一條都必須是 app 的 GET 路由或 frontend/ 的頁面（`test_smoke_paths_are_real_routes_or_pages`）。
- 來源資料庫雜湊（Online Backup 後的副本；備份的標頭計數器每次會變，只供同一次演練內比對；跨次比對用 6a 的邏輯內容比對）：
  第 5 次 `backend\motrix_erp.db` bccfa1fd94cf…、`backend\motrix_erp_demo.db` 0141fe4b960e…、`backend\motrix.db` 與根目錄 `motrix_erp.db` 皆 45c461d0b87f…（兩份內容相同）。
- 其他發現：WAL 模式的資料庫，連 `mode=ro` 開啟都會在來源目錄建出 `-wal`／`-shm` ⇒ 工具改成先位元組複製再備份（證據另記在 AUDIT-C-host-D3D5 D-4）。

## 正式 D7 待辦

> 前提（稽核 D K-O1）：演練目錄的舊每日快照資料夾有 `.done` 卻沒有 `.db`（複製時略過所有 .db），工具只補了今天的快照 ⇒ 碰舊快照的行為（備份清理「至少保留最新 7 份」等）在演練裡面對的目錄與正式機不同，演練結果不涵蓋這一段。

1. D1～D6 完成、第二批與 wip/c-d7 合回後，用 `build_deploy_package.ps1` 打包，`--package` 指向部署包。
2. 停掉 V9 開發機伺服器（工具會檢查 port 666）。
3. `python tools/platform/final_drill.py --package <部署包>`；`source-backup` 保留到使用者回來。
4. 轉換後的全量測試以打包那個 commit 的 `tools/platform/full_results/<sha>.json` 為準（部署包不含 tests/）。
