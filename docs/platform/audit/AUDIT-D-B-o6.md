# 稽核：B 的 O6——hard_cap 探針目錄移出 tests/（wip/b-o6；合回前）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。
> 對象：`origin/wip/b-o6` `a8f60a28`（只改 `backend/tests/test_e2e_hard_cap_2026_09_25.py`）：探針目錄由 `backend/tests/_hardcap_probe_<id>` 改成 `backend/.hardcap_probe_<id>`；新題 `test_probe_dir_is_outside_collected_trees`。
> 稽核樹 `D:\MOTRIX-PLATFORM-D`（detached），Python `D:\MOTRIX-PLATFORM\.venv312`（只用、未改）。

## 0. 結論

- **必修 1 項**：O6-M1。這次搬遷把原本的競態搬到另一批守門上。
- 原本的問題是：別的題的子 pytest 在收集 tests/ 時撞上探針被刪除。這個問題確實解了，因為 pytest 預設的 `norecursedirs` 含 `.*`，repo 的 pytest.ini 沒有覆寫。
- 但新位置不在 tests/ 底下。repo 裡有十多道「rglob 整個 backend、排除 tests/」的產品碼掃描，過去碰不到探針，現在全都看得到它。

## 1. 實測

D 在 D 樹做比對實驗：一個執行緒不斷建立、刪除探針目錄（內容與本題相同的一支 `.py`）；主執行緒照 `test_edge_profile` 的產品碼掃描方式（`BACKEND.rglob("*.py")`、排除 `tests`、逐檔 `read_text`）掃 20 次。

| 探針位置 | 20 次掃描中的例外 |
|---|---|
| **新位置** `backend/.hardcap_probe_*` | **FileNotFoundError 3 次**（前一輪實驗另有 **PermissionError**：Windows 上檔案正在刪除時被讀） |
| 舊位置 `backend/tests/_hardcap_probe_*` | 0 |

- 會走到新位置的掃描（排除 tests/、但沒有排除「.」開頭目錄），`git grep` 找到的有：`test_edge_profile`（:20）、`test_begin_only_via_begin_write`（:62）、`test_requirements_cover_imports`（:97）、`_l1_interface.cross_boundary_public`（:142）、`test_module_history`（:320）、`test_site_wording`（:58）、`test_px1_permission_message_matches_guard`（:95）、`test_navigation_destination`（:105）、`test_dispatch_connector`（:117）、`test_platform_catalog`（:523）、`test_deploy_dashboard_local_only`（:390）、`test_pdf_concurrency`（`os.walk`，:82）、`tools/platform/dep_scan.py`（:133）等。
- 附帶發現：本題 fixture 用 `shutil.rmtree(d, ignore_errors=True)` 清理，而讀取端開著檔案時會刪不乾淨。D 的實驗就留下了 2 個空的 `.hardcap_probe_*`（已手動刪除）。殘留在新位置時，上面那些掃描會一直掃到它。

## 2. 發現

### 必修

**O6-M1　探針搬到 `backend/.hardcap_probe_*` ⇒ 競態從「收集 tests/」搬到十多道產品碼掃描**
- 原本的症狀是全量裡偶發 FileNotFoundError（第二班紅 1 次）；搬家之後，同樣的偶發紅會出現在另一批題目上，而且那些題的名字與 hard_cap 無關，更難追（MEMORY〈偶發失敗先當產品競態〉）。
- 建議修法：改放 `backend/tests/.hardcap_probe_<id>`，兩邊都避開。
  - 它在 tests/ 底下，所以「排除 tests/」的產品碼掃描碰不到。
  - 它是「.」開頭，所以 pytest 遞迴收集不會進去（預設 `norecursedirs` 含 `.*`，pytest.ini 沒有覆寫）。
  - `backend/conftest.py` 仍然是它的上層，照樣吃得到。
  - 同時把 `test_probe_dir_is_outside_collected_trees` 改成斷言「在 tests/ 底下、而且是『.』開頭」。
- 另外補清理：刪不掉時重試幾次，或者在 session 結束時掃掉本題留下的 `.hardcap_probe_*`。

## 3. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | D 確認 |
|---|---|---|---|
| O6-M1 | 探針改放 `backend/tests/.hardcap_probe_*`；刪不掉印出並重試一次、仍失敗發 warning；靜態守門實際建探針、確認 source_tree 三個清單找不到它 | wip/b-o6-2 31d0033d | ✅ 11:02 D：重跑比較實驗（新位置、edge_profile 式掃描）20 次 **0 例外**；突變「探針回 backend 根」「前綴去掉點」⇒ 皆紅；基準 5 passed ⇒ **關閉（31d0033d）**。衍生建議 O6-S1 |
| O6-S1 | （主持修，local_only 屬主持的題）import 掃描抽成 `_scan_py_sources`：跳過「.」開頭目錄、讀的瞬間消失的檔略過、其他 OSError 照丟；tmp_path 重現題 | wip/h-o6s1 e2c8fdbd | ✅ 11:04 D：突變「不跳點目錄」⇒ 紅 ⇒ 掃描這一半**關閉（e2c8fdbd）**。小建議：函式說明寫「刻意含 tests/」，但正對照只放 `routers/ok.py`——D 突變「連 tests/ 也跳過」照綠（11 passed），建議正對照加一支 `tests/x.py`。靜態守門說明那一半（只驗 source_tree）由主持轉 B |

## 4. 31d0033d 複核（D，2026-09-26 11:02）

- 主持問：靜態守門只驗 `source_tree` 的三個清單，自己寫 rglob 的掃描擋得到嗎？D 逐行查了 §1 列的 13 道：**12 道排除 tests/**（`"tests" in parts`、`rel.startswith("tests/")`，或 `_SKIP_DIRS`／`_SKIP` 含 tests），所以新位置碰不到；**只有 `test_deploy_dashboard_local_only_2026_09_22.py:390` 不排除 tests**，而且只接 `SyntaxError`／`UnicodeDecodeError`。
- 實測（新位置 `backend/tests/.hardcap_probe_*`，20 次）：edge_profile 式掃描 **0**；local_only 式掃描 **FileNotFoundError 1**。後者在舊位置 `tests/_hardcap_probe_*` 也一樣看得到，是原本就存在的暴露，不是這次造成的。
- **O6-S1（建議）**：`test_deploy_dashboard_local_only` 的掃描跳過「.」開頭的目錄，或者把 `OSError` 一起當作略過；靜態守門的說明把「自己寫 rglob、排除 tests 的掃描」寫成已涵蓋，而實際上沒有題驗它們，建議補一句「由各掃描自己排除 tests/ 保證，本題只驗 source_tree」。

