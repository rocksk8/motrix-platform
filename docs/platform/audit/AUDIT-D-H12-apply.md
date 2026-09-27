# 稽核：H12 apply_update 日常更新（wip/h-apply-platform 0a96c920）——D 單獨完整稽核（2026-09-28 03:19）

> 範圍：`git diff 9350a3df...0a96c920`（13 檔）：apply_plan.py、apply_update.ps1、rollback_update.ps1、migrate_like_startup.py、
> tools/platform/upgrade.py、deploy_dashboard.py、test_apply_plan_2026_09_28.py、test_deploy_outcome、RUNBOOK §8、CORE-SPEC §9b 註記。
> 第一輪 A（AUDIT-A-H12-apply，92abe853）只當線索，結論逐項重驗。行號以 0a96c920 為準。
> 做法：只讀碼；在拋棄式 worktree（detached 0a96c920）跑題目、探針、突變；沒有起服務、沒有演練。暫存已刪，worktree `git status` 乾淨。

## 0. 結論

- **必修 2、建議 5、觀察 4。**
- **對正式機使用的判定：尚未通過。** 前提是 DM1、DM2 修好並經 D 複核，並完成 §5 的補演練（其中一條要等 B41 合回後才做得到）。
- A 第一輪已關閉的項目（AH-M1～M3、S2、S7、S9）重驗成立。AH-M1 由題目守住；M3、S7、S2 靠演練證據成立，**題目守不住**（見 DS3）。
- A 的 AH-S1、S3、S4、S5、S6 至今沒有回覆（PLAYBOOK §E-4 要逐項回覆）。其中 AH-S6 是本次判定的前提之一。

## 1. 逐項驗證

| 項目 | 驗法 | 結果 |
|---|---|---|
| 基準 | `pytest test_apply_plan_2026_09_28.py test_deploy_outcome_2026_09_23.py -n 2` | 122 過 |
| 刪除只限程式檔 | 讀 `deletable`（apply_plan.py:71）＋`core.upgrade.classify` | 成立（例外見 DO1） |
| 大小寫改名（AH-M1） | 突變 M10：execute 拿掉 casefold 過濾 | 紅（test_ahm1） |
| 快照核對 | 突變 M5：verify_snapshot 一律回空 | 紅 |
| 空目錄清理 | 突變 M6：`_prune` 直接 return | 紅 |
| 鎖、結果檔、trap | 讀碼＋題目在真的 PowerShell 跑抽出來的函式（:389-459） | 成立 |
| AH-S10 | `$timestamp = $script:RunStamp`（apply_update.ps1:491） | 成立 |
| 停服只停本安裝 | 演練 log：只結束 install\backend\autostart.bat 迴圈與 port 6781 行程；誘餌 18604／34276 都存活（主持紀錄） | 成立 |
| 演練五條路 | D:\MOTRIX-DRILLS\apply-run-0928 的 `::RESULT::`：migration_dryrun_failed ×2、success、unhealthy_rolled_back、rollback_ok ×2、delete_failed、copy_failed_frontend（rolled_back=restored service=up） | 與主持回報一致；**演練版本早於 240d3bbc／0a96c920** |

## 2. 必修

**DM1（必修）　兩種回滾都直接覆寫 DB，沒有先保存當下的 DB**

- 證據：
  - 手動回滾：rollback_update.ps1:427 `Copy-Item $dbBackupPath $dbPath -Force`，之前沒有任何備份當下 DB 的動作。儀表板帶 `-Yes`（_dashboard_remote.ps1:172），連確認框都沒有；:365 的確認框也沒有提到會丟資料
  - 自動回滾：apply_update.ps1:1073／:1084 同一個寫法
  - 這是既有行為（9350a3df:198 就是這樣），不是 H12 引入的，但它在「對正式機使用」的前提範圍內
- 後果：
  - 手動回滾（通常在套用後數小時到數天才做）會把期間所有的業務資料換掉。RUNBOOK §8 雖然寫了「⚠ 會丟掉套用後寫入的資料」，但腳本沒有留後路：選錯時間戳或判斷錯誤時救不回來，只剩最近一次的每日備份
  - 自動回滾：DB 快照（:491）到停服（:727）之間要經過乾跑、刪除計畫、程式快照。這段時間使用者照常寫入，而這些資料在回滾後會**靜默消失**
- 修法（不改使用者看得到的行為）：覆寫之前，先用 Online Backup 把當下的主庫與 demo 庫存到 `db_backups\pre_rollback_<RunStamp>\`，備份失敗就不覆寫（`Fail`，並新增一個狀態值）。成功與失敗的訊息都要印出這個路徑。補題：備份要出現在 `Copy-Item $dbBackupPath` 之前，而且兩支腳本都要有（結構題）
- 需要使用者裁示的部分（另列）：手動回滾是否一律換回 DB，或提供「只回程式、DB 保留」的選項。這會改變使用者看得到的行為，屬於 PLAYBOOK §F

**DM2（必修）　回滾到非最新的快照時，後來那幾次套用新增的模組資料夾會留在原地**

- 證據：
  - rollback_update.ps1:393-397 只跑**目標快照**那份 apply_plan.json 的 `cleanup-added`
  - 儀表板 list-snapshots 列出全部快照（保留 5 份，_dashboard_remote.ps1:189-），可以任選
- 重現（探針，拋棄式 worktree；scratchpad `probe_h12.py`）：
  1. T1 套用新增 `modules/m1`，T2 套用新增 `modules/m2`
  2. 以 T1 的計畫執行 `cleanup_added`
  3. ⇒ 刪掉 m1，而 `backend/modules/m2/{module.json, r.py}` 仍在
- 後果：
  - 回到 T1 之前的程式與 DB，但舊版載入器照樣載入 m2（載入器看資料夾）
  - m2 的模組 migration 會對回滾後的舊 DB 再跑一次
  - 腳本仍然報 `rollback_ok`（程式快照寫回、ping 過）⇒ 回滾本身就是一個假綠燈
- 修法（擇一）：
  - 甲（建議）：清理的依據改成「安裝目錄現在有、快照裡沒有的程式檔（classify==program）」。快照本身就是完整的程式清單，也涵蓋沒有 apply_plan.json 的舊快照
  - 乙：比目標更新的快照若帶有 apply_plan.json，就依新到舊逐份 cleanup-added
  - 丙：目標不是最新的快照 ⇒ 拒絕並說明
- 補題：兩次套用後回滾到第一次的快照 ⇒ 第二次新增的模組資料夾不存在（反向控制：回滾到最新快照時，行為與現在相同）

## 3. 建議

**DS1　停服之後的未預期例外：trap 回報了，但沒有嘗試恢復服務**
- 證據：trap（apply_update.ps1:397-402／rollback_update.ps1:302-307）只做 Emit-Result 然後 exit。停服（:727）之後、啟動（:880）之前，會丟例外的敘述有這些：
  - `Copy-Item` 根目錄文件（:831-833，檔案被占用時會丟）
  - autostart.bat 補檔（:811）
  - `Start-InstallService` 裡的 `Start-ScheduledTask`（:348）
- 後果：服務一直停著（service=down、rolled_back=applied），與 AH-M3 修掉的是同一類問題
- 建議：
  - trap 內判斷 `ProdState`。等於 `applied` 時嘗試 `Start-InstallService`（再包一層 try）；等於 `restoring` 時維持現狀，不要在 DB 沒還原時用舊程式啟動
  - RUNBOOK §8 狀態表補 `unhandled_exception`／`rollback_unhandled_exception` 兩列，依 rolled_back 寫處置（目前兩列都沒有）

**DS2　AH-S6 仍開著：乾跑「照啟動規則載入模組」那一支，在任何樹、任何演練都沒有執行過**
- 證據：
  - H12 沒有 `helpers/module_startup.py`
  - 演練 P2 的失敗點在 core migration（run_P2.log：`_core_v3_drill_bad`），走的是 `modules=none` 那一支
  - migrate_like_startup.py:37-59 的四個判定（載入失敗、停用清單讀不到、incomplete 為 None、incomplete 非空）沒有題。突變 M7（`inc is None` 不算失敗）存活
- 建議：第十四班 B41＋H12 同車，合回後補契約題（AH-S6 列的四件事），並補一次 P2m 演練：包裡放一個 migration 會失敗的**模組** ⇒ `migration_dryrun_failed`，而且程式檔 0 變動

**DS3　apply_update.ps1 的行為沒有題目守住；AH-O7 的雜湊題會讓突變看起來「紅」**
- 證據（突變，拋棄式 worktree，每次跑兩個題檔）：

| 突變 | 帶著 test_aho7 | 排除 test_aho7 |
|---|---|---|
| M3 複製失敗寫回時不還原根目錄文件 | 紅（只有 aho7） | **存活** |
| M4 自動回滾不還原 demo 庫 | 紅（只有 aho7） | **存活** |
| M8 套用前不把部署紀錄存進快照 | 紅（只有 aho7） | **存活** |
| M9 自動回滾不先 cleanup-added | 紅（只有 aho7） | **存活** |
| M1 手動回滾不還原 deployed_commit.before | 存活（rollback_update.ps1 沒有雜湊題） | 存活 |
| M2 手動回滾不移除新版 baseline | 存活 | 存活 |

- 後果：這些行為只有演練驗過，而且演練做在 240d3bbc 之前。日後對 apply_update.ps1 做的任何突變都會被 aho7 染紅，形成假紅燈（〈突變測試的假陽性〉的同型）
- 建議：
  - PLAYBOOK 的突變做法寫明：突變 ps1 時要 `--deselect` test_aho7
  - 對 M1～M4、M8、M9 各補一題結構題，照 test_ahm3 的寫法比對順序與存在

**DS4　AH-S5 仍開著：6 個狀態值不在 `_STATUS_FAILED`，RUNBOOK 表也沒有**
- 現況：`snapshot_failed_backend`／`_frontend`、`restore_copy_failed_backend`／`_frontend`、`rollback_copy_failed_backend`／`_frontend` 在儀表板與 RUNBOOK 各出現 0 次（grep）。判定結果靠 fail-closed 仍然正確，但處置表查不到
- 建議：照 A 的原建議處理，另加一題「兩支腳本所有狀態 ⊆ `_STATUS_ALL`」並附反向控制

**DS5　AH-S3 仍開著：手動回滾會把授權、憑證、autostart.bat 換回快照當時的版本**
- 現況：快照 /XF（apply_update.ps1:676）沒有排除 `license.key`／`certs`／`autostart.bat`，寫回時也沒有排除
- 後果：套用後才換的授權、憑證、對外連線開關，在回滾後被靜默改回舊值（包含 DM2 那種跨數天的回滾）
- 建議：寫回快照時依 `classify=="config"` 跳過（與轉換規則一致）；或由主持判定維持現狀，並寫進 RUNBOOK

## 4. 觀察

- **DO1**：`backend/.apply.lock` 的 classify 是 `program`（探針）。
  - 正式機現在沒有 baseline ⇒ 第一次日常更新的「只列不刪」清單會出現 `? backend/.apply.lock`（探針 P1b 重現），而套用中它一定存在
  - 它也會進程式快照、回滾時被寫回：手動回滾期間，鎖檔內容會變成舊的 apply PID。仍然擋得住並行（判成 stale）
  - 建議加進 `STATE_FILES`；快照的 /XF 也加上它
- **DO2**：migrate_like_startup 對 demo 庫未完成也判乾跑失敗（:53-59 逐庫），比使用者裁示 AB-S7 嚴格（「由主庫決定上下線；只有 demo 庫未完成 ⇒ ERROR＋demo 缺席」）⇒ 只有 demo 庫的問題也會擋下正式機更新。方向保守，記錄備查；要不要放寬由主持判定
- **DO3**：A 的 AH-S1（孤兒模組會刪掉 module_update 裝的加購模組）、AH-S4（行程樹沒有比對建立時間）未回覆。AH-S1 在「每個功能未來獨立販售」的方向下會變成必修，建議排進更新流程簡化之前
- **DO4**：演練工具的 drill_stop 會殺到自己（主持已記）。重跑演練前要先修，否則證據的 log 可能被截斷

## 5. 要不要再演練（240d3bbc 鎖／結果檔、0a96c920 AH-S10／S11 沒有演練）

**要，但要等 DM1／DM2 修好後一起做，避免做兩次。** 會起服務，由主持向使用者確認後才跑。
1. P1（成功）用最終版腳本：鎖在結束時被移除；`apply_update_<ts>.result.json` 與 `rollback_snapshots\<ts>` 同名，內容與 `::RESULT::` 相同；DO1 的候選清單
2. P3（自動回滾）：驗 DM1 的 pre_rollback 備份存在，而且含停服前寫入的一筆
3. RB-old：連續套用兩次（第二次新增一個模組），再回滾到第一次的快照 ⇒ 驗 DM2
4. P2m（第十四班合回 B41 之後）：模組 migration 失敗 ⇒ 乾跑擋下（DS2）
5. trap 路徑（DS1）不必演練；有題即可（例外注入在單元層就做得到）

## 6. 重現

```
git worktree add --detach D:\MOTRIX-PLATFORM-D14m 0a96c920
cd D:\MOTRIX-PLATFORM-D14m\backend
D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe -m pytest tests/platform/test_apply_plan_2026_09_28.py tests/test_deploy_outcome_2026_09_23.py -q -n 2 --basetemp=%TEMP%\motrix-pytest-d-h12
# 突變：逐項以唯一錨點取代（assert 次數＝1）→ 跑同兩檔（再加 --deselect ...::test_aho7_script_change_requires_a_version_decision 各跑一次）→ 寫回原內容
# 探針 DM2／DO1：apply_plan.make_plan／cleanup_added 在 %TEMP% 合成兩次套用，見 §2 DM2
```

## 7. 第二輪複核：wip/h-apply-platform ee434e2c（範圍 0a96c920...ee434e2c）（D，2026-09-28）

> 題目 140 過（排除 test_aho7）；突變 16 個（一律 `--deselect test_aho7`），紅 11、存活 5。
> 演練證據 D:\MOTRIX-DRILLS\apply-run-0928\r2_*，**跑在 1307ae09**（ee434e2c 之前）：ee434e2c 只把 plan_refused／plan_tool_missing 分開、另補 RUNBOOK，r2_run_PX.log 的 `plan_failed` 正是這一包要修的誤報。主持提到的 plan_tool_missing 路徑，r2_* 裡沒有找到對應的紀錄。

| 項目 | 讀碼＋題目＋突變＋演練 | 判定 |
|---|---|---|
| DM1 | 自動回滾：停服後 `Backup-DatabasesOnline` 另存 pre_rollback，失敗就不覆寫主庫與 demo 庫（突變 R2 紅）。手動回滾：預設只回程式；`-IncludeDatabase` 還要加 `-ConfirmDatabaseOverwrite`，`-Yes` 不算數（R3 紅）；另存失敗 ⇒ 不動檔、重啟服務（R9 紅）。演練：RB_noconfirm 被擋；RB_db 的 pre_rollback 有標記；P3 的 pre_rollback 有新版建的表 | 成立 |
| DM2 | `cleanup-snapshot`：刪「安裝目錄有、快照沒有」的可刪程式檔；快照裡沒有的頂層目錄略過；有上限，手動回滾先乾跑。R1 紅；演練：P4 之後回滾到 P1 之前，drillmod 與兩頁被清掉 | 成立 |
| DS1 | trap 在 service=down，而且磁碟是 not_applied／applied 時重新啟動；restoring 不動 | 邏輯成立；**沒有題**（R4 存活），見 D2-S1 |
| DS3 | M1、M2、M4、M8 紅；**M3、M9 存活**，見 D2-S2 | 部分成立 |
| DS4 | 值域補齊，並有「狀態 ⊆ 值域」題 | 成立；R10（plan_refused 分支）存活，見 D2-S1 |
| DS5 | 所有寫回都 `/XD certs /XF license.key autostart.bat .apply.lock heartbeat_config.json .deployed_commit.json`，有題。快照這一側也排除，但沒有題（R5 存活）；真正的防線在寫回那一側，所以可以接受 | 成立 |
| DO1 | `.apply.lock` 列進 STATE_FILES；`*.modules_disabled.json` 列進 STATE_SUFFIXES（R8 紅） | 成立 |
| DO2 | 未改：只有 demo 庫的 migration 失敗，照樣擋下正式機更新。D 判斷**維持即可**：乾跑失敗代表新版 migration 有缺陷，在更新前擋下、修好再出包，比讓正式機帶著一個 demo 會壞的版本上線便宜；使用者裁示 AB-S7 講的是啟動時的上下線，不是更新閘門 | 結案（不修） |
| DO3 | 使用者裁示：授權有、而包沒有 ⇒ plan_refused（R6 紅）；未授權 ⇒ 資料夾與頁面只停用不刪（R7 紅）。授權判定用新包的 helpers.licensing 讀正式機的金鑰，與啟動時同一支 | 成立 |

**D2-S1（建議）　trap 重啟與 plan_refused 分流沒有題**：R4（trap 不重啟）與 R10（APPLY_PLAN_REFUSED 不分流）改了都綠。建議照 test_ahs11 的做法：把 trap 取出來，在 PowerShell 裡跑兩個方向——ProdState=applied、service=down ⇒ 呼叫 Start-InstallService；restoring ⇒ 不呼叫。再補一題「輸出含 APPLY_PLAN_REFUSED ⇒ 狀態是 plan_refused」。

**D2-S2（建議）　DS3 結構題有兩處只驗「字串存在」**：
- M3：題目驗的是 `Join-Path $rollbackDir "root_docs"`（變數指派那一行）在不在；把真正的 Copy-Item 那行拿掉照樣綠。改成驗 `Copy-Item $_.FullName -Destination $ProdRoot` 出現在函式本體裡
- M9：題目驗的是 cleanup-snapshot 在寫回之前被呼叫；把 `$cleanFailed` 寫死成 `$false`（忽略清理失敗）照樣綠。補一條：`$cleanFailed` 的判定含 `APPLY_SNAPCLEAN_OK`，而且之後有 `if ($cleanFailed) { Fail … "restore_cleanup_failed" }`

**D2-O1（觀察）　`cleanup-snapshot` 是第一個「依『不在』就刪」、而且範圍涵蓋整個 backend 的動作**：分類預設是 program ⇒ 日後有任何執行期寫檔落在 backend／frontend／tools／product，而且不在 DATA_DIRS 裡，回滾時就會被刪。這一輪查過既有的寫入點：export_archive 屬於 PDF_ARCHIVES、品牌圖在 uploads、停用清單快取屬於 STATE_SUFFIXES，都安全。建議加一道守門：`core.paths` 每個會寫入的常數，classify 都不可以是 program。

**誘餌行程消失（主持要判斷要不要追）**：**不必再追產品碼**。
- 產品碼：Stop-InstallService 在每一次 `Stop-Process` 之前都印「結束 … PID」（apply_update.ps1 的 Stop-InstallService 迴圈）。r2_* 八份紀錄都沒有 33208、14120 ⇒ 不是 apply／rollback 停的
- 另有兩個會讓它們消失的演練工具機制：
  - drill_stop.ps1 設計上就會殺 decoys.txt 列的 PID，以及命令列含演練路徑、或 `--port 6781/6782` 的行程；演練目錄在 03:42:38 收尾
  - decoy1 是 `cmd.exe /c "<演練根>\other\backend\autostart.bat"`，這個檔現在不存在；如果演練時也不存在，cmd 會立刻結束
- 建議：下一次演練在每一條路之後，立刻記錄誘餌是否還活著（`Get-Process -Id`），不要等收尾時才看

**對正式機使用的判定**：H12 本身**通過**（DM1、DM2 關閉；自動回滾、兩種手動回滾、授權拒絕都有演練）。第十四班的包上正式機之前，還差一項：B41 合回後，在合併樹上補 **P2m**（模組 migration 失敗 ⇒ 乾跑擋下），也就是 DS2／AH-S6 的契約題與演練。

### 關閉紀錄（標準格式，PLAYBOOK §E-6）

- ✅ DM1 關閉（ee434e2c）——回滾覆寫資料庫前另存 pre_rollback，失敗就不覆寫；手動回滾預設只回程式，覆寫要另加確認
- ✅ DM2 關閉（ee434e2c）——回滾以快照為準清掉快照沒有的程式檔（cleanup-snapshot），回滾到較舊的快照也清得乾淨
