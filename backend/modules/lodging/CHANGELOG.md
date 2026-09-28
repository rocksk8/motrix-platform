# 附近旅宿 更新紀錄

## 1.0.0 — 2026-09-28 17:12（E 線 E2 第一、二段；設計見 docs/platform/LODGING-NEARBY.md）
- 新增：模組骨架、migration 1（四張表）、觀光署資料下載與整批匯入（開關 `MOTRIX_LODGING_FETCH`、24 小時速率、失敗冷卻、單一執行）、zip 防護（檔名白名單、zip slip、解壓上限）、`GET /api/lodging/status`、`POST /api/lodging/refresh`、顯名文字
- 新增：`POST /api/lodging/search`（只查本機快照、直線距離、類別與半徑、錯值價格標記）、查詢紀錄（建立／清單／明細／刪除，建立者＋admin+ 可見）、CSV／JSON 匯出（帶顯名）、兩筆紀錄比較（官方登記未變動）、人工詢價
- 新增：頁面 `lodging-records.html`（側欄「附近旅宿紀錄」、權限 key `lodging`）：資料狀態與更新、紀錄清單／明細／刪除、比較、匯出、列印、新增詢價；顯名在清單、明細、比較都顯示
- 中心點來源是 Google ⇒ 紀錄不存座標與距離（LG-M2）；過渡期地址定位一律不用 Google（待 L1 `geo.map_request_scope`）
