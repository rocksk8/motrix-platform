# 稽核：B 的計數／棘輪守門補掃 modules/（wip/b-scan-modules 64c3a9f6）（D，2026-09-26 22:33）

> 標準等級。延伸自 D 在 M06 稽核的 M06-M2。稽核者 D 沒有寫過任何受稽核的程式碼。

## 0. 結論

- **必修 1、建議 1**。
- 基準：五個相關檔 46 過（3 xfail 是既有的）。

## 1. 主持三點

| # | D 的驗證 | 結果 |
|---|---|---|
| ① payroll 未綁定 user 掃描的正對照 | 新題 `test_the_scan_covers_the_file_it_was_written_for` 斷言 `modules/payroll/api/bonus.py` 在掃描集合裡。突變 B1「掃描改回只 glob routers／helpers」⇒ **紅** | 成立 |
| ② 三個頁面守門改用 page_files()＋沙盒反向控制 | alpine double-init：突變 B3「工具不掃模組頁面」⇒ **紅**（`test_al1_a_module_page_that_double_inits_is_seen`）。legal_amount_rounding：讀碼，已併入 `source_tree.page_files()`。**view_filter：突變 B2「真正那一題改回只 glob L1 頁面目錄」⇒ 存活** ⇒ SM-M1。view_filter 基線 1→0 是 `page_path_baseline.json` 的計數（這支測試不再寫死 `frontend/pages`），屬真的減少 | view_filter 那一支不成立 |
| ③ 送信檔「有人做過決定」 | 突變 B4「archive.py 移出 SCAN_FILES」⇒ **紅**（`test_every_mail_sender_is_classified`）。沙盒反向控制 `test_a_new_sender_without_a_decision_is_red` 驗新增未歸類的送信檔會紅。排除清單：`NOT_SCANNED` 目前是空的，每筆要有理由而且仍是送信檔，不可同時在兩邊；加進 `SCAN_FILES` 的檔要照樣通過文案檢查，所以塞進去並不能讓守門變綠 | 成立（旁路見 SM-S1） |

## 2. 發現

**SM-M1（必修）　view_filter 的沙盒反向控制沒有釘住「真正那一題用哪個頁面集合」**
- 兩支新題（`test_a_module_page_is_in_scope`、`test_a_marked_module_page_passes`）直接呼叫 `_undecided_pages(source_tree.page_files())`。
- 真正的 `test_every_filter_like_binding_has_a_decision` 改回 `FRONTEND_PAGES.glob("*.html")` 時，這兩支照綠，也就是這包要防的「頁面搬進 modules 之後安靜地少掃」，在 view_filter 上仍然沒有題守。
- 修法：比照 alpine 的 `test_al1_the_page_population_is_drawn_from_page_files`，讓真正那一題的頁面集合可注入並被斷言；或者沙盒題改成直接跑真正那一題的函式本體。

**SM-S1（建議）　送信偵測的旁路**
- D 實測 `_mail_senders`：`from helpers.email_notify import _send_raising as s; s(...)` ⇒ **漏**；`getattr(email_notify, "_send_raising")(...)` ⇒ **漏**。`from smtplib import SMTP` 與直接呼叫都抓得到。
- 建議：ImportFrom 了任一原語（不看 alias）就算送信檔；字串常數等於原語名稱也算。

- 觀察：email_notify 的公開函式（`notify_*`）都是各自組好內文的領域通知，文案本身在 email_notify 裡，已在掃描範圍內，沒有「任意主旨＋內文」的公開送信口。
