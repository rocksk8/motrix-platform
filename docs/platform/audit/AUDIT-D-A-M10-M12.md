# 稽核：A 的 M10 網路規劃搬進 modules/netplan、M12 修正重驗、X-2 新規則（PLAYBOOK §B；上月台後稽核）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。只審新版（CORE-SPEC 35014aaa）。
> 對象：`origin/wip/a-m10` **`d2a95371`**（含 M12，取代 a-m12）。M10：`37430f44` 搬遷、`b6faa6cf`、`8835326c` module_installed、`6492aa6c` EM1、`acd8227f`、`30dab2ae`、`c38103a4` SPEC.md、`d2a95371` 反向控制 6 紅歸位；M12 修正：`c57f578a`、`16865fa3`、`d2a95371`；X-2：`be41fd9e`、`d2a95371`（正對照不綁 L2）。
> 反向控制範圍依主持 2026-09-26 定的標準：**`tests/platform`＋所有提到該模組的測試檔**（PLAYBOOK §B-11；`test_unit_index_is_current` 已列入允許清單）。
> 稽核樹 `D:\MOTRIX-PLATFORM-D`、`-D2`（detached），Python `D:\MOTRIX-PLATFORM\.venv312`（只用、未改）。
> 分級：**必修**／**建議**／**觀察**。關閉規則：被稽核者回覆後，由 D 確認才關。

## 0. 結論

- **必修 0 項**。
- **M12 的 M-1 關閉**：在 `d2a95371` 上真的刪掉 `modules/daily_tasks`，跑 `tests/platform` 加上 21 個檔，結果是 **953 passed、2 failed**，紅的兩題都在允許清單內。
- **M10 的 §B-11 反向控制通過**：真的刪掉 `modules/netplan`，跑 `tests/platform` 加上 12 個檔，結果是 **885 passed、2 failed**，紅的兩題都在允許清單內；不加 `--continue-on-collection-errors` 另跑收集，**888 題收集成功，沒有收集錯誤**。
  - D 在 `16865fa3` 上審的時候，曾經紅了 7 題，另有 1 個檔收集失敗（§2 保留這一輪的紀錄）。A 在 D 回報之前，已經以 `d2a95371` 自行修正。
- **X-2 新規則很嚴密**：在 `d2a95371` 上做了 7 項突變，全部轉紅。其中包含「只限 `modules/` 路徑」「混合提供方不豁免」，以及新版正對照改成不綁 L2 之後的「提供掃描失效」。
- A 在註解中寫「netplan 的 Edge 呼叫端由 sys.modules 掃描涵蓋」：D 用突變 EP1 驗證，結果成立。
- 另有建議 1 項、觀察 3 項。

## 1. M12 重驗（M-1 的關閉確認）

| 輪次 | 樹 | 範圍 | 結果 |
|---|---|---|---|
| 稽核時 | a-m12 `639949f4` | tests/platform＋17 檔 | 894 passed、**9 failed** |
| 重驗一 | a-m10 `16865fa3` | tests/platform＋18 檔（在 a-m10 上重新 grep；多了 A 新增的 `test_e2e_case_stage_daily_task_notice_2026_09_26.py`） | 910 passed、2 failed（皆在允許清單） |
| 重驗二 | a-m10 **`d2a95371`** | tests/platform＋21 檔（grep `daily_tasks\|daily-tasks\|daily_task`） | **953 passed、2 failed**（皆在允許清單） |

- A 的修正：
  - `c57f578a` 把 5 題移到 `modules/daily_tasks/tests/test_case_stage_done_daily_task.py`。
  - `6492aa6c`／`73ea3cff` 讓 EM1 用 `module_installed` 略過不在的模組。
  - `d2a95371` 把 `test_module_permission_fixes::test_modules_without_backend_checks_now_block` 裡寫死的 `/api/daily-tasks` 拿掉。這一項只刪不補，理由是「沒有模組權限就不給清單」這件事，已經由模組內的 `test_daily_tasks_main_flow.py::test_without_the_module_permission_the_list_is_refused` 涵蓋。D 接受，因為模組內的那一題有驗到 403。
- 其他項目：
  - S-1：`c38103a4` 補了 SPEC.md 與 G2 守門。
  - S-2：`c57f578a` 補了主流程 3 題；A 報突變 4/4 轉紅。
  - S-3：ROADMAP 已更新。
  - S-4（`system_checks.run_all` 沒有逐項隔離）：依主持裁示排進 ROADMAP，這次不修。D 接受，因為這個寫法在搬遷前就存在，不是這次造成的。
  - O-1：CHANGELOG 已寫明來源。

## 2. M10 反向控制（§B-11，新範圍）

`rm -rf backend/modules/netplan`（只在稽核樹，做完用 `git checkout` 還原）；跑 `tests/platform` 加上 12 個提到網路規劃的測試檔，單程序、低優先權。

| 輪次 | 結果 |
|---|---|
| `16865fa3`（`--continue-on-collection-errors`） | 881 passed、**9 failed**、1 skipped、**1 error** |
| **`d2a95371`**（`--continue-on-collection-errors`） | **885 passed、2 failed**（皆在允許清單）、1 skipped |
| **`d2a95371`**（`--collect-only`，不加旗標） | **888 tests collected**、exit 0 |

`16865fa3` 那一輪紅的題（保留紀錄；A 已在 `d2a95371` 修正）：

| 紅的題 | 題數 | `d2a95371` 的處理 |
|---|---|---|
| `test_modules_json_lists_only_existing_units`、`test_unit_index_is_current` | 2 | §B-11 允許 |
| `test_e2e_filter_fields_no_leave_warning…[network-plan-form?id={pid}]` | 1 | 兩個網路規劃頁面改由 `modules/netplan/tests/test_netplan_moved_guards.py` 加進 `PAGES` 再呼叫同一支 |
| `test_module_no_admin_bypass` 的 `/api/network-plans` 三個參數＋`test_network_plan_read_accepts_case_manage_consumer` | 4 | 移進模組；L1 的檢查函式以別名匯入、不重複收集 |
| `test_module_permission_fixes::test_case_network_plan_lookup_is_guarded` | 1 | 移進模組 |
| `test_pdf_concurrency::test_pdf_gen_and_network_plan_export_share_the_same_runner` | 1 | 網路規劃那一處移進模組（`test_netplan_export_uses_the_shared_edge_runner`） |
| `test_edge_profile_2026_09_25.py` **收集失敗**（模組層級 `import modules.netplan.export`） | 整檔 | 拿掉模組層級的 import；網路規劃的呼叫端改由 sys.modules 掃描涵蓋 |

- **EP1 突變**（驗證「由 sys.modules 掃描涵蓋」）：`backend/conftest.py` 換綁 `run_edge_pdf` 時略過 `modules.*` ⇒ `test_edge_profile…::test_every_import_site_uses_the_wrapper…` 與 `test_netplan_moved_guards.py::test_netplan_export_uses_the_shared_edge_runner` **兩題都紅**（2 failed、10 passed）。L1 那一題在網路規劃的呼叫端移走之後，照樣抓得到，因為 `client` 夾具啟動 app 時會載入 netplan。

## 3. X-2 新規則：D 的突變（`d2a95371`）

對象：`backend/tests/platform/test_integration_points_registered.py`、`backend/core/source_tree.py::module_installed`。題目：同一個檔，共 6 題；每一輪都確認有收到題。

| # | 突變 | 結果 | 紅的題 |
|---|---|---|---|
| X2a | 模組在也豁免（`if paths:`） | 紅 | `test_absent_module_green_present_module_still_red` |
| X2b | `module_installed` 永遠回 False | 紅 | 同上 |
| X2c | 拿掉豁免（`doc_caps - provided`） | 紅（2） | 同上＋`test_every_installed_module_can_be_removed_without_breaking_the_registry` |
| X2d | 非 `modules/` 路徑也當成「不在」 | 紅 | `test_absent_module_green_present_module_still_red` |
| X2e | 提供方混有 `modules/` 與 routers 時也豁免（`any`→`all`） | 紅 | 同上 |
| X2f | 提供掃描失效（`provided.add` 拿掉） | 紅（4） | `test_positive_control_parser_and_scanner`、`test_reverse_controls_…`、`test_every_installed_module_…`、`test_registry_matches_code` |
| X2g | 取用掃描失效（`consumed.add` 拿掉） | 紅（2） | `test_positive_control_parser_and_scanner`、`test_real_scan_sees_a_known_capability` |

`d2a95371` 把真實掃描的正對照從「`dispatch.row` 要同時出現在 provided 與 consumed」改成「`daily.check` 要出現在 consumed」。D 用 X2f 確認：provided 這一側的掃描即使壞掉，仍然有 4 題會紅，**沒有因此出現假綠燈**。

## 4. 發現

### 必修

（無）

### 建議

- **M10-S1　§B-11 的指令要固定帶 `--continue-on-collection-errors`，並把收集錯誤列為「不過」**：M12、M02、M10 三次搬遷，都是在審的時候才發現有題目留在模組外。收集錯誤不算進 failed 的題數；而不加旗標時，pytest 會在收集階段中斷，這一輪一題都不跑（`16865fa3` 就是這樣）。這條沒有寫進 PLAYBOOK 的話，會一直有人只看 failed 的數字。

### 觀察

- **O-1　模組的測試引用 L1 測試檔的私有輔助函式**：`test_netplan_moved_guards.py` 從 `tests.test_module_no_admin_bypass_2026_09_14` 匯入 `_login`，從 `tests.test_module_permission_fixes_2026_09_13` 匯入 `_auth`、`_make_case`、`_outsider`，也匯入 L1 的題目函式本身。L1 的測試檔改名或改簽名，模組的題會跟著壞。M02、M04、M08 接下來可能照抄這個作法；建議把共用的探針抽到 `tests/platform` 的共用輔助，或由 B 決定格式。
- **O-2　`module_installed` 的邊角**：`module_installed("modules/__init__.py")` 會回 False，因為 `is_dir()` 對檔案回 False。另外，`_provider_paths` 只取含 `/` 的名稱，所以提供方如果寫成「`modules/x/api.py::a`、`_b`」而 `_b` 其實在 routers 裡，這一節仍然會被豁免。目前沒有任何 IP 這樣寫；建議在 INTEGRATION-POINTS 的格式說明寫明「提供方的每一項都要帶路徑」。
- **O-3　IP-11 撞號，以及 case.access 與 case_access 兩條路**：A 的 `IP-11 case.access`（提供方是 M01 的 `helpers/quotations.py::_CaseAccess`）與 C 的 `IP-11 crm.quote_deleted` 同號（見 AUDIT-D-C-M02-move O-1），由列車依 §C-7 重新編號。另外，M01 不在時 M10 讀取案件摘要的行為，與 C 的 case_access 有關（AUDIT-D-C-case-access CA-M1 的判準）；兩者第四班要一起合回，屆時 M01 不在時，兩條路的行為要一致。
- **O-4　空的模組資料夾會被當成「模組在」**（補記 06:49）：`module_installed()` 只看 `modules/<key>` 是不是資料夾，而 loader 看的是有沒有 `module.json`。D 的稽核樹在切換分支後，留下一個只有 `__pycache__` 的空 `modules/netplan/`（git 不追蹤空資料夾）；升級時如果刪掉模組的 .py 卻留下 `__pycache__`，正式機也會出現同樣的狀態。這時產品判斷「模組不在」，守門卻判斷「模組在」：X-2 不會豁免、EM1 會去讀不存在的檔。方向是誤紅（會被看見），不是誤綠。建議 `module_installed` 改看 `module.json`，與 loader 用同一個定義。

## 5. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | D 確認 |
|---|---|---|---|
| M10-S1 | | | |
| O-1～O-4 | | | |
