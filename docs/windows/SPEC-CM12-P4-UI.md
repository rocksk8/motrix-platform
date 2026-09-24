# SPEC-CM12 P4 預備：共用提示／對話框 `static/ui.js`

來源：HANDOFF「🧊 CM12」P4（共用對話框），hichan-0a 2026-09-24 派 hichan-bf 先做**元件＋題＋e2e helper**，不碰凍結中的 `case-management.*`；套進案件頁由 hichan-a3 或 hichan-bf 在 CM12 做。

## API（`window.MotrixUI`，頁面載 `<script src="../static/ui.js"></script>`）
| 呼叫 | 回傳 | 取代 |
|---|---|---|
| `toast(msg, {kind:'ok'\|'error'\|'info', ms})` | 元素；ok／info 3 秒、error 6 秒自動消失；`ms:0` 不消失 | 成功類 `alert()` |
| `confirm(msg, {title, okText, cancelText, danger})` | `Promise<true\|false>` | `confirm()` |
| `prompt(msg, {title, value, placeholder, okText, cancelText, required})` | `Promise<字串\|null>`；取消＝`null`，空字串是合法答案（除非 `required`） | `prompt()` |
| `banner(msg, {kind:'warn'\|'error'\|'info', id, dismissible})` | `{el, close()}`；常駐；同 `id` 取代 | 需要使用者處理的錯誤／衝突 |

- 鍵盤：Esc＝取消、Enter＝確認、Tab 焦點鎖在對話框內、關閉後焦點回到開啟前的元素。
- `danger:true` ⇒ 初始焦點在「取消」（誤按 Enter 不會做下去），`role=alertdialog`。
- 一次一個對話框，後來的排隊。
- 訊息一律 `textContent`（不當 HTML）。
- 深色模式：色彩一律讀 style.css 的 P3 語意 token（`--surface`／`--ink-*`／`--line*`／`--tone-*`／`--overlay-backdrop`）。
  ~~走全站反轉濾鏡~~ **更正（rebase 帶進 P3 1b684cc 後）**：P3 的深色 token 是給「不經反轉」的元素用的 ⇒ 本元件根元素 `.mui-root`
  **退出**全站 invert（ui.js 自己注入 `:root[data-theme=dark] body > .mui-root{filter:none !important}`，不改 style.css 共用排除清單），
  直接吃深色 token；否則深色值會被再反轉一次變回淺色。⇒ 這是第一個照 P3 方向「移出反轉」的元件，案件頁移出時可比照。

## ⚠️ 替換時的語意差異（套進案件頁時要逐處判斷）
- 原生 `confirm()`／`prompt()` 是**同步**的，`MotrixUI` 是 `async`：呼叫端要改成 `if (!(await MotrixUI.confirm(...))) return`，**所在函式要變 async**，而呼叫它的地方若依賴回傳值也要跟著 await。
- 原生 `alert()` 會停住程式直到使用者按確定；`toast()` 不會。錯誤訊息若後面緊接著「放棄這次操作」的流程，改 `toast(…, {kind:'error'})` 行為等價；若 alert 是在等使用者讀完才繼續（少見），改 `await MotrixUI.confirm(msg, {cancelText: …})` 或保留。
- 現況（origin/master，CM12 凍結前）：~~`case-management.js` 約 `alert(` 170、`confirm(` 54、`prompt(` 11 處；`backend/tests` 有 29 個檔用 `page.on('dialog')`~~
  **更正**：實際呼叫 232（alert 170、confirm 52、prompt 10，含 HTML 內嵌 1；grep 多算了 5 處註解）；用 `page.on('dialog')` 的檔 31 個（含本項新增的 `_ui_dialogs.py` 與 ui.js 自己的題）。逐處清單見附錄 A。

## e2e helper：`backend/tests/_ui_dialogs.py`
```python
from tests._ui_dialogs import answer_confirm, answer_prompt, expect_toast, forbid_native_dialogs
natives = forbid_native_dialogs(page)          # 取代 page.on('dialog', lambda d: d.accept())
page.click(...)
answer_confirm(page, ok=True, expect="確定要刪除")   # 看到了再回答，且驗訊息內容
answer_prompt(page, "比例要調", expect="退回原因")    # value=None ⇒ 取消
expect_toast(page, "已刪除", kind="ok")
assert natives == []                            # 頁面若還在用原生對話框 ⇒ 抓得到
```

## 題
`backend/tests/test_e2e_ui_dialogs_2026_09_24.py`（7 支，`set_content` 最小測試頁，不動產品頁）：確認的鍵盤／點擊／背景、危險確認初始焦點、輸入框的值／取消／必填、焦點鎖與還原、排隊＋helper、toast／banner（含 HTML 注入當文字）、深色模式吃深色 token 且不被反轉（正對照：同頁一般元素仍被反轉）。突變 9 處皆紅（含「拿掉退出反轉」「背景寫死不讀 token」）。




## 附錄 A：P4 套用清單（2026-09-24，hichan-0a 派；以 1b684cc 的單檔為準）
來源：`frontend/js/case-management.js`@1b684cc（與 master 至 b60cfec 相同；P1 拆檔尚未推）。**主鍵＝方法名＋原文**，行號拆檔後會變，只作參考。
產生方式（可重跑）：scratchpad 的 `p4_extract.py`（抽呼叫、判型態）→ `p4_ripple.py`（sync 函式與呼叫端）→ 實際跑用 `page.on('dialog')` 的題並記錄每個對話框（`p4_dialog_logger.py` pytest 外掛）→ `p4_map.py`（以原文最長固定片段對回）。
### 數量（更正留著）
- ~~`alert(` 170、`confirm(` 54、`prompt(` 11（共 235）~~ **更正**：那是 grep 粗算，含 5 處註解裡的字（例：「原本用 prompt()」）。實際呼叫 **232**：alert 170、confirm 52、prompt 10（其中 HTML 內嵌 1：`@click` 裡的 alert）。
- 換成：toast(error) 152、confirm(danger) 34、confirm 18、toast(info) 11、prompt 10、toast(ok) 7。
- 分包：**A（案件層級／額外支出／款項／請款／開票／階段／結案／沖銷／附件）120 處**、**B（設備／叫料／派工／承攬匯款／出貨／完工／表單關閉）112 處**——兩包不共用方法，可兩人並行。

### 機械化規則
1. `alert(msg)` → `MotrixUI.toast(msg, {kind: 'error'|'ok'|'info'})`（表中「換成」欄已判好）。alert 會停住程式，toast 不會——**實查**每一處 alert 之後的第一個語句：全部是 `return`／區塊結束（含先重設狀態再 return），只有 `openInvoiceVoucherModal` 2 處是「alert 後關閉 Modal」，改 toast 後 Modal 立刻關、提示照樣看得到 ⇒ **不需要特別處理**。（第一版自動判斷標了 3 處「後面緊接換頁」，實查都是 alert 後 return、換頁只在成功路徑，已更正。）
2. `confirm` → `await MotrixUI.confirm(msg, {danger?})`；`danger` 依原文判（刪除／移除／作廢／結案／解鎖／撤銷／退回／駁回…），表中已標。**所在函式必須是 async**——表中「所在函式要改 async」的 9 處之外都已經是 async。
3. `prompt` → `await MotrixUI.prompt(msg, {required?})`；本檔 10 處全是「選填原因」且原本就用 `=== null` 判取消 ⇒ 語意不變（取消＝null、空字串＝空字串）。
4. sync → async 的連帶：`_confirmRemoveDevice`（:3442）與 `_confirmDiscardForm`（:4069）是**回傳 confirm 結果的小函式** ⇒ 改成回 Promise 後，呼叫端（`removeDevice`、`removeDeviceByObj`、6 個 `close*ModalGuarded`）都要 `await` 並改 async；它們的呼叫端都是 HTML 事件（`@click`／`@keydown.escape`），不用再往上改。
5. Esc：`close*ModalGuarded` 常掛在 Modal 的 `@keydown.escape`；MotrixUI 對話框的 Esc 在 capture 階段攔下並 stopPropagation ⇒ 「在確認框按 Esc」只關確認框、不會連帶再觸發 Modal 的 Esc。
6. 測試：凡是表中「測到它的題」有名字的，改完要把該題的 `page.on('dialog', …)` 換成 `tests/_ui_dialogs.py` 的 `answer_confirm`／`answer_prompt`（附 `expect=` 驗訊息）；其餘題的 handler 換成 `forbid_native_dialogs(page)`，最後斷言 `== []`。

### 包 A
| # | 方法（行@1b684cc） | 種類 | 原文 | 換成 | 改法 | 備註 | 測到它的題 |
|---|---|---|---|---|---|---|---|
| 1 | `xeSubmit`（585） | confirm | confirm(`確定送審這筆額外支出？\n\n${x.description} NT$ ${Math.round(x.totalCost … | confirm | `if (!(await MotrixUI.confirm(…))) return` |  |  |
| 2 | `xeDeleteFile`（624） | confirm | confirm('確定刪除這個附件？') | confirm(danger) | 逐處改寫：`!x \|\| !confirm(…)` → `!x \|\| !(await …)`（短路保留）；`(prompt(…) \|\| '')` → `((await …) \|\| '')` |  |  |
| 3 | `xeDelete`（642） | confirm | confirm(`確定刪除「${x.description}」？`) | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` |  |  |
| 4 | `xeSubmitChange`（755） | confirm | confirm(`確定送審這筆變更申請？\n\n${c.description}\nNT$ ${oldA} → NT$ ${newA}\n\… | confirm | `if (!(await MotrixUI.confirm(…))) return` |  | test_change_request_round_trip_in_browser（test_e2e_extra_expenses_ui_2026_09_11） |
| 5 | `xeCancelChange`（774） | confirm | confirm('確定撤銷這筆變更申請？已上傳的待核准附件會一併刪除。') | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` |  |  |
| 6 | `xeDeleteChangeFile`（811） | confirm | confirm('確定刪除這個待核准附件？') | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` |  |  |
| 19 | `selectCase`（1690） | confirm | confirm(`上一張案件（${this.selected.quote_no}）沒有存成功：${this.saveMsg \|\| '未儲存'… | confirm(danger) | 逐處改寫：`!x \|\| !confirm(…)` → `!x \|\| !(await …)`（短路保留）；`(prompt(…) \|\| '')` → `((await …) \|\| '')` |  |  |
| 20 | `addActionItem`（1846） | alert | alert('新增失敗：' + (await r.json()).detail) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 21 | `addActionItem`（1850） | alert | alert('發生錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 22 | `deleteActionItem`（1857） | confirm | confirm('確定刪除此待辦事項？') | confirm(danger) | 逐處改寫：`!x \|\| !confirm(…)` → `!x \|\| !(await …)`（短路保留）；`(prompt(…) \|\| '')` → `((await …) \|\| '')` |  |  |
| 23 | `deleteActionItem`（1863） | alert | alert('刪除失敗：' + (await r.json()).detail) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 24 | `deleteActionItem`（1866） | alert | alert('發生錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 25 | `approveActionItem`（1878） | alert | alert('確認失敗：' + (await r.json()).detail) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 26 | `approveActionItem`（1881） | alert | alert('發生錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 27 | `saveAssignedUsers`（1907） | alert | alert('儲存失敗：' + (await r.json()).detail) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 28 | `saveAssignedUsers`（1909） | alert | alert('發生錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 29 | `exportProjectReport`（1923） | alert | alert('匯出失敗：' + (await r.json()).detail) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 30 | `exportProjectReport`（1932） | alert | alert('發生錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 31 | `pullContractFromQuote`（1962） | alert | alert('報價單上沒有可帶入的欄位，或案件這邊都已經有值了。') | toast(info) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 32 | `removePaymentItem`（2301） | confirm | confirm(`確定要刪除款項期別「${pi?.type \|\| '第' + (idx + 1) + '期'}」？\n\n刪除後會自動存檔，… | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` | **所在函式要改 async**；呼叫端只有 HTML 事件，無需改 | test_deleting_payment_item_asks_first（test_e2e_case_data_loss_2026_09_24）<br>test_sales_sees_reason_when_deleting_received_installment（test_e2e_received_installment_lock_2026_09_24） |
| 33 | `_flushBeforeItemOp`（2579） | alert | alert('請先存檔成功後再操作（' + (this.saveMsg \|\| '尚未儲存') + '）') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 34 | `cancelWriteoff`（2646） | alert | alert(res.msg) | toast(info) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） | 訊息是變數，原文在上方組字 |  |
| 35 | `approveWriteoff`（2660） | alert | alert(res.msg) | toast(info) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） | 訊息是變數，原文在上方組字 |  |
| 36 | `closeCaseAction`（2676） | alert | alert('案件沒有存成功，已停止結案：' + (this.saveMsg \|\| '儲存失敗')) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  | test_close_stops_when_save_fails（test_case_close_checklist_2026_09_24） |
| 37 | `closeCaseAction`（2684） | alert | alert(d.detail \|\| '無法取得結案條件') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 38 | `closeCaseAction`（2687） | alert | alert('網路錯誤，請稍後再試') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 39 | `updateDealTag`（2808） | alert | alert(err.detail \|\| '操作失敗，請稍後再試') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 40 | `updateDealTag`（2811） | alert | alert('網路錯誤，請稍後再試') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 41 | `unlockCase`（2817） | confirm | confirm('確認解鎖此已結案案件？\n\n解鎖後將進入「半解鎖」狀態，之後對案件記錄的變更/上傳需最高管理員於簽核佇列審核通過後才會套… | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` |  |  |
| 42 | `unlockCase`（2826） | alert | alert((await r.json().catch(() => ({}))).detail \|\| '解鎖失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 43 | `unlockCase`（2828） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 44 | `lockCase`（2833） | confirm | confirm('確認重新上鎖此案件？\n\n上鎖後將無法再變更案件記錄，需再次解鎖才能繼續編輯（既有待審核項目不受影響）。') | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` |  |  |
| 45 | `lockCase`（2842） | alert | alert((await r.json().catch(() => ({}))).detail \|\| '上鎖失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 46 | `lockCase`（2844） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 47 | `addStage`（2892） | alert | alert('新增階段失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 48 | `addStage`（2894） | alert | alert('發生錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 49 | `removeStage`（2900） | confirm | confirm(`確定要刪除執行階段「${st.label \|\| '未命名'}」？\n\n階段內的拜訪紀錄會一併刪除，無法復原。`) | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` |  |  |
| 50 | `removeStage`（2903） | alert | alert('刪除失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 51 | `removeStage`（2906） | alert | alert('發生錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 52 | `setStageRatio`（2926） | alert | alert('比例需為 0～100%') | toast(info) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 53 | `updateStage`（2945） | alert | alert('儲存失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 54 | `updateStage`（2949） | alert | alert('發生錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 55 | `removeStageAssignee`（2963） | confirm | confirm(`確定要把「${(u && u.display_name) \|\| username}」從階段「${st.label \|\| '… | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` |  |  |
| 56 | `toggleStageDependency`（2990） | alert | alert('這樣設定會讓階段之間互相循環依賴，請重新選擇前置階段') | toast(info) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 57 | `toggleStageDependency`（2999） | alert | alert(err.detail \|\| '設定失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 58 | `toggleStageDependency`（3003） | alert | alert('發生錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 59 | `addVisit`（3269） | alert | alert('新增記錄失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 60 | `addVisit`（3271） | alert | alert('發生錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 61 | `removeVisit`（3277） | confirm | confirm(`確定要刪除這筆拜訪紀錄${visit.visitDate ? '（' + visit.visitDate + '）' : … | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` |  |  |
| 62 | `removeVisit`（3282） | alert | alert('刪除失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 63 | `removeVisit`（3284） | alert | alert('發生錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 69 | `postComment`（3869） | alert | alert('留言失敗：' + (err.detail \|\| r.status)) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 70 | `postComment`（3872） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 71 | `deleteCommentFile`（3884） | confirm | confirm(`確定刪除附件「${file.filename}」？此動作無法復原。`) | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` |  |  |
| 72 | `deleteCommentFile`（3893） | alert | alert('刪除失敗：' + (err.detail \|\| r.status)) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 73 | `deleteCommentFile`（3895） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 74 | `postWorkLogEntry`（3922） | alert | alert('新增工作日誌失敗：' + (await r.json()).detail) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 75 | `postWorkLogEntry`（3932） | alert | alert('照片上傳失敗：' + (await rp.json()).detail) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 76 | `postWorkLogEntry`（3944） | alert | alert('發生錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 77 | `deleteUpdate`（3951） | confirm | confirm('確定刪除這則更新？') | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` |  |  |
| 113 | `downloadClosingReportPdf`（4559） | alert | alert((await r.json().catch(() => ({}))).detail \|\| '結案報表產生失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 114 | `downloadClosingReportPdf`（4569） | alert | alert('下載失敗：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 139 | `confirmPayVoucher`（4822） | alert | alert((await r.json()).detail \|\| '操作失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 140 | `confirmPayVoucher`（4827） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 145 | `openInvoiceVoucherModal`（4906） | alert | alert('款項明細有未儲存的修改，請先儲存後再申請開票憑據') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 146 | `openInvoiceVoucherModal`（4918） | alert | alert((await r.json()).detail \|\| '載入額度失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 147 | `openInvoiceVoucherModal`（4919） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 148 | `openNetworkPlan`（4938） | alert | alert((await r.json().catch(() => ({}))).detail \|\| '查詢失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 149 | `openNetworkPlan`（4939） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 150 | `openNetworkPlan`（4943） | alert | alert('此案件尚無網路架構規劃書') | toast(info) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 151 | `openNetworkPlan`（4944） | confirm | confirm('此案件尚無網路架構規劃書，是否建立一份？') | confirm | `if (!(await MotrixUI.confirm(…))) return` |  |  |
| 152 | `openNetworkPlan`（4951） | alert | alert((await cr.json().catch(() => ({}))).detail \|\| '建立失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 153 | `openNetworkPlan`（4954） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 154 | `submitInvoiceVoucherCreate`（5006） | alert | alert('請輸入申請金額') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 155 | `submitInvoiceVoucherCreate`（5007） | alert | alert('超過剩餘可申請金額') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 156 | `submitInvoiceVoucherCreate`（5013） | alert | alert('請至少選擇一項品項') | toast(info) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 157 | `submitInvoiceVoucherCreate`（5014） | alert | alert('超過剩餘可申請金額') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 158 | `submitInvoiceVoucherCreate`（5017） | confirm | confirm('確定送出建立開票申請憑據？') | confirm | `if (!(await MotrixUI.confirm(…))) return` |  |  |
| 159 | `submitInvoiceVoucherCreate`（5025） | alert | alert((await r.json()).detail \|\| '建立失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 160 | `submitInvoiceVoucherCreate`（5028） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 161 | `deleteInvoiceVoucher`（5033） | confirm | confirm(`確定刪除開票申請憑據「${v.voucherNo}」？`) | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` |  |  |
| 162 | `deleteInvoiceVoucher`（5040） | alert | alert((await r.json()).detail \|\| '刪除失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 163 | `deleteInvoiceVoucher`（5041） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 164 | `submitInvoiceVoucher`（5045） | confirm | confirm(`確定送出開票申請憑據「${v.voucherNo}」進行簽核？`) | confirm | `if (!(await MotrixUI.confirm(…))) return` |  |  |
| 165 | `submitInvoiceVoucher`（5051） | alert | alert((await r.json()).detail \|\| '送出失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 166 | `submitInvoiceVoucher`（5053） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 167 | `approveInvoiceVoucher`（5062） | confirm | confirm(`確定簽核開票申請憑據「${v.voucherNo}」？` + window.MotrixApproval.cascadeN… | confirm | `if (!(await MotrixUI.confirm(…))) return` |  |  |
| 168 | `approveInvoiceVoucher`（5069） | alert | alert((await r.json()).detail \|\| '簽核失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 169 | `approveInvoiceVoucher`（5071） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 170 | `rejectInvoiceVoucher`（5075） | prompt | prompt(`退回開票申請憑據「${v.voucherNo}」，可填寫退回原因（選填）：`) | prompt | `const x = await MotrixUI.prompt(…)`；`=== null` 判斷照舊（取消＝null） |  |  |
| 171 | `rejectInvoiceVoucher`（5083） | alert | alert((await r.json()).detail \|\| '退回失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 172 | `rejectInvoiceVoucher`（5085） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 173 | `revokeInvoiceVoucherApproval`（5089） | prompt | prompt(`撤銷開票申請憑據「${v.voucherNo}」的核准？將退回草稿。\n\n可填寫撤銷原因（選填）：`) | prompt | `const x = await MotrixUI.prompt(…)`；`=== null` 判斷照舊（取消＝null） |  |  |
| 174 | `revokeInvoiceVoucherApproval`（5097） | alert | alert((await r.json()).detail \|\| '撤銷失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 175 | `revokeInvoiceVoucherApproval`（5099） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 176 | `downloadInvoiceVoucherPdf`（5111） | alert | alert((await r.json().catch(() => ({}))).detail \|\| 'PDF 產生失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 177 | `downloadInvoiceVoucherPdf`（5121） | alert | alert('下載失敗：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 178 | `previewInvoiceVoucherPdf`（5130） | alert | alert((await r.json().catch(() => ({}))).detail \|\| 'PDF 產生失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 179 | `previewInvoiceVoucherPdf`（5135） | alert | alert('預覽失敗：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 180 | `previewAttachmentFile`（5162） | alert | alert('取得檔案連結失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 181 | `previewAttachmentFile`（5165） | alert | alert('開啟檔案失敗：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 187 | `uploadInvoiceVoucherIssuedFiles`（5208） | alert | alert((await r.json().catch(() => ({}))).detail \|\| '上傳失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 188 | `uploadInvoiceVoucherIssuedFiles`（5210） | alert | alert('上傳失敗：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 189 | `uploadPaymentItemInvoiceFiles`（5226） | alert | alert((await r.json().catch(() => ({}))).detail \|\| '上傳失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 190 | `uploadPaymentItemInvoiceFiles`（5228） | alert | alert(body.message \|\| '已送出，待最高管理員審核後套用') | toast(ok) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 191 | `uploadPaymentItemInvoiceFiles`（5236） | alert | alert('上傳失敗：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 192 | `deletePaymentItemInvoiceFile`（5241） | confirm | confirm('確定刪除此附件？') | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` |  |  |
| 193 | `deletePaymentItemInvoiceFile`（5248） | alert | alert((await r.json().catch(() => ({}))).detail \|\| '刪除失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 194 | `deletePaymentItemInvoiceFile`（5250） | alert | alert(body.message \|\| '已送出，待最高管理員審核後套用') | toast(ok) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 195 | `deletePaymentItemInvoiceFile`（5255） | alert | alert('刪除失敗：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 220 | `deleteInvoiceVoucherIssuedFile`（5409） | confirm | confirm('確定刪除此附件？') | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` |  |  |
| 221 | `deleteInvoiceVoucherIssuedFile`（5415） | alert | alert((await r.json().catch(() => ({}))).detail \|\| '刪除失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 222 | `deleteInvoiceVoucherIssuedFile`（5417） | alert | alert('刪除失敗：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 223 | `_caseTaskSubmitReport`（5461） | alert | alert('請填寫回報內容') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 224 | `_caseTaskSubmitReport`（5470） | alert | alert(e.detail \|\| '送出失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 225 | `_caseTaskSubmitReport`（5473） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 226 | `markPendingAcceptance`（5525） | confirm | confirm(`確定將「${this._dispatchLabel(d)}」標記為待驗收？`) | confirm | `if (!(await MotrixUI.confirm(…))) return` |  |  |
| 227 | `markPendingAcceptance`（5532） | alert | alert((await r.json()).detail \|\| '操作失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 228 | `markPendingAcceptance`（5534） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 232 | `(inline 屬性)`（2352） | alert | alert('款項明細有未儲存的修改，請先儲存後再申請請款單') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |

### 包 B
| # | 方法（行@1b684cc） | 種類 | 原文 | 換成 | 改法 | 備註 | 測到它的題 |
|---|---|---|---|---|---|---|---|
| 7 | `deleteCompletionNote`（860） | confirm | confirm(`確定刪除完工單「${n.noteNo}」？`) | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` |  |  |
| 8 | `submitCompletionNote`（869） | confirm | confirm(`確定送出完工單「${n.noteNo}」申請完工？${warn}`) | confirm | `if (!(await MotrixUI.confirm(…))) return` |  |  |
| 9 | `approveCompletionNote`（879） | confirm | confirm(`確定簽核完工單「${n.noteNo}」？` + window.MotrixApproval.cascadeNote(_c… | confirm | `if (!(await MotrixUI.confirm(…))) return` |  |  |
| 10 | `rejectCompletionNote`（884） | prompt | prompt(`退回完工單「${n.noteNo}」，可填寫退回原因（選填）：`) | prompt | `const x = await MotrixUI.prompt(…)`；`=== null` 判斷照舊（取消＝null） |  |  |
| 11 | `revokeCompletionApproval`（890） | prompt | prompt(`撤銷完工單「${n.noteNo}」的核准？將退回草稿。\n\n可填寫撤銷原因（選填）：`) | prompt | `const x = await MotrixUI.prompt(…)`；`=== null` 判斷照舊（取消＝null） |  |  |
| 12 | `toggleCompletionSigned`（899） | confirm | confirm(msg) | confirm | `if (!(await MotrixUI.confirm(…))) return` | 訊息是變數，原文在上方組字 |  |
| 13 | `toggleCompletionSigned`（900） | prompt | prompt('備註（選填，例如驗收人姓名或方式）：') | prompt | 逐處改寫：`!x \|\| !confirm(…)` → `!x \|\| !(await …)`（短路保留）；`(prompt(…) \|\| '')` → `((await …) \|\| '')` |  |  |
| 14 | `_cnAction`（913） | alert | alert((await r.json().catch(() => ({}))).detail \|\| failMsg) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） | 訊息是變數，原文在上方組字 |  |
| 15 | `_cnAction`（915） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 16 | `previewCompletionPdf`（924） | alert | alert((await r.json().catch(() => ({}))).detail \|\| 'PDF 產生失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 17 | `previewCompletionPdf`（932） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 18 | `moRemoveItem`（1025） | confirm | confirm(`確定要刪除叫料品項「${(m && m.itemName) \|\| '未命名'}」？\n\n按「儲存」之後才會寫入。`) | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` | **所在函式要改 async**；呼叫端只有 HTML 事件，無需改 |  |
| 64 | `removeMaterial`（3326） | confirm | confirm(`確定要刪除材料「${m?.name \|\| '未命名'}」？\n\n刪除後會自動存檔，無法復原。`) | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` | **所在函式要改 async**；呼叫端只有 HTML 事件，無需改 |  |
| 65 | `openImportModal`（3347） | alert | alert('報價單無可匯入的品項') | toast(info) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 66 | `doImport`（3364） | alert | alert('請至少選擇一個品項') | toast(info) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 67 | `_confirmRemoveDevice`（3442） | confirm | confirm(`確定要刪除設備「${dev?.name \|\| '未命名'}${dev?.sn ? '／' + dev.sn : ''}」？… | confirm(danger) | `return MotrixUI.confirm(…)`（變 Promise）⇒ 呼叫端全部 `await` | **所在函式要改 async**；用到回傳值的呼叫端（也要 await、也要 async）：行 3445、3451 |  |
| 68 | `removeDeviceGroup`（3455） | confirm | confirm('確定要刪除整個設備群組？') | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` | **所在函式要改 async**；呼叫端只有 HTML 事件，無需改 |  |
| 78 | `_confirmDiscardForm`（4069） | confirm | confirm('表單尚未儲存，確定要關閉嗎？目前輸入的內容將會遺失。') | confirm | 逐處改寫：`!x \|\| !confirm(…)` → `!x \|\| !(await …)`（短路保留）；`(prompt(…) \|\| '')` → `((await …) \|\| '')` | **所在函式要改 async**；用到回傳值的呼叫端（也要 await、也要 async）：行 4072、4075、4078、4081、4084、4087 | test_header_first_row_is_customer_and_status_and_only_save_is_a_main_button（test_e2e_case_header_and_payment_tab_2026_09_24）<br>test_case_page_behaviour_matches_golden（test_e2e_case_page_golden_2026_09_24） |
| 79 | `removeDispatchPersonnel`（4132） | confirm | confirm(`確定要刪除派工人員「${(p && p.name) \|\| '未命名'}」這一列？`) | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` | **所在函式要改 async**；呼叫端只有 HTML 事件，無需改 |  |
| 80 | `removeDispatchItem`（4149） | confirm | confirm(`確定要刪除派工品項「${(it && it.description) \|\| '未命名'}」這一列？`) | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` | **所在函式要改 async**；呼叫端只有 HTML 事件，無需改 |  |
| 81 | `setDispatchInvoiceDate`（4213） | alert | alert(j.detail \|\| '發票日期儲存失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 82 | `setDispatchInvoiceDate`（4217） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 83 | `deleteDispatch`（4221） | confirm | confirm(`確定刪除派發給「${this._dispatchLabel(d)}」的紀錄？`) | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` |  |  |
| 84 | `deleteDispatch`（4228） | alert | alert((await r.json()).detail \|\| '刪除失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 85 | `importDispatchToQuote`（4233） | alert | alert('此派發紀錄沒有報價品項') | toast(info) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 86 | `importDispatchToQuote`（4234） | confirm | confirm(`確定將「${this._dispatchLabel(d)}」共 ${d.items.length} 筆品項匯入至報價單？\… | confirm | `if (!(await MotrixUI.confirm(…))) return` |  |  |
| 87 | `importDispatchToQuote`（4241） | alert | alert(`✓ 已成功匯入 ${data.imported} 筆品項至報價單`) | toast(ok) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 88 | `importDispatchToQuote`（4242） | alert | alert(data.detail \|\| '匯入失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 89 | `importDispatchToQuote`（4243） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 90 | `openEditShippingNote`（4327） | alert | alert('讀取出貨單失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 91 | `openEditShippingNote`（4342） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 92 | `importItemsFromQuote`（4347） | alert | alert('此案件的報價單沒有品項可匯入') | toast(info) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 93 | `removeShippingItem`（4377） | confirm | confirm(`確定要刪除出貨品項「${(it && it.description) \|\| '未命名'}」這一列？`) | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` | **所在函式要改 async**；呼叫端只有 HTML 事件，無需改 |  |
| 94 | `deleteShippingNote`（4464） | confirm | confirm(`確定刪除出貨單「${n.noteNo}」？`) | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` |  |  |
| 95 | `deleteShippingNote`（4471） | alert | alert((await r.json()).detail \|\| '刪除失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 96 | `deleteShippingNote`（4472） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 97 | `submitShippingNote`（4476） | confirm | confirm(`確定送出出貨單「${n.noteNo}」進行簽核？`) | confirm | `if (!(await MotrixUI.confirm(…))) return` |  |  |
| 98 | `submitShippingNote`（4482） | alert | alert((await r.json()).detail \|\| '送出失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 99 | `submitShippingNote`（4484） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 100 | `approveShippingNote`（4493） | confirm | confirm(`確定簽核出貨單「${n.noteNo}」？` + window.MotrixApproval.cascadeNote(_c… | confirm | `if (!(await MotrixUI.confirm(…))) return` |  |  |
| 101 | `approveShippingNote`（4500） | alert | alert((await r.json()).detail \|\| '簽核失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 102 | `approveShippingNote`（4502） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 103 | `rejectShippingNote`（4506） | prompt | prompt(`退回出貨單「${n.noteNo}」，可填寫退回原因（選填）：`) | prompt | `const x = await MotrixUI.prompt(…)`；`=== null` 判斷照舊（取消＝null） |  |  |
| 104 | `rejectShippingNote`（4514） | alert | alert((await r.json()).detail \|\| '退回失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 105 | `rejectShippingNote`（4516） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 106 | `revokeShippingApproval`（4520） | prompt | prompt(`撤銷出貨單「${n.noteNo}」的核准？將退回草稿，且已扣的庫存序號會自動歸還可出貨狀態。\n\n可填寫撤銷原因（選填）… | prompt | `const x = await MotrixUI.prompt(…)`；`=== null` 判斷照舊（取消＝null） |  |  |
| 107 | `revokeShippingApproval`（4528） | alert | alert((await r.json()).detail \|\| '撤銷失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 108 | `revokeShippingApproval`（4530） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 109 | `toggleSigned`（4537） | confirm | confirm(msg) | confirm | `if (!(await MotrixUI.confirm(…))) return` | 訊息是變數，原文在上方組字 |  |
| 110 | `toggleSigned`（4538） | prompt | prompt('備註（選填，例如簽收人姓名或方式）：') | prompt | 逐處改寫：`!x \|\| !confirm(…)` → `!x \|\| !(await …)`（短路保留）；`(prompt(…) \|\| '')` → `((await …) \|\| '')` |  |  |
| 111 | `toggleSigned`（4545） | alert | alert((await r.json()).detail \|\| '操作失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 112 | `toggleSigned`（4547） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 115 | `downloadShippingPdf`（4584） | alert | alert((await r.json().catch(() => ({}))).detail \|\| 'PDF 產生失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 116 | `downloadShippingPdf`（4594） | alert | alert('下載失敗：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 117 | `previewShippingPdf`（4603） | alert | alert((await r.json().catch(() => ({}))).detail \|\| 'PDF 產生失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 118 | `previewShippingPdf`（4608） | alert | alert('預覽失敗：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 119 | `confirmCreateContractorVoucher`（4666） | alert | alert((await r.json()).detail \|\| '建立失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 120 | `confirmCreateContractorVoucher`（4671） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 121 | `deleteContractorVoucher`（4676） | confirm | confirm(`確定刪除匯款申請「${v.voucherNo}」？`) | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` |  |  |
| 122 | `deleteContractorVoucher`（4683） | alert | alert((await r.json()).detail \|\| '刪除失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 123 | `deleteContractorVoucher`（4684） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 124 | `submitContractorVoucher`（4688） | confirm | confirm(`確定送出匯款申請「${v.voucherNo}」進行簽核？`) | confirm | `if (!(await MotrixUI.confirm(…))) return` |  |  |
| 125 | `submitContractorVoucher`（4694） | alert | alert((await r.json()).detail \|\| '送出失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 126 | `submitContractorVoucher`（4696） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 127 | `approveContractorVoucher`（4705） | confirm | confirm(`確定簽核匯款申請「${v.voucherNo}」？` + window.MotrixApproval.cascadeNot… | confirm | `if (!(await MotrixUI.confirm(…))) return` |  |  |
| 128 | `approveContractorVoucher`（4712） | alert | alert((await r.json()).detail \|\| '簽核失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 129 | `approveContractorVoucher`（4714） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 130 | `rejectContractorVoucher`（4718） | prompt | prompt(`退回匯款申請「${v.voucherNo}」，可填寫退回原因（選填）：`) | prompt | `const x = await MotrixUI.prompt(…)`；`=== null` 判斷照舊（取消＝null） |  |  |
| 131 | `rejectContractorVoucher`（4726） | alert | alert((await r.json()).detail \|\| '退回失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 132 | `rejectContractorVoucher`（4728） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 133 | `revokeContractorVoucherApproval`（4732） | prompt | prompt(`撤銷匯款申請「${v.voucherNo}」的核准？將退回草稿。\n\n可填寫撤銷原因（選填）：`) | prompt | `const x = await MotrixUI.prompt(…)`；`=== null` 判斷照舊（取消＝null） |  |  |
| 134 | `revokeContractorVoucherApproval`（4740） | alert | alert((await r.json()).detail \|\| '撤銷失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 135 | `revokeContractorVoucherApproval`（4742） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 136 | `toggleContractorVoucherPaid`（4796） | confirm | confirm(`確定取消匯款申請「${v.voucherNo}」的已匯款標記？`) | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` |  |  |
| 137 | `toggleContractorVoucherPaid`（4803） | alert | alert((await r.json()).detail \|\| '操作失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 138 | `toggleContractorVoucherPaid`（4806） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 141 | `downloadContractorVoucherPdf`（4840） | alert | alert((await r.json().catch(() => ({}))).detail \|\| 'PDF 產生失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 142 | `downloadContractorVoucherPdf`（4850） | alert | alert('下載失敗：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 143 | `previewContractorVoucherPdf`（4859） | alert | alert((await r.json().catch(() => ({}))).detail \|\| 'PDF 產生失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 144 | `previewContractorVoucherPdf`（4864） | alert | alert('預覽失敗：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 182 | `uploadShippingSignedFiles`（5179） | alert | alert((await r.json().catch(() => ({}))).detail \|\| '上傳失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 183 | `uploadShippingSignedFiles`（5181） | alert | alert('上傳失敗：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 184 | `deleteShippingSignedFile`（5186） | confirm | confirm('確定刪除此附件？') | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` |  |  |
| 185 | `deleteShippingSignedFile`（5192） | alert | alert((await r.json().catch(() => ({}))).detail \|\| '刪除失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 186 | `deleteShippingSignedFile`（5194） | alert | alert('刪除失敗：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 196 | `uploadMaterialFiles`（5270） | alert | alert((await r.json().catch(() => ({}))).detail \|\| '上傳失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 197 | `uploadMaterialFiles`（5272） | alert | alert(body.message \|\| '已送出，待最高管理員審核後套用') | toast(ok) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 198 | `uploadMaterialFiles`（5280） | alert | alert('上傳失敗：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 199 | `deleteMaterialFile`（5285） | confirm | confirm('確定刪除此附件？') | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` |  |  |
| 200 | `deleteMaterialFile`（5292） | alert | alert((await r.json().catch(() => ({}))).detail \|\| '刪除失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 201 | `deleteMaterialFile`（5294） | alert | alert(body.message \|\| '已送出，待最高管理員審核後套用') | toast(ok) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 202 | `deleteMaterialFile`（5299） | alert | alert('刪除失敗：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 203 | `uploadMaterialInvoiceFiles`（5314） | alert | alert((await r.json().catch(() => ({}))).detail \|\| '上傳失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 204 | `uploadMaterialInvoiceFiles`（5316） | alert | alert(body.message \|\| '已送出，待最高管理員審核後套用') | toast(ok) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 205 | `uploadMaterialInvoiceFiles`（5324） | alert | alert('上傳失敗：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 206 | `deleteMaterialInvoiceFile`（5329） | confirm | confirm('確定刪除此發票附件？') | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` |  |  |
| 207 | `deleteMaterialInvoiceFile`（5336） | alert | alert((await r.json().catch(() => ({}))).detail \|\| '刪除失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 208 | `deleteMaterialInvoiceFile`（5338） | alert | alert(body.message \|\| '已送出，待最高管理員審核後套用') | toast(ok) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 209 | `deleteMaterialInvoiceFile`（5343） | alert | alert('刪除失敗：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 210 | `uploadDispatchFiles`（5357） | alert | alert((await r.json().catch(() => ({}))).detail \|\| '上傳失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 211 | `uploadDispatchFiles`（5361） | alert | alert('上傳失敗：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 212 | `deleteDispatchFile`（5366） | confirm | confirm('確定刪除此報價附件？') | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` |  |  |
| 213 | `deleteDispatchFile`（5372） | alert | alert((await r.json().catch(() => ({}))).detail \|\| '刪除失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 214 | `deleteDispatchFile`（5374） | alert | alert('刪除失敗：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 215 | `uploadDispatchInvoiceFiles`（5388） | alert | alert((await r.json().catch(() => ({}))).detail \|\| '上傳失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 216 | `uploadDispatchInvoiceFiles`（5392） | alert | alert('上傳失敗：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 217 | `deleteDispatchInvoiceFile`（5397） | confirm | confirm('確定刪除此廠商發票？') | confirm(danger) | `if (!(await MotrixUI.confirm(…, {danger: true}))) return` |  |  |
| 218 | `deleteDispatchInvoiceFile`（5403） | alert | alert((await r.json().catch(() => ({}))).detail \|\| '刪除失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 219 | `deleteDispatchInvoiceFile`（5405） | alert | alert('刪除失敗：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 229 | `acceptDispatch`（5538） | confirm | confirm(`確定驗收「${this._dispatchLabel(d)}」的工程？\n驗收後將記錄您的姓名與時間。`) | confirm | `if (!(await MotrixUI.confirm(…))) return` |  |  |
| 230 | `acceptDispatch`（5545） | alert | alert((await r.json()).detail \|\| '操作失敗') | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |
| 231 | `acceptDispatch`（5547） | alert | alert('網路錯誤：' + e.message) | toast(error) | 改 `MotrixUI.toast(…, {kind})`（不再阻塞；後面的 return 照舊） |  |  |

### 用 `page.on('dialog')` 的測試檔（31 個）實際觸發了什麼
實跑記錄（外掛記下每一個原生對話框的題、頁面、內容；87 passed）。**只有下面標「案件頁」的會被 P4 影響**；其餘是別頁的對話框或根本沒觸發（handler 只是保險）。
⚠️ 「沒有觸發」只代表**這次綠燈的路徑**上沒有；失敗路徑（例如存檔失敗的 alert）仍可能跳原生對話框——換成 `forbid_native_dialogs` 後這種情況會被斷言抓到，而不是被盲接吞掉。

| 測試檔 | 觸發的對話框 |
|---|---|
| `_ui_dialogs.py` | （helper 本身：`forbid_native_dialogs` 內部用 `page.on('dialog')`，不是要改的對象） |
| `test_case_close_checklist_2026_09_24.py` | 案件頁：alert「案件沒有存成功，已停止結案：尾款：已標記收款但未填入收款日期，請補填」 |
| `test_case_cross_module_links_2026_09_24.py` | （沒有觸發——handler 只是保險；P4 後換 `forbid_native_dialogs`） |
| `test_e2e_case_all_done_inline_2026_09_24.py` | （沒有觸發——handler 只是保險；P4 後換 `forbid_native_dialogs`） |
| `test_e2e_case_batch_ops_2026_09_24.py` | （沒有觸發——handler 只是保險；P4 後換 `forbid_native_dialogs`） |
| `test_e2e_case_color_semantics_2026_09_24.py` | （沒有觸發——handler 只是保險；P4 後換 `forbid_native_dialogs`） |
| `test_e2e_case_concurrent_edit_2026_09_24.py` | （沒有觸發——handler 只是保險；P4 後換 `forbid_native_dialogs`） |
| `test_e2e_case_data_loss_2026_09_24.py` | 案件頁：confirm「確定要刪除款項期別「訂金款」？」 |
| `test_e2e_case_header_and_payment_tab_2026_09_24.py` | 案件頁：confirm「表單尚未儲存，確定要關閉嗎？目前輸入的內容將會遺失。」 |
| `test_e2e_case_health_overview_2026_09_24.py` | （沒有觸發——handler 只是保險；P4 後換 `forbid_native_dialogs`） |
| `test_e2e_case_invoice_amounts_2026_09_24.py` | （沒有觸發——handler 只是保險；P4 後換 `forbid_native_dialogs`） |
| `test_e2e_case_list_paging_2026_09_24.py` | （沒有觸發——handler 只是保險；P4 後換 `forbid_native_dialogs`） |
| `test_e2e_case_list_quick_filters_2026_09_24.py` | （沒有觸發——handler 只是保險；P4 後換 `forbid_native_dialogs`） |
| `test_e2e_case_money_mask_2026_09_24.py` | （沒有觸發——handler 只是保險；P4 後換 `forbid_native_dialogs`） |
| `test_e2e_case_page_golden_2026_09_24.py` | 案件頁：confirm「表單尚未儲存，確定要關閉嗎？目前輸入的內容將會遺失。」 |
| `test_e2e_case_payment_number_input_2026_09_24.py` | （沒有觸發——handler 只是保險；P4 後換 `forbid_native_dialogs`） |
| `test_e2e_case_roles_select_2026_09_24.py` | （沒有觸發——handler 只是保險；P4 後換 `forbid_native_dialogs`） |
| `test_e2e_case_save_feedback_2026_09_24.py` | （沒有觸發——handler 只是保險；P4 後換 `forbid_native_dialogs`） |
| `test_e2e_case_save_mode_and_labels_2026_09_24.py` | （沒有觸發——handler 只是保險；P4 後換 `forbid_native_dialogs`） |
| `test_e2e_case_save_serialized_2026_09_24.py` | （沒有觸發——handler 只是保險；P4 後換 `forbid_native_dialogs`） |
| `test_e2e_case_select_late_response_2026_09_24.py` | （沒有觸發——handler 只是保險；P4 後換 `forbid_native_dialogs`） |
| `test_e2e_case_select_stale_subloads_2026_09_24.py` | （沒有觸發——handler 只是保險；P4 後換 `forbid_native_dialogs`） |
| `test_e2e_cashier_read_only_case_2026_09_24.py` | （沒有觸發——handler 只是保險；P4 後換 `forbid_native_dialogs`） |
| `test_e2e_copy_to_new_2026_09_10.py` | quotation-form.html：confirm「「來源客戶」在客戶管理中尚無資料，是否建立客戶檔案？」 |
| `test_e2e_extra_expenses_ui_2026_09_11.py` | 案件頁：confirm「確定送審這筆變更申請？」 |
| `test_e2e_playwright_2026_09_07.py` | quotation-form.html：confirm「確認簽核通過此報價單？」 |
| `test_e2e_quote_number_input_2026_09_24.py` | quotation-form.html：alert「有數字欄位無法辨識（標紅處），請修正後再存檔」<br>quotation-form.html：confirm「「解析客戶」在客戶管理中尚無資料，是否建立客戶檔案？」 |
| `test_e2e_received_installment_lock_2026_09_24.py` | 案件頁：confirm「確定要刪除款項期別「訂金款」？」 |
| `test_e2e_report_recognition_2026_09_24.py` | （沒有觸發——handler 只是保險；P4 後換 `forbid_native_dialogs`） |
| `test_e2e_t100_unconfirm_2026_09_10.py` | cashier.html：confirm「確認這 1 筆事件已經實際匯入 T100？確認後將自動從之後的匯出/預覽排除，避」<br>cashier.html：alert「已標記 1 筆事件為已匯入」<br>cashier.html：confirm「撤銷這筆的「已匯入 T100」標記？」 |
| `test_e2e_tax_type_select_2026_09_24.py` | quotation-form.html：alert「此報價使用已停用的稅率 3%，請在「稅別」改選應稅 5%、零稅率或免稅後再存檔」 |
