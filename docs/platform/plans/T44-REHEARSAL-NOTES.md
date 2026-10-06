# 第 44 班套用演練（rehearsal）＋探針——執行筆記（尚未執行）

> 2026-10-07，hichan-c0。**不執行**，等 hichan-1e 說「閘門綠」。目標：`origin/wip/t44-integration`（c2fc54ba0 或更新）在**開發庫複本**上走一次「套用包 → migration（含 core 未取號 NEXT→8＝`notifications.link`）→ R1 等價驗證 → 冒煙」，並可選回滾。
> 讀過：PLAYBOOK §G1 ④／§D-1a、UPGRADE-RUNBOOK §8＋「開發機演練」、`prod-tasks/TEMPLATE-apply.md`、第 42／43 班 apply 步驟檔、`backend/tools/{stepfile_drill,delivery,verify_package,apply_update.ps1,duty_roles_equivalence,migrate_like_startup}.py`、`tools/platform/{final_drill,product_drill}.py`、`origin/drill/train35b-d5` 的 `drill_train_apply.py`／`drill_train35b.py` 與 `DRILL-TRAIN35B-REPORT.md`（現有最近一份「套用演練」證據；第 36～43 班沒有找到獨立演練報告，43 班只在步驟檔註記 cf 做過演練）。

## 0. 先講限制與假設（請確認）

1. **`apply_update.ps1` 只准在正式機路徑跑**（`$ProdRoot="C:\Users\Motrix\Desktop\V9.0"` 身分守門，`not_prod_machine`）。演練工具的作法（`drill_train_apply.py::rewrite_tools`）：**只改寫 `$ProdRoot`、`$Port` 兩行**、逐行比對；套用會把包內 tools 複製回去覆蓋，所以複製後**再改寫一次**。這套零件在 `origin/drill/train35b-d5`（不在 platform）；用它要從那個分支取 `tools/platform/drill_*.py`。
2. 現有演練工具的基線資料是**合成種子**，不是開發庫複本。你要的「開發庫複本」需要一個小改（見 §3 **缺口 G1**）。
3. **「probe CLEAN」我的解讀**（請糾正）：套用後的演練安裝上，所有模組宣告的 `provides.probes`（GET）＋`pages` 都回預期碼、`undeclared_probes` 為空、`server.log` 無指向專案模組的 Traceback、單一監聽行程。若你指的是別的探針（例如 `w3-focus-probe` 類腳本或 `prod_status_snapshot` 的 `errors`），告訴我。
4. 包：**用閘門之後建出的真包**（`deploy_packages\<包名>`），不另建（建包持獨佔、閘門在跑）。真包是**未簽**（演練用拋棄式金鑰重簽，§1），所以**正式金鑰簽章驗證不在演練範圍**（35b 報告同樣列為「未涵蓋」）。
5. 開發庫複本來源＝`D:\開發測試檔\qw-pr\backend\motrix_erp.db`（1.25 MB；memory：開發庫全是測試資料）。第 43 班 RUNBOOK 記載「AI 複製 `.db` 被分類器擋下（PII）」⇒ 複本可能要**你用 `!` 執行**（§1 步驟 2 給了單行指令，使用 Online Backup 唯讀來源）。

## 1. 準備（所有路徑在 `D:\開發測試檔\rh44\`；全部演練後刪）

| 路徑 | 用途 |
|---|---|
| `rh44\tools\` | `git worktree`／`git archive` 取出 `origin/drill/train35b-d5` 的 `tools/platform/drill_*.py`＋`backend/tools/*`（演練工具；不改共用檔） |
| `rh44\keys\` | 拋棄式簽章金鑰（私鑰不離開本資料夾；**不碰** `D:\MOTRIX-KEYS`） |
| `rh44\deliv\root\` | 演練交付資料夾（`delivery.py publish` 的 `--root`；**不碰** `G:\`） |
| `rh44\seed\dev_copy.db` | 開發庫複本（Online Backup） |
| `rh44\run\<時間>\` | 演練安裝目錄（baseline install、staging、快照、報告；埠 **6744**，只綁 127.0.0.1） |
| `%TEMP%\rh44-*` | 只放報告 JSON（演練目錄外，清除前先寫）；pytest 不跑所以沒有 basetemp |

安全：路徑不可含 `V9.0`；一律 `MOTRIX_DISABLE_SCHEDULERS=1`、`MOTRIX_CLOUD_ARCHIVE=off`、`MOTRIX_EMAIL_SEND=off`、根目錄放 `.no_email_send`／`.no_cloud_archive`；本機沒有排程工作「MOTRIX ERP Server Autostart」（已查：不存在；存在就拒絕，ps1 重啟會去啟動它）；埠 6744 已查無監聽。基線＝**已上線的正式機 commit** `89206122be983dffe33328819b53747ee1246511`（`git archive` 出來，無 `.git`）。

```powershell
# ── 開跑前閘（任何一項不成立就等／不跑）──
Get-CimInstance Win32_Process | ? { $_.Name -match 'python|pytest|chrome|node' -and $_.CommandLine -match 'pytest|playwright|modtest|motrix' } | Select ProcessId,Name   # 必須空
Get-NetTCPConnection -LocalPort 6744 -State Listen -ErrorAction SilentlyContinue                                                                     # 必須空
schtasks /query /tn "MOTRIX ERP Server Autostart"                                                                                                    # 必須「找不到」

$RH  = "D:\開發測試檔\rh44"; $PY = "D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe"
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONDONTWRITEBYTECODE="1"
New-Item -ItemType Directory -Force "$RH\keys","$RH\deliv\root","$RH\seed","$RH\run" | Out-Null

# 1 演練工具：從 drill 分支取（不動 platform／train 與任何共用工作樹）
git -C D:\開發測試檔\t44-rehearsal-notes worktree add --detach "$RH\tools" origin/drill/train35b-d5

# 2 開發庫複本（唯讀來源；Online Backup）——若被分類器擋，改由使用者執行同一行
& $PY -c "import sqlite3;s=sqlite3.connect('file:D:/開發測試檔/qw-pr/backend/motrix_erp.db?mode=ro',uri=True);d=sqlite3.connect(r'$RH\seed\dev_copy.db');s.backup(d);d.close();s.close()"

# 3 拋棄式簽章金鑰（delivery.py keygen＝Ed25519；私鑰寫到檔、已存在就拒絕，公鑰印出——存成 rh44\keys\drill_pub.pem；演練公鑰由工具 `--pubkey-file` 換進安裝版本內建公鑰）
& $PY "$RH	oolsackend	ools\delivery.py" keygen --private-out "$RH\keys\drill_priv.pem"   # 輸出的公鑰另存為 drill_pub.pem（格式照 35b：d5-drill35b-deliv\keys\drill_pub.pem）
```
（`delivery.py keygen` 的確切輸出格式與 `--pubkey-file` 期望的 PEM 以 35b 的 `drill_pub.pem` 為準；實跑前我會先讀 `delivery.py`／35b 的金鑰準備段再執行，不猜。）

## 2. 套用演練（A→C→E→B→R，沿用 35b 場次定義）

```powershell
# 4 發布真包到演練交付資料夾（拋棄式金鑰；--pkg 是閘門建出的包）
& $PY "$RH\tools\backend\tools\delivery.py" publish --pkg D:\開發測試檔\<建包 worktree>\deploy_packages\<包名> --root "$RH\deliv\root" --private-key "$RH\keys\drill_priv.pem"

# 5 演練本體（新腳本 drill_train44.py＝drill_train35b.py 的改版，見 §3；--runs 依序 A→C→E→B，結尾自動 R 再套用）
& $PY "$RH\tools\tools\platform\drill_train44.py" --delivery-root "$RH\deliv\root" --name <包名> --new-commit <新commit前8碼> `
      --base-commit 89206122 --pubkey-file "$RH\keys\drill_pub.pem" --drill-root "$RH\run" --port 6744 --seed-db "$RH\seed\dev_copy.db" `
      --expect-db-version <N> --runs A,C,E,B
```
場次（沿用 35b）：**A** 套用（`stage`→`verify`→`verify_package`→`apply_update.ps1 -Yes`，記 `::RESULT::`）；**C** 資料庫回滾（`rollback_update.ps1 -IncludeDatabase -ConfirmDatabaseOverwrite`，僅演練）；**E** 回滾後重套；**B** 只回程式（`rollback_update.ps1 -SnapshotTimestamp <t> -Yes`）並逐檔雜湊比對基線；**R** B 之後再套用一次（35b 踩過：R 之後服務是起著的，**清除前一定要先停**才刪得掉目錄）。

R1 等價驗證（演練本體內建，或手動等價）：
```powershell
# 套用「前」（基線安裝＋開發庫複本，舊程式能跑；唯讀 SELECT；腳本不 import 會演進的程式）
& $PY "$RH\tools\backend\tools\duty_roles_equivalence.py" snapshot --out "$RH\run\equiv_before.json" --db "$RH\run\<時間>\install\backend\motrix_erp.db"
# 套用＋migration 完成「後」
& $PY "<安裝>\backend\tools\duty_roles_equivalence.py" verify --snapshot "$RH\run\equiv_before.json" --db "<安裝>\backend\motrix_erp.db"
```

## 3. 缺口（要先做的小改；程式碼編輯，不佔測試鎖）

- **G1 `drill_train44.py`**（由 `drill_train35b.py` 複製改）：①基線資料＝`--seed-db`（開發庫複本，覆蓋合成種子；種子寫入與 35b 專屬 `seed35b` 拿掉）；②判準換成 §4 的 44 班檢查；③`TRAIN = {number:"44", base:"89206122", db_version:<N>, schema:…}`（case／subcontract schema 版本從包內 `module.json` 讀，不手寫）；④不連網、不寄信的替身沿用；⑤`R` 再套用保留。預估 30～45 分鐘寫＋讀 35b 的 `checks_after_apply`；**要我現在開始請說一聲**（只改程式、不跑）。
- **G2 `<N>`（`--expect-db-version`）**：第 43 班步驟檔用 **116**（`db.py` 遷移數，`verify_package --expect-db-version`）；第 43 班 BUILD-RUNBOOK 另寫「core migration 最大號 7」——兩者不同概念。第 44 班：`db.py` 遷移數預期**仍 116**（鈴鐺是 core 未取號 migration，不是 `db.py` 版號），core migration 最大號取號後＝8。以包內 `deploy_manifest.json`／`verify_package` 輸出為準，不手填。

## 4. 通過判準（機械可判；每項寫進報告 JSON）

**P. 包完整性**（A 之前、套用前）
1. `delivery.py stage` ⇒ `DELIVERY_STAGE_OK`；`verify`（`--skip-verify-package`）⇒ `DELIVERY_VERIFY_OK`、`ok=true`、`problems=[]`。
2. `package.sha256` 與行數、payload 檔案數與 `delivery.json` files 相同。
3. `verify_package.py <payload> --expect-db-version <N>` ⇒ 0 項 FAIL。
4. **包內無 `__pycache__`／`*.pyc`**（`Get-ChildItem <staged>\payload -Recurse -Force -Include __pycache__,*.pyc` 為空；**必須在套用之前**驗——套用工具會在暫存包目錄寫 ~245 個 pyc，第 43 班 cf 演練註記）。
5. `deploy_manifest.json` `verification`：有此欄位；`mode=scoped` ⇒ `scoped.base` 完整 SHA 必須＝基線 `89206122…`（步驟 0 #2）；`mode=full` ⇒ 記下。

**M. Migration**
6. A 的 `::RESULT:: status=success rolled_back=applied service=up exit=0`；`/api/ping` 200。
7. core migration 8 已跑完：`t44-integration` 的 `core/migrations.py` 已是 `register("core", 8, _core_next_notifications_link)`（已取號，不是 NEXT）；`SELECT version FROM module_schema_versions WHERE module='core'` ＝ **8**（套用前 7）；`PRAGMA table_info(notifications)` 有 `link TEXT NOT NULL DEFAULT ''`、兩個新索引在 `sqlite_master`；**舊列 `link=''` 且筆數與套用前相同**。
8. `migrate_like_startup.py --db <安裝庫> --db <demo 庫>` ⇒ `MIGRATE_LIKE_STARTUP_OK`（`core.migrations.incomplete` 為空；模組 migration 都做完）。
9. 資料不變（唯讀 `mode=ro`）：步驟 0 基準表筆數（`audit_log`、`quotations`、`case_extra_expenses`、`case_material_payments`、`contractor_dispatches`、`notifications`、`users`…）套用前後相同；`db_version` 為預期值；`module_states.json`：模組總數同、版本變化只限本班列出的模組。

**R. R1 等價**
10. `duty_roles_equivalence.py verify` **結束碼 0**，輸出「PASS（逐人相同）」；快照人數 N＝`SELECT COUNT(*) FROM users`。結束碼 1 ⇒ 紅（列出差異）。

**S. 冒煙／探針 CLEAN**
11. 套用後安裝上：共用 SMOKE＋每個已載入模組 `provides.probes`＋`pages` 全 200（缺席模組 404 為預期）；`undeclared_probes` 為空。
12. 鈴鐺冒煙：一般使用者（非 admin）`GET /api/notifications/mine` 200 且項目有 `link` 欄；管理員同；`/pages/*` 載入含 `notif.js` 不報錯；通知保留 90 天的清理工作在 `MOTRIX_DISABLE_SCHEDULERS=1` 下不自動跑（只驗函式在、跑一次不炸、只刪 >90 天列——用複本裡造一筆舊列驗）。
13. 本班其他分支的靜態存在題（多附件上限、`bonus_approved`／申請人信件類型已登記、`approval_queue` 出納附件路由存在且權限＝財務）逐項 `Select-String`／`GET`（`attach-views`、`bonus-mail` 是否併入以 `t44-integration` 實際 merge 為準，演練時先 `git log` 確認）。
14. `server.log`：最後一次「Uvicorn running on」之後，濾掉良性 ConnectionResetError，指向專案模組的 Traceback＝0；單一監聽行程（埠 6744 只有一個 PID）。

**B/C/R（回滾三條路）**
15. C：`status=rollback_ok rolled_back=restored service=up`；commit＝基線、舊資料不變。
16. B：只回程式後程式檔逐檔雜湊與基線相同（差異 0；排除 logs／uploads／db_backups／rollback_snapshots／backup_alerts）；`notifications.link` 欄**保留**（新增欄位，舊程式讀得了——驗舊程式 `ping` 200＋讀 notifications 不炸，這就是「回滾缺口」之外的相容證明）。
17. R：B 之後再套用 `status=success`。

總判：**1～17 全過＝PASS**；任一紅＝停、保留現場（`--keep`）、回報。

## 5. 清除（只刪自己的）

1. 先停服務（演練工具 `T.DM.stop`；R 之後服務起著，**不停就刪不掉**）：`Get-NetTCPConnection -LocalPort 6744` 確認釋放。
2. `git -C D:\開發測試檔\t44-rehearsal-notes worktree remove --force "$RH\tools"`（我自己建的 worktree）。
3. `Remove-Item -Recurse -Force $RH`（逐層 `ls` 後再刪；**不用萬用字元刪 `motrix-pytest-*`**）；`%TEMP%\rh44-*` 報告留到你讀完。
4. 開發庫複本 `rh44\seed\dev_copy.db` 一併刪（含測試資料，仍當敏感）。

## 6. 時間估計與觸發

- 預備（§1，含取真包、發布）約 5 分；演練本體 A+C+E+B+R 依 35b 報告各場 14～22 秒（套用）＋種子／瀏覽器檢查，**全程預估 10～15 分**（開發庫複本很小）。不需要 pytest／測試鎖，但會起一個 uvicorn（埠 6744）與 headless Chromium（若包含瀏覽器檢查）。
- 等你說「gate green」＋包名／commit 後開始；G1（`drill_train44.py`）可先做，請決定。
