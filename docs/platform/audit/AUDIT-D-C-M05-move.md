# 稽核：C 的 M05 應收應付搬進 modules/arap（wip/c-m05b b17e5296；合回前）（D 稽核，2026-09-26）

> 依 PLAYBOOK §B、§E、CORE-SPEC §9d：模組搬遷，完整稽核。稽核者 D 沒有寫過任何受稽核的程式碼。
> 對象：`c46647c8..b17e5296`（4 commits，疊在 c-tax-calc-2 上）：搬遷＋`helpers/receivables.py` 改 L1 薄殼（CORE 1.36）、IP-98／99（暫編號）、案件頁／報表頁／出納頁的「M05 不在」提示、銀行對帳自 M08 收回。
> 稽核樹 `D:\MOTRIX-PLATFORM-D`（基準、突變）、`D:\MOTRIX-PLATFORM-D2`（§B-11），Python `D:\MOTRIX-PLATFORM\.venv312`；非 e2e `-n 4`、e2e `-n 2`。

## 0. 結論

- **必修 2、建議 1、觀察 3**。
- 搬遷本體、IP-98／99、三個頁面的提示、§B-11 都成立；突變 7 項皆紅。
- 必修的兩項：薄殼沒有到期觸發（M5-M1）；新 e2e 題沒有關閉 browser context，會讓同一個 worker 的下一題偶發紅（M5-M2）。

## 1. 實測

| 項目 | 結果 |
|---|---|
| 題目盤點（`def test_*` 名稱計數，base → tip） | 4200 → 4215，**沒有任何一題消失**（拆檔、搬檔都有對應） |
| 基準：tests/platform＋arap 非 e2e＋本包改到的 25 檔 | 1350 過、2 紅：`test_every_module_page_is_declared_in_sidebar`（已知，等 C4）、`test_test_map_json_is_current`（O-1） |
| 基準：本包改到的 11 個 e2e 檔 | 18 過、1 紅：`test_case_page_behaviour_matches_golden`，錯誤是 `Browser.new_context: Response has been disposed`；單獨重跑通過 ⇒ 根因見 M5-M2 |
| §B-11（D2 樹刪 `backend/modules/arap`；tests/platform＋提到 arap／其路由／表的 50 檔） | 非 e2e：1434 過、25 skip、**5 紅＝允許 2＋產生檔 3**（dep_graph、test_map、歸屬）；e2e：18 過、4 skip；不帶旗標的 `--collect-only`：1486 題、無收集錯誤 |
| §B-11 端點（superadmin） | ping 200；`/api/cashier/receivable-queue`、`/api/invoice-vouchers`、`/api/payment-requests` 404；現金口徑報表 200，`incomeNotice`＝RECEIVABLES_MISSING；tax-export 404 並附說明；`POST /api/reports/bank-reconcile` 405（前端已處理） |
| IP 編號 | origin 用到 IP-17；各 wip 分支之間 98／99 不撞號；本文與題目都寫明「暫編號，列車定號」 |

## 2. 突變（D 自做，替換前 assert 恰好 1 處）

| # | 突變 | 結果 |
|---|---|---|
| MB1 | M08 `income_notice` 恆為空字串 | 紅（`test_reports_without_m05`） |
| MB2 | M08 稅務匯出在 M05 不在時回空表 | 紅（同上） |
| MB3 | L1 殼 `collect_tax_invoices` 在 M05 不在時回 `[]` | 紅（`test_shim_when_m05_is_absent`） |
| MB4 | T100 預覽不列「不含收款事件」 | 紅（`test_t100_preview_without_m05`） |
| MB5 | 報表快照 `payableKnown` 不看 `payableSnapMissing` | 紅（2 題 e2e） |
| MB6 | 案件頁兩處 404 都不設 `arapMissing` | 紅（`test_case_page_says_arap_is_missing...`） |
| MB7 | 出納頁銀行對帳忽略伺服器帶的說明 | 紅（`test_detail_from_the_endpoint...`） |
| MB8 | `CORE_VERSION` 升到 `"2.0"`，薄殼仍在 | **存活** ⇒ M5-M1 |

- MB6、MB7 的紅燈清單都另外多出 `test_reports_snapshot_shows_the_payable_queues_own_reason`，而這兩個突變跟它無關；實際是 M5-M2 的偶發紅。判定只看各自對應的題。

## 3. 發現

### 必修

**M5-M1　L1 薄殼寫著「下一個主版號刪除」，但沒有任何東西會在那時觸發**
- core/CHANGELOG 1.36、ROADMAP、IP-98／99、殼的 docstring 都寫「下一個主版號刪除」。但 `core_bump.py` 沒有淘汰清單，`test_receivables_shim` 也不看 CORE 版號。
- MB8：把 `CORE_VERSION` 改成 `"2.0"`，守門照綠。
- 後果：升主版號那天沒有任何題會紅，殼會一直留著；新程式照樣可以 import 它，「淘汰中」變成永久介面。這和「計數器要有落點」是同一個問題：從來不觸發，跟運作正常長得一樣。
- 建議修法：在 `test_receivables_shim` 加一題：讀 `registry.CORE_VERSION`，主版號大於等於 2 時，`helpers/receivables.py` 必須不存在，或者至少不能再有這 4 個名稱。修好後 MB8 要轉紅。如果要做成通用的淘汰清單，交主持裁示；本包只需要這一個到期點。

**M5-M2　`test_e2e_arap_absent_notices` 的 context 從不關閉 ⇒ 同一個 worker 的下一題偶發紅**
- 4 題都是 `e2e_browser.new_context().new_page()`，沒有一題關閉 context。其中 `test_reports_page_says_income_and_cashier_queues_are_missing` 用了 `route.fetch()`。
- 題目結束時頁面還開著、仍在發請求。那個 context 的請求被丟棄後，錯誤會浮到同一個 worker 的下一次 Playwright 呼叫：
  - `TargetClosedError: BrowserContext.route: "Route.fetch: Request context disposed."`
  - 錯誤請求是 `GET /api/reports/expenses-monthly…`，referer 是 reports.html。
- 發生次數：未突變的程式碼 3 次重跑紅 1 次；MB6、MB7 各紅 1 次；基準裡的 golden `Response has been disposed` 也是同一個 worker 的下一題。
- 這是觀測裝置本身的缺陷（〈探針與被測對象糾纏〉）：失敗訊息指向別的題，全量或列車會偶發紅，查的人會被帶去找不存在的產品缺陷。
- 建議修法：每題用 `ctx = e2e_browser.new_context()`，`try/finally` 裡 `ctx.close()`；有 `route.fetch` 的那題，關閉前先 `page.unroute_all(behavior="ignoreErrors")`，或者等頁面閒置。修完後 D 會連跑 5 次驗證。

### 建議

**M5-S1　報表頁先載過出納資料時，財務快照會略過 404 處理，畫成 NT$ 0**
- `_loadPayableSnapshot` 開頭是 `if (this.payableSnapLoaded || this.cashierLoaded) return`。
- `showCashierTab()` 裡的 `loadPayable`／`loadReceivable` 遇到 404 時什麼都不做，最後仍然設 `cashierLoaded = true`。
- 路徑：`reports.html?tab=cashier`（init 保留的舊深連結）→ M05 不在 → 切到圖表頁。快照直接 return，`payableSnapMissing` 是空字串，`payableKnown` 為 true，應收、應付、淨部位都顯示 NT$ 0。
- 可達性低：sidebar 已改連 cashier.html，repo 內沒有產生這個連結的地方，只剩舊書籤。這是 D 讀程式碼得出的結論，沒有做 e2e 實證。
- 建議：`loadPayable`／`loadReceivable` 遇到 404 時一併設 `payableSnapMissing`，或者移除 reports.js 裡已退役的出納頁籤程式碼。

### 觀察

- **O-1**　test_map.json 過期（tip 上 `--check` 不一致），交列車重產。
- **O-2**　同一句「應收應付模組未安裝」有兩個不同文字的常數：L1 殼的 `RECEIVABLES_MISSING` 與 M08 reports 的 `RECEIVABLES_MISSING`（後者多了括號說明）。前端只顯示伺服器給的那一句，目前不影響；殼刪除後自然消失。
- **O-3**　T100「匯出」（不是預覽）在 M05 不在時照樣產生不含收款事件的 Excel，只在預覽的 notice 說明。IP-99 已寫明「匯入檔不加說明列」，屬已裁示的設計，記錄備查。

## 4. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆 | commit | D 確認 |
|---|---|---|---|
| M5-M1 | **修正**（主持裁示做成通用機制）：`docs/platform/deprecations.json`（{file, name, since_core, remove_at_major, replacement}）＋`tests/platform/test_deprecations.py`：① 主版號 ≥ remove_at_major 而名稱還在 ⇒ 紅 ② 產品程式寫了「淘汰」卻沒登記 ⇒ 紅（反掃）③ 登記了名稱不存在 ⇒ 紅；各有合成反向控制。登記 receivables 殼 4 個名稱（remove_at_major 2）。突變：CORE 改 2.0 ⇒ ① 紅；登記表清空 ⇒ ② 紅。⚠ 交會：c-m01-s3 的 IP-12 `summary` 也寫了「淘汰」，兩包合回後 ② 會要求它登記（A 的 helpers.voucher 別名由 A 補） | c5484962（wip/c-m05b-2） | |
| M5-M2 | **修正**：每題自己的 context（`_page()` context manager），try/finally 關；關前 `unroute_all(behavior="ignoreErrors")`。本檔＋golden＋deprecations 連跑 3 次皆 12 過 | c5484962 | |
| M5-S1 | **修正**：`loadPayable`／`loadReceivable`（出納頁籤路徑）的 404 也記 `payableSnapMissing`；新 e2e `test_reports_cashier_tab_entry_also_records_the_reason`（`?tab=cashier` 進來）；突變拿掉該行 ⇒ 紅；analytics 1.0.4 | c5484962 | |
