# T62：版面／選單發布前預覽把關（可逐項選擇強制）

> 日期：2026-10-14　作者：hichan-3e（受 hichan-b4 指派）　測試已寫、未跑（機器由 02 使用）；只做靜態檢查與 node 小驗證。

## 管理者出貨後可以設定什麼
設定中心「建構器治理」多四個開關（預設全 0）：**版面（含選單）／自訂欄位／自訂按鈕／輸出版型 發布前強制先看過影響預覽**。
- 開啟＝該類定義發布時，必須帶「看過的預覽雜湊」（同一位使用者、同一份草稿），否則 409（`preview_required`／`preview_stale`），沒有例外。
- 前提：`builder_governance.enabled=1`；它關著時四個開關都不作用。
- 選單編輯器：發布前自動把每個模組剛存的版面草稿送去影響預覽並帶回雜湊（使用者已在編輯器內看過整份選單預覽，且草稿一改就必須重預覽）。

## 為何做成逐項開關
版面編輯器（`layout-editor.js`，3c 專屬）、欄位／按鈕／版型編輯器尚未送雜湊。直接把 kind 放進強制名單會讓它們無法發布。逐項開關讓編輯器接上之後再由管理者開啟，不用改程式。
**未接上就開啟會鎖住該類發布**（訊息清楚、可隨時關閉）——設定說明已寫明。

## 旗標關＝不變的證據
- `_preview_gate`：治理旗標關或 kind 不在（內建名單 ∪ 已開啟的選項）⇒ 回 None，與過去同一條路徑；既有 S1 測試不變（`layout`/`custom_fields` 仍不在內建名單）。
- 四個設定欄位預設 0；凍結基準以文字插入。
- 前端：`menu-editor.js` 只在選單建構器本身已開啟的畫面動作；治理關時多一次 `GET /api/def-governance/layout/.../impact`（404，被吞掉），發布請求本體不帶 `preview_hash`，與過去逐位元相同。DOM 沒有任何新增或樣式改動（沒有使用 x-show／內嵌 display）。

## 交給 3c（layout-editor.js，我不改）
發布前加三行（旗標關時 `available` 為 false，不影響）：
```js
var pub = { note: note, base_etag: etag }
if (window.MotrixDefGovernance && await MotrixDefGovernance.available('layout')) {
  var pvh = await MotrixDefGovernance.review({ kind: 'layout', key: 'module:' + moduleKey, scope: 'company', title: '發布前影響預覽：版面' })
  if (!pvh) return; pub.preview_hash = pvh
}
```
自訂欄位、按鈕、版型編輯器同樣。接上並驗證後才在正式機開對應的 `enforce_*`。

## 已知缺口
1. 版面／欄位／按鈕／版型的編輯器除選單外都尚未送雜湊（上節）。
2. 選單編輯器的「看過」＝整份選單預覽＋自動影響預覽；使用者不一定逐模組讀過影響預覽內容。
3. 共用生成物（response_keys／route_inventory／l1 快照）未動；本切片沒有新路由。
4. 測試沒跑：`tests/test_t62_preview_gate_optin_2026_10_14.py`（7 題）。
