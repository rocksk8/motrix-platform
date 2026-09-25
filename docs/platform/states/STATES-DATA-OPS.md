# 系統狀態目錄：資料／升級／部署／備份／通知（STATES-DATA-OPS，初版 2026-09-25）

> 視窗 C。另一面（模組平台）由 A 負責（編號 S-P…）；本檔編號一律以 **S-C** 開頭（S-CU 升級、S-CC 雲端備份、S-CD 資料庫、S-CP 部署、S-CN 通知）。基準：platform `6ef667ab`。
> **證據標記**：【實測】＝在開發機暫存目錄實際重現（腳本 `C:\…\scratchpad\repro_states.py` 與 init_db 損毀重現，暫存目錄已刪）；【讀碼】＝讀程式確認，附 `檔:行`；【讀碼·C 抽查】＝由 C 親自開檔核對過；【推論】＝依程式碼推得、**未實測**，列出以便下一步重現。
> 路徑前綴：`backend/`。`A`＝`archive.py`、`DT`＝`routers/daily_tasks.py`、`DD`＝`tools/deploy_dashboard.py`、`RP`＝`tools/_dashboard_remote.ps1`、`CU`＝`core/upgrade.py`、`TU`＝`../tools/platform/upgrade.py`、`EN`＝`helpers/email_notify.py`。

## 0. 摘要

- 共 46 個狀態；**嚴重度高 9 個，全部守門「缺」**（§6 清單）。
- 高且缺、屬於 C 的程式（L1 備份／資料庫／升級）：S-CD02、S-CC07、S-CC06、S-CN03、S-CU10。屬於主持的儀表板：S-CP01、S-CP02、S-CU01、S-CU06。§6 註明歸屬，**補程式等主持看過再開始**。
- 其餘列入 ROADMAP 階段 S（§7）。

欄位：狀態｜怎麼觸發｜目前實際行為（證據）｜應有行為｜使用者看得到什麼｜怎麼復原｜守門｜嚴重度

## 1. 升級精靈與升級工具（U）

| # | 狀態 | 怎麼觸發 | 目前實際行為（證據） | 應有行為 | 使用者看得到什麼 | 怎麼復原 | 守門 | 嚴重度 |
|---|---|---|---|---|---|---|---|---|
| S-CU01 | WinRM 連線**掛住不回**（非斷線） | 網路半斷、遠端卡住 | 【讀碼】`_run_upgrade_job` 的 Popen／讀取迴圈無逾時（DD:1074-1086），遠端腳本亦無逾時；job 永遠 running、全域鎖不放，之後每步 409（DD:1115-1116） | 每步有逾時；逾時標 failed、放鎖、提示「狀態未知，先查遠端再決定」 | 畫面一直「執行中」 | 重啟儀表板 | 缺 | **高** |
| S-CU02 | WinRM **斷線** | 網路中斷 | 【讀碼】收不到 `===EXITCODE=n===` ⇒ Fail「取不到結束碼（連線可能中斷）」exit 1（RP:362-368），job 標 failed（DD:1087-1091）；遠端 python 是否繼續跑：未找到 | 同左，並提示「遠端可能仍在執行，先查 conversion_log 再動作」 | 步驟失敗訊息 | 查 `<BK>` 日誌後重跑該步或回滾 | 缺 | 中 |
| S-CU03 | 儀表板重啟後輪詢不停 | 執行中重啟儀表板 | 【讀碼】`_jobs` 只在記憶體；`/api/jobs` 回 404（DD:786-789），前端 pollJob 不處理 404、每 1.5 秒輪詢不止（deploy_dashboard.html:337-352） | 404 ⇒ 停止輪詢並顯示「工作紀錄遺失」 | 無限轉圈 | 重新整理頁面 | 缺 | 低 |
| S-CU04 | 轉換中途斷電／磁碟滿（程式換到一半） | 斷電、`copy2` 失敗 | 【實測 R2】`replace_program` 先刪全部程式再複製（CU:416-427），中斷後程式目錄只剩部分新檔；**完整回滾可從半成品收斂**（實測 `rollback(full)` 回 `[]`、雜湊一致）；無續跑標記，`conversion_log.json` 只在結束時寫（TU:131,134） | 轉換前寫「進行中」標記；啟動時看到標記就拒絕並指向回滾 | traceback、exit 1 | `rollback --mode full`（實測可收斂） | 缺（R2 未入測試） | 中 |
| S-CU05 | 備份中途失敗 | 斷電、磁碟滿、損毀庫 | 【讀碼】manifest 最後才寫（CU:362）⇒ 留下非空、無 manifest 的目錄；convert 拒絕（TU:121-122）；同目錄重跑 backup 被擋（【實測 R4】RuntimeError「備份目錄不是空的」） | 同左（fail closed）；訊息指出「換一個新的空目錄重跑」 | traceback | 換新目錄重跑 backup | `test_backup_refuses_non_empty_dir` | 低 |
| S-CU06 | 精靈的備份時間戳隨頁面重整改變 | 備份後重新整理頁面 | 【讀碼】時間戳在前端產生、精度到分鐘、`<span>` 不可編輯（html:138,220-222）；重整後 convert 報「沒有已驗證的備份」、rollback `load_manifest` FileNotFoundError（CU:368）；**UI 再也指不回舊備份** | 備份目錄由伺服器記住（或可選既有備份）；回滾頁列出可用備份 | 回滾失敗 | 只能照 RUNBOOK 用 CLI | 缺 | **高** |
| S-CU07 | 回滾本身失敗（檔案被鎖） | 服務未停、防毒鎖檔 | 【實測 R3】`os.remove` PermissionError 未攔（CU:517-531），停在一半（新舊程式檔混雜）；**解除鎖定後重跑同一回滾可收斂**（實測回 `[]`）；`rollback_*.json` 只在成功回傳後寫（TU:178-179） | 回滾前檢查服務已停；失敗時寫出「回滾未完成，可重跑」並列出剩餘檔 | traceback、exit 1 | 解除鎖定後重跑同一回滾 | 缺（R3 未入測試） | 中 |
| S-CU08 | 同一時間戳重跑、步驟亂序 | 重按按鈕 | 【讀碼】伺服器不管步驟順序（DD:1099-1113）；backup 第二次必失敗；convert 可重跑且不重做預檢（服務已啟動也能跑）；rollback-full 遠端寫死 `--yes`（RP:359），**「轉換後新增列數」不給人看** | 伺服器端記步驟狀態；convert 前重做服務已停檢查；full 回滾先顯示新增列數再確認 | 無提示 | — | 缺 | 中 |
| S-CU09 | 預檢的磁碟判斷不足 | 備份目錄在另一顆碟、程式很大 | 【讀碼】只看安裝目錄那顆碟 ≥ DB×3（CU:281-285）；未計程式大小、未看備份目錄那顆碟、未計試還原到 %TEMP% 的第二份（CU:376-389）；RUNBOOK 寫「DB×3＋程式」（RUNBOOK:13）⇒ 不一致 | 依實際寫入量（DB＋程式＋設定）×2 分別檢查兩顆碟 | 備份做到一半才失敗 | 清空間重跑 | `test_preflight_rejects_low_disk`（只涵蓋 DB×3） | 中 |
| S-CU10 | **預檢放行損毀主庫** | 主庫部分損毀 | 【實測 R1】`preflight` 回 ok=true（未跑 integrity_check）；`backup` 在讀表列數時 `DatabaseError: database disk image is malformed` 未攔、traceback | 預檢跑 `PRAGMA quick_check`，不過 ⇒ 列成 problem、不動任何東西 | 預檢綠燈、備份時崩潰 | 先修庫（還原備份）再升級 | 缺 | **高** |
| S-CU11 | 正式機 PATH 上沒有 python | 環境變數缺 | 【讀碼】遠端直呼 `python`（RP:343,362；apply_update.ps1:104,271,319,482）；【推論】`$LASTEXITCODE` 為空 ⇒ 顯示「連線可能中斷」（誤導）；start-services 等滿 240 秒報「服務沒有回應」 | 預檢先檢查 `python --version`；訊息明說「找不到 python」 | 誤導訊息 | 設 PATH | 缺 | 中 |
| S-CU12 | 升級後版本號仍顯示舊的 | 升級後 | 【讀碼】`.build_commit` 被歸為設定檔（CU:66），`replace_program` 不帶新包的 `.build_commit` ⇒ 【推論】`/api/system/version` 回舊 SHA；完整回滾會還原舊值（正確） | `.build_commit` 屬於程式（隨包更新） | 版本資訊錯 | 手動換檔 | 缺 | 中 |
| S-CU13 | 轉換後還能按「啟動服務」而驗證沒過 | 使用者跳步 | 【讀碼】start-services 不看 verify 結果（RP:329-350） | verify 未通過 ⇒ 預設擋，需勾選確認並留紀錄 | 無 | — | 缺 | 中 |

## 2. 雲端與備份（C）

| # | 狀態 | 怎麼觸發 | 目前實際行為（證據） | 應有行為 | 使用者看得到什麼 | 怎麼復原 | 守門 | 嚴重度 |
|---|---|---|---|---|---|---|---|---|
| S-CC01 | 服務啟動時雲端碟還沒掛上 | GoogleDriveFS 比服務晚起 | 【讀碼】沒找到時快取 `None` 不命中、下次立即重掃（A:77-81）；啟動 `_ensure_archive_dirs` 寫 ERROR 並寄信（A:565-578）；本機快照照做並寫 `.done`（A:1038）；雲端部分跳過並告警（A:2160-2166）；每 2 小時重跑（A:2297）會補做；autostart 延遲 90 秒（setup_autostart_task.ps1:41） | 同左；啟動那封信在碟 N 分鐘內掛上時可抑制 | 一封 ERROR 信，之後自動清 | 自動 | 缺（「先未掛、後掛上」無測試） | 低 |
| S-CC02 | 碟符 G: → H: | 重新登入 | 【讀碼】每次 `isdir` 驗證、不在就重掃（A:78-80）；所有權快取以路徑為鍵（A:258-261） | 同左 | 無感 | 自動 | `test_verdict_cache_is_keyed_by_archive_path` | 低 |
| S-CC03 | `系統存檔_個資` 被刪或改名 | 人為 | 【讀碼】ready→missing 邊緣觸發 ERROR 並寄信（A:1205-1224）；之後不再告警；`BACKUP_ALERT.txt` 下次 daily_ok 被清（A:2268）；設定頁 `/api/settings/pii-archive-status` 顯示（system.py:1816-1825）；整庫 `.db` 與 F2 不再上雲 | 同左＋每日摘要持續列出「個資資料夾未就緒」 | 一封信＋設定頁 | 重建資料夾並收窄權限 | `test_alert_is_edge_triggered` | 中 |
| S-CC04 | 個資資料夾權限被改寬 | 人為分享 | 【讀碼】程式偵測不到（無任何分享權限檢查） | 列為**人工檢查項**：DR-SOP §3a、RUNBOOK §0.1 每季確認 | 無 | 右鍵→共用 收窄 | 缺（無法自動） | 中 |
| S-CC05 | 雲端空間滿／單張表寫入失敗 | 配額滿 | 【讀碼·C 抽查】單表失敗記 "error" **照寫 `.done`**（A:2245），只發 WARN 不寄信（A:2258-2265），同日下一輪看到 `.done` 提早結束並清警示（A:2190-2192）；鏡像逐檔失敗只記 log（A:1099-1100） | 有表失敗 ⇒ 不寫 `.done`（或寫 partial marker 並隔輪重試）；WARN 不可以被下一輪靜默清掉 | 一則 WARN，隨即消失 | 手動重跑 | `test_partial_backup_failure_is_not_reported_as_ok`（只驗不報 ok） | 中 |
| S-CC06 | **月底最後一天月備份失敗** | 當月第一次成功日恰在月底且失敗 | 【讀碼】月備份不寫 `.done`（A:2135-2145），但當日每日 `.done` 已在 ⇒ 當天不重試；隔天 `month_label` 換月（A:2063）⇒ **上個月永遠沒有月備份**，之後也不再告警 | 月備份以「上個月是否已完成」為準補做（跨月補跑） | 當天一封信，之後沉默 | 手動補 | 缺 | **高** |
| S-CC07 | **系統時鐘往前跳** | BIOS 電池、NTP 錯 | 【讀碼·C 抽查】清理用 `date.today()` 算 cutoff（A:1355-1365 本機、A:1432-1450 雲端每日／個資每日）；跳 >30 天 ⇒ **本機真實快照全刪**，>60 天 ⇒ 雲端每日層全刪；月備份預設永久不受影響（A:1469）；無時鐘合理性檢查 | 清理前檢查「最新快照日期與今天差距」；差距異常（例：今天比最新快照晚 >2 天而中間沒有快照）⇒ 不清理並告警；永遠保留最新 N 份 | 無（資料已刪） | 月備份還原 | 缺 | **高** |
| S-CC08 | 系統時鐘倒退 | 同上 | 【讀碼】那一天 `.done` 已在 ⇒ 略過並清警示（A:2190-2191）；新鮮度檢查 `now - ts` 為負不告警（DT:1499） | 偵測「今天 < 最新快照日期」⇒ 告警 | 無 | 修時鐘 | 缺 | 中 |
| S-CC09 | 兩台機器同一天寫雲端 | 開發機誤接、雙機 | 【讀碼】marker 不存在自動認領（A:268-275）；id 不符停寫並寄信（A:279-297）；讀／解析失敗 **fail-open**（A:291-293）；認領無鎖（A:270） | 讀失敗維持 fail-open（刻意：避免正式機誤停）但要告警 | 一封信 | 刪 marker 重新認領（DR-SOP） | `test_archive_ownership_2026_09_14` 全檔、`test_unreadable_marker_fails_open` | 低 |
| S-CC10 | 排程工作與程式內排程同時跑備份 | 02:00 `backup_job.py` ＋ 程式內每 2 小時 | 【讀碼】archive 無任何鎖（grep Lock／O_EXCL／filelock 無）；只靠 `.done`，檢查與寫之間有空窗；`_atomic_json_write` 暫存檔名固定 `path+'.tmp'`（A:384）⇒ 兩行程互相覆蓋 | 行程間鎖（鎖檔＋pid），拿不到就略過並記錄 | 無 | — | 缺 | 中 |
| S-CC11 | 快照時本機碟滿 | 碟滿 | 【讀碼】外層 except ⇒ ERROR「本機 SQLite 快照失敗」（A:1064-1066）；可能留半份 `.db` 無 `.done`，下輪重做；警示檔同碟也可能寫不進（見 S-CN03）；08:00 磁碟檢查寄信（DT:1580-1616） | 同左 | 一封信 | 清空間 | `test_low_disk_alerts`（快照時碟滿：缺） | 中 |
| S-CC12 | 週備份時雲端不可用 | 碟未掛 | 【讀碼】直接 return、不告警（A:2303-2305） | 由每日層的告警涵蓋（可接受）；文件註明 | 無 | 自動 | 缺 | 低 |
| S-CC13 | S3 後端的個資資料 | 設定為 S3 | 【讀碼】個資一律不上傳並告警（A:1198-1200） | 未實作個資 prefix（已知限制） | 一封信 | — | `test_object_storage_backend_does_not_upload_and_alerts` | 低 |

## 3. 資料庫（D）

| # | 狀態 | 怎麼觸發 | 目前實際行為（證據） | 應有行為 | 使用者看得到什麼 | 怎麼復原 | 守門 | 嚴重度 |
|---|---|---|---|---|---|---|---|---|
| S-CD01 | 主庫不存在 | 路徑錯、碟未掛、庫被移走 | 【讀碼】預設位置才守（main.py:543-544）；`DatabaseMissing` 拒絕啟動（paths.py:117-128） | 同左 | 服務起不來，訊息指向還原 | 還原或設 `MOTRIX_CREATE_NEW_DB=1` | `test_require_db_*` | 低 |
| S-CD02 | **主庫部分損毀仍啟動** | 斷電、磁碟壞軌 | 【實測】損毀落在非關鍵表時 `init_db` 照常成功（伺服器會起來），`PRAGMA integrity_check` 本身丟 `malformed`；檔頭壞 ⇒ `init_db` 丟 `DatabaseError`（實測）；全 backend 只有 CU:168 用 integrity_check；**每日快照 `_snapshot_health` 不做 integrity**（A:952-987）⇒ 損毀的庫會被複製成「健康」的每日／月備份，好的舊快照依保留天數被清掉 | 啟動與每日快照都跑 `quick_check`；不過 ⇒ 快照不寫 `.done`、不清舊快照、ERROR 告警；啟動時記 ERROR 並在系統頁顯示 | 無（直到某張表讀不出來） | 從最後一份 quick_check 通過的快照還原 | 缺 | **高** |
| S-CD03 | WAL／SHM 殘留 | 當機、手動複製 `.db` 沒帶 `-wal` | 【實測 R6】Online Backup API 會帶入 WAL 內未 checkpoint 的列（備份含 `in-wal` 那一列）；升級把 sidecar 歸為 db（CU:44,81）；apply_update／rollback_update 還原時刪 `-wal/-shm`（apply_update.ps1:686-689）；手動 Copy-Item 無防護（version_manifest.json:1359 記過事故） | 文件：禁止手動複製 `.db`，一律用工具 | 無 | — | 缺（R6 未入測試） | 低 |
| S-CD04 | schema 比基準新 | V9 新增 migration 未追進 | 【讀碼】ERROR＋`SchemaNewerThanBaseline`，服務起不來（db.py:884-898）；預檢亦擋（【實測 R5】） | 同左 | 服務起不來，訊息印兩個版本號 | 追進 migration 或換回 V9 | `test_newer_than_baseline_is_refused`、`test_preflight_rejects_running_service_and_newer_schema` | 低 |
| S-CD05 | database is locked | 長交易、備份鎖 | 【讀碼】`connect(timeout=30)`（db.py:181），逾時 ⇒ 500「伺服器發生內部錯誤」並記 sqlite_errorname（main.py:518-534）；>5 秒記 SLOW REQUEST | 同左（可接受）；前端可提示「稍後再試」 | 500 | 自動 | `test_u9_a_locked_or_broken_database_raises_instead_of_reporting_zero` | 低 |
| S-CD06 | demo 庫損毀使正式服務起不來 | demo 庫壞 | 【讀碼】`init_db(DEMO_DB_PATH)` 在模組層執行（main.py:546）⇒ 【推論】丟例外 ⇒ **整個服務起不來**；demo 庫不存在則默默新建（db.py:259,307） | demo 庫失敗只停用 demo 帳號、記 ERROR，正式服務照常 | 服務起不來 | 刪 demo 庫重啟 | 缺 | 中 |
| S-CD07 | migration 中途失敗 | 程式錯、磁碟滿 | 【讀碼】每支成功才 `_set_version(i)`（db.py:901-906），但 migration 內部自行 commit（例 db.py:999,1217）⇒ 第 k 支部分變更已寫入；例外往外丟、服務起不來；此路徑不關連線 | 同左＋依賴冪等（U10 守著）；失敗時關連線 | 服務起不來 | 修正後重啟重跑 | `test_u10_every_migration_can_be_run_twice`（中途失敗：缺） | 低 |

## 4. 部署（P）

| # | 狀態 | 怎麼觸發 | 目前實際行為（證據） | 應有行為 | 使用者看得到什麼 | 怎麼復原 | 守門 | 嚴重度 |
|---|---|---|---|---|---|---|---|---|
| S-CP01 | **部署／回滾結束時 NameError，歷史不寫** | 每一次 deploy／rollback | 【讀碼·C 抽查】`_run_job` 用了未定義的 `success`（DD:553；`_run_job` 476-561 內無賦值，只在 `_run_upgrade_job` 1072/1087 有）；發生在狀態設定之後、finally 會放鎖 ⇒ 畫面狀態正確，但**歷史永不寫入**，「15 分鐘內剛失敗」警告（DD:630-651）對部署失效；4 份測試都把 `_run_job` 換成假的 | 修正變數；補一題不 mock `_run_job` 的測試 | 無（log 有 traceback） | — | 缺 | **高** |
| S-CP02 | **D1 健康檢查假綠燈** | 每日備份壞了，但有人剛做過部署 | 【讀碼·C 抽查】「最近備份」取 `db_backups` 底下遞迴**任何檔案**的最新修改時間（RP:381-384），不看 `.done`、大小、完整性；apply_update 每次部署都建 `pre_update_<ts>`（apply_update.ps1:242）⇒ **一次部署嘗試就讓 D1 變綠**；磁碟只判斷名為 C 的碟，清單沒有 C 就放行（deploy_insights.py:163-165）；雲端未檢查 | 以最新 `YYYY-MM-DD/.done` 為準；磁碟找不到 ⇒ 未確認（不放行） | 綠燈 | — | 缺（`test_each_problem_blocks` 未涵蓋） | **高** |
| S-CP03 | 部署包不完整 | 打包中斷、推送不完整 | 【讀碼】打包只查 backend／frontend 存在（build_deploy_package.ps1:838-840），**未呼叫 verify_package**（只有註解，879,885）；MUST_EXIST 只有 2 個檔（verify_package.py:143）；apply_update 只查 manifest 存在（201-206）；推送後不驗（RP:293） | 包內附逐檔雜湊清單；推送後與套用前比對 | 靠啟動 ping 才抓到 | 重新打包推送 | 缺 | 中 |
| S-CP04 | 部署包 SHA 與全量紀錄不符 | 打包後又 commit | 【讀碼】只有打包時比 HEAD 與 `.last_full`（DD:827-830,869-873）；部署／升級步驟不比「包的 commit」（DD:904-930,1098-1124）；閘門看當下 HEAD、打包腳本另外釘 commit（build:187）⇒ 空窗 | 部署時比對包內 commit 與全量紀錄 | 無 | — | `test_build_blocked_when_full_is_for_another_commit`（部署端：缺） | 中 |
| S-CP05 | 開發機標記被帶上正式機 | 手動複製、非 git 打包 | 【讀碼】`.gitignore` 排除（:83-84）⇒ git archive 不含；verify_package 有 dev-marker 規則（:127-128）但**未接進打包**；apply_update 複製包根目錄全部檔案不過濾（458-459）；升級預檢會擋（CU:310-313）；D1 會查（RP:408） | 打包接 verify_package | D1 警告 | 刪標記 | 升級端 `test_preflight_each_check_can_fail`；打包端：缺 | 低 |
| S-CP06 | 人工放行留痕誤觸「上次失敗」 | 勾選略過閘門 | 【讀碼】略過以 `success=False` 記入歷史（DD:880,920,1118）⇒ 下一次部署出現「上一次失敗」警告 | 另記一種 kind（override） | 誤警告 | — | 缺 | 低 |

## 5. 通知（N）

| # | 狀態 | 怎麼觸發 | 目前實際行為（證據） | 應有行為 | 使用者看得到什麼 | 怎麼復原 | 守門 | 嚴重度 |
|---|---|---|---|---|---|---|---|---|
| S-CN01 | SMTP 未設定 | 新安裝 | 【讀碼】帳密空 ⇒ `SEND_SKIPPED`＋WARNING（EN:243-247）；設定頁 GET 無「可不可寄」欄位（system.py:1864-1874），只有按「測試」才回 400（:1962-1965） | 設定頁與系統狀態頁顯示「目前寄不出信：原因」 | 只有 log | 填設定 | 雷達：`test_n16_smtp_not_configured_does_not_mark`；設定頁狀態：缺 | 中 |
| S-CN02 | SMTP 寄送失敗 | 密碼錯、網路 | 【讀碼】任何例外當暫時失敗（EN:262-267），`_send` 不重試；呼叫端有 `wait()` 者才重試（例：新鮮度檢查 DT:1527-1529） | 同左 | 看呼叫端 | — | `test_notify_marks_only_on_success_2026_09_22` | 低 |
| S-CN03 | **告警本身發不出去（告警的告警）** | SMTP 壞、警示目錄不可寫 | 【讀碼】`_write_backup_alert` 的警示檔、日誌、audit、寄信在**同一個 try**（A:423-471）：目錄不可寫 ⇒ 424/437 丟例外 ⇒ audit 與寄信都不執行，只剩 `logger.exception`；節流標記在寄信**之前**寫（A:461-467）⇒ 寄失敗當天不再寄；`_async_send` 的 handle 被丟（A:501）；找不到最高管理者直接 return 無 log（A:482-484）；heartbeat 只看 `/api/ping`（heartbeat_job.py:53） | 四個管道各自獨立 try；寄成功才寫節流；寄不出去時改寫到另一個看得見的地方（系統頁紅色狀態、heartbeat 回報 fail） | 可能完全沒有 | — | 缺（只有新鮮度那一路的 `test_the_daily_guard_is_not_burned_when_the_alert_fails`） | **高** |
| S-CN04 | 收件人查詢失敗與「沒有收件人」無法分辨 | 庫鎖、users 表錯 | 【讀碼】`_admin_emails`／`_lookup_emails`／`_superadmin_emails` 失敗只記 log 回空（EN:160-162,179-181,1354） | 查詢失敗 ⇒ 另記 ERROR 並視同寄送失敗 | 無 | — | 缺 | 中 |
| S-CN05 | heartbeat 的 ping_url 未設 | 新安裝 | 【讀碼】WARNING 到 heartbeat_job.log，只查本機（heartbeat_job.py:50-51）；本機服務掛只記 ERROR 不對外發 fail（:55-58）；無 UI | 系統頁顯示「外部監控未設定」 | 無 | 填 heartbeat_config | 缺 | 中 |
| S-CN06 | 正式機殘留 `.no_email_send` | 誤帶標記 | 【讀碼】啟動記一次 INFO、之後每封 WARNING「email BLOCKED」（EN:47-77）；測試寄信回 400（EN:356）；升級預檢擋（CU:310-313）；D1 會查 | 系統頁顯示「這台機器不寄信：原因」 | log、D1 | 刪標記 | `test_email_send_policy`（系統頁顯示：缺） | 中 |
| S-CN07 | 備份告警 WARN 等級不寄信且被下一輪清掉 | 每日 partial | 【讀碼】partial 只 WARN（A:2256-2265），下一輪提前結束時清警示（A:2191） | 見 S-CC05 | 幾乎看不到 | — | 缺 | 中 |

## 6. 嚴重度「高」一覽與補強歸屬（補程式等主持看過再開始）

| # | 守門 | 歸屬 | 補強方向（摘要） |
|---|---|---|---|
| S-CD02 主庫部分損毀仍啟動、損毀庫被當成健康備份 | 缺 | **C**（L1 archive／db） | 每日快照與啟動加 `quick_check`；不過 ⇒ 不寫 `.done`、不清舊快照、ERROR |
| S-CC07 時鐘往前跳清掉所有快照 | 缺 | **C** | 清理前做時鐘合理性檢查，永遠保留最新 N 份 |
| S-CC06 月底月備份失敗 ⇒ 上個月永久缺 | 缺 | **C** | 以「上個月是否完成」補跑 |
| S-CN03 告警的告警 | 缺 | **C**（archive `_write_backup_alert`） | 管道獨立 try、寄成功才寫節流、寄不出去時另一條看得見的路 |
| S-CU10 預檢放行損毀庫 | 缺 | **C**（core.upgrade） | 預檢加 `quick_check` |
| S-CU06 精靈時間戳重整即失聯 | 缺 | 主持（儀表板） | 伺服器端記住備份目錄、可選既有備份 |
| S-CU01 WinRM 掛住 job 永不結束 | 缺 | 主持 | 每步逾時 |
| S-CP01 `_run_job` NameError | 缺 | 主持 | 修變數＋不 mock 的測試 |
| S-CP02 D1 假綠燈 | 缺 | 主持 | 以 `.done` 為準；磁碟未知不放行 |

> ⚠ 主持的儀表板是我在 §9d 的稽核對象。S-CU01／S-CU06／S-CP01／S-CP02 若由我修，等於修自己要稽核的東西；建議由主持修、我稽核，或改派。請裁示。

## 7. 其餘列入 ROADMAP 階段 S

中：S-CU02、S-CU04、S-CU07、S-CU08、S-CU09、S-CU11、S-CU12、S-CU13、S-CC03、S-CC04（人工檢查項）、S-CC05、S-CC08、S-CC10、S-CC11、S-CD06、S-CP03、S-CP04、S-CN01、S-CN04、S-CN05、S-CN06、S-CN07。
低：S-CU03、S-CU05、S-CC01、S-CC02、S-CC09、S-CC12、S-CC13、S-CD01、S-CD03、S-CD04、S-CD05、S-CD07、S-CP05、S-CP06、S-CN02。

## 8. 正對照與限制

- 【實測】7 項（R1–R6、init_db 損毀）；【讀碼·C 抽查】4 項（S-CC05、S-CC07、S-CP01、S-CP02）；其餘【讀碼】由三組並行蒐證取得 `檔:行`；【推論】已逐一標出（S-CU11、S-CU12、S-CD06），下一步優先實測。
- 未涵蓋：正式機的實際設定（SMTP、heartbeat ping_url、雲端碟符）——不連正式機，列為使用者可在儀表板 D1 或系統頁確認的項目。

## 9. 補強結果（C 的 5 項，2026-09-25）與 V9 是否同樣受影響

| # | 處理 | 守門（`backend/tests/test_states_data_ops_2026_09_25.py`） | 突變 | V9 正式機是否同樣受影響（`c83dae6e`） |
|---|---|---|---|---|
| S-CD02 | `db.quick_check()`；`_snapshot_health` 讀得開之後再做 quick_check，不過 ⇒ 不寫 `.done`、不清舊快照、ERROR；`main.py` 啟動時 `_startup_integrity_check()`，不過 ⇒ ERROR 告警（不擋啟動） | `test_state_cd02_*`（5 題：健康庫 ok、部分損毀仍能 init_db 但 quick_check 不過、快照拒收、損毀主庫不產生 `.done` 且舊快照保留、啟動接線） | 拿掉快照的 quick_check ⇒ 2 紅。⚠ 更正（X 稽核 A-2）：「啟動接線」那一題原本是假綠燈（子字串比對到 `def` 本身，刪掉呼叫照綠），已改用 AST 找模組層級的呼叫且在 `init_db(DEMO_DB_PATH)` 之後：刪掉呼叫、搬到前面 ⇒ 皆紅 | **是**：`backend/archive.py:946-951` `_snapshot_health` 只看讀得開與筆數，無完整性檢查；V9 無啟動檢查 |
| S-CC07 | `_prune_select()`：每一層（本機、雲端每日、個資每日、週、月、個資月）至少保留最新 `PRUNE_KEEP_NEWEST`＝7 份；除了今天以外全部過期 ⇒ ERROR「系統時鐘可能往前跳」 | `test_state_cc07_*`（正常時鐘照日期清且不告警；跳 40 天保留 7 份並 ERROR；雲端每日同一底線） | 底線拿掉 ⇒ 2 紅 | **是**：`backend/archive.py:1243`（本機 `cutoff = date.today()…`）、`:1313`（雲端每日） |
| S-CC07 更正（X 稽核 A-1，2026-09-25） | ⚠ 上一列的作法**不符「應有行為」**：只做到「保留最新 7 份」，其餘照刪；X 多日模擬：跳的當天 30 份剩 6 份、第 7 天剩 0、告警只有第 1 天。改為與 V9 a1cc2871 相同：①有份數日期晚於今天，或②有東西要刪且今天以外全部過期 ⇒ 該層寫 `.prune_hold`、這一輪不刪；標記在就每輪 ERROR 且不刪，直到有人確認後手動刪標記（讀不到標記當成暫停）；六層同一判定；保留最新 7 份的底線 | `test_state_cc07_*`（多日模擬 40 天：真實快照一份不刪、每天 ERROR；短停機照清不告警；未來日期；標記要人刪才解除；讀不到標記＝暫停；雲端每日） | 標記不持續（每輪重新推算）⇒ 2 紅；讀不到當成沒有／未來日期不觸發／不告警 ⇒ 各 1 紅；②不觸發 ⇒ 2 紅 | 同上一列；V9 已修（a1cc2871，U2） |
| S-CC06 | 每日 `.done` 已在時仍重試 `_monthly_backup()`；`_check_previous_month_backup()`：上個月系統有在跑卻沒有月備份 `.done` ⇒ ERROR（不自動補，因為補做的不是那個月的資料） | `test_state_cc06_*`（同日重試、上月缺漏告警、已完成／全新安裝不告警） | 拿掉同日重試 ⇒ 1 紅 | **是**：`backend/archive.py:1942` 每日 `.done` 在就 return；`:1829` 月份以當天計 |
| S-CN03 | `_write_backup_alert` 四個管道各自 try；寄信另設 `.emailed_<日期>`，**寄成功才寫**；寄失敗／無收件人 ⇒ `backup.alert_email_failed` audit＋警示檔註記＋ERROR log | `test_state_cn03_*`（成功一天一封、失敗不節流且留痕、警示目錄不可寫仍 audit 與寄信、無收件人留痕、WARN 不寄） | 不論結果都寫節流 ⇒ 1 紅 | **是**：`backend/archive.py:412-498` 同一個 try、`:442` 節流在寄信前寫、`:498` `_async_send` 結果丟棄 |
| S-CU10 | `core.upgrade.quick_check()`；預檢不過 ⇒ problem，不動任何東西 | `test_state_cu10_*`（健康庫通過、損毀庫擋下） | 拿掉 ⇒ 1 紅 | **否**：V9 沒有升級工具（`core/upgrade.py` 是新版才有） |

- 受影響題目（備份／告警／升級／email 相關 47 檔＋`tests/platform`）：901 passed。
- 行為變更（已同步調整既有測試）：`test_backup_retention_policy_2026_09_14` 的 `arch` 與 `test_cloud_storage_2026_09_07` 的 S3 清理題把底線設為 1／0，因為它們守的是日期規則、每題只造兩三個資料夾。
