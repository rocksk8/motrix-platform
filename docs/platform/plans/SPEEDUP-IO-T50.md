# 測試／閘門加速：時間花在哪、I/O、計時題（第 50 班設計諮詢，唯讀）

作者：b5。只用既有資料（`fail_stream` 結束紀錄 187 筆、`preflight_seconds.json` 921 檔、`PLAN-TEST-PERF.md`、`conftest.py`）＋兩個 2 秒內的微量測；沒有跑任何測試。「估計」標註者是推算，落地前要用 §5 的量測證實。

## 1. 時間花在哪（a）
官方 not_e2e（2026-10-09 兩次綠燈）：9,912 題、2,298～2,326 秒；以 -n 4 計約 9,300 worker-秒。最慢 20 檔合計 2,121 worker-秒（23%）；921 檔中位數 3.1 秒、p90 17.7 秒；≥10 秒的 180 檔占 69%、≥30 秒的 41 檔占 36%——**不是少數慢題，而是「每題固定成本 × 題數」加上一批閘門型大檔**。

| 類別 | 代表檔（worker-秒／題數） | 主因 |
|---|---|---|
| 閘門／工具型（子行程＋掃整個 repo） | module_update_delivery 207／45、ledger_mutation_guards 148／8、author_gate 115／23、scope_gate 98／103、changelog_follows_code 98／18、stage_select 91、modtest_rebase_check 89、stepfile_drill 87、generated_maps 77、upgrade_drill 76、module_boundaries 73 | 每題 spawn git／python 子行程、反覆走訪同一棵檔案樹；scope_gate 103 題 ≈ 1 秒／題都在重掃 repo |
| 角色矩陣／API 型 | finance_role_matrix_ext 183／77（2.4 秒／題）、dashboard_finance_cards_access 141／31、bonus_correction 113／23、bonus_case_api 112／25、quote_json_lost_update 85／43、custom_modules_engine 91／58 | **`make_user`＋登入的 PBKDF2**（見下）＋每題一個 TestClient |
| e2e | 10 檔共 87 秒（preflight 量到的非 e2e 子集）；e2e 段本身另計 | 瀏覽器啟動、頁面載入、固定等待 |

**最大單一熱點（本次新發現）：密碼雜湊。** `helpers/auth.py` 用 PBKDF2-SHA256 **260,000 次**；本機實測 **210 ms／次**（1,000 次僅 0.76 ms，差 276 倍）。`make_user` 每個帳號雜湊一次、每次登入驗證再算一次；測試碼有 2,316 處 `make_user(`、661 處 `/api/auth/login`（靜態呼叫點，執行次數更多）。矩陣型檔「題數少卻 2～3 秒／題」正好吻合。**估計**：整輪約 4,000 次雜湊＋4,000 次驗證 ≈ 1,700 worker-秒（≈18%，-n 4 約 7 分鐘牆鐘）。

## 2. 範本庫與暫存 I/O（b）
- **每 worker 一份範本庫已經存在**：`conftest.py::_template_db`（session 範圍＝每個 xdist worker 一份，用真正的 `db.init_db` 建一次、WAL 併回）；`client` 每題 `shutil.copyfile`，demo 庫用到才複製（lazy）。實測複製 1.19 MB ≈ **3.1 ms**，9,912 題 ≈ 30 秒（占 <1.5%）。建範本 ≈ 0.2～0.5 秒 × worker 數。⇒ **沒有「再做一份範本」的空間，只剩下面的暫存清理。**
- 每題 `tmp_path`（含庫檔 1.25 MB＋WAL／shm）要到整輪結束才刪：約 12 GB 的建檔／刪檔流量、數萬個小檔，Defender 即時掃描會加成（2026-09-15 有 MsMpEng 失控前科）。**提案**：測試通過就在 teardown 立刻刪該題 `tmp_path`（失敗保留），峰值磁碟 ≈ 0；並請使用者決定是否把 `%TEMP%\pt_*`、`.venv312` 加入 Defender 排除（安全取捨，需裁示）。估計 −60～200 秒（取決於 MsMpEng 佔用，**需在閘門中取樣 CPU 證實**）。
- **RAM 碟不建議**：節省的只有那 ~30 秒複製＋小檔寫入（≤60 秒），卻吃掉目前已 70～80% 的記憶體。C: 剩 386 GB、D: 910 GB，磁碟空間無壓力。

## 3. 計時門檻題（c）——負載下假紅
| 檔:行 | 門檻 |
|---|---|
| `test_approval_no_freeze_2026_09_30.py:289` | queue／count < **200 ms**（第 49 班因負載 437 ms 紅；:127 另有 < 1.0 s） |
| `test_audit_search_2026_09_30.py:320/323/326` | 0.3 s（5 次取最快）／0.5 s／0.3 s——**最緊** |
| `test_geocode_warm_async_2026_09_28.py:54/176/262` | 1.0 s、區塊死線、import main 不得 ≥ 預熱秒數 |
| `test_archive_schedule_async_2026_09_28.py:177`、`modules/tender_radar/tests/test_tender_notify_2026_09_21.py:1081` | import main 不得被排程／抓取拖慢 |
| `test_case_change_approve_deadlock_2026_09_15.py:79/161` | < 5 s（防卡死） |
| `test_e2e_hard_cap_2026_09_25.py:98`、`test_e2e_inflight_report_2026_09_26.py:286` | < 40 s／< 20 s（死線機制） |
**隔離設計（不降低門檻、不弱化閘門）**：新增 marker `timing`（登記在 pytest.ini），閘門改成兩段——平行段 `-m "not timing" -n N`，之後**單程序、機器上沒有其他工作時**跑 `-m timing`（≈15 題，< 60 秒）。選項 B（較弱，不建議當預設）：每題先量一次空轉基準再等比放寬。價值：每次假紅的 failfast 重跑 25～60 分鐘（主持實測）。

## 4. worker 數與 e2e 為何要序列（d）
- 6 實體核／12 執行緒；負載是 CPU 密集（PBKDF2、SQLite、子行程），超執行緒對這種負載只加 10～20%，且 worker 越多計時題越抖。**建議非 e2e 用 `-n 6`（= 實體核）**，記憶體每 worker ≈ 0.5～1 GB（目前 RAM 已 70～80%，先看 §5 的取樣再決定）；若現行為 -n 4，估計牆鐘 −20～25%（−450～550 秒）。LPT 排序種子（`gate_file_seconds.json` 只有 10 檔、2026-09 舊值）應改吃最新 `slowest_files`，最大單檔 207 秒遠小於總長，不會卡關鍵路徑。
- e2e 必須序列（或極低並行）：共用 uvicorn 伺服器在**同一行程**內讀 monkeypatch 過的 `db.DB_PATH`，背景執行緒（結案 PDF 等）會寫到「當下」的庫；Edge PDF／Chromium 與測試搶同一批核心，固定等待與逾時死線對負載敏感；`PLAN-TEST-PERF` §3.2 的 `-n 4` 實驗在負載下時序題就紅。

## 5. 排序後的改動清單
| # | 改動 | 估計省（牆鐘，-n 4） | 風險 |
|---|---|---|---|
| 1 | 測試環境 PBKDF2 次數降到 1,000（產品碼只加一個可測試覆寫的常數；保留 1 題真實 260k 的格式／相容題） | **−300～450 秒**（估計；先用計數包裝器量實際雜湊次數） | 釘死雜湊格式或固定 hash 的題要排除；不影響認證邏輯覆蓋 |
| 2 | `timing` 題隔離成安靜序列段 | −0（+≤60 秒序列），**避免 25～60 分鐘假紅重跑** | 需改建包腳本兩段式；題數少 |
| 3 | 閘門型大檔 session 內快取 repo 走訪／git 結果（scope_gate、changelog_follows_code、generated_maps、module_boundaries…） | −60～120 秒（估計） | 快取要以 HEAD 為鍵，守門自身的突變題要能清快取 |
| 4 | `-n 6`（若目前 4）＋以最新 `slowest_files` 重種 LPT | −450～550 秒 | 記憶體、與 #2 並用 |
| 5 | 通過即刪 `tmp_path`＋（裁示後）Defender 排除 | −60～200 秒（需量） | Defender 排除是安全取捨 |
| 6 | RAM 碟 | ≤ −60 秒 | 吃記憶體，**不建議** |
**先量再做（一次，機器空閒時）**：①計數包裝器統計 `_hash_pw`／驗證實際次數；②閘門期間每 5 秒取樣 python／MsMpEng／msedge 的 CPU 與記憶體；③`--durations=50` 區分 setup／call／teardown。
