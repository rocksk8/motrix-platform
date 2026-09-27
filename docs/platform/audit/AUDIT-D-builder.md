# 稽核：模組建構器——輸出預覽（wip/a-builder-output be26ee3a）＋同頁拖放（wip/b-builder-dnd-4 f84fb2df，疊在前者上）（D，2026-09-27 23:52）

> 完整等級、讀碼優先。兩包基底都是 e21b099a。

## 0. 結論

- **必修 0、建議 1、觀察 2**。

## 1. 主持重點

| 項目 | D 的驗證 | 結果 |
|---|---|---|
| 預覽模式不打 API | `custom-records.html?preview=1` 在 `<head>` 最早設 `window.MOTRIX_PREVIEW`：① auth-guard／notif／sidebar 見旗標就不執行；② 本頁 api／post／put 拒絕；③ `fetch`（`defineProperty` 不可覆寫）、XHR、`sendBeacon`、WebSocket、EventSource 換成拒絕並記次 `__motrixPreviewBlocked`。題以 `page.on("request")` 量預覽 frame 的 `/api/` 請求＝0，並斷言計數＝0；直接開 `?preview=1`（未登入、不在 iframe）也不轉登入頁、不打 API | 成立 |
| sandbox 條件 | 輸出預覽 iframe：`sandbox="allow-same-origin"`（**不給 scripts**，放後端畫好的靜態 HTML）⇒ 有效。表單／列表預覽 iframe：`allow-scripts allow-same-origin` ⇒ 同源又可跑腳本，**sandbox 形同不存在**（可自行解除、可存取父頁與 localStorage 權杖）；程式註解自己寫明，並把真正防線放在預覽旗標——與 BUILDER-UX §3.3「sandbox 只是第二道」一致 | 成立（見觀察 BLD-O1） |
| 子頁收訊息 | `_onPreviewMessage` 檢查 `e.origin === location.origin` 且 `e.source === window.parent`、`type`／`v`；題驗非同源、格式不對、不是父頁送的都忽略 | 成立 |
| 草稿內容的 XSS 面 | 預覽頁同源可跑腳本 ⇒ 任何把草稿當 HTML 畫的地方都等於拿得到權杖。D 逐一查：執行頁沒有 `x-html`；說明欄 `x-text`；建構器 `x-html` 只用在 `typeIcon`（固定對照表、查不到回通用圖示）；縮圖 `innerHTML` 的名稱／key 都過 `esc()`（轉 `& < > "`，屬性用雙引號）。後端：D 探針以 `<script>`、`<img onerror>`、`<b>` 當欄位／模組／狀態名稱送 `preview_output` ⇒ 輸出裡都沒有原樣出現、有轉義 | 成立 |
| 輸出預覽與正式匯出同一個 renderer | 預覽 `preview_output` 與單據輸出都呼叫 `render_view`；題 `test_preview_equals_the_real_export_for_the_same_sample`（同一筆樣本 HTML 完全相同，預設與自訂版型各一）。突變 B1「預覽另包一層」⇒ **紅** | 成立 |
| 畫布與執行頁一致 | 題 `test_canvas_sections_and_fields_equal_what_the_runtime_form_draws`：同一份草稿，畫布的區塊與欄位順序、標籤逐項等於執行頁實際畫出的。突變 B3「畫布顯示 key 而非標籤」⇒ **紅** | 成立 |
| 改題的理由（D4 驗收照過） | `test_e2e_p8_module_builder` 只換操作路徑（第 3 步下拉指派 ⇒ 同畫布拖進區塊），結尾 `_assert_definition_v1()`（存下的定義與原題相同）**未改、仍呼叫** | 成立 |
| 半成品預覽 | 未完成欄位畫成佔位「〈名稱〉尚未完成」、清單放標頭（`json.dumps` 預設 ASCII 跳脫）；只讀、不寫庫（有題）；只有建構者可呼叫（有題）；各種半成品不 500（參數化題） | 成立 |
| CORE 暫用 1.57 | 建構器與品牌（653662a1）**都暫用 1.57**、origin 是 1.56 ⇒ 依 §C-7，先合回的取 1.57，後合的 rebase 時跑 `core_bump` 取 1.58，並重產 CHANGELOG 與 L1 介面快照 | 上車時處理 |
| 其餘題 | 說明欄、靜態守門、拖放 e2e、輸出預覽 e2e、D4 驗收題：25 過；輸出預覽後端題 32 過 | 成立 |

## 2. 發現

**BLD-S1（建議）　縱深防護中「共用腳本見旗標不執行」這一層沒有題**
- 突變 B2「拿掉 `notif.js` 的 `if (window.MOTRIX_PREVIEW) return`」⇒ **存活**：通知腳本啟動時只包裝 `fetch`，真正發請求要等之後的輪詢，題目觀察的時間內沒有觸發；就算發了，第三道（不可覆寫的 `fetch`）仍會擋下。
- 不影響安全結論，但這一層退化了不會有人知道。建議題目加一個「觸發通知輪詢（或直接呼叫其啟動函式）後，`__motrixPreviewBlocked` 仍為 0」的斷言。

**觀察**
- **BLD-O1**：表單／列表預覽 iframe 的 sandbox 在同源＋可跑腳本下沒有防護作用，安全完全依賴預覽旗標與「草稿不當 HTML 畫」。之後任何人在執行頁加 `x-html` 或 `innerHTML` 畫草稿內容，就會變成可取得權杖的 XSS。建議把「custom-records.html 不准 `x-html`」寫成守門（本次 D 以 grep 確認現況為 0）。
- **BLD-O2**：預覽端點的兜底 `except Exception` ⇒ 422，回應只帶例外型別、log 記 ERROR（方向對，不外洩草稿內容）；代價是真正的程式錯誤也會被包成 422，要靠 log 發現。
