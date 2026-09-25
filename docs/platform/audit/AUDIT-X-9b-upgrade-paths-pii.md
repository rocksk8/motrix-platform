# 稽核：C 的升級轉換與回滾（§9b）、core.paths、個資分流（X 稽核，2026-09-25）

> 依 CORE-SPEC §9d、PLAYBOOK §E。這份接手已退役的 A 原本的分配。稽核者 X 沒有寫過任何受稽核的程式碼。
> 基準：platform `23cd8d56`。受稽核的檔案到 `fe38861b` 都沒有變動（`git diff --stat 23cd8d56 origin/platform -- <受稽核檔>` 的結果只有 audit 文件）。
> 分級：**必修**（不修不能關）／**建議**／**觀察**。關閉規則：被稽核者回覆之後，由 X 確認才關。
> 路徑縮寫：`CU`＝`backend/core/upgrade.py`，`TU`＝`tools/platform/upgrade.py`，`DR`＝`tools/platform/upgrade_drill.py`，`A`＝`backend/archive.py`，`CP`＝`backend/core/paths.py`。
> 與既有報告重複的項目只引用、不重複計數：AUDIT-X-C-batch1 的 B-2（鍵存在但值為空字串）、C-5（CU:339 SyntaxWarning）；STATES-DATA-OPS 的 S-CU04／S-CU07／S-CU12。

## 0. 結論

- 五個階段的主幹都成立，而且都有測試：預檢、備份與試還原、只新增的轉換、驗證、兩種回滾。本題相關的既有題目在 X 的環境：**124 passed**（`test_core_upgrade`、`test_core_paths`、`test_pii_archive_mirror`、`test_no_file_relative_data_paths`）；端到端演練 **2 passed**（92 秒）。
- core.paths 與 V9 相容：28 個 V9 既有位置（`NO_EMAIL_SEND_MARKER` 是新增的，不算在內）加上 7 個 PDF 目錄，X 直接對照 V9 `c83dae6e` 的原始碼逐一核對，全部相同（不是只看測試裡手寫的對照表）。
- 個資分流：整庫 `.db` 只放個資資料夾；一般 JSON 會拿掉 F2 欄位；資料夾不存在時會告警、不會建立。三項都經反向控制確認。
- **必修 4 項**：
  1. M-1：`verify` 啟動新版之後的比對沒有「補空值」例外。只要轉換補了公司資料，驗證就一定不過。
  2. M-2：回滾之後的資料清單要求「完全相同」。新版上線後只要有人上傳過檔案，或新版做過一次每日快照，兩種回滾都會回報失敗，包括建議優先使用的「只回程式」。
  3. M-3：外包個人的銀行帳號（F2）被凍結進 `contractor_payment_vouchers.snapshot_json`，照樣寫進一般每日備份和月備份。
  4. M-4：`backend/autostart.bat` 是機器自己的設定檔（對外連線的兩個總開關），卻被歸類成程式。轉換時會被新版包裡的檔案覆蓋，驗證看不出來。
- 建議 7 項、觀察 9 項。

## 1. 逐項驗收

### 1a. §9b 升級轉換與回滾

| 階段 | 規格 | 驗收 | 證據 |
|---|---|---|---|
| 0 預檢 | 明確給路徑（不猜）；schema_version ≤ 116；空間 ≥ DB×3；最近一次 `.done`；沒有告警；服務已停；任一項不過就什麼都不動 | ✅ | CU:270-332；`test_preflight_*` 7 題全綠；另有 quick_check（S-CU10）。空間只算 DB×3（S-CU09，已列管） |
| 1 備份 | ① Online Backup API ② 程式快照 ③ 設定與身分檔 ④ 資料只列清單 ⑤ manifest 的 SHA256；完成後試還原並比對，不過就中止 | ✅ | CU:342-420；TU:108-116（不過 ⇒ exit 2）。反向控制 RC1 三類竄改都轉紅。manifest 本身沒有外部錨點（O-2） |
| 2 轉換 | 換程式；migration；設定只補缺的鍵；只准新增 | ⚠ | 設定鍵 ✅（`test_add_missing_settings_*`）；公司資料只補空值 ✅（RC5：已有值不動）。**autostart.bat 被覆蓋**（M-4）；「只新增」只驗列數（S-3） |
| 3 驗證 | 非正式 port 啟動＋ping；列數相同；設定逐項相同；資料清單相同；**任一不過 ⇒ 自動回滾** | ⚠ | CU:578-604、TU:145-159。**啟動後的比對有假紅**（M-1）。規格寫「自動回滾」，工具是 exit 3、交給人決定（S-4） |
| 4 回滾 | full：程式＋DB＋設定還原，雜湊一致，V9 能 ping；code：保留新資料；兩種模式都有自動化測試 | ⚠ | CU:622-660；演練兩種模式都綠（DR）。**轉換後有新資料檔就假紅**（M-2）；回滾前不驗備份、不核對安裝根目錄（S-1）；full 回滾後的 DB 等於「備份副本」而不是「原檔」的位元組（O-1） |
| 時效確認 | full 前列出轉換後新增的列數，需要明確確認 | ⚠ | TU:171-178。轉換必定新增 `system_settings` 一列，所以提示永遠只顯示 `{"system_settings": 1}`；被改寫的列、新表的列都不會列出（S-3） |

### 1b. core.paths

| 項目 | 驗收 | 證據 |
|---|---|---|
| 值與 V9 原位置相同（原地讀取） | ✅ | X 對照 V9 原始碼：`db.py:16-36`、`archive.py:111-157`、`helpers/uploads.py:20`、`pdf_gen.py:18-83`、`routers/payslips.py:31`、`helpers/licensing.py:61`、`heartbeat_job.py:14`、`helpers/auth.py:37`、`helpers/startup.py:155`、`helpers/build_info.py:43`、`routers/daily_tasks.py:1284`、`routers/auth.py:290,329`、`main.py:35`、`photos.py:10`、`db.py:4318`（`git show c83dae6e:<檔>`）。全部與 CP:38-93 相同 |
| 錨點是安裝根目錄，不是呼叫者的 `__file__` | ✅ | 守門 `test_no_file_relative_data_paths`。**突變**：在 `routers/payslips.py` 加一行 `os.path.join(os.path.dirname(__file__), "..", "export_archive")` ⇒ 守門轉紅（X 實測，已還原） |
| 主庫不存在時拒絕啟動 | ✅ | CP:105-128；`test_require_db_*` 5 題 |
| 升級工具的版面從 core.paths 推導 | ⚠ 大致成立 | CU:43-71。`backend/rollback_snapshots`、`exports` 寫死在 CU:54-55，不在 core.paths（O-8） |

### 1c. 個資分流

| 項目 | 驗收 | 證據 |
|---|---|---|
| 勞報單存檔只進個資資料夾，不進一般 PDF 鏡像 | ✅ | A:1313-1325；A:1186-1200（6 類，不含勞報單）；`test_payslips_do_not_go_into_the_general_pdf_mirror` |
| 含個資的表：一般 JSON 拿掉 F2 欄位，完整列另存個資資料夾 | ⚠ | contractors／payslips ✅（A:2044-2081；哨兵測試）。**F2 值被複製進別的表**（M-3） |
| 整庫 `.db`（每日、月）只放個資資料夾 | ✅ | A:1110-1119、A:2237-2253；P1：資料夾不存在時，一般樹沒有 `.db`，月備份不寫 `.done` |
| 個資資料夾不存在 ⇒ 告警、不建立、不寫進一般備份 | ✅ | P1（每日＋週＋月）；**突變**：在 `pii_archive_status` 加 `os.makedirs(root)` ⇒ 4 題轉紅（X 實測，已還原） |
| 任何路徑都不會自動建立 `系統存檔_個資` | ⚠ | 見 §2 S-5：所有寫入端都是「先 isdir、再用 makedirs 連上層一起建」。資料夾在兩步之間消失的話，會被建回來（P3 實測） |
| 還原時合回 | ✅（手動步驟） | `merge_general_and_pii`（A:2084-2108）；DR-SOP §3a。沒有工具呼叫它，只有 SOP 的程式片段（O-6） |

**mkdir／makedirs 呼叫者盤點**（`grep -n -E "makedirs|\.mkdir\(" backend/archive.py`）：共 11 處。會碰到個資資料夾的只有三條路徑：A:338（`_cloud_copy_file`，被 A:1116、A:2247、`_mirror_directory_incremental`→A:1322 使用）、A:2119（`_export_pii_json_set`）。三條路徑前面都有 `pii_archive_status()` 的 `isdir` 檢查。其餘 8 處的目標是一般存檔、本機快照或告警目錄。PowerShell 的 `_prod_health_facts.ps1:33-39` 只做 `Test-Path`。

## 2. 發現

### 必修

**M-1　`verify` 啟動新版之後的「既有設定不得被改寫」比對，沒有「補空值」的例外：只要補過公司資料，驗證就一定不過**
- 位置：TU:153-157。這裡逐鍵比對 `after.get(k) != v`，用的是轉換**前**的設定。CU:594-596 的 `verify_conversion` 已經允許 `company_profile` 補上欄位，這裡卻沒有同樣的例外。
- 實測（真的 V9 `c83dae6e`，真的啟動新版，演練目錄在 %TEMP%）：把 company_profile 設成本公司、`contact_info` 只有電話 ⇒ 轉換補了 `company_name_en`、`email` ⇒ `verify_conversion` 回 `[]`，但 `T.verify` 回 `["新版啟動後改寫了既有設定：['company_profile']"]`，exit 3。
- 為什麼是必修：
  - 這條路徑本來就是為了「補空值」而設計的，只要真的補了，結果就一定是假紅。RUNBOOK §5 寫的是「不通過 ⇒ exit 3 ⇒ 進 §6 回滾」。
  - 演練的庫是全新的（統編空白 ⇒ 不補），所以兩題演練都綠（見 S-6）。
  - 正式機如果 m106 已經把 5 欄都補齊，這次就不會觸發。但工具判斷不出正式機是哪一種情況。
- 重現（在 `backend/` 底下執行，不會建立任何庫）：
  ```python
  import os,sys,json,sqlite3,tempfile
  sys.path.insert(0,'../tools/platform'); import upgrade as T; U=T.U
  t=tempfile.mkdtemp(); r,n,bd=[os.path.join(t,x) for x in ('i','n','bk')]
  def w(p,b=b'x'): os.makedirs(os.path.dirname(p),exist_ok=True); open(p,'wb').write(b)
  w(r+'/backend/db.py'); w(n+'/backend/db.py',b'#new'); db=r+'/backend/motrix_erp.db'
  c=sqlite3.connect(db); c.execute("create table system_settings(key text primary key,value_json text,updated_at text)")
  c.execute("insert into system_settings values('company_profile',?,'')",(json.dumps({'name':'允碩整合集創股份有限公司','tax_id':'60575481'}),)); c.commit(); c.close()
  U.backup(r,bd); T._write_log(bd,'backup_verify.json',{'problems':U.verify_backup_restorable(bd)})
  T.run_migrations=lambda root: type('R',(),{'returncode':0,'stdout':'MIGRATE_OK','stderr':''})()
  T.start_and_ping=lambda *a,**k: {'ok':True,'status':200,'log':''}
  T.convert(r,bd,n); print(U.verify_conversion(r,U.load_manifest(bd)), T.verify(r,bd,1))
  # ⇒ []  ["新版啟動後改寫了既有設定：['company_profile']"]
  ```
- 建議修法：
  - 啟動後的比對改用與 `verify_conversion` 相同的判準；最好共用同一支函式，不要各寫一份。
  - 補一題：轉換「有補欄位」的情況下，跑完整的 `T.verify`。
  - 演練加一個「本公司、欄位不齊」的變體（S-6）。

**M-2　回滾之後要求資料清單「完全相同」：新版上線後只要寫過一個資料檔，兩種回滾都會回報失敗**
- 位置：CU:658-659（`inventory(...) != manifest["data_inventory"]`），兩種模式都會執行。
- 實測（RC6）：轉換後新增 `uploads/projects/2/new_after_upgrade.jpg`，或新增一份 `backend/db_backups/<日>/.done`（新版每天都會做快照）⇒ `rollback(code)` 和 `rollback(full)` 都回 `['資料目錄與轉換前不同']`，CLI exit 5「回滾後比對不通過」。但程式檔的雜湊其實已經和備份逐一相等。
- 為什麼是必修：
  - 「只回程式」的定義就是保留轉換後的資料。而新版只要跑過一天，每日快照就會寫進 `db_backups`，所以正式機上真的需要回滾時，幾乎一定會落進這個情況。
  - 操作者分不出「回滾真的失敗」和「新版寫過資料」這兩種狀況。RUNBOOK §6 對 exit 5 的說明只有「不一致」一種。
  - 演練在轉換後只寫 DB，沒有寫檔（DR:92-100），所以沒有測到。
- 重現：接在 M-1 的片段後面，加上 `w(r+'/uploads/projects/9/after.jpg',b'new'); print(U.rollback(r,bd,'code'))` ⇒ `['資料目錄與轉換前不同']`。
- 建議修法：
  - 回滾驗證改成「轉換前清單裡的每一個檔都還在，而且雜湊相同」（不准少、不准改）。
  - 新增的檔案列成資訊，不算 problem。
  - 補兩題：轉換後新增一個上傳檔，再做 code 回滾與 full 回滾。

**M-3　外包個人的銀行帳號（F2）經由付款憑據的快照，進入一般每日備份與月備份**
- 位置：
  - `backend/routers/contractor_vouchers.py:283-306`：建立承攬付款憑據時，從 `contractors` 撈出每位外包人員的 `bank_account_name`、`bank_account_number`（還有存摺影像），凍結進 `snapshot_json.personnel[]`。
  - `_F2_FIELDS`（A:2044-2055）只宣告了 `contractors` 和 `payslips` 兩張表；`承攬付款憑據`（A:1851）照一般表匯出，只拿掉內嵌影像。
- 實測（P2，`client`＋`isolated_archive`，個資資料夾已建立）：在 `snapshot_json` 放一個外包人員的帳號哨兵，跑 `_daily_backup()` ⇒ 哨兵出現在 `每日備份/<日>/承攬付款憑據.json` 和 `月備份/<月>/承攬付款憑據.json`。
- 為什麼是必修：
  - 同一個值在 `contractors` 表已經被宣告成 F2、在一般份會被拿掉，換一張表存放就原樣上了一般雲端。這正是〈外洩的出口不一定是你寫的〉描述的情況。
  - 使用者裁示①的範圍是「含個資的表改備份到個資資料夾，一般備份排除」，主持也釐清過「所有個人識別／帳戶欄位」。
  - 守門題 `test_general_cloud_tree_has_no_db_no_f2_no_f3` 只在 contractors／payslips 兩張表放了哨兵，所以抓不到。
- 重現（在 `backend/` 底下）：`python -c "import archive,json;print(archive._general_row('承攬付款憑據',{'id':1,'snapshot_json':json.dumps({'personnel':[{'bankAccountNumber':'777000111222'}]})}))"` ⇒ 帳號原樣保留。
- 建議修法：
  - `_F2_FIELDS` 加上 `承攬付款憑據`，用 JSON 路徑 `snapshot_json.personnel[].bankAccountName／bankAccountNumber` 拿掉這兩個值，完整列另存個資資料夾；`merge_general_and_pii` 也要支援巢狀路徑。
  - 守門改成「在 contractors 放哨兵 → 走真正的建立憑據 API → 跑每日備份 → 掃一般樹」。這樣哨兵的傳遞路徑由產品程式決定，不是由測試指定。
  - `vendor_contractors` 的帳號是否也屬於個資，需要裁示（O-9）。

**M-4　`backend/autostart.bat` 是機器自己的設定，被歸類成程式：轉換時被新版包覆蓋，驗證看不出來**
- 位置：CU:86-92（沒有落在資料、DB、設定裡的，一律歸成 `program`）。`backend/autostart.bat:5-17` 自己寫明「這兩個是【這台機器的設定】……要關掉：把下面兩行加上 :: 註解掉」，也就是 `MOTRIX_TENDER_RADAR`、`MOTRIX_GEO` 兩個對外連線的總開關。
- 實測（RC9）：安裝目錄裡把這一行註解掉，新版來源保持開啟 ⇒ 轉換之後變成開啟；`verify_conversion` 回 `[]`。回滾（兩種模式）會還原。
- 為什麼是必修：
  - §9b 規定「設定轉換……不改寫既有值」。這個檔在事實上就是設定，而它管的正是「不會在沒有人知道的情況下連到外面」這個承諾。
  - 正式機如果沒有改過這個檔，就沒有實害。但工具判斷不出有沒有改過。
- 建議修法（二選一，需要主持裁示）：
  - (a) 歸類成設定：保留機器上的版本。新版的 autostart 有改動時，另外提示。
  - (b) 預檢時把 `<ROOT>` 的 autostart.bat 和 V9 基準比對，不同就列成 problem，要求人決定。
  - 無論哪一種，都要補一題守門。

### 建議

- **S-1　回滾前沒有先驗備份，也沒有核對安裝根目錄；先刪程式檔，才發現備份有問題**（CU:622-641）
  - RC8：刪掉備份裡的一個程式檔 ⇒ `rollback(code)` 刪完現有程式後，在複製時丟 `FileNotFoundError`。安裝目錄只剩 3 個檔，而且沒有寫 `rollback_code.json`。
  - RC1c：備份驗過之後才被改 ⇒ `convert` 只看 `backup_verify.json`、不重驗（TU:120-125），照樣轉換；要等回滾完才報「程式檔與備份不一致」。
  - RC7：拿另一個安裝的備份做 full 回滾 ⇒ 不拒絕，把別人的 DB 還原進來（`manifest["root"]` 從來沒有被比對過）。
  - 建議：回滾（以及轉換）一開始先核對 `manifest["root"] == root`、逐檔驗雜湊，全部通過才開始刪檔。與 S-CU07（回滾不是原子的）一起處理。
- **S-2　試還原不能重跑；DB 標頭損毀時是丟例外，而不是列出問題**
  - RC1e：`backup_verify.json` 寫出之後，再跑 `verify_backup_restorable` 必定得到「多 ['backup_verify.json']」（CU:396 只排除 manifest）。這會擋住 S-1 需要的「回滾前重驗」。建議排除工具自己寫的 `*_log.json`、`backup_verify.json`、`rollback_*.json`。
  - RC1d：竄改備份 DB 的第一個位元組 ⇒ `integrity_ok` 丟 `DatabaseError`（CU:179-184、412），不會列成 problem。CLI 會以 traceback 結束，不會寫 `backup_verify.json`，所以後續 convert 仍然會擋（fail closed）。建議改用已經有的 `quick_check()`（CU:166）。另外 demo 庫沒有做完整性檢查（O-7）。
- **S-3　「只准新增」只驗列數；full 回滾的確認提示是空的**
  - RC10：轉換後 `UPDATE customers SET name=…`，同時在新表寫入一列 ⇒ `verify_conversion` 回 `[]`；`rows_added_since` 只回 `{"system_settings": 1}`（CU:583-589、609-612）。
  - 因為轉換一定會新增 `payslip_archive_path`，提示永遠不是空的，但內容永遠說不出「哪些業務資料會消失」。
  - 建議：
    - 轉換前記下各表內容的雜湊（或 `max(updated_at)`），驗證時比對。
    - full 回滾的提示列出「被改寫的表」和「新表的列數」，並扣掉轉換本身寫入的那一列。
- **S-4　規格與工具不一致：「驗證不過 ⇒ 自動回滾」「回滾後啟動 V9 驗證 ping」**
  - §9b 第 3、4 列是這麼寫的。工具的做法是 exit 3 交給人決定（TU:13、162-168），回滾後也不會啟動 V9（TU:171-182）。RUNBOOK §5、§6 則寫成人工步驟。
  - 請主持裁示以哪一邊為準，然後修改另一邊。
- **S-5　個資資料夾「永不自動建立」只靠事前的 isdir 檢查**
  - A:338（`os.makedirs(os.path.dirname(dest))`）和 A:2119 會連上層一起建立。
  - P3：`_pii_db_path` 看到資料夾存在 ⇒ 資料夾被移除 ⇒ `_cloud_copy_file` 把 `系統存檔_個資` 建了回來。
  - 雲端硬碟同步、使用者刪除或改名，都可能發生在一次長時間鏡像的中途（勞報單逐檔複製）。
  - 建議：寫一支「只建根目錄以下各層、根目錄不在就失敗」的 helper（逐層 `os.mkdir`，不用 `makedirs`），三條個資寫入路徑都改用它。再補一題：模擬「檢查之後才消失」。
- **S-6　演練的夾具有盲區，所以 M-1、M-2 在綠燈下漏掉**（DR:62-100）
  - V9 主庫是全新建立的（統編空白 ⇒ 轉換不補欄位）；轉換後只寫 DB、不寫資料檔；`v9_after_start_row_kept` 有算但沒有斷言。
  - 建議加兩個變體：「本公司、欄位不齊」和「轉換後有上傳檔與每日快照」。
- **S-7　轉換會刪掉安裝目錄裡不認得的檔案，紀錄只有數量**（CU:429-446；TU:126）
  - 程式類的判定是「其他全部」。正式機上人放的檔（例如根目錄的備註、臨時腳本）在轉換後就從安裝目錄消失了（只留在備份裡）。`conversion_log.json` 只記 `removed`／`added` 兩個數字。
  - 建議：把「被刪除、而新版沒有對應檔」的清單寫進紀錄，讓人看得到。

### 觀察

- **O-1　full 回滾後，DB 與「原檔」的位元組不同，與「備份副本」相同**：RC3（delete／WAL 兩種模式）和真實 V9 演練（WAL）都一樣。邏輯內容（`iterdump`）完全相同，包括還沒 checkpoint 的 WAL 內容。差異只在 SQLite 標頭的 offset 24-27（file change counter）和 92-95（version-valid-for），是 Online Backup API 的正常行為。這符合規格（「雜湊與備份一致」），但 CLI 的「回滾完成，雜湊逐一相等」、`test_full_rollback_restores_program_db_and_config_by_hash` 的雜湊比對都是「複製之後比對副本自己」；真正獨立的證據是列數斷言（`customers == 2`）。建議 manifest 另外記下原檔的 `iterdump` 雜湊，回滾後比對它，輸出的字句也寫清楚比的是哪一份。
- **O-2**：manifest 沒有外部錨點。檔案和 manifest 一起改，試還原照樣通過（RC1b）。它能偵測損毀，偵測不了蓄意竄改。本機工具可以接受，但在 RUNBOOK 寫明比較好。
- **O-3**：CU:339 的 SyntaxWarning 已經由 AUDIT-X-C-batch1 C-5 回報。另外 CU:216 是一行被壓成一行的長條件（中間夾著大段空白），不影響行為，讀起來像換行被吃掉了。
- **O-4**：「鍵存在、值是空字串」會被補值，也會被驗證判成改寫，已經由 AUDIT-X-C-batch1 B-2 回報（X 的 RC5b 重現了）。V9 的 `CompanyProfile` 沒有 phone／email 欄位，m106 只寫非空值，所以在正式機上是理論情況。修 M-1 時請一起處理。
- **O-5**：個資資料夾不存在的那段期間，月備份不寫 `.done`，所以一般的月 JSON 每天都會重新匯出並覆蓋，內容會漂成「當月最後一次的資料」。每天會有一封告警（有上限）。這是設計，可以在文件寫明。
- **O-6**：`test_general_rows_drop_f2_fields_and_merge_restores_the_original` 把「記憶體裡的原始列」當成個資份來合回，沒有經過 `_export_pii_json_set` 實際寫出的檔案。合回的正確性證明了，但「個資份的檔案真的能合回」沒有證明。另外沒有任何工具呼叫 `merge_general_and_pii`，只存在 DR-SOP 的片段裡。
- **O-7**：試還原只對主庫做 integrity 與列數檢查；demo 庫只比雜湊。
- **O-8**：CU:54-55 的 `backend/rollback_snapshots`、`exports` 寫死在升級工具裡，不在 core.paths。「版面由 core.paths 推導」只有部分成立。
- **O-9**：`vendor_contractors`（協力廠商）的 `bankAccountNumber` 照一般表匯出。對象如果是個人工作室就屬於個資；需要裁示它的分類（與 M-3 一起決定）。

## 3. 反向控制與假綠燈

實際執行過的反向控制（臨時測試檔 `tests/platform/test_aud2_adhoc.py`、`tests/test_aud2_pii_adhoc.py`，以及演練腳本，都只在 X 的 worktree 執行、沒有 commit，跑完已刪除）：

| # | 控制 | 結果 |
|---|---|---|
| RC1 | 備份的程式檔／DB（中段位元組）／設定檔被竄改 ⇒ 試還原 | ✅ 三類都得到「雜湊不符」 |
| RC1b | 檔案與 manifest 一起改 | 通過（O-2） |
| RC1c | 驗證過之後才竄改 ⇒ convert、回滾 | convert 不擋；回滾後才報錯（S-1） |
| RC1d | DB 標頭被竄改 | `DatabaseError`，不是列出問題（S-2） |
| RC1e | 寫出 `backup_verify.json` 之後重跑試還原 | 必定是紅的（S-2） |
| RC2 | convert 中途失敗（新版 `db.py` 讓 migration 失敗）⇒ code／full 回滾 | ✅ 兩種模式都回 `[]`。code：整個安裝目錄的逐檔雜湊與轉換前相同；full：只有主庫的位元組不同（O-1） |
| RC2b | `replace_program` 複製到第 2 個檔時崩潰 ⇒ code 回滾 | ✅ 安裝目錄逐檔雜湊與轉換前相同 |
| RC3／RC3b | full 回滾後，DB 與原檔比對（delete／WAL／未 checkpoint 的 WAL） | 位元組不同、邏輯相同（O-1） |
| 演練 | 真 V9＋真新版：本公司欄位不齊 ⇒ 轉換 ⇒ verify ⇒ full 回滾 ⇒ V9 ping | verify 假紅（M-1）；回滾 `[]`；DB 邏輯相同、位元組不同；V9 ping 200 |
| RC5 | 只補空值：已有值的欄位 | ✅ 原始 JSON 逐位元組不變 |
| RC6 | 轉換後新增上傳檔／每日快照 ⇒ 回滾 | 兩種模式都假紅（M-2） |
| RC7 | 用別的安裝的備份做回滾 | 不拒絕（S-1） |
| RC8 | 備份缺一個程式檔 ⇒ 回滾 | 刪完程式後崩潰（S-1） |
| RC9 | autostart.bat 在正式機被改過 | 轉換覆蓋、驗證看不到（M-4） |
| RC10 | 轉換後 UPDATE 既有列、在新表寫入一列 | 驗證與 full 提示都看不到（S-3） |
| P1 | 個資資料夾不存在 ⇒ 每日＋週＋月備份 | ✅ 不建立；一般樹沒有 `.db`，也沒有 F2／F3 哨兵；月備份不寫 `.done`；有告警。正對照：一般每日與月 JSON 確實有寫出來 |
| P2 | 外包人員帳號經由付款憑據的快照 | 進了一般每日與月備份（M-3） |
| P3 | 檢查之後資料夾才消失 ⇒ 寫入 | 資料夾被建回來（S-5） |
| 突變① | 產品碼加入用 `__file__` 算的資料路徑 | 守門轉紅 ✅ |
| 突變② | `pii_archive_status` 自己建立資料夾 | 4 題轉紅 ✅ |

假綠燈：

- **斷言驗到自己設的值**：full 回滾的「雜湊逐一相等」比對的是剛從備份複製過來的那一份（O-1）。`test_core_paths` 的 V9 對照表是測試裡手寫的（X 另外對照了 V9 原始碼，結論相同）。
- **夾具的形狀**：演練用全新的 V9 庫，而且轉換後不寫資料檔，所以 M-1、M-2 在兩題演練都綠的情況下漏掉了（S-6）。個資守門只在兩張 F2 表放哨兵，M-3 在守門綠的情況下漏掉了。
- **觀測點**：`test_without_pii_folder_the_db_is_not_copied_anywhere_in_the_cloud` 的「沒有 `.db`」在快照分支沒跑到時也會成立。不過同一題斷言了「個資資料夾未建立」的告警，而另一題正對照證明同一個夾具下 `.db` 確實會寫進個資資料夾，所以這一題可以採信。
- **夾具污染**：沒有發現。`isolated_archive` 每題自己一個存檔根目錄，並清掉所有權快取。

環境備註：在 X 的 worktree 用主樹的 `.venv` 執行時，如果沒有設 `PYTHONDONTWRITEBYTECODE=1`，`test_pii_archive_mirror` 會被 BK19 擋下，因為它把寫到 `D:\MOTRIX-PLATFORM\.venv\...\__pycache__` 視為寫到 repo 之外。這是環境問題，不是產品問題；但別的 worktree 共用主樹 `.venv` 時會碰到同樣的情況，建議 B 的 venv 工具說明寫一句。

## 4. 回覆欄（被稽核者填；X 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | X 確認 |
|---|---|---|---|
| M-1 | 修正。新增 `U.settings_changes()`，`verify_conversion` 與 `T.verify` 的啟動後比對共用同一支（補空值不算改寫）。補題：`test_m1_full_verify_accepts_the_company_fill`（跑完整 `T.verify`）；反向控制 `test_m1_rewrite_during_startup_is_still_caught`（啟動時改寫 `pdf_base_path` ⇒ 紅）。演練夾具改成「本公司、欄位不齊」（S-6）。修正前實跑（b2469f61 程式＋新夾具）：演練 verify＝`["新版啟動後改寫了既有設定：['company_profile']"]`。突變（改回逐鍵相等）⇒ 紅 | eda4d3cb | |
| M-2 | 修正。新增 `U.data_changes()`：回滾只核對備份時就在的檔（不見或被改＝problem，訊息列出路徑）；新增的檔列進 `info.data_added`；本機每日快照 `db_backups/` 缺少或改變列進 `info.data_rotated`（保留期限清除是正常行為），兩者都不算失敗，CLI 印成資訊。補題：code／full × 轉換後新增上傳檔＋每日快照＋舊快照被清；反向控制：code／full × 既有資料檔不見／被改 ⇒ 仍紅。演練轉換後改寫上傳檔與每日快照（S-6）。修正前演練實跑：code、full 都回 `['資料目錄與轉換前不同']`。突變 2 個（改回完全相同、拿掉快照例外）⇒ 皆紅 | eda4d3cb | |
| M-3 | 修正。`_F2_FIELDS` 加 `承攬付款憑據`，新規格 `json_list`＝`snapshot_json.personnel[]` 的 `bankAccountName`／`bankAccountNumber`／`bankPassbookImage`：一般份拿掉，完整列進個資資料夾，`merge_general_and_pii` 整欄取個資份合回。守門 `test_general_tree_has_no_f2_copied_into_other_tables`：外包人員哨兵 → **真實 API**（協力廠商 → 派工 → 建立憑據）→ 每日＋週備份 → 掃一般樹：①哨兵值不可以出現 ②所有 JSON 欄位裡 F2 鍵名（由 `_F2_FIELDS` 推導）有值的位置必須在允許清單，而且清單每一條都要真的出現。正對照：個資資料夾有哨兵；掃描器正對照一題。最上層的協力廠商帳戶列在允許清單並標 O-9 待裁示。突變 2 個（拿掉宣告、不處理 json_list）⇒ 皆紅。MODULE-GUIDE §3.2 補規則與守門 | eda4d3cb | |
| M-4 | 修正，採 (a)。`core.paths.AUTOSTART_BAT`，歸類成設定（備份、完整回滾還原）；轉換保留機器上的版本，機器沒有才從新版包補上，兩邊不同 ⇒ `conversion_log.json` 的 `package_default_config` 與 CLI 提示人比對；`verify_conversion` 另比 manifest 內所有設定檔的雜湊。只有 `PACKAGE_DEFAULT_CONFIG` 宣告的檔會從包補上（開發機標記、授權不會）。補題 4＋classify 2。突變 2 個（不歸設定、verify 不看設定檔）⇒ 皆紅 | eda4d3cb | |
| S-1 | 修正。新增 `U.check_backup()`：manifest 讀得到、`manifest.root` 與 `--root` 相符、逐檔雜湊＋試還原。回滾動手前先跑，不過就一個檔都不動（CLI exit 7）；`convert` 也重驗，不再只看 `backup_verify.json`。補題：RC7（別人的備份）、RC8（備份缺檔）、RC1c（驗過之後才被改）、CLI exit 7，皆斷言安裝目錄逐檔雜湊不變。突變 2 個 ⇒ 皆紅。S-CU07（回滾不是原子的）沒有處理：前置驗證排除了「備份有問題」這個最主要的中途失敗原因；複製途中崩潰仍會停在一半，重跑同一個回滾指令可收斂 | eda4d3cb | |
| S-2 | 修正。工具寫在備份目錄最上層的紀錄檔（`TOOL_LOG_NAMES`＋`rollback_*.json`）不算備份檔 ⇒ 試還原可以重跑；DB 讀不了列成 problem，不丟例外；demo 庫也做 integrity（O-7）。沒有改用 `quick_check`：`integrity_check` 比較完整，例外改由 try 接住。補題：重跑＋反向控制（子目錄的多餘檔仍紅）、主庫／demo 庫標頭損毀。突變 2 個 ⇒ 皆紅 | eda4d3cb | |
| S-3 | 修正。備份時記各表內容雜湊 `pre.digests`（只比轉換前就有的欄 ⇒ migration 新增欄不算改寫）；`verify_conversion` 報「列數相同、內容不同」。轉換完成寫 `post_convert.json`；完整回滾前 `changes_since_conversion()` 列出新增／被刪／被改寫的表／新表的列，基準是轉換完成當下（轉換本身寫的那幾列不算）；沒有基準檔（轉換沒做完）退回備份當下並註明。限制：同一張表同時有新增與改寫時只報新增。演練實測 V9→新版轉換沒有改寫任何既有表。補題 4。突變 2 個 ⇒ 皆紅 | eda4d3cb | |
| S-4 | 主持裁示寫進 CORE-SPEC §9b（保留原句並註明更正）：以工具現行作法為準，交給人決定。工具：驗證不過 exit 3，並印「建議執行回滾」與兩條完整指令（先只回程式）；回滾比對通過之後，自動在 `--ping-port`（預設 6671）啟動 V9 並 ping，只印結果、寫進 `rollback_<mode>.json`，ping 不過 exit 6；`--no-ping` 可略過。演練改走同一條路（`T.rollback_and_ping`）。RUNBOOK §5、§6 同步。補題 4。突變 2 個（不 ping、不提示）⇒ 皆紅 | eda4d3cb | |
| S-5 | 修正。`_pii_ensure_dir()` 逐層 `os.mkdir`，根目錄不在 ⇒ `PiiFolderMissing`（`os.mkdir` 不建上層，所以檢查之後才消失也建不回來）；`_pii_copy_file()`。每日整庫、月整庫、個資 JSON、勞報單鏡像四條寫入路徑改用；失敗 ⇒ ERROR 告警「個資資料夾在寫入途中消失」，不建回來。補題 5（含 isdir 之後、mkdir 之前消失的最窄競態，以及整輪每日備份）。突變 5 個 ⇒ 皆紅。月整庫那一條只有 helper 題覆蓋。⚠ 未守門：**新增**的寫入路徑有沒有走 helper，排進 ROADMAP G6b | eda4d3cb | |
| S-6 | 修正。演練夾具新增 `company_incomplete`（本公司、統編有值、聯絡方式只有電話 ⇒ 轉換補英文名與 email）與 `write_files`（轉換後寫上傳檔與每日快照），預設開啟；另斷言 `v9_after_start_row_kept`、`new_files_kept`、補了哪些欄位、`changes_since_conversion`、回滾結束碼、O-1。修正前實跑（b2469f61 程式＋新夾具）：M-1 變體 verify 紅；M-2 變體 code、full 回滾皆紅。修正後演練 2 passed | eda4d3cb | |
| S-7 | 修正。`replace_program()` 回傳 `removed_without_replacement`（完整清單，寫進 `conversion_log.json`），CLI 印個數。補題 1；突變 ⇒ 紅 | eda4d3cb | |
| O-1～O-9 | O-1 修正：manifest 記備份時**原檔**的 `logical_digest`（schema＋各表全部欄位），完整回滾比它；位元組仍與備份副本比；CORE-SPEC §9b 驗收更正並註明標頭計數欄位（保留原句）。補題 3（含「副本與 manifest 一起換掉 ⇒ 只有邏輯比對紅」）；突變 ⇒ 紅。O-2：CLI 印 manifest SHA256，RUNBOOK 寫明抄到備份目錄以外、偵測不了蓄意竄改。O-3 修正（`"\\/"`、CU:216 換行）。O-4：同 B-2 修正（AUDIT-X-C-batch1 回覆欄）。O-5：RUNBOOK §7 寫明。O-6：補題——每日備份實際寫出的一般份與個資份檔案合回，等於原表（含承攬付款憑據）；工具不呼叫 `merge_general_and_pii` 維持現狀（DR-SOP 手動步驟），不修。O-7 修正（見 S-2）。O-8 不修：`rollback_snapshots`、`exports` 由部署 PowerShell 寫，Python 產品碼不讀；core.paths 的契約是「產品碼讀的位置＋與 V9 原始碼逐一對照」，放進去需要另一種對照來源。O-9 需裁示（與 M-3 守門連動：裁定屬個資 ⇒ 從允許清單移除，守門轉紅，再補 `_F2_FIELDS`） | eda4d3cb；O-6 題 837c0be8 | |
| O-9（裁示後） | 修正（2026-09-26 00:39，使用者表單裁示「當成個資分流」）。`_F2_FIELDS` 加 `協力廠商`（`data_json` 的 `bankAccountName`／`bankAccountNumber`／`bankPassbookImage`），`承攬付款憑據` 另加 `snapshot_json` 最上層同三鍵；一般每日／月 JSON 拿掉，完整列只進個資資料夾（主表與快照都處理；協力廠商 Excel 匯出本來就不含帳戶，週備份只含報價單與客戶）。M-3 守門允許清單清空：先轉紅（4 條未決）再補宣告轉綠；守門改放協力廠商哨兵、掃每日＋週＋月一般樹（與允許清單無關）＋個資份正對照。突變 4 個：全部還原（放回允許清單＋拿掉宣告）、只拿掉宣告、只拿掉憑據最上層宣告 ⇒ 皆被哨兵掃描抓到（紅在 `月備份/…/協力廠商.json`、`承攬付款憑據.json`）；只放回允許清單 ⇒ 紅（清單未出現）。另：S-CU12 `.build_commit` 歸類成程式（`CONFIG_FILES` 移除）：補題打 `/api/build-info`，轉換後回新版、code／full 回滾後回 V9、V9 沒檔 ⇒ 回滾後也沒有；突變放回設定 ⇒ 3 紅。CORE 1.8。MODULE-GUIDE §3.2、DR-SOP §3a | b32956fd | |
