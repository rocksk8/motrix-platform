# 附近旅宿 更新紀錄

## 1.1.1 — 2026-09-28 19:40（第十八班 e2e 偶發紅：產品競態）
- 修正：覆蓋層查詢回應先到、地圖還沒建好（開頁自動開圖在高負載下慢）時，原本直接畫標記丟例外、被當成「連線不到伺服器」、清單也不出現 ⇒ 改為清單、訊息、顯名先出，標記經 `onBasemapReady` 在地圖就緒後補畫（只畫最後一次查詢）；非網路例外照實顯示原因
- 題：決定性重現（先收地圖再查）＋e2e 失敗時存截圖與搜尋回應紀錄

## 1.1.0 — 2026-09-28 17:57（E 線 E2 L1 接點段）
- 新增：地圖覆蓋層 `pages/lodging-overlay.js`（`module.json` `map_overlays`；只經 L1 `MotrixMapOverlay` 契約）；回應底圖與頁面不一致 ⇒ 不畫、請重新整理（LG3-S1）
- 修改：地址定位包在 L1 `geo.map_request_scope(頁面底圖, missing="osm")` 內（LG2-M1），查詢帶 `basemap`、回應帶實際 `basemap`；T1 表改由 archive 依宣告自動備份
- 修正（D 稽核 E2-S1／S2）：下載加整次總時限 180 秒；CSV 匯出儲存格以 = + - @ 開頭者前加 '

## 1.0.0 — 2026-09-28 17:12（E 線 E2 第一、二段；設計見 docs/platform/LODGING-NEARBY.md）
- 新增：模組骨架、migration 1（四張表）、觀光署資料下載與整批匯入（開關 `MOTRIX_LODGING_FETCH`、24 小時速率、失敗冷卻、單一執行）、zip 防護（檔名白名單、zip slip、解壓上限）、`GET /api/lodging/status`、`POST /api/lodging/refresh`、顯名文字
- 新增：`POST /api/lodging/search`（只查本機快照、直線距離、類別與半徑、錯值價格標記）、查詢紀錄（建立／清單／明細／刪除，建立者＋admin+ 可見）、CSV／JSON 匯出（帶顯名）、兩筆紀錄比較（官方登記未變動）、人工詢價
- 新增：頁面 `lodging-records.html`（側欄「附近旅宿紀錄」、權限 key `lodging`）：資料狀態與更新、紀錄清單／明細／刪除、比較、匯出、列印、新增詢價；顯名在清單、明細、比較都顯示
- 中心點來源是 Google ⇒ 紀錄不存座標與距離（LG-M2）；過渡期地址定位一律不用 Google（1.1.0 改為 L1 `geo.map_request_scope`）
