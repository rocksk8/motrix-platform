# author_gate（建包優化 step 4）：作者在推「最終 sha」前跑的一支指令——設計（d7；2026-10-02；**只設計，不實作**）

## 0. 結論先行
- 第 31 班整合 5 輪才跑完，每輪露出不同的「作者沒跑的守門」：e2e marker、31-C 登記×9、changelog、字級 vh、金額往返、spec owner map（外加子模組的個資備份鏡像測試）。**這 7 類全都落在下面 (a) 的集合裡**——`tests/platform` 整個目錄、六組檔名樣式的守門檔（要跨 `backend/tests` 與 `modules/*/tests`）、test_map 對改動檔的受影響題。
- **預估時間（實測基礎）**：`tests/platform` 整個目錄 2253 題＝**6 分 17～6 分 26 秒**（-n 4，不含 e2e；本班實測兩次：383.5 s、377.1 s）；六組樣式守門檔（37 檔／315 題）＝**69～81 s**；test_map 受影響題典型 1～3 分。合計 **約 9～11 分**，落在 ≤12 分的預算內；改動多時由「受影響題」那一項膨脹，工具要印預估並在超過預算時**警告但不砍任何一項**。
- 結果寫 JSON（綁 **tree sha**＋環境指紋）；`pre_train_check` 與建包讀得到——**同 tree 且綠＝這一部分不重跑**，但**不得**當整段（not_e2e／e2e）的綠使用（它只是子集，見 §4）。
- 回放驗證（第 31 班 5 輪紅）：把每個紅燈 commit **之前**的樹丟進去，必須紅（§6）；離線先用 `stage_select` 的選題確認「會選到那些紅檔」，再用實跑（影子期）驗證。

## 1. 指令與輸出
```
python tools/platform/author_gate.py [--base <ref>] [--budget-min 12] [--json-out <path>] [--dry-run]
```
- 預設 `--base`＝`git merge-base HEAD origin/platform`（作者分支與整合基準的分歧點）；工作樹**必須乾淨**（含未追蹤檔，同 `build_test_reuse` 指紋規則）；不乾淨 ⇒ 拒絕並列出檔案。
- `--dry-run`＝只算選題與預估分鐘，不跑（直接用 `stage_select plan` 的函式）。
- 一次一個 pytest 行程樹（遵守測試鎖／全機測試負載上限；`-n 4`，與建包同）；`fail_stream`＋`failfast`（`MOTRIX_FAILFAST=1`，N=10）照用——紅了早停、印出紅清單，**不放水**。
- 結束印一行摘要：`作者閘門：綠／紅，實跑 N 題，M.m 分鐘（預估 E.e 分），tree=<sha12>，結果檔=<路徑>`；紅 ⇒ exit 1。

## 2. 內容（集合 a；全部跑，缺一項就紅）
| 組 | 內容 | 為什麼（對應本班哪一輪） | 時間（實測／估計） |
|---|---|---|---|
| A1 | `backend/tests/platform/` 整個目錄（`-m "not e2e"`） | e2e marker 分類、31-C 登記（簽核範圍、佇列覆蓋、`**` 呼叫、json_extract 棘輪、遷移登記）、changelog 跟著程式、module boundaries、spec owner map 之類的跨檔守門 | **6:17～6:26 實測**（2253 題） |
| A2 | 檔名樣式守門檔：`*approval*`、`*queue*`、`*pii*`、`*privacy*`、`*migration*`、`*spec_coverage*`、`*font_zoom*`（含 `vh` 字級）、`*money_round*`、`*changelog*`（**要同時掃 `backend/tests/` 與 `backend/modules/*/tests/`**——子模組的 `test_pii_archive_mirror` 就在後者）；`-m "not e2e"` | 個資備份鏡像（子模組版）、字級 vh、金額往返、spec owner map、簽核佇列覆蓋 | 37 檔／315 題＝**69～81 s 實測**（含上面 A1 重複的檔去重） |
| A3 | test_map／`stage_select.plan` 對「本分支改動檔」選到的題（`selected`＋`red_reselect`；e2e 另跑：改動頁面／JS 對應的 e2e，單獨成一段並印分鐘） | 作者自己改的模組的題；改到頁面就跑那頁的 e2e | 典型 1～3 分（估計）；e2e 部分依頁面數 |
| A4 | 作者**新增／修改的測試檔本身**（`git diff --name-only <base>` 中的 `test_*.py`） | 新題至少要在作者機上綠過 | 依檔數（小） |
- 去重後取聯集；A1∪A2 為**底板**（不因 diff 而省）；A3、A4 隨 diff。
- 預估＝Σ（各檔歷史秒數；沒有就 0.60 s／題）÷ 有效 worker 數；歷史秒數來自 `fail_stream` summary 的 `slowest_files` 與 `build_log_report`（BUILD-OPTIMIZATION-2）。**超出 `--budget-min` 時只警告**（印出占時間最大的前 10 個檔，建議作者別拆測試集合——時間問題用「先跑最可能紅的」＋早停解，不是砍守門）。

## 3. 結果 JSON（`tools/platform/author_gate_results/<head12>.json`；不進 git，`.gitignore`）
```
{ "version": 1, "head": "<40>", "base": "<40>", "tree_sha": "<ls-tree 雜湊，同 build_test_reuse>", "env_sha": "<同指紋的環境部分>",
  "selector_sha": "<scope_gate/modtest/test_map/stage_select/author_gate 的雜湊>",
  "groups": { "A1": {"files": N, "tests": N}, "A2": {...}, "A3": {...}, "A4": {...} },
  "collected": {"count": N, "nodeid_sha256": "..."}, "ran": {"passed": N, "failed": 0, "errors": 0, "skipped": N},
  "green": true, "duration_s": 612.3, "estimate_s": 640, "fail_stream_run": "<id>", "started": "...", "finished": "...",
  "stopped_by_failfast": false }
```
- 防偽（同 W4 規則）：紀錄必須有對應的 fail_stream summary（`collected`、`exitstatus`）；讀取端**現場重算** `tree_sha`／`selector_sha`，不符就當沒有紀錄。

## 4. 與 `pre_train_check`／建包的接口（誠實的邊界）
- **可以省的**：`pre_train_check` 的 `tests/platform` 那一段——結果檔存在、`tree_sha` 與合併後的預演樹相同、`green`、A1 全含 ⇒ 不重跑（預演樹與作者樹不同就沒有這個證據；整合樹幾乎一定不同——所以收益主要在「作者分支被原樣 fast-forward 整合」與「列車內最後一個人」）。
- **不可以省的**：建包的 not_e2e／e2e **整段**。作者閘門只是子集（A1∪A2∪A3∪A4 ⊂ 全量），**不得**寫進 `test_results.jsonl` 的段落紀錄（那會讓建包誤以為整段綠）。若要留痕，只寫 `stages.<段>.partial_evidence = [author_gate:<head12>]`（新欄位，舊讀法忽略）；建包 manifest 的 `verification` 只「附註」，不改 `ran/reused` 判定。
- 價值主要是**把紅燈提前到作者手上**（5 輪整合 → 0～1 輪），不是省建包時間。

## 5. 風險與誠實的限制
1. 只能證明「作者機上、這棵 tree 上這批題綠」；整合後的**組合**問題（兩個分支各自綠、合起來紅）它抓不到——那由整合樹的 `pre_train_check`／建包抓（本班的 spec owner map 與 changelog 編號有一部分就是這型）。
2. 檔名樣式會漏（命名不照樣式的守門）：樣式清單要有守門題「每個 `tests/platform` 以外的跨檔守門檔都在樣式或 `author_gate_extra.json` 裡」（用 `test_map` 的 `kind=path|dir|audit` 與全樹掃描型偵測補，同 BUILD-OPT-ITEM3 的掃目錄偵測器）。
3. 12 分預算在「改動多、e2e 多」時會超：預算只警告，不砍；真正要省時間走 BUILD-OPTIMIZATION-2 的項 1／3。
4. 共用資源：它自己就是一個 6～11 分鐘的 `-n 4` 行程，**不可與整合預檢／建包同時**（沿用測試鎖；工具開跑前列出其他 pytest）。

## 6. 回放驗證（d）：本班 5 輪紅燈必須全部被抓到
輸入表（每列：紅燈 commit 之前的樹＝`<red-parent>`；預期紅的題；應由哪一組抓到）——由主持／作者補齊 commit：
| 輪 | 紅燈 | 應抓到的組 |
|---|---|---|
| 1 | e2e marker（沒帶 `@pytest.mark.e2e` 的瀏覽器測試） | A1：`tests/platform/test_e2e_classification.py` |
| 2 | 31-C 登記×9：`**` 呼叫、`json_extract` 棘輪、簽核套用範圍、佇列覆蓋×2、遷移登記、個資告知欄位 | A1（`test_case_summary_purpose`、`test_json_extract_ratchet`、`test_module_migrations`、`test_pii_forms_notice`）＋A2（`*approval*`／`*queue*`／`*pii*`／`*migration*`） |
| 3 | changelog 跟著程式 | A1：`test_module_changelog_follows_code.py`（＋A2 `*changelog*`） |
| 4 | 字級 vh | A2：`*font_zoom*`（要確認該檔在 `backend/tests/` 或模組 tests 下） |
| 5 | 金額往返（`test_money_round_half_up`） | A2：`*money_round*` |
| 6 | spec owner map | A2：`*spec_coverage*` |
| 7 | 子模組個資備份鏡像（`modules/subcontract/tests/test_pii_archive_mirror…`） | A2：`*pii*`（**跨 `modules/*/tests/`**） |
- **離線預檢（不跑測試，分鐘級）**：用 `stage_select plan --base <red-parent> --head <red-commit>` 驗「A1∪A2∪A3 選題包含該紅檔」＝召回 100%；缺的樣式補進 A2。
- **實跑回放（影子期，需獨佔窗口）**：對每一輪 `git worktree` 在 `<red-parent>` 套上「該輪作者的最終分支內容」（即紅燈 commit 本身）跑 `author_gate`，**必須紅**，且紅清單包含上表的題；7 輪 × ≤12 分 ≈ 1.5 小時（可只跑 3 輪代表：2、4、7）。
- 反向控制（守門本身）：①把 A2 的某個樣式拿掉 ⇒ 守門題「樣式涵蓋清單」紅；②把 A1 縮成只跑一半目錄 ⇒ 守門題「A1＝整個 platform 目錄」紅；③結果檔的 `tree_sha` 被改一個字 ⇒ 讀取端拒絕；④工作樹不乾淨 ⇒ 拒絕執行；⑤紅了仍寫 `green:true` 的突變 ⇒ 轉紅。

## 7. 實作步驟與工作量（建包忙完後；全部在分支、不碰 build 腳本）
| # | 內容 | 工作量 |
|---|---|---|
| 1 | `author_gate.py`：選題（重用 `stage_select`）＋底板樣式＋預估＋執行（pytest 指令同建包）＋JSON 結果＋exit code | M（~1 天） |
| 2 | 樣式涵蓋守門題＋反向控制＋dry-run 測試台（自造小 repo；同 `test_stage_select`／`test_failfast` 作法） | M（~0.5～1 天） |
| 3 | `pre_train_check` 讀結果檔（同 tree、綠 ⇒ A1 不重跑）；`build_test_reuse` 的 `partial_evidence` 欄位（舊讀法相容） | S（~0.5 天） |
| 4 | 回放（離線預檢＋影子期實跑 3 輪） | S＋獨佔窗口 ~40 分 |
**待確認**：①預算 12 分是「作者機單人」還是含 e2e A3？（本設計 A3 的 e2e 單獨成段、不計入預算警告）；②結果檔位置放主工作樹（worktree 共用，同 `test_results.jsonl`）還是各 worktree；③`--base` 預設是否改成「上一次整合基準 tag（prod/*）」以涵蓋更多 diff。
