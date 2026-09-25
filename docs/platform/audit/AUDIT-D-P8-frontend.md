# 稽核：P8 前端——模組建構器 6 步與自訂模組執行頁（合回前稽核）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。**合回前稽核**。
> 對象：`origin/wip/h-p8-frontend` `ece37cf1`（基底 C 的 `89383bb4`），主持的前端 5 個 commit：`a7b9ee50`、`be8b5dd4`、`dc402f71`、`b85e1e12`、`ece37cf1`。C 的後端另見 `AUDIT-D-C-P4P5P8.md`。
> 稽核時（02:10）分支仍在 `ece37cf1`。主持說有子代理正在 rebase 並接上 #1／#2；**本檔的結論對應 `ece37cf1`**，rebase 之後由 D 在回覆欄確認差異。
> 分級：**必修**／**建議**／**觀察**。關閉規則：被稽核者回覆後，由 D 確認才關。
> 縮寫：`MB`＝`frontend/pages/module-builder.html`、`CR`＝`frontend/pages/custom-records.html`、`E2E`＝`backend/tests/test_e2e_p8_module_builder_2026_09_26.py`。

## 0. 結論

- 主持指定的三個重點：
  1. **斷言是否打在伺服器狀態**：✅ 是。定義看 `ui_definitions`，單據看 `custom_records`（含 `data`、`approval`、`def_version`），通知看 `notifications`，輸出看 `/output` 端點的 HTML 與 PDF 檔頭。畫面文字只有 `#cr-record-version` 兩處（E2E:390、395），而且前一行已經有同一件事的 DB 斷言（E2E:389）。
  2. **有沒有 sleep**：✅ E2E 沒有。等待點都是動作的終點狀態：
     - 存檔：`#mb-save-state` 的 `data-state=saved`，而且 dirty、saving 都是 0。MB 只在伺服器回 200、存檔期間內容也沒變時才標 saved（MB:872-876）。
     - 單據：`#cr-record[data-busy="0"]`、`data-status`。
     - 公式與條件：`data-state=ok／bad`，來自伺服器的 `/formula/check`。
  3. **Alpine 布林下拉**：✅ 必填、終點、只限申請人用 `x-model.boolean`＋寫死 value；通知申請人、有無簽核、預設值用 `:value`＋`@change` 明確轉型。D 突變 F01～F04（拿掉 `.boolean` 或改存字串）**都轉紅，而且轉紅的原因正確**（`'true' is True`、`{'requester': 'true'}`）。Alpine 3.17.1 的 `.boolean` 把 `""` 轉成 `null`（D 讀 vendor 原始碼確認），所以「（未選）」不會變成 false。
- **必修 0 項**。建議 2 項、觀察 3 項。
- 基準：E2E 2 題 **2 passed**（47.6 秒，單程序、低優先權）。

## 1. 突變（D 自做；每項都用 `git checkout` 還原並核對內容）

| 突變 | 結果 | 失敗訊息 |
|---|---|---|
| F01 必填下拉拿掉 `.boolean`（MB `#mb-f-required`） | 🔴 | `assert ('true' is True)` |
| F02 終點下拉拿掉 `.boolean` | 🔴 | 定義裡的 `final` 是字串 |
| F03 只限申請人拿掉 `.boolean` | 🔴 | `requester_only` 是字串 |
| F04 通知申請人存 `$event.target.value`（字串） | 🔴 | `{'requester': 'true'} == {'requester': True}` |
| F05 執行頁 checkbox 欄位拿掉 `.boolean`（CR） | 🟢 **存活** | —（P8F-S1） |

## 2. 發現

### 建議

- **P8F-S1　執行頁的布林欄位（checkbox）沒有任何題目**：CR:158-164 的寫法是對的（`x-model.boolean`，「（未選）」＝`null`），但 E2E 的設備借用單沒有 checkbox 欄位，拿掉 `.boolean` 照樣綠（F05）。這是記憶〈Alpine `:value="false"` 布林下拉〉的原型：存「否」回 200、畫面說已儲存，而 DB 裡是字串 `"false"`（truthy）。〔補充 2026-09-26 02:46，D 審 C 時查明〕後端 `custom_fields._coerce` 只收布林（`"false"` ⇒ 400「必須是勾選」），所以漏掉 `.boolean` 的後果是**存檔被拒**，不是靜默存錯；前端這一側仍然要有題目守。建議在 E2E 或一支小的 e2e 補一個 checkbox 欄位，驗三件事：存「否」後 DB 是 `false`（不是 `"false"`）、重新開單畫面顯示「否」、再存一次仍然是 `false`。
- **P8F-S2　`flushSave` 以 100 ms 輪詢等存檔完成**：MB:882-892。這是產品碼不是測試，也有 `error` 出口，但有兩點：
  - 迴圈沒有上限：伺服器一直回成功、使用者又一直在打字時，發布按鈕會一直等。
  - 等待條件是「沒有 dirty」而不是「這一次存檔的回應」。

  建議改成等「目前進行中的那一次存檔」的 Promise，並加上次數上限（例如 50 次 ⇒ 顯示「存檔一直沒有完成」）。

### 觀察

- **P8F-O1　E2E 的「直接寫 DB 授權」繞道**：`make_user(..., modules=["custom.equipment_loan"])`（E2E:289）。依主持指示列為觀察；C 的 `d4fdefc2`（#1 動態權限 key）已經在 origin，rebase 之後應改成走「使用者管理」頁授權。D 會在回覆欄確認。
- **P8F-O2　自訂模組的選單是「先渲染、再非同步疊加」**：`custom-modules-nav.js` 在 `sidebar.js` 渲染之後才去抓 `/api/custom-modules`，再插入項目（〈先渲染再非同步載入＝競態〉）。RUN-PLAN 01:26 的 C4 裁示已排定由 `window.MOTRIX_MENU` 同步取代、讓這支檔案退場，所以這裡只記錄；E2E:302 等的是「連結出現」（`state="attached"`），在切換之前是合理的等待點。
- **P8F-O3　`#cr-record-version` 的畫面斷言**：E2E:390、395 讀的是畫面文字。E2E:389 已經有 DB 斷言，所以不是假綠燈。另外，E2E:379 用 `"數量" in old_html and "借用數量" not in old_html` 判斷舊版輸出；「借用數量」本身就包含「數量」，第一個條件幾乎一定成立，真正在驗的是第二個條件。

## 3. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | D 確認 |
|---|---|---|---|
| P8F-S1 | 修正：新題 `test_checkbox_field_saves_a_real_boolean`——存「否」DB 是 `False`、重開單下拉顯示 false、再存仍 `False`；改「是」＝`True`；「（未選）」＝`None`。突變 F05（拿掉 `.boolean`）🔴（字串被後端擋下，單據建不出來） | 82258a0a | |
| P8F-S2 | 修正：`saveDraft` 回傳「這一次存檔」的 Promise（`_inflight`），`flushSave` 改等它（不輪詢）；上限 `flushLimitMs`＝10 秒，逾時標 `saveState=error`＋`#mb-error` 說明；發布、還原都檢查結果，失敗就不送出。新題 `test_publish_waits_for_the_draft_save_with_a_limit`（攔住草稿 PUT ⇒ 發布結束、畫面標錯、DB 沒有發布版）。突變「拿掉上限」🔴 | 82258a0a | |
| P8F-O1～O3 | O1 修正：授權改由超級管理員在 users.html 勾選（PUT /api/users），斷言打 `users.modules`；突變「權限目錄不認動態 key」🔴。O2 照裁示維持（C4 退場）。O3 修正：輸出改抽 meta 區每列標籤、與 DB 的 v1／v2 標籤精確比對 | 82258a0a | |
