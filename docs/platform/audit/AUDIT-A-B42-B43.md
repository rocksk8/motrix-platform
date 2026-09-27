# 稽核：B42 建構器 -5（wip/b-builder-dnd-5 d26a7b0c）＋B43 jv36 needs_m01（wip/b-jv36-needs-m01 424fe442）（A，2026-09-28 01:41）

> 只讀碼，沒有跑測試，也沒有改 B 的分支。範圍：
> - B42：`f84fb2df...d26a7b0c`（4 檔，+94／−1）
> - B43：`4348a3f3...424fe442`（4 檔，+17）

## 0. 結論

- **B42：必修 0、建議 1、觀察 2；合回時要處理 1 項版號衝突（AB42-C1）。**
- **B43：必修 0、觀察 1。** 11 題逐題都有 M01 的資料或挑案件的介面，沒有「驗 L1 照常」卻被標記的；同檔中沒標的題也逐一核對過。

## 1. B42

| 項目 | 讀碼結果 | 判定 |
|---|---|---|
| notif 預覽旗標題 | 另開同源空白頁：先開 login.html 取得同源，再 `set_content`；不裝第三道防線、只設旗標，然後載入 notif.js，量 `window.fetch` 有沒有被換掉。已核對：login.html **沒有**載入 notif.js，所以 `__fetchBefore` 是原生的 fetch；notif.js 的旗標判斷只包住第一段（包裝 fetch，notif.js:2-5），`window.MotrixReads` 在另一段（:36），所以 `wait_for_function(MotrixReads)` 在兩題都等得到。正對照（不設旗標 ⇒ fetch 被換掉）證明觀測點量得到 notif.js 的動作。D 23:52 那個存活的突變在這個觀測點上會紅 | 成立 |
| 禁 x-html 守門 | `source_tree.page_file` 找不到頁面時會紅、不會略過（§G5 #15）。正對照：在真頁面植入 `x-html`、`x-bind:innerHTML`、`:innerHTML` 各一處，都要亮、並指到正確行號。反向控制：`x-text`、`data-x-html-note`、註解、`:title` 都不算。真實題與對照走同一支 `html_sinks` | 成立；範圍見 AB42-S1 |
| BUILDER-UX §3.3／§4 | 兩段文字與題名一致 | 成立 |
| version_manifest 合併成一筆 | 建構器那一筆（未出貨）的版號從 `2026-09-27b` 改成 `2026-09-28a`，原內容保留，後面加一句安全檢查的說明。一個模組一筆（VR3）、當天有條目（VR1）都成立 | 成立，但版號衝突見 AB42-C1 |

**AB42-C1（合回衝突，不是缺陷）　`2026-09-28a` 與 A34 撞號**

- `wip/a-cr-network-errors`（A34）的「自訂模組/單據」也是 `2026-09-28a`
- `test_version_manifest_unique_version` 要求版號唯一 ⇒ 兩包都合回時會紅
- 處置：後合回的一包改成下一個字母；A34 由 A 自己改（列車時對照 origin 再定）

**AB42-S1（建議）　守門只擋 Alpine 屬性；頁面裡的 JS HTML 寫入點不在範圍內**

- `custom-records.html` 現有兩處把 HTML 字串放進 DOM：
  - :310 `<iframe sandbox="" :srcdoc="outputHtml">`：沒有 scripts，隔離成立
  - :682 `openOutput`：`w.document.write(html)`，寫進 `window.open('')` 開的**同源**新視窗，沒有 sandbox
- 目前內容是伺服器輸出的版型，D 稽核過後端轉義，所以不是現行漏洞
- 但它與 x-html 是同一類風險（使用者自訂內容一旦被當成 HTML，會在同源、帶著登入 token 的環境執行），守門看不到
- 建議：
  - 守門擴大到 `.innerHTML =`、`insertAdjacentHTML`、`document.write`、`srcdoc`，以白名單列出已審過的兩處（附理由）
  - 或把「輸出」改成 Blob URL，或用帶 sandbox 的新頁開

**觀察**

- **AB42-O1**：notif 題用 `e2e_browser.new_page()` 直接開頁，沒有經過 `new_context`。分類守門認得 `e2e_browser`，所以 marker 那道不受影響；但 e2e 的逐題軟死線靠「關掉這題的 contexts」解卡，直接開的頁不在追蹤範圍內 ⇒ 這兩題卡住時只能等硬上限。題很短，風險低。
- **AB42-O2**：版本紀錄的時間 `00:41` 與 A34 那一筆相同，應是巧合（兩邊各自用 date 產生），記錄備查。

## 2. B43（needs_m01 逐題）

逐題核對：題目本體＋它呼叫的同檔 helper，用到 M01 的方式如下。

| 檔 | 題 | 標記 | M01 依據 | 判定 |
|---|---|---|---|---|
| test_e2e_voucher_summary | jv7_…tab_switch | ✅ 新增 | `_seed_case` 寫報價單；從案件帶入摘要 | 該標 |
| 〃 | jv7_…reload | ✅ 新增 | 同上 | 該標 |
| 〃 | o92_late_deep_link…、o92_new_voucher… | 未標 | 只用兩張傳票（`_two_vouchers`），不碰案件 | 不該標 ✓ |
| test_e2e_voucher_summary_panel_side_by_side | picking_a_case_keeps_the_focus… | ✅ 新增 | `_seed` 寫報價單；挑案件 | 該標 |
| test_jv33_voucher_summary_panel | 4 題 | ✅ 新增 | `seed_extra_expense`＋支出項面板（M01 的案件與支出項來源） | 該標 |
| test_jv36_voucher_line_source_files | picking_an_expense…、picking_a_case…（原本就有標） | ✅ | `_open_with_case` 挑案件 | 該標 |
| 〃 | second_expense…、auto_amount…、o13 兩題 | ✅ 新增 | `_open_with_case`／`_slow_page` 挑案件或支出項 | 該標 |
| 〃 | a_path_escaping_uploads_is_refused | 未標 | 驗會計端 `line-source-file` 的路徑守門 | 不標可以；見 AB43-O1 |
| 〃 | lines_remember_their_source_and_bad_sources_are_refused | 未標 | 驗傳票行記住來源型別、錯誤型別 ⇒ 422（會計自己的驗證，不查來源存不存在） | 不該標 ✓（「L1／會計照常」） |

- 做法符合 §G5 #7：逐題標記、不是整檔；`requires_module` 的說明字串指出原因（M4-M3）。
- **AB43-O1（觀察）**：`a_path_escaping_uploads_is_refused` 在 M01 不在的樹上，`extra_expense` 來源可能在路徑守門之前就因提供者不在而 404。斷言是「400 或 404 而且沒有機密內容」，照樣綠，但這時它沒有驗到路徑守門（空轉的綠）。建議在那種樹上改用不經 M01 的來源型別，或加一句斷言：404 必須是「查無檔案」而不是「模組未安裝」。不擋 B43。
