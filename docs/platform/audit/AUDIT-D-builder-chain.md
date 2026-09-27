# 稽核：建構器鏈 a-builder-sink-guard 8fd09efb（含 dnd-5 d26a7b0c、output be26ee3a）（D，2026-09-28）

> 範圍：D 上一次審到 f84fb2df（必修 0），本次只看差異 `f84fb2df..8fd09efb`：6 檔，**只有題目、版本紀錄、BUILDER-UX，沒有產品程式**。
> 第一輪 A：AUDIT-A-B42-B43（d0158060）。品牌 h-branding ec48a245 先前已審過（必修 0），本次不重審。
> 非 e2e 題在拋棄式 worktree 跑：8 過。e2e 兩個新題（notif 讓位、favicon 豁免）會起 live_server，**沒有跑**，只讀碼。

## 0. 結論

- **必修 0、建議 1、觀察 3。**
- notif 讓位題、x-html 守門、JS 寫入點守門（AB42-S1）、favicon 豁免（使用者裁示「只排除 `GET /api/system/branding/favicon`」）都成立：
  - `counts_as_api` 以「方法＋路徑完全相同」判定，查詢字串不看；另外 6 個相近的請求都照算（有題）
  - 正對照用非 fetch 的 Image 載入：favicon 不算、`/api/system/branding` 照算，而且先確認兩個請求都真的發出
- A 列的 AB42-C1（版號 2026-09-28a 與 A34 撞號）是列車處理的事項，不是缺陷

## 1. 建議

**BS1　JS 寫入點守門只掃 custom-records.html；建構器頁載入的 form-preview.js 也畫使用者草稿，卻沒有被守門掃到**
- 事實：`frontend/static/form-preview.js` 有三處寫入點：
  - :150 `iframe.srcdoc = html`：輸出預覽，iframe sandbox 只給 `allow-same-origin`（:103），不跑腳本
  - :298 `el.innerHTML = fn(...)`：步驟縮圖 SVG，使用者字串一律經 `esc`（:177，轉義 & < > "）
  - :300 `el.innerHTML = ''`
- 讀碼判定：三處現在都安全，但守門看不到它們。建構器是管理員互相可見的草稿，這一檔出一次疏失，就是管理員之間的儲存型 XSS
- 建議：`sink_sites`／`check` 的掃描對象加上 form-preview.js（與 custom-layout.js，目前 0 處），白名單照同一個格式登記；上限按檔分開計

## 2. 觀察

- **BO1**：守門偵測的是「不小心寫出來」的形狀，不防刻意繞過。探針在真頁面植入以下寫法，**都不會亮**：
  - `el['innerHTML'] = s`
  - `Object.assign(el, {innerHTML: s})`
  - `document` 換行接 `.write(s)`
  - `setHTMLUnsafe`、`createContextualFragment`

  後兩個是瀏覽器正式 API，加進 `SINK_KINDS` 的成本低，建議順手補上。
- **BO2**：白名單以「種類＋所在方法」為鍵 ⇒ 在 `openOutput` 裡再加第二處 `document.write` 不會亮（換成別的種類會亮，探針確認）。可以接受，記錄備查。
- **BO3**：e2e 的 notif 讓位題與 favicon 題本次沒有跑，依 A 的讀碼與題目本身的正對照設計判定成立；列車全量時會跑到。

## 3. 重現

```
git worktree add --detach D:\MOTRIX-PLATFORM-D14m 8fd09efb
cd D:\MOTRIX-PLATFORM-D14m\backend
D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe -m pytest tests/test_custom_records_no_js_html_sink_2026_09_28.py tests/test_custom_records_no_x_html_2026_09_28.py "tests/test_e2e_builder_preview_2026_09_27.py::test_counts_as_api_exempts_exactly_one_request" -q
# BO1 探針：import 該題模組，把寫法植入 openOutput 前的新方法，跑 check(sink_sites(...))
```
