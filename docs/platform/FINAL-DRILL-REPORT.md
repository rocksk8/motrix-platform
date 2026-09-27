> 落地：2026-09-27 23:14 主持從 `D:\MOTRIX-DRILLS\FINAL-DRILL-REPORT.md` 收進 repo（演練子代理產出；D 稽核 2b8afa60〈AUDIT-D-D7-drill.md〉：full 可上正式機、必修 0；兩條被更正的判準 D 對照規格原文確認成立）。原始結果檔在開發機 `D:\MOTRIX-DRILLS\d7-results\`（不進 repo）。下方保留 2026-09-26 預演段落（原文不動）。

# D7 正式轉移升級演練報告（c006a2a0，13 份部署包）

> 產生：`D:\MOTRIX-DRILLS\d7-tools\make_report.py`（2026-09-27T22:51:16）。執行者：主持派的子代理（D7 執行）。
> 包的來源：主持代使用者建（使用者授權），commit `c006a2a0bc5c11a67f429e9d1324a31365524885`（branch platform），`build_deploy_package.ps1 -Product <產品>`，13 份在 `D:\MOTRIX-DRILLS\d7-packages\<產品>\<時間>_c006a2a0\`；建包紀錄 `D:\MOTRIX-DRILLS\d7-build-log.txt`。
> deploy_manifest（full）：built_at `2026-09-27 22:01:36`；tests {"not_e2e": {"passed": 5134, "failed": null, "skipped": 59}, "workers": 4, "e2e": {"passed": 498, "failed": null, "skipped": 2}}。
> 演練根目錄：full＝`D:\MOTRIX-FINAL-DRILL`；其他＝`D:\MOTRIX-DRILLS\d7-<產品>`。來源：`C:\Users\hichan\Desktop\MOTRIX-ERP`（只讀）。
> 工具：`D:\MOTRIX-DRILLS\d7-src`（`git worktree --detach c006a2a0`，與包同一個 commit，避免主工作樹變動影響工具）；Python `D:\MOTRIX-PLATFORM\.venv312`；BelowNormal；不跑 pytest。演練開始 2026-09-27T22:09:07。
> 腳本：`d7-tools\d7_verify.py`（V1～V7）、`run_matrix.py`（final_drill 11 步→d7_extra→product_drill）、`d7_extra.py`（§3 另外要驗）、`v9_snapshot.py`（E4）。原始結果：`D:\MOTRIX-DRILLS\d7-results\`。

## 2. 驗包 V1～V7

| 包 | V1 驗包工具（正對照） | V2 選配／lock | V3 逐檔（應有／包／缺／多） | V4 runtime ①②③ | V5 雜湊 | V6 lock | V7 不該進包 |
|---|---|---|---|---|---|---|---|
| full | ✅ exit=0 正對照=True | ✅ | ✅ 503／503／0／0 | ✅ ①✅ ②✅（152 檔）③✅ | ✅ `full-package-sha256.txt` | ✅ core 1.56 | ✅ 0 |
| core-only | ✅ exit=0 正對照=True | ✅ | ✅ 369／369／0／0 | ✅ ①✅ ②✅（79 檔）③✅ | ✅ `core-only-package-sha256.txt` | ✅ core 1.56 | ✅ 0 |
| accounting-only | ✅ exit=0 正對照=True | ✅ | ✅ 383／383／0／0 | ✅ ①✅ ②✅（92 檔）③✅ | ✅ `accounting-only-package-sha256.txt` | ✅ core 1.56 | ✅ 0 |
| analytics-only | ✅ exit=0 正對照=True | ✅ | ✅ 380／380／0／0 | ✅ ①✅ ②✅（89 檔）③✅ | ✅ `analytics-only-package-sha256.txt` | ✅ core 1.56 | ✅ 0 |
| arap-only | ✅ exit=0 正對照=True | ✅ | ✅ 381／381／0／0 | ✅ ①✅ ②✅（89 檔）③✅ | ✅ `arap-only-package-sha256.txt` | ✅ core 1.56 | ✅ 0 |
| case-only | ✅ exit=0 正對照=True | ✅ | ✅ 394／394／0／0 | ✅ ①✅ ②✅（98 檔）③✅ | ✅ `case-only-package-sha256.txt` | ✅ core 1.56 | ✅ 0 |
| crm-only | ✅ exit=0 正對照=True | ✅ | ✅ 375／375／0／0 | ✅ ①✅ ②✅（82 檔）③✅ | ✅ `crm-only-package-sha256.txt` | ✅ core 1.56 | ✅ 0 |
| daily_tasks-only | ✅ exit=0 正對照=True | ✅ | ✅ 375／375／0／0 | ✅ ①✅ ②✅（82 檔）③✅ | ✅ `daily_tasks-only-package-sha256.txt` | ✅ core 1.56 | ✅ 0 |
| netplan-only | ✅ exit=0 正對照=True | ✅ | ✅ 379／379／0／0 | ✅ ①✅ ②✅（85 檔）③✅ | ✅ `netplan-only-package-sha256.txt` | ✅ core 1.56 | ✅ 0 |
| payroll-only | ✅ exit=0 正對照=True | ✅ | ✅ 386／386／0／0 | ✅ ①✅ ②✅（92 檔）③✅ | ✅ `payroll-only-package-sha256.txt` | ✅ core 1.56 | ✅ 0 |
| subcontract-only | ✅ exit=0 正對照=True | ✅ | ✅ 381／381／0／0 | ✅ ①✅ ②✅（88 檔）③✅ | ✅ `subcontract-only-package-sha256.txt` | ✅ core 1.56 | ✅ 0 |
| supply-only | ✅ exit=0 正對照=True | ✅ | ✅ 381／381／0／0 | ✅ ①✅ ②✅（87 檔）③✅ | ✅ `supply-only-package-sha256.txt` | ✅ core 1.56 | ✅ 0 |
| tender_radar-only | ✅ exit=0 正對照=True | ✅ | ✅ 378／378／0／0 | ✅ ①✅ ②✅（84 檔）③✅ | ✅ `tender_radar-only-package-sha256.txt` | ✅ core 1.56 | ✅ 0 |

- V3 應有＝`git ls-tree -r c006a2a0`（1430）扣 export-ignore（930）扣沒選到的模組資料夾與 removed_pages，加建包產生的 3 檔（`backend/.build_commit`、`backend/modules.lock.json`、`deploy_manifest.json`，逐一列名）；逐檔集合比對，缺與多都是 0 才過。
- V4① 包內與 git 樹（同 commit，扣掉沒選到的模組）各跑 `core.source_tree.product_files()／page_files()／router_files()`，每一檔都在包裡、沒有 export-ignore 路徑；② 包的複本（空庫、SAFE_ENV）啟動並打 `/`、login 頁、version 後，`sys.modules` 裡來自包目錄的檔都在包裡、沒有 export-ignore 路徑；③ 產品碼 `open(`／`read_text`／`Path(`／`os.path.join`／`FileResponse` 等行上的字面檔名，沒有一個只存在於 export-ignore 路徑。
- V5 雜湊清單：`D:\MOTRIX-DRILLS\d7-results\<產品>-package-sha256.txt`；manifest commit＝`.build_commit`＝c006a2a0bc5c…（13 份）。

## 3. 11 步 × 選配矩陣

### full

包：`D:\MOTRIX-DRILLS\d7-packages\full\20260927_220134_c006a2a0`；演練根目錄：`D:\MOTRIX-FINAL-DRILL`；2026-09-27 22:42:26～2026-09-27 22:44:23（116 秒）

| 步 | 結果 | 秒 | 關鍵數據 |
|---|---|---|---|
| 1 備份來源（唯讀） | ✅ | 2.2 | db=4 data_files=821 |
| 2 建演練安裝目錄 | ✅ | 2.5 | files=1844；開發機備份告警封存=True；標記檔 .no_email_send、.no_cloud_archive |
| 4a 預檢 | ✅ | 0.0 | problems=[] |
| 4b 備份＋試還原 | ✅ | 6.4 | files=1017 db=['backend/motrix_erp.db', 'backend/motrix_erp_demo.db'] |
| 4c 轉換 | ✅ | 4.4 | migrate ok=True rc=0 |
| 4d 驗證（新版啟動） | ✅ | 14.2 | problems=[] |
| 5 冒煙 | ✅ | 5.6 | 冒煙 71 項：200×71、缺席期望 404 且回 404×0、不過 0 ；略過 0 |
| 6a 完整回滾（第一份備份） | ✅ | 19.3 | logical_equal_to_source=True；V9 ping=200；problems=[] |
| 6b 再轉換（只回程式前） | ✅ | 15.8 | verify=[]；backup_problems=[] |
| 6c 只回程式 | ✅ | 9.4 | exit=0；V9 ping=200；problems=[] |

final_drill 總判定：✅；stopped_at=None；保留=[]

**另外要驗**（V9 真實資料轉換後的新版；`d7_extra.py`）：總判定 ✅；模組狀態清單 ✅（key＝lock 模組、皆 loaded：{'extra': [], 'missing': []}）

- L1 頁面 25 頁：不過 0
- 無路徑參數 GET 全掃：131 支（排除連外／長連線／匯出類 24 支），狀態分佈 {'200': 118, '422': 9, '404': 2, '400': 2}，5xx／連線失敗 0

**product_drill（空庫選配）**：✅；ping 200、登入 200、正對照 /api/auth/me 200；65 項（在：65 項 200；缺席：0 項 404）；不過 0；undeclared_probes=[]

### core-only

包：`D:\MOTRIX-DRILLS\d7-packages\core-only\20260927_220155_c006a2a0`；演練根目錄：`D:\MOTRIX-DRILLS\d7-core-only`；2026-09-27 22:44:24～2026-09-27 22:46:06（102 秒）

| 步 | 結果 | 秒 | 關鍵數據 |
|---|---|---|---|
| 1 備份來源（唯讀） | ✅ | 2.1 | db=4 data_files=821 |
| 2 建演練安裝目錄 | ✅ | 2.4 | files=1844；開發機備份告警封存=True；標記檔 .no_email_send、.no_cloud_archive |
| 4a 預檢 | ✅ | 0.0 | problems=[] |
| 4b 備份＋試還原 | ✅ | 6.4 | files=1017 db=['backend/motrix_erp.db', 'backend/motrix_erp_demo.db'] |
| 4c 轉換 | ✅ | 4.6 | migrate ok=True rc=0 |
| 4d 驗證（新版啟動） | ✅ | 11.7 | problems=[] |
| 5 冒煙 | ✅ | 3.7 | 冒煙 71 項：200×6、缺席期望 404 且回 404×65、不過 0 ；略過 11 |
| 6a 完整回滾（第一份備份） | ✅ | 18.9 | logical_equal_to_source=True；V9 ping=200；problems=[] |
| 6b 再轉換（只回程式前） | ✅ | 15.9 | verify=[]；backup_problems=[] |
| 6c 只回程式 | ✅ | 9.8 | exit=0；V9 ping=200；problems=[] |

final_drill 總判定：✅；stopped_at=None；保留=[]

**另外要驗**（V9 真實資料轉換後的新版；`d7_extra.py`）：總判定 ✅；模組狀態清單 ✅（key＝lock 模組、皆 loaded：{'extra': [], 'missing': []}）

| IP | 項目 | 路徑 | 狀態碼（期望） | 缺少的說明字串 | 回應節錄 |
|---|---|---|---|---|---|
| IP-16 | L1 獎金入口：薪資獎金缺席 | `/api/system/bonus-module-status` | 200（200）✅ |  | {"enabled":false,"notice":"薪資獎金模組未安裝：獎金分潤不提供"} |
| IP-91 | L1 報價預設條款：案件缺席 | `/api/settings/quote-terms-defaults` | 404（404）✅ |  | {"detail":"案件模組未安裝：報價單預設條款不提供"} |

- L1 頁面 25 頁：不過 0
- 無路徑參數 GET 全掃：63 支（排除連外／長連線／匯出類 10 支），狀態分佈 {'200': 53, '422': 7, '404': 3}，5xx／連線失敗 0

**product_drill（空庫選配）**：✅；ping 200、登入 200、正對照 /api/auth/me 200；65 項（在：0 項 200；缺席：65 項 404）；不過 0；undeclared_probes=[]

### accounting-only

包：`D:\MOTRIX-DRILLS\d7-packages\accounting-only\20260927_220215_c006a2a0`；演練根目錄：`D:\MOTRIX-DRILLS\d7-accounting-only`；2026-09-27 22:46:07～2026-09-27 22:47:55（108 秒）

| 步 | 結果 | 秒 | 關鍵數據 |
|---|---|---|---|
| 1 備份來源（唯讀） | ✅ | 2.1 | db=4 data_files=821 |
| 2 建演練安裝目錄 | ✅ | 2.5 | files=1844；開發機備份告警封存=True；標記檔 .no_email_send、.no_cloud_archive |
| 4a 預檢 | ✅ | 0.0 | problems=[] |
| 4b 備份＋試還原 | ✅ | 6.2 | files=1017 db=['backend/motrix_erp.db', 'backend/motrix_erp_demo.db'] |
| 4c 轉換 | ✅ | 4.3 | migrate ok=True rc=0 |
| 4d 驗證（新版啟動） | ✅ | 13.7 | problems=[] |
| 5 冒煙 | ✅ | 5.4 | 冒煙 71 項：200×10、缺席期望 404 且回 404×61、不過 0 ；略過 10 |
| 6a 完整回滾（第一份備份） | ✅ | 19.2 | logical_equal_to_source=True；V9 ping=200；problems=[] |
| 6b 再轉換（只回程式前） | ✅ | 15.8 | verify=[]；backup_problems=[] |
| 6c 只回程式 | ✅ | 10.3 | exit=0；V9 ping=200；problems=[] |

final_drill 總判定：✅；stopped_at=None；保留=[]

**另外要驗**（V9 真實資料轉換後的新版；`d7_extra.py`）：總判定 ✅；模組狀態清單 ✅（key＝lock 模組、皆 loaded：{'extra': [], 'missing': []}）

| IP | 項目 | 路徑 | 狀態碼（期望） | 缺少的說明字串 | 回應節錄 |
|---|---|---|---|---|---|
| IP-16 | L1 獎金入口：薪資獎金缺席 | `/api/system/bonus-module-status` | 200（200）✅ |  | {"enabled":false,"notice":"薪資獎金模組未安裝：獎金分潤不提供"} |
| IP-91 | L1 報價預設條款：案件缺席 | `/api/settings/quote-terms-defaults` | 404（404）✅ |  | {"detail":"案件模組未安裝：報價單預設條款不提供"} |
| IP-14/99/20 | T100 預覽：來源模組缺席 | `/api/reports/t100-export/preview?start=2026-01-01&end=2026-09-30` | 200（200）✅ |  | {"notice":"外包工班模組未安裝：本次匯出不含承攬商費用的付款傳票；採購・庫存・出貨模組未安裝：本次匯出不含料件設備進貨的付款傳票；應收應付模組未安裝：T100 匯出不含收款事件（銷項）","count":0,"totalAmount":0,"events":[]} |

- L1 頁面 25 頁：不過 0
- 無路徑參數 GET 全掃：68 支（排除連外／長連線／匯出類 14 支），狀態分佈 {'200': 56, '422': 7, '404': 3, '400': 2}，5xx／連線失敗 0

**product_drill（空庫選配）**：✅；ping 200、登入 200、正對照 /api/auth/me 200；65 項（在：4 項 200；缺席：61 項 404）；不過 0；undeclared_probes=[]

### analytics-only

包：`D:\MOTRIX-DRILLS\d7-packages\analytics-only\20260927_220235_c006a2a0`；演練根目錄：`D:\MOTRIX-DRILLS\d7-analytics-only`；2026-09-27 22:47:56～2026-09-27 22:49:45（109 秒）

| 步 | 結果 | 秒 | 關鍵數據 |
|---|---|---|---|
| 1 備份來源（唯讀） | ✅ | 2.0 | db=4 data_files=821 |
| 2 建演練安裝目錄 | ✅ | 2.4 | files=1844；開發機備份告警封存=True；標記檔 .no_email_send、.no_cloud_archive |
| 4a 預檢 | ✅ | 0.0 | problems=[] |
| 4b 備份＋試還原 | ✅ | 6.4 | files=1017 db=['backend/motrix_erp.db', 'backend/motrix_erp_demo.db'] |
| 4c 轉換 | ✅ | 4.5 | migrate ok=True rc=0 |
| 4d 驗證（新版啟動） | ✅ | 12.2 | problems=[] |
| 5 冒煙 | ✅ | 5.7 | 冒煙 71 項：200×14、缺席期望 404 且回 404×57、不過 0 ；略過 10 |
| 6a 完整回滾（第一份備份） | ✅ | 20.5 | logical_equal_to_source=True；V9 ping=200；problems=[] |
| 6b 再轉換（只回程式前） | ✅ | 16.0 | verify=[]；backup_problems=[] |
| 6c 只回程式 | ✅ | 9.6 | exit=0；V9 ping=200；problems=[] |

final_drill 總判定：✅；stopped_at=None；保留=[]

**另外要驗**（V9 真實資料轉換後的新版；`d7_extra.py`）：總判定 ✅；模組狀態清單 ✅（key＝lock 模組、皆 loaded：{'extra': [], 'missing': []}）

| IP | 項目 | 路徑 | 狀態碼（期望） | 缺少的說明字串 | 回應節錄 |
|---|---|---|---|---|---|
| IP-16 | L1 獎金入口：薪資獎金缺席 | `/api/system/bonus-module-status` | 200（200）✅ |  | {"enabled":false,"notice":"薪資獎金模組未安裝：獎金分潤不提供"} |
| IP-91 | L1 報價預設條款：案件缺席 | `/api/settings/quote-terms-defaults` | 404（404）✅ |  | {"detail":"案件模組未安裝：報價單預設條款不提供"} |
| IP-99 | 稅務匯出：應收應付缺席 | `/api/reports/tax-export?year=2026` | 404（404）✅ |  | {"detail":"應收應付模組未安裝：收款與銷項發票資料不提供（現金口徑收入、銷項發票匯出需要它）"} |
| IP-98 | 支出／收入報表（現金口徑）：應收應付缺席 | `/api/reports/expenses-monthly?year=2026&month=2026-09&basis=cash` | 200（200）✅ |  | {"basis":"cash","basisNote":"現金口徑：收入依實際收款日（含稅），支出依實際付款日（含稅）：派工以匯款申請的已匯款日為準，叫料以付款日為準，額外支出以付款日為準（未登錄者暫用憑證日並標示）。","incomeTaxLabel":"含稅","recognitionFlags":{},"unav |
| IP-95 | 支出／收入報表（權責口徑）：案件缺席 | `/api/reports/expenses-monthly?year=2026&month=2026-09&basis=accrual` | 200（200）✅ |  | {"basis":"accrual","basisNote":"本報表預設採權責口徑：收入依案件階段完成月認列（未稅），支出依廠商發票月認列（拆得出稅額的用未稅，拆不出的用全額並標示）；叫料已納入支出。與舊版報表（收入依收款日、支出依派工日且未含叫料）數字不同屬正常。尚未補登發票日期或階段比例的單據，會暫用其他日期並列 |

- L1 頁面 25 頁：不過 0
- 無路徑參數 GET 全掃：79 支（排除連外／長連線／匯出類 13 支），狀態分佈 {'200': 69, '422': 7, '404': 3}，5xx／連線失敗 0

**product_drill（空庫選配）**：✅；ping 200、登入 200、正對照 /api/auth/me 200；65 項（在：8 項 200；缺席：57 項 404）；不過 0；undeclared_probes=[]

### arap-only

包：`D:\MOTRIX-DRILLS\d7-packages\arap-only\20260927_220256_c006a2a0`；演練根目錄：`D:\MOTRIX-DRILLS\d7-arap-only`；2026-09-27 22:23:31～2026-09-27 22:25:44（134 秒）

| 步 | 結果 | 秒 | 關鍵數據 |
|---|---|---|---|
| 1 備份來源（唯讀） | ✅ | 2.5 | db=4 data_files=821 |
| 2 建演練安裝目錄 | ✅ | 3.0 | files=1844；開發機備份告警封存=True；標記檔 .no_email_send、.no_cloud_archive |
| 4a 預檢 | ✅ | 0.0 | problems=[] |
| 4b 備份＋試還原 | ✅ | 8.3 | files=1017 db=['backend/motrix_erp.db', 'backend/motrix_erp_demo.db'] |
| 4c 轉換 | ✅ | 5.5 | migrate ok=True rc=0 |
| 4d 驗證（新版啟動） | ✅ | 17.0 | problems=[] |
| 5 冒煙 | ✅ | 6.3 | 冒煙 71 項：200×12、缺席期望 404 且回 404×59、不過 0 ；略過 10 |
| 6a 完整回滾（第一份備份） | ✅ | 25.3 | logical_equal_to_source=True；V9 ping=200；problems=[] |
| 6b 再轉換（只回程式前） | ✅ | 19.5 | verify=[]；backup_problems=[] |
| 6c 只回程式 | ✅ | 11.1 | exit=0；V9 ping=200；problems=[] |

final_drill 總判定：✅；stopped_at=None；保留=[]

**另外要驗**（V9 真實資料轉換後的新版；`d7_extra.py`）：總判定 ✅；模組狀態清單 ✅（key＝lock 模組、皆 loaded：{'extra': [], 'missing': []}）

| IP | 項目 | 路徑 | 狀態碼（期望） | 缺少的說明字串 | 回應節錄 |
|---|---|---|---|---|---|
| IP-16 | L1 獎金入口：薪資獎金缺席 | `/api/system/bonus-module-status` | 200（200）✅ |  | {"enabled":false,"notice":"薪資獎金模組未安裝：獎金分潤不提供"} |
| IP-91 | L1 報價預設條款：案件缺席 | `/api/settings/quote-terms-defaults` | 404（404）✅ |  | {"detail":"案件模組未安裝：報價單預設條款不提供"} |
| IP-14 | 出納待付：外包工班缺席 | `/api/cashier/payable-queue` | 404（404）✅ |  | {"detail":"外包工班模組未安裝：出納頁不顯示承攬商匯款"} |
| IP-8 | 出納獎金佇列：薪資獎金缺席 | `/api/cashier/bonus-queue` | 200（200）✅ |  | {"available":false,"visible":true,"notice":"薪資獎金模組未安裝：出納頁不顯示獎金分潤","items":[]} |

- L1 頁面 25 頁：不過 0
- 無路徑參數 GET 全掃：71 支（排除連外／長連線／匯出類 11 支），狀態分佈 {'200': 58, '422': 9, '404': 4}，5xx／連線失敗 0

**product_drill（空庫選配）**：✅；ping 200、登入 200、正對照 /api/auth/me 200；65 項（在：6 項 200；缺席：59 項 404）；不過 0；undeclared_probes=[]

### case-only

包：`D:\MOTRIX-DRILLS\d7-packages\case-only\20260927_220315_c006a2a0`；演練根目錄：`D:\MOTRIX-DRILLS\d7-case-only`；2026-09-27 22:25:45～2026-09-27 22:27:52（127 秒）

| 步 | 結果 | 秒 | 關鍵數據 |
|---|---|---|---|
| 1 備份來源（唯讀） | ✅ | 2.2 | db=4 data_files=821 |
| 2 建演練安裝目錄 | ✅ | 2.7 | files=1844；開發機備份告警封存=True；標記檔 .no_email_send、.no_cloud_archive |
| 4a 預檢 | ✅ | 0.0 | problems=[] |
| 4b 備份＋試還原 | ✅ | 7.8 | files=1017 db=['backend/motrix_erp.db', 'backend/motrix_erp_demo.db'] |
| 4c 轉換 | ✅ | 5.4 | migrate ok=True rc=0 |
| 4d 驗證（新版啟動） | ✅ | 15.5 | problems=[] |
| 5 冒煙 | ✅ | 6.2 | 冒煙 71 項：200×17、缺席期望 404 且回 404×54、不過 0 ；略過 10 |
| 6a 完整回滾（第一份備份） | ✅ | 23.5 | logical_equal_to_source=True；V9 ping=200；problems=[] |
| 6b 再轉換（只回程式前） | ✅ | 17.8 | verify=[]；backup_problems=[] |
| 6c 只回程式 | ✅ | 11.6 | exit=0；V9 ping=200；problems=[] |

final_drill 總判定：✅；stopped_at=None；保留=[]

**另外要驗**（V9 真實資料轉換後的新版；`d7_extra.py`）：總判定 ✅；模組狀態清單 ✅（key＝lock 模組、皆 loaded：{'extra': [], 'missing': []}）

| IP | 項目 | 路徑 | 狀態碼（期望） | 缺少的說明字串 | 回應節錄 |
|---|---|---|---|---|---|
| IP-16 | L1 獎金入口：薪資獎金缺席 | `/api/system/bonus-module-status` | 200（200）✅ |  | {"enabled":false,"notice":"薪資獎金模組未安裝：獎金分潤不提供"} |
| IP-15/18/22 | 案件整包：各段缺席 | `/api/quotations/MQ-EXPFILE-001/case-bundle` | 200（200）✅ |  | {"quotation":{"id":53,"quote_no":"MQ-EXPFILE-001","status":"已送出","customer_name":"測試客戶","project_name":"測試專案","total":50000.0,"pretax":47619.0,"direct_margin_pc |

- L1 頁面 25 頁：不過 0
- 無路徑參數 GET 全掃：71 支（排除連外／長連線／匯出類 10 支），狀態分佈 {'200': 62, '422': 7, '404': 2}，5xx／連線失敗 0

**product_drill（空庫選配）**：✅；ping 200、登入 200、正對照 /api/auth/me 200；65 項（在：11 項 200；缺席：54 項 404）；不過 0；undeclared_probes=[]

### crm-only

包：`D:\MOTRIX-DRILLS\d7-packages\crm-only\20260927_220337_c006a2a0`；演練根目錄：`D:\MOTRIX-DRILLS\d7-crm-only`；2026-09-27 22:27:53～2026-09-27 22:30:01（128 秒）

| 步 | 結果 | 秒 | 關鍵數據 |
|---|---|---|---|
| 1 備份來源（唯讀） | ✅ | 2.1 | db=4 data_files=821 |
| 2 建演練安裝目錄 | ✅ | 2.7 | files=1844；開發機備份告警封存=True；標記檔 .no_email_send、.no_cloud_archive |
| 4a 預檢 | ✅ | 0.1 | problems=[] |
| 4b 備份＋試還原 | ✅ | 9.3 | files=1017 db=['backend/motrix_erp.db', 'backend/motrix_erp_demo.db'] |
| 4c 轉換 | ✅ | 5.7 | migrate ok=True rc=0 |
| 4d 驗證（新版啟動） | ✅ | 15.2 | problems=[] |
| 5 冒煙 | ✅ | 6.0 | 冒煙 71 項：200×10、缺席期望 404 且回 404×61、不過 0 ；略過 10 |
| 6a 完整回滾（第一份備份） | ✅ | 23.3 | logical_equal_to_source=True；V9 ping=200；problems=[] |
| 6b 再轉換（只回程式前） | ✅ | 19.2 | verify=[]；backup_problems=[] |
| 6c 只回程式 | ✅ | 10.6 | exit=0；V9 ping=200；problems=[] |

final_drill 總判定：✅；stopped_at=None；保留=[]

**另外要驗**（V9 真實資料轉換後的新版；`d7_extra.py`）：總判定 ✅；模組狀態清單 ✅（key＝lock 模組、皆 loaded：{'extra': [], 'missing': []}）

| IP | 項目 | 路徑 | 狀態碼（期望） | 缺少的說明字串 | 回應節錄 |
|---|---|---|---|---|---|
| IP-16 | L1 獎金入口：薪資獎金缺席 | `/api/system/bonus-module-status` | 200（200）✅ |  | {"enabled":false,"notice":"薪資獎金模組未安裝：獎金分潤不提供"} |
| IP-91 | L1 報價預設條款：案件缺席 | `/api/settings/quote-terms-defaults` | 404（404）✅ |  | {"detail":"案件模組未安裝：報價單預設條款不提供"} |

- L1 頁面 25 頁：不過 0
- 無路徑參數 GET 全掃：66 支（排除連外／長連線／匯出類 10 支），狀態分佈 {'200': 56, '422': 7, '404': 3}，5xx／連線失敗 0

**product_drill（空庫選配）**：✅；ping 200、登入 200、正對照 /api/auth/me 200；65 項（在：4 項 200；缺席：61 項 404）；不過 0；undeclared_probes=[]

### daily_tasks-only

包：`D:\MOTRIX-DRILLS\d7-packages\daily_tasks-only\20260927_220357_c006a2a0`；演練根目錄：`D:\MOTRIX-DRILLS\d7-daily_tasks-only`；2026-09-27 22:30:02～2026-09-27 22:32:06（124 秒）

| 步 | 結果 | 秒 | 關鍵數據 |
|---|---|---|---|
| 1 備份來源（唯讀） | ✅ | 2.5 | db=4 data_files=821 |
| 2 建演練安裝目錄 | ✅ | 2.9 | files=1844；開發機備份告警封存=True；標記檔 .no_email_send、.no_cloud_archive |
| 4a 預檢 | ✅ | 0.0 | problems=[] |
| 4b 備份＋試還原 | ✅ | 8.1 | files=1017 db=['backend/motrix_erp.db', 'backend/motrix_erp_demo.db'] |
| 4c 轉換 | ✅ | 5.0 | migrate ok=True rc=0 |
| 4d 驗證（新版啟動） | ✅ | 16.9 | problems=[] |
| 5 冒煙 | ✅ | 5.7 | 冒煙 71 項：200×8、缺席期望 404 且回 404×63、不過 0 ；略過 10 |
| 6a 完整回滾（第一份備份） | ✅ | 21.1 | logical_equal_to_source=True；V9 ping=200；problems=[] |
| 6b 再轉換（只回程式前） | ✅ | 16.7 | verify=[]；backup_problems=[] |
| 6c 只回程式 | ✅ | 14.9 | exit=0；V9 ping=200；problems=[] |

final_drill 總判定：✅；stopped_at=None；保留=[]

**另外要驗**（V9 真實資料轉換後的新版；`d7_extra.py`）：總判定 ✅；模組狀態清單 ✅（key＝lock 模組、皆 loaded：{'extra': [], 'missing': []}）

| IP | 項目 | 路徑 | 狀態碼（期望） | 缺少的說明字串 | 回應節錄 |
|---|---|---|---|---|---|
| IP-16 | L1 獎金入口：薪資獎金缺席 | `/api/system/bonus-module-status` | 200（200）✅ |  | {"enabled":false,"notice":"薪資獎金模組未安裝：獎金分潤不提供"} |
| IP-91 | L1 報價預設條款：案件缺席 | `/api/settings/quote-terms-defaults` | 404（404）✅ |  | {"detail":"案件模組未安裝：報價單預設條款不提供"} |

- L1 頁面 25 頁：不過 0
- 無路徑參數 GET 全掃：64 支（排除連外／長連線／匯出類 10 支），狀態分佈 {'200': 54, '422': 7, '404': 3}，5xx／連線失敗 0

**product_drill（空庫選配）**：✅；ping 200、登入 200、正對照 /api/auth/me 200；65 項（在：2 項 200；缺席：63 項 404）；不過 0；undeclared_probes=[]

### netplan-only

包：`D:\MOTRIX-DRILLS\d7-packages\netplan-only\20260927_220419_c006a2a0`；演練根目錄：`D:\MOTRIX-DRILLS\d7-netplan-only`；2026-09-27 22:32:07～2026-09-27 22:34:08（122 秒）

| 步 | 結果 | 秒 | 關鍵數據 |
|---|---|---|---|
| 1 備份來源（唯讀） | ✅ | 2.8 | db=4 data_files=821 |
| 2 建演練安裝目錄 | ✅ | 2.8 | files=1844；開發機備份告警封存=True；標記檔 .no_email_send、.no_cloud_archive |
| 4a 預檢 | ✅ | 0.0 | problems=[] |
| 4b 備份＋試還原 | ✅ | 7.5 | files=1017 db=['backend/motrix_erp.db', 'backend/motrix_erp_demo.db'] |
| 4c 轉換 | ✅ | 5.4 | migrate ok=True rc=0 |
| 4d 驗證（新版啟動） | ✅ | 13.9 | problems=[] |
| 5 冒煙 | ✅ | 5.5 | 冒煙 71 項：200×10、缺席期望 404 且回 404×61、不過 0 ；略過 10 |
| 6a 完整回滾（第一份備份） | ✅ | 21.0 | logical_equal_to_source=True；V9 ping=200；problems=[] |
| 6b 再轉換（只回程式前） | ✅ | 18.5 | verify=[]；backup_problems=[] |
| 6c 只回程式 | ✅ | 12.7 | exit=0；V9 ping=200；problems=[] |

final_drill 總判定：✅；stopped_at=None；保留=[]

**另外要驗**（V9 真實資料轉換後的新版；`d7_extra.py`）：總判定 ✅；模組狀態清單 ✅（key＝lock 模組、皆 loaded：{'extra': [], 'missing': []}）

| IP | 項目 | 路徑 | 狀態碼（期望） | 缺少的說明字串 | 回應節錄 |
|---|---|---|---|---|---|
| IP-16 | L1 獎金入口：薪資獎金缺席 | `/api/system/bonus-module-status` | 200（200）✅ |  | {"enabled":false,"notice":"薪資獎金模組未安裝：獎金分潤不提供"} |
| IP-91 | L1 報價預設條款：案件缺席 | `/api/settings/quote-terms-defaults` | 404（404）✅ |  | {"detail":"案件模組未安裝：報價單預設條款不提供"} |
| IP-12 | 規劃書依案件查詢：案件缺席 | `/api/quotations/MQ-EXPFILE-001/network-plan` | 404（404）✅ |  | {"detail":"案件模組未安裝：無法依案件查詢網路架構規劃書"} |

- L1 頁面 25 頁：不過 0
- 無路徑參數 GET 全掃：64 支（排除連外／長連線／匯出類 10 支），狀態分佈 {'200': 54, '422': 7, '404': 3}，5xx／連線失敗 0

**product_drill（空庫選配）**：✅；ping 200、登入 200、正對照 /api/auth/me 200；65 項（在：4 項 200；缺席：61 項 404）；不過 0；undeclared_probes=[]

### payroll-only

包：`D:\MOTRIX-DRILLS\d7-packages\payroll-only\20260927_220440_c006a2a0`；演練根目錄：`D:\MOTRIX-DRILLS\d7-payroll-only`；2026-09-27 22:34:09～2026-09-27 22:36:17（128 秒）

| 步 | 結果 | 秒 | 關鍵數據 |
|---|---|---|---|
| 1 備份來源（唯讀） | ✅ | 2.9 | db=4 data_files=821 |
| 2 建演練安裝目錄 | ✅ | 2.9 | files=1844；開發機備份告警封存=True；標記檔 .no_email_send、.no_cloud_archive |
| 4a 預檢 | ✅ | 0.0 | problems=[] |
| 4b 備份＋試還原 | ✅ | 7.5 | files=1017 db=['backend/motrix_erp.db', 'backend/motrix_erp_demo.db'] |
| 4c 轉換 | ✅ | 5.2 | migrate ok=True rc=0 |
| 4d 驗證（新版啟動） | ✅ | 15.4 | problems=[] |
| 5 冒煙 | ✅ | 3.8 | 冒煙 71 項：200×13、缺席期望 404 且回 404×58、不過 0 ；略過 10 |
| 6a 完整回滾（第一份備份） | ✅ | 24.2 | logical_equal_to_source=True；V9 ping=200；problems=[] |
| 6b 再轉換（只回程式前） | ✅ | 18.7 | verify=[]；backup_problems=[] |
| 6c 只回程式 | ✅ | 11.8 | exit=0；V9 ping=200；problems=[] |

final_drill 總判定：✅；stopped_at=None；保留=[]

**另外要驗**（V9 真實資料轉換後的新版；`d7_extra.py`）：總判定 ✅；模組狀態清單 ✅（key＝lock 模組、皆 loaded：{'extra': [], 'missing': []}）

| IP | 項目 | 路徑 | 狀態碼（期望） | 缺少的說明字串 | 回應節錄 |
|---|---|---|---|---|---|
| IP-91 | L1 報價預設條款：案件缺席 | `/api/settings/quote-terms-defaults` | 404（404）✅ |  | {"detail":"案件模組未安裝：報價單預設條款不提供"} |
| IP-2 | 獎金傳票科目：會計缺席 | `/api/bonus/cases/voucher-accounts` | 200（200）✅ |  | {"accounts":{"expense":"6111","payable":"2191","withholding":"2252","nhi":"2252","bank":"1113"},"problems":{"expense":"會計模組未安裝，無法驗證科目","payable":"會計模組未安裝，無法驗證科目 |

- L1 頁面 25 頁：不過 0
- 無路徑參數 GET 全掃：74 支（排除連外／長連線／匯出類 10 支），狀態分佈 {'200': 64, '422': 7, '404': 3}，5xx／連線失敗 0

**product_drill（空庫選配）**：✅；ping 200、登入 200、正對照 /api/auth/me 200；65 項（在：7 項 200；缺席：58 項 404）；不過 0；undeclared_probes=[]

### subcontract-only

包：`D:\MOTRIX-DRILLS\d7-packages\subcontract-only\20260927_220501_c006a2a0`；演練根目錄：`D:\MOTRIX-DRILLS\d7-subcontract-only`；2026-09-27 22:36:18～2026-09-27 22:38:26（127 秒）

| 步 | 結果 | 秒 | 關鍵數據 |
|---|---|---|---|
| 1 備份來源（唯讀） | ✅ | 2.3 | db=4 data_files=821 |
| 2 建演練安裝目錄 | ✅ | 3.2 | files=1844；開發機備份告警封存=True；標記檔 .no_email_send、.no_cloud_archive |
| 4a 預檢 | ✅ | 0.0 | problems=[] |
| 4b 備份＋試還原 | ✅ | 9.3 | files=1017 db=['backend/motrix_erp.db', 'backend/motrix_erp_demo.db'] |
| 4c 轉換 | ✅ | 7.2 | migrate ok=True rc=0 |
| 4d 驗證（新版啟動） | ✅ | 17.0 | problems=[] |
| 5 冒煙 | ✅ | 5.7 | 冒煙 71 項：200×13、缺席期望 404 且回 404×58、不過 0 ；略過 10 |
| 6a 完整回滾（第一份備份） | ✅ | 21.0 | logical_equal_to_source=True；V9 ping=200；problems=[] |
| 6b 再轉換（只回程式前） | ✅ | 17.5 | verify=[]；backup_problems=[] |
| 6c 只回程式 | ✅ | 10.2 | exit=0；V9 ping=200；problems=[] |

final_drill 總判定：✅；stopped_at=None；保留=[]

**另外要驗**（V9 真實資料轉換後的新版；`d7_extra.py`）：總判定 ✅；模組狀態清單 ✅（key＝lock 模組、皆 loaded：{'extra': [], 'missing': []}）

| IP | 項目 | 路徑 | 狀態碼（期望） | 缺少的說明字串 | 回應節錄 |
|---|---|---|---|---|---|
| IP-16 | L1 獎金入口：薪資獎金缺席 | `/api/system/bonus-module-status` | 200（200）✅ |  | {"enabled":false,"notice":"薪資獎金模組未安裝：獎金分潤不提供"} |
| IP-91 | L1 報價預設條款：案件缺席 | `/api/settings/quote-terms-defaults` | 404（404）✅ |  | {"detail":"案件模組未安裝：報價單預設條款不提供"} |

- L1 頁面 25 頁：不過 0
- 無路徑參數 GET 全掃：71 支（排除連外／長連線／匯出類 11 支），狀態分佈 {'200': 61, '422': 7, '404': 3}，5xx／連線失敗 0

**product_drill（空庫選配）**：✅；ping 200、登入 200、正對照 /api/auth/me 200；65 項（在：7 項 200；缺席：58 項 404）；不過 0；undeclared_probes=[]

### supply-only

包：`D:\MOTRIX-DRILLS\d7-packages\supply-only\20260927_220522_c006a2a0`；演練根目錄：`D:\MOTRIX-DRILLS\d7-supply-only`；2026-09-27 22:38:27～2026-09-27 22:40:23（116 秒）

| 步 | 結果 | 秒 | 關鍵數據 |
|---|---|---|---|
| 1 備份來源（唯讀） | ✅ | 2.4 | db=4 data_files=821 |
| 2 建演練安裝目錄 | ✅ | 2.9 | files=1844；開發機備份告警封存=True；標記檔 .no_email_send、.no_cloud_archive |
| 4a 預檢 | ✅ | 0.0 | problems=[] |
| 4b 備份＋試還原 | ✅ | 8.2 | files=1017 db=['backend/motrix_erp.db', 'backend/motrix_erp_demo.db'] |
| 4c 轉換 | ✅ | 5.3 | migrate ok=True rc=0 |
| 4d 驗證（新版啟動） | ✅ | 16.9 | problems=[] |
| 5 冒煙 | ✅ | 5.3 | 冒煙 71 項：200×15、缺席期望 404 且回 404×56、不過 0 ；略過 10 |
| 6a 完整回滾（第一份備份） | ✅ | 19.9 | logical_equal_to_source=True；V9 ping=200；problems=[] |
| 6b 再轉換（只回程式前） | ✅ | 16.3 | verify=[]；backup_problems=[] |
| 6c 只回程式 | ✅ | 9.5 | exit=0；V9 ping=200；problems=[] |

final_drill 總判定：✅；stopped_at=None；保留=[]

**另外要驗**（V9 真實資料轉換後的新版；`d7_extra.py`）：總判定 ✅；模組狀態清單 ✅（key＝lock 模組、皆 loaded：{'extra': [], 'missing': []}）

| IP | 項目 | 路徑 | 狀態碼（期望） | 缺少的說明字串 | 回應節錄 |
|---|---|---|---|---|---|
| IP-16 | L1 獎金入口：薪資獎金缺席 | `/api/system/bonus-module-status` | 200（200）✅ |  | {"enabled":false,"notice":"薪資獎金模組未安裝：獎金分潤不提供"} |
| IP-91 | L1 報價預設條款：案件缺席 | `/api/settings/quote-terms-defaults` | 404（404）✅ |  | {"detail":"案件模組未安裝：報價單預設條款不提供"} |

- L1 頁面 25 頁：不過 0
- 無路徑參數 GET 全掃：70 支（排除連外／長連線／匯出類 11 支），狀態分佈 {'200': 60, '422': 7, '404': 3}，5xx／連線失敗 0

**product_drill（空庫選配）**：✅；ping 200、登入 200、正對照 /api/auth/me 200；65 項（在：9 項 200；缺席：56 項 404）；不過 0；undeclared_probes=[]

### tender_radar-only

包：`D:\MOTRIX-DRILLS\d7-packages\tender_radar-only\20260927_220543_c006a2a0`；演練根目錄：`D:\MOTRIX-DRILLS\d7-tender_radar-only`；2026-09-27 22:40:24～2026-09-27 22:42:10（106 秒）

| 步 | 結果 | 秒 | 關鍵數據 |
|---|---|---|---|
| 1 備份來源（唯讀） | ✅ | 2.0 | db=4 data_files=821 |
| 2 建演練安裝目錄 | ✅ | 2.5 | files=1844；開發機備份告警封存=True；標記檔 .no_email_send、.no_cloud_archive |
| 4a 預檢 | ✅ | 0.0 | problems=[] |
| 4b 備份＋試還原 | ✅ | 6.5 | files=1017 db=['backend/motrix_erp.db', 'backend/motrix_erp_demo.db'] |
| 4c 轉換 | ✅ | 4.6 | migrate ok=True rc=0 |
| 4d 驗證（新版啟動） | ✅ | 13.7 | problems=[] |
| 5 冒煙 | ✅ | 3.9 | 冒煙 71 項：200×9、缺席期望 404 且回 404×62、不過 0 ；略過 10 |
| 6a 完整回滾（第一份備份） | ✅ | 20.0 | logical_equal_to_source=True；V9 ping=200；problems=[] |
| 6b 再轉換（只回程式前） | ✅ | 16.3 | verify=[]；backup_problems=[] |
| 6c 只回程式 | ✅ | 9.4 | exit=0；V9 ping=200；problems=[] |

final_drill 總判定：✅；stopped_at=None；保留=[]

**另外要驗**（V9 真實資料轉換後的新版；`d7_extra.py`）：總判定 ✅；模組狀態清單 ✅（key＝lock 模組、皆 loaded：{'extra': [], 'missing': []}）

| IP | 項目 | 路徑 | 狀態碼（期望） | 缺少的說明字串 | 回應節錄 |
|---|---|---|---|---|---|
| IP-16 | L1 獎金入口：薪資獎金缺席 | `/api/system/bonus-module-status` | 200（200）✅ |  | {"enabled":false,"notice":"薪資獎金模組未安裝：獎金分潤不提供"} |
| IP-91 | L1 報價預設條款：案件缺席 | `/api/settings/quote-terms-defaults` | 404（404）✅ |  | {"detail":"案件模組未安裝：報價單預設條款不提供"} |

- L1 頁面 25 頁：不過 0
- 無路徑參數 GET 全掃：63 支（排除連外／長連線／匯出類 14 支），狀態分佈 {'200': 53, '422': 7, '404': 3}，5xx／連線失敗 0

**product_drill（空庫選配）**：✅；ping 200、登入 200、正對照 /api/auth/me 200；65 項（在：3 項 200；缺席：62 項 404）；不過 0；undeclared_probes=[]

## 4. V9 未被動到（E1～E4）

| # | 證據 | 結果 |
|---|---|---|
| E1 | 來源 `*.db` 34 個的 mtime 都早於演練開始 2026-09-27T22:09:07 | ✅  |
| E2 | 來源 `-wal`／`-shm`：演練後 60 個，全部在演練前的清單裡（新產生 0 個） | ✅  |
| E3 | 每份包的 `source-backup` 庫雜湊＝第 1 步記錄（比的是備份複本，不是來源檔） | ✅ full ✅；core-only ✅；accounting-only ✅；analytics-only ✅；arap-only ✅；case-only ✅；crm-only ✅；daily_tasks-only ✅；netplan-only ✅；payroll-only ✅；subcontract-only ✅；supply-only ✅；tender_radar-only ✅ |
| E4 | 來源檔案清單（路徑＋大小＋mtime_ns）演練前 6327 行 vs 演練後 6327 行 | ✅ 差異：前有後無 0、後有前無 0  |

清單檔：`D:\MOTRIX-DRILLS\d7-tools\v9-before.tsv`、`D:\MOTRIX-DRILLS\d7-tools\v9-after.tsv`（`# snapshot 2026-09-27T22:11:50 files=6327`／`# snapshot 2026-09-27T22:50:01 files=6327`）。

## 5. 發現

### 必修
（無）

### 建議
- **S-1 缺席說明的 HTTP 驗證目前只在本次臨時腳本裡**：`final_drill.smoke` 只驗 probes 200／缺席 404，§3「L1 頁在模組缺席時明說、不回 500」與「依賴的 IP 缺席時明說」沒有任何工具在演練層驗。本次以 `d7-tools\d7_extra.py` 補（V9 真實資料轉換後，逐條打 INTEGRATION-POINTS「對方不在時」的 GET 端點＋無參數 GET 全掃 5xx）。建議收進 `final_drill`（擁有者 C 或主持指派），否則下一次正式演練又要手寫。
- **S-2 未以 HTTP 驗的缺席行為**（寫入類或會連外，只有單元題守門）：IP-5（每日任務勾選）、IP-13（刪報價單）、IP-17（派工匯入報價 409）、IP-19（序號 stockNotice）、IP-3／IP-4（獎金發放寫入）、IP-21（line-source-files 需要真實 ref）、IP-97（地圖：`/api/map/points` 可能觸發地址查詢連外，刻意排除）。

### 觀察
- **O-1 本次探針自己出過三個錯（更正留列，不刪）**：
  1. 22:15～22:18 第一版 `d7_verify.py` 的 V4① 在**包目錄內**以預設設定 import `core.source_tree` ⇒ 在 13 份包的 `backend/core/__pycache__` 寫入 39 個 `.pyc`；第二輪 V1 因此在 core-only 紅（`包側 pycache —— __pycache__ 有 3 個命中`）。處置：逐包刪掉那 13 個我建的 `__pycache__`（時間戳皆晚於建包 22:05），V4① 改 `-B`＋`PYTHONDONTWRITEBYTECODE=1`，並在探針前後比對包的檔案清單（不同即 assert）；13 份包重跑 V1～V7 全過；受影響的 full、core-only、accounting-only（矩陣起跑時包內可能已有 .pyc）於 22:42 起用乾淨的包**整份重跑**。演練結束時 13 份包逐檔 sha256 與 V5 清單相同（`pkg_unchanged.py`，bad=0）。
  2. `d7_extra` 第一版把 `/api/system/modules/availability` 判成「缺席的 key 要被提到」；實際契約（system.py docstring、P-FE-02）是「不在清單＝不在安裝包」。core-only、accounting-only、analytics-only 因此假紅；判準改成「key＝lock 模組且皆 loaded」後重跑，全過。
  3. `d7_extra` 第一版 IP-98 打 `expenses-monthly` 沒帶 `basis=cash`（預設權責口徑，本來就不會出現應收應付的說明）⇒ analytics-only 假紅；加上 `basis=cash` 後重跑通過。
  - 以上三項都是**觀測裝置**的錯，不是產品缺陷；最終採用的結果全部來自更正後的重跑。
- **O-2** V3 使用 `git check-attr --stdin` 時，Python text 模式在 Windows 把 stdin 的 `\n` 轉成 `\r\n`，export-ignore 只認出 875／930 ⇒ 第一次 V3 假紅。改位元組模式後 930，與 shell 一致。
- **O-3** 建包紀錄的「入口檢查」警告 7 組路由在 frontend 找不到呼叫點（`/awards`、`/candidates`、`/case-activity`、`/reminder-send-failures`、`/runtime-switches`、`/texts`、`/unavailable-pages`），不擋包；維持原狀。
- **O-4** 本次驗的是 c006a2a0。演練期間 `origin/platform` 已前進到 10b76841；D7 結論只適用 c006a2a0 的 13 份包。
- **O-5** 無參數 GET 全掃（13 份各 63～131 支）沒有任何 5xx；422 是缺必要查詢參數、404 是端點設計（例：缺席模組說明、查無資料）、400 是參數驗證，未逐一判讀。
- **O-6** 用 `--package` 時 final_drill 不另列「3 取新版程式」一步（直接以包目錄為新版來源），所以每份包的步驟表是 10 列；包本身的正確性由 §2 V1～V7 驗。

## 6. 清理

- final_drill 每份包全部通過 ⇒ 由工具刪除 `v9-install`、`upgrade-backup`、`upgrade-backup-2`；`d7_extra` 通過 ⇒ 刪 `extra-app`；V4② 的 `D:\MOTRIX-DRILLS\d7-v4-<產品>` 每份用完即刪；product_drill 的 `%TEMP%\motrix-drill-*` 已刪（查無殘留）。
- 報告產生後刪除：12 份非 full 的演練根目錄 `D:\MOTRIX-DRILLS\d7-<產品>`（source-backup 已完成 E3 比對）、工具 worktree `D:\MOTRIX-DRILLS\d7-src`（`git worktree remove`）。
- 保留：`D:\MOTRIX-DRILLS\d7-results\`（原始結果、雜湊清單）、`D:\MOTRIX-DRILLS\d7-tools\`（腳本、V9 前後清單）、`D:\MOTRIX-DRILLS\d7-progress.txt`。
- **留下待人工刪除的路徑**：`D:\MOTRIX-FINAL-DRILL`（磁碟根下一層；內含 `source-backup`，依 RUN-PLAN §3-7 保留到使用者回來，以及 `final_drill.json`）。
- 殘留行程：演練結束時 python 行程中只有 port 8866 試用環境的兩支 uvicorn（pid 16180、53348，不是本次啟動的，未動）；沒有本次的 uvicorn／pytest 殘留。


## 7. 總判定

**通過**


---

# 附：預演（2026-09-26，原文保留）

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
