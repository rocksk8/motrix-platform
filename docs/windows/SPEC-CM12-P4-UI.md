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
- 深色模式：元素掛在 `body` 直下，走 style.css 對 body 直下元素的反轉濾鏡（與各頁 Modal 同路）；不另外判斷 `data-theme`。

## ⚠️ 替換時的語意差異（套進案件頁時要逐處判斷）
- 原生 `confirm()`／`prompt()` 是**同步**的，`MotrixUI` 是 `async`：呼叫端要改成 `if (!(await MotrixUI.confirm(...))) return`，**所在函式要變 async**，而呼叫它的地方若依賴回傳值也要跟著 await。
- 原生 `alert()` 會停住程式直到使用者按確定；`toast()` 不會。錯誤訊息若後面緊接著「放棄這次操作」的流程，改 `toast(…, {kind:'error'})` 行為等價；若 alert 是在等使用者讀完才繼續（少見），改 `await MotrixUI.confirm(msg, {cancelText: …})` 或保留。
- 現況（origin/master，CM12 凍結前）：`case-management.js` 約 `alert(` 170、`confirm(` 54、`prompt(` 11 處；`backend/tests` 有 29 個檔用 `page.on('dialog')`。

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
`backend/tests/test_e2e_ui_dialogs_2026_09_24.py`（7 支，`set_content` 最小測試頁，不動產品頁）：確認的鍵盤／點擊／背景、危險確認初始焦點、輸入框的值／取消／必填、焦點鎖與還原、排隊＋helper、toast／banner（含 HTML 注入當文字）、深色模式反轉。突變 8 處皆紅。
