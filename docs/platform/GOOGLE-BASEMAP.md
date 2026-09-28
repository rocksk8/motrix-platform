# Google 底圖：計費、條款與做法比較（第十五班 ②(b)，A，2026-09-28 11:40）

> 狀態：〔更正 2026-09-28 12:15：使用者裁示採 **B（Maps JavaScript API）**、金鑰分兩把（CORE-SPEC dee64c54）；已實作，見 §7。原句「查證與建議，尚未實作」保留如下〕
> ~~查證與建議，尚未實作~~（主持派工：「選定做法前把比較與建議回報我，不要先寫整個實作」）。
> 來源：2026-09-28 以 `curl` 抓官方原始 HTML、只去標籤、自己讀（未經摘要模型）。各頁 footer「Last updated 2026-09-24 UTC」。
> 引文一律逐字（英文原文），中文是我的說明。

## 0. 為什麼要換底圖

SST §6.2（逐字）：「Customer must not use Google Maps Content from the Geocoding API in conjunction with a non-Google map.」
ToS §3.2.3(e)（逐字）：「Customer will not use the Google Maps Core Services with or near a non-Google Map in a Customer Application.」
⇒ 有 Google 金鑰（用 Google 定位）就要配 Google 底圖。②(a) 已先擋：OSM 底圖時不畫 Google 座標（`geo.google_basemap()`）。

## 1. 兩條路

| | A. Map Tiles API（2D）＋既有 Leaflet | B. Maps JavaScript API（改寫成 google.maps） |
|---|---|---|
| 計費 SKU | `Map Tiles API: 2D Map Tiles`（0164-F76D-680A） | `Dynamic Maps`（FAF4-3B2D-51B2） |
| 計費事件（SKU details 逐字） | 「Request that returns a 2D map tile」；「Session Token and Viewport information requests aren't billed.」 | 「Successful map load」 |
| 每月免費（pricing 逐字表格） | **100,000** 次 | **10,000** 次 |
| 超過之後（每 1,000 次，第一級） | **$0.60**（1,000,001–5,000,000：$0.48） | **$7.00**（100,001–500,000：$5.60） |
| 第三方渲染器（Leaflet） | 官方明文可用（見 §3） | 不適用（Google 自己的渲染器） |
| 歸屬標示 | **我們自己做**：Google Maps logo＋viewport 回的 copyright 字串（隨視野變） | Google 自動畫，不可遮 |
| map.html 改動 | 換 `L.tileLayer` 一層＋歸屬控制項＋session | 地圖、標記、叢集、彈窗全部改寫（markercluster 換 @googlemaps/markerclusterer） |
| 金鑰 | 每一張圖磚網址都帶 `key=`（瀏覽器看得到） | script 網址帶 `key=`（瀏覽器看得到） |

📌 額度 **per-SKU、不 pool**（march-2025 頁逐字：「a free monthly usage threshold for each Core Services SKU」）；地圖用量不會吃到 Geocoding 的 10,000。
📌 價目頁只列一個例外區：「For India pricing, see Google Maps Platform core services pricing list - India」⇒ 台灣適用全球價目表。

### 1.1 用量估算（**我的估算，不是官方數字**）

假設：20 位使用者 × 每人每工作日開地圖 10 次 × 22 天 ＝ 每月 4,400 次開圖。

| | 每次開圖的計費事件 | 每月 | 月費 |
|---|---|---|---|
| A. 2D Tiles | 1920×1080 一個視野約 40 張 256px 圖磚；加上平移／縮放，粗估 **100 張** | 440,000 | (440,000−100,000)×$0.60/1000 ≈ **$204** |
| B. Dynamic Maps | **1 次** map load | 4,400 | **$0**（在 10,000 內） |

⇒ **MOTRIX 的用法（開圖次數少、每次會拖拉縮放）B 便宜很多**；A 的費用隨「拖拉多少」線性增加，難預估。
⚠️ 圖磚數受螢幕大小、縮放次數、瀏覽器快取（須照 Cache-Control，見 §3）影響很大；要定案前可以在開發機量一次實際圖磚數。

## 2. 共同的條款要求（ToS，逐字）

- §3.2.3(b) Attribution：「Customer will display all attribution that (i) Google provides through the Services (including branding, logos, and copyright and trademark notices) … Customer will not modify, obscure, or delete such attribution.」
- §3.2.3(b) No Caching：「Customer will not cache Google Maps Content except as expressly permitted under the Maps Service Specific Terms.」（SST 沒有 Map Tiles／Maps JavaScript 的段落 ⇒ 沒有額外許可）
- §3.2.3(d)(i)：「re-distribute the Google Maps Core Services or pass them off as if they were Customer’s services」屬禁止 ⇒ **白標化**：底圖的 Google logo 與歸屬不可以被換成客戶品牌或隱藏。
- §3.2.3(e) 「with or near a non-Google Map」⇒ 有金鑰時，同一畫面不應同時提供 OSM 與 Google（切換鈕要想清楚：建議有金鑰就只用 Google，不給 OSM 選項）。

## 3. Map Tiles API 政策（逐字，https://developers.google.com/maps/documentation/tile/policies）

- 快取：「you must not pre-fetch, index, store, or cache any Content except under the limited conditions stated in the terms.」「your client must respect the max-age value, the stale-while-revalidate value, the must-revalidate directive, and the private directive」⇒ 瀏覽器 HTTP 快取可以；**伺服器端不可以存圖磚、不可以預抓**。
- 第三方渲染器：「When you use the Map Tiles API to display Google Maps using a third-party renderer, you must not overlap or obscure the Google logo with any other logo, such as the renderer's logo.」⇒ Leaflet 可以，Leaflet 自己的歸屬不可以蓋到 Google logo。
- 資料歸屬：「Data returned from the Map Tiles API requires the display of attribution and copyright information from the appropriate metadata or viewport information requests … Note that the attribution strings are variable, depending on the map data requested by the renderer's viewport.」⇒ 每次視野改變要打 viewport（不計費）更新歸屬字串。
- 疊自己的資料：「you must ensure your audience fully understands which portion of the map visualization is attributed to Google and which portions are attributed to your own map data」。
- Logo：「Minimum logo height: 16dp / Maximum logo height: 19dp」、不可變形，並附官方素材下載。
- Session（tile/session_tokens 逐字）：「A session token is currently valid for two weeks from its issue time, but this might change.」、「You can use the same session token across multiple clients.」；`POST https://tile.googleapis.com/v1/createSession?key=…`，圖磚 `https://tile.googleapis.com/v1/2dtiles/{z}/{x}/{y}?session=…&key=…`。

## 4. 建議

**B（Maps JavaScript API）**，理由依序：
1. 成本：MOTRIX 是「少數人、偶爾開圖、會拖拉」的用法，計費以 map load 計，1 次開圖＝1 次；免費 10,000 次/月在一般客戶規模內用不完。A 以圖磚計，拖拉越多越貴、難估。
2. 條款風險最小：歸屬、logo 由 Google 自己畫，不會因我們的版面改動而違反 §3.2.3(b)；A 要自己維護 logo 尺寸、viewport 歸屬字串、與 Leaflet 歸屬的間距。
3. 代價：map.html 地圖層要改寫（標記、叢集、彈窗、`?focus=`、圖層切換），e2e 題要跟著改；A 只換一層 tileLayer。

若主持／使用者更在意「改動範圍小、這一班做完」：選 A，並把 viewport 歸屬與 logo 做成獨立元件＋題，另在 Google Cloud Console 對 Map Tiles API 設每日配額上限（我們的伺服器看不到瀏覽器抓了幾張圖磚，無法在程式裡擋）。

兩條路都要：**瀏覽器用的金鑰與伺服器定位用的金鑰分開**（瀏覽器那把會公開在網址上）——瀏覽器金鑰限定 HTTP referrer（正式機網址）＋只開 Maps JavaScript API 或 Map Tiles API；伺服器金鑰維持只開 Geocoding。

## 5. 要改的地方（選定後才動）

| 位置 | A. Map Tiles | B. Maps JS |
|---|---|---|
| `frontend/pages/map.html` | 有金鑰：`L.tileLayer('https://tile.googleapis.com/v1/2dtiles/{z}/{x}/{y}?session=…&key=…')`；歸屬控制項（Google Maps logo 16–19dp＋viewport copyright，`moveend` 更新）；Leaflet 歸屬移開不重疊；無金鑰維持 OSM | 有金鑰：改用 `google.maps.Map`／`AdvancedMarkerElement`／`@googlemaps/markerclusterer`（vendor 進 static，照 PROVENANCE 規則）；彈窗、`?focus=`、圖層切換改寫；無金鑰維持 Leaflet＋OSM（兩套渲染並存或抽象一層） |
| `main.py` CSP | `img-src` 加 `https://tile.googleapis.com`；`connect-src` 加 `https://tile.googleapis.com`（viewport；createSession 若由瀏覽器打） | `script-src` 加 `https://maps.googleapis.com`；`img-src` 加 `https://maps.gstatic.com https://*.googleapis.com`；`connect-src` 加 `https://maps.googleapis.com`；`font-src`／`style-src` 視官方 CSP 指南（要再逐字查 Maps JS 的 CSP 頁） |
| 後端 | `createSession`（伺服器用瀏覽器金鑰打一次、快取 token 到到期前）或交給前端；新端點回 token＋到期 | 回瀏覽器金鑰（只給登入者；或直接寫在頁面設定端點） |
| `helpers/geo.py` | `google_basemap()` ＝「有瀏覽器金鑰且未停用」；②(a) 的守門與預熱範圍自動切換 | 同左 |
| 額度計算器（`USAGE_SKU_*`、設定頁） | 新 SKU `google:map-tiles-2d`（免費 100,000）；**伺服器量不到**圖磚數 ⇒ 顯示「由 Google Cloud Console 查看」並建議設配額上限，不假裝計數 | 新 SKU `google:dynamic-maps`（免費 10,000）；伺服器可以用「開地圖頁的次數」近似（每次開圖＝1 load）並標明是估計 |
| 公司資料設定頁 | 新欄位「地圖用（瀏覽器）金鑰」＋限制說明 | 同左 |
| 白標化 | Google logo／歸屬不可換成客戶品牌；品牌設定頁說明「地圖上的 Google 標示依 Google 條款不可移除」 | 同左 |
| 條款守門題 | 有金鑰頁面不出現 OSM 圖磚網址；歸屬元件存在且未被遮；伺服器不存圖磚 | 有金鑰頁面不載入 OSM；Google 地圖載入後沒有我們的元素蓋在 logo 上 |

## 6. 未查證／待辦

- Maps JavaScript API 的 CSP 官方指南（B 要逐字查）。
- 實際每次開圖的圖磚數（A 的成本估算基礎；可在開發機量）。
- 伺服器代抓圖磚（proxy）是否被允許：沒查到明文許可 ⇒ **不採用**（§3.2.3(b) No Caching 的預設是禁止）。

## 7. 實作（B，第十五班，wip/a-google-basemap）與人工驗收清單

### 7.1 做了什麼
- 公司資料設定：「Google 地圖（瀏覽器）金鑰」（遮蔽、不入稽核值）與「Google 地圖 ID」兩欄；伺服器定位金鑰維持原欄位、**永不送到瀏覽器**（守門：`test_map_google_basemap_2026_09_28.py` 的回應檢查與 AST 讀取點白名單）。
- `geo.google_basemap()`＝有地圖金鑰。它同時決定：地圖頁載 Google 或 OSM、`/api/map/points` 是否可用 Google 座標、背景預熱與據點存檔是否問 Google（SST §6.2）。
- `GET /api/map/config`：`{basemap, browserKey, mapId}`（osm 時只有 basemap）；回 google 一次記一次 `google:dynamic-maps`（開圖次數近似 map load，額度設定頁 SKU 清單已列，實際以 Cloud Console 為準）。
- 地圖頁：`map.html` 先問設定；google ⇒ 載 `static/map-google.js` 轉接層（覆寫繪圖方法；標記／彈窗內容仍由 map.html 的 `_pinHtml`／`_popupHtml`／`_siteHtml` 產生），**同畫面不載 OSM**、OSM 出處不顯示；設定取不到 ⇒ 說出來、不畫。標記 `AdvancedMarkerElement`＋`mapId`；群聚 `@googlemaps/markerclusterer 2.6.2`（vendor，PROVENANCE 附雜湊）。
- CSP：官方 Allowlist 範例只套在 `/pages/map.html`。

### 7.2 自動測試證明不了的（需要真的瀏覽器金鑰與網路）
e2e 以攔截回一支假的 `google.maps` 驗「我們呼叫轉接層與畫面邏輯正確」，**不證明真 Google 的行為**。上線前由有金鑰的人照下表實測一次（開發機或正式機皆可；正式機要先在 Cloud Console 把正式網址加進 HTTP 參照網址）：

| # | 步驟 | 通過條件 |
|---|---|---|
| 1 | 公司資料設定填地圖金鑰與地圖 ID，存檔，開地圖頁 | 出現 Google 地圖（不是 OSM）；左下 Google 標誌、右下資料來源標示可見、沒有被我們的按鈕或標記蓋住 |
| 2 | 瀏覽器開發者工具 → Network，篩 `tile.openstreetmap.org` | 0 筆 |
| 3 | Network 篩 `maps.googleapis.com/maps/api/js` | 網址的 `key=` 是**地圖金鑰**（末四碼對得上），不是伺服器金鑰 |
| 4 | Console | 沒有 CSP 違規、沒有 `InvalidKeyMapError`／`RefererNotAllowedMapError`／Map ID 相關警告 |
| 5 | 地圖上的點、據點、「目前位置」與精度圈 | 與清單一致；點的顏色與字母和 OSM 版相同；重疊的點合成數字圈，點開會散開 |
| 6 | 點一個標記 | 彈窗內容與 OSM 版相同（名稱、地址、距離、「開啟單據」「Google 導航」連結可用） |
| 7 | 從單據頁按「在地圖上看」（`?focus=`） | 地圖放大到那一筆並開彈窗 |
| 8 | 清除地圖金鑰、存檔、重開地圖頁 | 回到 OSM；只有 Google 座標的點不顯示並有說明（googleOnlyHidden） |
| 9 | 故意填錯地圖金鑰 | 畫面顯示「Google 地圖金鑰無法使用…」而不是一片空白 |
| 10 | Cloud Console → Maps JavaScript API 用量 | 與額度設定頁「地圖載入」的近似次數同一量級（近似，不要求相等） |

### 7.3 裁示（2026-09-28 12:30，使用者）
- 瀏覽器金鑰＋地圖 ID **兩項都填**才切 Google 底圖；缺一項＝OSM、不使用任何 Google 內容（`geo.google_basemap()`）。只做 AdvancedMarkerElement，不做舊 Marker 分支。官方示範用 map ID 只准在測試。
