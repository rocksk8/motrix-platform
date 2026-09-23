# MOTRIX ERP — 跨機核對、拉檔與更新模式（§14／§15）

> 自 `MOTRIX-ERP-QUICK.md` 拆出（2026-09-23）。§ 編號沿用原編號，程式註解裡的「QUICK.md §N」依中樞檔的對照表找到本檔。
> 內容逐字搬移，未改寫；相對連結已改為自本目錄起算。

---

## §14 · 跨機核對與拉檔流程

> 背景與已知落差見 §0。目前完全靠人工複製，本章節是「核對時該看什麼、怎麼拉檔案」的清單，**不是自動化機制**——自動化推送是明確列為之後才考慮的項目（見章末）。

---

### §14.1 · 核對優先順序

依 2026-08-01 這次核對的實際經驗排序，越上面代表越容易漂移、越該優先看：

1. **`backend/db.py`（migrations）**——優先用「正式機 db 的 `sqlite_master` 實際結構」反推，不要只比對程式碼本身（程式碼可能也漏東西，這次 v32/v33 就是實例：功能檔案都在，唯獨 migration 遺失）
2. **`backend/routers/*.py`、`backend/helpers/*.py`**——新功能程式碼
3. **`frontend/pages/*.html`、`frontend/js/*.js`、`frontend/static/*.js`**
4. **`backend/*.ps1`**（部署/排程腳本，如 `setup_autostart_task.ps1`／`setup_heartbeat_task.ps1`）
5. **`backend/version_manifest.json`**——比對兩邊「最新一筆」的日期，誰比較新代表誰的紀錄比較完整

---

### §14.2 · 從正式機拉檔案回來的具體步驟

- **資料庫檔案**（`motrix_erp.db`）複製回來時**不要直接覆蓋**開發機正在用的檔案：先另存成 `motrix_erp_prod_YYYYMMDD.db` 之類的名稱，只用來讀取比對 schema/資料（例如 `PRAGMA table_info` / `sqlite_master`），確認要保留的內容後再手動決定是否取代開發機的檔案
- **純程式碼／文件檔案**：正式機有、這裡沒有的，直接複製過來；兩邊都有但內容不同的，人工比對（可用 PowerShell `Compare-Object` 或 `git diff --no-index`）決定保留哪一版，**不要自動二選一覆蓋**
- 核對完成後，依 §12 下方「維護規則」慣例補一筆 `version_manifest.json` + §12 摘要，並更新 §0 的「已知落差紀錄」表（狀態改為已補回，或新增剛發現的落差）

---

### §14.3 · 之後才考慮的方向

> ✅ **已實作半自動版本，見 §15**（2026-08-01j）：`build_deploy_package.ps1` + `apply_update.ps1`，方向是「開發機打包（git archive，強制先 commit）→ 人工複製 → 正式機套用（版本比對＋備份＋安全停服＋健康檢查＋失敗自動回滾）」。仍非全自動：套用前需操作者手動確認一次。
>
> ✅ **兩機 WinRM 網路直連已建立**（2026-09-08，見 §14.3b）：不用再靠人工把部署包複製到隨身碟/雲端硬碟——但**只用來讓開發機能對正式機下遠端指令／傳檔案，不是取代 §15 的部署安全機制**，`apply_update.ps1` 本身仍然要照原本方式在正式機執行（版本比對／備份／健康檢查／自動回滾一個都不能少）。

以下是還沒做、之後可以再評估的方向：

- 拉檔案回開發機（§14.2 方向，跟 §15 相反方向）目前仍是全人工，尚未有對應的半自動工具
- 部署流程全自動化（開發機一鍵打包→透過 WinRM 直接觸發正式機執行 `apply_update.ps1`，不需要人工介入複製或按 Enter 確認）——技術上現在已經有 WinRM 通道可以做到，但故意還沒做，因為 §15 的「套用前需操作者手動確認一次」是刻意保留的人工把關，避免半夜/誤觸發不小心把錯的版本套到正式機

---

### §14.3b · WinRM 網路直連設定（2026-09-08）

開發機（`hichan`，172.16.11.211）與正式機（`Motrix`，172.16.10.177）現在可以透過 WinRM 直接互相執行遠端指令，不需要再用隨身碟/雲端硬碟人工複製檔案。**用途僅限「輔助操作」**（傳檔案、遠端跑診斷指令、必要時直接呼叫 `apply_update.ps1`），不是要繞過 §15 既有的部署安全機制。

**兩邊各自的設定（一次性，已完成）：**

| 機器 | 設定內容 |
|------|---------|
| 兩邊都要 | `Enable-PSRemoting -Force -SkipNetworkProfileCheck`（需系統管理員權限，UAC 無法用指令繞過，一定要真人點「是」） |
| 開發機 | `Set-Item WSMan:\localhost\Client\TrustedHosts -Value "172.16.10.177" -Force`（信任正式機為遠端目標） |
| 正式機 | `New-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" -Name LocalAccountTokenFilterPolicy -PropertyType DWord -Value 1 -Force`（**工作群組環境必踩的坑**：本機系統管理員帳號遠端連線時 UAC 預設會拿到過濾後的權杖，導致需要提升權限的操作被拒絕，此登錄機值可以解除這個限制） |
| 正式機 | `Get-NetFirewallRule -DisplayGroup "Windows Remote Management" \| Set-NetFirewallRule -RemoteAddress Any`（**第二個坑**：Windows 內建的 WinRM 防火牆規則在 Public 設定檔下預設把遠端位址範圍限定成 `LocalSubnet`，即使兩機實際上在同一個實體網段，只要正式機自己的網卡設的是較窄的 `/24` 遮罩就會判定開發機「不算同子網路」而擋下——即使規則本身顯示 `Enabled: True` 也一樣會擋，因為問題出在遠端位址範圍不是啟用狀態，需要另外放寬） |

**使用方式（開發機執行）：**

```powershell
# 互動式遠端操作，像坐在正式機前面一樣（打 exit 離開）
Enter-PSSession -ComputerName 172.16.10.177 -Credential (Get-Credential -UserName "Motrix")

# 或一次性執行單一指令/腳本
$cred = Get-Credential -UserName "Motrix"
Invoke-Command -ComputerName 172.16.10.177 -Credential $cred -ScriptBlock { hostname }

# 免重複輸入密碼：先把密碼存成只有這台機器這個帳號能解開的加密檔案
Get-Credential -UserName "Motrix" | Export-Clixml -Path "$env:USERPROFILE\motrix_cred.xml"
# 之後用 Import-Clixml 讀回來當 -Credential 參數即可
```

**已知風險（刻意接受）**：正式機多了一個常駐的遠端執行入口（WinRM 服務＋開放的防火牆規則），若開發機帳密或這台機器本身被入侵，攻擊者可直接對正式機下遠端指令——這是持續性攻擊面，經使用者確認可接受這個取捨，換取部署效率。若未來要撤銷，正式機執行 `Disable-PSRemoting -Force` 並把上述防火牆規則改回 `LocalSubnet`／關閉即可還原。

---

### §14.3c · 本機部署儀表板（2026-09-08）

在 §14.3b 的 WinRM 通道上包了一層網頁 GUI，把「打包→推送→套用」跟「查看正式機狀態」跟「手動回滾」都變成按鈕點選，不用再手打一長串 PowerShell 指令。

**開關方式（2026-09-09 起）**：桌面捷徑「MOTRIX 部署儀表板」→ `backend/tools/deploy_dashboard_ctl.pyw`，一個 tkinter 小視窗，只有「開啟」「關閉」兩顆按鈕＋狀態燈（每 1.5 秒用 TCP 連 127.0.0.1:8765 判定，不靠任何會被系統語系影響的指令輸出）。開啟＝背景以 `pythonw.exe` 拉起 `deploy_dashboard.py`（無主控台視窗，輸出全進 `tools/deploy_dashboard_run.log`），起來後自動開瀏覽器；關閉＝二次確認後找 8765 的監聽者 `taskkill`，且**只殺 python 系列行程**，被別的程式佔用時寧可不動手也不誤殺。取代了原本的 `deploy_dashboard_start.bat`／`deploy_dashboard_stop.bat`（`91a80c8` 新增、2026-09-09 合併後刪除；改 Python GUI 順帶擺脫 .bat 檔不能寫中文的 codepage 限制，見 feedback_windows_locale_encoding_pitfall）。

**⚠️ 桌面捷徑一定要指向「真的」GUI 版 pythonw.exe（2026-09-11 修）**

桌面捷徑「MOTRIX 部署儀表板」原本指向
`AppData\Local\hermes\hermes-agent\venv\Scripts\pythonw.exe`，結果**每次開啟都會多跳
一個 CMD 主控台視窗**。根因不在這個專案的程式碼，而在那個 venv：

```
venv\Scripts\python.exe   45,568 bytes  SHA256 ADBF666C...
venv\Scripts\pythonw.exe  45,568 bytes  SHA256 ADBF666C...   ← 位元組完全相同
```

那是 **uv 建 venv 時放的 trampoline**，`pythonw.exe` 只是 `python.exe` 改個檔名，
仍然是 console 版——所以就算叫 pythonw 也會配一個主控台，`ctl` 再用
`sys.executable` 旁邊的 pythonw 去起 server 時同樣帶著主控台。
（`ctl` 的 `CREATE_NO_WINDOW` 擋不住，主控台是 trampoline 自己配的。）

**現在的設定**：捷徑 TargetPath 改成
`C:\Users\hichan\AppData\Local\Programs\Python\Python313\pythonw.exe`
（系統 Python 3.13，有真正的 GUI 版 pythonw，且 tkinter／fastapi／uvicorn／requests／
urllib3／pydantic 都齊全，實測儀表板六支唯讀端點在 3.13 下全部 200）。
Arguments 與 WorkingDirectory 維持不變。

**檢查方式**（換機器或重建 venv 後值得跑一次）：

```powershell
# 兩者 hash 相同 = 那個 pythonw 是假的，用它會跳主控台
(Get-FileHash "$venv\Scripts\python.exe").Hash -eq (Get-FileHash "$venv\Scripts\pythonw.exe").Hash

# 開起來之後確認沒有 conhost 掛在 python 底下
Get-CimInstance Win32_Process -Filter "Name='conhost.exe'" | ForEach-Object {
  $p = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.ParentProcessId)").Name
  if ($p -match 'python') { "有主控台：conhost $($_.ProcessId) <- $p" } }
```

**⚠️ 第二半：`deploy_dashboard.py` 的 subprocess 一律要帶 `CREATE_NO_WINDOW`**

把捷徑改成真正的 GUI `pythonw` 之後，使用者回報「不定期一直跳 CMD 的快速關閉
視窗」。那不是新缺陷，是**原本被那個常駐主控台蓋住的舊缺陷浮出來**：

- 主行程由 `pythonw` 啟動 → **自己沒有主控台**
- 每次呼叫 console 程式（`git.exe`、`powershell.exe`）而沒帶 `CREATE_NO_WINDOW`
  → Windows 就替那個子行程配一個新主控台 → 畫面上閃一下又關掉
- `/api/dev-status` 被前端 `setInterval(refreshDevStatus, 15000)` 每 15 秒輪詢，
  而它一次跑 **4 個 git**，所以閃得特別勤

`deploy_dashboard_ctl.pyw` 從一開始就有這個旗標，`deploy_dashboard.py` 則是
一個都沒有。已補齊 5 處（部署/回滾 job 的 Popen ×1、dev-status 的 git ×1、
`_dashboard_remote.ps1` 遠端呼叫 ×3）。

**驗證方式**（直接驗機制，不要靠數 conhost——conhost 的父行程是 `git.exe`
而不是伺服器本身，git 又立刻結束，數不到，會得到假綠燈；實測踩過）：

```python
# 由 pythonw 執行；子行程用 console 版 python.exe
PROBE = "import ctypes,sys; sys.exit(1 if ctypes.windll.kernel32.GetConsoleWindow() else 0)"
subprocess.run([PY, "-c", PROBE]).returncode                      # → 1（有主控台，會閃）
subprocess.run([PY, "-c", PROBE], creationflags=0x08000000).returncode  # → 0（沒有）
```

也可以照舊直接手動啟動：

```
cd backend
python tools/deploy_dashboard.py
```
瀏覽器打開 `http://127.0.0.1:8765`。只綁 loopback，不會被 LAN 上其他機器連到。密碼只在單次部署/回滾請求的生命週期內存在（寫進 `_dashboard_remote.ps1` 子行程的 STDIN 後立即捨棄），不落地、不進 log、不進 `deploy_dashboard_history.json`（只記錄時間/動作/成功與否，不記密碼）。

- 部署／回滾都是**兩段式確認**：填完資訊按第一次按鈕只會跳出摘要卡片，要再按一次「確認套用」/「確認回滾」才真的執行——這是網頁版的人工安全關卡，等價於 `apply_update.ps1`/`rollback_update.ps1` 原本的 `Read-Host "(y/N)"`（WinRM 遠端執行不支援事後對正在跑的遠端 script block 注入互動輸入，遠端呼叫本身帶 `-Yes` 跳過腳本自己的提示，詳見 §12 2026-09-08 條目）。
- 手動回滾：按「查詢可回滾的快照」（需帳密，因為快照清單只存在正式機上）→ 選一個時間戳 → 兩段式確認 → 執行 `rollback_update.ps1`（新檔案，照抄 `apply_update.ps1` 健康檢查失敗時的自動回滾邏輯，差別是操作者主動觸發，用於「健康檢查本身通過、但實際操作發現功能邏輯不對」這種 `apply_update.ps1` 自己不會自動回滾的情境）。
- ~~目前還沒有真正跑過一次完整的部署/回滾~~（**2026-09-10 更正**：截至 09-09 22:16 已累積 **20 次**真實部署嘗試、其中 6 次失敗，逐次因果鏈見 `WEEKLY-AUDIT-2026-09-07_2026-09-10.md` §C-1。⚠️ **但 09-10 那次真正上線的部署沒有走這個儀表板**——`deploy_dashboard_history.json` 裡查不到、`deploy_logs/` 也沒有對應的 build log，代表是直接執行腳本。用儀表板以外的方式部署會同時失去「打包測試關卡」與「歷史紀錄」兩層保障。）
- **已修復一個第一次真實嘗試就撞到的 bug**：`_ps_cmd()` 原本把參數「名稱」（`-Action`／`-Username`／`-PackagePath`）跟「值」混在同一個 list 裡統一加單引號跳脫，導致 `-Action` 被包成 `'-Action'` 純字串常值，PowerShell 認不出是參數旗標，改去綁定成 `_dashboard_remote.ps1` 第一個位置參數的值，撞上 `ValidateSet` 驗證失敗（`Cannot validate argument on parameter 'Action'`）。改成 `named_args: dict` 的介面——參數名原樣輸出（不加引號，因為是我自己寫死的固定字串）、只有值需要跳脫——並用 dry-run 對照 `ValidateSet` 的假腳本實測過確認修復（含值本身含單引號的情況）。**安全性複查那次沒抓到這個問題**：因為當時只推演了「單引號跳脫本身有沒有正確」，沒有實際跑一次生成的完整指令字串驗證參數綁定，這次靠使用者實際點擊部署按鈕才抓到——教訓是「跳脫邏輯正確」跟「整條指令實際能跑」是兩件不同的事，改動這類組指令字串的程式碼一定要跑一次真實 dry-run，不能只靠推演。

---

### §14.3d · 兩邊同時有人／有 AI session 在動時的交接協定（2026-09-10）

> 2026-09-10 首次遇到「開發機與正式機同時各有一個 Claude session 在改同一個功能
> （WebAuthn）」，開發機這邊已經打包好正要部署才被叫停（見 §0 落差表同日條目）。
> §0 那張表長期記錄的都是「事後才發現」，這次是即時發現——差別只在有人剛好在看。
> 以下把它變成不依賴運氣的流程。

**原則：序列化，不要並行。** 同一時間只有一邊在改程式碼。理由很實際——正式機不是
git repo，兩邊各改各的之後沒有任何工具能自動合併，而 `apply_update.ps1` Step 3 是
整個覆蓋，先部署的那邊會無聲無息蓋掉另一邊。

**交接檔（由「正在動的那一邊」在收工時產出）**

固定路徑，刻意放在部署會覆蓋的範圍之外，才不會被 `apply_update.ps1` 蓋掉：

```
正式機：C:\Users\Motrix\Desktop\AGENT-HANDOFF\YYYYMMDD_HHMM_prod.md
開發機：C:\Users\hichan\Desktop\MOTRIX-ERP\..\AGENT-HANDOFF\YYYYMMDD_HHMM_dev.md
```

開發機這邊用 `backend/tools/check_prod_drift.ps1` 把正式機的交接檔拉回來讀
（同一條 WinRM 通道，`Copy-Item -FromSession`）。

**交接檔必須包含這 7 項**（少一項下一棒就得自己去翻，等於沒交接）：

| # | 欄位 | 為什麼需要 |
|---|------|-----------|
| 1 | 改了哪些檔案（完整路徑清單） | 下一棒要知道自己的改動會不會撞到 |
| 2 | 每個檔案改了什麼、為什麼 | 決定該合併還是該丟棄 |
| 3 | 有沒有動資料庫（schema／資料列） | migration 沒進 `db.py` 的話，兩機 schema 會分岔（§0 v32/v33 就是這樣） |
| 4 | 有沒有改設定（`system_settings` 的 key 與**實際值**） | 例如 `webauthn_rp_id`／`webauthn_origin`，這些不在 git 裡，重建環境時會整個消失 |
| 5 | 有沒有重啟服務／改排程工作 | 影響下一棒判斷當下狀態 |
| 6 | 有沒有進 git（有的話附 commit hash） | 沒進 git 的東西下次部署就會被覆蓋掉 |
| 7 | 未完成、待接手的事 | 半成品最容易被下一棒當成完成品 |

**接手方的固定動作**（不要只信交接檔）：

1. 讀交接檔
2. 跑 `check_prod_drift.ps1` —— 交接檔寫的是「對方以為自己改了什麼」，drift 檢查
   看的是「實際上什麼不一樣」。兩者對不上的部分才是真正的風險
3. 把有價值、還沒進 git 的改動依 §14.2 拉回開發機合併進 git
4. 確認 §0 落差表已更新，再開始自己的工作

---

### §14.3e · 正式機漂移檢查（`check_prod_drift.ps1`，2026-09-10）

正式機不是 git repo，任何人直接在 `C:\Users\Motrix\Desktop\V9.0` 底下改檔案，開發機
完全看不到；下次 `apply_update.ps1` 一跑，Step 3 整個覆蓋，那些改動就無聲消失。過去
只能靠人記得講——而 §0 那張表本身就是「人不會記得」的證據。

作法：正式機的 `/api/system/deployed-version` 會回報它跑在哪個 commit，本工具用
`git archive` 還原該 commit 算 SHA256，再透過 WinRM 對正式機同一批路徑算一次，逐檔
比對。**全程唯讀**（遠端只跑 `Get-ChildItem`／`Get-FileHash`，不寫入、不重啟）。

```powershell
"密碼" | powershell -ExecutionPolicy Bypass -File backend\tools\check_prod_drift.ps1
"密碼" | powershell -ExecutionPolicy Bypass -File backend\tools\check_prod_drift.ps1 -Commit 2471747
```

輸出分三類：**內容被改過**（下次部署會覆蓋掉）／**只有正式機有**（新增但沒進 git）／
**正式機缺少**（被刪或套用不完整）。比對範圍只含 `backend/`＋`frontend/`，排除 db、
log、上傳檔、快照、憑證、per-machine 設定檔等執行期產物。

**踩過的坑**：排除規則必須在**遠端**就套用，不能只在本機端過濾結果——正式機的
`backend\logs\server.log` 被執行中的 uvicorn 開著，`Get-FileHash` 會拋 FileReadError
讓整個 `Invoke-Command` 中止；另外每個檔案要個別 try/catch，任何一個讀不到都不該
讓整次掃描報廢。

---

### §14.4 · 選型資料庫雙機內容核對（API 版，2026-08-10）

> §15 只管程式碼／schema，**選型資料庫的實際內容**（switch/monitor/access/gateway/netarch/env
> 六大類的 scenarios/categories/fit/products 這些 row）不在 schema 裡、migration 也管不到——
> 過去只能靠翻各支 `sync_YYYY-MM-DD_xxx.py` 的 docstring 回憶／人工核對兩機是否同步，這就是
> 2026-08-10 這次落差被發現的原因。現在改用兩台機器都已開通的 API（兩邊 LAN 可互通，見 §1
> 區網位址）直接比對，取代人工回憶。

**前置需求**：兩台機器都要有 `claude` 自動化帳號（`create_claude_account.py`，role=admin＋
`*_guide_edit` 模組旗標，最小權限）且核發過 session token：

```
python backend/issue_claude_session.py     # 於該機器 backend/ 目錄下執行，印出 token
```

token 不共用、各機器獨立（sessions 表各自是獨立 SQLite 檔案），效期比照一般登入 30 天，過期
重跑上面這行即可（冪等，會自動清掉該帳號舊 session 再核發新的）。

**核對**：

```
cd backend/tools
python check_guide_sync.py                            # 核對全部 6 大類
python check_guide_sync.py --category switch access    # 只核對指定類別
```

token 設定於 `backend/tools/.guide_sync_config.json`（**不進 git**，`.gitignore` 已排除，格式見
腳本內 `_CONFIG_EXAMPLE`）；依自然鍵（多數是 `code`，跨表關聯用 `scenario_code`/`category_code`，
`netarch_products` 例外用 `generation_id` 需先換算成 `(family_code, gen_name)` 再比對，因為那是
機器本地自增數字、兩機不保證相同）逐一比對每個端點，印出「哪些 key 只有一邊有」。

**已知限制**：這支工具只讀，不會自動修補落差；發現落差後仍要判斷是「單純缺資料」（直接用同帳號
對缺的那一機 POST 補上，見下方）還是「資料被取代/刪除」（一邊新增了更細的項目、同時刪掉舊的
籠統項目，這種情況另一邊要手動決定是否也要刪，不能自動判斷）。2026-08-10 這次首次使用就意外
挖到 `routers/netarch_guide.py` 的既有 bug（見 §12 同日條目）——透過 API 實際寫入資料是比對過
docstring 更可靠的驗證方式，往後新增選型資料庫內容建議優先用這個流程，而不是直接寫一次性
sqlite 腳本後假設「兩機遲早會一致」。

---

## §15 · 更新模式（測試機 → 正式機，半自動，2026-08-01）

> 目的：把 §14 的手動複製部署，收斂成有前後安全檢查、可重複執行的流程。**範圍只含程式碼／schema，絕不觸碰正式機業務資料**（quotations/customers 等 data_json 與熱路徑欄位一律不動）；db migration 只改表結構，不動既有資料列。觸發方式是半自動——一鍵執行，但套用前仍需操作者手動確認一次，不做無人值守全自動。

---

### §15.1 · 兩支腳本

| 腳本 | 執行位置 | 用途 |
|------|---------|------|
| `backend/tools/build_deploy_package.ps1` | **開發機** | 打包目前已 commit 的 `backend/`＋`frontend/`＋根目錄文件成部署包 |
| `backend/tools/apply_update.ps1` | **正式機** | 套用部署包，含備份／安全停服／健康檢查／失敗自動回滾 |

---

### §15.2 · 打包（開發機）

```
powershell -ExecutionPolicy Bypass -File backend\tools\build_deploy_package.ps1
```

- **強制 `git status` 乾淨**才允許打包，未 commit 的變更會被擋下——解決 §0 已知落差第 3 筆「來源不可靠」的問題：拿去正式機套用的東西，永遠等於 git 上看得到的東西
- 用 `git archive HEAD` 匯出，只含已 commit 的內容
- 產出 `deploy_packages/<timestamp>_<commit短碼>/`，內含 `deploy_manifest.json`（commit、分支、`version_manifest.json` 最後一筆）
- 完成後需**手動複製**整個資料夾到正式機（隨身碟／網路芳鄰／雲端硬碟皆可，兩機間目前無直連機制）

---

### §15.3 · 套用（正式機）

```
powershell -ExecutionPolicy Bypass -File "C:\Users\Motrix\Desktop\V9.0\backend\tools\apply_update.ps1" -PackagePath "<複製過去的絕對路徑>"
```

**建議一律用絕對路徑**（2026-09-08 起，見 §12 同日條目）：`-File` 用絕對路徑不影響腳本行為（腳本內部本來就用 `$PSScriptRoot` 反推專案根目錄，跟目前所在目錄無關），純粹是少一步 `cd`、避免在錯誤目錄下執行時「找不到檔案」；`-PackagePath` 本來就該給絕對路徑。兩者都用雙引號包起來，避免路徑含空白時出錯。

| 階段 | 動作 |
|------|------|
| 身分守門 | 確認腳本執行路徑就是正式機路徑，否則中止 |
| 套用前 | 版本比對（commit 相同視為重複套用，需 `-Force` 才強制）；記錄套用前健康狀態；**db 快照**至 `backend/db_backups/pre_update_<timestamp>/`；**Migration 乾跑驗證**（2026-08-01m 新增，見下方說明）；**程式碼回滾快照**至 `backend/rollback_snapshots/<timestamp>/`（保留最新 5 份）；印出摘要，等待操作者輸入 `y` 確認 |
| 停服 | 依 port 666 監聽者 PID／`uvicorn*main:app` commandline 逐一 kill；**不自己啟動新 uvicorn**，改讓既有 `MOTRIX ERP Server Autostart` 排程的 crash-restart 迴圈（§1.1）5 秒內自動接手重啟，避免搶 port |
| 套用 | robocopy 把套件的 `backend/`＋`frontend/`＋根目錄文件覆蓋過去；**只加不改既有多餘檔案，絕不用 `/MIR`**，加上 `/XD`／`/XF` 排除 db／uploads／報價單PDF／logs／設定檔等，即使套件不小心含這些也不會覆蓋 |
| 依賴安裝 | `python -m pip install -q -r backend\requirements.txt`（2026-09-07 新增，見下方說明）；失敗只警告不中止，靠下一步健康檢查當最終安全網 |
| 套用後 | 輪詢 `GET /api/ping` 最多 30 秒＋檢查 `logs/server.log` tail 200 行、**只看「最後一次成功啟動（`Uvicorn running on`）」之後**有無 traceback/ERROR（2026-08-02a 修正，避免把重啟迴圈重試階段已自癒的暫時性錯誤誤判成失敗，見下方說明）；成功→更新 `backend/.deployed_commit.json`；**失敗→自動回滾**（用剛才的程式碼快照復原＋重新停服讓迴圈拉起舊版＋再次確認健康），並印出 db／程式碼快照路徑供人工進一步排查 |

`-Force`：版本比對沒過仍要套用時使用。`-Yes`：跳過互動確認（僅供自動化測試，正常人工執行不要加）。`-CheckOnly`（2026-09-08 新增）：只對目前正在跑的伺服器打一次 `/api/ping`、印出結果就結束，不需要 `-PackagePath`，也不做備份／停服／複製程式碼／pip install／回滾等任何動作——專門用來驗證「健康檢查機制本身」對不對，不用每次都跑一次完整的部署+回滾循環（見下方 Runspace 崩潰條目的教訓）：
```
powershell -ExecutionPolicy Bypass -File "C:\Users\Motrix\Desktop\V9.0\backend\tools\apply_update.ps1" -CheckOnly
```

**Migration 乾跑驗證**（2026-08-01m）：正式庫過去是「第一個試跑新 migration 的地方」——伺服器套新程式碼重啟後 `init_db()` 立刻對正式庫跑 migration，若寫壞了，schema 已經被改壞才被套用後健康檢查發現，「自動回滾」雖然會把 db 整檔換回套用前快照（安全），但仍會遺失套用後到偵測失敗這段時間內產生的新業務資料。現在改成：db 快照做完後，先把快照複製一份到系統 temp 目錄，用**新套件裡的** `db.py`（`init_db(path)` 本來就接受任意路徑，只操作傳入的檔案）在這份副本上先跑一次；失敗就直接中止，不進入停服／複製程式碼／回滾快照等後續步驟，**正式庫全程不受觸碰**。

**健康檢查誤判自動回滾修正**（2026-08-02a）：commit `484c1b4` 第一次在正式機真實套用時，Step 2 停服後沒等 port 666 真正釋放，既有 crash-restart 迴圈搶著重新綁定撞到 `[Errno 10048]` 位址已被使用，重試 2 次後自行成功（迴圈設計上本來就會自癒），但 Step 4 健康檢查掃 log tail 80 行沒有分辨這些錯誤是否已被後續成功啟動蓋過去，誤判成更新失敗觸發回滾（回滾本身正常運作，正式機沒有受到實際影響）。已修正：Step 2 停服後新增主動輪詢確認 port 真正釋放；Step 4 log 掃描只看「最後一次成功啟動」之後的內容。

**缺套件導致真實部署失敗＋新增 pip install 步驟**（2026-09-07）：套用當天累積 12 個 commit 的部署包時，套用後健康檢查真的失敗（`healthy=False`，log 錯誤筆數=9），根因是 `ModuleNotFoundError: No module named 'pyotp'`——`requirements.txt` 早就正確列了新套件，但腳本從頭到尾只複製程式碼檔案，從未執行 `pip install`，正式機環境沒裝過。這次不是誤判，是腳本流程本身真的少了一步；已在「套用新程式碼」與「健康檢查」之間新增 `pip install -r requirements.txt`（詳見 §12 同日條目與 §15.3 表格），步驟數改為 6 步。

**HTTPS 健康檢查 Runspace 崩潰，造成誤判自動回滾**（2026-09-08）：正式機切換 HTTPS 後第一次真實套用，健康檢查連續兩次回報 `healthy=False, log 錯誤筆數=0` 觸發回滾，但 `server.log` 證明新程式碼其實正常啟動成功。根因：`[System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }` 用 PowerShell 指令碼區塊當委派方法，.NET 在 TLS handshake 階段從背景執行緒呼叫它，該執行緒沒有 PowerShell Runspace 可執行指令碼，丟出的例外被健康檢查迴圈的 `catch {}` 整個吞掉、完全不留痕跡。已改用 Windows 內建原生執行檔 `curl.exe -k`（不經過 .NET `ServicePointManager`，無 Runspace 問題）取代 HTTPS 情境下的 `Invoke-WebRequest`，新增 `Test-Ping` 共用函式；HTTP 情境維持不變。**這批事故也暴露一個流程性問題**：修 `apply_update.ps1` 本身的 bug，過去只能靠「真的在正式機跑一次完整部署+回滾」來驗證對不對——同一天因此被迫觸發了兩次不必要的停服/回滾。這正是新增 `-CheckOnly` 模式的動機。

---

### §15.3b · 正式機輔助工具的分工（2026-09-08 新增）

正式機除了 `V9.0`（實際運作目錄，混著程式碼＋db＋uploads＋logs）之外，可能還有以下輔助工具，**用途要分清楚，不要混用**：

| 工具 | 定位 | 可以做什麼 | 不能做什麼 |
|------|------|-----------|-----------|
| `motrix-erp-repo`（唯讀 git clone，建議放在跟 `V9.0` 平行的位置，例如 `C:\Users\Motrix\Desktop\motrix-erp-repo`） | 緊急單檔案取件用 | 遇到部署工具腳本本身（`apply_update.ps1`／`https_setup.ps1` 等）需要緊急修復、又還沒走完整打包流程時，`git pull` 更新這份 clone，再手動複製「單一檔案」到 `V9.0` 對應位置 | **不要**拿來部署應用程式碼（`routers/`／`frontend/` 等）——應用程式碼永遠只走 `build_deploy_package.ps1`＋`apply_update.ps1` 這套有 pytest 全過關卡＋備份＋健康檢查＋自動回滾保護的流程，直接 `git pull` 覆蓋 `V9.0` 會繞過所有這些保護 |
| 正式機上的 Claude Code session | 套用操作的執行者 | 之後要套用更新，直接請正式機本地的 Claude 執行 `apply_update.ps1`／查 log／驗證健康狀態，不要再讓開發機這邊的人工把指令貼到聊天視窗、請使用者手動轉貼到正式機——2026-09-08 那次事故裡，三次操作型失誤（漏打 `powershell` 前綴、目錄不對、多行 here-string 貼壞）全部出在「人工在兩台機器間轉貼指令」這一步，跟程式邏輯完全無關 | 不會改變 `apply_update.ps1` 本身的安全機制，仍然要照 §15.3 的方式帶 `-PackagePath` 執行，不要圖方便繞過版本比對／備份 |

---

### §15.4 · 已知限制

- 兩機間的部署包傳輸仍是人工複製，沒有網路直連（WinRM 等，見 §14.3）
- 正式機沒有 git，版本比對只能靠 `deploy_manifest.json` 記的 commit 做「是否重複套用」的相等比對，無法判斷新舊先後（先後順序由操作者自行確認）
- `apply_update.ps1` 已在正式機做過兩次真實套用：第一次（2026-08-02，commit `484c1b4`）健康檢查誤判觸發自動回滾，回滾機制運作正常、正式機無實際影響，誤判根因已修復（見上方說明與 §12 2026-08-02a）；第二次（2026-08-03，commit `259ad84`，業務開發 CRM 逾期警示功能）**套用成功、健康檢查通過、無回滾**，修正後的腳本已在正式機實地驗證過；`build_deploy_package.ps1` 已在開發機多次實際打包成功（見 §12 2026-08-01k/l/m）
