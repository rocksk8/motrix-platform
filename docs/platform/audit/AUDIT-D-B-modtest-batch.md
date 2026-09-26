# 稽核：B 的 modtest 分批結果彙總＋e2e 判定不看檔名（wip/b-modtest-batch f0fe645e）（D，2026-09-26 23:38）

> 標準等級，第十二班車頭，第十班差異題假綠的修正。稽核者 D 沒有寫過任何受稽核的程式碼。

## 0. 結論

- **必修 1**。基準：modtest_batches＋e2e_classification＋env_and_load_guards 60 過。

## 1. 主持三點

| # | D 的驗證 | 結果 |
|---|---|---|
| 任一批紅、沒有結果、選到的檔沒有結果 ⇒ 總結果紅 | 讀 `merge_batches`：非 0／5 的 exit 優先；某批沒有摘要行或讀不到 junit ⇒ 紅；`files_without_results` 對每個選到的 .py 檢查 junit 裡有沒有結果；帶 `-k／-m／--deselect…` 時才略過覆蓋檢查並印出說明。突變 MB1「總結果只取最後一批」、MB2「沒有摘要不判紅」、MB3「沒有結果的檔不判紅」⇒ 3/3 紅 | 成立 |
| 最後一行是合計 | 讀碼：`run_pytest` 最後印 `== N passed, M failed … in Xs（K 批合計；exit E）==`，而且放在回傳文字最後，`parse_summary` 讀到的就是總數 | 成立 |
| e2e 判定＋執行期檢查「用瀏覽器的題必有 e2e marker」，沙盒題：用了 playwright 而沒有 marker 要紅 | 用 B 自己的 collect-only 探針（`_collect`／`_unmarked_browser`），沙盒 4 種寫法都沒有 marker | **只抓到 1／4** ⇒ MB-M1 |

## 2. 發現

**MB-M1（必修）　「用了 playwright 而沒有 e2e marker」只抓得到一種寫法**

| 沙盒檔（都沒有 marker） | 執行期探針 | `test_map.file_is_e2e` |
|---|---|---|
| `from playwright.sync_api import sync_playwright` | 抓到 | e2e |
| `import playwright.sync_api` | **漏** | e2e |
| `pw = pytest.importorskip("playwright.sync_api")`（repo 的常見寫法） | **漏** | **非 e2e** |
| 函式內 `from playwright.sync_api import …` | **漏** | e2e |

- 原因：
  - 探針用「模組全域變數的 `__module__` 以 playwright 開頭」判斷。module 物件沒有 `__module__`，函式內的 import 也不在全域變數裡。
  - `file_is_e2e` 只看 import 陳述式，沒有看 `importorskip("playwright…")` 這個呼叫。
- 後果：這類題在全量會落在非 e2e 那一段（`-n 4`、沒有逐題死線），modtest 的 worker 上限也不會套用 e2e 的 2，正是這包要修的那一類。
- 修法：
  - 探針改看原始碼 AST：任何 `import playwright…`、`from playwright…`、`importorskip("playwright…")`，不分模組層或函式內，都算用了瀏覽器。
  - `file_is_e2e` 也認得 `importorskip("playwright…")`。
  - 反向控制把上表四種寫法都放進去。
