# e2e「測試執行緒睡覺時，頁面請求被卡住」風險清單（唯讀 grep 盤點；2026-10-02，d7）

**結論先行**：已證實 1 個實例（`test_e2e_material_approval`，已修 8fad1538）。全 repo 248 個用 Playwright 的測試檔裡，`time.sleep(` 出現在 18 個檔、27 處（不含 conftest／helper）；
真正有同型風險（**點了頁面 → 睡著輪詢資料庫／API 等頁面送出的請求生效**）的只有 **5 處／4 個檔**（H1×2、H2、H3、H4），不是「普遍原因」。
先前兩個偶發（派發按鈕 detached、地圖彈窗）**不是這個類型**：兩支都只用 Playwright 的等待（`wait_for_function`／`wait_for_selector`／`wait_for_timeout`），沒有 `time.sleep` 或睡覺輪詢 ⇒ 成因另有（Alpine 重繪競態、彈窗時序），不要併案。

## 已證實的機制（證據）
- 現象：頁面自動存檔的 `PATCH` 在頁面上 5.2 秒發出（fetch 包裝記錄 `start`，永不回應），**伺服器存取紀錄約 51 秒後才出現**，時間點＝測試執行緒下一次呼叫 Playwright；同時被卡的還有後面 3 個 `edit-presence`。伺服器執行緒傾印（+6 s／+18 s）無任何後端 frame ＝伺服器閒置，不是伺服器慢。
- 修法驗證：把輪詢的 `time.sleep(0.4)` 換成 `page.wait_for_timeout(400)` ⇒ 12/12 綠（修前 3/8、6/10、2/3 紅），斷言一字未改。
- **尚未釐清的機制細節（開放問題 Q1）**：`conftest._BROWSER_EXTERNAL_URL` 用正則（註解：「正則在 Playwright 的 node 端比對，本機請求根本不會送到 Python」）——照這個說法本機請求不該被 Python 端卡住。但現象顯示「測試執行緒不進 Playwright API 時，頁面請求不被送出」。可能原因：(a) 目前 Playwright 版本的 route 比對（含正則）在 Python 端做；(b) sync API 的 greenlet 分派／節流別的路徑。**待做（需要獨佔窗口，約 10 分鐘）**：在原版（`time.sleep` 輪詢）測試上，(1) 關掉 `_new_page`／`_new_context` 的 route 掛載、(2) 不關但改 `wait_for_timeout`，各跑 10 次，看紅燈率——把「是 route 還是 sync 分派」釘死，結論決定是否值得加全域守門。

## 風險排序（以「睡著時，頁面是否有請求在途」為準）

### 高（同型：點了之後 `time.sleep` 輪詢 DB 等頁面請求的結果）
| # | 位置 | 模式 | 說明 |
|---|---|---|---|
| H1 | `tests/test_e2e_quote_number_input_2026_09_24.py:114`、`:185` | `click(儲存草稿)` → `for _ in range(100): if _saved_*()… ; time.sleep(0.1)` | 輪詢 `_saved_item()`／`_saved_data()`（DB）等「儲存草稿」的 PATCH/PUT 落地；睡著期間請求若被卡，100×0.1＝10 秒內可能等不到 |
| H2 | `modules/arap/tests/test_e2e_cashier_receive_amount_2026_09_24.py:89` | `confirm.click()` → 輪詢 `_item().get("received")` | 同上（等收款 POST） |
| H3 | `modules/arap/tests/test_e2e_cashier_remit_payslip_link_2026_09_30.py:85` | `confirm.click()` → 輪詢 `_state()[0] == 1`（DB） | 同上；**同檔 :77 的迴圈裡有 Playwright 呼叫（`is_visible()`／`is_enabled()`）⇒ 安全** |
| H4 | `tests/test_case_close_checklist_2026_09_24.py:191` | `btn.click()` → 輪詢 `_deal_tag() == "已結案"`（DB） | 同上（等結案 PATCH） |

### 中（點了之後固定 `time.sleep(1.0～2.0)`，其後斷言 DB／對話框）
- `tests/test_e2e_quote_number_input_2026_09_24.py:103`、`:175`：`click(儲存草稿)` → `sleep(1.0)` → 斷言 `dialogs`（JS 同步產生，安全）與「**標紅時沒有存進 DB**」（負向斷言：請求若被卡住反而『假綠』——該存的沒存也過）。
- `tests/test_e2e_case_data_loss_2026_09_24.py:162`：`sleep(2.0)` 後斷言「沒存」（負向；同上，被卡住會假綠，**比紅燈更該注意**）。

### 低（不依賴在途請求）
- 時間戳間隔（為了讓「已讀時間」嚴格晚於動態時間）：`case_color_semantics:91`、`case_list_quick_filters:86`、`case_mark_all_read:44,59`、`case_mark_one_read_count:44,61`、`unread_marks_clear_on_click:62,288`、`crm_unread_marks:62,267`（睡的當下沒有在途請求）。
- `time.sleep` 在 route handler 內（刻意製造回應延遲）：`case_health_overview:122`、`case_list_paging:107`、`case_select_late_response:57`、`case_select_stale_subloads:91`。這些會讓 sync 分派被卡住是**設計意圖**（見 conftest:1436 的註解），已被 `W-4` 突變守住，不改。
- 迴圈內含 Playwright 呼叫 ⇒ 安全：`quote_preview_server_layout:63`（`evaluate`）、`cashier_remit_payslip_link:77`。
- 無頁面相依：`test_e2e_expense_chain_a2:60`（`_wait(pred)`，pred 只查 DB，等的是 API 呼叫的結果；API 由 Playwright `APIRequestContext` 在呼叫當下完成）。
- 基礎設施：`conftest.py:1086`（測試鎖等待）、`:1892`／`:1908`（啟動 uvicorn）。

## 建議
1. **H1～H4 改成 `page.wait_for_timeout(100)`**（或把等待改成對頁面可見終點的 `wait_for_function`／`expect_response`），不動任何斷言；每檔單獨連跑 5 次（改前改後各一）。
2. **中風險的負向斷言**（`標紅時沒有存`、`沒存`）改成「先等『儲存請求已回應或明確沒送』的終點」再斷言（例如 `page.expect_response` 的 timeout 反證、或讀頁面 `saveStatus`），否則被卡住時這些題會**假綠**。
3. 加一條靜態守門題（待 Q1 結論決定是否做）：e2e 測試檔裡「`for/while` 迴圈體內有 `time.sleep(` 且迴圈體內沒有任何 `page.`／`expect(`／`locator(` 呼叫」⇒ 紅，除非行尾有 `# sleep-ok: <理由>`；反向控制＝對 H1～H4 原文跑掃描器必須命中。
4. 本清單只用 grep 盤點（沒有跑任何測試）；有效的程式碼參照以 d7 的 worktree `bopt2-0248` 為準（內容同 platform fc5f4080 之前的 e2e）。
