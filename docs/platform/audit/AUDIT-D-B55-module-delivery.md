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

## 6. 分段稽核 S1：ship_tier（wip/b-module-delivery-2 4ae837fd）（D，2026-09-28）

**結論：必修 0、建議 2。** 題 47 過（拋棄式樹）；B 回報 tests/platform 1635 過、突變 8/8 紅。

- **偏離 (a)　文件級＝export-ignore ∪ docs/**，加上守門「執行期不讀 docs/」**：成立
  - 查證：backend 非測試碼裡出現 `docs/platform` 的只有註解（core/menu.py:78、helpers/privacy_notice.py:15），沒有任何讀檔
  - `test_docs_are_never_read_at_runtime` 附正對照（`test_docs_path_scanner_positive_control`）
  - docs/platform 雖然隨完整包出貨，但對執行沒有影響，所以判①合理
- **偏離 (b)　交叉比對改成「AST 能力清單 ⊇ 執行期 registry 實際登記」**（`test_real_ast_capabilities_match_runtime_registry`）：**方向對，但只守得到能力那一側**
  - 主持的問題：消費端漏抓時，會不會仍然靜默放行？**會，只要取用不經 registry 的取用函式**
  - 現況（grep 查證）：
    - 不經取用函式的只有 `core/catalog.py:192`（`registry._LEGACY_PROVIDERS`）與 `:196`（`m.spec.providers`）。它把所有提供者列成目錄、不呼叫、也不依任何能力的行為 ⇒ **今天沒有真的漏抓**
    - 沒有 `from core.registry import *`
  - `consumers()` 只在「取用函式被直接呼叫、或以名稱引用」時才看得到。下列三種會是**找不到**，而不是判不了：
    - 讀 registry 內部（`_LEGACY_PROVIDERS`、`spec.providers`、`registry.loaded()` 再取 providers）
    - 星號 import（names 表裡沒有這些名稱）
    - 經 L1 包裝函式（這一種由 modtest 虛擬改動的間接選題補上）
- **DB4-S1（建議）　消費端也要有一道「全部有交代」的守門**：
  - ① 核心之外讀 `_LEGACY_PROVIDERS`／`.spec.providers`（以及 `registry.loaded()` 之後取 providers）⇒ 白名單（目前只有 core/catalog.py，理由：只列目錄）；新增的位置 ⇒ 守門紅
  - ② `from core.registry import *` ⇒ `consumers()` 當成判不了
  - ③ 每一個能力字串常數在後端非測試碼裡的每一次出現，都必須落在「提供者模組」「已解析的消費端檔」「白名單（registry、catalog、INTEGRATION 註解）」其中之一，否則判不了、退回乙。能力字串是唯一的鍵，這一道抓得到「用了意料之外的管道」
  - 附反向控制：合成一個以 `registry._LEGACY_PROVIDERS[("case.access","case")]` 取用的檔 ⇒ 判不了
- **DB4-S2（建議）　交叉比對寫明它只守能力清單**：文件把 (b) 寫成「與 dep_graph 交叉比對」的替代，但它只驗能力那一側。§4.3 補一句它不涵蓋消費端，由 DB4-S1 負責

## 7. 分段稽核 S2：wip/b-module-delivery-2 0b646a01（D，2026-09-28）

**結論：必修 0、建議 2。** ship_tier＋module_states 題 68 過（拋棄式樹，不用 xdist）；B 回報 S2 選題 1820 過、突變 S2 4、DB4 7、S1 8 全紅。

- **DB4-S1**：成立
  - ① `registry_bypasses`：讀 `core.registry` 的底線名稱（含別名）、import 內部名稱 ⇒ 判不了；白名單只有 core/catalog.py，附理由
  - ② 星號 import core 的模組 ⇒ 判不了
  - ③ `stray_capability_strings`：能力字串（含跨檔常數）只要出現在「已解析的取用引數、提供者登記位置、白名單（approval.reassign 稽核動作同名）」以外的地方 ⇒ 判不了
  - ③ 是真正的兜底：①沒列到的寫法（`getattr(registry, "providers")("case.access")`、`for m in registry.loaded(): m.spec.providers[("case.access", …)]`）只要帶著能力字串，③都會抓到；不帶特定能力字串的通用讀法（像 catalog 列目錄）本來就不依任何能力的行為
- **DB4-S2**：§4.3 已寫明 runtime 比對只守能力那一側。成立
- **DB-S4（module_states.json）**：寫法成立：先寫 .tmp 再改名、寫失敗只記 WARNING、pid＝服務行程本身、在 fail_incomplete_modules 與 start_schedulers 之後。loader 的兩行 log 字串列為契約
- **DB-O1**：`.deployed_modules.json` 加進 CONFIG_FILES。成立

**DB5-S1（建議）　module_states.json 的寫入不要綁在排程閘門**
- 現在只在 `MOTRIX_DISABLE_SCHEDULERS` 沒設時才寫（理由：測試 session 不寫進 repo 的 logs/）
- 但它與「排程」無關：任何以 DISABLE_SCHEDULERS 起的安裝（演練、日後若有客戶為了除錯關排程），單模組更新的健檢都會讀不到這個檔 ⇒ 每次都判失敗、自動回滾。方向是保守的，但成因會很難查（畫面只會說「模組沒有載入」）
- 第十六班的事故就是演練設了 DISABLE_SCHEDULERS 而沒照到真實路徑
- 建議：改用獨立的條件（例：不在 pytest 之下，或 `LOGS_DIR` 不在 repo 工作樹內）；或者健檢讀不到檔時，訊息明說「狀態檔不存在（排程閘門關閉？）」

**DB5-S2（建議）　③ 的完全相等比對擋不到拼出來的字串**
- `"case." + "access"`、f-string 這類會漏過③；而①②只看 registry 名稱，也看不到
- repo 目前沒有這種寫法。可以在取用函式的引數不是常數時已經判不了的基礎上，再加一題：能力字串的組成片段（第一個 `.` 之前的前綴，例如 `case.`）出現在 BinOp／JoinedStr 裡 ⇒ 判不了。成本低，可以留到下一輪

## 8. 分段稽核 S3：wip/b-module-delivery-2 87a472b1（D，2026-09-28）

> 範圍：0b646a01..87a472b1（單一 commit）。拋棄式 worktree；探針題不提交、跑完即刪；暫存已清。

### 8.0 結論

- **必修 2、建議 2、觀察 2。**
- 相關題 39 過（delivery、states_file、module_update）。D 補做突變 4 個全紅：基準 commit 不比、同一版不拒絕、「本來沒有」的狀態檔回滾時不刪、狀態檔改回綁排程閘門
- 主持指定的「套用中途失敗」**不涵蓋**，見 S3-M1；另外，逐位元組還原在「之後有別人寫過這些檔」時會蓋掉別人的內容，見 S3-M2

### 8.1 必修

**S3-M1（必修）　套用中途失敗之後，回滾找不到這次的備份，或者回滾到更舊的版本**

〔更正（格式）：原標題寫成「S3-M1　套用中途失敗之後，回滾找不到這次的備份，或者回滾到更舊的版本」，缺「（必修）」標記 ⇒ 必修掃描器不認；分級與內容不變〕

- `apply()` 先刪掉整個模組資料夾（:483），再複製新版（:487）、寫 lock、寫三個狀態檔；**`apply.json` 在最後才寫**（:500）
- `backups()` 只認有 `apply.json` 的備份 ⇒ 中途失敗的這一次，備份資料夾雖然在，回滾卻看不到
- 探針（在 `shutil.copytree` 模擬磁碟滿）：
  - P1　第一次套用失敗：模組資料夾**已刪**，`backups()`＝[]，`rollback` 拒絕（「沒有任何套用備份」）⇒ 安裝目錄停在「模組不見了」，而且沒有工具救得回來
  - P2　v1→v2 套用成功之後，v2→v3 套用中途失敗：`rollback` 用的是**上一次（v1→v2）的備份** ⇒ 模組回到 **1.0.0**（不是失敗前的 1.1.0），三個狀態檔回到 v2 之前。回報成功、雜湊檢查通過（它比對的是那份備份自己的 files_before）＝〈降級之後它還是會動〉
- ps1（S4）一定會在「套用失敗」時呼叫 rollback，所以 P2 在正式機上會發生，而且不會有人發現
- 修法（擇一或兩者都做）：
  - 在動任何檔**之前**先寫 `apply.json`（`status: "in_progress"`、`files_before`、`pages_after`＝包裡 lock 的頁面），全部完成後改成 `complete`；回滾認得 in_progress 的備份，移除的對象以 `files_after`（沒有就用「模組資料夾＋pages_after」）為準
  - `apply()` 自己包 try/except：任一步失敗 ⇒ 立刻用這次的 bdir 還原（檔案＋lock_before＋state_before），再把原本的例外往外丟
- 題目：P1、P2 兩種情境各一題（失敗後安裝目錄逐位元組等於套用前）

**S3-M2（必修）　逐位元組還原會蓋掉「之後」別人寫入的共用檔**

〔更正（格式）：原標題寫成「S3-M2　逐位元組還原會蓋掉「之後」別人寫入的共用檔」，缺「（必修）」標記 ⇒ 必修掃描器不認；分級與內容不變〕

- 回滾整檔還原 `modules.lock.json`（lock_before）與三個狀態檔（state_before）。這些檔**不是這個模組專用的**：完整包，以及**其他模組**的單模組套用，也會寫它們
- 探針 P3：套用 zz 之後，模擬裝了完整包 Q（`.deployed_commit.json`、baseline、lock 都改寫）⇒ `rollback zz` **照做**：baseline 回到舊 commit 的內容，而 `.deployed_commit.json` 仍是 Q；lock 整份回到完整包之前 ⇒ 下一次完整包的刪除計畫用錯基準、lock 跟實際安裝的檔對不上
- 同一類（讀碼推得，沒有另外做探針）：套用 A → 套用 B → 回滾 A ⇒ B 的 lock 條目、baseline 片段、覆蓋紀錄、manifest 條目全被還原成「B 之前」，而 B 的檔還在
- 修法：套用完成時記下 lock 與三個狀態檔的雜湊（寫進 apply.json）；回滾前比對「現在的雜湊＝當時記的」，**不相等就拒絕整檔還原**，並說明原因（之後有完整包或其他模組套用過；請改用完整包，或先回滾較新的那一次）。另外 `deployed_commit(root) != rec.prod_base_commit` 時直接拒絕
- 題目：P3（完整包之後回滾 ⇒ 拒絕、安裝目錄不動）、A→B→回滾 A ⇒ 拒絕

### 8.2 建議

- **S3-S1　中途失敗留下的備份資料夾不會被清掉**：`_prune_backups` 只數有 `apply.json` 的備份。S3-M1 修完（先寫 in_progress）之後就會被納入，這一條自然消失；如果選 try/except 的修法，要記得把失敗那一份也納入清理
- **S3-S2　`list --json`**：主持裁示「正式機可見性靠 ::RESULT::／result.json＋list --json」，但 `list` 目前**沒有 `--json`**（:601），只有純文字輸出。S4 之前補上（每個模組的版本、覆蓋紀錄是否仍有效、備份清單與狀態）

### 8.3 觀察

- **S3-O1**：偏離 U-M4（不搬到 backend/tools）：理由成立。讀碼確認根目錄 `tools/` 隨完整包出貨（`product_select.REQUIRED_PKG_FILES` 要求 `tools/platform/upgrade.py`），正式機本來就有這一份。設計表已用〔更正〕保留原句
- **S3-O2**：DB5-S1 關閉條件成立：狀態檔改在 `mount_modules()` 之後、只在 pytest 之下不寫，並多記 `schedulers_disabled`（突變 S4 紅）。會 `import main` 的非測試程式有 `tools/platform/startup_writes.py`（在拋棄式複本裡跑，不影響安裝目錄）與建包腳本（開發機），都不會寫到正式機的狀態檔
- ✅ DB5-S1 關閉（87a472b1）

## 9. 複核 S3-M1／S3-M2：wip/b-module-delivery-2 18e66f7b（D，2026-09-28）

> 拋棄式 worktree 跑探針 8 題（不提交，跑完刪、暫存已清）。

- ✅ S3-M1 關閉（18e66f7b）
- ✅ S3-M2 關閉（18e66f7b）
- **新必修 1（S3R-M1）。**

| 探針 | 情境 | 結果 |
|---|---|---|
| P1 | 第一次套用在 copytree 失敗 | `apply_failed_restored`，安裝目錄逐位元組等於套用前，失敗的備份已刪 |
| P2 | v2 之後 v3 中途失敗 | 停在 v2（逐位元組），不再退到 v1 |
| P3 | 套用後裝了完整包（lock／baseline／commit 都變） | `state_changed` 拒絕，一個檔都不動 |
| P3b | 完整包只換了 deployed_commit | `base_changed` 拒絕 |
| P4 | 套 A→套 B→回滾 A | `state_changed` 拒絕；先回滾 B 再回滾 A 可以 |
| P5 | 行程在套用中途被砍（KeyboardInterrupt，不被 `except Exception` 接住） | 留下 in_progress；rollback 回到套用前（逐位元組） |
| P6 | 被砍 → 回滾 → 重新套用 | 回滾過的那份不再列出 |
| **P7** | 被砍（in_progress）→ **沒回滾就重新套用成功** → 套 B → `rollback --backup <舊 in_progress>` | **照做**：lock 回到最初（yy 條目不見），而 yy 的檔還在 |

**S3R-M1（必修）　舊的 in_progress 備份會繞過 S3-M2 的檢查**

- `rollback` 對 `status == "in_progress"` 的紀錄完全不比對現值（:640 起；因為它沒有 `state_after`），而且 `backups()` 會一直列出它
- 只要中斷之後有人沒回滾就重新套用（preflight 不擋：模組資料夾不在、lock 還是舊條目 ⇒ 雜湊不同、版號較高），這份 in_progress 就一直留著；之後指定它回滾，就是 S3-M2 原本要擋的整檔覆蓋（P7：lock 被還原成最初，yy 的條目消失而檔案還在）
- 修法（擇一，建議兩個都做）：
  - preflight：這個模組有 in_progress 備份 ⇒ 拒絕套用（新 code，例如 `interrupted_apply_pending`），訊息寫「先 rollback 那一次」
  - rollback：in_progress 只有在它是這個模組**最新的**一份備份、而且 `deployed_commit == prod_base_commit` 時才准
- 題：P7 情境 ⇒ 重新套用被拒，或指定舊 in_progress 回滾被拒；兩者都要做到安裝目錄一個檔都不動

**建議**
- **S3R-S1**：`rolled_back` 的備份不在 `backups()` 裡，而 `_prune_backups` 只清 `backups()` 列出的 ⇒ 回滾過的備份資料夾永遠不會被清。清理時一併算進去（保留最近 N 份，不分狀態）

## 10. 稽核 S4＋複核 S3R-M1：wip/b-module-delivery-2 2d842201（D，2026-09-28）

> 拋棄式 worktree 跑探針（不提交，跑完刪、暫存已清）。

### 10.1 S3R-M1：**未關**（同一模組已擋，跨模組仍在）

| 探針 | 情境 | 結果 |
|---|---|---|
| P5b | 套用中途 Ctrl+C | `apply_failed_restored`，逐位元組回到套用前 ✔ |
| P7 | zz 中斷（`apply_failed_half`，留 in_progress）→ 再套 zz | `interrupted_apply_pending` ✔ |
| **P8** | zz 中斷 → **套 yy（另一個模組）成功** → `rollback zz` | **照做**：lock 的 yy 條目、`.deployed_modules.json` 的 yy 都不見，而 yy 的檔還在 |

- 原因：`pending_interrupted`、`interrupted_not_latest` 都只看**同一個模組**的備份。但 lock 與三個狀態檔是**全安裝共用**的，in_progress 的回滾是整檔還原（`lock_before.json`、`state_before/`），也沒有 `state_after` 可以比對
- 這就是 §9 S3R-M1 原文的情境（「沒回滾就重新套用成功 → **套 B** → 回滾舊的 in_progress」），修正只擋了「重新套用同一個模組」這一步
- 修法（擇一，建議第一個）：
  - preflight：**任何**模組有 in_progress ⇒ 拒絕套用任何模組（`interrupted_apply_pending` 帶模組與備份名）；完整包的 apply 也要先檢查（或至少在 ::RESULT:: 報出來）
  - rollback：in_progress 的回滾要求「全安裝所有模組的備份裡，沒有比它新的」
- 題：P8 ⇒ 套 yy 被拒（或 rollback zz 被拒），安裝目錄一個檔都不動

### 10.2 S4：kind 與分派

**主持問的兩點：成立。**
- **kind 在簽章範圍內**：`kind` 寫在 `delivery.json`，而 `signed_bytes` 涵蓋 `delivery.json`＋`package.sha256` ⇒ 改 kind ＝簽章不符。缺 kind ⇒ full（本欄位之前的包）；不認得 ⇒ 拒絕
- **完整包的驗證端不會把模組包當完整包套**：
  - 新版 `verify_staged`：kind＝module 走 `_verify_module`（簽章或雜湊不過就不跑 preflight），**不會**進完整包的腳本版本／verify_package 分支；`apply_staged` 依 verified 的 kind 選已安裝的 `apply_module_update.ps1`，不複製任何工具
  - 正式機上**舊版** `delivery.py`（還不認得 kind）收到模組包：`script_version` 找不到 `apply_update.ps1` ⇒ 列為問題；`apply_staged` 要求包裡有 `backend\tools` ⇒ 丟例外。兩道都會擋下
- preflight 用**已安裝**的 `module_update.py`，只讀包裡的 JSON 與雜湊，不 import 包裡的程式

**建議**
- **S4-S1　套用工具版本不要用字串比較**：`_verify_module` 用 `str(have) < str(need)`。現行版本格式 `2026-09-28g` 在字尾是單一字母時可以，到 `…z` 之後（`aa`）就會比錯。訂格式（正規式）＋比較函式，完整包那一側若有同樣的比較一併換
- **S4-S2　lock 的頁面路徑要驗形狀**：`apply` 對 `lock["pages"]` 的每個 rel 直接 `root / rel` 寫入，`check` 只驗雜湊。lock 在簽章範圍內，所以不是外部攻擊面；但單模組包的承諾是「只動該模組與它宣告的頁面」，建議 preflight 驗每個 rel 符合 `^frontend/pages/[a-z0-9-]+\.html$` 且 resolve 後在 `frontend/pages` 底下（rollback 刪除 `files_after` 的頁面時同一套）
- **S4-O1（觀察）**：正式機升到新 delivery.py 之前，儀表板的包清單會把模組包列成一般的包（product＝`mod-…`）；按下去會被上述兩道擋下，訊息是「包裡沒有 apply_update.ps1」。建議正式機 Claude 指示裡提一句
