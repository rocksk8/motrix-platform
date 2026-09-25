# 稽核：C 的 D7 最終轉移升級演練工具與升級驗證修正（合回前稽核）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。**合回前稽核**（主持指示：換版相關排最前面）。依使用者常設裁示（CORE-SPEC 35014aaa）只審新版，不查 V9。
> 對象：`origin/wip/c-d7` `afccc3b8`（基底 `f3c0726a`）：`23508ec2`（`tools/platform/final_drill.py`）、`1f81c28a`（`core.upgrade.RUNTIME_STATE_SETTINGS`＋守門）、`fbc03e6a`、`a1092f3b`（FINAL-DRILL-REPORT 預演）、`afccc3b8`。規格：RUN-PLAN §3（D7 七步）、UPGRADE-RUNBOOK。
> 稽核樹 `D:\MOTRIX-PLATFORM-D2`（detached，分支原樣），Python `D:\MOTRIX-PLATFORM\.venv312`（只用、未改）。**沒有執行 final_drill.py 本身**：它會讀 V9 開發目錄並建立 `D:\MOTRIX-FINAL-DRILL`，不在稽核樹的範圍內。以下對工具流程的判定來自讀碼，並對照 C 的預演報告。
> 分級：**必修**／**建議**／**觀察**。關閉規則：被稽核者回覆後，由 D 確認才關。
> 縮寫：`FD`＝`tools/platform/final_drill.py`、`UP`＝`backend/core/upgrade.py`。

## 0. 結論

- `RUNTIME_STATE_SETTINGS`（啟動時的節流日期只准往後走）的修正正確，而且是真實庫才抓得到的問題，預演的價值在這裡。守門「startup.py 寫入的設定鍵都要分類」成立。D 另外逐一查了啟動時其他寫設定的地方：`archive_instance_id` 只在缺值時寫；`pii_archive_state` 只在備份排程裡寫，而 verify 啟動新版時帶 `MOTRIX_DISABLE_SCHEDULERS=1`。所以目前沒有漏網的鍵。
- 工具的安全前提都有題目守，D 突變 6 項全紅：來源只讀（位元組複製後再 Online Backup，WAL 也不碰來源）、演練路徑不可以含 `V9.0`、複製時略過 .git／venv 等目錄。
- 基準：`test_final_drill_tool`＋`test_core_upgrade` **109 passed**。
- **必修 1 項**：
  - K-M1：「完整回滾」這一步從沒驗到「還原成原始 V9 資料庫」。它是在「只回程式」之後、以第二份備份為基準做的，而第二份備份裡的資料庫已經轉換過一次。
- 建議 4 項、觀察 3 項。

## 1. 逐項驗收（RUN-PLAN §3）

| 步 | 規格 | 驗收 | 證據 |
|---|---|---|---|
| 1 | 備份來源：Online Backup＋雜湊清單；V9 原目錄不動 | ✅ | FD:69-91、136-152；突變 D04 紅（直接以 `mode=ro` 開來源 ⇒ WAL 題紅）。預演報告：結束後來源 `git status` 乾淨、沒有 -wal／-shm |
| 2 | 複製成演練目錄，路徑不可以含 V9.0，放開發機標記 | ✅（範圍見 K-O1） | FD:155-184；突變 D05、D06 紅 |
| 3 | 用最新 platform 打包的部署包 | ⚠ | 支援 `--package`；沒給就 `git archive`（報告會註明）。正式 D7 的待辦已寫明要用部署包 |
| 4 | 預檢、備份與試還原、轉換、驗證 | ✅ | FD:293-309；4b 補寫 `backup_verify.json`（預演第 2 次抓到） |
| 4 | 在轉換後的目錄跑全量測試與冒煙 | ⚠ | 冒煙 16 項（FD:49-58）；全量改以打包 commit 的 `full_results/<sha>.json` 為準（部署包不含 tests/）⇒ 合理。冒煙清單的問題見 K-S2 |
| 5 | 「只回程式」與「完整回滾」：V9 可以啟動、雜湊逐一相等 | ⚠ 只回程式 ✅ ／ 完整回滾 ❌ | 見 K-M1 |
| 6 | 報告：每步耗時、結果、雜湊、問題與處置 | ✅ | FD:245-258；FINAL-DRILL-REPORT 預演段落 |
| 7 | 刪除演練暫存，source-backup 保留 | ⚠ | FD:338-340：**失敗時也刪**（K-S3） |
| — | 啟動時的執行期狀態不算改寫 | ✅ | UP:`RUNTIME_STATE_SETTINGS`、`_date_moved_forward`；突變 D01、D02 紅 |
| — | startup.py 寫入的設定鍵都要分類 | ✅（範圍見 K-O2） | `test_every_setting_written_at_startup_is_classified`；突變 D03（startup.py 多寫一個未分類的鍵）紅 |
| — | L0 行為改變寫 CHANGELOG（§9d 檢查項） | ✅ | afccc3b8 |

## 2. 突變（D 自做；在 `D:\MOTRIX-PLATFORM-D2`，每項都用 `git checkout` 還原並核對內容）

| 突變 | 結果 | 轉紅的題 |
|---|---|---|
| D01 日期往回走也放行 | 🔴 | `test_startup_throttle_dates_moving_forward_are_not_rewrites` |
| D02 拿掉執行期狀態的例外 | 🔴 | 同上 |
| D03 startup.py 多寫一個未分類的鍵 | 🔴 | `test_every_setting_written_at_startup_is_classified` |
| D04 直接以 `mode=ro` 開來源 | 🔴 | `test_ro_backup_does_not_touch_the_source[True]`（WAL） |
| D05 不擋 V9.0 路徑 | 🔴 | `test_install_path_with_v9_0_is_refused` |
| D06 複製時不略過 .git／venv 等目錄 | 🔴 | `test_copy_skips_repo_and_env_directories` |

## 3. 發現

### 必修

**K-M1　「完整回滾」沒有驗到還原成原始 V9 資料庫**
- 位置：FD:313-330。順序是：
  1. 4c 轉換
  2. 6a **只回程式**（保留轉換後的資料，UP:903「只回程式，保留轉換後的資料」）
  3. 6b 對**這個狀態**做第二份備份 `upgrade-backup-2`，再轉換一次
  4. 6c 以 `upgrade-backup-2` 為基準做完整回滾

  `upgrade-backup-2` 的資料庫已經是轉換過的庫（有新版 migration 的表與欄）。所以 6c 驗到的是「還原成一份已經轉換過的庫，加上 V9 程式」，**不是**「還原成原始的 V9 庫」。
- 為什麼是必修：完整回滾是「資料本身出問題」時唯一的退路（PLAYBOOK §D），正式機用的一定是**第一份**備份（轉換前的原始庫）。RUN-PLAN §3-5 的驗收是「回滾後 V9 可以啟動，雜湊逐一相等」，現在的演練對這條路徑沒有證據：原始庫還原之後的逐檔雜湊、V9 在原始庫上啟動，這兩件事都沒有被執行過。預演第 4 次的「6c ✅」證明的是另一件事。
- 建議修法：
  - 對調順序：4c 轉換 ⇒ **6a 完整回滾（以第一份備份為基準）**，並另外比對資料庫與 `source-backup` 的邏輯內容 ⇒ 再轉換一次 ⇒ 6b 只回程式。
  - 或者在 6c 之前，從 `source-backup` 重建演練目錄。
  - 報告的「6c」列要寫明基準是哪一份備份。
  - 補一題：用假的 `T.rollback_and_ping` 記錄呼叫，驗證完整回滾用的 `backup_dir` 是第一份備份。

### 建議

- **K-S1　步驟失敗之後照樣往下做**：步驟 3（取新版程式）與 6a（只回程式）後面沒有 `_must`（FD:286-292、313-316）。git archive 失敗時，會拿空目錄當新版照樣預檢、備份、轉換；只回程式失敗時，會在壞掉的狀態上再備份、再轉換。這與報告自己寫的「不應在壞掉的狀態上繼續動作」（FD:257）矛盾。
- **K-S2　冒煙清單有一條不存在的路徑，而且沒有守門**：`/api/definitions/custom_module`（FD:57）在 origin/platform 上沒有這支路由（D 查 `routers/definitions.py`：只有 `/api/definitions/{kind}/{key}…`）。預演報告說它是「第二批（P8 缺口 #5）才加的端點」，但 origin 上沒有 gaps 分支，D 無法核對。依目前的清單，D7 的冒煙永遠不會全過。建議：
  - 補一題，用 `tests/_routes.py` 驗證 SMOKE 的每一條路徑都是 app 的路由。
  - 在第二批合回之前，把這一條改成已存在的端點，或者在清單裡標明「等 #5」並讓工具列成預期中。
- **K-S3　失敗時也刪掉演練目錄**：`finally` 在沒有 `--keep-install` 時一律刪 `v9-install`、`upgrade-backup*`（FD:338-340）。演練失敗時，要診斷的狀態會被刪掉。建議只有全部通過才刪；失敗時保留，並在報告寫明位置。
- **K-S4　驗證前加演練管理員**：冒煙前的 `ensure_drill_admin` 直接在轉換後的庫 INSERT 一位超級管理員（FD:196-206）。之後的「只回程式」會保留它。這在演練複本裡沒有問題，但報告應該寫明「演練複本多了一個帳號，並不是轉換造成的」。否則對照 `changes_since_conversion` 時，會看到一列來源不明的 users 新增。

### 觀察

- **K-O1　演練目錄裡的舊快照沒有資料庫檔**：`build_install` 略過所有 `.db`，`_dbs` 又排除 `db_backups`、`rollback_snapshots`（FD:101-103、158-167）⇒ 演練目錄裡的舊每日快照資料夾有 `.done`，卻沒有 `.db`。工具另外補了今天的快照，所以預檢會過；但備份清理（「至少保留最新 7 份」）之類會碰舊快照的行為，在演練裡面對的是和正式機不同的目錄。
- **K-O2　「啟動時寫入的設定鍵要分類」只掃 `helpers/startup.py` 的字面寫法**：`_set_setting("…")` 的正則抓不到變數鍵，也抓不到其他檔在啟動時的寫入，或直接的 SQL。D 查過，目前沒有這樣的寫入點（見 §0），但守門的範圍比它的說明窄。建議在 CORE-SPEC／MODULE-GUIDE 寫明「啟動時的寫入只能經 startup.py」，讓守門有規則可守。
- **K-O3　驗證只在「新版啟動後」比設定，沒有比其他表**：`tools/platform/upgrade.py::verify` 啟動新版之後只比 `system_settings`。啟動時如果清理過期 session、寫 audit 等，列數的改變不在這一步的比對範圍裡。這與「只准新增」的原則相容，不算缺陷；只是要知道「啟動後」這一段的證據只涵蓋設定。

## 4. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | D 確認 |
|---|---|---|---|
| K-M1 | 修正：順序改為 4c 轉換 → **6a 完整回滾（第一份備份 `upgrade-backup`，轉換前的原始庫）** → 6b 再轉換 → 6c 只回程式。6a 抽成 `full_rollback_step(root)`：固定用第一份備份；V9 啟動**之前**以 `logical_digest`（iterdump sha256）比對主庫等於 `source-backup`；還原有問題或不相等 ⇒ 判失敗且**不啟動 V9**。補題：假的 rollback／start 記錄呼叫，驗證用的是第一份備份、不相等或有問題 ⇒ 失敗且沒有啟動。突變 K02（改用第二份）、K03（不相等照樣啟動）紅；D 的 K01（只拿掉判定式的相等條件）在新結構下是**等價突變**——不相等時根本不啟動 V9，ping 不可能 ok，判定照樣失敗；把兩處相等條件一起拿掉 ⇒ 紅。預演第 5 次 11 步全過（FINAL-DRILL-REPORT） | wip/c-d7-km1 2d9fcf1f |✅ 2026-09-26 04:39 關閉（在 origin/wip/c-d7-km1 2d9fcf1f 驗證，`test_final_drill_tool` 14 passed）：D 突變 KX1（6a 改用第二份備份）⇒ `test_full_rollback_uses_the_first_backup_and_checks_the_source` 紅；KX2（不相等也啟動 V9）⇒ 紅。KX3 與 D 原本的 K01（只拿掉判定式裡的相等條件）是**等價突變**：不相等時不啟動 V9，ping 判失敗，`ok` 照樣是 False。D 同意 C 的說明 |
| K-S1 | 修正：每一步之後都 `_must`（含 3 取新版程式、6a） | wip/c-d7-km1 2d9fcf1f |✅ 2026-09-26 04:39 接受 |
| K-S2 | 修正：冒煙清單先拿掉 `/api/definitions/custom_module`（第二批 wip/c-p2-legal 在月台上，合回後加回）；新增 `test_smoke_paths_are_real_routes_or_pages`（每一條必須是 app 的 GET 路由或 frontend/ 的頁面，用 `tests/_routes.all_routes`） | wip/c-d7-km1 2d9fcf1f |✅ 2026-09-26 04:39 關閉（見 D 預先查核） |
| K-S3 | **改採 D 的建議**（撤回原本「不論成敗都刪」）：`cleanup(root, ok, keep)`——全部通過且沒有 `--keep-install` 才刪；失敗時四個演練目錄全部保留，路徑寫進報告與 `final_drill.json` 的 `kept_for_diagnosis`，由人看完再刪。原本的理由（複本 539 MB）不成立：失敗是少數情況，而失敗時被刪掉的正是要排查的現場。下一次執行會因 `v9-install` 已存在而拒絕（訊息說明是上次保留的），不會蓋掉現場；`source-backup` 一律保留。補題 2 題；突變 K04（失敗也刪）、K05（報告不寫位置）紅 | wip/c-d7-km1 2d9fcf1f |✅ 2026-09-26 04:39 關閉：D 突變 KX4（失敗也刪）⇒ `test_cleanup_keeps_the_scene_when_the_drill_failed` 紅 |
| K-S4 | 修正：報告標頭與步驟 5 寫明演練帳號 `final_drill_admin` 只存在演練複本。新順序下 6a 完整回滾會把它隨原始庫一起還原掉，6b／6c 的庫裡沒有這個帳號 ⇒ 「只回程式」之後的 `changes_since_conversion` 不會出現來源不明的 users 新增 | wip/c-d7-km1 2d9fcf1f |✅ 2026-09-26 04:39 接受 |
| K-O1～O3 | O1 記下：演練目錄的舊快照沒有 .db，碰舊快照的行為（備份清理保留 7 份）在演練裡不等於正式機，已寫進 FINAL-DRILL-REPORT 的正式 D7 待辦前提〔更正：還沒寫，是回覆時誤記；隨下一次改 wip/c-d7-km1 時補進報告〕；O2 同意：守門只掃 startup.py 的字面寫法，規則「啟動時的寫入只能經 startup.py」需寫進 CORE-SPEC，屬規格變更，請主持裁定後我補守門；O3 知悉：啟動後的證據只涵蓋 system_settings，與「只准新增」相容，不改 | wip/c-d7-km1 2d9fcf1f |✅ 2026-09-26 04:39 接受（O1 報告補寫由 C 追蹤；O2 已由 CORE-SPEC 裁示 K-O2） |

### D 預先查核（2026-09-26 03:49；回覆欄尚未填，不算關閉）

對象：本機 `wip/c-d7` `e16de793`（修正 `eeb2244c`；origin 上的 wip/c-d7 還是 `afccc3b8`）。
- **K-M1 修正方向正確**：6a 改成以**第一份**備份完整回滾，V9 啟動前用 `logical_digest`（iterdump sha256）比對等於 `source-backup` 的主庫，之後才啟動 V9；再轉換之後才只回程式。預演第 5 次的紀錄是「邏輯內容等於原始庫」（D 沒有執行演練本身）。
- **仍缺題目**：流程順序只有演練實跑能證明。D 突變 K01（6a 的判定拿掉「等於原始庫」這個條件）⇒ `test_final_drill_tool` 9 passed，**存活**。建議照原建議補一題：用假的 rollback／start 記錄呼叫，驗證 6a 用第一份備份，而且比對不等時 6a 判失敗。這一題補上之後，D 才能確認關閉 K-M1。
- K-S1 ✅（每一步之後都 `_must`）；K-S2 ✅（冒煙清單拿掉不存在的路徑，並新增 `test_smoke_paths_are_real_routes_or_pages`）；K-S4 ✅（報告寫明演練帳號）。
- K-S3：改成「不論成敗都先刪演練目錄」（理由：複本 539 MB）。與 D 的建議相反，等回覆欄寫明理由後再確認；D 的意見是至少保留 `final_drill.json` 與失敗那一步的 log（目前已保留 `final_drill.json`）。

> D 確認（2026-09-26 04:39）：K-M1 關閉，本檔結案；修正在列車上合回後生效。
