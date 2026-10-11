# 更新 2 小時路徑：實際耗時、worker 等待原因、省時清單（T55，唯讀報告）

作者：hichan-21（node-d8 轉派），2026-10-12 04:25。**只讀既有日誌與唯讀指令；沒有跑任何測試、建包或 AV 設定變更。** 資料來源：`%TEMP%\motrix-runstage-*-failstream\runstage-*.jsonl`（fail_stream 結束紀錄）、`/tmp/m2*_*.log`、`D:\開發測試檔\b7-m1-pkg\STATE-M1A.txt`、`m1a_build.log`、`build_history.jsonl`、離開日誌（記憶 `project_motrix_away_log_20261009.md`）、前案 `wip/t50-speedup-{io,cache,pipeline,prepush}`。「推算」標註者不是量測值。

## 0. 結論（先看這裡）
1. **2 小時在「機器健康＋零紅燈＋零閒置」時做得到**：不弱化閘門的下限＝not_e2e 約 39～44 分＋e2e 約 24 分＋建包 1 分＋演練／驗證約 5 分＋發布到套用約 16 分 ≈ **1 小時 30 分**（M1-a 實測各段）。
2. **今天一班拖成一天，不是閘門本身慢，是三件事疊加**：(a) 結果沒人即時接手的**閒置約 6 小時 50 分**（M2 一輪就有三段）；(b) **紅燈整輪重跑**（r1 紅 7、r2 紅 1 都是「啟動前／lint 前就能避免」的）；(c) r2 的 not_e2e **同樣 10.6k 題花 8,766 秒，是正常 2,300～2,600 秒的 3.4 倍**。
3. **(c) 的原因不是題目變多，也不是子行程數**：核心證據是整機 **核心態 CPU 67%／使用者態 32%**；Defender 服務已停，現行即時掃描是 **Bitdefender**；最慢的檔案大多**沒有任何 subprocess**，只是每題複製範本庫＋建 tmp 的純檔案 I/O。最可能的倍增器＝防毒（minifilter）掃每個建立／複製／刪除的檔案；這需使用者在 Bitdefender 管理介面決定排除路徑（見 §3、§5-問題 Q1）。
4. **目前重跑（02:35 起）已有 4 題紅**（§2.3），都是負載下的時序題，登記簿 `known_flakes.json` 是空的（`"flakes": []`）⇒ 不被偶發重試涵蓋。

## 1. 各階段實際牆鐘時間

### 1.1 M1-a（凍結 4eb521384，STATE-M1A.txt／離開日誌／failstream）
| 階段 | 起 → 迄 | 牆鐘 | 題數／備註 |
|---|---|---|---|
| 整合＋取號 | （未量；fe9fbc4bc 07:01 取號） | — | |
| 官方 not_e2e #1（fe9fbc4bc） | 07:04 → ≈07:46 | 2,497 s（41.6 分） | 10,444 過／**2 紅**（表單版號未升、版本清單跨午夜）|
| 修復＋重凍結 2d774ead → 4eb521384 | 07:46 → 08:07 | 21 分 | 2d774ead 的舊跑被樹變動作廢（2,426 s 白跑） |
| 等舊跑讓位 | 08:07 → 08:39 | **32 分（佇列等待）** | 舊官方跑不能被終止，排隊 |
| 官方 not_e2e #2（4eb521384） | 08:39 → 09:18 | **2,317 s（38.6 分）** | 10,446 過／0 紅（`--no-failfast`）|
| 官方 e2e | 09:19 → 09:43 | **1,450 s（24.2 分）** | 998 過／3 skip |
| **閒置（結果→建包）** | 09:43 → 10:36 | **≈53 分** | 建包本身只要 30～45 秒（`build_history.jsonl` total 25～43 s），這 53 分是無人接手 |
| 建包＋verify／drill | 10:36 → ≈10:41 | ≈5 分 | verify_package／final_drill PASS／final_verify PASS 19/0/W2/S1 |
| 發布 | ≈10:43～10:44 | ≈2 分 | `20261011_104311_4eb52138_full` |
| 正式機套用 | 10:44 → 10:59 | **≈15 分** | success、無回滾 |
| **合計 凍結→上線** | 07:04 → 10:59 | **3 時 55 分**（其中閒置／等待 ≈1 時 25 分、紅燈修復 ≈1 時） | |

### 1.2 M2 第一輪（凍結 bfa457208）
| 階段 | 起 → 迄 | 牆鐘 | 備註 |
|---|---|---|---|
| full-lint F 前置（預檢 2850 題） | ≈14:41 → 14:58 | ≈17 分 | `m2f_fulllint`；實測 |
| **閒置：lint 結果無人回報** | 14:58 → 20:14 | **5 時 16 分** | 離開日誌 20:14「約 14:58 結束但 5 小時無人回報」|
| 官方 not_e2e | 20:19 → ≈21:04 | **2,626 s（43.8 分）** | 10,628 過／**紅 7**（settings 3／perm 2／hub 2）|
| **閒置：紅燈結果未回報** | 21:04 → 22:17～22:25 | **73～81 分** | 離開日誌 22:25「延誤 70 分」|
| 修 r8／r12／r9＋非作者稽核＋重建 r2 | 22:25 → 23:29 | ≈64 分 | 3 組平行 |
| r2 full-lint（重建後） | ≈23:31 → 23:48 | **1,011 s（16.9 分）** | 2850 過；**抓到 1 紅**（hub L1_OWNER，23:2x 修）|

### 1.3 M2 第二輪（凍結 8207b54d8）
| 階段 | 起 → 迄 | 牆鐘 | 備註 |
|---|---|---|---|
| 官方 not_e2e #1 | 23:48 → 02:15 | **8,766 s（146 分）** | 10,633 過／70 skip／3 xfail／**1 紅**：`test_branch_does_not_touch_generated_files`（`MOTRIX_TRAIN=1` 沒設，測試本來 skipif）|
| **閒置：紅燈結果未回報** | 02:15 → 02:31～02:34 | **16～19 分** | |
| 官方 not_e2e #2（同凍結樹，已設環境變數） | 02:35 → **仍在跑（04:22 已 107 分）** | — | 04:22 為止 fail_stream 已記 **4 紅**（§2.3）|
| e2e | 尚未開始 | — | |

**M2 累計（至 04:22）**：從 M2 凍結（20:20）起 **8 小時以上、仍未上線**；閒置合計（5:16＋1:21＋0:17）≈ **6 小時 54 分**；而閘門實際計算只有 44＋146＋(進行中) 分鐘。

## 2. 測試題數與最慢項目（僅來自既有日誌）

### 2.1 各階段題數
| 階段 | 題數 | 牆鐘 |
|---|---|---|
| full-lint F／r2（`train_preflight` 選 13 檔） | 2,850 過／8 skip | 1,011 s（`-n` 未標；預檢跑法）|
| not_e2e | 10,409～10,446 過（M1）→ 10,628～10,633 過（M2）；skip 68～70；xfail 3 | 2,259～2,626 s（健康）；**8,766 s（r2 #1）** |
| e2e | 998 過／3 skip | 1,430～1,450 s（兩次實測幾乎一致）|

健康基準（同機、`-n 3`，兩次 M1／M2 r1）：2,317 s、2,626 s；t50 時期（`-n 4`）：2,298～2,326 s。**r2 #1 的 3.4 倍無法用題數（+1.7%）解釋。**

### 2.2 最慢檔案（fail_stream `slowest_files`；秒＝該檔所有題的總和，跨 worker）
| 檔案 | M1-a（08:39 跑） | M2 r1 | **M2 r2 #1** | r2 題數 | r2 每題 |
|---|---|---|---|---|---|
| `modules/netplan/tests/test_network_plans.py` | 不在前 6 | 不在前 6 | **1,584** | 13 | 122 s |
| `modules/payroll/tests/test_payslip_void_signed_paid_2026_09_29.py` | 不在前 6 | 不在前 6 | **1,385** | 17 | 81 s |
| `modules/case/tests/test_expense_form_output_a27_2026_10_01.py` | — | — | **1,052** | 10 | 105 s |
| `tests/test_quote_location_rest_2026_09_22.py` | — | — | **986** | 13 | 76 s |
| `tests/platform/test_stepfile_drill_2026_09_30.py`（t50 時 87 s） | — | — | 827 | 7 | 118 s |
| `tests/test_quote_location_snapshot_2026_09_23.py` | — | — | 812 | 3 | 270 s |
| `modules/accounting/tests/test_jv34_voucher_input_and_print_2026_09_24.py` | — | — | 628 | 2 | 314 s |
| `tests/platform/test_module_update_delivery_2026_09_28.py` | 248 | 330 | 478 | 45 | 10.6 s |
| `tests/platform/test_scope_gate_2026_09_30.py` | 113 | 153 | （前 19 名外）| 103 | — |

兩個觀察：①健康時最慢檔是「掃 repo 的閘門型檔」（約 100～330 s）；r2 #1 的前 7 名卻是**一般 API 型檔**，每題 76～314 s，比健康時（同型檔 <10 s／題）慢一到兩個數量級。②r2 #1 前 19 名合計 ≈ 11,600 worker 秒，而 3 worker × 8,766 s ＝ 26,300 worker 秒：**慢是普遍的，不是少數檔**。

### 2.3 目前重跑（023518）已紅 4 題
| 題 | 時間 | 訊息 | 性質 |
|---|---|---|---|
| `tests/platform/test_fail_stream_aborted_2026_09_30.py::test_killing_every_worker_with_no_restart_is_recorded_as_aborted` | 02:47 | 紀錄型別序列多了 `node_down`,`fail`（預期只有 `aborted`）| 殺 worker 的競態，負載下行程回收慢 |
| `tests/test_company_setup_cli_2026_09_28.py::test_invoke_company_setup_cli_fails_closed[not_configured-…]` | 03:43 | `reason=timeout`（預期 `no_record`）| powershell→假 python **3 秒**逾時 |
| 同檔 `[lying_exit-…]` | 03:44 | 同上 | 同上 |
| 同檔 `[crash-…]` | 03:44 | 同上 | 同上 |
- `known_flakes.json`：`"flakes": []`（只有 1 筆 removed 的 tender_radar e2e）⇒ 這 4 題**未登記**；`flaky_retry.py` 只由 `build_deploy_package.ps1` 呼叫，且「重跑過但未登記」仍判 exit 1。**沒有任何現成機制涵蓋這 4 題。**
- `test_company_setup_cli` 的 3 秒是測試內寫死的行程啟動預算（`Invoke-CompanySetupCli … 3`），三題都紅且同一分鐘 ⇒ 該時段 powershell/python 啟動 >3 秒（機器被拖慢的直接證據）。

## 3. xdist worker 在等什麼（排序，附證據）

**現象**：01:30 時 3 個 worker 各約 15% CPU 工作比，整機 CPU 100%（d8 取樣）。我 04:07 的取樣（重跑進行中）：`% Privileged Time` **67**、`% User Time` **32**、Interrupt 2、DPC 0；`% Processor Utility` 121。

| # | 假設 | 證據 | 判斷 |
|---|---|---|---|
| **H1** | **檔案 I/O 被即時掃描（minifilter）放大**：每題 `shutil.copyfile`（1.19 MB 範本庫）＋`tmp_path`＋WAL/shm 建立／刪除（`conftest.py:534-720`，通過就刪 `tmp_path`）；整輪建檔／刪檔流量約 12 GB、數萬小檔（conftest 註解、t50-io §2）| ①核心態 67%（子行程不多的純 API 檔也慢）②**最慢檔 netplan／payslip_void／expense_form／quote_location 的原始碼中 subprocess／powershell／git／sleep 計數＝0**（`grep -c`），只剩 client fixture 的檔案 I/O ③`Get-MpComputerStatus`：Defender `RealTimeProtectionEnabled=False`、`WinDefend`／`WdNisSvc`／`Sense` **Stopped**；`Win32_AntiVirusProduct` 列 **Bitdefender 防毒（productState 266240）**，`bdagent`／`bdservicehost`（5 個，一個 522 MB）／`bduserhost` 在跑 ④t50-io 已記 MsMpEng 前科（2026-09-15）| **最高**。無法直接證明（Bitdefender 排除清單與即時掃描日誌需系統管理員介面；Defender 的 `Get-MpPreference` 回 0x800106ba）；證實法＝A/B（見 §5-Q1）|
| **H2** | **Sysmon 稽核每個行程／檔案事件**：`sysmon64` 在跑，抽樣 3.2% CPU，且 Sysmon 依設定對 ProcessCreate／FileCreate 寫事件日誌（核心＋使用者態）| `sysmon64` 出現在 `\Process(*)` 前 10；不知其設定（唯讀無法看 config；`sysmon -c` 需管理員）| 中。與 H1 同屬「每個檔案／行程事件的固定稅」|
| **H3** | **venv 啟動器雙行程**：`.venv312\Scripts\python.exe` 是 launcher，每次啟動多一個 `Python312\python.exe` 子行程（`Get-CimInstance Win32_Process` 看到每個 worker／pytest 都成對：9624/21072、65672/65668、73824/66700…）。每個 spawn 的測試（stepfile_drill、module_update_delivery、company_setup_cli、build 類）在 Windows＋AV 下每次啟動加倍 | 行程成對為實測；但花最多時間的檔案（H1 證據②）不 spawn | 低～中（影響閘門型檔，不影響 r2 前 7 名）|
| **H4** | **背景執行緒收尾等待**：`client` fixture 收尾 `_join_own_background_threads` 最多等 30 秒（`BG_JOIN_BUDGET_SECONDS`）/題；若題目起了結案 PDF 之類背景工作且慢（I/O 慢時更慢），每題最多白等 30 s，**等待時 CPU 工作比低** | 這是唯一一處**程式內的固定等待**；符合「worker 只有 15%」。但 r2 #1 每題 76～314 s 超過 30 s 上限 ⇒ 不能單獨解釋 | 低～中；**可用 `--durations` 的 teardown 段量**（本機唯讀不可跑，列為量測項）|
| **H5** | **同機其他負載搶 CPU**：7 個 CLI（claude）視窗＋桌面 App；我 10 秒取樣 6 個 05～06 天前開的 CLI 各 1.2～2.0% 總 CPU（約 550 MB、≈360 handles），共 ≈10%；`RAM 空閒 8.8/31.9 GB`；d8 另測每個 claude 視窗核心態 15～25%（取樣範圍不同）| 有，但**量級不足以解釋 3.4 倍**（總共 ≈10% CPU）| 低（但閘門期間值得減）|
| H6 | 全機鎖排隊（`MOTRIX_PYTEST_SLOTS`）／heavy_run 佇列 | 佇列目錄只有 1 個 official（b7，02:35）；fail_stream 無排隊紀錄；r2 #1 當時是否另有 pytest 同跑**無法回溯**（`_ci\queue` 只留現況）| 不成立／無證據 |
| H7 | 熱／降頻 | 未量（Core Temp 在跑，唯讀可讀感測器但歷史不留）| 無證據 |

**一句話**：worker 等的不是鎖、也不是子行程，而是**每個檔案操作的核心態固定稅**；Bitdefender（以及 Sysmon）是唯一在路徑上的候選。r2 #1 時段更糟的原因（同一台機器 2 小時前還是 2,600 s）**目前沒有證據**——可能是掃描引擎在那個時段做了完整掃描／更新，或同時有別的 pytest（無法回溯）。建議之後在閘門期間每 60 秒記一行「核心態 %、bdservicehost CPU、同時 python 數」到檔案（唯讀取樣腳本，列為 §4-A8）。

## 4. 省時清單

### A 組：不弱化閘門（凍結樹仍整樹整輪實跑）
| # | 做法 | 省多少（M2 實例）| 備註 |
|---|---|---|---|
| A1 | **結果計時器／完成通知**：官方閘門開跑時，由 heavy_run／run-stage 在結束時寫一行 `status` 並**主動通知** PM＋執行者；執行者前景輪詢以 `until` 迴圈＋Monitor，不靠人記得看 | **閒置 ≈ 6 時 54 分**（5:16＋1:21＋0:17；M1-a 另 53 分）。單項最大 | `heavy_run.py --status` 已存在，缺「結束即推」|
| A2 | **啟動清單（run-stage 自己設環境）**：`MOTRIX_TRAIN=1` 由 run-stage 在 `train/*` 分支上自動帶入或缺則拒跑；列出 `train_only` 測試名單（skipif `MOTRIX_TRAIN` 的題）| r2 #1 白跑 **146 分**（＋閒置 16 分）| 一行檢查，風險零 |
| A3 | **full-lint 涵蓋所有「只在閘門才會紅」的題**：把 `test_form_version_bumped`、`test_version_manifest`、ac1／demo_reset／module_keys／router_registration／wording_guards，以及 `modules/*/tests` 的守門題納入 `FULL_LINT_FILES`（STATE-M1A 與離開日誌 23:xx 已列為待辦）| r1 紅 7 題＝**≈ 2 時 30 分一輪**（43.8 分閘門＋73～81 分閒置＋64 分修復）；M1-a 紅 2 題＝≈ 1 小時 | lint 只多 17 分鐘（預檢 2850 題 1,011 s）而且在**凍結前**跑 |
| A4 | **推送前檢查（`prepush_check.py`）／整合期背景檢查（`integ_watch.py`）全面啟用**——這兩個工具**已在樹上**（`tools/platform/`），t50-prepush 估 45 件紅燈中約 24 件作者端 60 秒內可擋，r1 的 7 紅（登記／守門類）屬此類 | 紅燈整輪 ≈ 1～1.5 小時／次 | 需每個視窗 `setup_prepush.py --check`|
| A5 | **建包立即接續**：e2e 綠 → 自動觸發建包＋verify／drill＋發布 dry-check，不等人 | M1-a **53 分**（建包本身 30～45 秒＋驗證 5 分）| 結合 A1；發布與套用仍須人工授權的部分保留 |
| A6 | **時序題隔離**（`timing` marker，單程序安靜段，≈15 題 <60 秒，t50-io §3）；納入本次 4 紅：`test_company_setup_cli`（3 秒行程預算）、`test_fail_stream_aborted`（殺 worker 競態）；不降低門檻，只換跑法 | 避免負載下假紅重跑（每次 25～60 分，t50 主持實測）| 需改 run-stage 兩段式 |
| A7 | **worker 數／優先權調整**：現官方 `-n 3`（`--workers 3`）、歷史建包 `workers=4`、6 實體核；換 5900XT／5950X 後以相同 10.4k 題實測 `-n` 6／8／12（t50-io §4 預測非 e2e 用實體核數）。**先量核心態比例**：若瓶頸是 H1，加 worker 只會加稅，需先處理 AV | 估 −20～25%（t50 推算；**本報告未驗證**）| 硬體換機後才有意義 |
| A8 | **閘門期間唯讀取樣腳本**：每 60 秒追加 `核心態%／使用者態%／bdservicehost CPU／sysmon CPU／同機 python 數／空閒 RAM` 到 `D:\開發測試檔\_ci\gate_sample.csv`，把「3.4 倍」之類事件變成可回溯證據 | 不省時，但讓 H1～H7 可判定 | 純讀，<0.1% CPU |
| A9 | **閘門期間減載**：長駐的舊 CLI 視窗（6 個、05～06 天前開的）在閘門期間關閉或以 `/clear` 重啟；不殺、由使用者決定。每次 Windows App 重啟也能降低 handles | 估 ≈ 5～10% CPU（推算）| 只是減少背景稅，不能單獨救 3.4 倍 |
| A10 | **AV 排除路徑**（僅建議，我們不碰 AV）：見 Q1 | 若 H1 成立，可能回到 ~2,300 s（r2 #1 少 ≈ 100 分）| 需使用者在 Bitdefender 介面操作 |

**無閒置、無紅燈、健康速度的 2 小時預算（推算）**：not_e2e 39～44 ＋ e2e 24 ＋ 建包／驗證 6 ＋ 發布／套用 16 ＝ **85～90 分**（含 30 分緩衝＝2 小時）。r2 #1 這種 146 分的輪次一發生，2 小時就不可能；所以 **A10／A8（把慢速變成可見、可修）與 A1／A2／A3（避免整輪白跑）是並列最高優先**。

### B 組：會弱化凍結樹閘門 ⇒ 只列問題，等使用者書面裁示，**不實作**
- **Q-B1（範圍閘門）**：凍結樹的 not_e2e 只跑 `modtest --changed-since` 選出的題＋契約題，而不是整棵 10.4k 題？（省 ≈ 25～35 分／輪；風險＝橫切改動的漏網，t50 O3／第 49 班 strict-bool 15 檔 import 例）
- **Q-B2（結果快取命中）**：凍結樹上，依賴位元組相同的測試檔沿用別棵樹的綠（t50-cache L1／L2），並至少 10% 抽樣實跑、每 3 班冷跑一次？（估非 e2e 省 8～15%（L1）至 30～45 分（L2，函式級改動班）；橫切 import 班≈0）
- **Q-B3（O3 續跑／O6 分段指紋排除沒人讀的檔）**：同一凍結樹紅燈修復後，只重跑紅檔＋被改到的檔，而非整輪重跑？（r1 紅後的重跑可由 44 分降到 ≈15 分）
- **Q-B4（演練→凍結沿用）**：夜間對整合 HEAD 乾淨樹跑完整 `modtest --full`，凍結 commit 若指紋相同，官方閘門沿用（0 分）？（t50-pipeline §2.2 主張等價；因會跳過凍結後的重跑，依你的規則列為待裁示）
- **Q-B5（e2e 範圍）**：e2e 998 題只跑 `test_map` 選出的受影響頁？（省 ≈ 15～20 分，推算）
- **Q-B6（not_e2e 與 e2e 重疊）**：兩段同時跑？（省 ≈ 24 分；但 t50-io §4：e2e 需序列、共用 uvicorn、計時題對負載敏感；在 H1 未解前會更糟）

### 需使用者決定的非弱化問題（admin／安全取捨）
- **Q1（AV 排除，admin UI，我們不動）**：是否在 **Bitdefender**（Defender 已停）對下列加「處理程序／資料夾排除」，並在加入前後各跑**同一個**單檔（建議 `modules/netplan/tests/test_network_plans.py`，13 題，r2 #1 為 1,584 s、健康時預期 ≈ 100 s 內）做 A/B？
  1. 資料夾：`C:\Users\hichan\AppData\Local\Temp\motrix-runstage-*`（pytest basetemp；conftest 通過即刪）
  2. 資料夾：`D:\MOTRIX-PLATFORM\.venv312`
  3. 資料夾：`D:\開發測試檔`（各 worktree 與建包輸出）
  4. 處理程序：`D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe` 與 `C:\Users\hichan\AppData\Local\Programs\Python\Python312\python.exe`（launcher 子行程）
  安全代價：測試暫存與 venv 不被即時掃描（這些是自己產生／重建的檔案；`.venv312` 的第三方套件由 pip 下載，仍被下載當下掃描）。Sysmon 設定是否也記這些路徑需管理員查（`sysmon -c`），列為 Q2。
- **Q2**：Sysmon（`sysmon64`）設定是否對 `Temp\motrix-runstage-*` 的 FileCreate 也記事件？是則請管理員排除該路徑。

## 5. 未解與後續量測（皆為唯讀或需排程的安靜期）
- r2 #1 為何在 23:48～02:15 比 20:19～21:04 慢 3.4 倍：**無可回溯資料**。需 A8 取樣腳本。
- `--durations` 的 setup／call／teardown 分段（t50-io 已要求）：本機無法在安靜期內執行；請 b7 下一次重跑加 `--durations=50 --durations-min=1`，並把輸出存檔（目前 `--durations=20` 只印到終端）。
- 重跑結果（02:35 起）截至 04:22 尚未結束；若最終判定紅的是這 4 題＋0 其他，則下一步＝**不是產品缺陷**，是 §2.3 的負載時序題；依 A6 處理，但**是否採納這 4 題的重跑結果作為凍結樹的綠證據，需使用者書面裁示**（會牽涉閘門定義，不在本報告權限）。
