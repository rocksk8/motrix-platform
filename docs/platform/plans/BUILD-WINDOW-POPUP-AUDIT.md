# 背景測試彈視窗：建包／階段測試工具鏈盤點（d7；2026-10-02；唯讀盤點，未改任何程式）

## 0. 結論先行
- **Playwright 一律 headless**：`conftest.py` 的 3 個 `chromium.launch()`（1805、1951＋fresh 模式）與兩個測試檔的 `p.chromium.launch()` 都沒帶 `headless=False`／`slow_mo`；全 repo 無 `--headed`、`PWDEBUG`、`webbrowser`／`os.startfile`（唯一的 `webbrowser.open` 在手動執行的 `scripts/setup_google_calendar_oauth.py`，不在測試鏈）。測試伺服器是 **行程內 uvicorn 執行緒**（`_start_uvicorn`），不起子行程。
- **工具鏈本身沒有 `CREATE_NO_WINDOW`**：`build_test_reuse.py`、`failfast.py`、`fail_stream.py`、`flaky_retry.py`、`modtest.py`、`build_preflight.py`（powershell）、`core_only_rc.py` 等的 `subprocess.run/Popen`（git、pip freeze、pytest、taskkill、powershell）**都沒帶 `creationflags`**；只有 `deploy_dashboard.py`／`deploy_insights.py` 有。另有 **310 個測試檔**用 `subprocess`，只有 1 檔（斷言 creationflags 的那題）提到 creationflags。
- 這些呼叫**是否真的彈窗，取決於父行程有沒有主控台**：父行程有（可見或無視窗的主控台）⇒ 子行程共用，不彈；父行程沒有主控台（例如以 `DETACHED_PROCESS`、排程、GUI 程式或某些背景啟動方式起 pytest）⇒ **每個 console 子行程（git／python／powershell／taskkill）各開一個新主控台視窗**；本機預設終端機是 Windows Terminal，所以會是一個個「Terminal」視窗。我在 Claude Code 的 Bash 工具下實測：該行程的 `GetConsoleWindow()`＝0（無視窗主控台）、子行程也是 0 ⇒ **這個啟動方式不會彈**。所以「使用者看到的彈窗」要看是從哪種方式啟動的——**先量再改**（見 §2）。
- 產品端：`helpers/startup.py` 的 Edge PDF 子行程（`msedge --headless`，GUI 程式，無主控台）只帶 `BELOW_NORMAL`，沒帶 `CREATE_NO_WINDOW`；`--headless` 下不該有視窗，但沒有保險。
- ps1 側：`build_deploy_package.ps1` 在使用者的可見主控台執行，自己不彈新視窗；`apply_*`／`rollback_update.ps1` 的 `Start-Process cmd.exe` 都已 `-WindowStyle Hidden`、`-NoNewWindow`。

## 1. 清單（可能彈窗的呼叫，依風險排序；「父行程無主控台」時才會彈）
| # | 位置 | 呼叫 | 現況 | 修法 |
|---|---|---|---|---|
| 1 | `tools/platform/flaky_retry.py:127,133` | `Popen([...pytest...])`、`taskkill /T /F` | 無 creationflags | 加 `CREATE_NO_WINDOW`（Popen 與 taskkill 都加） |
| 2 | `backend/tools/build_test_reuse.py:56,62,281,420` | git、`pip freeze`、**run-stage 內 `subprocess.run(cmd)`（跑 pytest）**、fingerprint | 無 | 同上；run-stage 那個要保留 stdout 轉送，只加旗標 |
| 3 | `tools/platform/failfast.py:126`、`fail_stream.py:69`、`modtest.py:71,93,101`、`core_bump.py:114`、`core_only_rc.py:48,212,279`、`build_preflight.py:36`（powershell）、`drill_module_apply.py:73,178,311`（powershell）、`final_drill.py:499,524`（uvicorn 子行程） | git／powershell／python | 無 | 統一用一個小 helper（見 §3） |
| 4 | 310 個測試檔的 `subprocess.*`（git、python、powershell、ps1 腳本） | 各自呼叫 | 無 | **不要逐檔改**；conftest 在 Windows 對 `subprocess.Popen` 預設補 `creationflags |= CREATE_NO_WINDOW`（呼叫端自己給了 creationflags 就不動），一處涵蓋所有測試與 xdist worker（worker 各自載入 conftest） |
| 5 | `backend/helpers/startup.py` `run_edge_pdf`／`_edge_creationflags` | `msedge --headless --print-to-pdf` | 只有 `BELOW_NORMAL`（0x4000） | 追加 `CREATE_NO_WINDOW`（0x08000000）；測試 `test_approval_no_freeze` 現在斷言 creationflags==0x4000，要一併改成含兩個旗標 |
| 6 | `build_deploy_package.ps1` 的 `& $pyExe …` | 在可見主控台 | 不彈 | 不改；若要從工作排程器／背景跑建包，請以 `-WindowStyle Hidden` 啟動 powershell |

## 2. 先量再改：`tools/platform/window_probe.py`（新增，唯讀）
每 100 ms 列舉可見最上層視窗，新出現者記 hwnd／類別／標題／父行程鏈；Windows Terminal 會把新主控台掛在自己名下，所以另外記「1.5 秒內剛啟動的行程（名稱←父行程）」歸因。彙總直接給 `新主控台（疑：git.exe←python.exe）  次數`。
- 正對照（已做）：以 `CREATE_NO_WINDOW` 啟動 `cmd` ⇒ 不記；以 `CREATE_NEW_CONSOLE` 啟動 `git` ⇒ 記到 1 個 `CASCADIA_HOSTING_WINDOW_CLASS`、歸因 `git.exe←python.exe`。
- 用法：背景測試開跑前另開終端機 `python tools/platform/window_probe.py --seconds 900 --out probe.jsonl`，跑完看彙總。**請使用者（或主持）在「會彈窗」的那種啟動方式下跑一次**，彙總就直接指出該改哪一行。

## 3. 建議修法（第 33 班；全部可獨立驗證）
1. `tools/platform/_nowindow.py`：`NO_WINDOW = 0x08000000 if os.name == "nt" else 0`；`def popen_kw(**kw)`：補 `creationflags`（保留呼叫端既有旗標，例如 BELOW_NORMAL 以 `|` 合併）。#1～#3 都改用它。
2. conftest（根與 `backend/conftest.py`）：Windows 下對 `subprocess.Popen.__init__` 補預設 `CREATE_NO_WINDOW`（只在呼叫端沒給 creationflags 時；不影響 `CREATE_NEW_CONSOLE` 等刻意用法；`DETACHED_PROCESS` 與其互斥，須跳過）。
3. `helpers/startup.py`：Edge 旗標合併 `CREATE_NO_WINDOW`，並改對應的單一測試。
4. 守門題（靜態）：`tools/platform/*.py` 與 `backend/tools/build_test_reuse.py` 內的 `subprocess.run/Popen/check_output` 呼叫必須帶 `creationflags` 或走 `_nowindow.popen_kw`（AST 掃描；附正對照：植入一個沒帶旗標的呼叫必須被抓）。
5. 驗證：以 window_probe 在「會彈」的啟動方式下，修前記到 N 個、修後 0 個；pytest 全綠不應受影響（`CREATE_NO_WINDOW` 不改 stdout/stderr 管線行為，但 **`DETACHED_PROCESS` 不可同時帶**，否則 CreateProcess 失敗）。
## 4. 限制
- 這是**靜態盤點＋工具**；我沒有重現使用者的彈窗（從 Claude Code Bash 工具啟動時不彈），所以哪一類呼叫是真兇**未確定**，不要在量測前就大改。
- 全 repo 310 個測試檔的 subprocess 呼叫只抽樣檢視，未逐一審。
