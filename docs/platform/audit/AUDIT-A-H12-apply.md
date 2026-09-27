# 稽核：H12 apply_update 日常更新安全修正（wip/h-apply-platform 1e7539c6）（A，2026-09-28 01:12）

> 只讀碼，沒有跑任何測試，也沒有改 H12。範圍：`git diff 9350a3df...1e7539c6`（12 檔，+1284／−62）。
> 這一輪在「D 單獨完整稽核」之前，不取代它。行號以 1e7539c6 為準。
> 對照讀過的外部碼：`backend/core/upgrade.py`（classify）、`backend/core/paths.py`、`backend/setup_autostart_task.ps1`、
> `backend/autostart_hidden.vbs`、`backend/tools/_dashboard_remote.ps1`、`tools/platform/module_update.py`；
> 另外讀了 B41（`wip/b-payreq` e70aa612）的 `helpers/module_startup.py`、`core/migrations.py::incomplete`、`helpers/licensing.py`。

## 0. 結論

- **必修 3、建議 6、觀察 6。**
- 主持的 ①～⑤ 大部分成立：
  - 分類：資料、DB、設定永不刪。
  - 超過上限時不動任何檔。
  - 每個要刪的檔在快照裡都要找得到。
  - 自動回滾的順序：停服 → 刪新增 → 寫回 → 兩個庫 → 啟動。
  - 乾跑的停用清單讀試跑的那個庫、授權指到正式機的金鑰、incomplete 為 None 算失敗。
- 缺口集中在三處：
  - Windows 大小寫：只差大小寫的改名會刪掉新檔（AH-M1）。
  - 手動執行的路徑：RUNBOOK 的指令跑到的是舊腳本（AH-M2）。
  - 停服之後的失敗出口：服務停著、迴圈也停著，沒有人把它拉起來（AH-M3）。

## 1. 逐項（主持重點）

| # | 項目 | 讀碼結果 | 判定 |
|---|---|---|---|
| ① | 刪除計畫會不會刪到資料／設定 | `deletable`（apply_plan.py:65）＝在程式目錄內、不是狀態檔、不是 `PACKAGE_DEFAULT_CONFIG`、`classify=="program"`。classify 依 `core.upgrade` 的 DB／DATA_DIRS／`_demo_`／CONFIG 清單判定。另外查過：模組資料夾與 `backend/data` 沒有執行期寫入（grep `dirname(__file__)`、`STATIC_DATA_DIR` 寫檔皆 0）⇒ 孤兒模組資料夾裡不會有資料被當成程式刪掉。`execute` 與 `cleanup_added` 再各自過一次 `deletable`＋`_inside`（:231） | 成立；例外見 AH-M1、AH-S1 |
| ① | 上限、快照核對 | `over_limit` ⇒ exit 3 ⇒ `delete_plan_too_large`，這時還沒停服、沒建快照（ps1:519-521）。`verify-snapshot` 在停服前跑，缺任何一檔就 `snapshot_missing_deleted`（ps1:560-564） | 成立 |
| ② | 自動回滾回到套用前 | 順序（ps1:871-937）：停服含迴圈 → `cleanup-added` → 快照寫回 backend／frontend／tools／product → 根目錄文件 → 主庫＋demo 庫 → 清理失敗就不啟動 → 啟動。`.deployed_files.json` 只在成功時寫（:1004）；回滾時快照裡的舊清單被寫回 | 成立；但 tools 見 AH-O1，設定檔見 AH-S3 |
| ② | 手動回滾 | 同一套流程，加上「快照沒有 baseline ⇒ 刪掉現在那份」（rollback_update.ps1:326-330）。**沒有還原 `.deployed_commit.json`** | 見 AH-S2 |
| ③ | 停服只停本安裝 | 迴圈用完整的 `autostart.bat` 路徑辨認（:202-208）。vbs 以完整路徑、`Run …, 0, False` 啟動 ⇒ wscript 立刻結束，排程工作回到 Ready，`Start-ScheduledTask` 有效。port 反查往上最多 6 層、遇到非 python 就停；非 python 佔用 port 時只警告不殺 | 大致成立；行程樹見 AH-S4，出口見 AH-M3 |
| ④ | 乾跑與正式啟動一致 | `migrate_like_startup` 走 B41 的 `load_modules_like_startup(db_path=試跑庫)`。停用清單的快取檔寫在試跑庫旁，事後刪（ps1:483）。授權：`licensing.LICENSE_PATH` 換成正式機那一份，而 `verify_license` 每次都在函式內讀模組層級的名字。`LICENSE_GATE_ENABLED` 是常數。模組載入不看環境變數（loader／registry／switches 皆無 getenv）⇒ autostart.bat 的環境變數不影響乾跑。incomplete 為 None 或非空都算失敗 | 成立；前提與測試缺口見 AH-S6 |
| ④ | 舊包相容 | 包裡沒有 `migrate_like_startup.py` ⇒ 只跑 init_db（與原本相同）。**包裡沒有 `apply_plan.py` ⇒ `plan_refused`，整包拒絕** | 見 AH-O4 |
| ⑤ | 出口狀態值域與 1:1 | 新增的 11 個值都登記進 `_STATUS_FAILED`，也有題。靜態比對兩支腳本所有 `Fail`／`Emit-Result` 與儀表板集合：**有 6 個既有的值不在集合裡**（靠 fail-closed 仍判失敗） | 見 AH-S5 |

## 2. 必修

**AH-M1（必修）　只差大小寫的改名會刪掉新檔**

- 證據：
  - `make_plan.add`：`if rel in new_set`（apply_plan.py:115）
  - baseline 差集：`set(baseline["files"]) - new_set`（:125）
  - `execute`：`if d["rel"] not in new_set`（:247）
  - 以上三處都是區分大小寫的字串比對，而正式機是 Windows、檔案系統不分大小寫
- 重現（讀碼推演）：
  1. 舊版 baseline 有 `frontend/pages/Foo.html`，新包改名成 `foo.html`
  2. 計畫時：`Foo.html` 不在 new_set，而 `isfile(root/Foo.html)` 為真 ⇒ 列入刪除
  3. `added` 用 `isfile(root/foo.html)` 判斷，不分大小寫 ⇒ 為真 ⇒ 不算新增
  4. Step 3：robocopy 把新內容寫進同一個檔
  5. 接著 `execute` 刪除 `Foo.html`（同一個檔）
  6. ⇒ 新版的 `foo.html` 從磁碟上消失
- 影響：
  - 頁面：`/api/ping` 照樣 200 ⇒ 健康檢查過、不會回滾 ⇒ 靜默 404
  - .py：可能 import 失敗而觸發回滾
  - `verify_snapshot` 也會過，因為快照裡確實有 `Foo.html`
- 修法：
  - 計畫與 execute 都以 `os.path.normcase`（或 `.lower()`）後的鍵比對 new_set
  - 補題：baseline 有 `Foo.html`、包裡是 `foo.html` ⇒ 不列入刪除
  - 反向控制：大小寫不同的不同檔（例如在分大小寫的 tmp 上）照舊判定

**AH-M2（必修）　RUNBOOK §8 的手動指令跑的是安裝目錄裡的舊腳本**

- 證據：
  - UPGRADE-RUNBOOK.md:207 是 `<ROOT>\backend\tools\apply_update.ps1 -PackagePath <包>`
  - 身分守門要求從 ROOT 執行（apply_update.ps1:299）
  - 儀表板先把 `<包>\backend\tools\*` 複製進 ROOT，才呼叫腳本（_dashboard_remote.ps1:117-120）
  - RUNBOOK 的手動路徑沒有這一步
- 後果：
  - 正式機現在是 c006a2a0，它的 apply_update.ps1 是本分支之前的版本
  - 照 §8 手動執行 ⇒ 跑到舊腳本：沒有刪除計畫、殺掉所有 `uvicorn main:app`、迴圈用舊的環境變數把服務拉回來
  - §8 描述的行為一項都不會發生，而 `::PROTOCOL:: v=2` 照印（兩版都印）
- 修法（二選一，建議都做）：
  - RUNBOOK §8 的手動步驟先寫「把 `<包>\backend\tools\*` 複製到 `<ROOT>\backend\tools\`」
  - 腳本開頭比對 `$PSScriptRoot` 與 `$PackagePath\backend\tools` 的 apply_update.ps1／apply_plan.py 雜湊，不同就拒絕並說明

**AH-M3（必修）　停服之後的失敗出口：服務停著、迴圈也停著，沒有自動回滾**

- 證據：
  - `Stop-InstallService`（:595）連迴圈一起停
  - 之後的 `copy_failed_backend`／`copy_failed_frontend`／`copy_failed_root_dirs`（:639／:642／:648）與 `delete_failed`（:667）都直接走 `Fail`（:163-167＝印結果、exit 1）
  - `Start-InstallService` 只在 :725（成功路徑）與 :937（自動回滾）
- 與修改前的差別：
  - 以前迴圈沒停，5 秒後會把服務拉起來（雖然是半套用的程式碼）
  - 現在直到有人手動回滾為止，服務都是停的
  - RUNBOOK 表格寫的處置是「用快照手動回滾」
- 情境：
  - `delete_failed` 發生時，新程式碼已經完整複製（只剩部分舊檔沒刪掉）
  - 這時直接進健康檢查、或走自動回滾都比停著好
  - 快照與計畫都已備妥，自動回滾的條件齊全
- 修法：這四個出口改走自動回滾的同一段（或至少 `delete_failed` 繼續到健康檢查）；出口值維持各自的名字（1:1 不變），`rolled_back` 如實記錄。

## 3. 建議

**AH-S1　孤兒模組刪除沒有看 module_update 的安裝紀錄**

- 事實：
  - `module_update.py apply` 可以安裝完整包裡沒有的模組
  - 它的 preflight 只在已安裝時比版本（module_update.py:191），所以沒裝過的也可以裝
  - 它在 `<ROOT>/module_backups/<key>/<時間>/apply.json` 留紀錄
- 問題：
  - `make_plan` 把「安裝目錄有、包裡沒有」的模組一律當孤兒刪除（apply_plan.py:138-140）
  - 儀表板帶 `-Yes` 時不會有人讀清單
  - 刪掉的是買來的加購模組，而且它的頁面（在 `frontend/pages`、不在模組資料夾）會留下
- 另一個相關問題（既有，不是 H12 引入）：模組經 module_update 升到比包更新的版本時，robocopy 會用包裡的舊版蓋回去
- 建議：孤兒模組若在 `module_backups/<key>` 有紀錄、又不在 lock 的 excluded ⇒ `plan_refused` 並說明（或要求明確的參數）。

**AH-S2　手動回滾沒有還原 `.deployed_commit.json`**

- 事實：快照排除它（ps1:547 `/XF`），回滾也不改寫它（rollback_update.ps1 全檔沒有出現）
- 後果：
  - 手動回滾後，`/api/prod-status` 與部署紀錄仍是新版的 commit
  - 下一次套用同一版會被 `duplicate_version` 擋下
  - 這是既有缺口，但屬於 ② 的範圍
- 建議：回滾成功後寫回套用前那一份（apply_update 在 :339-340 已讀到 `$prevDeployed`，可以存進快照）。

**AH-S3　回滾會把設定檔還原成快照當時的版本**

- 事實：
  - 程式快照 `robocopy backend /E` 只排除 `heartbeat_config.json`、`.deployed_commit.json` 與資料目錄（ps1:547）
  - 所以 `license.key`、`certs/`、`.initial_*_credentials.txt`、`autostart.bat` 都在快照裡，回滾時寫回
  - 套用本身不動它們；autostart.bat 本輪還刻意保留機器上的版本
- 後果：手動回滾若發生在套用幾天之後，期間換過的授權金鑰、憑證、對外連線開關會被靜默改回舊值。舊授權過期時，模組在回滾後就被擋住。
- 建議：快照或寫回時依 `classify=="config"` 排除（與轉換的規則一致）。

**AH-S4　行程樹用 ParentProcessId 展開，沒有核對建立時間**

- 事實：`Add-Tree`（ps1:227-233）把 `ParentProcessId == 目標 PID` 的行程都當成子行程
- 風險：
  - Windows 的父 PID 在父行程結束後會保留
  - PID 被回收時，一個早已與它無關的行程（父行程早於迴圈 cmd 結束，而 PID 恰好被迴圈 cmd 取得）會被當成子行程一起結束
- 建議：只收 `CreationDate` 晚於父行程的子行程。這是業界常見的 PID 回收防護。

**AH-S5　出口狀態值域：6 個既有的值不在儀表板集合裡**

- 靜態比對結果：
  - `snapshot_failed_backend`／`snapshot_failed_frontend`
  - `restore_copy_failed_backend`／`restore_copy_failed_frontend`
  - `rollback_copy_failed_backend`／`rollback_copy_failed_frontend`
  - 以上都不在 `_STATUS_FAILED`
- 現況：儀表板 `status not in _STATUS_ALL ⇒ failed`（deploy_dashboard.py:480）⇒ 判定結果正確，但值域登記不完整
- 另外：RUNBOOK §8 的狀態表沒列 `copy_failed_backend`／`copy_failed_frontend`
- 建議：
  - 補齊集合
  - 加一題「兩支腳本的每個 `Fail`／`Emit-Result` 狀態 ⊆ `_STATUS_ALL`」，並附反向控制：合成一個未登記的值 ⇒ 紅

**AH-S6　乾跑的「照啟動規則載入模組」在 H12 樹上沒有任何一題實際執行**

- 事實：
  - `helpers/module_startup.py` 不在 H12，也不在 origin/platform，只在 B41
  - H12 的題只驗偵測（test_apply_plan:243）與沒有 module_startup 的路徑（:265）
  - 模組化那一支（授權覆寫、`UNREADABLE_REASON`、`incomplete` 為 None／非空）的判定沒有題
- 合回順序：
  - H12 先合 ⇒ 那一支處於休眠，行為等於舊版。RUNBOOK「已知限制」已寫明，這點成立
  - 但兩邊合回之後要有一道契約題：B41 改了 `incomplete` 的形狀，H12 的判定要跟著紅
- 建議：B41 與 H12 都合回之後補一題，驗以下四件事：
  - 未完成的 migration ⇒ `MIGRATE_LIKE_STARTUP_FAIL`
  - 沒跑過（None）⇒ FAIL
  - 停用清單讀不到 ⇒ FAIL
  - 授權路徑確實換成 `--license`

## 4. 觀察

- **AH-O1**：儀表板在呼叫前就把包裡的 `backend\tools\*` 複製進正式機（_dashboard_remote.ps1:117-120），早於程式快照。
  - ⇒ 快照裡的 tools 已經是新版，回滾後 tools 仍是新版（對回滾工具本身反而有利）
  - ⇒ `plan_refused` 等出口說的「正式機尚未被觸碰」嚴格來說不成立：backend\tools 已經被換過
- **AH-O2**：robocopy 的 `/XD logs uploads 報價單PDF export_archive backup_alerts _demo_* …` 以目錄名稱比對，任何深度都算。
  - 目前 `git ls-files` 的程式目錄沒有與這些名稱相撞的（已查）
  - 日後若有模組建立 `logs`／`uploads` 子資料夾，它會靜默不被安裝，也不進快照
- **AH-O3**：乾跑（`import db`、載入模組）與 `apply_plan`（import `core.upgrade`）在**包目錄**執行，會在包裡寫 `__pycache__`。
  - Step 3 的 backend robocopy 沒有 `/XD __pycache__` ⇒ .pyc 一起進正式機
  - 由同一份原始碼編譯、無害，但與 D7「包內無 pyc」的判準不一致。import db 的部分是既有行為
- **AH-O4**：沒有 `apply_plan.py` 的包一律 `plan_refused` ⇒ 本分支之前建的包（含 c006a2a0）不能再用 apply_update 重新套用。
  - 恢復要走 rollback_update
  - 建議 RUNBOOK §8「已知限制」寫一句
- **AH-O5**：主庫不在、只有 demo 庫時，`dbs[0]` 是 demo 庫 ⇒ 停用清單讀 demo 庫（migrate_like_startup.py:43）。實務上不會發生，記錄備查。
- **AH-O6**：port 被非 python 程式佔用時只警告、繼續（ps1:238-240）。之後的健康檢查打到的是那個程式；它不會回 `/api/ping` 的正確內容，所以結果是回滾，不是假綠。記錄備查。

## 5. 給 D 單獨稽核的建議驗證點（這一輪沒跑）

1. AH-M1：在 Windows 暫存目錄合成 baseline `Foo.html`＋包 `foo.html`，跑 plan＋execute ⇒ 目前會刪掉；修正後不刪。
2. AH-M3：三條路演練加第四條——在 execute 前讓一個要刪的檔被占用（開著不放）⇒ `delete_failed`，觀察服務狀態。
3. 手動回滾之後打 `/api/prod-status`，看 commit（AH-S2）。
4. `Stop-InstallService`：同機另開一個 `uvicorn main:app --port 8866`，確認不會被停；排程工作 Ready／Running 兩種狀態下各重啟一次。
