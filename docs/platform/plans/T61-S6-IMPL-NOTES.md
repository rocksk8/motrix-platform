# T61 S6 實作筆記：使用者自訂按鈕（供應商頁工具列先導）

> 分支 `wip/t61-s6-impl-r1`；設計 `T61-S6-ACTION-CATALOG-DESIGN.md`。旗標：設定中心「自訂按鈕」＝`builder_actions.enabled`，預設關閉。

## 規則（程式碼審查時要守）
1. **哪些匯出能變成按鈕**：同時滿足 ①模組在 `module.json` 的 `customization.pages[].exports` 登記；②方法是 `GET`、路徑是 `/api/` 底下的單純路徑（`[A-Za-z0-9_/.-]`，不含 `..`、`//`、`?`、`{}`、`#`）；③列在 `helpers.user_buttons.BUTTON_EXPORTS`（明確的允許清單，目前只有 `subcontract:roster`）。第③項是『明示同意』：登記匯出不代表可以變按鈕，未來若有會產生副作用的 GET 匯出，不會悄悄變成可放的按鈕。要加一個匯出＝改 `BUTTON_EXPORTS`（需要審查：該端點自己檢查權限、寫稽核、不改資料、沒有必填參數）。
2. 為什麼是允許清單而不是 `module.json` 的新鍵（例：`"button": true`）：`exports` 項目的鍵由 `core/customization.py` 驗證（未知鍵＝載入失敗），加鍵要動 L0；先導不動 L0。之後若核心層同意，把 `BUTTON_EXPORTS` 搬成 module.json 的 opt-in 鍵即可（行為相同）。
3. 檢視者可見性一律用 `core` 側欄選單同一套：`effective_modules(role, modules, user_id)`（含職責角色與財務角色規則）；匯出按鈕只在檢視者是最高管理者或有效模組清單含該匯出登記的 `perm` 時出現。預覽（以某帳號）用同一套，所以職責角色會被解析。顯示與否不是存取控制：匯出端點自己再驗一次。

## 沒做
瀏覽器實機驗證；角色層（只有公司層）；P9 動態點；module.json `button_slots`；治理比較函式（在 3e 的管線，見 PR 說明）。
