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

## 3. MB-M1 複核：wip/b-modtest-batch-2 f3be5cd2（D 23:56）

- 修法：`playwright_refs` 看原始碼 AST（import、from-import、importorskip、import_module／`__import__`，任何層級）；`playwright_functions` 以「題」為粒度，經同檔 helper 與 fixture 遞移；`file_is_e2e` 用同一套判斷。基準 10 過。
- D 用 B 的 collect-only 探針重跑沙盒，每題本體都真的用到 playwright：

| 寫法（都沒有 marker） | 執行期守門 | `file_is_e2e` |
|---|---|---|
| from-import | 抓到 | e2e |
| `import playwright.sync_api` | 抓到 | e2e |
| 模組層 `importorskip` | 抓到 | e2e |
| 函式內 import | 抓到 | e2e |
| 經同檔 helper 的 `import_module` | 抓到 | e2e |
| 只在模組層 import、題目本身沒用到 | 不列（依設計：純單元題） | e2e（保守方向） |

- 突變 MB4「不認 importorskip」、MB5「不做同檔 helper 遞移」⇒ 都紅（`test_every_way_of_using_playwright_without_a_marker_is_caught`）。
- **主持的問題：playwright 藏在跨檔 fixture（conftest）時，會不會被判成非 e2e？**
  - 執行期守門：conftest 裡碰到 playwright 的 fixture 有 `_browser_netguard`、`new_context`、`e2e_browser`、`new_page`。後兩者依賴 `new_context`，pytest 的 fixturenames 會展開依賴，所以「用 `new_page` 而沒有 marker」一樣會紅。**目前沒有漏洞。**
  - 靜態 `file_is_e2e`：夾具清單沒有 `new_page`；只用 `new_page` 的沙盒檔判成非 e2e。但真實 repo 用瀏覽器夾具的檔**全部 0 個判錯**，因為都另外用了 live_server 或 e2e_browser。而且執行期守門會要求這種題帶 marker，一帶 marker 靜態也就判成 e2e，兩道合起來是閉環。
  - **射程限制（寫進說明即可）**：日後在 conftest 新增一個直接呼叫 `sync_playwright`、而**不依賴 `new_context`** 的 fixture，執行期守門（依名稱 `_BROWSER_FIXTURES`）認不得。建議把 `_BROWSER_FIXTURES` 改由 conftest 的 `playwright_functions` 算出來，或者要求 conftest 的瀏覽器 fixture 一律經 `new_context`。

⇒ **MB-M1 關閉（f3be5cd2）**。
