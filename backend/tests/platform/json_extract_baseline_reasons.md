# json_extract 基線：增加的理由（棘輪「只准變少」的例外，主持裁示 2026-09-30）

基線檔 `json_extract_baseline.json` 只能放次數（測試逐檔比對），理由寫在這裡；**每一筆增加都要有一行，而且日後降下來時要同一個 commit 刪掉對應的行。**

| 檔案 | 基線 | 增加 | 理由 |
|---|---|---|---|
| `modules/case/api/quotations.py` | 39 → 40 | +1 | `approval_queue_items`（待簽佇列與側欄角標）：200 張待簽、每張 data_json 約 60KB 時，逐筆 `json.loads` 整份 data_json 佔 441／400 ms；改由 SQLite 取 `$.approval`，降到 113／88 ms（W3 approval-freeze，使用者回報簽核卡頓）。 |
| `modules/case/quotations.py` | 5 → 6 | +1 | `case_summary` 的 deal_tag：欄位空時由 SQLite 取 `$.dealTag`，不再把整份 data_json 撈進 Python（同上，待簽佇列的 `_openable` 每次都會呼叫它）。 |

## 為什麼這兩處不會踩到棘輪原本要擋的風險（「壞一筆 JSON 讓整個查詢丟例外、整類資料靜默消失」）

- 兩處都用**巢狀 CASE**：`CASE WHEN json_valid(data_json) THEN CASE WHEN json_type(...)=… THEN json_extract(...) END END`——`json_valid` 為假就**不會執行** `json_type`／`json_extract`，壞 JSON 只會得到 NULL，不會丟例外。
- NULL（壞 JSON、沒有 approval、approval 不是物件、dealTag 不是字串、空字串、NULL）一律**退回舊的 Python 逐筆解析**（L1 `approval_json_of`／`_deal_tag_of`），語意完全不變：壞的那一筆跳過＋ERROR、沒有簽核層照列。
- 守門：`backend/tests/test_approval_no_freeze_2026_09_30.py`
  - `test_queue_provider_fast_path_is_equivalent_to_the_python_parse_for_every_shape`（15 種 approval 形狀，逐筆與舊算法相同）
  - `test_a_bad_json_row_does_not_make_the_whole_class_disappear`
  - `test_case_summary_deal_tag_fast_path_is_equivalent_for_every_shape`（15 種 dealTag 形狀）
  - `test_queue_and_badge_with_200_large_pending_quotations_stay_under_200ms`（200 張×60KB；任一優化被退回都會紅：佇列 220／326 ms）
  - 反向控制：拿掉 fallback／放寬型別判斷，等價題紅。
- 不用 `->`／`->>` 躲棘輪（主持裁示）：它們遇壞 JSON 一樣丟例外，只是計數器看不到——新增的 JSON-SQL 取值點必須留在守門的視線裡。
