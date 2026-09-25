# 稽核：§9c ②模組授權 ③管理者啟停（X 稽核，2026-09-25）

> 依 CORE-SPEC §9d、PLAYBOOK §E。稽核者 X 沒有參與這批程式。
> 對象：原作者 A，已合回 platform。commit `645923c7`（主體）、`7dc74ffd`（e2e）、`1ddd288d`（MODULE-GUIDE §5）、`df2381a6`（夾具還原／golden）、`c45d6227`（snapshot 守門題）。
> 基準：platform `507a76ea`。稽核在 detached worktree `D:\MOTRIX-PLATFORM-AUD` 進行，產品程式碼一行都沒改（突變都已還原，`git status` 乾淨）。
> 分級：**必修**（不修不能關）／**建議**／**觀察**。關閉規則：被稽核者回覆後，由 X 確認才關。
> 路徑前綴 `backend/`。`LD`＝`core/loader.py`、`RG`＝`core/registry.py`、`LIC`＝`helpers/licensing.py`、`MS`＝`helpers/module_switches.py`、`SYS`＝`routers/system.py`、`SB`＝`frontend/static/sidebar.js`（repo 根目錄起算）、`TMS`＝`tests/platform/test_module_selection.py`。
> 重現環境：`D:\MOTRIX-PLATFORM\.venv`（Python 3.13.3）。pytest 一律帶 `--basetemp=%TEMP%\motrix-pytest-AUD-adhoc`，並設 `PYTHONDONTWRITEBYTECODE=1`（原因見 C-5）。

## 0. 結論

- 主流程成立：未授權與停用都不 import 模組，端點 404，資料不動；優先順序是「未授權 ＞ 停用」；切換開關後要重啟才生效；頁面沒有重啟按鈕。X 在裸行程另外重現了一次（§3）。
- **必修 3 項**：
  1. A-1：讀不到停用清單時當成「沒有停用任何模組」，管理者停用的模組會在下次重啟時默默回來（STATES-PLATFORM P-SW-05，platform 上仍未修）。
  2. A-2：§9c 的守門與 e2e 綁死 `tender_radar`。拿掉這個模組（等於 `product/core-only.json` 這個產品）後有 **7 題轉紅**，違反 MODULE-GUIDE §7 與 PLAYBOOK §C-6。
  3. A-3：規格要求授權檢查沒有啟用時，狀態要標「授權檢查未啟用」。目前這句訊息在載入器裡被丟掉，任何畫面都看不到。
- 建議 4 項、觀察 6 項。
- 驗證：`TMS`＋`tests/platform/test_core_loader.py`＋`tests/test_e2e_module_settings_2026_09_25.py`，**40 passed**（e2e 需要 C-5 的環境變通）。

## 1. 逐項驗收（CORE-SPEC §9c ②③、MODULE-GUIDE §5「選配」）

| 規格 | 驗收 | 證據 |
|---|---|---|
| ② 沒有授權 ⇒ 載入器不載入，並列出原因 | ✅ | LD:81-87。X 在裸行程重現：開關打開、金鑰只含 `some_other` ⇒ `('unlicensed', '未授權：授權金鑰未包含此模組（tender_radar）')`，`modules.tender_radar` 不在 `sys.modules`。開關打開、用真的 `verify_license`（worktree 沒有 license.key）⇒ `未授權：這台機器尚未安裝授權金鑰…`，同樣不 import |
| 授權單位是模組的 `license_key`，預設等於資料夾名，`*` 表示全開 | ✅（有一個型別漏洞，見 B-2） | LIC:651-661；`TMS::test_module_licensed` 8 組 |
| 授權檢查沒有啟用 ⇒ 一律可載入，**狀態標「授權檢查未啟用」** | ❌ 後半沒做到 | 見 A-3 |
| ③ 關閉 ⇒ 路由不掛 | ✅（失敗路徑例外，見 A-1） | main.py:694-696 只掛 `registry.loaded()`；子行程 `child_module_gate.py:50-51` 驗到 404 |
| ③ 關閉 ⇒ 排程不跑 | ✅（沒有測試，見 B-3） | main.py:604-606 只跑 `loaded()` 的 schedulers。X 在裸行程重現：停用 ⇒ `schedulers: 0`；正對照（啟用）⇒ 呼叫 1 次 |
| ③ 關閉 ⇒ 選單不出現 | ✅（只限有資料夾的模組，見 C-1） | SB:1155-1172；e2e `test_sidebar_hides_entries_of_unloaded_modules`（含正對照） |
| ③ 資料保留 | ✅ | 子行程在 3 種狀態下資料列數都不變（`child_module_gate.py:63-68`） |
| 優先順序：不在包內 ＞ 未授權 ＞ 停用 | ✅ | LD:81-91；子行程 `both` ⇒ `unlicensed` |
| 重啟後生效；分開顯示目前狀態與重啟後狀態；頁面不提供重啟 | ✅ | SYS:714-727（`afterRestart`／`pendingRestart`）；`TMS::test_toggle_is_pending_until_restart`；e2e 第 1 題；`TMS::test_page_and_sidebar_wiring` |
| 未授權或載入失敗不能切換 | ✅ | SYS:750-752 回 400；`TMS::test_unlicensed_cannot_be_toggled` |
| 權限：只有 superadmin 能切換；選單 API 登入即可 | ✅ | `TMS::test_toggle_permissions_and_unknown` |
| 啟停守門：「關閉後…；**開回來後恢復**」 | ⚠ 只驗了一個方向 | 見 B-4 |
| 每一種產品設定檔都要通過該組合的測試 | ❌ core-only 過不了 | 見 A-2 |

## 2. 發現

### 必修

**A-1　讀不到停用清單 ⇒ 當成沒有停用 ⇒ 被停用的模組在重啟後默默回來**
- 位置：MS:43-45（`sqlite3.Error` ⇒ `frozenset()`）、MS:50-52（內容解析不了 ⇒ `frozenset()`）；main.py:40-41 把結果直接交給載入器。
- 為什麼是必修：
  - §9c③ 的驗收是「關閉 ⇒ 端點回 404」，而這條失敗路徑會把管理者的決定反過來。
  - 反轉之後只留下一行 WARNING。模組管理頁顯示「啟用」，看起來和管理者從來沒關過一樣。STATES-PLATFORM 把它列為「高、缺守門」。
  - 修法已經設計好（STATES-PLATFORM §9.2：改用上次成功讀到的快取；沒有快取時全部不載入），但只在分支 `wip/a-platform-states`（`55f3c8b2`），**platform 上沒有**。
- X 的重現（腳本在 scratchpad，§3 列出指令）：

  | 觸發方式 | 讀到的結果 | 耗時 | 載入器的結果 |
  |---|---|---|---|
  | 一般 journal 的庫，另一條連線 `BEGIN EXCLUSIVE` | `frozenset()` | 8.0s | `tender_radar: loaded` |
  | **WAL 庫**，另一條連線 `PRAGMA locking_mode=EXCLUSIVE` 後寫入 | `frozenset()` | 7.4s | 同上 |
  | 主庫檔頭損毀（`file is not a database`） | `frozenset()` | — | 同上 |
  | WAL 庫，另一條連線只是 `BEGIN EXCLUSIVE` | `{'tender_radar'}` | 0.0s | `disabled`（正常） |

- 修法：照 STATES-PLATFORM §9.2 做。另外補一題 WAL 版本的反向控制（見 C-2：原本的重現手法在 WAL 庫上不會觸發）。

**A-2　§9c 的守門綁死 `tender_radar`：拿掉它（core-only 產品）就有 7 題紅**
- 位置：
  - `TMS:143-176`（`test_toggle_is_pending_until_restart`、`test_unlicensed_cannot_be_toggled` 直接指名 `tender_radar`）；
  - `tests/platform/child_module_gate.py:43-61`（寫 `tender_watches` 表、打 `/api/tender-radar/*`、讀 `rows["tender_radar"]`）；
  - `tests/test_e2e_module_settings_2026_09_25.py:25-64`。
- 違反的規則：
  - MODULE-GUIDE §7：「守門的正對照不可以綁在特定的 L2 模組上」；
  - PLAYBOOK §C-6；
  - CORE-SPEC §9c 驗收：「每一種產品設定檔都要能打包、啟動，並通過該組合的測試」。`product/core-only.json` 就是 `modules: []`。
- X 的重現：把 `modules/tender_radar` 暫時移出 worktree，再跑 `TMS`＋e2e，結果 **7 failed、16 passed**：`test_toggle_is_pending_until_restart`、`test_unlicensed_cannot_be_toggled`、`test_after_restart…[disabled/unlicensed/both]`（子行程 `KeyError: 'tender_radar'`），以及 e2e 兩題。移回後恢復全綠。
- 同一類的夾具污染：`conftest.py:240` 的 autouse fixture 在**每一題**都 `from modules.tender_radar import source`。
  - L1 的測試設定點名了一個 L2 模組。
  - 真正的 `modules.tender_radar` 永遠已經在 `sys.modules` 裡，所以「停用後不 import」只能用合成模組驗（`TMS:60-80` 確實是這樣做的，但子行程那幾題沒辦法驗這一點）。
- 修法：
  - 子行程與 API 題改用合成模組：`MOTRIX_MODULES_DIR` 之類的注入點，或「任取一個已載入的模組」。沒有模組時用 `pytest.skip` 明說，而不是紅。
  - conftest 那一段搬進 `modules/tender_radar/tests/conftest.py`。

**A-3　「授權檢查未啟用」這個狀態在任何地方都看不到**
- 規格：CORE-SPEC §9c「授權檢查沒有啟用時（開發模式）一律可載入，**狀態標「授權檢查未啟用」**」。
- 位置：`LIC::module_license_check` 回 `(True, '授權檢查未啟用')`，但 LD:82-87 只在 `not licensed` 時使用 `why`，LD:102 固定寫 `reason=""`。
  - `grep -rn "授權檢查未啟用\|MODULE_LICENSE_NOT_CHECKED\|LICENSE_GATE_ENABLED" routers core frontend` 只找到 main.py 的中介層，沒有任何畫面或 API 露出這個狀態。
- 重現：`python -c "…loader.load_all(license_check=lic.module_license_check);print(registry.module_states())"` ⇒ `'state': 'loaded', 'reason': ''`。
- 為什麼是必修：這是規格明文的驗收項。後果是出貨時如果忘了打開 `LICENSE_GATE_ENABLED`，模組管理頁看起來和「授權都驗過了」一模一樣。這個錯是安靜的，而且落在會影響營收的那一側。
- 修法：loaded 時把 `why` 寫進 reason，或另設一個欄位 `licenseChecked: false`；模組管理頁頂端顯示一次「授權檢查未啟用（開發模式）」。

### 建議

- **B-1　`test_registry_snapshot_restores_every_table` 寫著「每一張表」，實際上驗不到**（TMS:206-220）：
  - 這題只把探針放進 `_STATES`，再比對 `restore(before)` 與 `snapshot()`。兩邊用的是同一份列舉，所以 snapshot 漏掉哪一張表，兩邊就一起漏掉。
  - X 的突變：把 `RG::snapshot` 的 `dict(_FAILED)` 換成 `{}`。這題照綠，**`tests/platform` 全部 378 passed**。
  - 修法：用 `vars(registry)` 列出模組層級的 `_` 開頭 dict（排除 `_LEGACY_PROVIDERS`），斷言 snapshot 的長度與它們一致，並且每一張都放一筆探針。
- **B-2　金鑰的 `modules` 沒有驗型別，字串會變成子字串比對**（LIC:658-659）：
  - `mods = status.get("modules") or []`，接著判斷 `key in mods`。當 `modules` 是字串時，這會變成子字串比對。
  - X 的重現：`'tender_radar_pro'`⇒`(True, '')`，`'xtender_radarx'`⇒`(True, '')`；`['tender_radar_pro']`⇒ 正確拒絕。
  - 金鑰有簽章，`issue_license.py:129` 產生的是 list，所以目前不會被利用。但驗證端不應該依賴簽發端永遠正確。
  - 修法：`modules` 不是 `list[str]` 就回 `malformed`，或者判定未授權。
- **B-3　「停用 ⇒ 排程不跑」沒有任何一題真的跑過排程**：
  - conftest 對整個 session 設 `MOTRIX_DISABLE_SCHEDULERS=1`（conftest.py:311），子行程也繼承這個設定 ⇒ 不論停用與否，排程都不會跑。STATES P-SW-08 引用的守門是合成模組的 `sys.modules` 檢查，不是排程本身。
  - X 用裸行程補了一對：停用 ⇒ `schedulers: 0`；啟用 ⇒ 把 `source.schedule_tender_scan` 換成記錄器，呼叫 1 次。
  - 建議把這一對寫成題目，而且用合成模組（同 A-2）。
- **B-4　規格裡的「開回來後恢復」沒有測試**：子行程只驗了「關 ⇒ 404」。建議加一個參數：設定裡先停用、再啟用，然後重啟 ⇒ 端點 200、資料還在。

### 觀察

- **C-1　STATES-PLATFORM 目錄與它的修正都還沒進 platform**：
  - `docs/platform/states/STATES-PLATFORM.md` 只在 `wip/a-platform-states`（`2a9635a3`、`55f3c8b2`），platform 上沒有這個檔。
  - 同一份目錄裡和 §9c 驗收直接相關、但還沒修的有：
    - P-FE-02：模組不在包內 ⇒ 狀態表裡沒有它 ⇒ `unavailable-pages` 不列它的頁面 ⇒ 側欄入口照樣出現（SYS:767-768 只迭代 `module_states()`）。
    - P-FE-03：直接打網址進去是半空白的頁面。
    - P-DT-01：地圖在模組停用後仍然讀 `tenders`。
    - P-LD-07：路由衝突。
- **C-2　P-SW-05 的重現手法在正式機的組態上不成立**：
  - STATES R2 用的是一般 journal 的庫加 `BEGIN EXCLUSIVE`。
  - 主庫是 WAL（db.py:184）。在 WAL 上，`BEGIN EXCLUSIVE` 不擋讀取（X 實測 0.0s 就讀到正確的清單）。
  - 風險仍然成立，但觸發方式不同：`locking_mode=EXCLUSIVE`、檔頭損毀、權限錯誤等等（A-1 的表）。修 A-1 時，反向控制要用 WAL 的觸發方式，否則會是一題綠燈是真的、但證明的是另一種庫的題目。
- **C-3**：SB:1157 用 `document.querySelectorAll('a[href$="…"]')` 掃的是**整頁**，不只側欄。帶查詢字串的連結（`record-link.js:48` 的 `tender-radar.html?case=`）不會被藏（STATES P-FE-06）。API 失敗時 `catch` 什麼都不做，所以全部入口照常顯示（P-FE-04）。目前都不會越權，因為端點仍然是 404。
- **C-4**：MS:61-71 的 `set_enabled` 是讀、改、寫，而且沒有鎖（P-SW-10）。模組管理頁有兩位 superadmin 同時切換時，後寫的會蓋掉先寫的。
- **C-5　重現環境**：
  - 共用 venv 在 repo 外面（`D:\MOTRIX-PLATFORM\.venv`）。從別的 worktree 跑 pytest 會寫 `__pycache__` 到 venv，而那會被 BK19 守門擋下（`conftest.py:158`：「測試想寫到 repo 與 tmp 之外」），`client` 夾具全部 ERROR。要設 `PYTHONDONTWRITEBYTECODE=1`。
  - venv 裡的 playwright 1.63 要的是 chromium 1243，這台機器只有 1234。X 在 scratchpad 建目錄連結，再設 `PLAYWRIGHT_BROWSERS_PATH` 才跑得動 e2e。
  - 其他視窗的 e2e 如果在這台機器上是「skip／error」而不是綠，原因在這裡。
- **C-6**：跑 `client` 夾具時，初始帳號憑證檔（`.initial_admin_credentials.txt`／`.initial_demo_credentials.txt`，F3）被寫進 **worktree 的 `backend/`**，而不是暫存目錄（log：`helpers/startup.py:121/199`）。檔案在 `.gitignore` 裡，不會進 commit，但這是夾具隔離範圍的缺口（BK19 同一類）。不在這次的範圍內，只記下來。

## 3. 反向控制與假綠燈檢查（X 實際跑過）

腳本：`%scratchpad%\aud_9c.py <case>`，裸行程執行，不經過 conftest，也不 import main。

| # | 做了什麼 | 結果 |
|---|---|---|
| R1 | 授權開關打開＋金鑰只含別的模組 ⇒ `load_all` | `unlicensed`，原因齊全，沒有 import ✅ |
| R2 | 授權開關打開＋真的 `verify_license`（沒有金鑰檔） | `unlicensed`「尚未安裝授權金鑰」，沒有 import ✅ |
| R3 | 子行程：停用／未授權／兩者 ⇒ `/api/tender-radar/*` 回 404、資料列數不變 | 3 題綠 ✅（現有題目，X 重跑） |
| R4 | 停用 ⇒ 排程迴圈 | 0 個；正對照（啟用）呼叫 1 次 ✅ |
| R5 | 讀停用清單的失敗路徑（4 種觸發方式） | 3 種反轉了管理者的決定 ❌（A-1） |
| R6 | 對方不在：拿掉 `modules/tender_radar` | 7 題紅 ❌（A-2） |
| R7 | 突變：snapshot 漏掉 `_FAILED` | 守門題與 `tests/platform` 全綠 ❌（B-1） |
| R8 | 金鑰 `modules` 是字串 | 子字串比對放行 ⚠（B-2） |
| R9 | 授權開關關閉 ⇒ 狀態原因 | `reason=''` ❌（A-3） |

- **假綠燈**：
  - B-1：同一份列舉的兩邊互相比對。
  - B-3：排程閘門在整個測試 session 都是關的，所以「停用後排程沒跑」在測試裡恆真。
  - A-2：正對照綁在特定模組上。
- **回滾路徑**：「停用 → 啟用」只驗了設定值會回去（`TMS:157-159`），沒有驗重啟後端點會恢復（B-4）。

## 4. 回覆欄（被稽核者填；X 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | X 確認 |
|---|---|---|---|
| A-1 | 不在這次範圍（主持裁示）：P-SW-05 已在 `wip/a-platform-states`，由另一個代理合回。⚠ 該分支與本修正衝突，見表下「合併注意」 | — | **待合回**。origin/platform `af3d5ef7`（9c／batch1 的題目在 `7eb162f0` 跑；兩者之間沒有動到受稽核的檔） 的 `read_disabled_at_startup` 讀不到時仍回 `frozenset()`（MS:44-52）；`wip/a-platform-states`（`0dffe55d`）只在主樹的本機分支，**origin 上沒有**。合回後由稽核者用 WAL 觸發方式（`locking_mode=EXCLUSIVE`、檔頭損毀）重跑 R5 才關<br>✅ **D 代為確認（2026-09-26 01:53）：關閉**。98d43855 合回，基準 origin `41865c87`。`read_disabled_list()` 讀不到時沿用快取；沒有快取就全部停用（MS:120-143），`main.py:43-47` 把 `all_disabled` 傳成 `loader.ALL`。反向控制照 C-2 用三種觸發方式（journal `BEGIN EXCLUSIVE`、**WAL `locking_mode=EXCLUSIVE`**、**檔頭損毀**），連同 WAL 上 `BEGIN EXCLUSIVE` 不擋讀的對照題都在，基準 82 passed。D 自做突變：X01 讀不到當沒停用（原缺陷）紅 3 題（三種觸發方式都紅）；X02 不用快取紅 4；X03 鎖住即回空紅 4（含 WAL 與檔頭損毀）；X04 切換後不更新快取紅 1；X05 main 忽略全部停用紅 1（重啟題 `[unreadable]`）。**新觀察 X06（不擋關閉）**：`_read_cache` 讀到損毀的快取檔時，把 `return None` 突變成 `return []`（＝「沒有停用」，會反轉管理者的決定），題目照樣綠（82 passed）。產品碼現在是對的，但沒有題目守；建議補一題「快取檔損毀＋主庫讀不到 ⇒ 全部停用」。另：權限錯誤這一種觸發方式沒有列進 `_HOW`，同屬 sqlite 讀取失敗路徑，不另要求 |
| A-2 | 修正。① `load_all()` 在呼叫當下讀 `MODULES_DIR`／新增的 `MODULES_PACKAGE`；② 子行程由父行程在 tmp 建合成模組樹（`zz_gate`：路由、排程、頁面），`import main` 前換掉；參數加 `reenabled`、`coreonly`；③ D 組用合成模組 `zz_toggle`（路由插在 StaticFiles 前、題後依身分移除，registry 用 snapshot／restore）；④ e2e 用合成狀態列；選單題「任取已載入且選單有入口的模組」，沒有就 skip 並說明；另加 core-only e2e（空狀態表 ⇒ 管理頁說沒有模組、選單照常、無 JS 錯誤）；⑤ conftest 的 `_no_politeness_delay` 搬到 `modules/tender_radar/tests/conftest.py`；⑥ 靜態守門 `test_no_real_l2_module_named_here`（含正對照）、`test_conftest_names_no_l2_module`；MODULE-GUIDE §7 補寫法與守門。**反向控制實跑**：拿掉 `modules/tender_radar` 跑 TMS＋e2e ⇒ **37 passed、2 skipped**（兩題 skip 都寫明 core-only；修正前 X 的 R6 是 7 failed）。突變：`load_all` 改回讀定義時的目錄 ⇒ 6 紅；conftest 再 import L2 ⇒ 紅；e2e 再點名 `tender_radar` ⇒ 紅 | 5f372370 | ✅ 關閉。反向控制 R6 重跑：移走 `modules/tender_radar` 後 TMS＋`test_core_loader`＋§9c e2e ⇒ **53 passed、3 skipped**（3 題 skip 都寫明 core-only；修正前 7 failed）。稽核者突變：`_current_modules_dir()` 改回 import 時綁定的目錄 ⇒ **6 紅**（`test_loader_reads_modules_dir_at_call_time`＋子行程 disabled／unlicensed／both／reenabled／coreonly）。假綠燈檢查：子行程的模組樹由父行程在 tmp 建、經產品的 `load_all` 讀取；靜態守門有正對照；沒有綁特定模組 |
| A-3 | 修正。registry 狀態加 `note`（`set_state(…, note=…)`，`reason` 仍＝有問題，不會被當錯誤）；loader 在授權通過時保存說明（loaded 與 disabled 都帶）；`/api/system/modules` 每列帶 `note`；模組管理頁狀態格顯示、頂端提示一次「授權檢查未啟用（開發模式）」。題：`test_license_not_checked_is_visible_in_state`（含反向：授權有啟用 ⇒ note 空）、`test_admin_api_shows_the_license_note`、e2e `test_license_not_checked_is_shown`（含正對照）。突變：loader 丟 note ⇒ 紅；狀態不存 note ⇒ 紅；頁面不顯示提示 ⇒ e2e 紅 | 5f372370 | ✅ 關閉。裸呼叫：開關關閉 ⇒ `module_license_check` 回 `(True, '授權檢查未啟用')`，main.py:40 直接注入它。稽核者突變：loader `note = why or ""`→`""` ⇒ `test_license_not_checked_is_visible_in_state` 紅；頁面 `licenseNotes` 改成 `[]` ⇒ e2e `test_license_not_checked_is_shown` 紅（橫幅逾時）。假綠燈檢查：API 題與 e2e 的 note 是測試自己寫進狀態表的（驗「傳遞與顯示」），loader 那一段由真 loader＋真授權函式驗；三段合起來涵蓋整條鏈，接受 |
| B-1 | 修正。表清單改從 `vars(registry)` 列（`_` 開頭 dict、排除 `_LEGACY_PROVIDERS`），斷言 snapshot 份數＝表數，每張表放探針。突變 `dict(_FAILED)`→`{}` ⇒ 紅 | 5f372370 | ✅ 關閉（抽查：表清單從 `vars(registry)` 列，與 snapshot 不同源；本次基準綠） |
| B-2 | 修正。`modules` 不是 `list[str]` ⇒ 未授權「模組清單格式不正確」。新增 6 組參數（字串、`"*"` 字串、dict、混型別、正確拒絕）。突變拿掉型別檢查 ⇒ 5 紅 | 5f372370 | ✅ 關閉。稽核者裸呼叫 `module_licensed`：`'xtender_radarx'`、`'*'`（字串）、dict ⇒ 未授權「格式不正確」；`['tender_radar']`、`['*']` ⇒ 通過；`['tender_radar_pro']` ⇒ 拒絕 |
| B-3 | 修正。新增 `core.loader.start_schedulers()`，main 在排程閘門內改呼叫它；子行程在重啟後直接呼叫同一函式：停用／未授權 ⇒ 0 次，開回 ⇒ 1 次，core-only ⇒ 0。突變：函式不跑 ⇒ 紅；停用的模組照樣 import＋登錄 ⇒ 紅。⚠ 殘留：「main 有沒有在閘門內呼叫它」沒有題（session 閘門恆關） | 5f372370 | ✅ 關閉（抽查：main.py:605 在閘門內呼叫 `start_schedulers()`）。接受回覆自述的殘留（「main 有沒有呼叫」無題：session 閘門恆關） |
| B-4 | 修正。子行程 `reenabled`：父行程用真的 `set_enabled` 停用（先確認讀得到）再啟用，子行程用真的讀取路徑 ⇒ 200、讀到停用期間的資料列、排程 1 次。突變：啟用時不拿掉 key ⇒ 紅 | 5f372370 | ✅ 關閉（A-2 的突變讓 `reenabled` 一起轉紅 ⇒ 這一題確實走子行程＋真的讀取路徑） |
| C-1 | 不在範圍：STATES-PLATFORM 與 P-FE-02／03、P-DT-01、P-LD-07 由 `wip/a-platform-states` 合回 | — | **待合回**（同 A-1）<br>✅ **D 代為確認（2026-09-26 01:53）：關閉**。`docs/platform/states/STATES-PLATFORM.md` 與 repro 已在 origin（98d43855）；P-FE-02／03、P-DT-01、P-LD-07 的題目 `test_states_platform_entries_2026_09_25.py`、`test_core_loader.py` 包含在基準的 82 passed 裡。D 這次的突變只針對 P-SW-05，這幾項沒有另外做突變 |
| C-2 | 不在範圍（屬 A-1）。提醒合回 A-1 的代理：該分支 `test_locked_db_uses_last_good_list_then_all_disabled` 仍用一般 journal 庫＋`BEGIN EXCLUSIVE`，要補 WAL 觸發方式 | — | **待合回**：隨 A-1 確認反向控制改用 WAL 觸發方式<br>✅ **D 代為確認（2026-09-26 01:53）：關閉**。`test_locked_db_uses_last_good_list_then_all_disabled` 參數化成三種觸發方式，其中兩種是 WAL 庫（`_settings_db(wal=True)`）；突變 X01、X03 讓 WAL 那兩種觸發方式都轉紅，證明綠燈驗到的是主庫的實際組態 |
| C-3 | 不修。① 「掃整頁」在現況是必要的：側欄已退役，選單在 `#app-mainnav`（不在 `#app-sidebar`）；② 帶查詢字串的連結（P-FE-06）與 API 失敗（P-FE-04，STATES 判「可接受」）由 `wip/a-platform-states` 處理（`record-link.js` 依模組狀態不產生連結）。現在改 `sidebar.js` 同一段必然與該分支衝突 | — | ✅ 接受不修：選單在 `#app-mainnav`，掃整頁在現況是必要的；P-FE-04／06 在 `wip/a-platform-states`，現在改必衝突。⚠ 該分支尚未推上 origin，隨 A-1 追蹤 |
| C-4 | 修正。`set_enabled` 讀改寫放進同一個寫入交易（`core.txn.write_txn`；第一版直接寫 `BEGIN IMMEDIATE`，被全量的 `test_begin_only_via_begin_write` 擋下，35189b82 改正）。題：兩條執行緒都卡在「讀完、未寫」⇒ 兩個 key 都要在。突變改回原本的讀改寫 ⇒ 紅（`['zz_c4_b'] == ['zz_c4_a','zz_c4_b']`，確認是遺失更新） | 5f372370 | ✅ 關閉（抽查：`set_enabled` 讀改寫在 `write_txn` 內；本次基準綠） |
| C-5 | 環境：`D:\MOTRIX-PLATFORM\.venv` 在 22:1x 被刪一半；本次用自建 `.venv-x9`（Python 3.12.8，requirements＋dev）。發現 `requirements-dev.txt` 沒有 `httpx`（starlette 1.7 的 TestClient 需要 `httpx2` 或 `httpx`），全新 venv 下 `client` 夾具全部 ERROR ⇒ 另案處理（未改 requirements：屬 fixture 層） | — | ✅ 記錄。本次在 `.venv312`＋`PYTHONDONTWRITEBYTECODE=1` 下全部跑得動（含 e2e）；`requirements-dev` 缺 httpx 另案 |
| C-6 | 不在範圍；本次重現同一現象（初始帳號憑證檔寫進 worktree 的 `backend/`），已隨 worktree 刪除 | — | ✅ 同意移出本次 |

**驗證（X9）**：全量在 8ac0b042（基準 2801d757）：非 e2e 3745 passed／7 failed，e2e 367 passed／2 skipped。7 紅之中：1 題是本修正造成的（`test_begin_only_via_begin_write`，35189b82 修正）；另外 6 題在 origin/platform 7c66c232 單獨重跑也紅，是既有問題：`test_module_history::test_fn4_*` 兩題、`test_licensing_core::test_08a`，以及 `test_no_credentials_in_query` 三題（自建 venv 沒有 numpy／cv2）。rebase 到 a33ef2b5 之後，重跑 `tests/platform`、§9c e2e、begin 守門、tender 平台控制題：464 passed（-n 2、低優先權，PLAYBOOK §C-13）。突變 12 項全紅，全部已還原。

**合併注意（給合回 `wip/a-platform-states` 的代理）**：
- 與本修正重疊的檔：`core/loader.py`、`core/registry.py`（兩邊都用 CORE 1.5 ⇒ 後合者升 1.6，重產 G1 快照）、`helpers/module_switches.py` 的 `set_enabled`（該分支加寫快取，要放進本修正的交易之後）、`main.py` 排程段（該分支移到 `mount_modules()` 之後，請改呼叫 `module_loader.start_schedulers()`）、`module-settings.html`、三支 §9c 測試檔、`core/CHANGELOG.md`。
- 該分支新增的題（子行程 `unreadable`、`test_toggle_updates_the_cache`、`test_admin_page_shows_disabled_list_source`、e2e 第 3 題）點名 `tender_radar`，合回後 `test_no_real_l2_module_named_here` 會紅——改用本檔的合成模組（`synthetic_loaded`、`_gate_tree`）。

### 稽核者確認紀錄（2026-09-26 00:45）

- 基準 origin/platform `af3d5ef7`（9c／batch1 的題目在 `7eb162f0` 跑；兩者之間沒有動到受稽核的檔）；worktree `D:\MOTRIX-PLATFORM-CONF`（detached）、`.venv312`、`PYTHONDONTWRITEBYTECODE=1`、basetemp `%TEMP%\motrix-pytest-CONF-adhoc`；突變都在 worktree 內做、`git checkout` 還原，`git status` 乾淨。
- 基準：TMS＋`test_core_loader`＋§9c e2e **56 passed**；core-only 反向控制 **53 passed／3 skipped**。
- 稽核者自做突變 3 項（A-2 ×1、A-3 ×2），全部轉紅、已還原。
- 結果：必修 A-2、A-3 關閉；**A-1 待合回**（連同 C-1、C-2）。本檔**尚不能結案**。
- **D 代為確認（2026-09-26 01:53，基準 origin `41865c87`）**：A-1、C-1、C-2 ✅ 關閉（突變 6 項：5 紅、1 存活；存活的 X06 列為新觀察，不擋關閉）⇒ 本檔必修全部關閉，**可以結案**（X06 的補題建議交給 A）。
