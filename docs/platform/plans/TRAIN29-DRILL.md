# 第 29 班套用演練（TRAIN29-DRILL）

> 負責：W1（演練主持，host 2026-10-01 指派）。分支 `drill/train29`（起點 `origin/wip/train-29-int1`）。
> 目的：在**拋棄式的類正式機安裝**上，用與正式機同一支 `apply_update.ps1`、同一個部署包，把第 28 班（`0bb4834e`）升到第 29 班，
> 並演練：套用、只回程式的回滾、資料庫回滾、自動回滾、回滾後重套；驗證三個 `0003` migration 與「費用類別清單是空的」的首次使用行為。
> 依據：`docs/platform/prod-tasks/20261001-train28-apply.md`（正式機步驟與判準）、`docs/platform/MODULE-UPDATE-DRILL-20260928.md`（演練做法與踩過的坑）、
> `tools/platform/drill_module_apply.py`（演練安裝／改寫兩行／啟動／公司資料的現成零件）、正式機第 28 班回報 `正式機回報\20261001_055939_0bb4834e_成功\摘要.md`（對照基準）。

## 0. 紅線（任何一條不成立就不開始）

1. **不碰正式機、不讀正式機資料庫、不用正式機金鑰**。不讀 `D:\MOTRIX-KEYS`；交付簽章用**演練自己產生的** ed25519 金鑰（同 `drill_module_apply.deliver`）。
2. **資料全是合成的**（開發機資料本來就全是測試資料，見 [[project-motrix-dev-prod-data-split]]）：基線安裝由 `0bb4834e` 全新建庫，再用本檔 §3 的種子腳本灌「量級接近正式機」的假資料（單號、姓名、帳號全是 `DRILL-` 開頭的虛構值）。**不複製任何開發者的 `.db`**（那份已被新版程式 migrate 過，演練不到 0003）。
3. 所有目錄放 **`D:\開發測試檔\drill-t29\<yyyyMMdd_HHmmss>\`**（不建在 D 槽根目錄；路徑不含 `V9.0`——V9 以路徑判斷正式機、會真的寄信）。pytest 暫存放 `%TEMP%`、用完刪。
4. 演練安裝：埠 **6760**（只綁 `127.0.0.1`）、`.no_email_send`、`.no_cloud_archive`、`MOTRIX_TENDER_RADAR` 關、`MOTRIX_GEO` 關（不連外）、**排程開**（與正式機一致，`MOTRIX_DISABLE_SCHEDULERS` 不設）。
5. 本機若存在排程工作 **「MOTRIX ERP Server Autostart」** ⇒ 拒絕開始（`apply_update.ps1` 的重啟會去啟動它，那是別的安裝）。檢查：`Get-ScheduledTask -TaskName "MOTRIX ERP Server Autostart" -ErrorAction SilentlyContinue`。
6. 同一時間只跑一場；跑完一定清（服務 `taskkill /T`、演練目錄刪、worktree 移除）。報告 JSON 先寫到演練目錄**外**（`%TEMP%\motrix-drill-t29\`）再清（踩過：清除失敗連報告一起刪）。
7. 全量測試不在演練裡跑（列車長在整合樹跑）；演練只驗「套用這件事」。

## 1. 輸入

| 項目 | 值 |
|---|---|
| 基線（模擬正式機現狀） | commit `0bb4834e`（第 28 班），`git archive` → `install\`，`product_select` 選 `full`，`.deployed_commit.json`／`.deployed_files.json` 寫成該 commit |
| 新版 | 主持交付的**部署包目錄**（`build_deploy_package.ps1` 的產物，含 `deploy_manifest.json`、`payload`）；其 commit 記為 `<NEW>`（開演練前先 `git -C <包> …` 或讀 manifest 寫進報告） |
| 預期 DB 版本 | `--expect-db-version 116`（`core` 不變；`db.py CURRENT_VERSION=116` 與第 28 班相同） |
| 預期 migration | `module_schema_versions`：`case`=3、`accounting`=3、`payroll`=3、`crm`≥1、`core`=6（基線：case=2、accounting=2、payroll=2） |
| 預期版號變化 | 由工具自動比對：包內每個 `modules/*/module.json` 的 `version`（`next` 在取號後是數字）對基線；**只有**這些變、其餘不變；`filehub` 是新模組（基線沒有） |

## 2. 演練場次

| 場 | 內容 | 期待 `::RESULT::` | 重點 |
|---|---|---|---|
| **A 套用** | 基線 → `<NEW>`（完整一條：stage → verify → verify_package → 複製 tools → apply） | `status=success rolled_back=applied service=up exit=0` | §5 的 A 判準；耗時（第 28 班實測約 15 秒） |
| **B 只回程式** | A 之後 `rollback_update.ps1 -SnapshotTimestamp <ts> -Yes`（**不帶** `-IncludeDatabase`） | 回到 `0bb4834e`、ping 200 | 舊程式對**已 migrate 的庫**照常運作（§5 B） |
| **C 資料庫回滾** | 再套一次 A，然後 `rollback_update.ps1 … -IncludeDatabase -ConfirmDatabaseOverwrite`（只在演練做；正式機一律先問使用者） | 庫雜湊＝套用前快照；三個 0003 的新東西消失 | 回滾後 `module_schema_versions` 回到 2/2/2 |
| **D 自動回滾** | 另開一個「`filehub`（或 `case`）`__init__` 在 uvicorn 已載入時丟例外」的包變體（乾跑過得了、真啟動載入失敗） | `module_unhealthy_rolled_back`／`restored`／`up` | 模組與頁面雜湊逐一等於套用前（同 `MODULE-UPDATE-DRILL` B） |
| **E 回滾後重套** | B 或 C 之後再套 A 的包 | `success`；migration 重跑無錯（冪等） | 證明「第一次失敗過」不會卡住第二次 |
| **F 乾跑擋下** | 變體：多一支回「未完成」的 migration | `migration_dryrun_failed`／`not_applied` | 安裝未動 |

A、B、C、E 是必做；D、F 是第 29 班新增的 migration 與模組載入風險的反向控制，時間不夠先做 D。

## 3. 準備（一次性）

```powershell
# 0. 目錄與守門
$T = "D:\開發測試檔\drill-t29\$(Get-Date -Format yyyyMMdd_HHmmss)"; New-Item -ItemType Directory -Force $T | Out-Null
Get-ScheduledTask -TaskName "MOTRIX ERP Server Autostart" -ErrorAction SilentlyContinue   # 必須沒有輸出
```

1. **基線安裝**：`git -C D:\MOTRIX-PLATFORM archive 0bb4834e` 解到 `$T\install`；`product_select.apply(root, load_product("full"))`；寫 `.deployed_commit.json`、`apply_plan.write_baseline`（零件：`drill_module_apply.make_install`，它吃 commit 與埠）。
2. **套用腳本**：包內的 `apply_update.ps1` 複製到 `install\backend\tools\`，**只改寫 `$ProdRoot`、`$Port` 兩行**（`$ProdRoot`＝`$T\install`、`$Port`＝6760）；改寫前後逐行比對，多一行就拒絕（`drill_module_apply.rewrite_ps1`）。身分守門比的是腳本位置與 `$ProdRoot`，所以這兩行改完它就認得；沒有任何繞過分支。
3. **第一次啟動**建新庫（`MOTRIX_CREATE_NEW_DB=1`）→ 最高管理員改密碼 → 依 COMPANY-SETUP-GATE 正式路徑「存檔並確認本公司資料」（`drill_module_apply.setup_company`）→ `status` 要 `configured=true`。
4. **種子資料**（合成，量級對正式機第 28 班回報：`dev_cases` 109、`quotations` 40、`vouchers_all` 64、`voucher_lines` 151、`audit_log` ≈3350、`custom_records` 0、`gl_settings feature.%` 4 列〔engine_drafts／withholding／source_annotations／tax401〕）：
   - 報價單 40 張（含已成案、有回簽檔 `signed_files_json`、材料／收付款項目的 `caseRecord`）、開發案 109（含開發記錄附件）、傳票 64／分錄 151（含 2 張有附件）、勞報單 3（1 張有簽回檔）、出貨單 2、開票申請 2、派工單 2。
   - **舊版案件額外支出 12 筆**：不同狀態（草稿／待審核／已核准／已駁回／已付款）、其中 4 筆有附件（含 `quotation_settlement_extra` 舊資料夾 2 筆）。**這批是「資料不變」與「舊程式回滾」的主要證據**，每列記 `id/status/total_cost/files_json 雜湊`。
   - `audit_log` 灌到 ≈3350；`gl_settings` 插 4 個 `feature.*`。
   - 實體檔案（附件、簽回檔）寫入對應的 `uploads\…`／勞報單封存目錄；每個檔記 SHA-256。
5. **基線記錄**（寫進報告，等同正式機步驟 0 #6／#7）：`module_states.json`（模組數、每個 key/version/state）、六個筆數、`gl_settings feature.%`、`module_schema_versions`、`PRAGMA user_version`、`case_extra_expenses` 欄位清單、`voucher_lines` 欄位清單、12 筆額外支出與附件雜湊表、`motrix_erp.db` 的 SHA-256（C 場比對用）。
6. 基線再啟動一次確認健康（`/api/ping` 200、`module_states` 全 loaded）。

> 種子與基線記錄由 `tools/platform/drill_train_apply.py` 產生（本分支）；沒有它之前不開場。

## 4. 指令（A 場；B～F 見 §6）

與第 28 班正式機步驟逐條對應（路徑換成 `$T\install`、埠 6760；**一律只執行一次**，結果不明先停）：

```powershell
$ROOT = "$T\install"; $PKG = "<主持交付的包目錄>"          # 例：...\deploy_packages\<時間>_<NEW>_full
$S = "$T\staging"; New-Item -ItemType Directory -Force $S | Out-Null
# 1 取包並驗證（演練金鑰簽章；公鑰用演練那一把）
python $ROOT\backend\tools\delivery.py stage  --root "$T\交付" --name <包名> --staging $S      # 末行 DELIVERY_STAGE_OK
python $ROOT\backend\tools\delivery.py verify --staged $S\<包名> --install-root $ROOT --skip-verify-package   # DELIVERY_VERIFY_OK
python $S\<包名>\payload\backend\tools\verify_package.py $S\<包名>\payload --expect-db-version 116       # ✅ 全部通過（0 項 FAIL）
# 2 套用（兩段分開呼叫）
Copy-Item "$S\<包名>\payload\backend\tools\*" "$ROOT\backend\tools\" -Recurse -Force
powershell -NoProfile -ExecutionPolicy Bypass -File $ROOT\backend\tools\apply_update.ps1 -PackagePath $S\<包名>\payload -Yes
```

> 演練用 `deliver()` 的發布端（`delivery.publish`）把包簽成演練金鑰；若主持只給「未簽的包目錄」，stage/verify 兩行改記為「略過（無簽章包）」，直接用包目錄當 `-PackagePath`，並在報告註明。

記下 `<t0>`（套用開始）。最後一個 `::RESULT::` 行與 `apply_update_<ts>.result.json`、`plan.txt` 存進報告。

## 5. 判準

### A 套用後（沿用第 28 班步驟 3 的 12 項，並加第 29 班專屬項；全部唯讀）

| # | 檢查 | 通過條件 |
|---|---|---|
| 1 | 版本 | `.deployed_commit.json` 以 `<NEW>` 開頭；`/api/system/version` 等於包內版號 |
| 2 | 健檢 | `/api/ping` 200（HTTP；演練安裝無 certs） |
| 3 | 開關誤報 | 輸出／result.json／plan.txt 不含「開關沒有生效」 |
| 4 | 公司資料 | `company_setup_cli.py status` 的 `configured=true` |
| 5 | API 文件關閉 | `/openapi.json`、`/docs` 404 |
| 6 | 模組載入 | `module_states.json`：`started_at` ≥ `<t0>`；模組數＝基線＋1（`filehub`）；每個 `state=loaded`；版本變化＝包內 module.json 與基線的差集，**不多不少** |
| 7 | 伺服器 log | 最後一次「Uvicorn running on」之後：指向模組／core／helpers／routers／main 的 Traceback 為 0；其餘 ERROR 前 5 行與總數寫進報告 |
| 8 | 服務行程 | 埠 6760 監聽，監聽 PID 只有一個且等於 `module_states` 的 pid |
| 9 | migration 與資料不變 | (a) `module_schema_versions`：`case`=3、`accounting`=3、`payroll`=3、`core`=6；`PRAGMA user_version`＝116；(b) 新表 `expense_categories`、`gl_dimensions`、`user_bank_accounts` 存在；`voucher_lines.dim_json` 存在且舊分錄皆 `'{}'`；`case_extra_expenses` 新增欄位齊全（`kind, doc_code, data_json, lines_json, def_version, department_id, payee_*, pay_terms, remit_date, pay_method, pay_account_code, paid_by, pretax, tax, currency, void_*`），索引 `idx_case_extra_exp_doc_code`（部分唯一）、`idx_case_extra_exp_kind_status`；(c) 六個筆數＝基線（`vouchers_all`/`voucher_lines` 因引擎草稿可 ≥）；12 筆舊額外支出逐列「`id/status/total_cost/files_json` 雜湊」不變，且 `kind=''`、`doc_code=''`、`data_json='{}'`、`lines_json='[]'`、`def_version=0`；(d) `gl_settings feature.%` 同基線；(e) 無「migration 未完成」字樣 |
| 10 | 新功能靜態存在與守門（不登入） | 檔案存在：`frontend/pages/expense-types.html`、`file-center.html`、`frontend/static/definition-form.js`；不帶 Authorization：`GET /api/expense-types`、`/api/expense-categories`、`/api/filehub/search`、`/api/definition-kinds`、`/api/settings/approval-doc-types` 皆 401／403 |
| 11 | 狀態快照 | `prod_status_snapshot.py --out <演練目錄外>\status.json` exit 0；`deployed_commit`＝`<NEW>`、`ping`＝200、`errors` 為 `{}` |
| 12 | 啟動耗時 | `<t0>` → `started_at` 秒數（第 28 班 14 秒；本班有 3 個 migration，超過 60 秒要寫原因） |
| 13 | migration 冪等 | 重啟一次服務（停→啟）：第二次啟動無 migration 錯誤、`module_schema_versions` 不變、log 無 ERROR |
| 14 | 舊資料可用 | 12 筆舊額外支出的附件逐檔 `GET /api/attachments/open`（舊資料夾 2 筆也要開得起來）→ 200 且位元組＝種子雜湊；列表／詳情 API 對舊列的回應鍵與數值＝基線 |
| 15 | 舊流程不變 | 用舊式（無 `kind`）建立一筆額外支出→送審→核准→出納登錄付款：全程成功，單號格式與基線相同 |

### A′ 第一次登入與「費用類別清單是空的」（**必驗**；這是第 29 班上線後使用者第一眼會碰到的）

升級後 `expense_categories` 是空表（migration 不灌種子；類別由會計主管在總帳設定頁維護）。逐項記錄**實際行為**，不符預期者列為缺陷回報主持（不自行改產品行為）：

1. 以升級後的最高管理員登入：`GET /api/expense-categories` → 200 且 `{"categories": []}`（不是 500／403）。
2. 「新增請款」頁選一個費用單據類型（請購單）：表單照定義渲染；費用類別下拉**沒有選項**（目前的實作沒有任何說明文字）。依現行程式，明細的「費用類別」是必填欄，前端驗證會同時擋「存成草稿」與「送審」，訊息是「第 1 列：費用類別必填」——**使用者看到必填卻沒有任何可選項，也沒有告訴他要找誰設定**。預期的最低要求：**不可以是 500、不可以無聲成功**；若實測確如上述，列為「上線後處理」缺陷並建議二選一：(a) 表單在類別清單為空時顯示「尚未設定費用類別，請洽會計主管至總帳設定新增」；(b) 升級時由會計 migration 灌一組預設類別（需 W4／使用者裁示）。直接打 API（繞過前端）送審 → 後端 400「第 N 列的費用類別「…」不是啟用中的類別」，草稿可存（只有送審才驗類別）——這一條也要實測記錄。
3. 最高管理員在總帳設定頁新增一個費用類別（`PUT /api/ledger/expense-categories`，需對應科目的話一併設）→ 重新整理「新增請款」→ 下拉出現該類別 → 送審成功（有簽核層走簽核；無簽核層直接核准）→ 明細列寫入 `categoryCode`／`categoryName`／`accountCode`（有對應時）。
4. 一般使用者（無 `expense_forms`、非 admin）：選單沒有「請款類型」；`GET /api/expense-types` 200（任何登入者）；建立**無案件**單據 403「沒有建立無案件費用單據的權限」；有案件的單據仍可（案件讀者）。
5. 沒有「檔案中心」模組權限的人：全域 `GET /api/filehub/search` 403；帶 `quote_no` 200（案件頁「全部附件」）；最高管理員全域 200。
6. 預設四個類型（請購／採購／差旅／零用金）在「請款類型」編輯頁列為「程式預設」，可開啟並以目前生效的預設為起點；**欄位仍是草稿**（使用者尚未確認）。

### B 只回程式後

- `.deployed_commit.json` 回 `0bb4834e`、`/api/ping` 200、`module_states` 回基線版本（`filehub` 不在）。
- 舊程式對**已 migrate 的庫**：不 crash（log 無 Traceback）；舊式額外支出建立→列表→詳情→送審照常；傳票列表／新增傳票照常（`voucher_lines` 多了 `dim_json` 有預設）；勞報單、開發案照常。
- 新表與新欄位**留在庫裡**（預期；不是缺陷）。`module_schema_versions` 仍是 3（舊程式不讀）。
- 這時用舊程式建立的一筆額外支出（沒有新欄位的值）再套用 §E 重套後，新程式讀它要正常（`kind=''`、其餘預設）。

### C 資料庫回滾後

- `motrix_erp.db` 的 SHA-256 或邏輯內容（表清單＋每表筆數＋12 筆舊額外支出雜湊）＝基線快照；`expense_categories`／`gl_dimensions`／`user_bank_accounts` 不存在；`module_schema_versions` 回 case=2／accounting=2／payroll=2；服務 ping 200。
- 套用到回滾之間新增的資料（A′ 驗證時建的類別與單據）**按設計消失**：報告要明寫「資料庫回滾會丟掉這段期間的所有寫入」（正式機要先問使用者的理由）。

### D 自動回滾

`::RESULT:: status=module_unhealthy_rolled_back rolled_back=restored service=up`；回滾後每個模組版本與頁面雜湊逐一等於套用前；庫還原（先另存再還原兩個庫）；結束時服務健康。

### E 回滾後重套

`status=success`；三個 0003 重跑無錯；A 的 6、9、13 重驗；A′ 不必重跑。

### F 乾跑擋下

`migration_dryrun_failed`／`not_applied`；安裝目錄雜湊不變、服務仍是舊版且健康。

## 6. B～F 指令摘要

```powershell
# B：只回程式
$ts = (Get-ChildItem "$ROOT\backend\logs\apply_update_*.result.json" | Sort-Object Name | Select-Object -Last 1).BaseName -replace '^apply_update_|\.result$',''
powershell -NoProfile -ExecutionPolicy Bypass -File $ROOT\backend\tools\rollback_update.ps1 -SnapshotTimestamp $ts -Yes
# C：資料庫回滾（僅演練）
powershell -NoProfile -ExecutionPolicy Bypass -File $ROOT\backend\tools\rollback_update.ps1 -SnapshotTimestamp $ts -IncludeDatabase -ConfirmDatabaseOverwrite -Yes
# E：重套 = §4 的套用兩段再來一次
```
D、F 用 `drill_module_apply.make_variant` 的做法在演練用 worktree 做變體包（不推、不進 repo）。

## 7. 交付與清理

- 報告：`docs/platform/TRAIN29-DRILL-REPORT.md`（本分支）＋ JSON `%TEMP%\motrix-drill-t29\<ts>.report.json`。內容：每場的 `::RESULT::`、耗時、§5 逐項結果與證據（數字、雜湊，不含任何真實個資）、缺陷清單（分「擋上線」／「上線後處理」）、A′ 實際行為紀錄、各場前後 commit。
- 清理：服務停止（`taskkill /T`）→ 演練 worktree 移除 → `$T` 刪（失敗先盤點再重試，別信錯誤訊息）→ `%TEMP%` pytest 暫存刪。不留 `source` 資料庫副本。
- 回報主持（bin-1c）：第一行自我識別；結論先行（過／不過、擋上線的缺陷數）；附報告路徑與 SHA。

## 8. 風險與已知注意事項（開場前先讀）

- **PS 5.1 讀無 BOM 的 UTF-8 `server.log` 要帶 `-Encoding UTF8`**（演練抓過：否則每次都被判不健康而自動回滾）；本班不新增這類腳本，若包內 `apply_update.ps1` 版本不同於第 28 班（`2026-09-28k`），先比對差異再開演練。
- 套用腳本版本守門：執行中的 `apply_update.ps1` 與包內的版本字串必須相同，所以**先**把包內 `backend\tools\*` 複製過去（§4 第二段第一行）。
- `case_extra_expenses` 在正式機可能比種子大很多；演練量級小，**ALTER 與建索引的時間不代表正式機**——報告只寫量級，不外推。
- 種子資料不含真實個資；A′ 的類別、帳號等都用 `DRILL-` 前綴。
- 本演練不驗：HTTPS 憑證路徑（演練無 certs）、Remote Control 回報管道、Google Drive 路徑——這三項在正式機步驟 0 與 5 才會碰到。
