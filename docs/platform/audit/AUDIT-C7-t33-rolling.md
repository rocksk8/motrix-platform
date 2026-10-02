# 第 33 班滾動稽核（c7）— 每片一節；發現當場回作者

## wip/t33-nowindow-d7 @bcb6e827（建包／測試工具鏈無視窗）— PASS，2 項建議、2 項觀察
讀碼＋探針（作者測試 9／9 不重跑）。
- **S-1（建議）23 支 `tools/platform/*.py` 的 `sys.path.insert(… parents[1] / "tools" / "platform")` 路徑是錯的**（解析成 `<root>/tools/tools/platform`，不存在；只有 `backend/tools/build_test_reuse.py` 的 `parents[2]` 正確）。目前能動只因為「以腳本執行」時 `sys.path[0]` 就是腳本所在目錄；改以 `python -m`、`runpy`、被別支 import 後走 `__main__` 時 `import nowindow` 失敗 ⇒ `except ImportError: pass` **靜默略過**，視窗又跳出來，而守門仍綠。建議 `parents[0]`（或直接不加路徑）。
- **S-2（建議）守門 `test_no_window_guard` 只比對字串**（`"nowindow" in src and ".install()" in src`）：註解提到、裝在從不被呼叫的函式裡、`from subprocess import run`、`import subprocess as sp`、`os.system` 五種形式探針全部放行（`verdict()`＝False）。現有檔案沒有這些形式（已掃），所以是守門的洞、不是現行缺陷。建議以 AST 檢查「模組層或 `if __name__` 底下真的呼叫 `nowindow.install()`」並涵蓋別名。
- O-1　`install()` 換掉 `Popen.__init__`：呼叫端以**位置參數**傳 startupinfo／creationflags ⇒ `TypeError: got multiple values for argument 'creationflags'`（實測）；呼叫端傳入的 `STARTUPINFO` 物件會被就地改寫（實測 flags 被改）。現行呼叫點都用關鍵字，僅供留意。
- O-2　`startup.run_edge_pdf` 是**產品程式**的行為變更（一律 `CREATE_NO_WINDOW`）；Edge headless 列印不受影響，作者測試已更新；屬合理。
## wip/t33-remit-s0-a3 @b2f311a1（31-B S0 匯款款別設定）— PASS，0 發現
`test_probe_t33_remit_s0_c7.py` 31／31：發布後移除／改代碼 ⇒ 422、停用可；**還原舊版若會讓已發布代碼消失 ⇒ 422（無繞過）**；草稿較新時 `current()` 仍回已發布版；24 種壞 body（stages 型別／重複／取消、active 型別、名稱長度、代碼格式／型別、sort 型別、note 長度、重複代碼、非物件、空）一律 422 不 500；>30 款別、非物件 body；key≠default 被拒；權限矩陣（superadmin 200/200、admin 200/403、sales 403/403、未登入 401/403、非 superadmin 不可存草稿／發布）；出貨預設四款與版本 0；停用款別離開下拉但設定頁仍在；`kind_allowed_at` 邊界。前端新檔無 `x-html`／`innerHTML`。
- 觀察：該分支基於 745f3c2d，**不含 52033606 的 M-1 修正**（`material_payment_cashier.py` 與其測試 diff 顯示為回退）；合入 platform 請以三方合併／rebase，不要以該分支內容覆蓋。
