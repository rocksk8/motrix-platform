# 建包優化 2（BUILD-OPTIMIZATION-2）

> 起因：使用者「建包不能精簡優化嗎」。狀態：**待辦，有期限**——今晚（第 30 班）上機完成後開工、下一班列車前做完；每 3 天依 §6 複查一次。
> 目標：**乾淨全量的測試時間 ≤ 30 分**（現況 38～40 分）；典型「單一模組小改」的重建 ≤ 10 分（現況每次 38～40 分）。
> 鐵則：不得放寬任何閘門；每一項附**反向控制**（證明沒變弱）；不動 `build_deploy_package.ps1` 的任何一項在「實作班」才動，本文件只規劃。
> 證據標記：**[已讀]** 讀程式／文件所得；**[實測]** 取自 build log、fail_stream JSONL、build_history.jsonl 的數字；**[推論]** 估算，動手前須用 §5 的量測驗證。
> 唯讀工具：`tools/platform/build_log_report.py`（只解析文字；§6）。

---

## 0. 結論先行

1. **浪費不在「單題慢」，在「紅了還跑完」與「改一個檔就全部重跑」。** 第 29＋30 班已完成的測試段合計 **194 分鐘**；其中 **78 分鐘（40%）發生在「第一個紅已經出現之後」**，且除第一次外，**每次重建都把全部題目再跑一遍**（第 29 班最後一次重建：只差 1 個測試檔，仍重跑 40 分）。[實測]
2. 失敗「當下印出」其實**已經有**（`FAIL-EARLY`，fail_stream.py:207-214；log 內 t30b 有 9 行穿插在進度點之間）；缺的是**看到紅之後不停**。[已讀＋實測]
3. 最快見效的順序（使用者指定，下表）：①fail-fast（省 ~55～65 分／兩班）→ ②同一棵樹的段結果不重跑 → ③依賴指紋增量（單次重建 38 → ~8 分，最大單項）→ ④預演列車併入閘門第一片 → ⑤慢題車道 → ⑥worker／順序調校。
4. 單看「最慢 20 題」只佔非 e2e worker 時間的 **8%**（~526／6224 worker‑秒），最慢 20 個**檔**也只 ~26%；題目耗時是平的（8022 題、均 0.78 秒／題）。**所以靠加速慢題最多省 2～7 分；要降到 30 分以內得靠「少跑」（③）與「多用核心」（⑥）。**[實測＋推論]

---

## 1. 基準數字（全部取自 log；§5 表格的「前」欄）

| 項目 | 數值 | 來源 |
|---|---|---|
| 機器 | AMD Ryzen 5 5600X，6 實體核心／12 邏輯處理器 | [實測] `Get-CimInstance Win32_Processor` |
| 非 e2e 段 | 25:40～27:53（t29 26:00、t29c 25:58、t29e 27:22、t29f 27:53、t30b 25:40、t30c 26:24）；8022 題；-n 4；6224 worker‑秒 | [實測] pytest 摘要行／fail_stream summary |
| e2e 段 | 11:13～12:05（t29c 11:35、t29f 12:05、t30c 11:13）；754 題；-n 4 | [實測] |
| 前後置（preflight、覆蓋率、archive） | ~30 秒（t29f：total 2432 s − 1675 − 727） | [實測] build 自報 |
| 趨勢 | 非 e2e：932 s（6156 題，9/29）→ 1675 s（7848 題，10/1）＝**+80% 時間／+27% 題數**；e2e：358 s→727 s＝**+103%／+31%** | [實測] `backend/tools/deploy_logs/build_history.jsonl` |
| 第 29 班 | 6 次呼叫（t29、29b、29c、29d、29e、29f），牆鐘 18:13→21:29＝3h16；測試分鐘 131；t29b 在「等別的 pytest」1.5 分後 exit 1、t29d 開跑 2 分後被中止（無 end 訊息）＝2 次沒有測試結果 | [實測] |
| 第 30 班（到 02:52） | t30（版本紀錄檢查 1 秒就擋）、t30b（25:40 紅 9 題）、t30c（26:24 綠＋e2e 11:13 紅 4 題）、t30d（進行中，02:28 起） | [實測] |
| 沿用 | 9 份 log **沒有任何一次「沿用」**：5 次不同指紋（`test_results.jsonl`：842a…、d32a…、0fb2…、6881…、3ebc…、3cdd…），每次重建 commit 都變 | [實測] |
| 第一個紅之後白跑 | t29#1 非e2e 23:11（第一紅在段 +2:30）；t29c e2e 4:39；t29e 非e2e 22:02（1 題偶發 perf 題）；t30b 非e2e 19:50（第一紅 +5:21、最後一紅 +14:22）；t30c e2e 8:39（第一紅 +2:31）；**合計 78:21／194:18＝40%** | [實測] fail_stream JSONL＋摘要時間戳 |
| 重建的差異量 vs 重跑量 | 0ebe7eac→47db5613：**1 個測試檔**→重跑 27:53＋12:05＝40 分；9f19563d→0ebe7eac：3 檔（含 `tools/platform/flaky_retry.py`）→重跑非 e2e 27:22；8b87c5c1→0d4db8aa：13 檔（subcontract 模組＋1 頁）→重跑 26:24＋11:13 | [實測] `git diff --stat`＋log |
| 預演列車 | `pre_train_check`：~12 分（使用者回報；PLAYBOOK §G5 #19 寫 10～25 分），跑 `tests/platform` 全部＋GUARDS 10 個檔，-n 2；建包之後又把同一批跑一次 | [已讀] pre_train_check.py:50-62、184-186；時間為使用者回報 |

最慢 20 題與最慢檔見 §4-5。

---

## 2. 現況機制（[已讀]，附檔案:行）

- **段結構**：非 e2e `-m "not e2e" -n $workers --durations=20`（build_deploy_package.ps1:827），e2e `-m e2e -n 4`（:898-900），**先非 e2e、後 e2e、序列**；非 e2e 紅 ⇒ 該段跑完才進偶發重跑（:838）、再 Fail。兩段都沒有 `-x`／`--maxfail`。
- **worker**：`$workers = max(2, min(實體核心數, 4))`（:659-660；PLAYBOOK §C-13 上限 4）；e2e 固定 4（:898）；modtest `--full` 的 e2e 上限 2（modtest.py:673-677，記憶體理由，2026-09-26 -n 4 曾被記憶體不足停掉）。注釋裡的實測（:638-643）只有 940 題、-n 6／8／12，**沒有量過 -n 4 vs 6 在 8000 題上的差**。
- **失敗先行**：fail_stream（-p）每個紅當下印 `FAIL-EARLY …`＋寫 JSONL（fail_stream.py:207-214、:341 摘要）；**只觀察、不改結果**。
- **段沿用**：指紋＝`ls-tree -r HEAD`（扣 `known_flakes.json`）的 sha256＋環境（Python、pip freeze、playwright、瀏覽器、`MOTRIX_*`、`PYTEST_ADDOPTS`）（build_test_reuse.py:44、55-77、80-91）；`lookup-stage` 同指紋、該段綠、同日、12h 內才沿用（:113-145；build :686-720）；**寫入者只有 build 自己與 `modtest --full`（乾淨樹、無縮小參數）**（:231-250、modtest.py:1221-1263）。
- **指紋是整棵樹**：任何一個檔變 ⇒ 兩段全部失效。
- **範圍驗證**（scope_gate）已能「P→X 只動模組／測試／文件 ⇒ 只跑選到的題」（PLAYBOOK §D-1a；scope_gate.py:326 `select_tests`、:356 `gate`），但**基準固定是正式機 tag `prod/<sha>`**，且 `tools/**`、`backend/tools/**` 都算底層（一律全量）；建包夜間重建迴圈（基準＝上一次全綠）沒有用到它。
- **預演列車**：`pre_train_check.py` 在拋棄式合併樹跑 `tests/platform`＋GUARDS（:50-62；`build_pytest_cmd` :184-186，`-n 2`、`MOTRIX_TRAIN=1`）。建包腳本**不設** `MOTRIX_TRAIN`（grep 無）。

---

## 3. 實作項目（依使用者指定順序；每項：現況｜提案｜節省｜風險｜反向控制）

### 項 1　Fail-fast：紅了就停（並先跑最可能紅的）

**現況**：見 §2。紅出現後仍跑完整段（白跑 78 分／兩班，[實測]）。

**提案**（三層，由安全到積極）
1. **停止條件**放在 fail_stream plugin（它已在 controller 端逐題收報告）：**未登記在 `known_flakes.json` 的紅**累計達 N 筆，**或**「第一個紅之後 Q 分鐘內都沒有新紅」且已有紅 ⇒ 設 `session.shouldstop`（xdist controller 會讓 worker 收尾）。**已登記的偶發紅不計**（照舊交 flaky_retry）。N、Q 以環境變數覆寫，預設 N=10、Q=3（t30b 紅的間隔最長 3:35，故 Q 取 4 較穩；以 §5 的重放決定）。
2. **先跑最可能紅的**（`pytest_collection_modifyitems` 重排；xdist `load` 依序派發）：⒜ 最近 10 份 fail_stream JSONL 紅過的題；⒝ 自上一個綠 commit 起 diff 動到的測試檔；⒞ 靜態掃描型守門題（test_map `kind=path`：t30b 的 9 個紅幾乎全是這型——cm12 字級、write_endpoints_audited、approval_queue、builder_preview_static…）與 `tests/platform`；其餘照原順序。**排序只改順序、不刪題**。
3. **e2e 同理**：t30c 的 4 個紅在 e2e 段 +2:31～+5:33（段長 11:13）；停止條件相同。
4. **fail-fast 不吞資訊**：停止時仍印紅清單、寫 summary（`aborted_by=failfast`），flaky_retry 照舊對紅的題單獨重跑；**出口碼一律非 0**，Record-Stage 記紅（不得因「沒跑完」被記成綠或被沿用）。

**節省**：每個「紅的建包」省 15～20 分；兩班合計 **~55～65 分**（78 分的 70～80%）[推論，由實測的紅時間戳反推]。排序後紅集中在前 5～8 分，停止更準 [推論]。

**風險**：(a) 只看到前 N 個紅 ⇒ 多一輪才見到其餘的紅——因為下一輪同樣 fail-fast，單輪成本 ≤ 8 分，而非 26 分；(b) 停止條件誤判把「偶發」當真紅 ⇒ 建包被擋（結果與現在一樣：未登記偶發本來就擋）；(c) xdist 對 `shouldstop` 的行為與 `--maxfail` 不同，exit code 要實測。

**反向控制**
- R1-a 在 fail_stream 做單元題：假的紅（未登記）達 N ⇒ 觸發 stop；**已登記的紅不觸發**；**全綠的 run，執行題數＝收集題數**（逐 nodeid 與不啟用 fail-fast 的 run 比對，集合相等）。
- R1-b 突變：把 stop 條件拿掉 ⇒ 守門題轉紅（確認題目抓得到）；把「紅 ⇒ exit≠0」改成 0 ⇒ 轉紅。
- R1-c 植入探針：在排序後的最尾端放一個故意紅的題 ⇒ 全綠前綴不得被截斷（stop 只在「已有紅」時才可能發生）。
- R1-d 重排不刪題：`--collect-only` 的 nodeid 集合在重排前後 sha 相同。
- R1-e 重放：把 t29#1、t30b、t30c 的紅題集當輸入，模擬「第一個紅＋Q」時機，確認 stop 發生時**已涵蓋 ≥ 90% 的紅**（其餘在下一輪必現）。

#### 項 1 實作狀態（2026-10-02，wip/build-opt2-d7；**尚未接進建包腳本**——使用者套用第 30 包前不動 `build_deploy_package.ps1`）
- **已做**：`tools/platform/failfast.py`（pytest plugin，**預設關**）＋ `fail_stream.py` 認得它（停止不記成 aborted）＋ dry-run 測試台 `backend/tests/platform/test_failfast_2026_10_02.py`（自造 72 題小專案、巢狀 pytest，9 題全綠；`fail_stream` 既有 15＋9 題照綠）。
- **開關**（環境變數）：`MOTRIX_FAILFAST=1`（N 預設 10、`MOTRIX_FAILFAST_QUIET_MIN` 預設 4 分、已登記且未過期的偶發紅不計）；`MOTRIX_FAILFIRST=1`（最近 fail_stream 紅過的題 → `MOTRIX_FAILFIRST_BASE` 起 diff 動到的測試檔 → tests/platform → 其餘原順序；只改順序、集合不同就放棄重排）。
- **回答 §開放問題 #4**：xdist 下 `session.shouldstop` 沒有作用（DSession 看自己的 `shouldstop` 屬性）；plugin 設 `dsession.shouldstop`，pytest 會以 `xdist.dsession.Interrupted`（KeyboardInterrupt 子類）收尾、**exit code = 2（INTERRUPTED）**——這會被 fail_stream／建包當成「外部中斷」。因此 plugin 在 sessionfinish 把 exitstatus 改回 **1**，且 fail_stream 看到 `_failfast_reason` 就不記 aborted（summary 帶 `aborted_by: failfast`）。單程序（無 xdist）用 `session.shouldfail`，exit 1。
- **反向控制（已跑，全部 RED 後還原）**：stop 條件拿掉／exit code 不改回 1／登記的偶發也計入／重排丟一題／quiet 立即停／預設就開——6 個突變都被測試台抓到；全綠 run 不被截斷（60 綠、exit 0）；重排前後 `--collect-only` 題集合相同（72＝72）。
- **R1-e 部分重放（只有每段「第一個紅／最後一個紅」時間，沒有逐題時間戳）[實測＋推算]**：t30b 非 e2e（段長 25:40）第一紅 +5:21、最後紅 +14:22 ⇒ Q=4 分會在 +18:22 停，省 **7:18**（Q=2 分省 9:18），9 個紅全數涵蓋；t30c e2e（段長 11:13）第一紅 +2:32、最後紅 +5:34 ⇒ Q=4 分在 +9:34 停，只省 **1:39**（Q=2 分省 3:39）；t30d e2e（2 個紅，+3:39～+11:19）Q=4 分幾乎省不到。⇒ **前文「每個紅的建包省 15～20 分」過於樂觀**：單靠停止條件，實測型態只省約 2～9 分；**真正的大頭是『先跑最可能紅的』（把紅集中到段首）與項 3（增量）**。N／Q 預設改為先 N=10、Q=2 再以逐題時間戳重放校準（需要 fail_stream JSONL 的逐題 `t`，下一輪建包就會有）。
- **還沒做**：R1-e（用 t29#1／t30b／t30c 的紅題集重放，驗「stop 時已涵蓋 ≥90% 的紅」）；把 plugin 接進 `build_deploy_package.ps1`（`-p failfast` ＋環境變數；等使用者套用第 30 包後、在分支上做，並用 dry-run 台驗證 exit code 與 Record-Stage 仍記紅）；非 e2e 與 e2e 兩段各自的 N／Q 調校。

### 項 2　段結果以「樹雜湊」計，獨立跑的也算（不重跑兩次）

**現況**：沿用紀錄只有 build 與 `modtest --full`（兩者都要乾淨樹、無縮小參數）寫入（build_test_reuse.py:231-250）；指紋含環境，任何 `MOTRIX_*` 差異（`_ENV_IGNORE` 只排除少數）都會讓兩邊不相等。使用者描述的「e2e 單獨跑 19 分，建包又跑一次」在 9 份 log 內**沒有留下 `沿用` 一行**，**真正的不相等原因無法從 log 判定** [實測]。可能原因 [推論]：⒜獨立跑用原生 `pytest -m e2e`／縮小參數，不寫紀錄；⒝兩個 shell 的 `MOTRIX_*`／`PYTEST_ADDOPTS`／pip freeze 不同；⒞中間 commit 變了。

**提案**
1. 先加診斷：`build_test_reuse.py explain`：印 tree sha 與環境各成分（python、pip_freeze sha、playwright、browsers、motrix_env 各鍵），建包因「沒沿用」時印出「與哪一筆最接近、哪個成分不同」。**不改行為，先看 3 天資料。**
2. 新入口 `tools/platform/stage_run.py <not_e2e|e2e>`：以**與建包完全相同的參數**（`-m`、路徑、`-p fail_stream`）跑單一段，只在「乾淨樹＋fail_stream 的 summary 為證據＋invocation args 正規化後等於該段標準選擇」時寫段紀錄。fail_stream 在 summary 加 `invocation_args`、`collected`（收集題數）。
3. 沿用判定改為 `(tree_sha, env_sha, stage, selection_sha)`：`tree_sha` 用 `git rev-parse HEAD^{tree}`（同一棵樹換 commit 也命中；仍扣 REUSE_EXCLUDE），**環境成分分開比對**，並新增 allowlist（只影響快慢的鍵：已含 `MOTRIX_*_MAX_WORKERS`）。
4. 12 小時／同日窗口、「同指紋最新一筆若紅則不沿用更早的綠」、偶發重跑條目沿用——**全部維持**。

**節省**：消除使用者所述的雙跑 19 分（e2e）或 26 分（非 e2e）；每次發生省 12～26 分 [推論；未見 log 證據，故先做診斷]。

**風險**：誤把縮小範圍的跑當全量（假綠）；環境成分放寬過頭。

**反向控制**
- R2-a 用 `-k`／`--deselect`／`-x`／縮小路徑跑 `stage_run`：**不得**寫紀錄或寫了也不被 lookup 採用。
- R2-b 改一個檔（任何一個）⇒ lookup 不命中；改 pip 套件版本／`MOTRIX_*`（非 allowlist）⇒ 不命中。
- R2-c 偽造紀錄（沒有對應 fail_stream summary）⇒ 拒絕（現有 W4 規則延用）。
- R2-d 端到端：同一棵樹先 `stage_run e2e` 再建包 ⇒ 建包印沿用、**pytest 啟動次數＝0**（以行程計數驗，而非看字串）。
- R2-e 同指紋最新一筆紅 ⇒ 不沿用更早的綠（既有守門題 `test_build_test_reuse_2026_09_25`、`test_build_opt_2026_09_30` 必須全綠）。

### 項 3　依賴指紋：增量段（改一個檔不使全綠失效）

**現況**：整棵樹進指紋 ⇒ 任一檔變、兩段全重跑。[實測] 1 個測試檔的差異＝40 分重跑；3 檔＝27 分；13 檔＝38 分。每次夜間重建的 commit 幾乎都是「修紅」小改。

**提案**：沿用 scope_gate／modtest 既有「差異 → 選題」引擎，把**基準從 `prod/<sha>` 改成「同環境、12h 內、全量全綠的最近 commit」**（夜間重建迴圈專用）。
1. 新模式 `gate_mode=incremental`：基準 G＝最近一筆**兩段皆綠且為全量或全量加增量鏈**的紀錄（紀錄需存完整 commit SHA；現存只有 8 碼，要補）。
2. G→X 的改動檔以 `bottom_layer.json` 分類：**任何底層檔（含 `tools/**`、fixture 層、migrations、共用前端、`backend/tools/**`）⇒ 該段全量**（與 §D-1a 同規則，fail closed）。全部落在「模組檔／恰好一個模組的頁面／測試檔／docs」⇒ 選題＝`modtest` 遞移選題＋`tests/platform` 全部（`MOTRIX_TRAIN=1`）＋規則附帶的 `global_tests`＋改到頁面的 e2e＋test_map 沒對到單位的題（unmapped 一律選入）。
3. 未選的題以 G 的綠「沿用」，manifest 記 `stages.<段> = incremental(base=G, selected=N, carried=M)`。
4. **鏈長上限 2**、**同日 12h 內**；**發行包（要上正式機的最終包）仍要求「基準的那一筆是真的全量」**，不接受增量鏈根在別日。
5. `-ForceTests`／`-Release`（新旗標）＝一律全量，供使用者隨時要求。

**節省**：以第 29／30 班的重建型態推 [推論]：平台契約題 ~4 分＋選到的題 ~3 分＋頁面 e2e ~2 分 ≈ 8～10 分，對現在每次 38～40 分。第 29 班 5 次重建、第 30 班 2 次（t30c、t30d）⇒ 保守省 **>100 分**。

**風險**：test_map 是靜態分析，漏掉動態依賴 ⇒ 該跑的沒跑（假綠）。緩解：unmapped 全選、`global_tests`、tests/platform 全跑、底層一律全量、鏈長上限、最終包要真全量根。

**反向控制**
- R3-a **重放召回率（離線，不跑 pytest）**：對每一組歷史「紅 commit → 修正 commit」（t29#1 的 11 紅、t30b 的 9 紅、t30c 的 4 e2e 紅），用「紅的來源 diff」算增量選題（`modtest --dry-run --list`），**必須 100% 包含當時紅的題**；有一個漏掉＝不上線。
- R3-b 突變注入：在某模組檔植入會讓既有題轉紅的突變 ⇒ 增量選題會跑到該題且轉紅，與全量結果相同（逐題結果集比對）。
- R3-c fail closed：diff 含任一底層檔、判定出錯、紀錄缺 SHA、鏈長超限、基準不是全量根 ⇒ 全量（守門題＝仿 `test_scope_gate_2026_09_30` 的 (a)(b)(c)(d) 與八種假輸出）。
- R3-d 集合守恆：`selected ∪ carried ⊇ collected`（manifest 內記 collected 的 sha；缺口 ⇒ 擋）。
- R3-e 影子驗證：開頭 2 週，增量放行的包，**夜裡閒置時仍跑一次全量**（背景、不擋出貨），差異＝0 才算通過；有差異就退回。

### 項 4　預演列車（pre_train_check）併入閘門第一片／增量化

**現況**：`pre_train_check` 在合併樹跑 `tests/platform`＋10 個 GUARDS（-n 2，~12 分），建包再整套跑一次（同批題重複）。t30b 的 9 個紅**全是**「靜態掃描型、合併後才紅」的守門（cm12 字級、write_endpoints_audited、approval_queue、builder_preview_static…）——它們在建包的非 e2e 段前 5～14 分才出現，後面還白跑 20 分。[實測]

**提案**
1. 建 `tools/platform/gate_slices.json` 為**單一來源**：`slice0`＝`pre_train_check.GUARDS`＋`tests/platform`＋靜態掃描型守門（test_map `kind=path`）＋最近紅過的題。建包非 e2e 段的**第一片**先跑 slice0（`-n 4`，fail-fast），綠才跑其餘；等於項 1 的重排取其中一片。
2. `pre_train_check` 的 pytest 部分改讀同一份清單（作者推送前用），**列車長的建包路徑不再另跑一次預演 pytest**；列車長仍跑「合併＋取號＋重產產生檔」（`--skip-tests` 型，秒級）。
3. 若合併樹的 `HEAD^{tree}` 等於候選 commit 的 tree（單分支列車），pre_train_check 的綠可依項 2 當 slice0 的段結果。

**節省**：列車長路徑省 ~12 分／班；slice0 在建包內 ~4～5 分出結果（紅就停）[推論：tests/platform 為前 20 慢檔中 8 檔，worker 時間約 540 s；整個 slice0 估 4～6 分，需 §5 量測]。

**風險**：slice0 清單與 GUARDS 漂移；作者少跑預演而晚發現。

**反向控制**
- R4-a 靜態題：`GUARDS ⊆ slice0`、`pre_train_check` 與建包讀同一檔。
- R4-b 植入紅：在 slice0 的某題植入紅 ⇒ 建包在 slice0 內（<8 分）失敗，未進其餘題。
- R4-c 題目覆蓋守恆：`slice0 ∪ rest` 的 nodeid 集合與單一 run 的 `--collect-only` 集合相等（sha 比對）。

### 項 5　慢題車道（巢狀 pytest 突變守門、25～30 秒的題）

**現況**（[實測] 最慢 20 題，t30c 非 e2e；每行 worker‑秒）：

| # | 秒 | 題 |
|---|---|---|
| 1 | 63.4 | tests/platform/test_module_update_delivery_2026_09_28::test_ship_tests_adds_consumers_of_a_changed_provider |
| 2 | 37.0 | tests/platform/test_module_changelog_follows_code::test_every_module_changelog_follows_its_code |
| 3 | 36.4／36.3 | tests/test_upgrade_drill_2026_09_25::test_convert_then_rollback_restores_v9[code]／[full] |
| 5 | 35.8 | tests/platform/test_modtest_json_stdout_2026_09_29::…worker_caps_are_set |
| 6 | 25.0 | tests/platform/test_modtest_rebase_check::test_own_fixture_layer_change_runs_the_diff… |
| 7 | 24.4／23.5 | tests/platform/test_stepfile_drill_2026_09_30（兩題） |
| 9 | 23.5 | tests/platform/test_module_boundaries::test_prune_keeps_other_keys… |
| 10 | 22.7 | tests/platform/test_modtest_scope::test_real_helper_private_change_selects_its_tests |
| 11 | 21.5 | tests/platform/test_e2e_classification::test_every_browser_test_carries_the_e2e_marker |
| 12 | 21.2／17.9 | modules/accounting/tests/test_ledger_mutation_guards_2026_10_01（M3 call、M1 call；M1 setup 另 17.9） |
| 14 | 20.7 | tests/platform/test_integration_points_registered::…removed_without_breaking_the_registry |
| 15 | 20.6／20.3 | tests/platform/test_module_boundaries::test_rc_end_to_end_through_real_source／test_scope_gate_2026_09_30::test_m1_global_nails… |
| 17 | 20.0 | tests/test_company_setup_gate_2026_09_28::test_every_other_api_route_is_blocked_when_unconfigured |
| 18 | 19.8 | tests/platform/test_ship_tier_2026_09_28::test_real_repo_every_provider_module_resolves |
| 19 | 17.9 | tests/platform/test_startup_writes_only_via_startup（setup） |

（t29f 同批：test_ship_tests… 62.7、json_stdout 47.9、changelog 40.2、drill 33.4／33.0、scope_gate 30.2…；另見 t29#1：8 個 ledger mutation 守門在整段**最末**才完成、6 個 setup error＋1 個＝7 errors。）最慢**檔**前 5：test_module_update_delivery 157 s（45 題）、test_ledger_mutation_guards 139 s（8 題）、test_bonus_correction 101 s、test_bonus_case_api 97 s、test_quote_json_lost_update 85 s；前 18 檔合計 ~1530 worker‑秒＝~26%。e2e 最慢：`test_e2e_p8_module_builder…acceptance_equipment_loan` 28.4 s、`…bonus_correction_page…lifecycle_supplement` 19.5 s、`…case_page_theme…dark_mode` 18.7 s、`edit_presence_modal` 17.6 s、`inflight_report…teardown_hang[n1]` 15.7 s（e2e 前 20 皆 9～28 s）。

**判讀**：慢題是**測工具／測守門本身**（巢狀 pytest、drill、突變），多數只在「對應的工具或模組被改」時才有資訊量。

**提案**
1. 加 marker `slow_guard`（由 test_map 判得：巢狀 pytest／drill／突變）＋在 `gate_slices.json` 為每個慢題登記**依賴單位**（例：`ledger_mutation_guards` ← `modules/accounting/**`；`module_update_delivery` ← `tools/platform/module_update.py` 等）。
2. **增量模式**（項 3）：依賴沒被 G→X 動到 ⇒ 沿用；動到 ⇒ 跑。**乾淨全量／發行包：全部照跑**。
3. **全量內的排程**：慢題放最前面（LPT）＋ xdist `--dist worksteal`（若版本支援；先驗），避免 63 秒的題落在最後一輪（t29#1 即如此）。
4. 突變守門共用 fixture（`test_ledger_mutation_guards` 每個 case 各 18 s setup＋18 s call）改 module scope：[推論] 省 ~100 worker‑秒≈25 秒牆鐘；需先確認突變前後狀態還原。

**節省**：乾淨全量 ≤ 2～3 分（排程＋fixture）；增量模式下每次再省 2～6 分 [推論]。

**風險**：登記的依賴不完整 ⇒ 慢守門被誤略；共用 fixture 讓突變間互相污染。

**反向控制**
- R5-a 標記完整性：每個 `slow_guard` 題必須在 `gate_slices.json` 有依賴登記（靜態題）。
- R5-b 依賴被動到 ⇒ 該題**必定**被選入（對每個慢題做一次「動依賴檔 ⇒ 選題含它」的離線檢驗）。
- R5-c 突變：把 `modules/accounting` 的一個檔植入突變 ⇒ 增量選題含 ledger 突變守門且轉紅。
- R5-d 乾淨全量／`-Release` 仍執行全部 `slow_guard`（題數與不分車道時相同）。
- R5-e 共用 fixture 版本對原版：跑兩種，結果集（每個突變是否被偵測）完全相同。

### 項 6　worker 數與順序調校

**現況**：非 e2e `-n 4`（:659-660，上限 4 為使用者「CPU 100%」回報，PLAYBOOK §C-13）；e2e -n 4（:898）；6 實體核心；已降 BelowNormal（:660 起）。**-n 4 vs 6 在 8000 題規模從未量測**；e2e 在 modtest 為 -n 2（記憶體）、在建包為 -n 4。

**提案**
1. **先量測、再決定**（§5）：同一棵樹、機器閒置（`build_preflight` 無其他 pytest）、只改 `-n`：非 e2e 4／5／6、e2e 2／4／6；同時以 `Get-Counter '\Processor(_Total)\% Processor Time'`（5 秒取樣）記 CPU 利用率與可用記憶體。
2. 若 -n 6 且 BelowNormal 下結果集相同、flake 率不升：建包新增 `-Away`（使用者離開／夜間）旗標＝非 e2e／e2e 用 -n 6；白天維持 4。上限仍受全機測試鎖（Acquire-TestExclusive）管，不繞過。
3. e2e 與非 e2e **重疊**：只在 CPU 利用率量到 e2e 期間 <70% 時才試（e2e 平均 3.6 worker‑秒／題，可能大量等瀏覽器）；試法＝非 e2e 4 worker＋e2e 2 worker，總 ≤ 核心數；e2e 對負載最敏感（PLAYBOOK §D-建包 ③），**預設不開**，要連 3 次同樹全綠才算。
4. 失敗機率高的先跑：e2e 段的紅率（3 段中 2 段紅）高於非 e2e（6 段中 3 段）[實測]，但 e2e 在非 e2e 綠之後才跑；與項 1 的「先跑最可能紅的」合併處理，不另調段序。

**節省**：非 e2e -n 4→6：線性上限 −33%（26→17.5 分），實際取 −20% ≈ **−5 分**；e2e −n 4→6 約 −2～3 分 [推論；§5 量測決定]。

**風險**：機器被吃滿（使用者痛點）；e2e 偶發率上升；記憶體（e2e 每 worker 一個瀏覽器）。

**反向控制**
- R6-a 同一棵樹 A/B：**逐 nodeid 的結果集相同**（passed/failed/skipped 集合，取自 fail_stream JSONL），至少各 2 次。
- R6-b e2e 偶發率：同樹連跑 3 次，紅題數不高於 -n 4 的基準；任何一次多出新紅 ⇒ 退回 -n 4。
- R6-c 保險絲：`-Away` 需 preflight 無其他 pytest、否則自動回 -n 4；`MOTRIX_FULL_MAX_WORKERS`／旗標可一鍵還原。

---

## 4. 預算（乾淨全量 ≤ 30 分）與典型小改

| 段 | 現況 | 預算 | 達成手段 |
|---|---|---|---|
| 前後置（preflight、覆蓋率、archive） | 0:30 | 1:30 | 不動 |
| slice0（項 4） | 含在非 e2e 內 | 5:00（內含，非另加） | 項 1、4 |
| 非 e2e | 26:00（25:40～27:53） | **≤ 19:00** | 項 6（-n 6，~−5）＋項 5（排程／fixture，~−2） |
| e2e | 11:30（11:13～12:05） | **≤ 9:00** | 項 6（-n 5～6，~−2.5） |
| 小計 | ~38:00 | **≤ 30:00（含 0:30 緩衝）** | — |
| 典型單模組小改重建 | 38～40:00 | **≤ 10:00** | 項 3＋4＋5（增量） |
| 紅了的建包（任何一段） | 全段跑完（最多 26:00／11:30） | **≤ 8:00 出紅** | 項 1 |

預算需防止題數成長吃掉：題數 2 天 +27%、單題均耗時 0.15→0.21 s（[實測] build_history）；§6 要追「秒／題」。

---

## 5. 量測方法（前／後，同一棵樹）

**規則**：①同一個 commit、同一個環境（`build_test_reuse.py explain` 的環境成分相同）；②機器閒置（`build_preflight.py`：無其他 pytest）；③每個方案至少 2 次，取兩次與差；④不同方案**不同時跑**；⑤結果集以 fail_stream JSONL／pytest `-rA` 產生的 nodeid 清單比對（不只比數量）；⑥用 `tools/platform/build_log_report.py --json` 取數，貼進下表。

**表格樣板**（「前」已填基準；「後」於實作時填）

| 指標 | 前（基準，[實測]） | 後（#1） | 後（#2） | 預算 |
|---|---|---|---|---|
| 非 e2e 牆鐘 | 26:00（25:40～27:53） | | | ≤ 19:00 |
| 非 e2e 題數／worker‑秒 | 8022／6224 | | | — |
| e2e 牆鐘 | 11:30（11:13～12:05） | | | ≤ 9:00 |
| e2e 題數 | 754 | | | — |
| 前後置 | 0:30 | | | ≤ 1:30 |
| 乾淨全量合計 | ~38:00 | | | ≤ 30:00 |
| 第一個紅出現（段 +） | 非e2e 2:30～5:21；e2e 2:31 | | | — |
| 第一個紅之後白跑 | 4:39～23:11（平均 15:40） | | | ≤ 2:00 |
| 單檔差異重建（模擬 t29f：1 個測試檔） | 40:00 | | | ≤ 10:00 |
| 一次 3 檔差異（t29e 型） | 27:22 | | | ≤ 10:00 |
| 結果集與基準 | — | 相同／差異 N 題 | | 必須相同 |
| 最慢 20 題總和 | 526 worker‑秒（8%） | | | — |
| CPU 利用率（非 e2e／e2e） | 未量 | | | — |
| 重複建包（含紅）每班測試分鐘 | 第 29 班 131；第 30 班 ≥ 90（進行中） | | | ≤ 60 |

---

## 6. 3 天複查（每 3 天；第一次＝實作完成當日起算）

**一行指令**（唯讀，只解析 `%TEMP%\build_*.log`＋fail_stream JSONL）：

```
D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe tools\platform\build_log_report.py --last 3 --top 20 --budget
```
（`--json` 可機器讀；`--dir`／`--glob` 指向別處。已對現有 log 跑過：t30b／t30c 的段時間、第一紅時間、最慢題都能解析；t30d 因尚未結束顯示「進行中」。）

**複查清單**
1. 各段時間 vs §4 預算（腳本印「超出」）；乾淨全量合計 ≤ 30:00？
2. 「第一個紅之後白跑」≤ 2:00？（項 1 是否生效）
3. 重建是否走 `incremental`／沿用（manifest `verification.stages`）？有沒有發生雙跑（pytest 啟動次數）？
4. 秒／題趨勢（`build_history.jsonl`）：> 0.20 就開單查最慢檔。
5. 閘門沒變弱的證據：各項反向控制守門題都在、全綠；`selected ∪ carried ⊇ collected`；影子全量（R3-e）差異＝0。
6. 偶發登記簿：本期新登記幾題、到期日（known_flakes.json）。
7. 把這 6 項寫進 RUN-LOG，超標者排下一個實作。

**排程（每 3 天；使用者指令：建包優化要定期複查）**
- 主持視窗用 session cron：`CronCreate`，cron 表示式 `17 9 */3 * *`（每 3 天 09:17；避開整點），prompt＝「跑 §6 一行指令、逐項核對 6 條複查清單、把結果寫進 RUN-LOG、超標者開下一個實作項」。session cron 只活在當次工作階段內 ⇒ 每次開新工作階段先 `CronList` 確認還在，不在就重建。
- 不依賴工作階段的備援：Windows 工作排程器（登入使用者、每 3 天）執行上面那行 `build_log_report.py --last 3 --top 20 --budget --json > <RUN-LOG 資料夾>uild-report-<日期>.json`；腳本唯讀，不吃 CPU，可與建包並行。
- 複查結果的**落地位置**：`docs/platform/RUN-LOG`（日期＋六項各一行＋超標項的處置）；連續兩次「乾淨全量 > 30:00」＝升級給主持排實作。


---

## 7. 摘要表與建議順序

| 項 | 節省（性質） | 風險 | 工作量 | 備註 |
|---|---|---|---|---|
| 1 fail-fast＋先跑易紅 | 每個紅的建包 −15～20 分；兩班 ~−55～65 分（[實測]反推） | 低 | S（~1 天：plugin＋排序＋守門題） | 先做；最小改動換最大已證實浪費 |
| 2 樹雜湊段結果＋獨立跑算數 | 每次雙跑 −12～26 分（[推論]；9 份 log 無雙跑證據，先加 explain） | 低～中（假綠） | S～M（~1 天） | 先做 `explain` 診斷 3 天 |
| 3 依賴指紋增量 | 每次重建 38 → ~8～10 分；兩班 >100 分（[推論]） | 中（test_map 漏依賴） | M～L（2～3 天；重用 scope_gate／modtest） | 最大單項；R3-a 重放 100% 召回為上線門檻 |
| 4 預演列車併入 slice0 | 列車長路徑 −12 分／班；紅在 ~5 分出（[推論]） | 低 | S～M（~1 天） | 依賴項 1 的排序機制 |
| 5 慢題車道 | 乾淨全量 −2～3 分；增量再 −2～6 分（[推論]） | 低～中（依賴登記） | M（~1.5 天） | 慢題只佔 8%，別期待大 |
| 6 worker／順序 | 非 e2e ≈ −5 分、e2e ≈ −2.5 分（[推論]，需量測） | 低（可一鍵還原） | S（量測為主；~0.5 天） | **量測不需要寫碼，可在實作 1～5 的同時先跑** |

**建議順序**：先並行開量測（項 6 的 A/B 與 CPU 取樣，純量測，不改碼）→ 1 → 2（先 explain）→ 4（共用 slice0 與 1 的排序）→ 3（含 R3-a 重放與 R3-e 影子驗證）→ 5 → 依量測決定 6 的 `-Away`。**達成 ≤30 分的主力是 6（乾淨全量）與 3（小改重建）；1 是止血。**

**未解問題**（動工前確認）：①建包不設 `MOTRIX_TRAIN=1`，而範圍驗證設——「是否最新」三題在建包是否被 skip（skipped=60 內）；②使用者所說「e2e 單獨跑＋建包再跑」當時的指令與環境（決定項 2 的真因）；③t29b／t29d 兩次無測試結果的呼叫（等別的 pytest／被中止）是否另有流程成本；④xdist 版本是否支援 `--dist worksteal`；⑤fail-fast 的 `shouldstop` 在 xdist controller 端的 exit code 行為（需 5 分鐘探針）。
