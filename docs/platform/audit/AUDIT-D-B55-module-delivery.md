# 稽核：B55 單一模組更新包上線——設計審（wip/b-module-delivery 2ab3585d，MODULE-UPDATE-DELIVERY.md）（D，2026-09-28）

> 依據：CORE-SPEC「單一模組更新包上線（正式機可用）」（a8ec2b4b）、「出貨前測試依改動範圍分級」、「完整包與客戶加購模組」。
> 只審文件（尚未實作）；查證用 git grep／讀碼，沒有跑任何東西。

## 0. 結論

- **必修 2、建議 6、觀察 2。** 必修都是設計層級、改文件就能關，關了再實作。
- 主持四個重點：

| 重點 | 判定 |
|---|---|
| U-M1（共用函式） | **選 ②**：複製＋逐字比對守門，這一包不動 apply_update（見 DB-S1） |
| U-M2（演練過 $ProdRoot 守門） | **選 ②**：演練複製腳本、改寫常數，正式機的腳本不加任何繞過路徑（見 DB-S2） |
| ship_tier 的寬窄 | 路徑規則的方向正確（其他一切＝③、頁面恰好一個模組、manifest 做 JSON 層比對、覆蓋模組用雜湊扣除）；**太窄的一處是必修 DB-M2**；太寬的一處目前沒有實害（DB-S3） |
| 健檢看「模組 <key> <新版> 已載入」 | 方向對（ping 會把模組沒載入判成成功，這是完整包沒有的一種失敗）；改讀機器可讀的狀態會比 log 字串穩（DB-S4） |
| 「先套一版帶新工具的完整包」 | 成立。工具版本（min_apply_module_script）在簽章範圍內，裝的工具太舊就拒絕 |

## 1. 必修

**DB-M1（必修）　§1.3 步驟 5 的疊加樹用黑名單排除，會把個資與帳密複製到 %TEMP%**
- 設計寫的是：「複製安裝目錄 `backend`（排除 DB、logs、uploads、db_backups、rollback_snapshots、module_backups、certs）」
- 沒列到的、實際在 backend 底下的（core/paths.py）：
  - `export_archive`（勞報單 PDF，個資）
  - `_demo_pdf_archive` 等 7 個 `_demo_*` 存檔
  - `.initial_admin_credentials.txt`、`.initial_demo_credentials.txt`（初始帳密）
  - `heartbeat_config.json`、`license.key`
- 每套一次模組包就複製一份；finally 會刪，但程序被中斷或當機就留在 %TEMP%。H12 為了同一件事，把程式快照改成排除個資（「回滾快照不再複製個資資料夾」）
- 修法：**改白名單**——只複製 `core.upgrade.classify(rel) == "program"` 的檔（與 apply_plan 的 `deletable` 同一支判定），DB 副本另外只放快照複本。補題：疊加樹裡沒有任何 classify≠program 的檔；反向控制：安裝目錄放一個 `export_archive/x.pdf`、一個 `.initial_admin_credentials.txt` ⇒ 疊加樹裡都沒有

**DB-M2（必修）　第②級只測「該模組＋tests/platform＋該模組頁面」，沒有測「用這個模組提供的整合點（IP）的其他模組」**
- 模組之間經 IP 提供者相連（INTEGRATION-POINTS、dep_graph.json）。例：case（M01）提供 `case.access`、`case.locations` 等，netplan、accounting、arap 都在用
- 只改 case、出 case 的單模組包：
  - 正式機上的消費端維持舊版 ⇒ 真實的組合是「case 新＋消費端舊」
  - 而第②級的測試集合裡沒有任何一題跑消費端
  - ⇒ 提供者的回傳形狀或語意一改，消費端壞掉而測試全綠（〈判準的寬窄都會騙人〉的「太窄」）
- 修法（二選一，要寫進 §4 與 §1.1 步驟 3）：
  - 甲（推薦）：第②級加上「消費這個模組所提供 IP 的其他模組的題」，由 dep_graph／INTEGRATION-POINTS 機器取得，不靠人列
  - 乙：模組的 `provides`（IP 提供者）有任何改動 ⇒ 判③（必須完整包）
- 使用者裁示第②級的字面範圍是「該模組題＋tests/platform＋該模組頁面 e2e」。甲會擴大它 ⇒ **由主持用表單問使用者**（推薦甲）
- 補題：改 case 的一個提供者函式 ⇒ 選題清單裡有 netplan 的消費端題

## 2. 建議

**DB-S1（U-M1）選 ②：新腳本複製共用函式，加逐字比對守門**
- apply_update.ps1 在正式機上剛經過兩次事故與多輪演練；抽出 `_apply_common.ps1` 會讓這一包變成第③級，而且 apply_update、rollback_update 都要重演練
- repo 裡已經有同樣的做法可以沿用：apply_update 與 rollback_update 的鎖、結果檔、停服函式「逐字相同」＋守門題
- 等下一次 apply_update 本來就要改時，再一起抽成共用檔

**DB-S2（U-M2）選 ②：演練複製腳本、改寫 $ProdRoot／$Port，正式機的腳本不加繞過**
- ① 會在正式機的腳本裡加一條「三個條件都成立就換根目錄」的分支。身分守門是這支腳本最後一道防線，任何繞過分支都是新的誤觸面，而且它在正式機上永遠不該被走到——也就永遠沒有真實的驗證
- ② 是目前 apply-run 演練既有的做法（drill_apply_copy.py），版本守門（AH-O7）已經考慮過「演練副本改路徑與 port」
- 建議加一題：演練改寫只動 `$ProdRoot`、`$Port` 那兩行（對改寫前後做 diff）
- 演練 B 的 `-SkipDryRun`（只准演練旗標下）也改成只在演練副本裡存在

**DB-S3（ship_tier 太寬，目前沒有實害）　「`*.md` 任何位置＝①」**
- 根目錄的 .md 會隨完整包複製到正式機根目錄；模組資料夾的 README.md 已依「路徑先於副檔名」歸到模組
- 查證：後端沒有任何地方在執行期讀 .md、或把它當內容送出（git grep `open`／`read_text`／`FileResponse` 配 `.md`：0 筆）⇒ 目前安全
- 建議：「文件」的判定改成「完整包不出貨的路徑」（export-ignore＋建包精簡規則），而不是副檔名。日後有人加一個執行期讀取的 .md（說明頁、範本），判定才不會把它當文件放過

**DB-S4　健檢改讀機器可讀的載入狀態，不靠 log 字串**
- log 字串當契約可以用（有守門題），但有三個弱點：
  - server.log 會輪替
  - 「最後一次 Uvicorn running on」這個錨點在 crash-restart 迴圈裡會漂
  - 多行程（spawn）的輸出會交錯
- 建議：啟動完成時寫 `backend/logs/module_states.json`（pid、啟動時間、每個模組的 state／version／reason，由 `registry.module_states()` 產生）；健檢讀它，而且要求啟動時間晚於「重啟」那一刻
- 字串守門題可以保留，當第二道

**DB-S5（U-M3）　模組回滾失敗（F13）：不要直接重啟，先把該模組停用再重啟**
- 「loader 會隔離壞模組」只在 import 失敗時成立。雜湊不符＝半新半舊的檔，很可能 import 得起來，而行為是混的
- 而重啟（步驟 8）時，新版模組的 migration 可能已經對正式庫跑過
- 建議第三個選項：把該模組寫進停用清單（module_switches，與模組管理頁同一個機制）⇒ 重啟 ⇒ 其他模組與 L1 照常、這個模組明說缺席；status 維持 `module_restore_failed`，畫面請人處理

**DB-S6　module_update apply 要鏡像模組資料夾，並更新 baseline 的那一段**
- 現行 apply 是「換模組資料夾與頁面」，要寫清楚是鏡像（包裡沒有的檔要刪），否則舊版有、新版刪掉的檔會留著被載入。H12 就是為了同一件事才做了刪除計畫
- `backend/.deployed_files.json`（完整包的 baseline）不包含模組包新增的檔 ⇒ 下一個完整包的刪除計畫看不到它們。建議模組包套用時，同步更新 baseline 裡 `backend/modules/<key>/` 那一段與宣告頁面（回滾時還原）
- 補題：模組包 v2 刪掉 v1 的一個檔 ⇒ 套用後那個檔不在；之後套一個完整包，刪除計畫對得上

## 3. 觀察

- **DB-O1**：`.deployed_modules.json` 的分類是 program，會進程式快照、也會被 cleanup-snapshot 處理。推演下來行為是對的：完整包回滾到較舊快照 ⇒ 模組覆蓋紀錄跟著消失，而模組資料夾也回到那個快照。但它是狀態檔，建議明確列進 STATE_FILES，並寫一段「兩種回滾各自怎麼處理它」，不要靠推演
- **DB-O2**：U-M4 選 ①、U-M5 選 ①、U-M6 選 ① 都同意。U-M5 的文字插入照〈共用 JSON 用文字插入〉的做法，回滾時要移除同一段，而且要有題

## 4. 複審第二、三版：wip/b-module-delivery 79489c98（0d5636cc＋DB-M2 改甲）（D，2026-09-28）

**結論：必修 1（新）、其餘成立。**

| 項目 | 判定 |
|---|---|
| DB-M1 | 成立：改白名單（已安裝的 `classify=="program"`），DB 只放快照副本；另排除 `.apply.lock`；殘留目錄在下一次開頭清（只清前綴、而且沒有鎖時）；有反向控制題與突變。✅ 關閉行見本節末 |
| DB-M2 | 使用者裁示甲；設定點單一（`PROVIDER_CHANGE_POLICY="consumers"`）、判定不了就退回乙、與 dep_graph 交叉比對 ⇒ 方向成立。**但消費端與能力清單的取法太窄，見 DB2-M1**；關閉要等 DB2-M1 |
| U-M1②、U-M2②、DB-S3～S6、DB-O1、U-M4～M6 | 成立 |

**B 指出的三處前提（逐一確認）**：
1. `drill_apply_copy.py` 不在 origin：**B 說得對**。它在 `D:\MOTRIX-DRILLS\apply-run-0928\tools\`（演練目錄、不進 repo），D 寫成「既有做法」，但沒說它不在 repo。設計改成新寫一支、放進 repo 的 `tools/platform/drill_module_apply.py`，比較好
2. classify 白名單會帶進 `.apply.lock` 等非個資狀態檔：**B 說得對**。已另排除 `.apply.lock`，其餘不含個資，可以接受
3. 「STATE_FILES 實為 CONFIG_FILES」：**兩個都存在**。`apply_plan.STATE_FILES`（`.deployed_files.json`、`.apply.lock`）是 D 原本的意思；B 改用 `core.upgrade.CONFIG_FILES`（與 `.deployed_commit.json` 同類）。後果：完整包刪除計畫與 cleanup-snapshot 不碰它、程式快照照樣含它、V9 完整回滾時照設定檔還原——推演一致，**接受 B 的選擇**。它是 L1 改動，已經列進第③級

**DB2-M1（必修）　§4.3 找消費端的判準太窄：漏了 `single_provider`，也漏了 import 時登記的提供者**
- 取用端：設計只寫 `registry.providers("<cap>")`／`registry.provider("<cap>")`
  - 但 `core.registry` 沒有 `provider` 這個函式
  - 實際上最常用的是 **`registry.single_provider(...)`**：origin/platform 的模組、helpers、routers 裡，single_provider 的呼叫比 providers 還多
  - ⇒ 照設計實作，大部分消費端不會被找到，而且是「找不到」而不是「判不了」⇒ 不會退回乙，是靜默放行（〈判準的寬窄都會騙人〉的太窄）
- 提供端：「提供者有改」與能力清單只讀 `ModuleSpec.providers`
  - 但 arap 另外在 import 時以 `_registry.provide(...)` 登記了 `calendar.writeback`（invoice_vouchers.py:870、payment_requests.py:908）與 `attachments.for_document`（invoice_vouchers.py:958）
  - ⇒ 改到這些函式時，能力清單裡沒有它們 ⇒ 消費端（例：case 的附件彙整、行事曆寫回）不會被選到
- 修法：
  - 能力清單＝`ModuleSpec.providers` 的 key ∪ 模組檔案裡以字串常數呼叫 `registry.provide(cap, …)` 的 cap
  - 取用端＝`registry.providers`／`registry.single_provider`，以及 `core.registry` 裡日後新增的任何「以 capability 取提供者」的函式——**由 registry 的公開介面清單產生**，不在 ship_tier 裡手抄
  - 要處理別名（`_registry.`、`from core.registry import single_provider`）與模組層字串常數（例：helpers/case_access.py:86 的 `_registry.providers(CASE_PRESENT)`）。仍解析不了 ⇒ 退回乙（原設計）
- 補題：
  - 正對照（真實 repo）：改 arap 的 `_InvoiceVoucherAttach…` ⇒ 選題含 `attachments.for_document` 的消費端；改 case 的 `case.access` 提供者 ⇒ 選題含 netplan、accounting 的消費端
  - 突變：把 single_provider 從取用端清單拿掉 ⇒ 正對照紅

### 關閉紀錄（標準格式，PLAYBOOK §E-6）

- ✅ DB-M1 關閉（79489c98）——疊加樹改白名單（已安裝的 classify==program），DB 只放快照副本，另排除 .apply.lock

## 5. 複審 DB2-M1：wip/b-module-delivery 269adafe（只改 §4.3）（D，2026-09-28）

- 修正：
  - 能力清單＝`ModuleSpec.providers` 的 key ∪ 模組層 `registry.provide(cap…)` 的 cap
  - 取用函式由 `core/registry.py` 的公開介面產生（第一個參數名是 capability，扣掉 provide），並有守門
  - AST 解析別名與跨檔字串常數；任何一處判不了 ⇒ 整體退回乙
  - 消費端檔案當成虛擬改動交給 `modtest.select`，連間接依賴一起選
  - 與 dep_graph 不一致 ⇒ 退回乙
  - 正對照 3 組、突變 4 個
  - ⇒ **成立**
- **B 對 D 的更正，查證後**：
  - `attachments.for_document` 的消費端是 accounting（voucher_attachments.py:103），case 是同一能力的另一個提供者（case/__init__.py:57）⇒ **B 對，D 原文錯**（設計已改，原文保留）
  - `case.access`：L1 `helpers/case_access.py:81/86`（CASE_PRESENT）是直接消費端。**但 netplan 也是直接消費端**（`modules/netplan/api.py:43`：`_registry.single_provider("case.access")`；netplan 並沒有 import case_access）；accounting 則是經 case_access 間接用到（voucher_attachments.py:46 import `case_page_readable`）⇒ B 的「netplan、accounting 都是經由 case_access 間接」只對了 accounting 那一半
- **DB3-S1（建議，實作時改題目即可）**：突變「拿掉虛擬改動、只留直接消費端 ⇒ netplan 正對照紅」**不會紅**，因為 netplan 是直接消費端，AST 本來就找得到。間接那一條的見證要改用 **accounting**（改 `case.access` 提供者 ⇒ 選題含 accounting 的題，只有經 modtest 的間接選題才會選到）；§4.3 那一句「netplan、accounting 都 import case_access」照實更正
- **DB3-S2（建議）**：能力清單只收**模組層**的 provide 呼叫。函式內的 provide（目前 0 筆，grep 查證）日後若出現，應該算**判不了 ⇒ 退回乙**，而不是略過——與「任一處判不了就退回乙」同一條原則

### 關閉紀錄（標準格式，PLAYBOOK §E-6）

- ✅ DB2-M1 關閉（269adafe）——能力清單含 import 時登記、取用函式由 registry 介面產生、判不了整體退回乙、間接消費端經 modtest 選題
- ✅ DB-M2 關閉（269adafe）——使用者裁示甲落地為單一設定點，消費端取法經 DB2-M1 修正
