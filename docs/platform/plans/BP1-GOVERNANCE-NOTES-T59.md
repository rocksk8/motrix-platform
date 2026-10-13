# BP-1 定義治理切片（t59）筆記

旗標 `builder_governance.enabled`（預設 0＝關）。關閉時三條 `GET /api/def-governance/{kind}/{key}/{ledger|diff|impact}` 對最高管理者一律 404、畫面不出現任何入口；開啟後只多出檢視與預覽，發布與還原本身的行為完全不變。不改資料庫結構，只讀既有 `ui_definitions`。

- 版本帳本：每一版的誰／何時／備註，標出生效版與可還原版；任兩版（或 live／draft／default）逐欄差異。
- 發布前影響預覽：草稿對生效版的差異、現行驗證器的結果、同一定義在其他範圍（公司／角色）的版本、宣告的影響範圍；自訂模組另列「凍結在生效版的單據數」。預覽只多一筆稽核 `definitions.previewed`（不記內容）。
- 畫面：`frontend/js/def-governance.js`（獨立面板，`MotrixDefGovernance.available／open／preview`）。已接上：費用單據類型編輯頁（`expense-types.html`，發布鈕旁）、模組建構器發布步驟（`#mb-gov-impact`／`#mb-gov-ledger`）。沒有真正「通用」的定義編輯頁；第三個接上的是同樣建在定義文件庫上的匯款款別設定頁（`remit-kinds-settings.html`，`rk-gov-*`）。兩處都用唯讀面板（`readonly: true`），還原仍走各編輯器自己的流程。排版器（`layout-editor.js`）由其他列車負責，只需在發布步驟呼叫 `preview()`。

## 已知缺口（誠實版）

1. `previewHash`（草稿內容戳）會回傳，但發布端點**不要求**帶回它；「發布前一定要看過預覽」目前沒有被強制，只是提供入口。強制需要改發布端點，留給單一發布管線（架構筆記 §3.9）。
2. 還原到較寬鬆的版本**沒有**放寬把關：設定中心的「放寬→待生效→第二位核准」只存在於設定值（`SettingDef.loosen`），版面／輸出版型／欄位／模組定義沒有可比較的放寬判斷，這裡不自創。改做兩件事：帳本回傳 `warnings`（明說「不判斷寬鬆或嚴格，請先比較差異」，面板一律顯示），以及每個可還原版本的 `validNow`（舊版在**現行驗證器**下是否仍合法；不合法就不給還原按鈕、說明原因）。真正的還原端點本來就在發布前用現行驗證器再驗一次（不過＝422、不產生新版本，有測試）。完整的放寬把關屬單一發布管線（架構筆記 §3.9）。
3. `frozenRecords` 只有自訂模組（公司範圍）有數字；其他種類回 `null`＝不適用（不是 0），因為只有自訂模組會在單據上凍結定義版本。
4. 前端沒有真瀏覽器或 e2e。證據是 `tests/test_def_governance_ui_2026_10_14.py`（node 直接執行 `def-governance.js` 與兩個編輯器的零件）：探測在 404／401／403 為關、400／200 為開；未呼叫 `open` 前什麼都不渲染；帳本／差異（內容轉義）／影響預覽渲染；唯讀面板沒有還原；現行驗證不過的舊版沒有還原按鈕；還原要兩段確認、確認後才以正確的版本與範圍呼叫既有還原路由（含失敗訊息）；兩個編輯器的入口預設 `govOn=false`、`openGov` 帶正確參數、入口按鈕都由 `x-show="govOn"` 把關。反向控制：把兩段確認或驗證把關拿掉，對應測試轉紅。三個入口的 DOM id 以讀碼確認。
5. 「快照表＋不可變觸發器＋保留政策」（架構筆記 §3.8）沒有做：已發布版本本來就不可變，真正新的資料（疊加層、進行中單據指標）在這一刀還不存在；等疊加層落地再加。

## T60 待辦（下一列車）

- **版面 `hide` 等操作的目標 id 對非最高管理者外露**：`GET /api/platform/menu` 的 `layout.skipped/applied/dropped` 帶原始操作文字，針對受限使用者看不到的側欄項目的操作會洩漏該項目的目標 id。此問題早於 BP-1，旗標全關時今天就存在，**本列車依「關閉＝逐位元不變」不改**；1f 的 886a86ad7 只在選單旗標開啟時遮蔽原始操作文字與新名稱。下一列車對非最高管理者一律遮蔽，不論旗標（計畫見 `BP1-NEXT-TRAIN-T60.md` S0，需使用者同意 D8）。
- `GET /api/def-governance/{kind}/{key}/diff` 預設 b=draft，沒有草稿時仍回 400（狀態碼不變），但訊息已改為白話「目前沒有草稿…」。

## T60 S0／S1（wip/t60-s0s1-r1）

- **S0（D8）**：`GET /api/platform/menu` 對非最高管理者一律遮蔽 `layout.applied／skipped／dropped` 的操作原文（只剩操作種類與理由），**不再看旗標**；前端沒有任何地方讀這三個欄位。最高管理者照舊拿原文。測試 `test_t60_s0_menu_redact_2026_10_14.py`（含反向控制：把遮蔽函式換回原樣回傳，兩次回應除了這三個欄位完全相同）。
- **S1（D4）**：旗標 `builder_governance.enabled` 開啟時，`POST /api/definitions/{kind}/{key}/publish` 對名單內的 kind（`expense_type`、`remit_kinds`、`custom_module`，即 `routers/definitions.py` 的 `_PREVIEW_ENFORCED_KINDS`）必須帶 `preview_hash`＝目前草稿戳，且稽核裡要有這位使用者對這個戳的 `definitions.previewed`（別人的預覽不算、只知道戳不算）；否則 409 `preview_required`／`preview_stale`，沒有繞過。旗標關、不在名單的 kind、沒有草稿 ⇒ 與今天逐字相同。三個編輯器（費用類型、匯款款別、模組建構器）旗標開時先開「審閱」面板（`MotrixDefGovernance.review()`），確認才發布。
- **還沒涵蓋**：排版器（`layout-editor.js`，3c）與選單建構器（發布走 layout 定義）尚未送 `preview_hash`，所以 `layout`／`output_template`／`custom_fields` 還不在名單；它們接上之後把 kind 加進 `_PREVIEW_ENFORCED_KINDS`。在那之前，這些種類仍只有前端強制（選單建構器）或沒有強制。

## T60 S0b（hichan-04 對 t59 的稽核，wip/t60-s0s1-r1）

- (a) `GET /api/layout/{module}` 對非最高管理者不再帶側欄操作（`ops`／`dropped` 裡 target 以 `/sidebar` 結尾的）：這些只有 `/api/platform/menu` 在用，頁面引擎不需要。`points`（模組宣告的可自訂點）不動——它與公開的選單宣告同一份。最高管理者照舊。
- (b) 含 `hub` 項的群組（目前是 `system`）不能當 `move.to` 的目的地：執行期 `core.menu._group_dest`（略過並列在 skipped）、發布驗證 `core.customization._check_sidebar_group_dest`（可選清單不含它）、`menu-editor.js` 的下拉（只有項目本來就在裡面時才保留現值）。新增 `core.menu.hub_group_keys()`。
- (c) `impact` 說明文字已改成與 S1 一致：開啟旗標後，費用單據類型／匯款款別／自訂模組的發布由伺服端要求「看過的」雜湊；其他種類仍不強制。
- (d) 注意：選單整份預覽（`POST /api/platform/menu/preview`）是在伺服端算的，**早於**瀏覽器端 sidebar.js 的 hub 收合（`_collapseHub`）；所以預覽裡 hub 群組顯示的是展開的項目，實際導覽列會收成單一連結。因此現在也不讓項目搬進 hub 群組。

