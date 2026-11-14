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
| T4 | 改動模組自己的測試、頁面／前端 js 關聯測試、**引用改動頁面／js／工具檔名的測試**、**打改動路由的測試**（AST 取被 diff 改到的處理函式的固定路徑前綴）；e2e 一律排最後 | **由後往前砍**（e2e 最先），砍掉的逐檔列為「未跑」 |

- 太大的整合守門組（`static_scans2`、`recent_interplay`、`superadmin_login`）整組列為「未跑（太大）」。
- **凡是沒選到、或只選了一部分的都進 `skipped`（印「未跑」）**：太通用的字面值（只選最窄子集＝同模組目錄或被 ≥2 個被刪字面值同時命中，其餘列「N 檔未選題」）、被截斷的字面值、
  不可用的反向探針、命中 conftest／輔助檔、被很多測試引用的檔名／路由。
- 被刪除／改名走的舊路徑（`deleted`）：只用在守門組觸發與「引用舊檔名的測試」，**不會**進 pytest；改名的頁面因此仍會選到引用舊檔名的測試。
- T0–T3 必跑；若它們自己的預估就超過預算，輸出與結果 JSON 都標 `over_budget`（`quick_over_budget`），5 分鐘是目標不是保證。
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
- v2 掃描器（h11 審查 S4／S5）：認 f-string、字串相加、AnnAssign 與類別層級常數、走訪常數清單的迴圈變數、`re.findall(字面值, x)` 與 `str.count(x, 字面值)`、split 拆包與 `len(x.split(..))`；
  兩字中文（按鈕文字）與 `-`／`@` 標記字元也算。掃描範圍＝測試根底下所有 `.py`（含 `conftest.py` 與非 `test_` 開頭的輔助檔）。
- v3（h11 複審 S-a）：切出來**綁名稱再取索引／`len`／拆包**、`len(list(re.finditer(..)))`、`sum(1 for _ in re.finditer(..))`、`"尚無%s" % n`／`"尚無{}".format(n)` 的格式字串常數段、
  後面同名常數蓋掉前面無害的那個（同名多次賦值**全部**都測）、bytes 標記都會抓。已知限制：標記從輔助函式的參數進來（`def _n(t, m): t.count(m)`）看不到呼叫端傳的字串（測試釘住這個限制）。
- **沒有逃生口**（h11 F1，PM 裁示）：逃生口曾經是「基線 0、新增就紅，但訊息卻叫作者用它」的死結，現在整個移除——命中就改寫測試；舊的 `# text-anchor-ok` 註解不具任何效力，基線也不再記逃生口。
- **棘輪（`tools/platform/ratchet.py` 三道檢查，兩個寫法守門共用）**：既有檔命中數記在 `text_anchor_baseline.json`，**只准減少**。
  1. 逐檔貼合：基線 > 現場＝有人改乾淨了卻沒重寫基線（空位之後會被補滿）⇒ 紅，要用 `--write-baseline` 重寫（只准往下寫；第一次建立要刪檔重來）。
  2. 基線對照**合併基準上的基線**（`git show <base>:路徑`；改名用 `git diff -M` 對回舊名）：任何一檔變多、新檔、總數變多＝紅。抓不到基準（沒 git／沒主線分支）⇒ pytest `skip`＋原因，**而且 `author_gate --quick` 會把它列進「未跑」**（h11 S-b：不讓 skip 看起來像綠）。
     `MOTRIX_RATCHET_BASE` 只給作者本機演練；環境有 `MOTRIX_TRAIN`（整合閘門）時設了它＝直接紅，作者端設了會印出實際用的基準 sha。真 git 改名（`-M`）與改名同時多一個命中有測試釘住。
  3. 不另存上限常數（上限就是合併基準上的基線；舊的 `BASELINE_TOTAL_CEILING` 已移除）。
- 掃描數 787 → 896（228 → 249 檔）→ 943（265 檔）**不是變差**：是 v2、v3 掃描器更嚴（上述新型態）重新量出來的基線（第一次建立，合併基準上沒有這份檔）；之後只准下降。
- 已知限制（N2）：總數與逐檔數都不變的「同檔換一個錨點」看不出來，靠審查。
- 要改的寫法：用 `data-testid`、結構（AST／正規式抓結構）、行為比對，不用文案當定位。

## 測試寫法守門：讀全域稽核表必須依自己的使用者／request 篩選

- 起因：T86 正式閘門的 `test_quote_put_fail_reason_codes` 用 `SELECT * FROM audit_log WHERE result='fail'` 讀整個庫的失敗列再斷言 `len(rows)==1`，單跑綠、整包跑別的測試的列混進來而紅（`_fail_rows`）。
- 掃描器 `tools/platform/audit_scope_scan.py`（AST）：SQL 敘述開頭（SELECT／WITH／DELETE／UPDATE）、`FROM audit_log`，且 **WHERE 子句**（第一個 WHERE 之後、ORDER BY／GROUP BY／LIMIT 之前）裡沒有自己的範圍條件 ⇒ 命中（h11 F2）：
  沒有 WHERE ⇒ 命中；範圍欄位（username／user_id／actor／request_id／target／entity／…）要和值比較（`= != <> IN LIKE`）才算；水位線 `id >`／`rowid >`／`created_at >`／`ts >` 右邊不能是數字常數（`id > 0` 等於沒篩）；
  只出現在 SELECT 欄位清單或 ORDER BY 的欄位名不算；`"a" + "b"` 拼接的字串會合併後再看。
  守門測試 `test_audit_reads_scoped_to_own_rows_2026_11_14.py`（含 h11 的探針：`SELECT username, result FROM audit_log WHERE result='fail'`、`WHERE id > 0`、`WHERE result=1 ORDER BY target` 都要被抓）；**沒有逃生口**；棘輪同上（基線 `audit_scope_baseline.json`，138 檔／225 處；掃描器變嚴後重新量的第一次基線）。
- quick 選題兩處微調（h11 S-c／S-d）：T2 字面值截斷時，html／js／py 的字面值排在文件（docs／`*.md`）之前，文件另設 30 個上限（被砍的算進截斷、印「未跑」）；
  命中 `conftest.py` 時，所在目錄的 `test_*.py` ≤15 個就全選，否則列「未跑」。
- 已知限制：只認 `audit_log` 表名與 SQL 敘述開頭的字串；動態拼表名、ORM 讀取、別的全域表（例如 failure 表）看不到——要擴就在 `AUDIT_TABLES` 加表名。

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

回放工具同時報三個數字（分母一律含範圍外與未歸因）：**不限預算**、**真實 5 分鐘預算**（歷史秒數／題數×0.75 s／e2e 20 s）、**只算 T0–T3**（不靠可被砍的 T4），
加上分層直方圖、未歸因數與「近似歸因」數。stale 案例的歸因與選題用同一組字面值（循環，h11 S7），所以嚴格歸因（pickaxe／案例明寫 breaker）與近似歸因（pickaxe 找不到時，
用測試檔引用的頁面／js 檔名找最近動過它們的 commit；與 T4 選題同源，**不當確證**）分開報。

### 預估（離線選題，2026-11-14，未真的跑紅）

- 第一輪（7b91a96f8）：17／31＝55%（嚴格歸因）。
- 本輪加入 T4 的「引用檔名／打路由」、e2e 排最後、刪除路徑觸發、`q_unit_cards`／`q_platform_catalog` 等補充組後：嚴格歸因仍是 **17／31＝55%**；
  加上近似歸因後不限預算 **20／31＝65%**、真實預算 **19／31＝61%**（其中 T0–T3 即抓到的 19 個；T4 在真實預算下一個也沒被留下）。**未達 80%**。
- 漏抓的分類與原因（離線天生抓不到的類型）：
  1. **行為改變型過期斷言**（c03909aa6 的 e2e／單元檔約 8 個）：產品行為變了、測試的舊值不是來源字面值，也不是被引用的檔名（頁面走 `page_paths` 間接取得、被 30+ 個測試共用而被視為太通用）。
     離線拿不到「哪個 commit 弄壞它」；要抓只能真的跑那個測試（實測以 breaker 樹實跑 quick 補證）。
  2. **移動行**（`test_module_startup.py`）：字面值從一行移到另一行，diff 同時有刪有增，「新增行重現」規則把它濾掉（N4：之後可加 T2b，字面值在新增行出現位置改變就選）。
  3. **範圍外**（3 個）：bottom_layer 登記是 `pre_train_check` A3 工具檢查（不是 pytest，交給 h4 的整合者一鍵）；`bae0c67e0`、`12e5a7ca8` 離線無法辨識是哪個守門紅。

### 實測（安靜期已解除；進行中）

做法：在每個弄壞的 commit 的樹上真的跑 `--quick`，確認預期測試檔紅；同時補歸因與缺的案例（CHANGELOG／版號／FORM_VERSION）。**實測數字出來前，不報達標。**

## 限制與後續

1. 字面值反查抓不到「行為改變、字面值沒變」的過期斷言——這一類靠 T4（模組自己的測試）與階段測試。
2. 預算估算用 `題數 × 0.75 s`（e2e 每檔 20 s）；`gate_file_seconds.json` 只有 10 個種子檔，實測後應補。
3. quick 專用補充組（`q_boundaries`、`q_e2e_lint`、`q_page_paths`）不改整合者的 `preflight_guards.json`；若整合者之後把 watch 補齊，可從 `QUICK_EXTRA_GROUPS` 拿掉。
4. 整合者一鍵工具（resolve_baselines → train_number → regen → 步驟檔）由 h4 負責，不在本分支。
