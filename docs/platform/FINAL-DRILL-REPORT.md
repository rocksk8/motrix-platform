# D7 最終轉移升級驗證報告

> 正式 D7 在 D1～D6 完成後執行（RUN-PLAN §3），用 `tools/platform/final_drill.py` 產生結果。
> 下面「預演」是 2026-09-26 用同一支工具、在 D1～D6 完成前跑的；正式執行時保留預演段落，在上面補正式結果。

## 正式執行

（待 D1～D6 完成後執行）

## 預演（2026-09-26，C）

- 來源：`C:\Users\hichan\Desktop\MOTRIX-ERP`（V9 開發目錄，只讀；結束後 `git status` 乾淨、沒有 -wal／-shm）。
- 演練目錄：`D:\MOTRIX-FINAL-DRILL-REHEARSAL`（跑完已刪，含 source-backup——預演不保留；正式 D7 保留到使用者回來）。
- 新版程式：`git archive origin/platform`（cdf41cc0）。不是部署包；正式 D7 用 `--package`。
- 共跑 4 次；前 3 次各抓到一個問題，修完才跑到底：

| 次 | 停在 | 原因 | 處置 |
|---|---|---|---|
| 1 | 4a 預檢 | V9 開發機有未處理的備份告警（「找不到雲端備份路徑」：開發機沒有掛雲端） | 工具在**演練複本**裡封存告警，內容寫進報告；正式機升級前仍要由人處理 |
| 2 | 4c 轉換 | 工具沒寫 `backup_verify.json`（轉換只認已驗證的備份） | 工具補寫（兩次備份都寫） |
| 3 | 4d 驗證 | 🔴 新版啟動後「改寫了既有設定」`security.last_weak_pw_scan`／`last_unlock_pw_scan`。這是每日掃描的節流日期，新版一啟動就寫今天；真實庫是舊日期 ⇒ 驗證不過 ⇒ **正式機升級會被判失敗而回滾**。合成演練的庫是新建的、日期本來就是今天，所以一直沒看到 | `core.upgrade.RUNTIME_STATE_SETTINGS`：只有這兩個鍵、值是日期且沒有往回走才放行；守門要求 startup.py 寫入的設定鍵都要分類（wip/c-d7 a75aaaf8，突變 3 項皆紅） |
| 4 | — | 跑到底（見下表） | — |

第 4 次結果（總計約 3.7 分鐘）：

| # | 步驟 | 結果 | 耗時（秒） | 摘要 |
|---|---|---|---|---|
| 1 | 備份來源（唯讀） | ✅ | 12.5 | 4 個資料庫、821 個資料檔 |
| 2 | 建演練安裝目錄 | ✅ | 7.0 | 1,844 個檔；開發機舊告警已封存 |
| 3 | 取新版程式 | ✅ | 3.4 | origin/platform cdf41cc0 |
| 4a | 預檢 | ✅ | 0.0 | 無問題 |
| 4b | 備份＋試還原 | ✅ | 18.2 | 無問題 |
| 4c | 轉換 | ✅ | 15.4 | migration OK |
| 4d | 驗證（新版啟動） | ✅ | 37.2 | 無問題 |
| 5 | 冒煙 | ❌ | 16.0 | 15／16 項 200；未過：定義文件庫 `/api/definitions/custom_module`（404） |
| 6a | 只回程式 | ✅ | 25.1 | V9 啟動 ping 通過、雜湊比對無問題 |
| 6b | 再轉換（完整回滾前） | ✅ | 31.0 | 備份試還原、轉換、驗證皆過 |
| 6c | 完整回滾 | ✅ | 16.5 | V9 啟動 ping 通過、雜湊比對無問題 |

- 冒煙通過的 15 項：首頁、登入頁、報價單列表、案件管理頁、傳票列表、傳票頁、獎金分潤項目、獎金分潤頁、出納待付、請款單列表、營運報表、營運報表頁、模組管理、自訂模組清單、版本。
- 唯一的 404 `/api/definitions/custom_module` 是第二批（P8 缺口 #5）才加的端點，預演用的 origin 程式本來就沒有 ⇒ 預期中；第二批合回後重跑應為 200。
- 來源資料庫雜湊（Online Backup 後的副本；備份的標頭計數器每次會變，只供同一次演練內比對）：
  `backend\motrix_erp.db` 093dee8e…d3fe77d、`backend\motrix_erp_demo.db` aec61efa…13c9faf、`backend\motrix.db` 與根目錄 `motrix_erp.db` 皆 b5c4a536…ca0b6a45（兩份內容相同）。
- 其他發現：WAL 模式的資料庫，連 `mode=ro` 開啟都會在來源目錄建出 `-wal`／`-shm` ⇒ 工具改成先位元組複製再備份（證據另記在 AUDIT-C-host-D3D5 D-4）。

## 正式 D7 待辦

1. D1～D6 完成、第二批與 wip/c-d7 合回後，用 `build_deploy_package.ps1` 打包，`--package` 指向部署包。
2. 停掉 V9 開發機伺服器（工具會檢查 port 666）。
3. `python tools/platform/final_drill.py --package <部署包>`；`source-backup` 保留到使用者回來。
4. 轉換後的全量測試以打包那個 commit 的 `tools/platform/full_results/<sha>.json` 為準（部署包不含 tests/）。
