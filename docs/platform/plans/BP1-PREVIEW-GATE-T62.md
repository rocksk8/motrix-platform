# T62：版面／選單發布前預覽把關（可逐項選擇強制）

> 日期：2026-10-14　作者：hichan-3e（受 hichan-b4 指派）　測試已寫、未跑（機器由 02 使用）；只做靜態檢查與 node 小驗證。

## 管理者出貨後可以設定什麼
設定中心「建構器治理」多四個開關（預設全 0）：**版面（含選單）／自訂欄位／自訂按鈕／輸出版型 發布前強制先看過影響預覽**。
- 開啟＝該類定義發布時，必須帶「看過的預覽雜湊」（同一位使用者、同一份草稿），否則 409（`preview_required`／`preview_stale`），沒有例外。
- 四個 `enforce_*` 獨立於總開關：開了之後即使把 `builder_governance.enabled` 關掉也**仍然強制**（預覽路由對已強制的 kind 仍可用）；要解除只能關 `enforce_*`（loosen＝確認期間＋第二位核准）。內建三個 kind（費用單據類型／匯款款別／自訂模組）仍跟著總開關走（T60 S1 既有行為；關總開關＝停止強制，只留設定變更稽核）——這是已知且明說的缺口。
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

## 3c 審查後的修正（r1 之後的新提交）
- A 還原也把關：`POST …/restore/{version}` 在強制範圍內需帶 `preview_hash`＝`v<版本>:<內容戳>`，由 `GET /api/def-governance/{kind}/{key}/impact?version=N` 取得並留『看過』稽核（沿用同一個把關函式，已發布版本不可變）。面板與三個編輯器已送；`layout-editor.js` 的還原（3c）仍需另行接，否則開啟 `enforce_layout` 後版面還原會 409。
- B 發布以預覽戳進寫鎖：強制範圍內且呼叫端沒給 `base_etag` 時，以 `preview_hash` 當 `base_etag` ⇒ 閘門與發布之間草稿被改 ⇒ `D.publish` 丟 DraftConflict（409，`code=draft_conflict`）。
- C 讀不到設定不再放行：可能被強制的 kind（內建名單＋選項名單）若讀 `builder_governance` 失敗 ⇒ 503＋日誌，擋下發布與還原；其他 kind 完全不讀設定（與今天相同）。
- D 四個 `enforce_*` 是 `loosen="down"`：關閉強制走確認期間＋第二位最高管理者核准，等待期間仍強制。**取捨**：緊急回退不能靠關這四項即時生效；整體即時回退仍是關 `builder_governance.enabled`（它沒有加 loosen，維持 t59 行為）。
- 回應碼：`preview_required`／`preview_stale` 與 `draft_conflict` 同為 409，用戶端依 `code` 分辨。

## 04 靜態審查後的第二輪修正
- C（真修）：把關改用**嚴格讀取** `_strict_setting`（直接查定義表＋到時的待生效值；資料庫錯誤、格式不對、值不是 0／1 ⇒ 503，不再經 `settings_registry.get` 的『永不丟例外、回預設』）；`MOTRIX_SETTINGS_DEFAULTS_ONLY=1` 不影響把關。測試改成讓資料庫讀取失敗（不是換掉包裝函式）。
- B：強制範圍內**一律**以 `preview_hash` 當寫鎖內比對的 `base_etag`；呼叫端另帶不同的 `base_etag` ⇒ 409 `draft_conflict`。
- D：不替總開關加 loosen（會拖慢 t59 的即時回退）；改成讓 `enforce_*` 獨立於總開關（上節），關總開關繞不過它；內建三個 kind 的缺口明寫。
- LOW：還原預覽的戳改成 `v<版本>@live<生效版>:<內容戳>`，預覽之後又發布過別版 ⇒ 戳對不上 ⇒ `preview_stale`。

## 已知缺口
1. 版面／欄位／按鈕／版型的編輯器除選單外都尚未送雜湊（上節）。
2. 選單編輯器的「看過」＝整份選單預覽＋自動影響預覽；使用者不一定逐模組讀過影響預覽內容。
3. 共用生成物（response_keys／route_inventory／l1 快照）未動；本切片沒有新路由。
4. 測試沒跑：`tests/test_t62_preview_gate_optin_2026_10_14.py`（7 題）。
