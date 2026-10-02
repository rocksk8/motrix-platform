# 建包優化項 3：依賴指紋增量段（設計＋重放＋風險）

> 範圍：唯讀設計與探針；未跑 pytest／建包，未動 `build_deploy_package.ps1` 與 D:\MOTRIX-PLATFORM。
> 證據標記：**[已讀]** 讀程式／文件；**[實測]** build log、fail_stream JSONL、git；**[推論]** 由實測外推的估算。
> 重放與統計腳本在 session scratchpad（`replay.py`／`final.py`／`recall.py`／`floor.py`），純 git＋靜態分析，**不執行任何測試**。

---

## 0. 結論先行

1. **增量可行，但效益比 BUILD-OPTIMIZATION-2 §3 項 3 寫的小**：典型「小改重建」非 e2e 26～28 分 → **10～12.6 分**（省 15～18 分 [推論]），e2e 視動到什麼：0～6.6 分。不是 38 → 8。原因：**一定要跑的底板（契約目錄 `tests/platform`＋全域釘子＋unmapped）本身 ≈ 10 分**（8 分是 tests/platform 145 檔；原文件估 4 分不成立）。
2. **兩班重放（t29＋t30，14 個測試段，共 296 分）**：保守版（基準＝同段最後一次全綠）省 **76 分**，建議版（基準＝同段最後一次跑完、紅過的檔重選）省 **92 分（31%）**；若「出貨包必須是真全量」則建議版只省 **52 分**。現行 scope_gate 規則原封不動（`tools/**`、`frontend/static|js/**` 皆底層⇒全量）只省 **0（保守版）～35 分（建議版）**。[推論，邊界見 §3.3]
3. **召回**：兩班的 7 組紅（26 個紅檔）以「test_map 選題＋底板」重放，**漏 2 個**：①`test_frontend_local_date`（用 `os.listdir` 掃整個 frontend 目錄，test_map 只記到兩個 js 單位）②`test_audit_search::perf`（負載下的偶發，與 diff 無關）。①補進「掃目錄型」底板（27 檔、0.8 分）後可達 100%；②不是依賴問題，由「基準那次紅的題重選＋known_flakes」處理。**目前的 test_map 單獨用不達標，必須加底板與掃描型補丁。**
4. **一定要跑的底板**：`tests/platform/**`（145 檔）＋`bottom_layer.json` 的 `global_tests`（41 檔）＋test_map unmapped（12 檔）＋掃目錄型（27 檔）＝ **~11.4 分（含 0.5 分段開銷）**；其中 9 個「測工具的演練」（~2.5 分）可改成依賴鍵控，**無條件底板 ≈ 8.8 分**。
5. **阻塞**：接進建包要動 `build_deploy_package.ps1`（等使用者套用第 30 包）；且任何 `tools/**`、`backend/tools/**`、`bottom_layer.json` 的 commit 都會讓第 30 包的指紋失效，故**合進 `platform` 要等第 30 包上機後**；分支上的工具＋離線重放＋dry-run 台現在就能做。

---

## 1. 現行機制（[已讀]，file:line）

### 1.1 scope_gate（`tools/platform/scope_gate.py`）
- **目的**：正式機基準 P → 候選 X 的改動檔「一個都不在底層」⇒ 以範圍驗證代替全量（:1-14；PLAYBOOK §D-1a，docs/platform/PLAYBOOK.md:134）。
- **基準固定是正式機 tag**：`trusted_base()`（:259）取最新 `prod/<sha>`；X 上 `_prod_baseline.py` 的 BASELINE 必須等於它（`assess` :287-305），否則 `_full(...)`（:282）＝全量。候選自己不能把基準往後移。
- **「底層 ⇒ 全量」**：`classify_path`（:110）依 `tools/platform/bottom_layer.json` 規則**由上而下第一條符合者**決定；**沒有規則符合 ⇒ bottom（fail closed）**。`decide`（:127）只要有一個 bottom ⇒ `mode="full"`。bottom 規則：`**/conftest.py`、`backend/pytest.ini`、`requirements*`、`modules/*/migrations/**`、`backend/core|helpers|routers/**`、`db.py`、`main.py`、`backend/tools/**`、**`tools/**`**、`product/**`、`frontend/static|js|css|fonts/**`、`frontend/index.html`、`backend/*`；`{PAGES}/*` 只在「恰好一個模組宣告」時是 page 層，否則共用頁⇒底層。
- **選題**：`select_tests`（:326）＝`modtest.select(改動檔∪消費端, load_map, load_graph, None)`（**iface=None＝全部遞移，閘門寧寬**）＋規則附帶題（`global_tests`、VR 守門題）。`ship_tier.provider_check` 找提供者的消費端，判不了⇒全量（:300-308）。
- **閘門**：`gate`（:356）先看紀錄在不在，再現場重算 `assess`＋選題，`judge`（:143）逐項比對（commit、base、模組集合、config sha、題目 ⊇ 重算、兩段 exit），任何對不上⇒不接受。建包 Step 3 經 `_scope_gate.ps1::Get-ScopedGateResult` 呼叫（build_deploy_package.ps1:767-775）。

### 1.2 test_map（`docs/platform/test_map.json`，產生器 `tools/platform/test_map.py`）
- **[實測]** 1000 個**測試檔**（不是逐題）；`kind`：api 541／e2e 241／audit 130／unit 88；unmapped 12；`units` 出現次數：mod 1414、file 1222、dir 774、core 704、plat 581、page 549、router 503、helper 404、js 134。
- 單位命名 `unit_name`（test_map.py:70）：`router:/helper:/core:/plat:/mod:<key>/<檔>/page:/js:`，其餘 `file:<路徑>`、`dir:<目錄>/`。證據 `evidence` 分 import／api／page／path／module_dir。**靜態分析，對不到列 unmapped、不猜。**
- 測試怎麼對到單位（`modtest.select` :520-600）：改動檔→單位→`reverse_closure`（:293）沿 imports／routers_called 反向遞移（`core:main` 是彙整點不往上傳）＋資料表一跳 `table_hop`；`audit` 類只看**直接**單位（讀原始碼本身）；`dir:` 單位＝該目錄下任一檔變就中（:566-570）；api/e2e 經 fixture 隱含 `core:main`。**契約目錄 `backend/tests/platform`、`backend/core/tests` 永遠加入**（:571-576，`CONTRACT_DIRS` :64）。`FIXTURE_LAYER`（:54）改到 ⇒ need_full。
- **寬 `dir:` 單位（[實測]）**：`dir:backend/modules/` 38 檔、`dir:frontend/pages/` 39、`dir:frontend/js/` 23、`dir:tools/platform/` 48、`dir:docs/platform/` 27、`dir:backend/` 8——這是 test_map 對「掃目錄」型測試的既有防線，但只在測試**用字面路徑**時才記得到（見 §4）。

### 1.3 build_test_reuse（`backend/tools/build_test_reuse.py`）
- **指紋＝整棵樹**：`fingerprint`（:83）＝`ls-tree -r HEAD`（扣 REUSE_EXCLUDE＝`known_flakes.json` 等）sha256＋環境（Python、pip freeze、playwright、瀏覽器、`MOTRIX_*`）。工作樹不乾淨⇒None。任一檔變⇒兩段指紋全不同。
- 段沿用 `find_reusable_stage`（:126）：同指紋、**帶該段**的最新一筆、綠、同日、12 小時內；舊格式兩段同結果。寫入者只有建包與 `modtest --full`（乾淨樹、無縮小參數；`record_full_run` :234）。紀錄 `commit` 只存 8 碼（build_deploy_package.ps1:740）。
- 建包呼叫：:693 指紋、:704 `lookup-stage`、:737-740 `record-stage`。

### 1.4 modtest 怎麼用上面三者（tools/platform/modtest.py）
`--dry-run [--list]` 只印選題；`--train`（:739 `run_train`）＝①差異題②`tests/platform` 全部（`MOTRIX_TRAIN=1`，`-rs`）③「是否最新」三題不得 skip／收集不到（`train_judge` :720）；`--full`（:1221 `run_full`）＝兩段全量並寫沿用紀錄；`scope_gate.run` 同型但基準是 prod tag；`module_update.ship_tests` 以子行程 `modtest --dry-run --json` 取選題。**modtest 預設用 `iface_checker`（§C-11a 介面沒變只到直接依賴）縮小；scope_gate 傳 None＝遞移（寬）。**

### 1.5 為什麼夜間重建迴圈今天用不到它 [已讀＋實測]
1. 基準是 **prod tag**（t29 的 0bb4834e、t30 的 47db5613）。第 29 班首次建包 P→X＝217 檔、**29 檔在底層**；第 30 班 91 檔、11 檔在底層（含 `backend/conftest.py`、`backend/core/**`）⇒ 整段 `full`。每一輪重建的基準不會往前挪。
2. 規則把 `tools/**`、`backend/tools/**`、`frontend/static|js/**` 都當底層：t29e（只 3 檔，其中 `tools/platform/flaky_retry.py`）、t30d（6 檔，`frontend/static/notif.js`）、t30e/f（`frontend/js/case-management-dispatch.js`）**單看重建 diff 也被判全量**。
3. 範圍驗證紀錄綁 commit＋prod 基準（`gate` :356）；重建每次 commit 都變 ⇒ 要重跑 `scope_gate.py run`，而它同樣以 prod 為基準。
4. 沿用指紋整樹雜湊 ⇒ 改 1 個測試檔也失效（9 份 log 零次沿用）。

---

## 2. 設計：依賴指紋增量段

### 2.1 一段的內容
```
incremental(stage) = floor ∪ selected ∪ red_reselect          （要跑）
carried            = collected − (要跑)                        （沿用基準的綠）
不變式：selected ∪ floor ∪ red_reselect ∪ carried ⊇ collected   （缺口⇒擋）
```
- **基準 G（每段各自）**：同環境、同日、12 小時內、**該段最近一次「跑完」的紀錄**（建議版 B）；保守版 A 只認「該段綠」。紀錄鏈長 ≤ 2、鏈根必須是該段**真全量**（同 §3 項 3 原文）。G 的紅檔（`failed`／`error` 的 nodeid 所屬檔）一律 `red_reselect`——因為紅過的題沒有「綠」可沿用。
- **selected**：`diff(G, HEAD)` 經 test_map（`modtest.select`，建議 `iface=None` 先求寬）＋規則附帶題＋改動的測試檔＋**unmapped 全選**。
- **強制全量 ⇒ 該段全量**：見 §5.2。
- **per-stage 指紋**（取代整樹雜湊，仍保留整樹雜湊供全量沿用）：對每個測試檔 t 算 `dep_fp(t)＝sha256(env_sha ‖ blob sha of {t 本身, unit→路徑展開(test_map.units(t)), FIXTURE_LAYER 檔, selector_sha})`；`dir:` 單位展開成該目錄 `ls-tree`。段指紋＝所選檔 `dep_fp` 的排序雜湊。**兩條獨立推導互證**：`selected`（diff 路徑）必須 ⊇ `{t : dep_fp(t, HEAD) ≠ dep_fp(t, G)}`（指紋路徑）；兩者不一致＝test_map／圖有洞⇒擋。
- `selector_sha＝sha256(scope_gate.py, modtest.py, test_map.py, dep_scan.py, bottom_layer.json, 本段 stage_select 程式)`：選題邏輯自己變⇒全量（自我指涉防線）。

### 2.2 紀錄要存什麼（擴充 `test_results.jsonl` 的 `stages.<段>`；舊格式讀得懂、新欄位缺⇒當不可增量）
```
stages.not_e2e = {
  green, tested_at, flaky_retried[],
  mode: "full" | "incremental",
  commit40, tree_sha, env_sha, selector_sha,
  base:  {commit40, record_ref, chain_depth, root_commit40},   # 增量才有
  collected: {count, nodeid_sha256},       # 全量與增量都存（--collect-only 或 fail_stream summary）
  selected:  {files[], count, nodeid_sha256, reasons{file: [unit...]}},
  carried:   {files[], count, from_record, dep_fp{file: sha}},
  floor:     {files[], count},
  red_reselect: {files[]},
  ran:       {passed, failed, errors, skipped, fail_stream_run},
  forced_full_reason: null | "..."
}
```
- manifest `verification.stages.<段>` 同形，另寫 `selected/carried/collected` 三個計數與 sha，儀表板可顯示「這一包 26% 實跑、74% 沿用自 <commit>」。
- 不可偽造性沿用 W4 規則：紀錄須有對應 fail_stream summary（`invocation_args`、`collected`），且閘門**現場重算**選題與 `dep_fp`，紀錄只能 ⊇ 重算結果。

### 2.3 e2e 怎麼處理
- 選題＝test_map 的 `page:`／`js:` 單位＋模組單位（`mod:`）：改到的頁面、經 `routers_called` 呼叫到的頁面、改到的 `frontend/js/<頁>.js` 的 e2e。**共用前端檔（`static/notif.js`、`auth-guard.js`）會拖進幾乎所有 e2e**（重放：t30d 的 notif.js ⇒ e2e 693／754 題＝92%），這是正確的，不要為了省時縮小。
- e2e 底板（小）：`tests/platform` 內 2 個 e2e 檔、`global_tests` 內 2 個、`test_module_registry`／`test_walk_batch_small` 2 個、加一個登入送簽冒煙（`test_e2e_playwright_2026_09_07::test_login_create_submit_approve_smoke`，單題 ~47 s）＝約 0.4～1.5 分。
- **e2e 的基準要用「該段最後一次跑完」而非「最後一次全綠」**：e2e 在非 e2e 綠之後才跑、又常紅（t29c 紅、t30c 紅、t30d 紅），保守版 A 在 14 段中幾乎找不到 e2e 綠基準（只有 t30f 之前的 t29f，且與之差異含底層）；建議版 B 才有 t30d/t30f 兩段增量。
- e2e 偶發（逾時型：t29c 的登入冒煙 45 s、t30d 的 leaflet／dispatch 逾時）由 flaky_retry／known_flakes 處理，不屬增量判定。

### 2.4 與項 1（fail-fast）並用
增量段只縮小 `collected`；`failfast.py` 的「先跑最可能紅的」＋停止條件照用（排序只改順序）。`aborted_by=failfast` 的段**不寫綠、不當基準**，但其「已通過的檔」不得當 carried 來源（沒跑完的段 `ran` 不完整⇒基準只認跑完的）。

---

## 3. 以 t29／t30 真實資料重放

### 3.1 資料與方法
- **[實測] 建包序列**（log＝`%TEMP%\build_t29*.log`／`build_t30*.log`；commit 取自各 log 的 `Commit:` 行）：
  t29：fca93b04（#1，非 e2e 紅）→272f57cc（t29b，無測試）→9f19563d（t29c，非 e2e 綠／e2e 紅）→a34747de（t29d，無測試）→0ebe7eac（t29e，非 e2e 紅）→47db5613（t29f，綠；**＝prod/47db5613 上機**）。
  t30：d939a9b4（無測試，版本紀錄擋）→8b87c5c1（t30b，非 e2e 紅）→0d4db8aa（t30c，非 e2e 綠／e2e 紅）→8d658078（t30d，非 e2e 綠／e2e 紅）→c7977514（t30e，非 e2e 紅，**只 1 題**）→6b5d2865（t30f，綠）。
  比 BUILD-OPTIMIZATION-2 多了 t30d、t30e、t30f（該文件寫成時尚未結束）。無測試結果的 4 次呼叫不計入。
- 相鄰 commit 的 diff 以 `git diff --name-only` 取得；選題以**該 commit 上提交的** `docs/platform/test_map.json`／`dep_graph.json` 跑 `modtest.select`（`iface=None`，寬）＋底板；單位／規則以 X 上的 `bottom_layer.json` 判層。
- **耗時模型 [推論]**：每檔題數＝靜態計 `def test_` × 校正係數（非 e2e ×1.30、e2e ×0.96，對齊收集 8022／754）；每檔秒數＝已知的（fail_stream summary 的 `slowest_files`，6 次建包聯集 60 檔，取中位數）否則 `題數 × 殘差均秒`（非 e2e 0.60 s／題、e2e 3.3 s／題，殘差＝(段牆鐘×4 − 已知檔秒)／剩餘題數）；段牆鐘 ＝ 段開銷（非 e2e 20 s、e2e 30 s，估）＋ worker‑秒／4。**驗算**：全量加總 6310／2776 worker‑秒，對實測 6224／~2760（誤差 <2%）。
- **兩種基準**：A＝同段最後一次**綠**（無⇒全量）；B＝同段最後一次**跑完**，其紅檔重選（無⇒全量）。**兩種分層**：S＝現行 scope_gate（底層⇒全量）；M＝**只有「硬底層」⇒全量**（`conftest`／`pytest.ini`／`requirements`／`core/**`／`helpers/**`／`db.py`／`main.py`／`routers/**`／`migrations`／`product/**`／`index.html`），`tools/**`、`backend/tools/**`、`frontend/static|js|css` 走 test_map（unmapped⇒全量）。首輪（基準＝prod tag）P→X 都含硬底層⇒全量，與現況相同。

### 3.2 每個測試段（建議版 B·M；括號為 A·M）
| 段 | commit | 實際 [實測] | 基準 | 選到題數占比 | 增量估計 [推論] | 省 |
|---|---|---|---|---|---|---|
| t29#1 非e2e | fca93b04 | 26:00 | prod 0bb4834e（29 檔硬底層） | 全量 | 26:00 | 0 |
| t29c 非e2e | 9f19563d | 25:58 | fca93b04（20 檔，3 頁＋5 模組） | 92% | 24:12 | 1:46（A：全量 0） |
| t29c e2e | 9f19563d | 11:35 | 無（e2e 從未跑完） | 全量 | 11:35 | 0 |
| t29e 非e2e | 0ebe7eac | 27:22 | 9f19563d（3 檔：flaky_retry.py＋2 測試） | 35% | 10:42 | **16:40**（S：全量 0） |
| t29f 非e2e | 47db5613 | 27:53 | 0ebe7eac（1 測試檔＋重選 audit_search） | 34% | 10:12（A：10:48） | **17:41** |
| t29f e2e | 47db5613 | 12:05 | 無 | 全量 | 12:05 | 0 |
| t30b 非e2e | 8b87c5c1 | 25:40 | prod 47db5613（91 檔，11 硬底層） | 全量 | 25:40 | 0 |
| t30c 非e2e | 0d4db8aa | 26:24 | 8b87c5c1（13 檔：case＋subcontract 模組、1 頁、1 backend/tools） | 87% | 22:40 | 3:44（A：全量） |
| t30c e2e | 0d4db8aa | 11:13 | prod（硬底層） | 全量 | 11:13 | 0 |
| t30d 非e2e | 8d658078 | 26:20 | 0d4db8aa（6 檔：notif.js＋5） | 45% | 12:36 | **13:44** |
| t30d e2e | 8d658078 | 11:39 | 0d4db8aa（重選 4 紅檔；notif.js 拖進 92% e2e） | 92% | 11:05 | 0:34（A：全量） |
| t30e 非e2e | c7977514 | 27:44 | 8d658078（3 檔：dispatch js＋2 測試） | 42% | 12:04 | **15:40** |
| t30f 非e2e | 6b5d2865 | 25:23 | c7977514（1 測試檔＋重選 classification） | 34% | 10:06（A：12:04） | **15:17** |
| t30f e2e | 6b5d2865 | 10:47 | 8d658078（3 檔） | 30% | 4:13 | **6:34**（A：全量） |

**合計**（14 段）：

| 版本 | 第 29 班 131 分 → | 省 | 第 30 班 165 分 → | 省 | 兩班 296 分 → | 省 |
|---|---|---|---|---|---|---|
| **B·M 建議版** | 94.7 | 36.1 | 109.6 | 55.6 | 204.3 | **91.8（31%）** |
| A·M 保守基準 | 97.1 | 33.8 | 122.5 | 42.7 | 219.6 | **76.5（26%）** |
| B·S（現行分層、B 基準） | 111.4 | 19.5 | 149.9 | 15.3 | 261.3 | 34.8（12%） |
| A·S（現狀規則＋保守基準） | 130.9 | 0 | 165.2 | 0 | 296.1 | 0 |
| **B·M 但出貨包（t29f、t30f）強制全量** | | 18.4 | | 33.7 | | **52.1（18%）** |

### 3.3 實測 vs 估算與假設（必讀）
- **[實測]**：各段實際分鐘、commit、diff 檔案清單、test_map／bottom_layer 分層判定、紅清單、已知檔的 `slowest_files` 秒數。
- **[推論]**：選到的題數（靜態計題＋校正係數）、每檔秒數（約 60 檔實測，其餘均值）、段開銷、**底板 192 檔 ≈ 10.1 分**（其中 16 檔有實測秒數 1022 worker‑秒、其餘 176 檔以 0.60 s／題估；tests/platform 內含巢狀 pytest 的檔通常高於均值 ⇒ **底板可能被低估**）。
- 假設：①`-n 4`、機器閒置；②選題用遞移（寬），**modtest 預設的 iface 縮小未用 ⇒ 實際選到的可能更少（上限樂觀 ~+10%）**；③`ship_tier.provider_check`（消費端）未計（只對動到模組 API 的 diff 加題，t29c/t30c 的 87～92% 已含寬鬆）；④test_map 取各 commit 上**已提交**的版本（產生檔由列車提交，新增測試檔可能不在 ⇒ 另以「改動的測試檔必選」補）；⑤e2e 以 test_map `kind=e2e` 檔當 e2e 段（與 `-m e2e` 近似）。
- 整體結論對假設的敏感度：底板每多 1 分，兩班少省 ≈ 9 段×1 ＝ 9 分；選題占比每 +10 個百分點，少省約 2.6 分／段。

### 3.4 與 BUILD-OPTIMIZATION-2 的差異（需修正該文件）
- 原文「單次重建 38 → ~8 分」：**不成立**。非 e2e 的下限是底板 ~10 分；e2e 約 4～11 分；合計 **~15～22 分**（以 t30e 型小改計：12＋［e2e 4～11］）。
- 原文「兩班省 >100 分」：本重放 **92 分（建議版、含出貨包）／52 分（出貨包全量）**；且 14 段中 7 段（各班首輪、無 e2e 基準）本來就全量。
- 原文把 `tests/platform` 估 4～6 分；以 145 檔、2160 題、~1900 worker‑秒計 **~7.9 分**。

---

## 4. 風險：增量選題會漏的測試

### 4.1 [已讀＋實測] 具體類別
1. **掃目錄型（動態掃，test_map 記不到）**：`os.listdir`／`rglob`／`glob`／`os.walk`／`git ls-files` 掃 `frontend/pages|js`、`backend/modules`、`docs`。test_map 只記**字面**單位。實測：用這些 API 的測試檔 118 個，**27 檔沒有任何 `dir:` 單位且不在底板**（`test_frontend_local_date`、`test_page_script_deps`、`test_router_registration`、`test_begin_only_via_begin_write`、`test_no_credentials_in_query`、`test_upload_path_traversal`、`test_homoglyphs_in_docs`、`test_frontend_session_key`、`test_builder_preview_static`、`test_company_setup_output_points` 等）。**t29#1 的 `test_frontend_local_date` 就是這型**：其單位只有 `js:static/auth-guard.js`、`js:static/motrix-date.js`，漏掉被掃的 27 個 frontend 檔。
2. **「更新日誌跟著程式」型（git／檔案雙掃）**：`tests/platform/test_module_changelog_follows_code.py`（37～57 s）單位只有 `dir:frontend/pages/`＋2 個 plat ⇒ 改任何模組程式都不會經 test_map 選到它；靠契約目錄全跑才安全。**不可從底板拿掉。**
3. **跨模組全域釘子**（`global_tests` 41 檔）：掃整個 sqlite_master、所有 module.json、所有頁面、權限目錄（bottom_layer.json `_global_tests_doc`）。目前只在 module／page 層規則掛 `@global_tests`；**軟底層（`tools/**`、共用 js）不掛**——M 版必須對軟底層也掛。
4. **unmapped 12 檔**（test_map.json `unmapped`）：`test_approval_queue_extra_types`（t30b 紅）、`test_stepfile_drill`、`test_deploy_dashboard_*` 四檔、`test_no_leaky_tempdirs`、`test_netguard`、`test_e2e_bn3/4/12`、`test_stock_batch_payment`。`modtest.select` **不會**選 unmapped（只有 `unmapped_changes` 報告「改動檔沒對到題」）⇒ 必須顯式加入底板。
5. **產生檔／快照型**：`test_generated_maps`（重產 maps 與提交的相等；單位 `dir:docs/platform/`＋`dir:tools/platform/`）、`test_module_registry`（catalogue 快照，t29#1 紅）、`test_version_manifest*`（bookkeeping 規則已掛）。改任何程式都可能使快照過期。
6. **分類／標記型**：`test_e2e_classification`（用瀏覽器的題必須有 `@pytest.mark.e2e`；t30e 唯一的紅，單位 `dir:backend/modules/`＋`dir:tools/platform/`，只有契約目錄全跑才選得到）。
7. **模組邊界／相依圖**：`test_module_boundaries`、`test_integration_points_registered`、`test_ship_tier*`、`test_scope_gate_2026_09_30`（103 題，單位含 `dir:backend/modules/`）；多數有寬 `dir:` 單位，另在契約目錄內。
8. **選題器自己**：改 `scope_gate`／`modtest`／`test_map.py`／`dep_scan`／`bottom_layer.json` 後，原本的選題結果不可信 ⇒ 全量（`selector_sha`）。
9. **偶發／負載型**：`test_audit_search::perf_100k_rows`（門檻 0.3 s，t29#1 與 t29e 紅，無相關 diff）、e2e 逾時。**沿用「綠」的前提是這題對機器負載不敏感**；此型靠 flaky 登記與基準紅重選，不靠選題。
10. **fixture 隱含依賴**：`api`／`e2e` 類隱含 `core:main`（`FIXTURE_IMPLIED`，modtest.py:62）；`conftest.py`（含 `modules/*/tests/conftest.py`）已在硬底層清單。

### 4.2 重放召回（紅清單，[實測]；以「test_map 選題＋底板」重放，**不含**「硬底層⇒全量」逃生門）
| 紅 | 基準→X | 紅檔數 | 選到 | 漏掉 | 備註 |
|---|---|---|---|---|---|
| t29#1 非e2e（11 紅＋7 error） | prod 0bb4834e→fca93b04（217 檔） | 10 | 9 | `test_frontend_local_date`（掃目錄型） | 其餘靠 map；`test_module_registry` 靠底板（global_tests） |
| t29c e2e（登入冒煙逾時） | 0bb4834e→9f19563d | 1 | 1 | — | |
| t29e 非e2e（audit_search perf） | 9f19563d→0ebe7eac（3 檔） | 1 | 0 | `test_audit_search`（perf 偶發，與 diff 無關） | 基準 t29c 該題綠；下一輪 t29f 由「基準紅重選」涵蓋 |
| t30b 非e2e（9 紅） | prod 47db5613→8b87c5c1（91 檔） | 7 | 7 | — | `test_approval_queue_extra_types` 是 unmapped，靠底板 |
| t30c e2e（4 紅） | 47db5613→0d4db8aa（96 檔） | 4 | 4 | — | |
| t30d e2e（2 紅，逾時型） | 0d4db8aa→8d658078（6 檔） | 2 | 2 | — | 兩個基準都選到 |
| t30e 非e2e（1 紅） | 8d658078→c7977514（3 檔） | 1 | 1 | — | 靠 tests/platform 底板 |
| **合計** | | **26** | **24（92.3%）** | 2 | 加「掃目錄型 27 檔」進底板 ⇒ **25／26＝96.2%；扣除偶發 perf 後 25／25＝100%** |

加上「硬底層 ⇒ 全量」逃生門後，26／26 都在選題內，但**其中 4 組（t29#1、t29c e2e、t30b、t30c e2e）是靠全量達成**，不是靠選題——所以上線門檻要測**不含逃生門**的召回（R3-a）。

---

## 5. 一定要跑的底板（always-run floor）與強制全量規則

### 5.1 底板（[推論] 時間；已知檔秒數取自 6 次建包 `slowest_files` 的 fail_stream summary；其餘 0.60 s／題）
| 組 | 檔 | 題 | 牆鐘（-n 4） | 說明 |
|---|---|---|---|---|
| **F0a** `backend/tests/platform/**`（扣 F1） | 137 | ~1830 | ~5.4 分 | 契約目錄（modtest.CONTRACT_DIRS）；含 `test_module_changelog_follows_code`（57 s）、`test_module_boundaries`（56 s）、`test_generated_maps`（48 s）、`test_pii_forms_notice`（57 s）、`test_e2e_classification`（19 s）、`test_integration_points_registered` 等 |
| **F0b** `bottom_layer.json global_tests` | 41 | 558 | 2.1 分 | 含 `test_bonus_correction`（97 s）、`test_custom_modules_engine`（79 s）等，已知 2 檔 176 worker‑秒 |
| **F0c** test_map `unmapped`（扣 stepfile_drill） | 11 | 70 | 0.2 分 | deploy_dashboard 四檔、`test_approval_queue_extra_types`… |
| **F0d** 掃目錄型（§4.1-1） | 26～27 | 302 | 0.8 分 | 啟發式掃出，需守門題維護（§6） |
| **F0 小計（無條件）** | 210 | ~2700 | **~8.3 分＋開銷 0.5 ≈ 8.8 分** | |
| **F1** 工具演練（可依賴鍵控） | 9 | 330 | 2.5 分 | `test_module_update_delivery` 149 s、`test_scope_gate` 72 s、`test_mail_registry` 73 s、`test_modtest_rebase_check` 64 s、`test_module_selection` 57 s、`test_stepfile_drill` 57（在 unmapped 內）、`test_ship_tier` 48 s、`test_modtest_json_stdout` 47 s、`test_modtest_scope` 41 s（合計已知 608 worker‑秒）。**在 `tools/**`／`backend/core/**`／`modules.json`／選題器改動或每第 N 次時才跑**；其餘增量略過 |
| **全底板（F0＋F1）** | 219 | ~3030 | **~10.9 分＋0.5 ≈ 11.4 分** | 重放（§3）用的是保守版：契約目錄全部＋global＋unmapped＝10.1 分 |
| e2e 底板（§2.3） | ~6 | ~30 | 0.4～1.5 分 | |

**實測依據**：`--durations=20` 出現在底板的最慢題——`test_ship_tests_adds_consumers…` 59～65.7 s、`test_module_changelog_follows_code` 37～41.5 s、`test_modtest_json_stdout` 40～47.9 s、`test_scope_gate…m1_global_nails` 20 s、`test_module_boundaries` 20～23 s、`test_e2e_classification` 18～21 s（build_t29c/f、t30b/c/d logs）。

### 5.2 何時強制全量（fail closed）
1. P/G→X 含**硬底層**檔（§3.1 清單）或 `FIXTURE_LAYER`。
2. 改到**選題器**：`scope_gate.py`、`modtest.py`、`test_map.py`、`dep_scan.py`、`ship_tier.py`、`bottom_layer.json`、`build_test_reuse.py`、本段新工具、`failfast.py`／`fail_stream.py`（`selector_sha` 變）。
3. `test_map.json`／`dep_graph.json` 本身壞掉、現場重算失敗、`unmapped_changes` 非空（有改動檔沒對到任何單位）。
4. 基準紀錄缺 40 碼 SHA、環境指紋不同、跨日、超過 **6 小時**（建議；現沿用窗 12 小時，影子期以資料收斂）、鏈長 > 2、鏈根不是真全量。
5. **連續 N=3 次增量**後下一次全量（重置漂移）。
6. 出貨包（要上正式機的最終包）：預設要**真全量或「根為全量、距今 ≤ 6 小時、`selector_sha` 同」**；使用者旗標 `-ForceTests`／`-Release` ＝ 一律全量。
7. 有任何 `aborted_by` 的段（fail-fast／被中斷）不當基準。

---

## 6. 反向控制與上線閘門

**R3-a 離線重放召回（不跑 pytest）**：把 §4.2 的紅集與未來每個「紅→修」當輸入，以**無逃生門**的選題算，要求 **100% 含該段的確定性紅**；偶發（perf、逾時）單列、須在 `known_flakes`／基準紅重選覆蓋。本表現況 25／25（確定性）但需先把掃目錄型 27 檔入底板——**未入底板前 24／26，不達標**。
**R3-b 集合守恆**：manifest 內 `selected ∪ floor ∪ red_reselect ∪ carried ⊇ collected`，nodeid sha 比對；`collected` 取自 fail_stream summary 的 `collected` 或 `--collect-only`。缺口⇒擋；另驗 `carried ∩ ran = ∅`。
**R3-c 兩條推導互證**：`selected ⊇ {t: dep_fp 變}`；不等⇒擋＋印差集（找出 test_map 洞）。
**R3-d 突變（對守門題，非產品）**：①把 F0 的某個守門檔從底板拿掉（例 `test_module_changelog_follows_code`）⇒「底板含契約目錄」守門題轉紅；②把 `tools/**` 軟底層拿掉 `@global_tests` ⇒ 轉紅；③在 `scope_gate`／`stage_select` 刪掉「改選題器⇒全量」⇒ 轉紅；④把紅重選拿掉（G 的紅檔不選）⇒ 重放題轉紅；⑤把鏈長上限／6 小時上限放寬 ⇒ 轉紅；⑥植入一個會讓某非底板測試轉紅的模組突變 ⇒ 增量選題含該題且轉紅，與全量結果逐 nodeid 相同。
**R3-e 影子全量（上線前 2 週）**：每個增量放行的包，夜間閒置仍跑一次**全量**（背景、不擋出貨、遵守全機測試鎖），比對 nodeid 結果集：**差異＝0 才算通過**；任何一次差異＝退回增量並寫入「選題洞」清單。影子期同時校準 6 小時／N=3／底板內容與耗時模型（以真實逐題 `t` 取代本文的估算）。
**不靜默略過的證明**：①manifest 逐段記 `selected/carried/floor/collected` 計數＋sha；儀表板顯示「實跑 %／沿用 %、基準 commit、鏈長」；②沿用的題**逐檔列名**（不只計數）；③`carried` 檔每一個都帶 `dep_fp` 與來源紀錄，閘門現場重算；④增量段**不寫入**全量沿用紀錄（不得被後續整棵樹指紋誤判為全量綠）；⑤全量沿用（`stages.mode=full`）與增量分開記，`lookup-stage` 對增量紀錄預設不命中全量要求；⑥守門題：`selected` 為空且 `collected>0` 時，底板仍非空（至少 F0）。
**既有守門題要全綠**：`test_build_test_reuse_2026_09_25`、`test_scope_gate_2026_09_30`、`test_build_opt_2026_09_30`、`test_failfast_2026_10_02`。

---

## 7. 實作步驟、工作量、阻塞

| # | 內容 | 工作量 | 現在可做？ |
|---|---|---|---|
| 1 | `tools/platform/stage_select.py`：輸入 G、HEAD、段 ⇒ 輸出 `{selected, floor, red_reselect, carried, forced_full}`；重用 `scope_gate.decide`（分硬／軟底層）＋`modtest.select`；純函式＋CLI（`plan`，只算不跑） | M（~1 天） | 可（分支、不碰 PS1） |
| 2 | `dep_fp`＋`selector_sha`（`build_test_reuse.py` 新子命令 `dep-fingerprint`）；兩條推導互證 | S～M（0.5～1 天） | 可 |
| 3 | 紀錄擴充（`stages.<段>` 新欄位）、`lookup-stage --incremental`、讀舊格式相容 | S（0.5 天） | 可（但 `backend/tools/**` 是底層，合進 `platform` 見下） |
| 4 | 底板清單單一來源（`gate_slices.json`，與項 4／5 共用）＋掃目錄型偵測（`test_map.py` 加「listdir/glob/walk ⇒ 補 `dir:`」或掃描式守門題） | M（~1 天；補 test_map 可把 27 檔減少） | 可 |
| 5 | **離線重放工具**（把本文腳本固化成 `tools/platform/replay_incremental.py`＋守門題，輸入 build log＋git） | S（0.5 天） | 可 |
| 6 | dry-run 測試台：自造小專案＋假 git 歷史，驗 R3-b／c／d，**不跑真測試**（同 `test_failfast_2026_10_02` 作法） | M（1 天） | 可 |
| 7 | 接進建包（Step 3：增量判定→只跑 selected，manifest `verification.stages` 加欄位）、儀表板顯示 | M（1 天） | **阻塞：改 `build_deploy_package.ps1`＋`deploy_dashboard`，等使用者套用第 30 包** |
| 8 | 影子全量 2 週（R3-e）與參數校準，通過才預設開啟（先 opt-in `-Incremental`） | 日曆 2 週 | **阻塞於 7** |
| 9 | 以真實逐題耗時（fail_stream 逐題 `t`，下一輪建包才有）重算底板與占比 | S | 阻塞於下一輪建包 |

**合計**：寫碼＋測試台 ~4～5 工作日，影子期 2 週；**阻塞**：①`build_deploy_package.ps1` 與儀表板（使用者令）；②`tools/**`／`backend/tools/**`／`bottom_layer.json` 的任何 commit 都是底層、會使第 30 包的指紋與範圍驗證失效 ⇒ **不得合進 `platform`，直到第 30 包上機（打 `prod/` tag）**；③真實逐題耗時資料要等 failfast 接上後的建包。
**建議順序**：5（重放工具，產生可重複的證據）→ 1＋2（選題＋指紋）→ 4（底板與掃目錄補丁，先把召回補到 100%）→ 6（測試台）→（第 30 包後）3＋7＋8。**若影子期召回有任何一次漏，退回只做項 1（fail-fast）＋項 2（樹雜湊）。**
