# 稽核：B 的專案環境、requirements 守門、§C-13 負載上限、全量結果依 commit 分檔（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。
> 對象：
> - `b3785e31`：project_env、requirements 守門、BK19
> - `0feda074`：tests/_routes.py、project_env 預設 3.12
> - `ba14bf36`：§C-13（modtest 壓 -n、低優先權）、Python 不綁版本
> - `3a1cc3ce`：全量結果寫成 full_results/<sha>.json，閘門讀這個 commit 的那一份
>
> 稽核基準 origin/platform `09f8fc70`，稽核樹 `D:\MOTRIX-PLATFORM-D`（detached），Python `D:\MOTRIX-PLATFORM\.venv312`（只用、未改；starlette 1.7.0、fastapi 0.141.1）。
> 分級：**必修**（不修不能關）／**建議**／**觀察**。關閉規則：被稽核者回覆後，由 D 確認才關。
> 縮寫：
> - `MT`＝`tools/platform/modtest.py`
> - `PE`＝`tools/platform/project_env.py`
> - `RQ`＝`backend/tests/platform/test_requirements_cover_imports.py`
> - `DI`＝`backend/tools/deploy_insights.py`

## 0. 結論

- **分檔機制本身正確**，D 自做突變 B04、B08 都轉紅：
  - 別的 commit 的紅燈，蓋不掉這個 commit 的綠燈。
  - dirty 的一輪不寫 per-commit 檔。
  - 檔名與內容的 commit 不符，照樣擋。
- **requirements 守門能抓到直接 import**：拿掉 pypdf、opencv，守門都會紅。
- **問題集中在「輸入」與「沒有題目的部分」**：
  - 守門與閘門驗的是**餵給它的值**，而產生那個值的程式碼沒有題目。
  - §C-13 的三處程式碼完全沒有題目：突變 B05、B06、B07 都存活。
- **必修 3 項**：
  1. B-M1：`modtest` 遇到 `-n auto` 不會壓到上限。§C-13 最常見的寫法直接穿過，而且沒有題目。
  2. B-M2：照 CORE-SPEC §10 的寫法執行 `project_env create --python 3.13`，會把 3.13 就地裝進共用的 `.venv312`，沒有存在檢查。
  3. B-M3：全量的 `dirty` 判定有兩個缺口，而且這個輸入沒有任何題目守（突變 B07 存活）⇒「這個 commit 全綠」可以代表一棵不是這個 commit 的樹。
     - 不算未追蹤檔。
     - 只在開跑時判一次。
- 建議 4 項、觀察 3 項。
- 基準（未突變）：RQ、`test_modtest_full_results`、`test_deploy_insights`、`test_deploy_dashboard_gates`、`test_modtest_rebase_check` 共 **51 passed**（單程序、低優先權）。

## 1. 逐項驗收

| 項目 | 規格 | 驗收 | 證據 |
|---|---|---|---|
| requirements 守門 | 產品 import ⊆ requirements.txt（含相依）；測試 ⊆ 再加 dev | ⚠ 只驗直接 import | 突變 B01、B03 紅；B02 存活，見 B-S1 |
| project_env create | 主工作樹建 venv，只照 requirements 安裝 | ❌ | 見 B-M2 |
| project_env check | 只提示、不擋；Python 只看支援範圍下限 | ✅ | PE:81-97；exit 一律 0（依使用者裁示）。**沒有題目**（B-S3） |
| §C-13 ①② 全量 -n ≤4、差異題 -n ≤2 | 壓到上限並說明 | ❌ | 見 B-M1 |
| §C-13 ③ 低優先權 | pytest 以 BELOW_NORMAL 執行 | ✅ 讀碼 ／ 無題目 | MT:361-363、394；突變 B06 存活 |
| 全量依 commit 分檔 | per-commit 檔；dirty 不寫；閘門讀這個 commit 的那一份 | ✅ 機制 ／ ❌ 輸入 | MT:502-516；DI:120-136；突變 B04、B08 紅；B07 存活（B-M3） |
| tests/_routes.py | 新舊 FastAPI 都能攤平路由 | ✅ | 使用方 5 檔；另見 B-O2 |
| CORE-SPEC §10 第 3 條與程式一致 | | ❌ | 規格寫「主工作樹 `.venv`」，程式預設 `.venv312`（PE:25）；見 B-M2 |

## 2. 反向控制與突變（D 自做；每項都用 `git checkout` 還原並核對內容）

| 突變 | 結果 | 轉紅的題 |
|---|---|---|
| B01 requirements.txt 拿掉 `pypdf` | 🔴 紅 | `test_product_imports_are_in_requirements`、`test_test_imports_are_in_requirements` |
| B02 requirements-dev 拿掉 `httpx2` | 🟢 **存活** | —（B-S1） |
| B03 requirements-dev 拿掉 `opencv-python-headless` | 🔴 紅 | `test_test_imports_are_in_requirements` |
| B04 `write_last_full` 遇到 dirty 照樣寫 per-commit 檔 | 🔴 紅 | `test_rc_dirty_run_does_not_touch_the_per_commit_record` |
| B05 `cap_workers` 不壓 | 🟢 **存活** | —（B-M1） |
| B06 `_low_priority_flags` 回 0 | 🟢 **存活** | —（B-S3） |
| B07 `run_full` 的 dirty 寫死成 False | 🟢 **存活** | —（B-M3） |
| B08 閘門不比對紀錄裡的 commit | 🔴 紅 | `test_last_full_states`、`test_rc_mismatched_record_inside_the_file_is_caught` |

直接呼叫（`cap_workers(e, 2)`）：

| 輸入 | 輸出 | |
|---|---|---|
| `-n 8` | `-n 2` | ✅ |
| `-n8` | `-n2` | ✅ |
| `--numprocesses 8` | `--numprocesses 2` | ✅ |
| `-n -1` | `-n 2` | ✅ |
| **`-n auto`** | **`-n auto`** | ❌ |
| `-nauto` | `-nauto` | ❌ |
| `--numprocesses=8` | `--numprocesses=8` | ❌ |

## 3. 發現

### 必修

**B-M1　`-n auto` 不會被壓到上限（§C-13 ①②）**
- 位置：MT:348-351。`n = limit if val in ("auto", "logical")` 之後判斷 `n > limit`。n 就是 limit，所以判斷不成立，原值照樣傳下去。在 12 邏輯核的機器上，`auto` 會開 12 個 worker。另外 `-nauto` 與 `--numprocesses=8` 兩種寫法完全沒有被解析。
- 為什麼是必修：
  - `-n auto` 是 xdist 最常見的寫法，本 repo 的註解與建包歷史都用它（`build_deploy_package.ps1:515-544`）。
  - §C-13 是使用者回報 CPU 100% 之後才訂的規則。
  - 沒有任何題目守（突變 B05 存活）。
- 重現：`set PYTHONIOENCODING=utf-8 && python -c "import sys;sys.path.insert(0,'tools/platform');import modtest as m;print(m.cap_workers(['-n','auto'],2))"` ⇒ `['-n', 'auto']`
- 建議修法：
  - `auto`／`logical` 一律改寫成 limit。
  - 另外解析 `-n<值>`、`--numprocesses=<值>`。
  - 補一題參數化題，把上面的表全部列進去，並用 B05 證明它會紅。
- 附帶：`cap_workers` 的 `print("⚠ …")` 只在 modtest 自己的 `__main__` 裡有 reconfigure。被別的程式 import 呼叫時，在 cp932 主控台會 `UnicodeEncodeError`（D 直接呼叫時踩到）。

**B-M2　`project_env create --python 3.13` 會就地覆寫共用的 `.venv312`**
- 位置：
  - PE:25：`VENV_DIR` 預設 `.venv312`，與 `--python` 無關。
  - PE:123-130：`py -3.13 -m venv <root>/.venv312` 沒有「資料夾已存在」的檢查，也沒有查占用，接著在同一個資料夾升級 pip、安裝全部 requirements。
- 規格：
  - CORE-SPEC §10 第 3 條寫的指令就是 `project_env.py create [--python 3.13]`，並說建出來的是 `.venv`，與程式不符。
  - PLAYBOOK §C-12「刪除或覆寫共用目錄前先查占用」。
- 後果：`.venv312` 是全部視窗共用的受測環境（主持派工也明訂「只能用，不可以修改」），而且隨時都有別的 session 在跑 pytest。
  - 3.13 的直譯器、pyvenv.cfg 蓋進 3.12 的 venv，`Lib/site-packages` 裡 cp312 的二進位套件（pydantic-core 等）還留著 ⇒ 版本混在一起。
  - 正在跑的測試會中途壞掉。
  - 重現方式與 2026-09-25「B 弄壞 .venv」同一類。
  - D 沒有實際執行這個指令（會破壞共用環境），以上依讀碼判定。
- 建議修法：
  - 目標資料夾依 `--python` 命名（例如 `.venv313`），或者資料夾已存在時拒絕執行並提示 `--force`。
  - 動手前照 §C-12 查占用。
  - 修正 CORE-SPEC §10 的文字。
  - 補一題：monkeypatch `subprocess.run`，驗證資料夾已存在時不會呼叫 venv。

**B-M3　全量結果的 dirty 判定不算未追蹤檔、只在開跑時判一次，而且這個判定沒有題目**
- 位置：
  - MT:529：`git status --porcelain --untracked-files=no`，只在 `run_full` 開頭判一次。
  - MT:527：commit 也是開頭讀的。
- 3a1cc3ce 要證明的是「per-commit 檔＝這個 commit 的全量結果」。以下三種情況下，這句話都不成立，閘門卻放行：
  - 未追蹤的檔會影響一輪全量：
    - 新增的產品檔忘了 `git add`，而 `core.loader` 會掃 `modules/` 資料夾。
    - 未追蹤的 conftest 外掛、測試檔。
    - 結果一樣記成 `dirty: false`。
    - D 實測：稽核樹裡有一個未追蹤的探針題時，這個判定回空字串。
  - 全量要跑 40 分鐘以上，中途有人改了檔、commit，或 checkout 了別的 commit，都不會被記下來。
  - 測試只把 `dirty` 值直接餵給 `write_last_full`（`test_modtest_full_results.py` 全部），從沒驗證 `run_full` 怎麼算出它。屬於「斷言驗到自己設的值」這一類假綠燈，突變 B07 存活。
- 建議修法：
  - 改成 `--untracked-files=normal`，gitignored 的照樣排除。
  - 開跑與結束各判一次，HEAD 或狀態不同就記 dirty。
  - 把判定抽成函式，並用暫存 git repo 補兩題：未追蹤檔 ⇒ dirty；跑到一半 HEAD 變了 ⇒ dirty。

### 建議

- **B-S1　requirements 守門抓不到它當初要抓的 httpx2（突變 B02 存活）**：
  - 守門只掃**直接 import**（RQ:31-50）。
  - httpx2 是 starlette TestClient 在執行期才載入的，而且在 starlette 的中繼資料裡是 `extra == 'full'`，closure 會跳過它。
  - RQ 的說明寫「成因：TestClient 需要的 httpx2 …從沒列進 requirements」，但拿掉那一行，守門照樣綠。
  - 真正能抓到它的只有「全新 venv 跑 client 夾具」。
  - 建議：
    - 加一份「執行期需要、但不會被直接 import」的清單（httpx2、playwright 瀏覽器），並驗證它們都有宣告。
    - 或者加一題：在 `sys.modules` 裡找 TestClient 實際載入的 HTTP 套件，驗證它在 requirements-dev 的 closure 裡。
- **B-S2　建包的 pytest worker 數超過 §C-13**：`build_deploy_package.ps1:556` `min(實體核心, 8)`，這台機器是 6，而 §C-13 規定全量 ≤4。建包是使用者的動作，但在同一台開發機上執行，§C-13 的理由同樣成立。建議取 `min(…, 4)`，或在規格寫明建包例外。
- **B-S3　§C-13 ③ 與 project_env 沒有題目**：`_low_priority_flags` 被突變成回 0 仍然綠（B06）。`compare`、`parse_prod_env`、`in_supported_range` 是純函式，很好測，但沒有題目。
- **B-S4　同一個 commit 重跑時，最後一次覆蓋前一次**：跑到一半中斷的紅，會蓋掉同一個 commit 先前完整的綠，這一點偏保守，可以接受。但反過來也成立：偶發紅之後重跑一次綠，閘門就放行，紀錄裡看不到曾經紅過。依〈偶發失敗先當產品競態〉，建議 per-commit 檔保留歷次結果，閘門顯示「這個 commit 曾經紅過 N 次」。

### 觀察

- **B-O1　requirements-dev 沒有直接宣告 `pytest`**：靠 pytest-xdist 的相依才裝得到。守門的 closure 會放行，但只要把 xdist 換掉，pytest 就會消失。
- **B-O2　`test_deploy_dashboard_local_only` 仍直接走訪 `app.routes`**（:165）：儀表板目前沒有 `include_router`，所以結果正確。但這題的說明是「動態列舉，明天新增的那一支自動被涵蓋」；一旦儀表板改用 include_router，它在 FastAPI 0.14x 會安靜地少掉那些路由。建議改用 `tests/_routes.py`。
- **B-O3　`project_env check` 讀 prod_env.json 的順序**：先讀本 worktree，再讀主工作樹（PE:105-107）。worktree 裡如果留著舊的一份，就會比對舊資料。影響小，可以考慮只讀主工作樹那一份。

## 4. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | D 確認 |
|---|---|---|---|
| B-M1 | 修正：`cap_workers` 認得 `-n X`／`-nX`／`-n=X`／`--numprocesses X`／`--numprocesses=X`；`auto`／`logical`／非數字／負數一律改成上限；提示改走 `_say()`（cp932 主控台不炸）。題：`test_env_and_load_guards::test_cap_workers_every_spelling`（13 種寫法，含 D 表上全部）＋ cp932 題。突變 B05 ⇒ 11 紅 | f14ee6db | |
| B-M2 | 修正：`create` 目標依 `--python` 命名（`.venv313`）；**資料夾已存在一律拒絕**（不提供 --force：就地覆寫或先刪再建都是 .venv 事件同一類），並照 §C-12 列出占用行程；CORE-SPEC §10 保留原句加更正。題：`test_rc_create_refuses_an_existing_folder`（monkeypatch subprocess.run，驗證沒有呼叫 venv／pip）。突變（拿掉存在檢查）⇒ 紅 | f14ee6db、4d0808a0 | |
| B-M3 | 修正：抽出 `tree_state()`（`--untracked-files=normal`，gitignored 照樣排除）與 `run_dirty()`；`run_full` 開跑、結束各取一次，開跑不乾淨或中途 HEAD／工作樹變了 ⇒ dirty，並記 `head_at_end`；結束時讀不到狀態 ⇒ 當成 dirty。題：暫存 git repo 驗未追蹤檔、HEAD 中途變、工作樹中途改；**行為題**實際呼叫 `run_full`（pytest 換掉）驗寫出去的紀錄。突變 B07 ⇒ 2 紅、不算未追蹤檔 ⇒ 1 紅。〔更正：B07 在我第一版題目（AST 檢查呼叫次數）下仍存活，屬「驗程式長相」的假綠燈，已改成行為題〕另確認：全量跑完後 Bfull 工作樹 `status --untracked-files=normal` 為空（測試產生的 uploads 等都已 gitignore），不會讓每一輪都 dirty | f14ee6db | |
| B-S1 | 修正：新增 `runtime_imports()`，掃描測試夾具在執行期才 import 的函式庫（`starlette.testclient`）頂層 import 的**已安裝**第三方模組，要求都在 requirements(-dev) 閉包內；正對照「掃得到 httpx2」＋反向控制。突變 B02（拿掉 httpx2）⇒ 紅 | 4d0808a0 | |
| B-S2 | 修正：建包 `Min($physCores, 4)`（保留 BOM／CRLF，PowerShell 剖析 0 錯誤）；題 `test_build_script_workers_within_full_limit`（≤ modtest.FULL_MAX_WORKERS）。突變（改回 8）⇒ 紅 | 4d0808a0 | |
| B-S3 | 修正：補 `_low_priority_flags`（Windows 等於 BELOW_NORMAL）、`in_supported_range`／`parse_prod_env`／`compare` 的題。突變 B06 ⇒ 紅 | f14ee6db | |
| B-S4 | 修正：per-commit 檔保留 `history`（先前每一輪的 started／finished／ok／failed／e2e_failed）；閘門仍以最新一輪放行，但回 `red_runs` 並在說明寫「先前紅過 N 次」。題：紅→綠重跑。突變（不保留）⇒ 紅 | f14ee6db | |
| B-O1～O3 | O1 修正：requirements-dev 直接宣告 `pytest>=8.0`（題 `test_pytest_is_declared_directly`，突變 ⇒ 紅）。O2 修正：`test_deploy_dashboard_local_only` 改經 `tests._routes.all_routes`；**另發現**這個檔單獨跑有 9 題 `ModuleNotFoundError: deploy_insights`（靠別的測試先把 backend/tools 放進 sys.path，全量裡才會過——順序相依），fixture 改為自己 `syspath_prepend`，單獨跑 10 綠。O3 修正：`check` 只讀主工作樹的 prod_env.json | 4d0808a0、f14ee6db | |

### D 確認（2026-09-26 03:58；對象：B 在本機 `wip/b-scope` 上的回覆 `3a62d617`，修正 `f14ee6db`、`4d0808a0`）

回覆欄在 b-scope 分支上，還沒進 origin；D 把確認寫在這裡，合併時不會與回覆欄的表格衝突。在 `63a47f4e` 上，相關 3 檔（`test_env_and_load_guards`、`test_modtest_full_results`、`test_requirements_cover_imports`）**52 passed**。

| # | D 確認 | 證據 |
|---|---|---|
| B-M1 | ✅ 關閉 | 直接呼叫 `cap_workers(e, 2)`：`-n 8`、`-n8`、`-n=8`、`--numprocesses=8`、`--numprocesses 8`、`-nauto`、`-n auto`、`-n logical`、`-n -1` 全部壓到 2，`-n 2` 不變。D 突變 BR5（`auto` 照傳）⇒ `test_cap_workers_every_spelling` 等 6 紅 |
| B-M2 | ✅ 關閉 | `project_env.py:150` 資料夾已存在就拒絕；D 突變 BR3（拿掉檢查）⇒ `test_rc_create_refuses_an_existing_folder` 紅 |
| B-M3 | ✅ 關閉 | `tree_state` 改用 `--untracked-files=normal`，`run_dirty` 開跑與結束各判一次；D 突變 BR1（改回 `=no`）⇒ `test_rc_untracked_file_makes_the_run_dirty` 紅；BR2（只看開跑）⇒ 3 紅。原本存活的 B07 這一類，現在由行為題守住 |
| B-S1 | ✅ 關閉 | D 突變 BR4（requirements-dev 拿掉 httpx2，原 B02 存活）⇒ `test_runtime_imports_of_test_fixtures_are_in_requirements` 紅 |
| B-S2 | ✅ 關閉 | `build_deploy_package.ps1:557` `Min($physCores, 4)` |
| B-S3、B-S4、B-O1～O3 | ✅ 接受 | 依回覆欄；D 抽查 B-S3（`_low_priority_flags`）與 B-O1（pytest 直接宣告）的題目都在，並包含在上面的 52 passed 裡 |

⇒ 本檔必修全部關閉。⚠ 這些修正與 D1b 選題（`AUDIT-D-B-D1b-scope.md`，必修 S-M1）在同一個分支上：**b-scope 在 S-M1 關閉之前不可以合回**，所以本檔的關閉要等那一包合回之後才在 origin 上生效。
