# 抽查（輕量）：B 的瀏覽器 fixture 一律經 new_context（wip/b-newctx-rule ca1b84b6；疊在 b-modtest-batch-2 上）（D，2026-09-27 00:25）

> 規則：conftest 裡 `new_context` 以外的 fixture 呼叫 `sync_playwright` ⇒ 紅，由 D 在 MB-M1 提出的射程限制延伸而來。規則已寫進 MODULE-GUIDE §7 與守門 docstring。

| 項目 | 結果 |
|---|---|
| 反向控制有沒有涵蓋主持點名的三種寫法 | `test_a_fixture_starting_its_own_playwright_is_caught`：直接呼叫（`direct`）、經同檔 helper（`via_helper`）、屬性寫法 `playwright.sync_api.sync_playwright()`（`via_attr`）⇒ 三種都列出；依賴 new_context 的 fixture、非 fixture 的 helper、new_context 本身 ⇒ 不列。**成立** |
| 正對照 | 把真正的 `new_context` 改名後掃描，確實會被列出，所以量尺量得到東西 |
| 突變 NC1「不認 sync_playwright」 | 紅（2 題） |
| D 追加沙盒 | `import playwright.sync_api as pa; pa.sync_playwright()` ⇒ 抓到；`from playwright.sync_api import sync_playwright as sp; sp()` ⇒ **漏**；`async_playwright()` ⇒ **漏** |

- **建議 NC-S1**（依主持約定，同類繞過列建議）：函式名稱比對改成「從 import 綁定反查」，讓別名也算；另外把 `async_playwright` 加進去。

⇒ 通過、必修 0。

## 複核：wip/b-newctx-rule-2 d28c7c1d（NC-S1；D 00:35）

- D 用 `fixtures_starting_playwright` 直接測沙盒：
  - `sync_playwright as sp` ⇒ 抓到
  - `async_playwright`（async fixture）⇒ 抓到
  - `async_playwright as ap` ⇒ 抓到
  - 經同檔 helper 的別名 ⇒ 抓到
  - 模組別名 `pa.sync_playwright()` ⇒ 抓到
  - **來源不是 playwright** 的同名別名 ⇒ 不列（正確）
- 本檔 8 過。突變 NC2「不認別名」⇒ 紅。
⇒ **NC-S1 關閉（d28c7c1d）**。
