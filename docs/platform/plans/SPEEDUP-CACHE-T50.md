# 測試結果快取（依賴雜湊）設計諮詢 — SPEEDUP-CACHE-T50

作者 hichan-1d，2026-10-09，唯讀設計（沒跑任何測試；數字出處標在括號）。與既有 O3（`stage_select` 依 diff＋基準鏈增量）互補：**內容定址**，不需要「基準 commit／鏈長／年齡」，任何樹上跑出的綠都可被別棵樹在「依賴位元組完全相同」時沿用。

## 1. 現況數字
- 非 e2e 9 693 題／3 938 s（65.6 分，-n 2）、e2e 950 題／1 511 s（25 分）；紅燈重跑把整合閘門做到 200 分運算（BUILD-VERIFY-OPTIMIZATION-T47 §1）。
- 948 個非 e2e 測試檔：**598（63%）會開 app**（`client`／`_app`）、162 在 `tests/platform`（序列 28 分，佔非 e2e worker‑秒約 21%）、約 37 讀 git 狀態、約 149 讀現在時間（`git grep` 靜態計數）。
- 現行沿用的指紋＝整棵 tracked tree＋環境（`build_test_reuse.fingerprint`）：任何一個 commit 都讓 66＋25 分全失效；O3 只在「同日、基準已全綠、鏈長≤2」時能增量。

## 2. 設計
**鍵（每個測試檔一把）** `key = sha256(測試檔位元組 ‖ 觀測到的依賴集 {路徑→內容雜湊｜ABSENT｜目錄清單雜湊} ‖ 環境指紋)`。
- 依賴集用**執行期觀測**，不用靜態 import 圖：pytest plugin（同 `fail_stream` 的載入方式）在每個測試檔的收集＋執行期間以 `sys.addaudithook` 記錄 `open`／`import`／`os.listdir|scandir`／`subprocess`（含**打開失敗的路徑**＝ABSENT，之後該檔出現就換鍵），並用 Python 3.12 `sys.monitoring`（PY_START，每個 code object 只觸發一次）記「實際執行到的原始檔」。
- 兩層粒度：**L1 檔層**＝上述觀測集的檔案內容雜湊（簡單、保守）；**L2 區塊層**＝對「執行到的 .py」改用 testmon 式的函式區塊雜湊（`ast.dump` 的 FunctionDef ＋ 模組頂層殘餘），函式本體改了才失效。
- 公共成分（每把鍵都含）：`conftest.py` 鏈、`pytest.ini`、`requirements*`、Python／pip freeze／playwright（沿用 `current_env()`）、`MOTRIX_*` 環境（沿用 `_ENV_IGNORE`）；**開 app 的測試另含「模板庫輸入」**＝`db.py`＋`core/`＋所有 `migrations*/`（schema 變了就全失效，這是對的）。
- 不可快取（永遠實跑）：觸發 `subprocess git`／讀 `.git` 的（約 37 檔：changelog_follows_code、cache_index_fresh、generated_maps…）、e2e（瀏覽器、port、計時）。讀現在時間的（約 149 檔）鍵加「本地日期」＝最多沿用到當天。
- 只存**整檔全綠**（含登記偶發重試後綠）；紅不存、不沿用；順序相依題（既有偶發）所在檔標 `order_sensitive` 不快取。

**存放** 機器本機、不進 git：`D:\MOTRIX-TESTCACHE\v1\<key前2碼>\<key>.json`＋一個 sqlite 索引；內容 `{file, nodeids{id:outcome,sec}, deps[{path,sha}], env_fp, tree_sha, run_id, created_at, stage, worker_mode}`；原子寫入（tmp＋rename）；保留 14 天／5 GB LRU。多個 worktree 共用同一個目錄。

**怎麼用在流程裡（不破壞「最終驗證在凍結樹上」）**
- 命中判定**永遠在當下這棵樹上重算**：讀 entry 的 deps，逐一對當下檔案算雜湊，全等才算命中；因此「綠的證據」只對「與當下位元組相同的依賴」成立，與它是在哪個分支、哪個 commit 產生無關。
- wip 分支跑的結果寫入快取；整合樹（`pre_train_check`、列車整合閘門）命中同一批檔不重跑 ⇒ 解決「分支全量＋整合全量重複」（O4 的大戶 #4）。
- **凍結樹（發布候選）**：同一套機制，但（a）manifest 逐檔記 `cache_hit{run_id, tree_sha, created_at}`，審查者看得到證據來源；（b）命中檔仍抽樣實跑 ≥10%（分層：每個模組至少 1 檔、所有依賴集含「本班 diff 的鄰居」的檔）；（c）未命中＝實跑，所以「凍結樹上每一題要嘛當下實跑、要嘛有位元組相同依賴的綠證據」；（d）**每 3 班或每週一次完整冷跑**（關快取）做對照。這是對 §「最終驗證」的一個**弱化**，採用前要使用者書面裁示（同 O3）。

## 3. 預期節省（誠實版；步驟 1 會用實測取代下面的估計）
- **L1** 命中的主要是：不開 app 的單元檔（約 350 檔）、不讀產生檔的 `tests/platform` 守門（每班取號會重產 `test_map／dep_graph／UNIT-INDEX`，讀它們的守門每班必 miss）。估 **非 e2e 省 8～15%（5～10 分）**。
- **L2** 才碰得到大宗（598 個開 app 的檔）：只改函式本體的班，命中率可到 60～80% ⇒ 省 **30～45 分**；但**頂層殘餘變動（新增 import、常數）會使所有「執行過該檔頂層」的測試失效**——第 49 班 strict‑bool 在 15 個端點檔各加一行 import，L2 下幾乎等於全 miss。硬底層（`helpers/`、`core/`、`conftest`）一動，開 app 的檔全 miss（與 `stage_select` 的硬底層規則一致）。
- 疊加紅燈重跑：第二輪起只重跑「紅檔＋被改到的檔」，把 §1.2 的 110 分浪費壓到約 15 分（與 O3 同效，但不需基準鏈）。
- 結論：L1 單獨不夠達標；L2 在「函式級改動」的班有效，在「橫切 import 改動」的班等於零。

## 4. 假綠風險與對策
| 風險 | 對策 |
|---|---|
| 動態 import／registry（`importlib.import_module("…0005…")`、provider 註冊） | 觀測式依賴集（不靠靜態圖）；模組頂層在 import 時執行 ⇒ 計入該檔頂層殘餘 |
| 模板／靜態檔／文件被測試讀取（`docs/`、`frontend/`、`.gitattributes`） | `open` 稽核事件＋目錄清單雜湊＋ABSENT 記錄；子目錄掃描記清單 |
| DB schema／模板庫 | 公共成分含 migrations 全集；`_template_db` 輸入進鍵 |
| 環境／時間／隨機／網路 | 環境指紋沿用；讀時間檔鍵含日期；用 port／外部網路的標 uncacheable；同日 12 小時窗（沿用 `MAX_HOURS`） |
| git 狀態、工作樹是否乾淨 | 偵測 `subprocess git` ⇒ 永不快取 |
| 檔間共享狀態／順序相依 | 只存整檔綠；`order_sensitive` 名單不快取；快取以檔為單位，不跨檔拆題 |
| 觀測漏記（C 擴充、`mmap`、子行程內讀檔） | 子行程的依賴集合併（`subprocess` 事件＋環境傳遞 plugin）；抽樣實跑＋週期冷跑兜底 |
| 快取被污染／改壞 | entry 內含自身雜湊；讀取時驗證；任一次抽樣分歧 ⇒ 整個快取隔離並自動關閉 |

**突變檢查（上線前必過）** ①鍵靈敏度：對隨機 N 檔，逐一對每個記錄的依賴做「改一個位元組／刪除／新增同名檔」，鍵必須變（單元題）；②行為突變：對命中檔的依賴原始碼套已知突變（翻轉常數、刪一行），快取必須 miss 且該題實跑變紅；③對照：同樹冷跑 vs 全命中跑，結果逐題相同（含 outcome 與 skipped 數）。**週期對照**：每週冷跑一次完整閘門並比對快取預測；分歧＝事故。

## 5. 上線五步
1. **影子錄製**（零風險）：plugin 只錄依賴集與「若啟用會命中幾檔」，掛在現有閘門上跑 2 班；產出真實命中率、觀測成本（目標開銷 <3%）、哪些檔 uncacheable。
2. **正確性證明**：鍵靈敏度單元題＋行為突變＋冷跑/全命中逐題對照；影子期間每個「會命中」的檔都實跑，統計分歧＝0。
3. **作者分支與 `pre_train_check` 啟用 L1**（非發布路徑），保留 10% 抽樣；e2e 與 uncacheable 不動。
4. **整合閘門啟用 L1＋L2**，manifest 記 `cache_hit` 證據；發布候選仍全實跑一次（維持現行規則）直到使用者書面核准「發布候選可沿用」。
5. **使用者裁示後**才開凍結樹沿用（附 ≥10% 抽樣＋每 3 班冷跑＋自動關閉開關 `MOTRIX_TESTCACHE=0`）；與 O3 擇一或合併（O3 提供選題、本快取提供證據與跨樹沿用）。
