# 稽核：授權閘門預設開（license-gate-default-on）與可信來源 IP（trusted-client-ip-r3）（hichan-16 稽核，2026-11-12）

> 依 PLAYBOOK §E、§G7。稽核者 hichan-16 沒有寫過、也沒有改過任何受稽核的程式碼（本 session 先前只做過 UI 版面與 T79 步驟檔文件複核）。
> 對象：
> - `backend/helpers/licensing.py`、`backend/main.py::license_gate_middleware`（`LICENSE_GATE_ENABLED` 預設改 True，每個 `/api/*` 請求都驗）
> - `backend/helpers/license_alerts.py`、`routers/licensing.py`、`tools/issue_license.py` 的通行證段、`frontend/static/notif.js` 的 402／橫幅處理
> - trusted-client-ip-r3：`backend/helpers/client_ip.py`、`routers/auth.py` 的 `_client_ip`／登入鎖定、`tools/deploy_dashboard.py` 的 `_local_only`／`/ws/prod-status`（`docs/windows/STATE.md` HC1d）
>
> 稽核基準 `origin/train/t80-int` **`ffd4b8a90`**（detached worktree `D:\Claude-pm\audit-t80-security`），Python `D:\MOTRIX-PLATFORM\.venv312`（只用、未改）。
> 分級：**必修**（不修不能關）／**建議**／**觀察**。關閉規則：被稽核者回覆後，由稽核者確認才關。
> 縮寫：`LIC`＝`backend/helpers/licensing.py`、`MAIN`＝`backend/main.py`、`CIP`＝`backend/helpers/client_ip.py`、`AUTH`＝`backend/routers/auth.py`、`DD`＝`backend/tools/deploy_dashboard.py`、`LA`＝`backend/helpers/license_alerts.py`。
>
> ⚠️ **未做的事（誠實標註）**：
> - 沒有在真機跑 `machine_fingerprint()`（PowerShell `Get-CimInstance` 讀硬體）——遵守使用者「禁跑硬體／儲存 WMI 查詢」的約定。所有涉及指紋的實測都把 `licensing._run`／`_windows_hardware` 換成假的；**真實的 PowerShell 耗時與失敗率沒有量到**，下面寫「plausible」的地方就是這個意思。
> - 沒有真的發 IPv6 封包；IPv6 那一項是用 `client_ip()` 的輸入輸出證明「同一個 /64 會得到不同的鎖定鍵」。
> - 沒有經過真的 Cloudflare 隧道。

## 0. 結論

- **閘門本身擋得住**：我試了 23 條路徑（含 `//api`、大小寫、`%61pi`、尾斜線、`HEAD`／`OPTIONS`、`/api/ping/`、未登入／已登入各一次），沒有找到繞過；沒有 WebSocket／SSE 路由；非 `/api/` 的路由只有頁面外殼與 JS（`/pages/*`、`/map-overlays/*`、`/static/sidebar.js`、`/`、兩個 Mount），不含資料。中介層順序（license 在 auth 內側）與 `exempt` 判定都有題目守，我做了突變（見 §2）全部被抓到。
- **HC1d（隧道不當本機）程式面成立**：突變拿掉 `_came_through_proxy`（HTTP／WebSocket 各一）、讓 `client_ip` 對任何對端都採信 `CF-Connecting-IP`，現有題目都紅。
- **問題集中在三處「預設一翻才變成真的」的邊角**，都有實測：
  1. **LG-M1**：指紋讀不到／只讀到一半時，**失敗結果被快取**——整站 402（直到金鑰檔被碰、本機時間午夜，或重啟），硬體恢復後同一個檔仍判「機器不符」；殘缺指紋甚至快取到行程結束。這條路徑在 T80 之前**從沒在正式機跑過**（閘門關著不算指紋）。
  2. **LG-M2**：授權判定在 async 中介層裡**同步**執行：指紋冷啟動時整個事件迴圈被擋住（模擬 3 秒 ⇒ 公開的 `/api/ping` 等了 2.44 秒）；被擋住且有通行證時，每個請求（含公開端點）都多付約 0.7 ms 的同步檔案讀取＋驗章，沒有任何快取。
  3. **IP-M1**：登入鎖定只以「單一 IP 字串」計，**沒有 IPv6 /64 聚合、也沒有帳號維度**；隧道一開，IPv6 用戶端換位址就繞過鎖定。HC1d 修的是 XFF 偽造，這一條是同一個控制項的下一個洞。
- **必修 3 項**（LG-M1、LG-M2、IP-M1）、建議 4 項、觀察 7 項。
- 基準（未突變）：`test_licensing_gate`、`test_licensing_emergency`、`test_licensing_core`、`test_trusted_client_ip`、`test_deploy_dashboard_local_only` 共 **191 passed**（單程序，約 52 秒）。
- 「疑似相關的 timing 測試超標」：**我沒有重現**（`test_conn_reaper_t80` 的 `test_async_middleware_writes_do_not_block_the_event_loop`、`test_real_app_stack_releases_lock_and_logs_request` 各單獨跑 3 次，3/3 綠、約 13 秒）。給你判斷用的成本資料：授權判定**正常路徑**（快取命中）約 **0.04–0.06 ms／請求**，不足以單獨造成 timing 題超標；真正會吃毫秒到秒級的是 LG-M2 的兩條冷路徑。如果超標的題目是在「換了 `LICENSE_PATH` 的第一個請求」之後立刻量，快取未命中（讀檔＋驗章）也只約 0.3 ms。請把超標題的名稱與數字給我，我可以針對它再量。

## 1. 逐項驗收

| 項目 | 規格／期望 | 驗收 | 證據 |
|---|---|---|---|
| 預設 True | `LICENSE_GATE_ENABLED = True` | ✅ | LIC:107；`test_gate_ships_enabled` |
| 非 `/api/` 放行 | 靜態檔載得出來 | ✅ | MAIN:564；§2 `PATH /`、`/index.html` 皆 200 |
| 豁免＝`LICENSE_EXEMPT_PATHS ∪ _PUBLIC_API_PATHS` | 精確比對，不收萬用字元 | ✅ | MAIN:567；`/api/ping/`（尾斜線）不豁免、`//api/..`、`/API/..` 皆 404 |
| 未登入先 401、不洩漏授權狀態 | 中介層順序：auth 先、license 後 | ⚠️ 大部分成立 | MAIN:533-541 的設計；**例外：`/api/uploads/*?pt=`**，見 LG-S1 |
| 簽章先於 machine／expires | 驗章前不信任 payload | ✅ | LIC:344-441；`_unverified()` 不回填欄位 |
| fail-closed（算不出指紋就擋） | 不把「讀不到」當通過 | ✅ 判定；❌ 快取 | LIC:426-436；快取見 LG-M1 |
| 通行證只救 `machine_mismatch`／`expired`、綁 tax_id＋machine＋環境、≤14 天 | 不是「放個檔案就放行」 | ✅ | LIC:542-600；LIC:513、511；`test_licensing_emergency` |
| 通行證／授權金鑰不可互相冒充 | purpose／必要欄位不同 | ✅ | LIC:555、515；`_open_blob(…, required)` |
| 橫幅標頭只給已登入者 | K 審 S4 | ✅ | MAIN:603-604；`request.state.authed`（MAIN:710） |
| 稽核寫入不在事件迴圈上 | K 審 S1 | ✅ | LA:56-67（背景執行緒）；MAIN:596、598 |
| 授權判定不阻塞事件迴圈 | T80 R6 同一標準（`test_async_middleware_writes_do_not_block_the_event_loop`） | ❌ | LG-M2 |
| HC1d：帶 Cloudflare／代理標頭 ⇒ 403／1008 | fail closed | ✅ | DD:152-162、1243-1250；突變 MA、MB 紅 |
| `client_ip`：只在對端是 loopback 才採信 `CF-Connecting-IP`、不讀 XFF | CIP 不變式 ①②③ | ✅ | CIP:62-72；突變 MC 紅 |
| 登入鎖定以可信 IP 計 | 5 次／15 分鐘 | ⚠️ | 判定正確、但鍵不夠粗，見 IP-M1 |

## 2. 反向控制與突變（稽核者自做；每項都用 `git checkout` 還原並核對 `git status` 乾淨）

| 突變 | 結果 | 轉紅的題 |
|---|---|---|
| MA `DD:160` 拿掉 `or _came_through_proxy(request.headers)` | 🔴 紅 | `test_deploy_dashboard_local_only_2026_09_22.py -k hc1d` |
| MB `DD:1248` WebSocket 檢查拿掉 `_came_through_proxy` | 🔴 紅 | 同上（1 紅、7 綠後停） |
| MC `CIP:66` `if is_loopback(peer):` → `if True:` | 🔴 紅 | `test_trusted_client_ip_2026_11_11.py` |
| MF `MAIN:567` `exempt = True` | 🔴 紅 | `test_licensing_gate_2026_09_21.py`／`test_licensing_emergency_2026_11_11.py` |

路徑試探（`probe` 的 `test_probe_blocked_paths`；金鑰不存在 ⇒ 業務 API 該被擋；anon＝沒帶 token、authed＝一般管理者）：

| 路徑 | anon | authed | 判讀 |
|---|---|---|---|
| `/api/customers`、`/api/customers/`、`/api/./customers` | 401 | 402 | ✅ |
| `//api/customers`、`/API/customers` | 404 | 404 | ✅ 不進 `/api/` 也不命中路由 |
| `/%61pi/customers` | 401 | 402 | ✅ 解碼後與路由器看到同一個路徑 |
| `/api/ping`、`/api/system/version`、`/api/system/branding`、`/api/system/deployed-version` | 200 | 200 | ✅ 公開端點，不含業務資料 |
| `/api/ping/` | 401 | 402 | ✅（不在豁免清單，符合精確比對） |
| `/api/auth/me` | 401 | 402 | ✅ |
| `/api/license/status` | 401 | 200 | ✅ 登入後可讀（豁免） |
| `/api/line/callback` | 400 | 400 | ✅（固定頁，T79 已審） |
| **`/api/uploads/x?pt=bad`** | **402** | 402 | ❌ **未登入也拿到授權狀態**（LG-S1） |
| `/`、`/index.html` | 200 | 200 | ✅ 外殼 |
| `/docs`、`/openapi.json`、`/redoc`、`/uploads/x`、`/api` | 404 | 404 | ✅ |
| `HEAD /api/customers`（authed） | — | 402 | ✅ |
| `OPTIONS /api/customers`（authed） | — | 405 | ✅ 略過閘門但路由不收 OPTIONS，沒有資料 |

## 3. 發現

### 必修

**LG-M1　指紋讀不到／讀一半時，失敗結果被快取（fail-closed 變成長時間停擺）**
- 位置：
  - LIC:426-436：`machine_fingerprint()` 丟例外 ⇒ `this_machine=None` ⇒ 回 `machine_mismatch`。
  - LIC:324-326：`_verify_license_file()` 把**這個結果**存進 `_LICENSE_FILE_CACHE`，沒有分「確定不符」與「這次沒算出指紋」。
  - LIC:284-292：快取鍵＝路徑、mtime、大小、兩把公鑰、今天日期——**不含指紋**（`test_licensing_emergency_2026_11_11.py:96`、`test_e2e_license_gate_2026_11_11.py:55` 的註解都承認「快取鍵不含指紋」，測試靠手動清快取繞過）。
  - LIC:822-838：只讀到 MAC 沒讀到 UUID（或相反）時，`parts` 只有一項、照樣算出一個「看起來像指紋的值」並**存進 `_FINGERPRINT_CACHE`（行程內永久）**。`_PS_HARDWARE`（LIC:683-690）用 `$ErrorActionPreference='SilentlyContinue'`，單項 CIM 查詢失敗不會有任何訊息；`_run`（LIC:661-680）逾時 30 秒後回空字串。
  - 呼叫時機：服務開機時 `module_license_check`（LIC:870-881，由 `load_all` 對每個模組呼叫）與 `license_alerts.startup_check`（MAIN:949）是**第一個**算指紋的人；T80 之前閘門關著、這條路徑在正式機從沒跑過。
- 為什麼是必修：
  - 預設一翻，「開機時 WMI 還沒就緒、或 CIM 查詢偶發失敗」就會變成**整站 402＋所有模組沒載入**。模組載入只在開機時決定一次（LIC:504-506 的說明；`/api/license/status` 的 `modules_unlicensed`），所以即使之後指紋恢復，**模組要重啟才會回來**。
  - 殘缺指紋（D1）連「隔天午夜」都救不了：`_FINGERPRINT_CACHE` 不隨日期重算，只有重啟。
  - 通行證能救 `machine_mismatch`，但前提是**事先簽好、放好**——一次暫時性的讀取失敗不會有人預先準備。
  - 正式機有 BSOD 0x124 的歷史（LIC:483-484 自己引用）：重開機後服務自動啟動、此時 WMI 慢，是現實情境。**我沒有在真機重現「WMI 慢到失敗」**，所以是 plausible，不是已發生。
- 重現：`probe_pure.py` 的 C 與 D（`D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe -X utf8 docs\platform\audit\AUDIT-16-probes\probe_pure.py`）：
  - `C1 hardware unreadable at first call -> machine_mismatch`
  - `C2 hardware recovered, SAME license file, same day -> machine_mismatch`（此時 `machine_fingerprint()` 已能算出正確值，狀態仍卡在快取）
  - `D1 partial = e37cc0fe79b6f4ff  later (hardware fully readable) = e37cc0fe79b6f4ff  expected = b47d7a727f5f00ca`
- 建議修法（擇要，細節由被稽核者定）：
  - 「這次沒算出指紋」的結果**不進** `_LICENSE_FILE_CACHE`（或只快取很短的 TTL，例如 ≤60 秒），並在判 `machine_mismatch` 前**強制重讀一次硬體**（略過 `_FINGERPRINT_CACHE`）。
  - 殘缺指紋不快取到永久：UUID 與 MAC 兩項至少有一項「本來就讀不到」才算穩定（例如連續兩次相同、或與金鑰上的 machine 相符才快取）；讀到空值時重試（3 次、間隔 1–2 秒）。
  - 啟動時（`startup_check` 之前）先暖指紋並重試，讀不到就明確 log，不要把第一次的失敗留給整個行程。
  - 補題：`_windows_hardware` 先回殘缺／空、再回完整 ⇒ 同一個金鑰檔最終判 `ok`；突變（恢復原狀）要紅。

**LG-M2　授權判定在 async 中介層裡同步執行（指紋冷啟動、通行證判定都擋事件迴圈）**
- 位置：MAIN:578（`license_core.verify_license()`）、MAIN:582（`license_core.emergency_pass(status) if blocked`）。這個函式是 `async def`，沒有 `run_in_threadpool`；T80 R6 才剛把 `auth_middleware` 的同步 SQLite 寫入搬出事件迴圈，並有 `test_async_middleware_writes_do_not_block_the_event_loop` 守——同一個標準，這裡沒套用。
- (a) **指紋冷啟動**：`_verify_blob`（LIC:427）→ `machine_fingerprint()` → `_run`（`subprocess.run`，最長 30 秒，LIC:661）全部在事件迴圈上。冷的情況：服務開機時沒有有效金鑰（`missing` 在 LIC:303-307 就返回，沒算指紋），之後才放進 `license.key`——這正是 LIC:103-106 規定的上線順序「②放金鑰 ③確認 valid」，而且文件說「業務 API 下一個請求就恢復」。那「下一個請求」就是付代價的人。
  - 實測（`test_probe_cold_fingerprint_blocks_event_loop`：用真的 `machine_fingerprint`，但 `_run` 換成睡 3 秒的假指令，**不碰真硬體**）：`COLD A (triggers fingerprint): (200, 3.07)  B (/api/ping started 0.6s later): (200, 2.44)`——公開的 `/api/ping` 被卡了 2.44 秒。
  - 真實 PowerShell 耗時沒量到；LIC 內註解、`/api/license/status` 的 K 審 S6（routers/licensing.py:27-37）都把它當成「慢」的操作對待。
- (b) **通行證判定無快取**：被擋時 MAIN:582 對**每個請求**呼叫 `emergency_pass`，而且在 `exempt` 判斷（MAIN:583）**之前**——所以 `/api/ping`、`/api/auth/login` 等公開端點、未登入的請求也要付。每次＝讀通行證檔＋讀授權金鑰檔＋兩次 `_open_blob`（含 PEM 解析與 Ed25519 驗章），都在事件迴圈上，沒有 mtime 快取（授權金鑰本身有，LIC:281-326）。
  - 實測（`probe_pure.py` A／B）：正常快取命中 **43–63 µs**；被擋＋有效通行證 **718–812 µs**；被擋＋沒有通行證檔 **28–40 µs**；被擋＋8 KB 垃圾通行證檔（`EMERGENCY_MAX_BYTES`＝8192，LIC:512）**311–349 µs**。
  - 約 1000 個請求／秒 ≈ 吃掉事件迴圈 70–80%，而其中未登入的公開端點不需要任何憑證。也就是通行證生效期間（本來就是事故期間）多了一個便宜的放大器。
- 建議修法：
  - (a) 啟動時暖指紋（同 LG-M1），並把 `verify_license()` 的**未命中路徑**放進 `run_in_threadpool`（命中時維持同步以保 0.05 ms）；或乾脆整個判定用一次 `run_in_threadpool` 呼叫。
  - (b) `emergency_pass` 比照授權金鑰的快取：鍵＝通行證路徑＋mtime＋size＋授權金鑰的 stat＋兩把公鑰＋今天日期；同樣只在「被擋」時才查。
  - 補題：仿 `test_async_middleware_writes_do_not_block_the_event_loop`，在同一個事件迴圈量心跳，覆蓋「金鑰冷啟動」與「被擋＋通行證」兩個情境（`worst < 0.6` 之類的上限）。

**IP-M1　登入鎖定的鍵不夠粗：IPv6 /64 與帳號維度都沒有**
- 位置：
  - CIP:51-59、62-72：`_valid_ip` 只正規化，不做前綴聚合；`client_ip()` 回的是完整位址。
  - AUTH:46-48、117-143：`_rl_state` 以**完整 IP 字串**為鍵；沒有「帳號」維度的計數器（`_rl_fail(ip, username)` 的 username 只進 log，AUTH:141），users 表上也沒有失敗計數（`grep failed_attempts|login_fail|account_lock` 在 routers/auth.py、helpers/auth.py、db.py 無結果）。
- 為什麼是必修：HC1d 的動機是「外網存取 go-live 前必修」，而鎖定正是 XFF 被偽造時失效的那個控制項。現在隧道一開，Cloudflare 給的是用戶端的真實位址；擁有 IPv6 的攻擊者（一般住宅網路就有一個 /64＝2^64 個位址）每次換位址就是一個新桶 ⇒ 無限次猜密碼，與 XFF 偽造同一類後果。
- 附帶：`_rl_state.setdefault(ip, …)`（AUTH:135）對每個失敗的新位址建一筆，`fails<5` 的列永遠不會被清（`_rl_check` 只刪 `locked_until>0` 且已過期的列，AUTH:127-128；`helpers.startup._prune_login_locks` 只清資料庫那份）⇒ 位址輪換同時是**記憶體無上限成長**。
- 重現：`probe_pure.py` 的 E2：同一個 /64 的三個位址 `2001:db8:1:2::1/2/3` 經 `client_ip()` 得到三個不同的字串（＝三個不同的鎖定桶）。（這是鍵的證明；沒有真的發 IPv6 流量。要確認的外部事實：Cloudflare 該網域的 IPv6 相容是否開著——若關閉，IPv6 用戶端連不進來，風險降低但不是消失，因為 IPv4 池也能輪換。）
- 建議修法：
  - 鎖定用的鍵：IPv4 用完整位址、IPv6 取 /64 前綴；**稽核紀錄仍記完整位址**（不要為了鎖定把稽核資訊變粗）。
  - 另加帳號維度的失敗計數（跨 IP 的滑動視窗，例如 N 次／15 分鐘 ⇒ 漸進式延遲，不要硬鎖帳號，避免被拿來鎖別人；硬鎖與否是產品裁示）。
  - `_rl_state` 加上限與逾時清理（例如超過 10 000 筆時淘汰最舊、`fails>0` 的列 1 小時後過期）。
  - 補題：同 /64 不同位址連續失敗 ⇒ 第 5 次起 429；突變（改回完整位址）要紅。

### 建議

- **LG-S1　`/api/uploads/*?pt=…` 讓未登入者讀到授權狀態（與中介層順序的設計目的相反）**
  - 位置：`auth_middleware` 在 MAIN:683-684 對帶 `pt` 的 uploads 請求**不驗 session 就放行**；之後 `license_gate_middleware`（內側）在 MAIN:583-593 回完整的 402 body。MAIN:533-541 的註解明說這個順序就是要避免「對還沒通過身分驗證的人洩漏『這台機器沒有授權』」。
  - 實測：`PATH /api/uploads/x?pt=bad anon= 402 … {"detail":"這台機器尚未安裝授權金鑰，請聯絡供應商取得。","reason":"missing","code":"license_required"}`（沒有任何 token）。已登入的請求本來就看得到，所以只有未登入這一側是洩漏；內容是「授權的 reason 碼＋中文說明」，不含客戶名稱、機器指紋或模組。嚴重度低。
  - 建議：被擋且 `request.state.authed` 不是 True（沒有通過 session 驗證）時，回不帶 `reason` 的通用 402（或讓 uploads 處理函式先驗 `pt`，驗過才適用 402）；補一題「未登入＋`?pt=` ⇒ 402 body 不含 reason」。
- **LG-S2　每日一次的通行證／開發金鑰稽核，寫入失敗就整天沒有紀錄**：`LA:78-83` 的 `_once()` 在 `_emit` 之前就把今天標成已警告；`LA:37-53` 的 `_audit` 失敗只記 log。事件發生當下資料庫忙到逾時（這個專案有 30 秒 busy timeout 的前例），**ERROR log 還在，但 audit_log 那筆永遠補不回來**（直到隔天）。建議：`_audit` 回傳成敗，失敗時把 `_ALERTED[code]` 放掉讓下一個請求再試。
- **LG-S3　授權快取回傳的是淺拷貝，`modules` 清單共用**：LIC:313、325 `dict(status)`；`probe_pure.py` E1：呼叫端對回傳值的 `modules` 做 `append("*")`，**下一次 `verify_license()` 的 `modules` 變成 `['case','*']`**（污染一直持續到快取失效）。目前沒有呼叫端這樣做（`module_licensed` 只讀），但註解（LIC:312「回複本：呼叫端改了回傳值也不會污染下一個人」）宣稱的性質並不成立。建議改成 `tuple`／深拷貝，補一題。
- **LG-S4　回滾快照對 `license_emergency.key` 的待遇與 `license.key` 不同**：`apply_update.ps1:832`（建快照）、`:916`、`:922`、`:1211`、`:1213`、`:1218`（還原）與 `rollback_update.ps1:443`、`:445`、`:450` 的 robocopy `/XF` 清單都列 `license.key`，**沒有** `license_emergency.key`（`grep emergency backend/tools/*.ps1` 無結果）。後果（讀碼推論，沒有實際回滾驗證）：事故中新簽發的通行證，遇上回滾，會被快照裡**較舊**的那份蓋掉（若舊的已過期，等於通行證消失、又 402）。`verify_package.py:112/BAD` 以 `.key` 副檔名擋進包，所以不會被打進部署包，這一點沒問題。建議：兩處清單一起補 `license_emergency.key`，並讓既有「`/XF` 清單與 `.gitignore` 的 per-installation 檔一致」類守門涵蓋它（若沒有，補一題）。

### 觀察

- **LG-O1　開發金鑰與（未來的）正式金鑰同時受信**：LIC:382 兩把公鑰都試；`_PUBKEY_PROD` 仍是空的（LIC:74），**所以目前這個預設開的閘門，對任何握有開發私鑰的人沒有防護力**（開發私鑰在 `backend/tools/_license_private_key_dev.pem`，被 `.gitignore`；本機兩棵樹都沒有這個檔，我沒有它）。作者已在 LIC:507-508 與 `license_alerts.py` 檔頭記下「正式公鑰進來後部署包不要再帶 `_PUBKEY_DEV`」。建議把它變成守門而不是備忘：`verify_package.py`／建包在 `_PUBKEY_PROD` 非空時，發現 `_PUBKEY_DEV` 仍在就失敗。
- **LG-O2　時鐘回撥可以延長年費授權**：`_days_left`（LIC:246-253）與通行證日期判定（LIC:571）都用本機 `date.today()`。`probe_pure.py` E3：授權到期日 2026-01-02、把系統日期設成 2020-01-01 ⇒ `ok`。離線授權的已知限制；若威脅模型包含「客戶自己的管理員」，可在資料庫／稽核表記錄已見過的最大日期（高水位），`今天 < 高水位 − 1 天` 時當成 `clock_tampered`。是否值得做是產品裁示。
- **LG-O3　指紋會因「新增網卡」而漂移**：LIC:730-733 取 PCI／USB 網卡 MAC 排序後**最小**的那個；在伺服器插一張 MAC 較小的 USB 網卡就變了指紋 ⇒ `machine_mismatch`、整站 402。通行證是唯一出口。作者已處理過 TAP／藍牙（LIC:701-707），這一項是同類。建議在運維文件（LICENSE-EMERGENCY-PASS.md）明寫「伺服器不要插／拔網卡」，或讓 UUID 存在時只用 UUID（會改變指紋、需要既有金鑰重簽，所以是產品裁示）。
- **LG-O4　閘門只管 HTTP**：排程與背景工作（寄信、LINE 推播、心跳、標案雷達等）在授權中途到期時**不受閘門影響**，模組載入只在開機決定。作者的設計是「到期後重啟才停」；請確認這符合商業預期（年費到期後，已在跑的服務還會繼續寄信／推播到下次重啟）。
- **LG-O5　`/api/license/status` 對任何已登入角色都回 `machine`、`customer`、`modules`**（routers/licensing.py:40-71，只 `_require_user`）。指紋文件說明「不是祕密」，客戶名稱與模組清單也不算機敏，只是提醒：若日後要限制，這是唯一一支。
- **LG-O6　部署儀表板的兩份「代理標頭清單」各自維護**：`CIP:34、81`（`CLOUDFLARE_HEADERS`、`has_proxy_headers`）與 `DD:134-135`（`_PROXY_MARKER_HEADERS`）內容目前相符，`DD` 是刻意不 import helpers（DD:133）；但沒有題目守「兩份清單一致」，日後只改一邊會悄悄分歧。另外儀表板沒有 `Host`／`Origin` 檢查（DD 全檔 `grep -i origin` 只有一條註解），本機瀏覽器開著的惡意網頁（DNS rebinding）能讀 `/api/prod-status`、`/api/history` 等 GET；**寫入端 `/api/deploy`、`/api/rollback` 要在請求本文帶正式機的 OS 帳密**（DD:1522-1580），所以不是無憑證可部署。屬縱深防禦，不是這一輪的阻擋項。
- **LG-O7　HC1d 的邊界條件（確認過、不需動作）**：① `forwarded_allow_ips` 在四個 launcher 都釘 `127.0.0.1`（autostart.bat:31、restart.bat:40、start.bat:27、start_server.ps1:80）；`main.py:3` 的註解範例與 `STATE.md:7923` 的指令沒有釘，但 uvicorn 預設也是 `127.0.0.1`，只有環境變數 `FORWARDED_ALLOW_IPS=*`（例如容器）才會失效，已有 `test_every_launcher_that_binds_all_interfaces_pins…` 守。② 若隧道所在的 Cloudflare 設定關掉「移除訪客 IP 標頭」以外的轉換（例如移除 `CF-Connecting-IP`／XFF），`cf-ray`／`cf-visitor` 仍在，`_came_through_proxy` 仍判代理；但**登入鎖定**會因為對端 127.0.0.1＋沒有任何可信 IP，所有外部使用者共用「127.0.0.1」一桶（一個人輸錯 5 次鎖住所有人，包括本機）。這是設定面風險，列在隧道設定檢查表即可。

## 4. 回覆欄（被稽核者填；稽核者確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | 稽核者確認 |
|---|---|---|---|
| LG-M1 | 修正：指紋探測不完整時重試 3 次；`machine_mismatch` 改 60 秒短 TTL 快取 | b7d08799b | ✅ 關閉（§7） |
| LG-M1b | 修正：殘缺指紋不永久快取，退避 60 秒→5 分鐘→1 小時；兩項齊全或走機器 ID 後路才算穩定 | a75a51067、448313a58（題） | ✅ 關閉（§7） |
| LG-M2 | 修正：`verify_license`／`emergency_pass` 進 `run_in_threadpool`；`emergency_pass` 加快取 | b7d08799b、a75a51067（題）、448313a58（題的固件） | ✅ 關閉（§7） |
| IP-M1 | 修正：`rate_limit_key`（IPv6 取 /64）；`_rl_state` 加上限與逾時清理；稽核紀錄仍用完整位址。帳號維度鎖定未動（產品裁示，作者未改） | b7d08799b、a75a51067（題） | ✅ 關閉（§7）；帳號維度仍待產品裁示 |
| LG-S1～S4 | 未回覆（本輪未處理） | | ⏳ 待回覆（不阻擋 T80） |
| LG-S5 | accept，不卡這班車，列下一班待辦（理由：只在指紋持續讀不到的退化狀態觸發） | | ✅ 接受（併入 §6.1 備註的另一個入口） |
| LG-S6 | accept，排下一班 | | ✅ 接受 |
| LG-S7 | 修正：`rate_limit_key` 先展開 IPv4-mapped | a75a51067 | ✅ 關閉 |
| LG-O1 | accept，但須在「正式機實際部署 T80」之前完成（部署包移除 `_PUBKEY_DEV`）；記入上線前 checklist，與 license.key 就緒狀態一起追。`perpetual` 是刻意的，已與使用者確認 | | ✅ 接受；⚠️ **上線前條件**，未完成前不可部署到正式機 |
| LG-O2～O7 | 未回覆（觀察項） | | — |

## 5. 複驗（稽核者，2026-11-12；對象 `b7d08799b`，在基準 `ffd4b8a90` 之上，中間夾 `8a46893a3` 填入 `_PUBKEY_PROD`）

> 結論：**LG-M2 修好了；IP-M1 的主要洞（/64）修好了；LG-M1 只修了一半。三項都還不能關**——主因是**三個修正都沒有任何新題目**（`b7d08799b` 只動了 5 個檔，測試只改了 `test_licensing_core` 一處），我把每個修正個別還原，現有測試全部照綠（見下表）。我自己上一輪「補題」那條建議沒有被採納，所以關閉條件不變：要有會紅的題。

基準（`b7d08799b`，未突變）：上一輪 5 檔＋`test_totp`＋`test_conn_reaper_t80` 共 **224 passed**（約 68 秒）。

### 5.1 修正是否有效（`probe_pure.py` 的 C／D 改寫版＋`test_zz_audit16_probe.py` 的 `COLD`）

| 情境 | 修正前 | 修正後 | 判讀 |
|---|---|---|---|
| C：第一次指紋全空、之後恢復，**同一個金鑰檔** | 一直 `machine_mismatch` 到午夜／碰檔／重啟 | 60 秒內仍 mismatch（TTL 內），**TTL 過後 `ok`** | ✅ 達成 |
| D4：第一次只讀到一半、重試時讀到完整 | 殘缺指紋永久 | `ok` | ✅ 達成 |
| **D1–D3：三次探測都只讀到一半**（或 WMI 比 ≈3 秒慢） | 殘缺指紋永久 | **仍然永久**：`machine_fingerprint()` 仍回殘缺值並存進 `_FINGERPRINT_CACHE`；TTL 過後重算還是同一個錯值 ⇒ 持續 `machine_mismatch`，要重啟 | ❌ **LG-M1 剩下的部分（見 LG-M1b）** |
| 事件迴圈：冷指紋（假指令 3 秒／次） | `/api/ping` 2.44 秒 | 同一時間 `GET /`（靜態）**0.04 秒**；`/api/ping` 仍等（它要等授權判定），但不再是事件迴圈被擋 | ✅ LG-M2(a) 達成 |
| 被擋＋有效通行證，`emergency_pass` 每次 | 718–812 µs | **77 µs**（8 KB 垃圾檔 114 µs；無通行證檔 72 µs，因為多了兩次 stat 做快取鍵，比修正前的 28–40 µs 高，可以接受） | ✅ LG-M2(b) 達成 |
| 正常快取命中 | 43–63 µs | 38 µs（`verify_license` 本身；中介層多一次 threadpool 往返） | ✅ |
| IPv6 同 /64 三個位址的鎖定鍵 | 三個不同字串 | `2001:db8:1:2::/64`（單一桶）；IPv4 原樣 | ✅ IP-M1 主要洞達成 |

> 撤回一項顧慮：我一度擔心「每個請求都 `await run_in_threadpool`」讓公開端點多一個對 threadpool 的依賴。實測（45 個同步慢處理函式占滿 threadpool，量 `/api/ping`）**基準 `ffd4b8a90` 就已經 3.26 秒、修正後 3.33 秒**——不是這次修正造成的，不列為發現。

### 5.2 新發現（都不大，但 LG-M1b 要處理）

- **LG-M1b（必修，LG-M1 的殘餘）　殘缺指紋仍永久快取**：`licensing.py` 的 `machine_fingerprint()` 重試 3 次後，只要最後仍是「只有 UUID」或「只有 MAC」，就把它存進 `_FINGERPRINT_CACHE`（行程內永久）。重試只改變「剛好慢一點點」的機率，沒有改變「慢到超過 ≈3 秒」或「某一項持續讀不到」時的結局。建議：殘缺結果不進永久快取，而是帶 TTL（例如 60 秒，之後退避到 5 分鐘、1 小時）重新探測；真的長期只有一項來源的機器（部分 VM 的 UUID 是 `_USELESS_UUIDS`）也能自我收斂到穩定值，每次探測是 threadpool 內的一次 PowerShell，成本可接受。
- **LG-S5（建議）　指紋仍在失敗時，TTL 到期的瞬間沒有 single-flight**：`_verify_license_file` 沒有鎖。實測（`_windows_hardware` 睡 0.3 秒並持續回空、30 個並行 `verify_license` 在 TTL 剛過時進來）：**30 次各自重算、共 90 次硬體探測**（正式機＝90 個 PowerShell，每個 1–數秒，會占滿 threadpool 的 40 個執行緒）。只發生在「指紋持續讀不到」的退化狀態，每 60 秒一次。建議加一把鎖或「已有人在算就回上一次的結果」。同理冷啟動（無金鑰開機後放金鑰）時所有並行請求各自探測。
- **LG-S6（建議）　`_rl_state` 上限是軟的**：`_rl_prune_locked` 只在 `len > 10000` 時清**沒鎖定且 1 小時沒失敗**的列；一小時內來的新列不會被清，所以「一小時內灌 10 萬個不同 /64」仍會長到 10 萬列，而且超過上限後**每次失敗登入都掃整張表**（O(n)，持鎖）。攻擊者要有大量不同前綴（/48 有 65 536 個 /64），比修正前難很多，列建議即可。硬上限＝超過就淘汰最舊的。
- **LG-S7（建議，潛在）　`rate_limit_key` 沒處理 IPv4-mapped IPv6**：`::ffff:1.2.3.4` 與 `::ffff:5.6.7.8` 都變成 `::/64`——全部 IPv4 用戶端共用一個桶（一個人輸錯 5 次鎖住所有人）。`client_ip()` 從 `CF-Connecting-IP` 取值時會先解 mapped，但對端位址路徑（`return peer`）不會；目前四個 launcher 都綁 `0.0.0.0`（IPv4 socket，對端是純 IPv4），所以**現在不會發生**，改綁 `::`（雙棧）才會。一行 `addr.ipv4_mapped` 就能補。
- **LG-O1 升級（建議，上線前決定）**：`8a46893a3` 已填入 `_PUBKEY_PROD`，但 `_PUBKEY_DEV` 仍在、仍受信（`licensing.py:382` 兩把都試）。現在這個閘門的實際強度＝「開發私鑰與正式私鑰兩者中最弱的那一把的保管」。握有開發私鑰的人可以對正式機指紋 `93ece768770e4ccd` 簽出一把 `env=dev` 的授權，結果只有橫幅（`dev_key`）與一筆每日稽核，**不擋**。我不知道開發私鑰在哪些機器上。建議在建包／`verify_package.py` 加：`_PUBKEY_PROD` 非空時，部署包內的 `_PUBKEY_DEV` 必須被移除或置空（作者在 `licensing.py` 的註解已寫成備忘，現在是時候變成守門）。另外請確認該筆授權簽成 `perpetual` 是預期：永久授權過期**不擋**，只剩維護期提示。

### 5.3 突變：把每個修正還原，現有測試是否會紅（結果：全部存活 ⇒ 沒有題目守這些修正）

| 突變（修正被還原成什麼） | 跑的測試 | 結果 |
|---|---|---|
| M1 `machine_mismatch` 又整天快取（`if True:`） | gate／emergency／core／em6 共 127 題 | 🟢 **存活** |
| M2 `_FP_PROBE_RETRIES = 1`（不重試） | core／em6 共 29 題 | 🟢 **存活** |
| M3 `rate_limit_key` 不再取 /64 | trusted_client_ip／totp／system_audit 共 82 題 | 🟢 **存活** |
| M4 `emergency_pass` 快取鍵拿掉 `status.reason` | emergency 63 題 | 🟢 **存活**（鍵變弱沒人發現） |
| M5 `await run_in_threadpool(verify_license)` 還原成同步 | conn_reaper＋gate 共 57 題 | 🟢 **存活**（LG-M2 回退沒人發現） |

每次突變後 `git checkout` 還原，`git status` 乾淨。

### 5.4 關閉條件（稽核者會確認的項目）

1. **LG-M1／LG-M1b**：題目——`_windows_hardware` 先回空／殘缺、再回完整 ⇒ 同一個金鑰檔在 TTL 後 `ok`；**三次探測都殘缺、之後完整 ⇒ 最終 `ok`**（目前紅）。突變 M1、M2 要紅。
2. **LG-M2**：題目——仿 `test_async_middleware_writes_do_not_block_the_event_loop`，冷指紋（假指令睡 ≥1 秒）時同迴圈心跳最大間隔 <0.6 秒；被擋＋通行證時同樣。突變 M5 要紅。`emergency_pass` 快取題：換通行證檔／授權檔／日期／`status.reason` 各要重算；突變 M4 要紅。
3. **IP-M1**：題目——同 /64 不同位址連續失敗第 5 次起 429；IPv4 不受影響；稽核紀錄仍是完整位址；`_rl_state` 超過上限會被清。突變 M3 要紅。
4. 建議項（LG-S5～S7、LG-O1）可在回覆欄表態，不阻擋關閉。

## 6. 第二次複驗（稽核者，2026-11-12；對象 `a75a51067`）

> 結論：**程式修正全部成立**（LG-M1、LG-M1b、LG-M2、IP-M1、LG-S7 都用函式層級實測確認）；補的題殺得掉 §5.3 的 M1／M2／M3／M4／M5＋新增的 M3b、M7'。**剩兩件事要處理才能關：①新測試檔會讓同一個 pytest 行程裡之後所有用 `client` 的測試全部 error（必修，一個字就能修）；②LG-M1b 的核心邏輯（殘缺 ⇒ 不永久快取）仍有突變存活（M6、M8）。**

### 6.1 程式修正（`a75a51067`，已逐項實測）

| 項目 | 實測 | 判讀 |
|---|---|---|
| LG-M1b 殘缺不永久快取 | 三次探測只有 MAC ⇒ `stable? False strikes 0`；60 秒內回同一個殘缺值；撥過 61 秒、硬體完整 ⇒ 升級為穩定值（`True`）；再次殘缺過期 ⇒ `strikes` 加 1 | ✅ |
| LG-S7 IPv4-mapped | `rate_limit_key("::ffff:1.2.3.4")` 現在回 `1.2.3.4`（`test_rate_limit_key_unwraps_ipv4_mapped…` 守） | ✅ |
| LG-M1／LG-M2／IP-M1 | 與 §5.1 相同，行為未變 | ✅ |

小備註（不阻擋）：`machine_fingerprint()` 在「先前已快取殘缺值、退避已過、這次探測**全空**」時會丟 `RuntimeError`，而快取沒更新（`cached_at` 仍是舊的、退避仍是過期）⇒ **之後每次呼叫都重新探測**（3 次探測＋2×1.5 秒睡眠），直到有一次探測成功。外層 `_verify_license_file` 的 60 秒 TTL 擋掉大部分，但與 LG-S5（沒有 single-flight）疊在一起。這是 LG-S5 的另一個入口（讀碼推論，未另做實測），修 S5 時一起處理即可。

### 6.2 新測試檔 `test_t80_audit16_fixes_2026_11_12.py`

**必修（測試檔本身）：`test_lgm2a_cold_license_check_does_not_block_the_event_loop` 沒有要 `client`／`_app` 固件就直接 `import main`**，會讓同一個 pytest 行程裡之後每個用 `client` 的測試噴
`Failed: main.py was already imported before the integration-test fixture could patch its file paths…`（BK19 類守門）。
- 重現（在 `a75a51067`，serial）：`pytest tests/test_t80_audit16_fixes_2026_11_12.py tests/test_trusted_client_ip_2026_11_11.py` ⇒ `52 passed, 6 errors`；`pytest "tests/test_t80_audit16_fixes_2026_11_12.py::test_lgm2a_…" tests/test_licensing_gate_2026_09_21.py` ⇒ `5 passed, 31 errors`。再加上 emergency／core／totp／conn_reaper 的大集合跑出 `106 passed, 131 errors`。
- 為什麼會漏掉：全量按字母序時，`test_t80…` 之前已經有別的檔經 `client` 固件匯入 `main`，所以不會紅；但 xdist 分 worker、modtest 的差異題選題、或單獨／少數檔案執行時，只要這個檔案是某個行程第一個碰 `main` 的，後面就全爆。這是「順序相依」的問題，不是產品壞了。
- 修法（一個字，我已驗證）：簽名改成 `def test_lgm2a_cold_license_check_does_not_block_the_event_loop(client, monkeypatch):`（比照 `test_conn_reaper_t80` 同類題）。改完同樣兩個指令 ⇒ `88 passed`。我沒有把這個改動 commit 進你的分支。

### 6.3 突變（對 `a75a51067`；跑 `test_licensing_core`＋新檔＋`test_trusted_client_ip`，基準 85 passed；每次 `git checkout` 還原，`git status` 乾淨）

| 突變 | 結果 | 轉紅的題 |
|---|---|---|
| M1 mismatch 又整天快取 | 🔴 紅 | `test_lgm1_machine_mismatch_is_cached_only_for_a_short_ttl` |
| M2 `_FP_PROBE_RETRIES = 1` | 🔴 紅 | `test_lgm1b_three_partial_probes_are_not_cached_permanently` |
| M3 `rate_limit_key` 不取 /64 | 🔴 紅（2 題） | `test_rate_limit_key_aggregates_ipv6_to_slash_64`、`test_login_lockout_shares_one_bucket_across_the_same_v64_but_not_across_v4` |
| M3b 不展開 IPv4-mapped | 🔴 紅 | `test_rate_limit_key_unwraps_ipv4_mapped_ipv6_before_decidin_v4_vs_v6` |
| M4 `emergency_pass` 快取鍵拿掉 `status.reason` | 🔴 紅 | `test_lgm2b_emergency_pass_cache_recomputes_when_status_reason_changes` |
| M5 `verify_license` 還原成同步 | 🔴 紅 | `test_lgm2a_cold_license_check_does_not_block_the_event_loop` |
| M7' 退避改成 `(-1,)`（退避期內也重探） | 🔴 紅 | `test_lgm1b_three_partial_probes_are_not_cached_permanently` |
| **M6 `is_stable = True`（殘缺值當穩定、永久快取，＝LG-M1b 還原）** | 🟢 **存活** | —（85 passed） |
| **M8 退避不升級（永遠 `_FP_PARTIAL_BACKOFF_S[0]`）** | 🟢 **存活** | — |
| M7 退避改 `(0,)` | 🟢 存活，但這是 Windows `time.monotonic()` 解析度（約 15 ms）讓 `差 <= 0` 偶爾成立，突變本身太弱；換 `(-1,)`（M7'）就紅，不算漏洞 | — |

M6、M8 存活的原因：三題 LG-M1b 的題目裡，第一題只驗「重試 3 次、退避內不重探」（永久快取與否它看不出來，因為兩種實作第二次呼叫都回同一個值）；第三題**手動塞**一個 `is_stable=False` 的快取列再驗升級，沒有走 `machine_fingerprint()` 自己存進去的那一列。
補題建議（一題就夠 M6＋M8）：用真實流程——殘缺×3（`_probe_hardware_once` 回只有一半）⇒ 讀 `lic._FINGERPRINT_CACHE`，斷言 `is_stable is False`、`strikes == 0`；把 `cached_at` 撥早 61 秒、硬體仍殘缺 ⇒ `strikes == 1`；再撥早 61 秒（<300）、硬體完整 ⇒ **不重探**（退避已升級到 300 秒）；撥早 301 秒 ⇒ 重探並升級為 `is_stable is True`。

### 6.4 關閉判定

| # | 判定 | 條件 |
|---|---|---|
| LG-M1 | ✅ 關閉 | M1 被抓到；情境 C 實測恢復 |
| LG-M2 | ✅ 關閉（待 §6.2 修好測試檔） | M4、M5 被抓到；`COLD` 實測事件迴圈不再被擋 |
| IP-M1 | ✅ 關閉 | M3 被抓到；/64 實測 |
| LG-S7 | ✅ 關閉 | M3b 被抓到 |
| LG-M1b | ⏳ **程式 ✅、題目未收**（M6、M8 存活） | 補 §6.3 那一題即可關 |
| §6.2 測試檔 `client` 固件 | ❌ 未關（必修） | 一個字；修完請把兩個指令重跑 |
| LG-S5、LG-S6、LG-O1 | 作者表態先不動；`perpetual` 是刻意且已與使用者確認 | 不阻擋 T80；請在回覆欄寫明「接受／不修＋理由」，我會依此標記 |

## 7. 第三次複驗（稽核者，2026-11-12；對象 `448313a58`，與 `a75a51067` 只差測試檔）

- 兩個重現指令都乾淨：新檔先跑→`test_trusted_client_ip` **58 passed**（之前 52 passed／6 errors）；`::test_lgm2a_…` 先跑→`test_licensing_gate` **36 passed**（之前 5 passed／31 errors）。含 emergency／core／em6／dashboard／totp／conn_reaper 的大集合 **237 passed**（之前 106 passed／131 errors）。
- 突變（跑 core＋新檔＋trusted_client_ip，基準 85 passed；每次 `git checkout` 還原，`git status` 乾淨）：

| 突變 | 結果 | 轉紅的題 |
|---|---|---|
| M6 殘缺值當穩定 | 🔴 紅 | `test_lgm1b_strikes_escalate_the_backoff_instead_of_caching_forever` |
| M8 退避不升級 | 🔴 紅 | 同上 |
| M1／M2／M4／M5／M3 | 🔴 全紅 | 與 §6.3 相同的題 |
| M9 穩定快取被忽略（每 60 秒重探一次） | 🟢 存活 | —（見下） |

- M9 存活是個小缺口，**不阻擋**：「穩定結果快取到行程結束」目前只被驗到「同一瞬間不重探」，沒有驗「撥過一小時仍不重探」。實際後果只是每分鐘多一次探測（threadpool 內），不是正確性問題；有空時在 `test_lgm1_all_empty_then_full_recovers…` 後面加一段「`cached_at` 撥早 7200 秒，再呼叫仍不探測」即可。
- 結論：**LG-M1、LG-M1b、LG-M2、IP-M1、LG-S7 全部關閉。** 其餘見 §4 回覆欄。**唯一的上線條件是 LG-O1**（正式機實際部署 T80 之前，部署包不可再帶 `_PUBKEY_DEV`；`_PUBKEY_PROD` 已填入，現在閘門的實際強度取決於開發私鑰的保管）。LG-S1～S4 本輪沒有回覆，不阻擋，但請在下一班前表態。

## 附錄：重現檔

- `docs/platform/audit/AUDIT-16-probes/probe_pure.py`：純 Python，A（正常成本）、B（被擋＋通行證成本）、C／D（LG-M1）、E1（LG-S3）、E2（IP-M1）、E3（LG-O2）。指令見檔頭。
- `docs/platform/audit/AUDIT-16-probes/test_zz_audit16_probe.py`：三題 pytest（路由清單、23 條路徑試探、`COLD` 事件迴圈量測）。要借 `backend/conftest.py`，複製進 `backend/tests/` 才能跑，**跑完刪掉、不要 commit**。指令見檔頭。
- 環境提醒：手動跑 pytest 要 `MOTRIX_TRAIN=1`、`PYTHONUTF8=1`，`TMP`／`TEMP` 與 `--basetemp` 都放在 `D:\Claude-pm\` 底下（BK19 守門）。
