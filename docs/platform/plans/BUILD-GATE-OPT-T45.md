# 建包全閘門優化計畫（第 45 班；分析稿，只讀不跑測試）

> 起因：全閘門約 66 分（非 e2e 31＋e2e 22＋e2e 重跑 13），預算 30 分（使用者 2026-10-02／10-07 裁示：優化不得放寬任何守門，改用重用／拆慢題／範圍閘門）。
> 作者：hichan-68（受 hichan-1e 派工）。分析期間第 44 班占用測試鎖，**本文件沒有跑任何 pytest**；「[實測]」取自既有紀錄，「[推論]」須在鎖空出後依 §6 量測。
> 證據來源：`tools/platform/full_results/*.json`、`tools/platform/fail_stream/*.jsonl`（第 43 班 bld43 兩輪＋獨立 e2e）、`backend/tools/deploy_logs/test_results.jsonl`、`backend/tools/build_test_reuse.py`、`tools/platform/{scope_gate,modtest,stage_select}.py`、`tools/platform/bottom_layer.json`、`backend/conftest.py`、`docs/platform/plans/BUILD-OPTIMIZATION-2.md`、`BUILD-OPT-ITEM3-INCREMENTAL-DESIGN.md`、`docs/windows/PLAN-TEST-PERF.md`。

---

## 0. 結論先行

1. **浪費不在慢題，在三件事**：①紅了還整輪跑完（第 43 班第一輪 10 個紅全是 4～13 分內就能抓到的靜態／產生檔守門，卻白跑 51.8 分）；②兩段序列、e2e 只用 2 個 worker（e2e 在全閘門 -n 2 跑 21～22 分，同一批在 -n 4 獨立跑只要 12.7 分且全綠）；③底層一動就整棵重跑（沒有比「整棵樹雜湊」更細的重用）。慢題本身是小頭：非 e2e 前 20 檔＝24%，e2e 前 20 檔＝26%。
2. **不放寬守門就能拿到的**：O1 預演切片前置（紅的整合 −42～47 分）、O2 兩段重疊（−17～20 分）、O4 偶發快速分流（−11 分／次）、O5＋O6 慢檔與尾端平衡（−3.5～6 分）。**O2＋O5＋O6 後乾淨全閘門估 30～34 分**（待 §6 量測），再加 O7（使用者離開時 -n 6）可到 25～28 分。
3. **要「底層動了也不用整棵重跑」只有 O9（執行層級重用）**：以實際執行到的程式碼＋讀到的檔案做依賴指紋，沿用祖先全量的綠。可把第 44 班這種動底層 helper 的班從 66 分壓到估 20～25 分，但工程量最大、風險最高，必須先影子驗證兩週、且需使用者裁示。**不建議跳過 O1～O6 直接做 O9。**
4. 需要使用者裁示的見 §8。

---

## 1. 基準（第 43 班全閘門，[實測]）

| 輪 | 時間 | 非 e2e | e2e | 結果 |
|---|---|---|---|---|
| bld43 第 1 輪（HEAD 3c8f8b6b，`modtest --full`） | 16:33:57～17:25:46＝51.8 分 | 1822.9 s，9297 過／**10 紅** | 1249.8 s，934 過／**2 紅** | 紅 |
| bld43 第 2 輪（HEAD 89206122） | 17:34:55～18:27:51＝52.9 分 | 1808.2 s，9307 過／0 紅 | 1328.8 s，935 過／**1 紅** | 紅（e2e 一題） |
| 獨立 e2e 重跑（同一棵樹，`run-stage e2e`） | 18:28～18:41＝12.7 分 | — | **764.5 s**，936 過／0 紅 | 綠（沿用進建包） |

- 第 1 輪 10 個紅（第一個在 +4:00、最後一個在 +12:55，之後白跑 38 分）：`test_dep_graph_json_is_current`、`test_test_map_json_is_current`、`test_unit_index_is_current`（產生檔過期）、`ac1_every_page_either_writes_something_or_is_registered`、`cm12 小字級 ×2`、`alpine_double_init ×2`、`begin_appears_only_in_begin_write`、`module_keys…unread_by_design`——**全部是靜態／掃描型守門，與慢題無關，且都是整合後才紅**。
- e2e 三次不同的紅（`case_page_golden`、`bonus_case_page::outsider…`、`home_waiting_for_me_sync`）皆在 `modtest --full` 的 **-n 2** 下、機器同時有別的視窗在跑；同一棵樹獨立 -n 4 跑 936 題全綠。⇒ 負載下的時序題（依政策先當產品競態查），也是「重跑 13 分」的來源。
- 機器：Ryzen 5 5600X，6 核／12 緒，RAM 31.9 GB（量測當下可用 17.4 GB，多個 Claude 視窗並行）。
- 預設 worker：非 e2e `-n 4`（`modtest.FULL_MAX_WORKERS`）、e2e `-n 2`（`E2E_MAX_WORKERS`，2026-09-26 記憶體事故）；建包腳本的 e2e 是 `-n 4`。**兩條路徑上限不一致**。

## 2. 時間去向（[實測]，第 2 輪）

| 段 | 總 worker‑秒 | 題數 | 平均 | 前 20 檔 |
|---|---|---|---|---|
| 非 e2e（-n 4，1808 s） | ≈7,230 | 9,307 | 0.78 s/題 | 1,729 s（24%） |
| e2e（-n 2，1329 s） | ≈2,660 | 935 | 2.84 s/題 | 693 s（26%） |

非 e2e 前 10 檔（秒／題數）：`test_module_update_delivery` 198／45、`test_finance_role_matrix_ext` 163／77、`test_ledger_mutation_guards` 119／8、`test_dashboard_finance_cards_access` 102／31、`test_bonus_correction` 101／23、`test_quote_json_lost_update` 82／43、`test_bonus_case_api` 79／25、`test_custom_modules_engine` 75／58、`test_scope_gate` 75／103、`test_module_changelog_follows_code` 73／18。
類型：測工具本身（巢狀 pytest、drill、`modtest --dry-run` 子行程）、權限矩陣（角色×端點）、突變守門（每個突變一份 setup＋call）、薪資獎金 API。最慢單題 88 s，前 14 慢題合計約 570 worker‑秒＝約 2.4 分牆鐘。**題目耗時是平的，加速慢題最多省 3～6 分。**
已完成（不再重做）：範本庫（`_template_db`）、共用瀏覽器／伺服器、e2e 逐題上限、fail-fast＋failfirst（**只接在建包腳本，`modtest --full` 沒有**——第 1 輪 10 紅仍跑完整輪可證）、段結果沿用（整樹雜湊）、`scope_gate`（只管正式機基準→候選且不含底層）。

## 3. 為什麼動到底層就強迫全量（機制鏈）

1. **`scope_gate` 規則 fail closed**（`tools/platform/bottom_layer.json`，由上而下第一條符合者；沒有符合 ⇒ bottom）：`**/conftest.py`、`backend/pytest.ini`、`requirements*`、`modules/*/migrations/**`、`backend/core/**`、`backend/helpers/**`、`backend/db.py`、`migrations_frozen/**`、`backend/main.py`、`backend/routers/**`、`backend/tools/**`、`tools/**`、`product/**`、`frontend/{static,js,css,fonts}/**`、`index.html` 全是底層。`decide()` 只要有**一個**底層檔 ⇒ `mode="full"`。第 44 班的 diff 動到多個 `helpers/**`、`core/CHANGELOG`、`frontend/static/attach-picker.js` ⇒ 一定全量。
2. **就算改用差異選題也擴不小**：`modtest --dry-run`（第 44 班 diff）挑出 169 單位、**9,120／10,331 題（88%）**。原因：(a) `import main` 組裝所有 router，靜態 import 圖裡 helper→router→`core:main`；(b) 規則 5：`client`／`live_server` fixture 讓所有 api／e2e 題隱含依賴 `core:main`；(c) `core:db` 的 `dynamic_sql` 保守擴大。**靜態圖分不出「哪一題真的執行到這個函式」**，只能往寬選。（`direct+iface` 規則只在 helper 私有改動時才縮得小。）
3. **段結果沿用只認整棵樹**（`build_test_reuse.fingerprint`＝`ls-tree -r HEAD`＋環境）：任何一個檔、包括不影響執行的文件，都讓兩段整個失效；`stage_select`（增量段）已設計但**只 dry-run、沒接進建包**，且遇「硬底層」仍強制全量（設計 §5.2）。
4. 以上都是**正確的保守**；要在不放寬下縮小，只能：提高依賴資訊精度（O9）、降低「為了找紅而重跑」的成本（O1／O4）、把同樣的工作更快做完（O2／O3／O5／O6／O7）。

## 4. 選項

> 估算基準：非 e2e 30.4 分、e2e 21.5 分（-n 2）、獨立 e2e 12.7 分（-n 4）。「省」＝對一次乾淨全閘門或一次紅的整合；[推論] 一律待 §6 量測。

| # | 做法 | 省（估） | 風險 | 反向控制（證明沒放寬） | 前置／裁示 |
|---|---|---|---|---|---|
| **O1** | **預演切片前置**：全閘門第一片＝重產並驗證產生檔（dep_graph／test_map／UNIT-INDEX）＋`tests/platform`＋全域釘子（`global_tests`）＋第 43 班第 1 輪那類靜態守門，**-n 4、fail-fast**；綠才開第二片。`modtest --full` 接上建包腳本已有的 failfast／failfirst（`MOTRIX_FAILFAST`、`MOTRIX_FAILFIRST`）。切片清單單一來源 `tools/platform/gate_slices.json`，`pre_train_check` 讀同一份。 | 紅的整合：51.8→≤10 分（**−42～47 分**）；綠的：0（切片是整段子集，總題數不變）。第 43 班第 1 輪 10 個紅預估 +13 分內全出現。 | 低。切片漂移；作者少跑預演。 | `slice0 ∪ rest` 的 nodeid 集合＝單一 run 的 `--collect-only` 集合（sha 比對）；全綠 run 執行題數＝收集題數；植入紅於 slice0 ⇒ ≤10 分失敗；已登記偶發不計；停止必 exit≠0 且記紅（沿用 BUILD-OPTIMIZATION-2 項 1 的 R1-a～e）。 | 動 `tools/**`（底層）⇒ 本身走全閘門；第 44 班上線後再落地 |
| **O2** | **兩段重疊**：非 e2e `-n 4` 與 e2e `-n 2` **同時**跑（2 個 pytest 行程各占一格全機鎖，合計 6 worker＝實體核心數，仍低於 §C-13 的「2 組×-n 4」；皆 BelowNormal）。 | 52.6→≈33～36 分（**−17～20 分**）[推論：關鍵路徑＝非 e2e 30.4 分＋約 10% 爭用；e2e 被遮蓋] | 中。e2e 時序題在 CPU 滿載下偶發率可能升；記憶體；使用者機器可用性。 | 同一棵樹 A/B（序列 vs 重疊）逐 nodeid 結果集相同、各 2 次；e2e 同樹連 3 次不得出現新紅；`MOTRIX_FULL_OVERLAP=0` 一鍵還原；起跑前 `build_preflight` 無其他 pytest、可用記憶體 ≥ 門檻，否則自動序列。 | **需裁示**（§8-1）；先量測 |
| **O3** | **e2e 在全閘門也用 -n 4**（與建包腳本一致），記憶體守門（可用 ≥ 8 GB 才升）。與 O2 二選一（O2 較省）。 | e2e 21.5→≈12.7 分（**−9 分**）；獨立 -n 4 936 題全綠為證 | 中。2026-09-26 -n 4 曾因記憶體被停；其他視窗同時吃記憶體。 | 起跑前記憶體檢查＋e2e -rf；結果集對照；每 worker RSS 量測（§6）。 | 需裁示；先量 e2e 每 worker RSS |
| **O4** | **偶發快速分流**：出紅時立刻把「紅的那幾題」單獨重跑 ×3（≤2 分），印出「3/3 綠＝疑似負載偶發／3/3 紅＝真紅」；**階段結果與登記規則完全不變**（未登記偶發仍擋）。`modtest --full` 比照建包腳本的 `Invoke-FlakyRetry`，已登記且未過期的偶發才放行。同時把第 43 班三個負載下才紅的 e2e 當產品競態逐一查根因。 | 重跑 12.7 分→2 分診斷（**−11 分／次**，僅限已登記偶發；未登記者仍須修或登記，但診斷提早 11 分） | 低。誤判成真紅只會多擋，不會放行。 | 已登記→放行、未登記→擋（沿用 `test_build_opt_2026_09_30`）；`flaky_retried[]` 進 manifest；重跑題集＝紅題集。 | 無 |
| **O5** | **慢檔瘦身（不減題數）**：`test_module_update_delivery`（45 題×4.4 s，每題起 `modtest --dry-run` 子行程）改進程內呼叫＋同一 diff 輸入的選題結果快取；`test_ledger_mutation_guards` 的 setup 改 module scope（先證明各突變間狀態還原）；權限矩陣（`finance_role_matrix_ext`、`dashboard_finance_cards_access`）只讀的部分共用同一份 app／庫。 | 估 −600～900 worker‑秒＝**−2.5～4 分**（非 e2e） | 低～中。共用 fixture 讓案例互相污染；快取讓子行程路徑沒被驗到。 | 每項前後逐 nodeid 結果集相同；突變守門「每個突變是否被偵測」逐一相同；保留一題走真實子行程路徑。 | 無 |
| **O6** | **尾端平衡**：依歷史單題耗時 LPT 排序（慢檔先派），xdist `--dist worksteal`（先驗版本支援）。避免 88 s 的題落在最後一輪。 | −1～2 分 | 低。 | `--collect-only` 題集重排前後 sha 相同。 | 無 |
| **O7** | **離開窗口調高 worker**：`MOTRIX_FULL_MAX_WORKERS=6`（環境變數，已存在，**零程式碼**）。 | 非 e2e 30.4→≈21～23 分（**−7～9 分**）[推論：線性上限 −33%] | 中。CPU 100%（使用者痛點）、時序題。 | 同 O2；使用者本人說「離開」才用（有 2026-09-26 先例，CORE-SPEC 裁示表）。 | **每次需使用者說離開** |
| **O8** | **指紋精度**：`REUSE_EXCLUDE` 加入「從沒被任何測試讀過」的檔（先用 `sys.addaudithook` 的 `open`／`os.listdir`／`os.scandir` 事件在一次全量中記錄所有被讀的 repo 檔與被列舉的目錄，只排除既不被讀也不在被列舉目錄內者，例如 `docs/platform/RUN-LOG.md`、`prod-tasks/*.md`、`audit/*.md`）。 | 乾淨流程 0；避免「閘門之後只動了無關文件」就整輪重跑（−52～66 分／次） | 低。漏記一個被讀的檔⇒假沿用。 | 被排除的檔改一個字⇒指紋不變；被讀的檔改一個字⇒指紋變；全量中任何新讀到的檔＝紅（棘輪）。 | 無（分析可先做） |
| **O9** | **執行層級重用**（取代「靜態圖＋整樹雜湊」）：每個測試檔記錄**實際執行**的函式區塊（`sys.monitoring`〔Python 3.12，開銷低〕或 coverage 動態 context）＋被讀的非 Python 檔（O8 的 audit hook）＋子行程標記；依賴指紋＝`sha256(env ‖ 被執行區塊內容 ‖ 被讀檔 blob ‖ 測試檔本身)`。祖先全量（同環境、≤N 天）的綠，指紋沒變的測試檔直接沿用；**fail closed 全量**：指紋缺、新測試、環境／選題器變、`date_sensitive`、起子行程（git／pytest）、掃目錄型、`conftest`／fixture 層。模組層級程式碼（常數、裝飾器、註冊）每個 worker import 時就執行 ⇒ 改了它＝全部重跑（正確）。 | 第 44 班型（動底層 helper，呼叫端 ~15～35%）：66→**≈20～25 分** [推論，待離線重放]；小改 10 分內 | **最高**：依賴捕捉漏洞＝假綠。 | ①離線重放：取近 30 個「紅→修」commit，對每個**反向還原**，被修的測試必須被選到且在反向版本上紅（召回 100% 為上線門檻）；②突變：對近 N 個 commit 改動行植入突變，全量紅集 R ⊆ 重跑集 S；③**影子**：前 2 週每次沿用放行的包，夜裡閒置時仍跑一次全量，差異＝0 才算過；④每週一次強制全量；⑤`selected ∪ carried ⊇ collected` 缺口擋。 | **需裁示**（§8-3）；3～5 天原型＋兩週影子；先 O1～O6 |

## 5. 建議組合與預估

| 階段 | 內容 | 乾淨全閘門 | 紅的整合 | 備註 |
|---|---|---|---|---|
| 現況 | — | 52.6（含 e2e 重跑 65～66） | 52＋52（各輪全跑完） | 第 43 班實付 117 分 |
| A（無鎖，先寫） | O1＋O4＋O8 分析＋O5／O6 程式修改（第 44 班上線後才合） | 同上 | **≤10＋乾淨** | O1 是單項最大省（避免整輪白跑） |
| B（鎖空出後量測、再切換） | ＋O2（或 O3）＋O5＋O6 | **≈30～34** | ≈10＋30～34 | 乾淨全閘門逼近 30 分預算 |
| B＋（使用者離開） | ＋O7 | ≈25～28 | — | 每次需裁示 |
| C（影子兩週後） | ＋O9 | **≈20～25**（底層動了也是） | ≈10＋20～25 | 風險最高 |

## 6. 量測計畫（第 44 班落地、鎖空出後；一次一組、-n 不超過上限；只刪自己的暫存）

1. **同一棵樹 A/B**：序列（現況）vs 重疊（O2）各 2 次；記錄牆鐘、每段時間、CPU 利用率（Windows 效能計數器 `\Processor(_Total)\% Processor Time`，5 秒取樣）、可用記憶體最低值、逐 nodeid 結果集（fail_stream JSONL）。
2. **e2e 每 worker RSS**（chromium＋uvicorn＋python）：-n 2／-n 4 各取尖峰，決定 O3 的記憶體門檻。
3. **setup 佔比**：`--durations=0` 取非 e2e 的 setup／call／teardown 分布（現有紀錄沒有 setup 欄），確認範本庫之後 `client` 固定成本是否仍有大宗。
4. **O9 可行性（離線）**：用 `sys.monitoring` 在 20 個代表性測試檔上記錄執行區塊，量記錄開銷與「改動一個 helper 函式時被選中的測試檔比例」。
5. **負載下 e2e 紅**：第 43 班三題各在 -n 2／-n 4／序列重跑 5 次，區分真競態與資源爭用。

## 7. 不放寬守門的檢查表（每項落地前逐條過）

- 題數不減：`slice0 ∪ rest`、重排前後、`selected ∪ carried` 的 nodeid 集合與單一 `--collect-only` 相等（sha 記進 manifest）。
- 紅的語意不變：任何未登記紅 ⇒ 段記紅；停止／分流不可把「沒跑完」記成綠或被沿用；已登記偶發規則與到期日不動。
- 沿用只在「同樹或可證依賴不變」時發生；環境、選題器、時鐘、`MOTRIX_*`（非 allowlist）任一變 ⇒ 全量。
- 每項附反向控制（上表），並走 `tools/**` 底層規則（本身全量驗證）。
- 發行前仍有一次**真全量**（O9 的鏈根；每週強制）。

## 8. 需使用者裁示

1. O2：兩段重疊＝同時 6 個 worker（仍在「2 組×-n 4」內，BelowNormal）；全閘門期間機器較忙但總時間縮短。是否同意先量測再切換？
2. O3：全閘門 e2e 從 -n 2 提到 -n 4（記憶體守門）；與建包腳本一致。是否同意？（與 O2 擇一）
3. O9：是否接受「祖先全量的綠，依執行層級依賴指紋沿用」作為發行閘門的一部分（含兩週影子驗證、每週強制全量）？這是本計畫中唯一改變「何時需要重跑」語意者。
4. O7：照 2026-09-26 先例，使用者說「離開」才啟用 -n 6。

## 9. 開放問題

- 第 43 班三個 -n 2 下才紅的 e2e 是產品競態還是資源爭用？（§6-5）
- `modtest --full` 與建包腳本是否合併成同一條路徑（現在 worker 上限、failfast、偶發重跑各有一份）？合併可一次解決 e2e -n 2／4 不一致與 O1／O4 重複實作。
- O8 的 audit hook 在 xdist 子行程／巢狀 pytest 中的覆蓋（子行程需另掛）。
