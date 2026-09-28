# 附近旅宿（lodging）

在地圖頁手動開啟，查詢中心點（目前位置或輸入的地址）附近的合法旅館與民宿：距離、官方登記參考房價、人工詢價紀錄；
查詢可存成紀錄，之後回查與比較。設計、條款逐字查證與稽核結論：`docs/platform/LODGING-NEARBY.md`。

## 資料來源

交通部觀光署「旅館民宿 - 觀光資訊資料庫」（data.gov.tw 7780），政府資料開放授權條款第 1 版：可商用、可保存，**必須顯名**
（顯名文字只由 `attribution.py` 產生；所有顯示官方資料的畫面與輸出都要帶）。
價格只有官方「參考最低／最高房價」（業者登記值，非即時）與使用者自己輸入的詢價；**不抓訂房網站**（條款禁止）。

## 開關與對外連線

| 環境變數 | 作用 |
|---|---|
| `MOTRIX_LODGING_FETCH=1` | 允許最高管理者按「更新旅宿資料」下載觀光署資料；沒設就不連外網 |

- 不排程；開頁、查詢都只查本機**旅宿**快照。
- ⚠ 「輸入地址」查詢時，中心點定位若 L1 快取沒命中，會經 L1 `geo.locate_cached()` 對外定位（受 `MOTRIX_GEO` 與 L1 節流；TGOS／Nominatim；地圖頁與設定都是 Google 底圖時才可能用 Google，且依條款不保存 Google 座標與距離）。「目前位置」只用瀏覽器定位。
- 下載有單次讀取逾時（60 秒）與整次總時限（180 秒）、大小上限 50 MB、解壓上限 200 MB。
- 速率：成功後 24 小時內不再下載；失敗後冷卻 1 小時；同時只跑一個。狀態在設定 `lodging_fetch_state`。
- 關閉：拿掉環境變數並重啟；或在模組管理停用本模組（不 import、零連線）；或產品選配不含本模組。

## 端點

前綴 `/api/lodging`，權限 key `lodging`（更新限最高管理者）。清單見 `api.py`。

## 資料（依 MODULE-GUIDE §3 分類）

| 名稱 | 類別 | 說明 |
|---|---|---|
| `lodging_catalog` | T3 | 觀光署資料快照（整批替換、可重抓）；不存電話、經營者、統編 |
| `lodging_searches` | T1 | 使用者存下的查詢；中心點為 Google 定位時不存座標 |
| `lodging_search_items` | T1 | 該次查詢結果；中心點為 Google 定位時不存距離 |
| `lodging_quotes` | T1 | 人工詢價紀錄 |

本模組不擁有任何檔案（F 類）：下載的 zip 只在記憶體解開。表由本模組的 migration（`migrations/0001_lodging_tables.py`）建立。

## 串接點

| 對象 | 形式 | 對方不在時 |
|---|---|---|
| L1 `helpers.geo`（定位） | L1 函式 | —（L1 一定在） |
| L1 地圖頁覆蓋層（IP-101 `map.overlay`） | `module.json` `map_overlays` 宣告＋`pages/lodging-overlay.js` 經 `MotrixMapOverlay.register` | 本模組不在 ⇒ 地圖頁沒有「附近旅宿」按鈕 |
| L1 每日 JSON 備份 | `module.json` `data.tables` 宣告 T1（archive 自動併入） | —（本模組未載入 ⇒ 不列，資料仍在整庫備份） |
