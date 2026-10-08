# 給正式機 Claude：第四十八班（48a）更新步驟（c107fd8fd → `e526a2ef74d4e8a9e23d6fac80d4a5ab1fc41d0d`）

> **定稿（已發布並已套用成功，2026-10-09 07:31）**：班次號 48（a 梯次）、整合分支 `train/t48-int`（head `e526a2ef74d4e8a9e23d6fac80d4a5ab1fc41d0d`）；包名 `20261009_071926_e526a2ef_full`、`package.sha256` 的 SHA256 `a58283c7551888a2545986228d95ade100f1018b4e0f295789aa75588861a4de`、行數／檔案數 `963`——發布後由主持填入。
> 格式同第四十七班。路徑、授權、停止規則同前：安裝目錄 `<ROOT>`；staging＝`<ROOT>\..\motrix-staging`；服務 `https://127.0.0.1:666`（略過憑證檢查）。**任何一步不符預期一律停下回報，不重試、不臨場改寫。**
> **本班驗證全部唯讀；不要在正式機送審、核可、駁回、付款、匯出、簽回、連結／解除派發、改預定付款日、作廢、上傳檔案、建立任何單據、修改使用者或職責角色來「測試」。**會寫資料的驗收項一律列在「需要使用者自己做的」。
> **授權：自動套用（主持 node-d8 轉述；沿用第 46／47 班規則）**：主持發布本包後，你做步驟 0～1（含 staging 驗證）；**步驟 0 與步驟 1 全部綠燈才自動進步驟 2 套用**。**任何一項不綠 ⇒ 不套用、停下回報**。若分類器擋下 Copy-Item／apply：停下回報，不繞過，等使用者處理。
> 🟢 **本班沒有資料庫 migration、`schema_version` 維持 118**（`db.py` `CURRENT_VERSION`／`V9_BASELINE` 皆 118；包內與正式機基準 `c107fd8fd` 的模組 migration 目錄零差異，整合者已核對；`backend/migrations_frozen/t48_overhead25/` 是**離線遷移工具的凍結算式，不是資料庫 migration、不自動執行**）。仍須套用前備份並驗證（路徑、大小、`integrity_check`）。

## 這一班有什麼（使用者看得懂的版本）

**A. 使用者管理整合職責角色（R2 第 2 步；`wip/t48-r2-step2`＋兩輪獨立稽核跟進）— 正式機新行為**
- 「使用者管理」編輯視窗（編輯既有、非最高管理者）可直接勾「職責角色」、設「個人扣項」，並即時看到伺服器算出的「生效權限預覽」；變更原因欄（高敏感變更必填）。畫面只送**原始勾選**，預覽唯讀。
- **舊的「存取模組」勾選如果勾到已被個人扣項扣掉的權限，現在會被擋下（400）並說明**（過去默默無效）；需要退回舊口徑可設旗標（見 core CHANGELOG）。
- **行為變更**：編輯既有使用者、而該帳號個人勾選為空時，不再自動填入該角色類別的預設勾選。
- 權限稽核報表與財務角色影響報表預設改看「生效權限」（要看資料庫原始勾選加 `--raw`）；`permission_changes.audit_id` 開始填值（稽核與變更紀錄同一交易）。
- 新端點 `POST /api/duty-roles/preview`（superadmin、唯讀）。**不放寬任何權限，只新增拒絕。**
- 整合期發現並修掉一個前端退化：職責角色 chip 的 `title` 以未綁定方法傳入 ⇒ `this.duty` undefined（`Cannot read properties of undefined (reading 'keys')`），已加專用 e2e 釘住。

**B. 承攬商匯款可填預定付款日（`wip/t48-paydate-gap`）**：案件頁「產生匯款申請」視窗多「預定付款日（選填）」；派發卡片顯示該日期；出納仍可改期。

**C. 管銷／利潤規則底座（`wip/t48-oh25-s1`、`s2b`、`s5`；**舊口徑不變、不改任何數字**）**
- S1：利潤規則單一來源（`helpers/profit_rules.py`＋`static/profit-rules.js`＋黃金向量守門）；完結比對的管銷／公益金／營業利益改呼叫它，**口徑仍是第 47 班的 10%**（零行為變更）。
- S2（`overheadPct`、`/api/overhead/settings`）：管銷分攤比率與伺服器把關；**`overhead_rule_mode` 預設 legacy（新行為關）**；切 v2 只能經 `PUT /api/overhead/settings`（確認＋遷移完成標記 `overhead_migration_done`），標記不存在時伺服器一律當 legacy；戳記由伺服器蓋、不信任前端。
- S5：未精算報價單管銷重算**離線遷移工具**（`tools/overhead_migrate.py`；dry-run／回滾／模式開關）——**本班不執行**，隨 48b（S3 畫面、S4 標籤、S6 獎金）公式切換時才用。
- **本班不含**：S3（報價單比率輸入畫面）、S4（「營業利益」等標籤改名）、S6（獎金）；正式機畫面文字與金額不變。

**D. 整合期小修（`wip/t48-small-fixes`）**：`suppliers.html` 聯絡人區塊在資料載入前丟 JS 例外（一般角色從供應商紀錄頁導回時常見）已防呆；測試端修午夜跨日偶發紅燈（僅測試）。

## ⚠ 權限／可見度變更（上線備註；請使用者知悉）
1. **使用者管理頁（僅 superadmin 看得到職責角色區塊）**：新增勾選／預覽；個人扣項與「存取模組」勾選衝突時舊 PUT 回 400（新的拒絕，不是放寬）。
2. 第 47 班的 `GET /api/users` 收緊、財務站內提醒、採購單廠商帳號遮罩等**不變**，不再重列。
3. **沒有**放寬任何角色的選單、金額可視、模組權限；R2 財務旗標 `finance_via_effective` 本班不動（預期仍關）；`overhead_rule_mode` 預期仍為缺／`legacy`。

## 已知殘留風險（本班不修）
- 簽核代理人（事後加入的非超管代理人在佇列詳情看得到金額）— 排後續班。
- 第 48b／c 候選（不在本班）：S3 畫面、S4 標籤、S6 獎金（公式切換一起上）；`wip/t48-payslip-person-link`（含 payroll migration 5，稽核中）。
- 其餘第 46／47 班殘留風險沿用。

**資料庫變更：無。**
- `schema_version` 維持 **118**；`module_schema_versions`：`core` 8、`case` 8、`subcontract` 6、`payroll` 4（全部不變）。
- **版本**：核心 `1.119 → 1.120`；`case 1.0.163 → 1.0.164`、`supply 1.0.21 → 1.0.22`；其餘模組版本不變。manifest 新增 `2026-10-09a`（平台/使用者管理）、`2026-10-09b`（案件管理/承攬商匯款預定付款日）。
- **回滾風險變化**：DB 版本不變，程式單獨回滾在技術上可行；仍維持「失敗不自行回滾、等使用者」鐵則。回程式後職責角色變更若已在新版寫入（`permission_changes.audit_id` 有值、`audit_log` 有 `duty_roles.*`），舊程式不讀、無害。
- 驗證（開發機，2026-10-09，commit e526a2ef7）：整合樹官方 run-stage——非 e2e 全綠、e2e 全綠（單獨跑；MOTRIX_TRAIN=1；e2e 第一次因機器負載有 4 題 playwright 逾時、單獨重跑全過，整段重跑全綠），偶發題沒有登記；包完整性 `verify_package --expect-db-version 118` 0 項 FAIL；V5 逐檔比對僅允許差異；`final_drill` 11 步通過（含 3b、6b；總判定：通過）時填入。整合期修了 5 組合併後才紅的項目（見 `train/t48-int` 提交歷史：改名常數匯入、寫入端點稽核登記、test_map 重產、職責角色 chip 前端退化＋e2e）。

## 步驟 0：前置
1. `<ROOT>\backend\.deployed_commit.json` 的 `commit` 以 `c107fd8fd` 開頭（已是 `e526a2ef7` ⇒ 回報「已是這一版」結束；其他值 ⇒ 停下回報）。
2. stage 後讀 `payload\deploy_manifest.json`（utf-8-sig）的 `verification`：預期 `mode`＝`full`，`flaky_retried`＝`[]`；若 `mode`＝`scoped` ⇒ `verification.scoped.base` 必須等於 `.deployed_commit.json` 的 `commit`；沒有 `verification` ⇒ 停下回報。另確認 `deploy_manifest.json` 的 `commit`＝`e526a2ef74d4e8a9e23d6fac80d4a5ab1fc41d0d`，與 `payload\backend\.build_commit` 內容一致。
3. `.install_identity`、`company_confirmation.sig` 存在；`GET /api/ping` 200；系統碟可用空間 ≥ 5 GB；備份健康（`backup_alerts` 無新告警、最近一次每日備份存在）。
4. 記下套用前 `module_states.json`（模組數與每個 key／version／state）及唯讀 `mode=ro` 基準：`audit_log`、`quotations`、`payslips`（總數與 `SELECT status, COUNT(*) FROM payslips GROUP BY status`）、`notifications` 筆數；**`schema_version`（預期 118）**；`module_schema_versions` 裡 `core`（預期 8）、`payroll`（預期 4）、`case`（預期 8）、`subcontract`（預期 6）；`sqlite_master` 已有表 `payslip_dispatch_links`（預期有）；`system_settings` 裡 `finance_via_effective` 是否存在（預期不存在或 `"off"`；若是 `shadow`／`on` ⇒ 停下回報）；在職帳號數與各角色人數（`SELECT role, COUNT(*) FROM users WHERE active=1 GROUP BY role`）；`user_duty_roles`、`user_perm_subtracts` 筆數（預期 0／0；非 0 ⇒ 記下並照實回報，不阻擋）。
   - 正式機的勞報單可能已有 `待審核`／`已核准`（第 46 班已上線新流程），照實記下各狀態筆數即可，不阻擋。
5. **套用前備份（資料庫）——備份未驗證 ⇒ 不套用**：
   - 確認 `<ROOT>\backend\db_backups` 有今天的每日備份；記下最新一份的檔名與大小。
   - **另外在套用前自己取一份新備份**（Online Backup，不是複製執行中的檔案；服務保持運行）：`python -c "import sqlite3; s=sqlite3.connect(r'file:<ROOT>\backend\motrix_erp.db?mode=ro', uri=True); d=sqlite3.connect(r'<ROOT>\backend\db_backups\pre_train48a_manual.db'); s.backup(d); d.close(); s.close()"`（檔名可帶時間戳；存放在 `db_backups`，**不放進安裝目錄的其他位置、不覆蓋既有備份**）。
   - **驗證那份備份**，並把結果寫進報告：完整路徑、檔案大小（> 0 且與來源庫同量級）、`PRAGMA integrity_check`（必須回 `ok`）、`SELECT value FROM schema_version`／等同查詢確認備份的 schema 版本＝**118**、`SELECT COUNT(*) FROM payslips` 與來源庫相同。任何一項不符 ⇒ **不套用**、停下回報。
   - 套用本身會再做 `db_backups\pre_update_*` 快照（步驟 3 #12 核對）；**兩份備份都在、大小 > 0 才往下**。
6. **職責角色等值關卡——快照（套用前，唯讀，schema 2）**（工具已隨第 45 班安裝，直接用安裝目錄內的）：
   ```powershell
   python <ROOT>\backend\tools\duty_roles_equivalence.py snapshot --schema 2 --out "H:\我的雲端硬碟\MOTRIX-交付\正式機回報\duty_before_48a.json" --db <ROOT>\backend\motrix_erp.db
   ```
   結束碼必須 0，並回報「已存快照（schema 2）：N 位使用者」；N 必須等於 `SELECT COUNT(*) FROM users`（預期 12）。非 0 ⇒ 停下回報。

## 步驟 1：取包並驗證（不套用）
包名：`20261009_071926_e526a2ef_full`（commit `e526a2ef74d4e8a9e23d6fac80d4a5ab1fc41d0d`）；`package.sha256` 的 SHA256 必須等於 `a58283c7551888a2545986228d95ade100f1018b4e0f295789aa75588861a4de`，行數 `963`、payload 檔案數 `963`（`delivery.json` 的 files 相同）。
```powershell
python <ROOT>\backend\tools\delivery.py stage  --root "H:\我的雲端硬碟\MOTRIX-交付" --name 20261009_071926_e526a2ef_full --staging <ROOT>\..\motrix-staging
python <ROOT>\backend\tools\delivery.py verify --staged <ROOT>\..\motrix-staging\20261009_071926_e526a2ef_full --install-root <ROOT> --skip-verify-package
python <ROOT>\..\motrix-staging\20261009_071926_e526a2ef_full\payload\backend\tools\verify_package.py <ROOT>\..\motrix-staging\20261009_071926_e526a2ef_full\payload --expect-db-version 118
```
> 🔴 **必須明寫 `--expect-db-version 118`**（包內 `db.py` 的 `CURRENT_VERSION`；本班與正式機已安裝版本相同，仍請明寫）。不要為了通過而改 `delivery.py` 或略過這項檢查。

判準同前：`DELIVERY_STAGE_OK`／`DELIVERY_VERIFY_OK`（`ok=true`、`problems=[]`）／verify_package 0 項 FAIL（含「包內 db 版本 == 118 ✅」與「三者一致」）；雜湊與行數相符；包內不得有 `__pycache__`、`.pyc` 或任何 `*.db`。雲端未同步完 ⇒ 等，不要暫存。任一不符 ⇒ 停下回報。

## 步驟 2：套用（**自動**：步驟 0 與步驟 1 全部綠燈才執行；任何一項不綠 ⇒ 不套用、停下回報；兩次分開呼叫，只執行一次）
> 進入前逐項自我核對並寫進報告：步驟 0 #1～#6 全綠（含備份已驗證）、步驟 1 的 stage／verify／verify_package（`--expect-db-version 118`）全綠、`package.sha256` 與行數相符、`deploy_manifest.json` 的 commit 與包名相符。缺一項 ⇒ 不套用。
```powershell
Copy-Item "<ROOT>\..\motrix-staging\20261009_071926_e526a2ef_full\payload\backend\tools\*" "<ROOT>\backend\tools\" -Recurse -Force
powershell -NoProfile -ExecutionPolicy Bypass -File <ROOT>\backend\tools\apply_update.ps1 -PackagePath <ROOT>\..\motrix-staging\20261009_071926_e526a2ef_full\payload -Yes
```
記下 `<t0>`。log 檔名一律帶時間戳（`Tee-Object <staging>\apply_train48a_$(Get-Date -Format yyyyMMdd_HHmmss).log`；步驟 3 引用 log 時寫「時間戳最大且 `::RESULT::` 為 success 的那份」）。不加 `-Force`／`-SkipAutoRollback`／`-MaxDeleteFiles`。最後 `::RESULT::` 為 `status=success rolled_back=applied service=up exit=0` ⇒ 步驟 3；其他 ⇒ 停下回報（附 `::RESULT::` 行與 `apply_update_<時間戳>.result.json`）。
> 套用前注意：離線工具會在暫存包留空 `motrix_erp.db`（第 45 班經驗）。套用前只刪**暫存包裡**那個空檔（`<staging>\20261009_071926_e526a2ef_full\payload\backend\motrix_erp.db`，若存在且大小為空），**絕不動 `<ROOT>` 下的資料庫**。

## 步驟 3：套用後檢查（唯讀）
| # | 檢查 | 通過條件 |
|---|---|---|
| 1 | 版本 | `.deployed_commit.json` 的 `commit` 以 `e526a2ef` 開頭 |
| 2 | 健檢 | `/api/ping` 200 |
| 3 | 開關誤報 | 套用輸出／result.json／plan.txt 不含「開關沒有生效」 |
| 4 | API 文件關閉 | `/openapi.json`、`/docs` 皆 404 |
| 5 | 模組載入 | `started_at` ≥ `<t0>`；模組總數與每個 state 同步驟 0；版本變化僅限 `case`（1.0.164）、`supply`（1.0.22）兩個；其餘模組 key／version／state 與套用前相同 |
| 6 | 伺服器 log | 最後一次「Uvicorn running on」之後，濾掉良性 ConnectionResetError：指向 `payroll`、`subcontract`、`case`、`arap`、`filehub`、`core`、`helpers`、`routers`、`main` 的 Traceback ＝ 0；且無 `payslip`、`approval`、`migration` 相關 ERROR 重複出現 |
| 7 | 服務行程 | 埠 666 監聽、PID 只有一個 |
| 8 | 資料 | 步驟 0 各表筆數與套用前相同（`notifications` 可因 90 天清理減少，判準同第 44 班：`total_after <= total_before` 且差距不超過 `old_before` 加邊界日幾筆）；`payslips` 總數與各狀態筆數與套用前相同（本班不應改變任何既有勞報單的狀態）；在職帳號數與各角色人數與套用前相同 |
| 9 | 新功能靜態存在（只查**實際部署的程式檔**） | `<ROOT>\backend\helpers\profit_rules.py`、`<ROOT>\backend\modules\case\profit_guard.py`、`<ROOT>\backend\tools\overhead_migrate.py`、`<ROOT>\frontend\static\users-duty.js` 皆存在；`Select-String <ROOT>\backend\routers\duty_roles.py -Pattern "preview"` ≥1；`Select-String <ROOT>\frontend\pages\users.html -Pattern "users-duty.js"` ≥1。**備註：`docs\platform` 依設計不由 `apply_update.ps1` 部署，本項不檢查任何 docs 檔。** |
| 10 | 狀態快照 | `prod_status_snapshot.py --out "H:\我的雲端硬碟\MOTRIX-交付\正式機回報\status\latest.json"` exit 0；`deployed_commit` 相符、`errors` 為 `{}` |
| 11 | 啟動耗時 | `<t0>` 到 `started_at` 的秒數寫進摘要 |
| **12** | **資料庫沒有 migration（`mode=ro`）** | ① **`schema_version` ＝ 118**（與套用前相同）；② `module_schema_versions`：`core`＝8、`case`＝8、`subcontract`＝6、`payroll`＝4（與套用前相同）；③ `PRAGMA table_info(payslips)` 欄位清單與套用前相同；④ `db_backups\pre_update_*` 存在一份時間戳 ≥ `<t0>` 的快照，且大小 > 0；⑤ **核心版本**：於 `<ROOT>\backend` 執行 `python -c "from core.registry import CORE_VERSION; print(CORE_VERSION)"`，輸出 `1.120`；⑥ `python -c "import db; print(db.CURRENT_VERSION, db.V9_BASELINE)"` 輸出 `118 118`。任一項不符 ⇒ 步驟 4 |
| 13 | 職責角色等值關卡（套用後；schema 2） | `python <ROOT>\backend\tools\duty_roles_equivalence.py verify --snapshot "H:\我的雲端硬碟\MOTRIX-交付\正式機回報\duty_before_48a.json" --db <ROOT>\backend\motrix_erp.db --json-out "H:\我的雲端硬碟\MOTRIX-交付\正式機回報\duty_verify_48a.json"`，**結束碼必須 0**（輸出「PASS」）；結束碼 1 或 3 ⇒ 立即停下回報並貼完整輸出（不要自行處置） |
| 14 | 財務旗標確實是關的（`mode=ro`） | `SELECT value_json FROM system_settings WHERE key='finance_via_effective'` ＝ 無列（或值為 `"off"`）；不得是 `"shadow"` 或 `"on"`；`SELECT COUNT(*) FROM audit_log WHERE action='permission.finance_shadow_diff'` ＝ 0 |
| 15 | 勞報單稽核動作未被誤觸發（`mode=ro`） | `SELECT COUNT(*) FROM audit_log WHERE action LIKE 'payslip.%' AND at >= '<t0>'` ＝ 0（套用本身不應產生任何勞報單稽核；使用者驗收開始後才會有，屆時不算）；特別是 `payslip.approval_reveal` ＝ 0 |
| 16 | 站內通知未洪水（`mode=ro`） | `SELECT COUNT(*) FROM notifications WHERE created_at >= '<t0>'`：只記數字回報（第一次上線會為已寄過信的提醒補一則站內通知，預期為少量；異常大量 ⇒ 回報，不處置） |

| 17 | 管銷口徑開關仍是舊口徑（`mode=ro`） | `SELECT value_json FROM system_settings WHERE key='overhead_rule_mode'` ＝ 無列或 `"legacy"`（不得是 `"v2"`）；`SELECT COUNT(*) FROM system_settings WHERE key='overhead_migration_done'` ＝ 0 |

> **備註**：本班 manifest 最新 api_version 為 `2026-10-09b`；`version_manifest_latest` 可能因陣列順序顯示不同，以 `2026-10-09` 開頭的最大字母為準。

全部通過 ⇒ 步驟 5。#1～#5、#7～#8、#12～#15、#17 任一不過，或 #6 有上列 Traceback ⇒ 步驟 4。#16 只回報數字。

## 步驟 4：失敗處理（apply 失敗，或 apply 顯示 success 但步驟 3 不過）——**你不自行回滾；停下等使用者**
> 🟢 **本班 `CURRENT_VERSION` 維持 118**：程式單獨回滾不會被 `SchemaNewerThanBaseline` 拒絕，技術上可行；但**是否回滾、回哪個版本、是否還原資料庫，只有使用者能決定**。
> **禁止**：自行執行 `rollback_update.ps1`（任何參數）、自行還原資料庫、自行刪表／刪欄、重試 apply、`-SkipAutoRollback`／`-Force`。例外：`apply_update.ps1` 自己的自動回滾（`rolled_back` 欄位）是工具內建行為，照實記錄，不再追加動作。
0. **立刻做的唯一事**：把現況寫進報告資料夾（`…\正式機回報\<yyyyMMdd_HHmmss>_e526a2ef7_擋下`）：`::RESULT::` 行、`apply_update_<時間戳>.result.json`、失敗的檢查項與原始輸出、`schema_version` 目前值、服務是否在線（`/api/ping`）、`.deployed_commit.json` 的 commit、**套用前備份的路徑／大小／integrity_check 結果**、`audit_log` 在 `<t0>` 之後的筆數。然後**停下，等使用者**。
1. 先停下回報，列出：失敗的檢查項、`::RESULT::` 行、套用後是否已有使用者操作（`audit_log` 在 `<t0>` 之後的筆數）。**使用者不同意還原資料庫 ⇒ 不執行任何回滾，維持現狀等待處置。**
2. 以下**僅在使用者明確要求回滾後**才執行：`<時間戳>`＝`<ROOT>\backend\logs\apply_update_*.result.json` 時間戳最大那份；先確認 `db_backups\pre_update_<時間戳>*` 快照存在、大小 > 0，再執行
   `powershell -NoProfile -ExecutionPolicy Bypass -File <ROOT>\backend\tools\rollback_update.ps1 -SnapshotTimestamp <時間戳> -IncludeDatabase -ConfirmDatabaseOverwrite -Yes`；回滾後 `commit` 以 `c107fd8fd` 開頭、`schema_version`＝118（本班沒有新遷移）、`/api/ping` 200；停下回報。
3. 資料庫版本不變（118），無新欄位或新表；回程式後 L1 寫入的站內通知與行事曆事件留在庫內，舊程式不讀、無害。**預設不還原資料庫**；只有使用者另行要求才還原 `pre_update_*`。
4. 不要手動刪表／欄位、不要重試 apply、不要用 `-Force`／`-SkipAutoRollback`。
5. **財務旗標**：本班旗標預設關，回滾不需處理。**不要執行 `duty_roles_rollback.py --apply`**：本班沒有任何 R2 資料動作。

## 步驟 5：回報
`H:\我的雲端硬碟\MOTRIX-交付\正式機回報\<yyyyMMdd_HHmmss>_e526a2ef7_<成功|回滾|擋下>\摘要.md`（寫檔被擋時把摘要全文貼回覆）：`::RESULT::` 行、步驟 0 #2、#6 的快照人數、步驟 3 各項結果（**#12 的 ①～⑧ 逐項寫出數值；#13 的完整輸出原樣貼上；#14 的值；#15 的筆數；#17 的值**）、耗時、前後 commit。



## 需要使用者自己做的（驗收；逐項點，哪一項不如預期就回報，不要自己改設定）
**第 48 班（48a）新增：**
r. **使用者管理（superadmin）**：編輯一位**非最高管理者**的既有使用者 ⇒ 視窗出現「職責角色／個人扣項／生效權限預覽」；勾角色或設扣項，預覽即時變化；**不要真的存檔**（或存檔後立刻還原並回報）。編輯最高管理者 ⇒ 不顯示職責區塊。沒有任何 JS 錯誤（開發者工具 Console 乾淨）。
s. **舊勾選與扣項衝突被擋**：對已有個人扣項的使用者，在「存取模組」勾回被扣的權限並存檔 ⇒ 被拒並說明「請先解除扣項」（不是默默失敗）。
t. **權限稽核報表**：預設顯示「生效權限」；與昨天使用者實際看到的選單一致。
u. **承攬商匯款預定付款日**：案件頁「產生匯款申請」視窗可填預定付款日（選填、可留空）；派發卡片顯示該日；出納可改期；留空時行為同第 47 班。
v. **供應商紀錄頁**：以業務／工程師開供應商紀錄頁，沒有紅色錯誤；找不到供應商時導回供應商清單且頁面正常。
w. **金額與口徑不變**：任一未精算報價單的管銷、公益金、營業利益數字與昨天相同；報價單／精算畫面沒有新欄位或改名的標籤（S3／S4 不在本班）。
x. **選單與權限不變**：同第 46 班 j。

## 停止條件（任何一條成立 ⇒ 停下回報，不自行處置）
- 套用前備份沒做或沒驗證通過（路徑、大小、`integrity_check`＝`ok`、備份 schema＝118、`payslips` 筆數相同缺一）⇒ 不套用。
- 自動套用的前提不成立（步驟 0 或步驟 1 有任何一項不綠）⇒ 不套用，寫「擋下」報告。
- 套用已動到資料庫之後任何失敗 ⇒ 不自行回滾、不重試 apply；寫報告、等使用者。
- 步驟 1 雜湊／行數／`verify_package --expect-db-version 118` 不符，或包內出現 `.pyc`／`__pycache__`／`*.db`。
- 步驟 2 `::RESULT::` 不是 `status=success rolled_back=applied service=up exit=0`。
- 步驟 3 #12 任一項不符（**出現非預期 schema／migration 變動**）；#13 結束碼不是 0；#14 旗標不是關。
- 步驟 3 #17：`overhead_rule_mode` 為 `v2` 或 `overhead_migration_done` 存在（本班不應有）⇒ 阻擋。
- 驗收回報：「某位使用者選單或權限和昨天不同」、「非財務角色看得到金額或到期提醒」、「一般人員仍看得到別人的 email／電話」、「某頁因 /api/users 收緊壞掉」、「使用者管理編輯視窗有 JS 錯誤」、「任何金額／管銷數字與昨天不同」——一律阻擋項。
