# 單一模組更新包上線：簽章交付＋正式機同等保護（設計，未實作）

> B，2026-09-28。依據：CORE-SPEC「單一模組更新包上線（正式機可用）」列（a8ec2b4b）、「出貨前測試依改動範圍分級」列、「完整包與客戶加購模組」列。
> 本文件只寫設計；D 審過再實作。沿用 UPDATE-DELIVERY.md（完整包交付）的通道、簽章、儀表板與結果協定，**只寫與完整包不同的地方**。
> **第二版（D 設計審 AUDIT-D-B55-module-delivery.md，wip/d-audit-train16 6b7d7552；主持裁示）**：DB-M1 照 D（疊加樹改白名單）；U-M1＝②、U-M2＝②；DB-S3～S6 全收；U-M4～M6＝①；DB-M2 實作成可切換的判斷點（§4.3），第二版預設乙；**第三版：使用者裁示＝甲（CORE-SPEC ee383527），預設改 consumers**。各處改動以〔D 審〕標示，原文保留在 git 歷史（2ab3585d）。
> 現況盤點（2026-09-28 讀碼）：`tools/platform/module_update.py`（P7）有 build／check／preflight／apply／rollback（備份到 `module_backups/<key>/<ts>/`、雜湊逐一核對），但沒有鎖、停服、健檢、自動回滾、`::RESULT::`；遇到 `migrations/` 一律拒絕（P7b）。`delivery.py` 沒有包型別，`verify_staged`／`apply_staged` 假設完整包（要 `payload/backend/tools`、跑 `apply_update.ps1`）。

## 0. 邊界與不變式

- 單模組包**只含** `backend/modules/<key>/`（不含 tests／SPEC.md／__pycache__，照 module_update 既有排除）＋ module.json 宣告的頁面＋`module-update.lock.json`。**不含任何 tools、L0／L1、main.py**。
- ⇒ 推論（🔴 順序限制）：正式機要先有一版**完整包**帶上本設計的新工具（`apply_module_update.ps1`、改過的 `delivery.py`／`deploy_dashboard.py`／`module_update.py`），之後才收得了單模組包。單模組包永遠不更新套用工具本身。
- 判定「能不能出單模組包」由工具依 git diff 決定，不靠人工（§4）；判不了 ⇒ 拒絕（必須完整包）。
- 正式機的動作由使用者在正式機儀表板按下（PLAYBOOK §C-10），與完整包同一個畫面、同一套 superadmin 驗證與確認。
- 模組 migration 只准新增（CORE-SPEC §6）；套用失敗時 DB 還原到套用前快照（與完整包相同）。
- 〔D 審 DB-S1＝U-M1②〕**這一包不動 `apply_update.ps1`／`rollback_update.ps1`**：新腳本複製共用函式、守門題逐字比對（§5）。
- 〔D 審 DB-S2＝U-M2②〕正式機的腳本**沒有任何繞過身分守門的分支**；演練用副本改寫常數（§7）。

## 1. 步驟清單

### 1.1 開發機：建包（`module_update.py build`＋新增判定）

1. 取得**正式機目前的 commit** P：`delivery.latest_prod_commit()`（交付資料夾 results 中最新一筆 succeeded）；讀不到 ⇒ 拒絕（不退回 tests/_prod_baseline 猜）。另讀正式機已套用的模組覆蓋紀錄（§3 `deployed_modules`，隨結果寫回）。
2. 分級判定 `tier(P, X, key)`（§4）：X＝要出貨的 commit。結果不是「②單一模組 key」⇒ 拒絕，印出越界的檔。
3. 出貨前測試（第②級）：該模組的題（`backend/modules/<key>/tests`）＋`backend/tests/platform`＋該模組宣告頁面的 e2e（用 test_map 的 page→e2e 對應）〔D 審 DB-M2：＋ 判斷點「提供者有改」預設甲（使用者裁示）：提供者有改 ⇒ 加所有消費端模組的題；消費端判定不了 ⇒ 退回乙，在步驟 2 判③拒絕。見 §4.3〕。-n 2、低優先權、basetemp 用完刪。紅 ⇒ 拒絕。結果摘要（題數、passed、耗時、tree 雜湊）寫進 delivery.json。
4. `module_update.build(key, out, commit=X)`（既有）產生包目錄；lock 另加 `prod_base_commit: P`、`tier: "module"`、`tests: {...}`。
5. `delivery.py publish --kind module`：payload＝上述包目錄；`delivery.json` 加 `kind:"module"`、`module:{key, version, core, built_from:X, prod_base_commit:P, from_version:<P 時的版本>}`、`min_apply_module_script:<版本>`（**在簽章範圍內**）；包名 `<ts>_<commit8>_mod-<key>`（符合既有 `NAME_RE`，不改正則）。不要求 payload 有 apply_update.ps1（`script_version` 檢查只對 full）。

### 1.2 正式機：偵測、驗證（`delivery.verify_staged` 依 kind 分支）

1. 偵測、staging、簽章、逐檔雜湊、清單外多檔：**與完整包同一段程式**（不分支）。
2. `kind` 缺席 ⇒ 視為 `full`（舊包相容）；不認得的 kind ⇒ 拒絕。
3. kind＝module：
   - 已安裝的 `apply_module_update.ps1` 版本 ≥ `min_apply_module_script`，否則「正式機套用工具太舊，請先套用完整包」。
   - `module_update.check(payload)`（包自身一致）＋`preflight(install_root, payload)`（唯讀：安裝目錄 lock 存在、core 相容、版本高於已安裝）。
   - `prod_base_commit` 必須等於正式機 `.deployed_commit.json` 的 commit（否則「這個包是對另一版正式機做的」⇒ 拒絕；§3 的覆蓋紀錄不影響此比對）。
   - 「已是這一版」：安裝目錄 lock 的 `modules[key].sha256` 等於包的 ⇒ 顯示、不可按。
   - 不跑 `verify_package`（完整包結構檢查，不適用）。
4. 畫面摘要：模組名、版本 舊→新、頁面清單、是否帶 migration、出貨前測試摘要。

### 1.3 正式機：套用（新腳本 `backend/tools/apply_module_update.ps1`）

依序（每一步的失敗出口見 §2）：

0. 身分守門（同 apply_update：`$ProdRoot`）；`::PROTOCOL:: v=2`。
1. 參數與包：`-PackagePath -Yes [-SkipAutoRollback]`；包裡必須有 `module-update.lock.json`，kind＝module_update。
2. **鎖**：`backend\.apply.lock`，與 apply_update／rollback_update **同一把**（同一段 `Enter-InstallLock`；完整包與模組包互斥）。
3. 預檢：`python module_update.py preflight`（新增子命令，只讀，回 exit 碼＋一行原因）。
4. DB 快照：`Backup-DatabasesOnline` 到 `db_backups\pre_module_<key>_<ts>\`（主庫＋demo 庫）。
5. Migration 乾跑（包帶 `migrations/` 時才跑；沒帶也跑一次載入檢查，見下）：
   - 在 `%TEMP%\motrix-modapply-<ts>\` 建**疊加樹**〔D 審 DB-M1：黑名單改白名單〕：只複製安裝目錄 `backend\` 底下 `core.upgrade.classify(rel) == "program"` 的檔（與 apply_plan `deletable` 同一支判定，用**已安裝**的 core.upgrade）→ 以包的 `modules\<key>` 取代；DB 只放快照副本（不從安裝目錄複製任何 db／data／config）。
     - 讀碼實測（2026-09-28，classify 逐一打）：`backend/export_archive/*`、`backend/_demo_*`、`backend/logs/*`、`backend/db_backups/*`、`backend/rollback_snapshots/*` ⇒ data；`.initial_admin_credentials.txt`、`.initial_demo_credentials.txt`、`heartbeat_config.json`、`license.key`、`certs/*`、`.deployed_commit.json` ⇒ config ⇒ 都不進疊加樹。uploads／PDF 資料夾在安裝根目錄、不在 backend ⇒ 本來就不在複製範圍。
     - ⚠ 仍會被判 program 而進疊加樹的非程式檔：`backend/.apply.lock`、`backend/<主庫>.modules_disabled.json`（停用清單快取，只含模組代號）、`backend/.deployed_files.json`、`backend/.deployed_modules.json`。都不含個資；疊加樹另排除 `.apply.lock`（避免乾跑的載入器誤判）。
     - 疊加樹在 finally 刪；程序中斷時殘留的只有程式檔與 DB 快照副本 ⇒ DB 副本另放 `%TEMP%\motrix-modapply-<ts>-db\`，下一次套用開頭先清掉同前綴的殘留目錄（只清 `motrix-modapply-` 前綴、且 `.apply.lock` 不在時）。
   - 以**已安裝**的 `migrate_like_startup.py --db <快照副本> --license <license.key 唯讀>` 在疊加樹上跑（cwd＝疊加樹）；必須 `DRYRUN_OK` 且 `incomplete` 為空。
   - 同一步驗「模組載得起來」：疊加樹上 `core.loader.load_all()` 之後該模組 state＝loaded、版本＝新版（乾跑工具加一個 `--expect-module key=version` 選項，印 `MODULE_LOAD_OK`）。
   - 刪疊加樹與副本（finally）。
6. 停服：`Stop-InstallService`（同 apply_update，只停本安裝）。
7. 換檔：`python module_update.py apply --root $ProdRoot --pkg $PackagePath`（既有：先備份到 `<ROOT>\module_backups\<key>\<ts>\`，再換模組資料夾與頁面、改安裝目錄 lock 的 `modules[key]`／`excluded`）。開始前 `ProdState=applied_no_restore`，成功後 `applied`。
   - 〔D 審 DB-S6〕**鏡像**：現行 apply 已是「整個模組資料夾 rmtree 後 copytree」＋「刪舊版宣告的頁面、放新版宣告的頁面」＝鏡像（module_update.py:217-227）⇒ 新版刪掉的檔不會留著；寫進 docstring 並加題（v2 刪掉 v1 的一個檔 ⇒ 套用後不在）。
   - 〔D 審 DB-S6〕**baseline**：同步改 `backend\.deployed_files.json`（完整包的刪除計畫基準）裡 `backend/modules/<key>/` 那一段與宣告頁面（換成套用後的清單）；改前的那一段存進備份目錄 `baseline_before.json`，回滾時還原。之後的完整包刪除計畫因此對得上（加題：模組包 v2 之後套完整包，刪除計畫不報多餘檔也不漏）。
   - 備份位置 `<ROOT>\module_backups\` 在安裝根目錄、不在 apply_plan 的 PROGRAM_SCOPES（backend／frontend／tools／product）⇒ 完整包的刪除計畫與 cleanup-snapshot 碰不到它。
8. 重啟：`Start-InstallService`。
9. 健檢（比完整包多一層）：
   - ping：同 apply_update（20 次）。
   - 〔D 審 DB-S4〕**第一道：機器可讀的載入狀態**。L1 新增：啟動完成（mount_modules 之後）寫 `backend\logs\module_states.json`＝`{pid, started_at, modules:[{key, state, version, reason}]}`（由 `registry.module_states()` 產生；先寫 .tmp 再改名）。健檢要求：檔案的 `started_at` 晚於步驟 8 重啟那一刻、`pid` 是正在聽 666 的那個行程、該模組 `state=loaded` 且 `version`＝新版。等不到（逾時同 ping）⇒ 判失敗。（loader 對單一模組壞掉是隔離的 ⇒ ping 會過，只看 ping 會把「模組沒載入」判成功）
   - 第二道：server.log 的 `模組 <key> <新版本> 已載入`／`模組 <key> 未載入`（兩道都要過）；另沿用 Traceback／ERROR 掃描。loader 兩個格式字串照樣有守門題。
   - 這是 L1 改動（main.py 或 core/loader）⇒ 屬第③級，隨「先套一版帶新工具的完整包」一起上。
   - 模組宣告了 `provides.probes` ⇒ 逐一打（本機、不需登入者才打；需要登入的只記錄不判）。
10. 成功：寫 `backend\.deployed_modules.json`（§3），`Emit-Result success`。套用成功時把 version_manifest 條目以文字插入（U-M5①，§3）。
11. 健檢失敗 ⇒ 自動回滾（§2 R 系列）：停服 → `module_update.py rollback --stamp <本次>`（雜湊逐一核對）→ DB 還原（先另存 pre_rollback，同 apply_update）→ 重啟 → ping＋「舊版本已載入」檢查 → `unhealthy_rolled_back`。
12. 結果檔 `backend\logs\apply_module_update_<ts>.result.json`：apply_update 的 12 欄＋`kind:"module"`、`module_key`、`from_version`、`to_version`。stdout 最後一行 `::RESULT::` 四欄與檔案一致（同 `RESULT_CORE` 比對）。

### 1.4 儀表板與寫回

- `apply_staged` 依 kind 分派：module ⇒ 不複製 tools（包裡沒有），直接跑**已安裝**的 `apply_module_update.ps1`；逾時 20 分（不自動中止，同完整包原則）。
- `find_result` 依腳本名找 `apply_module_update_*.result.json`。
- `write_back` 多帶 `kind`、`module_key`、`to_version`。
- 開發機 `/api/prod-status`：`latest_prod_commit` 只取 kind＝full（或缺席）的 succeeded；另列「正式機模組覆蓋」＝kind＝module 且在最新 full 之後的 succeeded 紀錄（顯示「commit P＋tender_radar 1.3.4」）。

## 2. 失敗模式表

「正式機狀態」欄＝`::RESULT::` 的 `rolled_back` 值。沿用既有 status 名的以（沿用）標示；新 status 一律加進 `deploy_dashboard._STATUS_FAILED`（值域封閉）。

| # | 情境 | 偵測點 | 處置／回滾 | status | rolled_back | service |
|---|---|---|---|---|---|---|
| F1 | 不在正式機 | 身分守門 | 不動 | not_prod_machine（沿用） | not_applied | unknown |
| F2 | 參數缺、包不存在、lock 不是 module_update | 開頭 | 不動 | bad_args／package_missing／package_invalid（沿用） | not_applied | unknown |
| F3 | 另一個套用進行中／殘留鎖 | `.apply.lock` | 不動；殘留鎖不自動清 | apply_locked／apply_locked_stale（沿用） | not_applied | unknown |
| F4 | core 不相容、版本不高於已安裝、安裝目錄沒有 lock | preflight | 不動 | module_preflight_failed（新） | not_applied | up |
| F5 | 同一版（sha256 相同） | preflight | 不動 | duplicate_version（沿用） | not_applied | up |
| F6 | DB 快照失敗 | 步驟 4 | 不動 | backup_failed（沿用） | not_applied | up |
| F7 | migration 乾跑失敗／incomplete 非空／模組載入乾跑不是 loaded | 步驟 5 | 不動；疊加樹刪除 | migration_dryrun_failed（沿用）／module_load_dryrun_failed（新） | not_applied | up |
| F8 | 使用者取消 | 確認 | 不動 | user_cancelled（沿用） | not_applied | up |
| F9 | 換檔中途失敗（備份寫不進、copytree 失敗、lock 寫不進） | 步驟 7 | `module_update rollback`（本次 stamp）→ 重啟 → ping | module_copy_failed（新） | restored／restored_unhealthy；回滾本身失敗 ⇒ applied_no_restore | 依觀察 |
| F10 | 重啟後 ping 不過 | 步驟 9 | R：停服 → 模組回滾 → DB 還原 → 重啟 → ping | unhealthy_rolled_back（沿用） | restored／restored_unhealthy | 依觀察 |
| F11 | ping 過、但模組沒載入／版本不對／probe 失敗（**完整包沒有的一種**） | 步驟 9 | 同 R | module_unhealthy_rolled_back（新） | restored／restored_unhealthy | 依觀察 |
| F12 | 帶 -SkipAutoRollback 且健檢失敗 | 步驟 9 | 不回滾 | unhealthy_not_rolled_back（沿用，exit 0 行為照舊） | applied | 依觀察 |
| F13 | 回滾時備份雜湊不符（備份損壞） | R | 〔D 審 DB-S5〕停止回滾 → **把該模組寫進停用清單**（`helpers.module_switches.set_enabled(key, False)`，與模組管理頁同一機制）→ 重啟 → 確認 module_states.json 裡它是 disabled、其他照常；列出不符的檔，畫面請人處理 | module_restore_failed（新） | applied_no_restore | 依觀察 |
| F14 | 回滾時 DB 另存失敗 | R | 不覆寫 DB（同 apply_update）；程式已回滾 | unhealthy_rolled_back＋訊息（沿用） | restored_unhealthy | 依觀察 |
| F15 | 未預期例外 | trap | 服務是 down 且未開始換檔 ⇒ 重啟 | unhandled_exception（沿用） | 當時的 ProdState | 依觀察 |
| F16 | 包簽章不符／雜湊不符／kind 不認得／工具太舊／base commit 不符 | 儀表板驗證（腳本前） | 不提供套用；包移 rejected | （儀表板層，不產生 ::RESULT::） | — | — |

- F13 與 apply_update 的 `restore_cleanup_failed`（不重啟）**刻意不同**〔D 審 DB-S5，取代原「直接重啟」〕：半新半舊的檔很可能 import 得起來而行為是混的，新版 migration 也可能已對正式庫跑過 ⇒ 不能讓它載入；但其他模組與 L1 沒有理由跟著停 ⇒ 先停用該模組再重啟。停用寫入失敗 ⇒ 不重啟（退回 apply_update 的保守行為），status 同一個、訊息寫明。
- 停用後的解除：人修好（或重新套用完整包）後在模組管理頁啟用；畫面訊息寫這一步。
- 回滾範圍＝該模組資料夾＋宣告頁面＋安裝目錄 lock 的 `modules[key]`／`excluded`＋DB；不動其他任何檔。

## 3. 與完整包、lock 的關係（照「完整包與客戶加購模組」列）

- 安裝目錄的 `backend/modules.lock.json`（kind 仍是 full_package）是**唯一的事實**：module_update apply 改 `modules[key]`（版本、sha256）、從 `excluded` 移除；回滾還原。
- 新增 `backend/.deployed_modules.json`：`{key: {version, built_from, prod_base_commit, applied_at, result_ts}}`，記在某個完整包之上套用的模組包。
  - 〔D 審 DB-S1 連帶〕**不靠 apply_update 清空**（這一包不動 apply_update）：讀取端只認 `prod_base_commit`＝目前 `.deployed_commit.json` commit 的條目，其餘視為過期（完整包換了 commit ⇒ 自動全部過期）。模組包套用時順手刪掉過期條目。
  - 〔D 審 DB-O1〕分類：加進 `core.upgrade.CONFIG_FILES`（與 `.deployed_commit.json` 同類：「這台機器套用過什麼」）。兩種回滾各自的行為：
    - 模組回滾（本設計）：還原備份目錄裡的 `deployed_modules_before.json`（套用前那一份），逐位元組相同。
    - 完整包回滾（apply_update，不改它）：它是 config ⇒ cleanup-snapshot 不刪；程式快照的 robocopy 沒有排除它 ⇒ 快照裡是套用完整包之前的那一份 ⇒ 還原成那一份，而模組資料夾也回到同一個快照 ⇒ 兩者一致。加題釘住這個推演（快照含它、cleanup 不刪它）。
    - V9→新版轉換不會有它（新裝）。
  - ⚠ `CONFIG_FILES` 在 core/upgrade（L1）⇒ 第③級，隨帶新工具的完整包一起上。
- 〔U-M5①〕version_manifest：包帶該模組的新條目（`module_update build` 取 X 的 version_manifest 裡 P 沒有、而且 module＝<key> 的條目；有其他模組的新條目 ⇒ 分級判③，§4）。套用成功後以**文字插入**安裝目錄 `backend/version_manifest.json` 開頭（〈共用 JSON 用文字插入〉：不 json.dumps 整份重寫）；插入前把原檔存進備份目錄，回滾時整檔還原（逐位元組）。加題：插入後其他行逐位元組不變；回滾後整檔相同。
- **版本比對不互相覆蓋**：
  - 完整包套用前（apply_plan，新增一條 Refuse）：新包的 `modules[key].version` < 安裝目錄 lock 的版本 ⇒ 拒絕並列出（「正式機的 tender_radar 1.3.4 是單模組更新，這個完整包帶 1.3.3 ⇒ 請用含 1.3.4 的 commit 重建」）。等於 ⇒ 照常（sha256 不同也照常：完整包是事實來源）。
  - 單模組包套用前：版本必須高於安裝目錄 lock（既有 preflight）；`prod_base_commit`＝正式機 commit（§1.2）。
  - 授權：模組包的 key 不在授權內 ⇒ preflight 拒絕（沿用完整包的授權判斷函式，閘門關閉視為全部有授權）；已被完整包列為 kept（未授權保留）的模組也拒絕。
- 快照與保留：模組備份在 `module_backups\<key>\<ts>\`，每模組保留最新 5 份（同 rollback_snapshots）；DB 快照 `pre_module_*` 與 `pre_update_*` 同一套保留規則。

## 4. 測試分級判定（`tools/platform/ship_tier.py`，建包與 modtest 共用）

- 輸入：`git diff --name-only --no-renames P X`（P＝正式機 commit，X＝出貨 commit）＋ X 時的 modules.json／module.json。
- 分類（每個檔一個類別，取最嚴者）：

| 類別 | 檔案 | 等級 |
|---|---|---|
| doc | 〔D 審 DB-S3：改以「完整包不出貨的路徑」判定，不看副檔名〕`.gitattributes` 的 export-ignore 樣式命中者（docs/**、backend/tests/**、backend/conftest.py、backend/modules/*/tests/**、backend/modules/*/SPEC.md、requirements-dev…）＋ build_deploy_package 的建包精簡規則會移除者；兩者由工具**讀原檔**取得（不在 ship_tier 裡另抄一份清單）。⚠ 其中 fixture 層（conftest、pytest.ini、requirements*）與 `tools/**` 雖不出貨，照舊判③（它們改變測試環境或建包工具，先於本規則比對） | ① |
| module:<k> | `backend/modules/<k>/**` | ② |
| page:<k> | `frontend/**` 且被**恰好一個**模組 <k> 的 module.json `pages` 宣告（X 或 P 任一版宣告即算） | ② |
| manifest | `backend/version_manifest.json`，且 P→X 新增的條目 module 都屬同一個 <k>（JSON 層比對） | ②（跟著 <k>） |
| 其他一切 | L0／L1（`backend/core`、`helpers`、`routers`、`backend/*.py` 含 main.py）、`backend/tools/**`、`tools/**`、fixture 層（`modtest.FIXTURE_LAYER`）、requirements、`frontend/static/**`、未被宣告或被多個模組宣告的頁面、其他模組的 version_manifest 條目 | ③ |

- 分類順序：路徑規則先於副檔名（`backend/modules/<k>/README.md` 屬 module:<k>，因為它會隨包出貨）。
- **已套用的模組覆蓋要扣掉**：正式機在 P 之上已套過模組包（`.deployed_modules.json`）時，P→X 的差異會含那些模組的改動。對每個覆蓋模組 <m>：X 裡 `backend/modules/<m>/`（排除 tests 等，同打包規則）的資料夾雜湊＝正式機 lock 的 `modules[m].sha256`，且 <m> 宣告頁面雜湊相同 ⇒ 那些檔視為「已在正式機」，不計入；不相等 ⇒ 照常計入（會判 3 或判成兩個模組）。
- 判定：全部 ① ⇒ tier 1；只有 ①＋同一個 <k> 的 ② ⇒ tier 2（key＝<k>）；其他 ⇒ tier 3（輸出越界檔清單）。兩個以上模組 ⇒ tier 3（不出多模組包）。
- 單模組包工具：tier≠2 ⇒ **拒絕**（exit 3，印「必須完整包：<越界檔>」）。tier 1（只改文件）⇒ 也拒絕出包（沒有東西要出貨）。
- 判定邏輯抽純函式 `classify(files, pages_by_module) -> (tier, key, offenders)`，不碰 git，才測得到各種組合。
- **反向控制題**（每一條都要能讓判定變嚴）：改 L1 一行（helpers/geo.py）⇒ 3；main.py ⇒ 3；conftest.py ⇒ 3；requirements ⇒ 3；`backend/tools/apply_update.ps1` ⇒ 3；另一個模組一行 ⇒ 3；兩個模組 ⇒ 3；`frontend/static/*.js` ⇒ 3；未宣告頁面 ⇒ 3；version_manifest 夾帶別的模組條目 ⇒ 3；只改該模組＋其宣告頁面＋.md ⇒ 2；只改 .md ⇒ 1；模組資料夾內的 README.md ⇒ 2（不是 1）；正式機已覆蓋 A 且雜湊相等、這次改 B ⇒ 2（key＝B）；已覆蓋 A 但 X 的 A 又改過 ⇒ 3。突變：把「其他一切 ⇒ 3」改成 ⇒ 2 必須有題紅；把「頁面恰好一個模組」改成「至少一個」必須有題紅。
- 正對照：以實際 repo 的一段真實歷史（某個只改 tender_radar 的 commit 對其父）跑一次，必須判 2（〈盤點工具的正對照〉）。
- 〔D 審 DB-S3〕反向控制加：根目錄一個 .md 若**不在** export-ignore 內（會出貨）⇒ 不是 doc ⇒ 3；`docs/x.md` ⇒ 1；模組內的 `tests/test_x.py` 單獨改 ⇒ 屬 export-ignore，但路徑在 `backend/modules/<k>/` ⇒ 仍算 module:<k>（題要跑，判 2 不判 1）。

### 4.3 判斷點「提供者有改」（D 審 DB-M2；**使用者裁示＝甲**，CORE-SPEC ee383527）

- 問題：模組 <k> 以 `ModuleSpec.providers` 提供串接點（`core.registry.provide(capability, name, fn)`，INTEGRATION-POINTS）給其他模組；只出 <k> 時正式機是「<k> 新＋消費端舊」，而第②級的題不跑消費端。
- 判定「提供者有改」（保守、可機器算）：<k> 在 P 或 X 的**能力清單**非空（定義見下方〔D 複審 DB2-M1〕；讀不出來 ⇒ 當成有）**而且** P→X 改到 <k> 的任何 `.py`（不含 tests）。只改頁面／文件／module.json 的非 provides 欄位 ⇒ 不算。
- 設定點：`ship_tier.PROVIDER_CHANGE_POLICY = "consumers"`（甲，**預設**，使用者裁示）｜`"reject"`（乙）。〔更正：第二版寫「預設乙」，使用者裁示後改甲〕**只在這一處**；工具與題都讀它（不在別處寫死）。
  - 乙：判③，拒絕出單模組包，訊息「<k> 提供串接點 <capability…> 給其他模組，而這次改到它的程式 ⇒ 必須完整包」。
  - 甲：仍判②，但第②級題目加上**消費端的題**（定義見下方〔D 複審 DB2-M1〕）。
  - 〔第二版原文，D 複審判太窄：「消費端＝其他模組的 `.py` 裡以字串常數呼叫 `registry.providers("<cap>")`／`registry.provider("<cap>")`」——`core.registry` 沒有 `provider()`；漏了最常用的 `single_provider`；也漏了 import 時登記的提供者〕

#### 〔D 複審 DB2-M1〕能力清單與消費端的取法

- **能力清單**（<k> 提供了哪些 capability）＝
  - `ModuleSpec.providers` 的 key（`__init__.py` AST；key 是 `(capability, name)` tuple，取第一項）
  - ∪ <k> 資料夾內任何 `.py` 在**模組層**呼叫 `registry.provide(cap, …)` 的 cap（例：arap `invoice_vouchers.py:870`／`payment_requests.py:908` 的 `calendar.writeback`、`invoice_vouchers.py:958` 的 `attachments.for_document`）
  - cap 引數要解析成字串（見下方「解析」）；有任何一個 provide 呼叫的 cap 解析不了 ⇒ **判不了 ⇒ 退回乙**。
- **取用函式清單**：不在 ship_tier 手抄。由 `backend/core/registry.py` 產生：檔頭 `[公開介面]` 列出、而且第一個參數名是 `capability` 的函式，扣掉登記用的 `provide` ⇒ 今天是 `{providers, single_provider}`；registry 日後新增任何「以 capability 取提供者」的函式會自動納入（寧可多選題）。守門題：產生出來的集合必須包含 `providers`、`single_provider`（正對照），而且 `provide` 不在裡面。
- **消費端**＝在 <k> 以外的全部後端程式（`backend/**/*.py`，含 L1 helpers／routers／core／main 與其他模組；不含任何 tests）中，呼叫取用函式、而且 cap 解析後屬於 <k> 能力清單的**檔案**。
- **解析**（AST，逐檔）：
  - 呼叫形式：`registry.X(...)`、`_registry.X(...)`、任何別名（`from core import registry as R` ⇒ `R.X`；`import core.registry as r` ⇒ `r.X`；`from core.registry import single_provider as sp` ⇒ `sp(...)`）。以 import 表解析名稱，不靠字面 `registry`。
  - cap 引數：字串常數；同檔模組層 `NAME = "..."` 的名稱（例 `helpers/case_access.py:81/86` 的 `CASE_PRESENT`）；以 import 取得的另一個 repo 內模組的模組層字串常數（`from helpers.case_access import CASE_PRESENT`、`case_access.CASE_PRESENT`），跟到定義檔為止。
  - 其他一切（f-string、函式參數、變數被重新指派、`getattr(registry, ...)`、把取用函式當值傳遞、`*args`）⇒ **判不了**。
  - 🔴 **判不了 ≠ 沒有消費端**：任何一處取用呼叫判不了（不論它最後是不是在取 <k> 的能力）⇒ 整個判定退回乙（拒絕出單模組包，列出判不了的位置）。「找不到消費端」只有在所有取用呼叫都解析成功、而且沒有一個屬於 <k> 能力清單時才成立（〈盤點工具的正對照〉）。
- **消費端的題**：把消費端檔案當作「虛擬改動」交給 modtest 的選題（`modtest.select`，同 §C-11a 規則），連帶選到依賴它們的單位的題。
  - 🔑 這一步是必要的：`case.access` 的直接消費端是 L1 的 `helpers/case_access.py`，netplan、accounting 是**經由它**用到 case（`modules/netplan/api.py`、`modules/accounting/voucher_attachments.py` 都 import case_access）；只選直接消費端的題會漏掉它們。
- **與 dep_graph.json 交叉比對**：dep_graph 若另有 <k> 能力清單上的消費關係而 AST 沒找到 ⇒ 退回乙並列出差異（兩個來源不一致時不猜誰對）。
- **正對照（真實 repo，D 補題；讀碼 2026-09-28 核對後的實際消費端）**：
  - 改 arap 的 `_InvoiceVoucherAttachments`（`attachments.for_document` 提供者）⇒ 選題含 **accounting** 的附件彙整題（消費端是 `modules/accounting/voucher_attachments.py:103`；〔更正 D 複審原文「⇒ case 消費端題」：case 是同一能力的**另一個提供者**（`modules/case/__init__.py:57`），不是消費端〕）。
  - 改 arap 的 `_calendar_writeback` ⇒ 選題含 `helpers/google_calendar.py:236` 的單位的題。
  - 改 case 的 `case.access` 提供者（`quotations._CaseAccess`）⇒ 選題含 **netplan**（`modules/netplan/tests/test_netplan_case_access.py`）與 **accounting** 的題（經 `helpers/case_access`）。
- **突變**：取用函式清單拿掉 `single_provider` ⇒ 正對照紅；拿掉「模組層 provide 呼叫」那一半能力清單 ⇒ arap 正對照紅；把「判不了 ⇒ 退回乙」改成「判不了 ⇒ 略過」⇒ 判不了那一題紅；拿掉「虛擬改動交給 modtest」只留直接消費端 ⇒ netplan 正對照紅。
- 題：兩種設定各一組；乙：改 case 提供者函式 ⇒ 3；只改 case 頁面 ⇒ 2。甲：同一個改動 ⇒ 2 且選題含 netplan／accounting 的消費端題（D 補題）；消費端用動態字串 ⇒ 退回 3。突變：把「讀不出 providers ⇒ 當成有」改成「當成沒有」必須紅。
- 使用者裁示後：只改設定值（與 CORE-SPEC 決定列），不改判定程式。

## 5. 核心代碼方向（檔案／函式）

| 檔案 | 動作 | 內容 |
|---|---|---|
| `tools/platform/ship_tier.py`（新） | 新增 | `classify()` 純函式＋`tier_for(P, X)` git 包裝＋`PROVIDER_CHANGE_POLICY`（§4.3）；CLI 給建包與 modtest 用 |
| `backend/tools/module_update.py`（〔U-M4①〕自 tools/platform 搬入） | 改 | build：加 `--prod-base`、呼叫 ship_tier、跑第②級測試、lock 多三欄、帶 version_manifest 條目；新增 `preflight` 子命令（只讀）；apply：寫明鏡像、更新 baseline 片段、插入 version_manifest 條目、備份三個「套用前」檔（baseline 片段、`.deployed_modules.json`、version_manifest.json）；rollback 對稱還原；`--stamp`／JSON 輸出給 ps1 解析；移除「帶 migrations/ 一律拒絕」（改由 §1.3 步驟 5 乾跑）。`tools/platform/module_update.py` 留一支轉呼叫（開發機舊用法照舊） |
| `backend/tools/apply_module_update.ps1`（新） | 新增 | §1.3。〔D 審 DB-S1＝U-M1②〕共用函式（Enter/Exit-InstallLock、Emit-Result、Write-ResultFile、Stop/Start-InstallService、Backup-DatabasesOnline、健檢 ping、log 掃描）**逐字複製**自 apply_update.ps1；守門題以 AST／函式本體比對兩份逐字相同（同 apply_update 與 rollback_update 既有做法），任一邊改了另一邊沒改 ⇒ 紅。**沒有**演練繞過分支（§7） |
| `backend/tools/apply_module_update.version.json`（新） | 新增 | 腳本版本＋雜湊（同 AH-O7 機制），`min_apply_module_script` 比的是它 |
| `backend/tools/migrate_like_startup.py` | 改 | 加 `--expect-module key=version`（印 `MODULE_LOAD_OK`） |
| `backend/tools/delivery.py` | 改 | `publish(kind=)`、delivery.json 加 kind／module／min_apply_module_script；`verify_staged` 依 kind 分支（§1.2）；`apply_staged` 分派；`find_result` 依腳本名；`write_back` 多三欄；`latest_prod_commit` 只看 full＋新 `module_overlays()`（只認 base commit＝正式機 commit 的條目） |
| `backend/tools/deploy_dashboard.py`＋`.html` | 改 | 新 status 進值域；摘要顯示模組資訊；prod-status 顯示模組覆蓋；模組回滾按鈕（列 `module_backups\<key>\`） |
| `backend/tools/apply_plan.py` | 改 | 完整包「不降模組版本」Refuse（§3） |
| `backend/tools/apply_update.ps1`／`rollback_update.ps1` | **不改** | 〔D 審 DB-S1〕`.deployed_modules.json` 過期改由讀取端依 base commit 判定（§3） |
| `backend/core/upgrade.py` | 改（L1） | `CONFIG_FILES` 加 `.deployed_modules.json`（D 審 DB-O1） |
| `backend/main.py` 或 `core/loader.py` | 改（L1） | 啟動完成寫 `logs/module_states.json`（D 審 DB-S4）；loader 兩個 log 格式字串加守門題 |
| `tools/platform/drill_module_apply.py`（新） | 新增 | 演練副本：複製 apply_module_update.ps1、只改寫 `$ProdRoot`／`$Port` 兩行（§7） |

- 這一包本身是**第③級**（改 L1 upgrade／main 或 loader、改 backend/tools）⇒ 走完整包＋全量；之後的模組包才走第②級。
- 依 MODULE-GUIDE：本功能全部在工具層（backend/tools、tools/platform），不動 L0／L1 介面、不動任何 L2 模組；模組作者不需要為了能出單模組包做任何事（只要頁面有在 module.json 宣告）。

## 6. 題目（實作時）

- `ship_tier`：§4 全部組合＋突變＋真實歷史正對照。
- `module_update`：preflight 子命令各拒絕原因；帶 migrations 的包不再被拒；`--stamp`／JSON 輸出；回滾雜湊不符 ⇒ 停止。
- `delivery`：kind 缺席＝full（舊包照驗）；kind＝module 的每一條拒絕（工具太舊、base commit 不符、同版、preflight 不過）；kind 竄改 ⇒ 簽章不符；module 包不要求 apply_update.ps1。
- `apply_module_update.ps1`：靜態題照 test_apply_plan 的做法（函式本體逐項驗：鎖在備份之前、乾跑在停服之前、健檢含「已載入」、自動回滾順序、finally 刪疊加樹、所有 status 在儀表板值域內）；腳本 status 與 `_STATUS_*` 雙向一致。
- loader log 契約題；apply_plan「完整包不降模組版本」＋反向控制（等於版本照常）。
- 儀表板：module 包的 prepare／apply 流程（沿用 delivery e2e 題的形狀）。
- 〔D 審補題〕
  - DB-M1：疊加樹裡沒有任何 `classify≠program` 的檔；反向控制：安裝目錄放 `backend/export_archive/x.pdf`、`backend/.initial_admin_credentials.txt`、`backend/license.key`、`backend/heartbeat_config.json` ⇒ 疊加樹裡都沒有；突變「白名單改回全部複製」⇒ 紅。
  - DB-S1：apply_module_update.ps1 與 apply_update.ps1 的共用函式逐字相同（改一個字元 ⇒ 紅）。
  - DB-S2：演練副本相對正式腳本的 diff 只有 `$ProdRoot`、`$Port` 兩行；正式腳本裡沒有 `SkipDryRun`／`DrillRoot` 等字樣。
  - DB-S4：module_states.json 的 started_at／pid 條件（舊檔、別的 pid ⇒ 判失敗）；模組 failed ⇒ 判失敗。
  - DB-S5：回滾雜湊不符 ⇒ 該模組進停用清單後才重啟（順序以函式本體驗）；停用寫入失敗 ⇒ 不重啟。
  - DB-S6：v2 刪掉 v1 的檔 ⇒ 套用後不在；baseline 片段更新與回滾還原；之後完整包刪除計畫對得上。
  - DB-O1：`.deployed_modules.json` classify＝config；完整包程式快照含它、cleanup-snapshot 不刪它；過期條目（base≠目前 commit）讀取端忽略。
  - U-M5：version_manifest 文字插入後其他行逐位元組不變；回滾後整檔相同。

## 7. 演練計畫（開發機；正式機條件）

- 條件：**排程開著**（不設 `MOTRIX_DISABLE_SCHEDULERS`）、`MOTRIX_GEO=1`、有待定位地址（第十六班主持加的那一種演練條件）、HTTPS 憑證在、授權閘門開。
- 安裝：用本輪完整包裝到演練目錄（%TEMP% 深一層、路徑不含 V9.0，照 upgrade_drill 規則），啟動服務並確認健康。
- 身分守門〔D 審 DB-S2＝U-M2②〕：`tools/platform/drill_module_apply.py` 把 apply_module_update.ps1 **複製到演練目錄**，只改寫 `$ProdRoot`、`$Port` 兩行（改寫前後 diff 只能是這兩行，否則演練工具自己拒絕）；正式機的腳本沒有任何繞過分支。演練副本的腳本版本雜湊與正式版不同是預期的（AH-O7 已考慮演練副本改路徑與 port）。
  - 讀碼註記：D 稽核提到的 `drill_apply_copy.py` 在 origin 所有分支都找不到（2026-09-28 逐一 ls-tree）⇒ 本設計新寫 drill_module_apply.py，不假設既有工具。
- 演練 A（成功）：挑 tender_radar，演練分支只改一行頁面文案＋版號 → ship_tier 判 2 → 第②級測試 → build → publish 到演練交付資料夾 → 儀表板 prepare／apply（真 superadmin 登入）→ 期待 `success`、lock 版本＝新版、server.log 有「已載入」、`.deployed_modules.json` 有一筆、results 寫回、開發機 prod-status 顯示覆蓋。**計時**：從按下到健康 ≤ 3 分鐘。
- 演練 B（自動回滾）：演練分支讓 tender_radar 的 `__init__.py` 在 import 時丟例外（其他不變）→ 乾跑的「模組載入」應先擋下（F7，`module_load_dryrun_failed`，正式機沒被碰）；再用演練副本（drill_module_apply.py 另外把乾跑那一段改寫成跳過；正式腳本沒有這個參數）強行套用 → ping 過而模組未載入 ⇒ F11 → 自動回滾 → 期待 `module_unhealthy_rolled_back`、`restored`、模組資料夾與頁面雜湊逐一等於套用前、DB 與套用前一致、服務 up、舊版「已載入」。
- 演練 C（加做，便宜）：帶一支會回未完成原因的 migration → F7 `migration_dryrun_failed`，正式機沒被碰。
- 每次演練記：命令、耗時、`::RESULT::` 行、result.json、前後雜湊；報告寫進 docs/platform/MODULE-UPDATE-DRILL-<日期>.md。

## 8. 給正式機 Claude 的指示範本（大綱）

1. 開場：你在正式機，只做讀取與使用者要求的一個動作；不修改程式、不跑測試。
2. 先查健康：`/api/prod-status`（本機）、備份 `.done`、告警；有異常先回報，不套用。
3. 看儀表板「6. 套用更新」：列出偵測到的包；說明 kind＝module 的包是「只更新一個模組」，列模組名、版本 舊→新、頁面、是否帶 migration、出貨前測試摘要。
4. 驗證結果只唸儀表板的判定（簽章／雜湊／工具版本／base commit／同版）；驗證不過 ⇒ 照畫面訊息告訴使用者，不嘗試繞過。
5. 由使用者本人按「套用」並輸入 superadmin 帳密；Claude 不代輸密碼。
6. 套用中：告知預估時間（≤ 3 分鐘）與死線（10 分鐘沒結果 ⇒ 回報「仍在跑」並讀 `backend\logs\apply_module_update_*.log` 最後 30 行，不中止）。
7. 結果：唸 `::RESULT::` 三行（結果／正式機現況／服務），依 §2 表的處置欄告訴使用者下一步；失敗時附 result.json 路徑與 log 路徑，不貼個資內容。
8. 手動回滾：只在使用者要求時，用儀表板的模組回滾（列 `module_backups\<key>\` 的時間戳讓使用者選）。
9. 回報給開發機：確認 `results\<包名>.result.json` 已寫出；不需要另外傳檔。

## 9. 需要決定的事（U-M）

裁示結果（2026-09-28 主持，依 D 設計審）：

| # | 裁示 | 落在 |
|---|---|---|
| U-M1 | ②複製＋逐字守門，不動 apply_update | §0、§5 |
| U-M2 | ②演練副本改寫常數，正式腳本無繞過 | §7 |
| U-M3 | D 的第三案：先停用該模組再重啟（DB-S5） | §2 F13 |
| U-M4 | ①搬到 backend/tools | §5 |
| U-M5 | ①包帶條目、文字插入、回滾整檔還原 | §3 |
| U-M6 | ①不設上限 | — |
| DB-M2 | 使用者裁示＝甲（CORE-SPEC ee383527）：加消費端題；判定不了 ⇒ 退回乙。單一設定點，預設 consumers | §4.3 |

原始選項（第一版，保留）：

| # | 問題 | 選項（推薦在前） |
|---|---|---|
| U-M1 | 套用共用函式怎麼共用 | ①抽 `_apply_common.ps1`，三支腳本 dot-source（單一來源；動到 apply_update ⇒ 第③級＋重跑其題與演練）②新腳本複製＋守門題逐字比對（不動 apply_update） |
| U-M2 | 演練怎麼通過 `$ProdRoot` 守門 | ①`-DrillRoot <路徑>`＋環境變數 `MOTRIX_APPLY_DRILL=1`＋根目錄要有演練工具建立的 `.motrix_drill_root` 標記檔，三者都在才准（正式機不會有標記檔）②演練時複製腳本並改寫常數（演練的不是正式那份）③不做端到端演練，只做靜態題 |
| U-M3 | 模組回滾本身失敗（F13）要不要重啟 | ①重啟（loader 隔離壞模組，其他照常）②同 apply_update 不重啟 |
| U-M4 | module_update.py 放哪 | ①搬到 `backend/tools/`（正式機有；tools/platform 留一支轉呼叫給開發機舊用法）②留在 tools/platform，正式機腳本改呼叫包裡帶的那份（違反「單模組包不帶工具」，不推薦） |
| U-M5 | 版本紀錄（version_manifest）怎麼跟著單模組包 | ①包帶該模組的新 manifest 條目，套用時以文字插入安裝目錄的 version_manifest.json、回滾時移除（畫面的版本紀錄才看得到）②不帶，等下一個完整包補上 |
| U-M6 | 單模組包要不要設「距離上一個完整包最多幾個模組包」上限 | ①不設，靠 base commit 必須等於正式機 commit 自然限制②設 N 個 |
