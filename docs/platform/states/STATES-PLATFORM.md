# 模組平台可能遇到的狀態（STATES-PLATFORM）

> 視窗 A｜2026-09-25｜基準：分支 `wip/a-platform-states`（＝9c 分支 `6bd94e6d`，§9c 授權與啟停已在內）
> 範圍：模組平台（載入、授權與啟停、串接、跨模組資料、前端入口）。資料／升級／部署／備份由 C 負責，不重疊。
> 每一列的「目前實際行為」都有證據：**實測**（附重現方式）或 **檔:行**。行號以本分支為準。

## 0. 結論（先看這裡）

- 共 33 列。嚴重度「高」5 列，其中 **守門「缺」的有 2 列**，擬在本分支補處理與測試（等主持看過再動）：
  - **P-LD-07 路由衝突**：兩個模組（或模組與 L1）宣告同一條路由，兩條都掛上、先掛的默默勝出。模組掛在一部分 L1 router 之前 ⇒ **模組可以默默蓋掉 L1 或其他模組的端點**。
  - **P-SW-05 啟動時讀不到停用清單**：主庫被別的行程鎖住時，等約 7.5 秒後當成「沒有停用任何模組」⇒ **管理者停用的模組被默默重新載入**，只留一行 WARNING。
- 其餘 3 列「高」已有守門或屬已知結構限制（P-DT-03 移除尚未搬遷的模組會讓伺服器起不來——要等 ROADMAP 階段 B 搬遷）。
- 「中」「低」各列排進 ROADMAP 新增的階段 S（見 §7）。
- 「直接打網址進入停用模組的頁面」目前是：頁面照常載入、API 回 404、部分區塊靜默空白。**建議應有行為＝提示頁**（「此模組目前未啟用／未授權／不在安裝包」＋原因），不是 404：頁面是靜態檔，404 會讓人以為網址打錯。

嚴重度判準：**高**＝錯誤結果安靜發生（使用者或管理者看不出來）且影響權限、資料或管理者的決定；**中**＝看得出來但體驗差、或需要多一步才發現；**低**＝邊界情況或只影響顯示。

---

## 1. 載入（L0 `core/loader.py`）

| # | 狀態 | 怎麼觸發 | 目前實際行為 | 應有行為 | 使用者看得到什麼 | 怎麼復原 | 守門 | 嚴重度 |
|---|---|---|---|---|---|---|---|---|
| P-LD-01 | module.json 不是合法 JSON | 手改壞、合併衝突殘留 | **實測**（重現腳本 R1）：state=failed，reason＝`Expecting property name enclosed in double quotes: line 1 column 2`；其他模組照常載入（`core/loader.py:96` 單一模組例外不拖垮整台） | 同左；reason 應是中文「module.json 格式錯誤（第 1 行第 2 字）」 | 模組管理頁該列「載入失敗」＋英文原因 | 修正 module.json 後重啟 | `test_core_loader.py::test_broken_module_is_isolated_and_reported` | 低 |
| P-LD-02 | module.json 缺 `core` 範圍 | 新模組忘了寫 | **實測** R1：failed，`core range: empty core range` | 同左（算不出相容性就不載入，不猜） | 同上 | 補 `core` 後重啟 | `test_core_loader.py::test_unparsable_core_range_raises_not_guesses` | 低 |
| P-LD-03 | core 範圍不相容 | 底層升主版號、模組還沒跟上 | **實測** R1：failed，`requires core >=2.0,<3.0, have 1.2` | 同左 | 同上 | 模組升版或底層回退 | `test_core_loader.py::test_core_range` | 中（主版號一升，所有沒跟上的模組同時消失） |
| P-LD-04 | core 範圍寫法看不懂（`~1.0`） | 抄別的生態系寫法 | **實測** R1：failed，`unparsable core range: '~1.0'` | 同左 | 同上 | 改成 `>=x,<y` | `test_core_loader.py::test_unparsable_core_range_raises_not_guesses` | 低 |
| P-LD-05 | module.json 的 key 與資料夾名不同 | 複製資料夾改名忘了改 key | **實測** R1：failed，`module.json key 'other' != folder 'm_keymismatch'` | 同左 | 同上 | 對齊名稱 | `dep_scan --check-modules`（`check_module_folders`）＋ R1 | 低 |
| P-LD-06 | `__init__.py` 匯入失敗（缺套件、語法錯、import 已移除的模組） | 相依套件沒裝、引用別組私有函式而對方不在 | **實測** R1：failed，`No module named 'no_such_package_zz'`；未載入 ⇒ 路由不掛、排程不跑（`main.py:587`、`:678` 只迭代 `registry.loaded()`） | 同左 | 同上 | 補套件／改走 provider | `test_core_loader.py::test_broken_module_is_isolated_and_reported` | 中 |
| **P-LD-07** | **兩個模組（或模組與 L1）宣告同一條路由** | 複製貼上、前綴撞名（例：模組也開 `/api/vouchers/...`） | **實測** R1：兩個模組都 loaded，`/api/dup/x` 掛了 2 條，**先掛的回應**，沒有任何錯誤或警告。模組的掛載點在 `main.py:678`，**在 map_points／account_items／bonus／vouchers／item_reads／modules 這些 L1／舊 router 之前** ⇒ 模組可以蓋掉它們 | 載入時偵測：與已掛的路由（L1＋先載入的模組）撞到 ⇒ 該模組 **不載入**，state=failed，reason 列出撞到的路徑與對方 | 看不出來：打到的是另一個模組的端點 | 改名後重啟 | ~~**缺**（`check_module_folders` 只比 module.json 與 modules.json，不比模組之間／模組與 L1）~~ ⇒ ✅ §9.4 | **高** |
| P-LD-08 | 有程式、沒有 module.json 的資料夾 | 搬遷做一半、漏放 module.json | **實測** R1：**完全不出現**在狀態表（`core/loader.py:68` 直接 `continue`），沒有 log | 列為 failed「缺 module.json」，讓管理頁看得到 | 看不到（模組像是不存在） | 補 module.json | 缺 | 中 |
| P-LD-09 | 有 module.json、沒有 `__init__.py`／沒有 `MODULE` | 資料夾不完整 | **實測** R1：failed，`MODULE missing or key mismatch`（namespace package 可以 import，但沒有 spec） | 同左；reason 分開寫「缺 __init__.py」「缺 MODULE」 | 同 P-LD-01 | 補檔 | `test_core_loader.py::test_broken_module_is_isolated_and_reported`（部分） | 低 |
| P-LD-10 | 有 `api.py` 但 spec 沒列它的 router（或反過來） | 新增端點忘了登記 | 讀程式：路由只從 `spec.routers` 掛（`main.py:678`）⇒ api.py 的端點**不存在**、頁面 404 | 同左（明確登記）＋守門 | 功能 404 | 補登記 | `test_core_loader.py::test_every_module_api_router_is_declared_in_its_spec` | 低 |
| P-LD-11 | 兩個資料夾宣告同一個 key | — | 讀程式：key 必須等於資料夾名（`core/loader.py:74`），同一目錄不可能有兩個同名資料夾（Windows 大小寫不分也擋掉） | 同左 | — | — | 結構上不可能＋ `dep_scan --check-modules` | 低 |
| P-LD-12 | 模組 migration 失敗 | 模組的新表建立失敗 | 讀程式：**機制尚未實作**——只有版本表 `module_schema_versions`（`db.py:856`），沒有執行器；目前唯一的模組 tender_radar 沒有自有 migration（module.json `tables_note`） | 失敗 ⇒ 該模組不載入、state=failed＋原因、交易回滾不留半套表、其他模組不受影響 | — | — | 缺（機制未實作） | 中（第一個有自有表的模組搬進來前必須補） |
| P-LD-13 | 載入失敗原因是英文例外字串 | P-LD-01～06 任一 | **實測** R1：reason 原樣是 Python 例外訊息 | 中文原因＋技術細節分開 | 管理頁看到英文 | — | 缺 | 低 |

## 2. 授權與啟停（§9c）

| # | 狀態 | 怎麼觸發 | 目前實際行為 | 應有行為 | 使用者看得到什麼 | 怎麼復原 | 守門 | 嚴重度 |
|---|---|---|---|---|---|---|---|---|
| P-SW-01 | 授權開關關閉（開發模式） | `LICENSE_GATE_ENABLED=False`（`helpers/licensing.py:94`） | 讀程式：模組授權完全不查，連 `verify_license` 都不呼叫（`helpers/licensing.py` `module_license_check`） | 同左（照既有規則） | 無 | — | `test_module_selection.py::test_gate_off_never_reads_the_key` | 低 |
| P-SW-02 | 金鑰沒包含某模組 | 發證時漏列 license_key | 讀程式＋子行程實測：state=unlicensed，reason「未授權：授權金鑰未包含此模組（key）」，不 import | 同左 | 管理頁「未授權」＋原因；選單入口消失；端點 404 | 重發金鑰後重啟 | `test_module_selection.py::test_after_restart_the_module_is_gone_and_data_stays[unlicensed]` | 低 |
| P-SW-03 | **執行中**授權過期／金鑰被換掉 | 跨過到期日、換新金鑰檔 | 讀程式：整體守門每個 request 重讀（`main.py:333-334`）⇒ 年費過期＝**所有**業務 API 402；**模組層級只在啟動時判斷**（`main.py:40`）⇒ 新金鑰少了某模組，該模組照跑到下次重啟，管理頁仍顯示「啟用」 | 模組層級的變化也要看得到：管理頁標「授權已變更，重啟後生效」 | 看不出來（直到重啟） | 重啟 | ~~缺~~ ⇒ ✅ §9.4 | 中 |
| P-SW-04 | modules_disabled 裡有不存在的 key | 模組移除後設定殘留、手改 | **實測** R2：原樣保留 `['ghost_module','tender_radar']`；載入器忽略未知 key；管理頁只列存在的模組（`routers/system.py:714`）⇒ 殘留看不到 | 管理頁列出「設定中有、但安裝包沒有」的 key，可清除 | 看不到 | 手動清設定 | 缺 | 低 |
| **P-SW-05** | **啟動時讀不到停用清單** | 主庫被別的行程持有排他鎖（備份、另一個 uvicorn、手動工具） | **實測** R2：`database is locked`，等約 **7.5 秒**後回空集合（`helpers/module_switches.py:45`）⇒ **管理者停用的模組被重新載入**；只記一行 WARNING | 不可以默默反轉管理者的決定：重試（有上限）；仍讀不到 ⇒ 啟動記 ERROR、管理頁標「停用清單讀取失敗，本次啟動沿用…」，並在 runtime-switches 類的狀態端點露出 | 看不出來（模組又出現了） | 重啟一次 | ~~**缺**~~ ⇒ ✅ §9.4 | **高** |
| P-SW-06 | 主庫不存在時讀停用清單 | 全新安裝、路徑錯 | 讀程式＋測試：唯讀模式，不會建出空檔（`helpers/module_switches.py:35-38`），回空集合 | 同左 | 無 | — | `test_module_selection.py::test_read_disabled_never_creates_the_db`（突變：拿掉唯讀模式 ⇒ 紅） | 低 |
| P-SW-07 | 停用清單內容壞掉 | 手改 value_json | 測試：回空集合並記 WARNING（`helpers/module_switches.py:52`） | 同 P-SW-05 的「看得到」 | 看不出來 | 修設定 | `test_module_selection.py::test_read_disabled_values`（⇒ §9.4：併入 P-SW-05，沿用快取／全部停用） | 中 |
| P-SW-08 | 停用的模組還有排程在跑 | 停用後 | 讀程式：沒 import ⇒ 排程沒有登記（`main.py:587` 只迭代 loaded）；L1 沒有直接呼叫模組排程（grep `tender_source` 於 `main.py`／`routers`／`helpers` 只剩註解） | 同左 | 無 | — | `test_module_selection.py::test_loader_priority_and_no_import`（`sys.modules` 沒有該模組） | 低 |
| P-SW-09 | 停用／未授權的優先順序 | 兩者同時成立 | 子行程實測：state=unlicensed（未授權優先） | 同左 | 管理頁「未授權」 | — | `test_module_selection.py::test_after_restart_…[both]` | 低 |
| P-SW-10 | 兩位管理者同時切換 | 同時按 | 讀程式：`set_enabled` 讀－改－寫沒有鎖（`helpers/module_switches.py:61`）⇒ 後寫覆蓋前寫 | 以交易或單一 SQL 更新 | 其中一人的切換消失 | 重按 | 缺 | 低 |
| P-SW-11 | 權限 key 屬於未安裝／未載入的模組 | 使用者權限畫面 | 讀程式：權限目錄是靜態清單（`helpers/module_registry.py:52` 固定含 `tender_radar`；`routers/modules.py:14` 原樣回傳）⇒ 權限畫面照常可勾「標案雷達」 | 標示「模組未安裝／未載入」並停用勾選（保留既有勾選，不刪） | 可以勾一個不存在的功能 | — | 缺 | 中 |

## 3. 串接（provider）

| # | 狀態 | 怎麼觸發 | 目前實際行為 | 應有行為 | 使用者看得到什麼 | 怎麼復原 | 守門 | 嚴重度 |
|---|---|---|---|---|---|---|---|---|
| P-IP-01 | provider 不在 | 對方模組未安裝／未載入 | 讀程式＋測試：各使用端退化並明說（IP-1～4，`helpers/bonus_vouchers.py:51-59`、`helpers/recognition.py:242`、`routers/vouchers.py:582`、`routers/bonus.py:1888`） | 同左 | 「未產生傳票：會計模組未安裝」等提示 | 裝回對方模組 | `test_dispatch_connector.py`、`test_voucher_connectors.py`、`test_voucher_status_connectors.py` 的反向控制 | 低 |
| P-IP-02 | 同一能力有多個 provider | 兩個模組都登記 | 讀程式：`single_provider` 丟 `RuntimeError`（`core/registry.py:130`）；使用端沒有接 ⇒ 該請求 500 | 啟動時就偵測並讓後登記的那個模組 failed（不要等到第一個請求才炸） | 相關功能 500 | 移除其一 | `test_dispatch_connector.py::test_registry_rules`（只驗丟例外，不驗啟動偵測） | 中 |
| P-IP-03 | provider 呼叫時丟例外 | 對方的 bug、DB 錯 | 讀程式：使用端沒有 try ⇒ 例外往上丟。獎金核准（`routers/bonus.py:2288`）在 commit 前 ⇒ **整個核准不成立**、500；營運報表經 `dispatch_entries` ⇒ **整份報表** 500 | 依 IP 原則：本身的動作照常，對方那一項降級並明說（「傳票產生失敗：…請會計手動開立」）；報表少那一類並標示 | 500 | 修對方 | 缺 | 中 |
| P-IP-04 | provider 呼叫逾時 | 對方卡住 | 讀程式：provider 是同步函式呼叫，沒有逾時概念；卡住＝請求卡住 | 目前都是本機 DB 操作，不跨網路 ⇒ 暫不需要；有跨網路的 provider 時必須加 | 頁面轉圈 | — | 缺（目前不適用） | 低 |
| P-IP-05 | 回傳形狀不符契約版本 | 對方改欄位沒升版 | 讀程式：沒有執行期版本協商；缺欄位 ⇒ `KeyError` ⇒ 500 | 契約測試在 CI 擋下（執行期不檢查） | 500 | 對方回復欄位或升版 | 契約形狀測試：`test_dispatch_connector.py::test_contract_shape_has_every_consumed_key`、`test_voucher_connectors.py::test_contract_…`、`test_voucher_status_connectors.py::test_contract_…` | 低 |
| P-IP-06 | 事件沒有人訂閱 | — | 讀程式：**事件匯流排尚未實作**（`core/`、`helpers/` 無 publish／subscribe） | 設計時：沒有訂閱者＝正常（事件是通知，不是要求） | — | — | 不適用（未實作） | 低 |

## 4. 跨模組資料

| # | 狀態 | 怎麼觸發 | 目前實際行為 | 應有行為 | 使用者看得到什麼 | 怎麼復原 | 守門 | 嚴重度 |
|---|---|---|---|---|---|---|---|---|
| P-DT-01 | 模組未載入，它的表還在、別人仍讀它的表 | 停用 tender_radar | 讀程式：地圖（L1）直接讀 `tenders`（`routers/map_points.py:136`、`:638-647`），只看權限 key（`:398-406`）、不看模組是否載入 ⇒ **停用後地圖仍顯示標案點**，點下去連到停用的頁面（`frontend/static/record-link.js:48`） | 地圖改用模組狀態（或走 provider）；模組未載入 ⇒ 不列該來源並說明 | 看得到已停用功能的資料 | — | ~~缺~~ ⇒ ✅ §9.4 | 中 |
| P-DT-02 | 單據連到已移除／未載入模組的資料 | 獎金 → 傳票，M06 不在 | 測試：明細仍列出並標「無法查詢狀態」（IP-4） | 同左 | 提示 | 裝回 M06 | `test_voucher_status_connectors.py::test_without_accounting_return_keeps_the_link_and_says_so` | 低 |
| P-DT-03 | 移除**尚未搬進 modules/** 的模組 | 刪 `routers/xxx.py` | 讀程式：`main.py:28` 直接 import 所有舊 router ⇒ **ImportError，伺服器起不來**；其他舊 router 之間也還有直接 import（邊界基線 `l2_import_baseline.json`） | 只有 `modules/` 底下的模組支援移除；舊模組依 ROADMAP 階段 B 搬遷後才有 | 服務起不來 | 放回檔案 | `tests/platform/test_module_boundaries.py`（邊只准變少） | 高（已知結構限制，靠搬遷解決，不另補） |
| P-DT-04 | row_access 的 kind 沒有登錄 | 擁有該表的模組沒載入 | 測試：fail closed（visible False、SQL 恆假、WARNING，連 admin 也不放行，`helpers/row_access.py` `rule_for`） | 同左 | 該類資料看不到 | 裝回模組 | `test_row_access_2026_09_25.py::test_unregistered_kind_fails_closed` | 低 |
| P-DT-05 | 模組未載入，它的表仍在備份／匯出裡 | 停用 | 屬 C 的範圍（備份），此處只標記：資料保留是 §9c 的要求 | — | — | — | （C） | — |

## 5. 前端入口

| # | 狀態 | 怎麼觸發 | 目前實際行為 | 應有行為 | 使用者看得到什麼 | 怎麼復原 | 守門 | 嚴重度 |
|---|---|---|---|---|---|---|---|---|
| P-FE-01 | 模組未載入（停用／未授權／失敗） | §9c | e2e 實測：側欄入口被藏（`frontend/static/sidebar.js` `_hideUnavailableModulePages`） | 同左 | 入口消失 | — | `test_e2e_module_settings_2026_09_25.py::test_sidebar_hides_entries_of_unloaded_modules`（含正對照、突變） | 低 |
| P-FE-02 | 模組**不在安裝包**（資料夾不存在） | 選配打包沒包、手動刪除 | 讀程式：狀態表只列存在的資料夾（`core/loader.py:66-68`）⇒ unavailable-pages 不含它 ⇒ 側欄入口**照樣出現**（`sidebar.js:494`、`:678` 只看權限 key）；頁面檔在 `frontend/pages/`（不在模組資料夾）⇒ 點得進去 | 入口消失（頁面清單應由已知的模組宣告反推，或頁面隨模組資料夾走） | 點進去是壞掉的頁面 | — | ~~缺~~ ⇒ ✅ §9.4 | 中 |
| P-FE-03 | 直接打網址進入未載入模組的頁面 | 書籤、別頁連結（P-DT-01） | 讀程式：頁面是靜態檔（`main.py:696` StaticFiles）⇒ 照常載入；`/api/tender-radar/status`、`/watches` 失敗時**靜默**（`frontend/pages/tender-radar.html:673-676`），清單顯示「標案清單載入失敗（HTTP 404）」（`:547`） | **提示頁**：「此模組目前未啟用／未授權／不在安裝包」＋原因＋回首頁（不是 404：靜態頁回 404 會讓人以為網址打錯） | 半空白頁＋HTTP 404 字樣 | — | ~~缺~~ ⇒ ✅ §9.4 | 中 |
| P-FE-04 | 選單清單的 API 失敗 | 網路、後端錯 | 讀程式：`_hideUnavailableModulePages` 的 `catch` 什麼都不做 ⇒ 全部入口照常顯示 | 同左可接受（入口顯示但 API 仍 404，不會越權） | 可能點到未載入的功能 | — | 缺 | 低 |
| P-FE-05 | 入口先出現再被藏（閃一下） | 頁面載入 | 讀程式：側欄同步建好後才非同步藏（同獎金做法） | 可接受 | 閃一下 | — | 缺 | 低 |
| P-FE-06 | 停用後其他頁面仍有連結指向它 | 地圖的標案點、record-link | 讀程式：`frontend/static/record-link.js:27`、`:48` 仍產生 `tender-radar.html` 連結 | 連結依模組狀態不產生，或點了走提示頁（P-FE-03） | 點到未載入的頁面 | — | ~~缺~~ ⇒ ✅ §9.4 | 低 |

## 6. 重現方式

- **R1 載入器**：`docs/platform/states/repro/r1_loader.py`——在臨時目錄建 11 個合成模組（JSON 壞、缺 core、core 不相容、寫法看不懂、key 不符、匯入失敗、缺 __init__、缺 MODULE、兩個同路由、有程式沒 module.json），呼叫 `core.loader.load_all()`，再用 FastAPI 掛上已載入的 router 打同一條路由。
- **R2 停用清單**：`docs/platform/states/repro/r2_disabled_list.py`——臨時 sqlite 寫入 `modules_disabled=["tender_radar","ghost_module"]` 讀一次；另開連線 `BEGIN EXCLUSIVE` 持鎖時再讀一次（耗時 7.5 秒、回空集合）。
- 子行程實測：`tests/platform/test_module_selection.py::test_after_restart_the_module_is_gone_and_data_stays`。

## 7. 處置提案

**本分支補（等主持看過目錄後才動）**：P-LD-07、P-SW-05（高且缺守門）。各自附反向控制與突變驗證。

**排進 ROADMAP 階段 S**（依嚴重度）：
- 中：P-LD-03（主版號升級前的相容性預檢）、P-LD-06、P-LD-08、P-LD-12（模組 migration 執行器，第一個有自有表的模組搬遷前）、P-SW-03、P-SW-07、P-SW-11、P-IP-02、P-IP-03、P-DT-01、P-FE-02、P-FE-03
- 低：P-LD-13、P-SW-04、P-SW-10、P-FE-04、P-FE-05、P-FE-06
- 不處理：P-DT-03（靠階段 B 搬遷解決）、P-IP-04／P-IP-06（未實作的機制，設計時納入）

## 8. R1 實測輸出（摘錄）

```
m_badcore      failed    requires core >=2.0,<3.0, have 1.2
m_badjson      failed    Expecting property name enclosed in double quotes: line 1 column 2 (char 1)
m_badrange     failed    core range: unparsable core range: '~1.0'
m_dup_a        loaded
m_dup_b        loaded
m_importerr    failed    No module named 'no_such_package_zz'
m_keymismatch  failed    module.json key 'other' != folder 'm_keymismatch'
m_nocore       failed    core range: empty core range
m_noinit       failed    MODULE missing or key mismatch
m_nomodule     failed    MODULE missing or key mismatch
m_nomanifest 出現在狀態表？ False
GET /api/dup/x → {'who': 'm_dup_a'} ；同路徑路由數 = 2
```
R2：`含不存在的 key：['ghost_module', 'tender_radar']`；`排他鎖期間讀到：[] 耗時 7.5s`（WARNING：`讀不到 modules_disabled（database is locked）⇒ 本次啟動視為沒有停用任何模組`）

## 9. 主持裁示與實作設計（交接，2026-09-25 22:0x，視窗 A）

> 狀態：目錄已完成、主持已審。**程式一行都還沒改**。分支 `wip/a-platform-states`，worktree `D:\MOTRIX-PLATFORM-A2`，
> 已 rebase 到 platform `bc8e0b51`（§9c 已在 platform 裡）。照 PLAYBOOK §C 做；完成後 fast-forward 合回。

### 9.1 主持裁示（要做的 6 件）

| 項目 | 裁示 |
|---|---|
| P-LD-07 路由衝突 | 後載入、撞到路由的模組 failed，原因寫明路徑與對方；**模組不可以蓋掉 L1 的路由**（另加一題） |
| P-SW-05 讀不到停用清單 | 用「上一次成功讀到的清單」（快取檔，位置向 `core.paths` 取，屬 F4，不進雲端／匯出）；**沒有快取 ⇒ 所有 L2 都不載入**，記 ERROR，管理頁與狀態端點標「停用清單讀取失敗，模組暫不載入」（寧可少開，不可多開） |
| P-FE-03 直接打網址 | 提示頁（不是 404），寫明原因（停用／未授權／未安裝／載入失敗）與處理方式 |
| P-FE-02 不在安裝包 | 入口顯示依「狀態表裡有這個模組**而且**已載入」，不是只看權限 key |
| P-DT-01＋P-FE-06 | 地圖先改成檢查模組是否已載入（最小改動；provider 化留給 M08 搬遷）；連結依模組狀態決定產不產生 |
| P-SW-03 | 管理頁提示「授權變更於重啟後生效」 |
| 其餘 | 照 §7 排進 ROADMAP 階段 S：C 已建好該節（5f95850a），**我的列用 S-P 編號接在同一張表後面**，欄位 `# ｜ 狀態 ｜ 嚴重度 ｜ 目前守門 ｜ 狀態`，不動 S-C 開頭的列 |

### 9.2 實作設計（已想清楚，照做即可）

**P-LD-07**
- 新增 L0 `core.loader.mount_modules(app) -> dict[key, reason]`：逐一取 `registry.loaded()`，把模組每條 route 的 `(method, path)` 與 **app 上已掛的路由**比對（路徑參數正規化成 `{}` 再比；owner＝L1 或先掛的模組，用 route.endpoint 的身分對回模組）；撞到 ⇒ 該模組**整個不掛**，`registry` 新增 `unload(key, reason)`（移出 `_LOADED`、`mark_failed`、`set_state(failed)`），reason 例：「路由衝突：GET /api/x 已由 L1（或模組 k）提供」。
- `main.py`：模組掛載從現在的 `main.py:678`（L1 router 中間）**移到所有 L1 `include_router` 之後、`app.mount("/", StaticFiles…)` 之前**，改呼叫 `mount_modules(app)`。
- ⚠ 模組的 **schedulers**（`main.py:587`）與 **startup_notices**（`:620`）目前在掛路由之前就跑 ⇒ 必須移到 `mount_modules` 之後，否則被判衝突的模組排程已經啟動。
- 測試（in-process 即可，不需 main）：新 FastAPI app 先 include 一支「L1」router（例 `GET /api/ping`）；registry 放兩個合成模組（一個撞 L1、一個撞前一個模組、一個正常）；呼叫 `mount_modules` ⇒ 撞的兩個 failed＋原因、正常的掛上、`/api/ping` 回 L1 的內容。突變：拿掉比對 ⇒ 紅。

**P-SW-05**
- `core.paths`：新增 `modules_disabled_cache(db_path)` ＝ 主庫旁的 `<db>.modules_disabled.json`（放主庫旁，測試夾具改 `db.DB_PATH` 時自動隔離——**不要**用固定的 `core.paths` 常數路徑，那會讓測試寫真實目錄）。`.gitignore` 加 `backend/*.modules_disabled.json`。
- `helpers.module_switches`：讀成功 ⇒ 原子寫快取；讀失敗 ⇒ 有上限重試（例 3 次、每次 sqlite timeout 2 秒）⇒ 仍失敗讀快取（source="cache"，記 ERROR）⇒ 沒快取 ⇒ source="unreadable"，**回「全部停用」**。回傳改成小物件 `(keys | ALL, source, message)`；`main.py:40` 對應調整。
- loader：支援「全部停用」＋停用原因（`disabled_reason`），狀態表 reason 寫「停用清單讀取失敗，模組暫不載入」。
- `registry` 記一筆「停用清單來源」；`/api/system/modules` 回 `disabledList: {source, message}`，`module-settings.html` 頂端顯示。
- 測試：`docs/platform/states/repro/r2_disabled_list.py` 的排他鎖手法；有快取 ⇒ 用快取；無快取 ⇒ 全部 disabled；突變：失敗時回空集合 ⇒ 紅。**注意** `read_disabled_at_startup` 目前在 `tests/platform/test_module_selection.py` 被直接呼叫（回 frozenset），改介面要一起改那幾題。

**P-FE-02／P-FE-03／P-FE-06**
- 端點：新增 `/api/system/modules/availability`（任何登入者）＝ `{key: {"state", "label"}}`（不給 reason 細節；reason 只給 superadmin 的 `/api/system/modules`）。現有 `/api/system/modules/unavailable-pages` 改為由它取代（只有我的測試與 sidebar 在用；`tests/golden_case_page_2026_09_24.json` 的「99 API 請求」要用 `GOLDEN_WRITE=1` 重錄，diff 應只換這一行）。
- `sidebar.js`：宣告 `MODULE_PAGES = {'tender-radar.html': {key: 'tender_radar', name: '標案雷達'}}`；入口只在 `availability[key].state === 'loaded'` 時顯示（**未知＝不在包內＝不顯示**）。守門題：每個 `modules/*/module.json` 的 `pages` 都要在 `MODULE_PAGES` 裡且 key 對得上。
- 提示頁：同一支 sidebar.js，目前頁面若在 `MODULE_PAGES` 而狀態非 loaded ⇒ 把 `<main>` 藏起來、插入提示區塊（停用：請洽最高管理者於系統→模組管理啟用，重啟後生效；未授權：請聯絡供應商取得包含此模組的授權；未安裝：此安裝包未包含這個模組；載入失敗：請洽系統管理者查看模組管理的原因）。
- `record-link.js`：`tenders` 連結在模組未載入時不產生（讀 sidebar 存的 `window.MOTRIX_MODULE_AVAILABILITY`；未知時照舊產生，點了由提示頁接手）。

**P-DT-01**
- `routers/map_points.py:398-406` `_may_see_tenders`：另外要求 `core.registry.is_loaded("tender_radar")`；`:638-647` 模組未載入時 `source_info` 加 `{"source": "tenders", "skipped": "module_not_loaded"}`（明說，不默默少）。

### 9.3 驗證要求（主持）
- 跑受影響題（非全量；L1 有改 ⇒ 依 §C-4 在 detached worktree 跑全量，或依 §C-11 已驗證的差異只跑 changed-since）。
- 每項附反向控制與突變驗證；e2e：停用後側欄入口消失、直接打網址看到提示頁、地圖不列標案。
- ⚠ 教訓（這一輪抓到的）：registry 的測試夾具一律用 `registry.snapshot()`／`restore()`；新守門題不可以依賴「worker 有沒有先 import main」。

### 9.4 處理結果（2026-09-25，接手視窗 A2）

分支 `wip/a-platform-states`；CORE 1.8 → 1.9（`backend/core/CHANGELOG.md`；更正：原寫「1.2 → 1.3」「1.3 → 1.4」「1.4 → 1.5」「1.5 → 1.6」「1.6 → 1.7」，每次 rebase 時都已被別人先用掉；依 PLAYBOOK §C-7 合回時才定）。每一項都有反向控制，並以突變驗證（拿掉判斷 ⇒ 紅）。

| 項目 | 處理 | 守門（正對照／反向控制） | 突變 ⇒ 紅 |
|---|---|---|---|
| P-LD-07 路由衝突 | `core.loader.mount_modules(app)`：`main.py` 在**所有** L1 `include_router` 之後、StaticFiles 之前呼叫；撞 L1 或先掛的模組（同方法同路徑，路徑參數正規化）⇒ 整個不掛、`registry.unload` 記 failed＋「路由衝突：GET /api/x 已由 L1（或模組 k）提供」；模組排程與啟動提示移到它之後 | `test_core_loader.py::test_mount_modules_refuses_route_conflicts`（撞 L1／撞模組／撞參數路徑、不同方法不算、不掛一半、provider 一併消失）、`::test_mount_modules_without_conflict_mounts_everything`、`::test_main_mounts_modules_after_every_l1_router`（靜態讀 main.py，不 import main） | 拿掉比對；L1 路由不列入 owner；mount 搬到 L1 之前；排程迴圈搬到 mount 之前；（更正後）`matches` 永不成立、略過 L1、讀不出路徑當成沒有路由——FastAPI 0.133 與 0.141 各跑一次 |
| P-SW-05 讀不到停用清單 | `helpers.module_switches.read_disabled_list()`：重試 3 次 × 2 秒 ⇒ 沿用快取（`core.paths.modules_disabled_cache`＝主庫旁 `<db>.modules_disabled.json`，F4、.gitignore）⇒ 沒快取 ⇒ **全部停用**（`loader.ALL`，原因「停用清單讀取失敗，模組暫不載入」），記 ERROR；`set_enabled` 同步寫快取；`/api/system/modules` 回 `disabledList`，模組管理頁頂端標示 | `test_module_selection.py::test_locked_db_uses_last_good_list_then_all_disabled[journal_exclusive／wal_locking_mode_exclusive／corrupt_header]`（R2 手法＋WAL 組態的觸發方式，AUDIT-X-9c C-2）、對照 `::test_wal_begin_exclusive_does_not_block_reads`、`::test_retry_is_bounded`、`::test_loader_all_disabled_marks_every_module`、`::test_toggle_updates_the_cache`、`::test_admin_page_shows_disabled_list_source`、子行程 `::test_after_restart_the_module_is_gone_and_data_stays[unreadable]`；e2e `test_e2e_module_settings_2026_09_25.py::test_page_shows_unreadable_disabled_list_and_license_change` | 失敗時回空集合；沒快取時不全停；`set_enabled` 不寫快取；main 忽略全停；「表還沒建」當成讀不到 |
| P-SW-07 內容壞掉 | 併入 P-SW-05 同一路徑（原本回空集合） | `::test_read_disabled_values` | 同上 |
| P-FE-02 不在安裝包 | 新端點 `/api/system/modules/availability`（登入即可，`{key:{state,label,name}}`，不回原因）；`sidebar.js` 的 `MODULE_PAGES` 宣告頁面→模組，入口只在 `state==='loaded'` 時顯示（清單沒有這個 key ＝不顯示）；舊 `/unavailable-pages` 保留相容 | `::test_availability_lists_package_modules_only`、`::test_every_module_page_is_declared_in_sidebar`＋`::test_every_module_page_guard_negative_control`；e2e `test_states_platform_entries_2026_09_25.py::test_sidebar_hides_entry_of_module_not_in_package` | 「沒有 key ＝顯示」；availability 回原因；MODULE_PAGES 頁名打錯 |
| P-FE-03 直接打網址 | `sidebar.js`：目前頁面屬於未載入模組 ⇒ 藏 `<main>`、插入提示（停用／未授權／載入失敗／未安裝＋處理方式＋回首頁） | e2e `::test_direct_url_to_unloaded_module_shows_notice[4 種]`、正對照 `::test_direct_url_to_loaded_module_has_no_notice` | 不呼叫提示 |
| P-DT-01＋P-FE-06 | `map_points._tender_module_loaded()`（`registry.is_loaded("tender_radar")`）：未載入 ⇒ 不列標案、`sources` 標 `module_not_loaded`＋說明（快取鍵的 `visible` 一併變）；`record-link.js` 依 `MOTRIX_MODULE_AVAILABILITY` 不產生未載入模組的連結（未知時照舊，點了由提示頁接手） | `::test_map_lists_tenders_only_while_the_module_is_loaded`；e2e `::test_map_page_does_not_list_tenders_or_link_to_unloaded_module` | 地圖不看載入狀態；record-link 不看狀態 |
| P-SW-03 授權執行中變更 | `/api/system/modules` 每列當下重判授權：與啟動時不同 ⇒ `licenseChanged`、`licenseNote`「授權變更於重啟後生效：…」，`afterRestart` 依新授權；模組管理頁該列顯示 | `::test_license_change_is_shown_until_restart[4 種，含 2 種沒變的反向控制]`；e2e 同 P-SW-05 那題 | 不改 afterRestart；不標 licenseChanged；頁面不讀 disabledList |

- **更正（23:10）**：P-LD-07 第一版用 `route.path` 字面比對（路徑參數正規化成 `{}`）。在 3.11／FastAPI 0.133 上綠，但在 3.12／FastAPI 0.141 上 `include_router` 會把整支 router 包成沒有 `path` 的物件，⇒ **完全看不到 L1 路由，撞 L1 的衝突默默放行**（`.venv312` 差異題抓到）。改用 starlette 公開的 `route.matches(scope)` 探測（路徑參數代入 "0"，與路由器本身選路由是同一個判斷）；讀不出路徑的模組 router 一律不掛（不猜）。新增兩題：先掛的參數路由接走模組固定路徑＝衝突（反過來不算）；模組 router 內含巢狀 include ⇒ 不掛。「讀不出路徑」那個突變在 0.133 上存活，屬於等價突變：0.133 讀得出巢狀路徑，走不到那一支；在 0.141 上會轉紅。
- 本輪新增的 API 題改用合成模組狀態列（不綁 tender_radar，AUDIT-X-9c A-2 不再擴大）；`test_states_platform_entries_2026_09_25.py` 驗的對象就是 tender_radar，安裝包沒有它時整檔 skip 並說明。
- 案件頁 golden（`tests/golden_case_page_2026_09_24.json`）以 `GOLDEN_WRITE=1` 重錄：diff 只換一行（`/unavailable-pages` → `/availability`）。
- 其餘中、低項目排進 ROADMAP 階段 S（S-P 開頭）；「L1 讀 L2 表要先看載入狀態」的通用守門排進階段 G（G7）。
- 給 D5（主持／H，儀表板模組狀態）：路由衝突的模組在 log 會先有「模組 X 版本 已載入」、之後才有「模組 X 未載入：路由衝突：…」——以**最後一行**為準。

