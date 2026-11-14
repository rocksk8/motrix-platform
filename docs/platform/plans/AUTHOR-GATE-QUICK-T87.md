# author_gate --quick（T87 A2）：作者端 5 分鐘快速守門

> 設計延伸自 `AUTHOR-GATE-DESIGN.md`；本文只寫 T87 新增的部分。規格來源：`D:\Claude-pm\t87-plan.md` A2。

## 目標與界線

- 作者推 sha 前跑 `python tools/platform/author_gate.py --quick`，**預設預算 5 分鐘**（`--budget-min` 可改）。
- 只當**部分證據**：不替代建包的完整階段；沒跑的一律印「未跑」，不能看起來像通過。
- 抓的是 T86 診斷／整合階段才冒出來的紅燈類型：**過期斷言**（來源文案或結構改了，舊測試沒改）和**守門類**（邊界、golden、登記、字級、寫法檢查）。

## 選題的優先層

| 層 | 內容 | 超預算時 |
|---|---|---|
| T0 | 本分支新增／修改的測試檔 | 必跑，只警告 |
| T1 | 被 diff 觸發的整合守門組（`preflight_guards.json` 的 `watch` 是唯一規則表）＋ quick 專用補充組（`QUICK_EXTRA_GROUPS`） | 必跑，只警告 |
| T2 | **字面值反查**：diff 刪掉、且沒在新增行重現的字面值，去 grep 測試檔 | 必跑，只警告 |
| T3 | 檔名樣式守門（`guard_patterns.json`，含新的 `*text_anchor*`） | 必跑，只警告 |
| T4 | 改動模組自己的測試、頁面／前端 js 關聯測試 | **由後往前砍**，砍掉的逐檔列為「未跑」 |

- 太大的整合守門組（`static_scans2`、`recent_interplay`、`superadmin_login`）整組列為「未跑（太大）」。
- e2e 檔（T1／T2 選到的也算）走 e2e 那一段，預算估算每檔 20 s。
- 輸出尾端：`⚠ 未跑 N 項（上面列了；不是通過）`；結果 JSON 的 `quick_skipped` 同步記錄。

### 字面值反查（T2）為什麼是主力

T86 診斷紅燈的主要型態是「來源改了一句文案或一段結構，測試還在斷言舊的」。測試常只斷言來源整句的一小段
（來源刪 `您沒有任何變動可儲存`、測試寫 `沒有任何變動`），所以除了拿來源整段去 grep，還做**反向**：
一次 `git grep` 取出全部測試文字（約 20 MB、約 1 s），抽出測試裡的字面值，凡「⊂ 被刪文字、且不在新增行」的都拿去反查。
命中超過 25 個測試檔的字面值視為太通用，不選，並寫進輸出的備註。

## 測試寫法守門：禁止用文字子字串當計數或錨點

- 掃描器 `tools/platform/text_anchor_scan.py`（AST）：`<x>.count("標記")`、`.index/.find/.rindex/.rfind/.partition/.rpartition("標記")`、`.split("標記")[n]`，
  標記＝字串常數（或同檔頂層常數名），長度 ≥3 且含中文或標記字元；純英數單字不算。
- 守門測試：`backend/tests/platform/test_no_text_anchor_in_tests_2026_11_14.py`。
- 逃生口：同一行加 `# text-anchor-ok: <理由>`（理由必填）。
- **棘輪**：既有檔命中數記在 `backend/tests/platform/text_anchor_baseline.json`（787 處／228 檔），**只准減少**；新檔與有改動的檔超過基線＝紅。
  另有 `BASELINE_TOTAL_CEILING = 787` 當第二道釘子，調高基線＝測試紅。基線不得為了讓新測試過關而放寬。
- 要改的寫法：用 `data-testid`、結構（AST／正規式抓結構）、行為比對，不用文案當定位。

## T86 紅燈 → 哪個 quick 檢查本來能抓到

| T86 紅燈（修復 commit） | 弄壞的 commit | quick 的哪一層抓 |
|---|---|---|
| 13 單元＋19 e2e 過期斷言（c03909aa6） | 各檔各自的來源改動 | T2 字面值反查（含反向探針） |
| fx33 空狀態探針（bcb5fc87f） | 文案中性化 | T0／T2；之後 text_anchor 守門禁止同型寫法 |
| page_paths（b01e9ee2b） | 91122952e | T1 `q_page_paths`（測試放在 modules/*/tests 時 preflight 的 watch 看不到） |
| 規格編號重複（b01e9ee2b） | 29674b1c2 | T1 `spec_coverage` |
| L1 不得 import L2（9140ef9a8） | 807d26cea | T1 `q_boundaries` |
| route table golden 缺列（44ee7cd94） | 807d26cea | T1 `route_inventory` |
| 裸 vh（dc738d58d） | a4b2040f1 | T3 檔名樣式（font） |
| 「重啟」按鈕（9d257a924） | c93d6213c | T0（該批次連同 e2e 測試一起改） |
| e2e-lint（0e5f917f7） | 14eb792c4 | T1 `q_e2e_lint`（e2e 測試不一定叫 `test_e2e_*`） |
| bottom_layer 登記（2cb59c77c） | 50e16277e | **範圍外**：是 `pre_train_check` A3 工具檢查，不是 pytest；交給整合者一鍵（h4） |
| L1 快照卡片（bae0c67e0）、write-lock／log_setup（12e5a7ca8） | — | 離線無法辨識是哪個守門紅；實跑後補歸因 |
| CHANGELOG heading／版號／FORM_VERSION | — | T1 `changelog`／`version_slots`／`version_manifest`（本版回放案例尚未納入，實跑後補） |

## 回放驗收

```
python tools/platform/quickgate_replay.py            # 離線：只讀 git，不跑 pytest
```

案例表 `tools/platform/quickgate_replay_cases.json`。判定以**測試檔**為單位：該檔在 quick 的選題（T0–T4 要跑的）內＝抓到；只在「未跑」或沒選＝漏抓；
找不到弄壞的 commit（pickaxe 失敗）＝漏抓，不略過。

### 預估（離線選題，2026-11-14，未真的跑紅）

- 全部 **17／31＝55%**；範圍內 17／28＝61%。**未達 80%**。
- 可歸因的 19 個檔裡抓到 17 個（89%）；漏的 2 個是 `test_module_startup.py`（移動行，字面值在新增行重現）與 `test_e2e_legal_params_r1`。
- 拉低數字的是 **12 個無法離線歸因**（c03909aa6 的 9 個 e2e／單元檔：多半是產品行為改變、測試的舊值不是來源字面值；另 3 個範圍外／未辨識）。
  這 12 個在離線無法證明抓得到或抓不到，一律記為漏抓。

### 實測（待安靜期解除後）

做法：在每個弄壞的 commit 的樹上真的跑 `--quick`，確認預期測試檔紅；同時補歸因與缺的案例（CHANGELOG／版號／FORM_VERSION），
再決定要不要為「行為改變型」過期斷言加第二道（例如 T4 納入被改函式的呼叫端測試）。**實測數字出來前，不報達標。**

## 限制與後續

1. 字面值反查抓不到「行為改變、字面值沒變」的過期斷言——這一類靠 T4（模組自己的測試）與階段測試。
2. 預算估算用 `題數 × 0.75 s`（e2e 每檔 20 s）；`gate_file_seconds.json` 只有 10 個種子檔，實測後應補。
3. quick 專用補充組（`q_boundaries`、`q_e2e_lint`、`q_page_paths`）不改整合者的 `preflight_guards.json`；若整合者之後把 watch 補齊，可從 `QUICK_EXTRA_GROUPS` 拿掉。
4. 整合者一鍵工具（resolve_baselines → train_number → regen → 步驟檔）由 h4 負責，不在本分支。
