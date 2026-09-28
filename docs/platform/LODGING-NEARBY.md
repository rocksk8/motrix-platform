# 地圖附近旅宿：來源調查與設計（E 線 E1，2026-09-28）

> 狀態：**來源調查＋設計，尚未實作**（主持派工：交 D 審，過了才寫產品碼）。
> 依據：CORE-SPEC 裁示表「地圖附近旅宿（新功能，第 E 線）」（09888e19）。
> 取證方式：2026-09-28 16:30～16:45 以 `curl` 抓原始檔，只去標籤、自己讀（未經摘要模型）。引文一律逐字；中文說明是我的判讀。
> 原始檔保存在 E 線 session scratchpad（未進 repo）；重抓網址逐條列在各節。

## 0. 結論（先看這裡）

| 項目 | 結論 |
|---|---|
| 主要來源 | **交通部觀光署「旅館民宿 - 觀光資訊資料庫」**（data.gov.tw 7780）：全國合法旅館＋民宿 15,646 筆，全部有座標、證號；免費、免金鑰、無 IP 白名單；政府資料開放授權條款第 1 版（可商用、可保存、可改作，**必須顯名**） |
| 各縣市登記資料 | 同一授權；欄位是全國檔的子集、多數無座標 ⇒ **不接**（全國檔已涵蓋） |
| OpenStreetMap／Overpass | 公開站政策明文「Commercial use should use self-hosted or paid Overpass servers」；OSM 標籤**沒有房價欄位**；實測主站 2 次 504、備援站逾時 ⇒ **第一版不接**，留介面給「自架 Overpass」 |
| 免費即時價格 | **不存在**（查到的都要合約或條款禁止自動取得，見 §2） |
| 價格替代 | ①官方登記的「參考最低／最高房價」（LowestPrice／CeilingPrice，15,640 筆有值）②使用者人工輸入的詢價紀錄（誰、何時、來源、房型、金額） |
| 訂房網站爬價 | **不可用**（Booking.com A15.2、Airbnb Terms 逐字見 §2.2）；舊的「GPU 手動抓」不沿用 |

## 1. 來源逐一查證

### 1.1 交通部觀光署「旅館民宿 - 觀光資訊資料庫」（主要來源）

- 詮釋資料：`GET https://data.gov.tw/api/v2/rest/dataset/7780`（逐字欄位）：
  - `"title": "旅館民宿 - 觀光資訊資料庫"`、`"license": "1"`、`"cost": "free"`、`"updateFrequency": {"Frequency": "1", "unittime": "日"}`
  - `"notes": "座標地圖:GOOGLE為主"`（⚠ 見 §1.1.4）
  - 下載：`https://media.taiwan.net.tw/XMLReleaseAll_public/v2.0/Zh_tw/Hotel-json.zip`（亦有 XML）
- 資料集清單 CSV（`https://data.gov.tw/datasets/export/csv`）「授權方式」欄逐字：`政府資料開放授權條款-第1版`。
- 取得方式：一個 zip（2026-09-28 為 4,802,443 bytes，解開 `HotelList.json` 37 MB）。**不需金鑰、不需申請、不需 IP 白名單**（直接 `curl` 200）。回應標頭 `Access-Control-Allow-Origin: *`、`Cache-Control: private, no-store`（後者是 HTTP 快取語意，不是授權限制；保存與重製的許可來自授權條款 §二(一)）。

#### 1.1.1 授權條款逐字（`https://data.gov.tw/license`，政府資料開放授權條款－第1版，中華民國104年7月27日訂定）

- 二(一)：「各機關所提供之開放資料，授權使用者不限目的、時間及地域、非專屬、不可撤回、免授權金進行利用，利用之方式包括重製、散布、公開傳輸、公開播送、公開口述、公開上映、公開演出、編輯、改作，包括但不限於開發各種產品或服務型態之衍生物。」
  ⇒ **可商用、可保存（不限時間）、可做成產品。**
- 二(二)：「使用者得再轉授權他人為前項之利用。」⇒ 賣給客戶的安裝可以帶這份資料。
- 三(二)：「使用者利用依本條款提供之開放資料，及後續之衍生物，應以符合附件所示「顯名聲明」要求之方式，明確標示原資料提供機關之相關聲明；**未盡顯名標示義務者，視為自始未取得開放資料之授權。**」
  ⇒ **顯名是授權的條件，不是禮貌**：頁面、匯出、列印都要帶（§3.7 守門）。
- 附件顯名聲明（逐字格式）：「提供機關／單位 [年份] [開放資料釋出名稱與版本號]　此開放資料依政府資料開放授權條款 (Open Government Data License) 進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。　政府資料開放授權條款：https://data.gov.tw/license」
- 五：機關得停止提供（情事變更、侵權之虞），「使用者不得向資料提供機關請求任何賠償或補償」⇒ 來源可能消失，模組要能在沒有新資料時照常用舊快照並標示日期。
- 六(一)：「不構成任何資料提供機關申述、保證…」⇒ 頁面標「資料為官方登記資訊，實際以業者為準」。
- 頻率上限：條款與資料集頁**沒有明文**。資料每日更新一次 ⇒ 自訂上限：**每 24 小時最多下載 1 次**（§3.5）。

#### 1.1.2 實際欄位（2026-09-28 14:30 版實測，15,646 筆）

| 需求 | 欄位 | 實測 |
|---|---|---|
| 座標 | `PositionLat`／`PositionLon`（標準：WGS84，至少小數 5 位） | 15,646／15,646 有值 |
| 類別 | `HotelClasses`（標準 §20 旅宿類型代碼：1 國際觀光旅館、2 一般觀光旅館、3 一般旅館、4 民宿、9 其他） | 4＝12,371、3＝3,159、1＝71、2＝45 |
| 合法性 | `HotelLicenseNumber`（例「南投縣民宿358號」） | 15,646 有值 |
| 名稱／地址／電話 | `HotelName`、`PostalAddress{City,Town,ZipCode,StreetAddress}`、`Telephones[]` | 有 |
| 價格 | `LowestPrice`／`CeilingPrice`（標準逐字：「描述旅館民宿最低價房型參考值，單位為TWD。」「描述旅館民宿最高價房型參考值，單位為TWD。」） | 最低價 >0：15,640；最高價 >0：15,643；最低>最高：0 筆；最低價中位數 4,000，極值 5～122,000（有明顯錯值，要過濾顯示） |
| 房型價目文字 | `RoomInfo`（例「套房3000;套房3000;」） | 3,164 筆有值，格式不一 ⇒ 只顯示原文、不解析 |
| 營運狀態 | `ServiceStatus`（1＝正常營運） | 全部 1 |
| 更新時間 | 檔頭 `UpdateTime`（`2026-09-28T14:30:31+08:00`）、`UpdateInterval: 86400`；每筆 `UpdateTime` | 每筆 2025-02～2026-09 |
| 經營者 | `Organizations[]`（含 `TaxCode`） | ⚠ 民宿經營者多為自然人 ⇒ **不存、不顯示**（§3.4） |

欄位定義出處：`https://media.taiwan.net.tw/Upload/觀光資料標準V2.1.pdf`（markitdown 轉文字後逐字比對 §20、LowestPrice／CeilingPrice 條目）。

#### 1.1.3 覆蓋抽查
以台中火車站（24.1372, 120.6867）半徑 3 km：官方 167 筆（一般旅館 166、國際觀光旅館 1）。OSM 對照因 Overpass 失敗未完成（§1.3）。

#### 1.1.4 ⚠ 座標的來歷（交 D 判斷）
詮釋資料 `"notes": "座標地圖:GOOGLE為主"`。我的判讀：這是機關取得座標的方式；我們取得的是機關以政府開放授權釋出的資料，授權方是機關、不是 Google，我們不呼叫 Google、也不受 Google ToS 拘束。**但**授權條款 §五「所提供之開放資料，有侵害第三人智慧財產權…之虞」機關可停止提供 ⇒ 風險落在「來源消失」，不落在我們保存的副本違約。列為 D 審查點 Q1。

### 1.2 各縣市合法民宿／旅館登記開放資料

資料集清單 CSV 以名稱含「民宿／旅館／旅宿」篩出（排除統計、稽查、營運報表）：

| 例 | 提供機關 | 欄位（清單「主要欄位說明」逐字） |
|---|---|---|
| 臺北市民宿名冊（135463） | 臺北市政府觀光傳播局 | 縣市代碼;民宿名稱;電話或手機號碼;傳真號碼;營業地址;房間數;參考房價 |
| 臺北市一般旅館名冊（135464） | 同上 | …;客房最低定價;客房最高定價;房間數 |
| 新北市合法民宿名冊（123996） | 新北市政府觀光旅遊局 | …;address(地址);coordinatelongitude(座標經度);coordinatelatitude(座標緯度… |
| 新竹市合法旅宿資料名冊（67759） | 城市行銷處 | …;緯度;經度;房間總數;最低價格;最高價格;… |
| 臺中市合法民宿（83638） | 臺中市政府觀光旅遊局 | 民宿登記證編號;中文名稱;縣市別代碼;郵遞區號;地址;網址 |
| 南投縣各鄉鎮合法旅館民宿（168774 等） | 南投縣政府 | 專用標識編號;中文名稱;地址;電話或手機;合計總房間數 |
| 連江縣合法民宿名冊（每月一檔，ODS） | 連江縣政府 | 民宿編號;民宿名稱;電話;地址 |

- 授權：全部是「政府資料開放授權條款-第1版」（同 §1.1.1）。
- 結論：**格式各縣市不同、多數沒有座標（要再定位＝又要對外連線）、部分按月另開新資料集**；欄位是全國檔的子集，而全國檔的 `HotelLicenseNumber` 本身就是「核發縣市＋旅宿類型＋號」（標準 §18）。⇒ **第一版不接**；只在 D 或使用者要求「交叉比對全國檔漏列」時再加。

### 1.3 OpenStreetMap／Overpass（tourism=hotel／guest_house／hostel／motel）

#### 1.3.1 資料授權（`https://www.openstreetmap.org/copyright`、ODbL 1.0 `https://opendatacommons.org/licenses/odbl/1-0/`）
- OSM copyright 頁逐字：「You are free to copy, distribute, transmit and adapt our data, as long as you credit OpenStreetMap and its contributors. If you alter or build upon our data, you may distribute the result only under the same license.」
- 同頁：「Where you use OpenStreetMap data, you are required to do the following two things: Provide credit to OpenStreetMap by displaying our attribution notice. Make clear that the data is available under the Open Database License.」
- ODbL 4.4 b：「Extraction or Re-utilisation of the whole or a Substantial part of the Contents into a new database is a Derivative Database and must comply with Section 4.4.」
- ODbL 4.5 c：「Use of a Derivative Database internally within an organisation is not to the public and therefore does not fall under the requirements of Section 4.4.」
- ODbL「Publicly」定義：「means to Persons other than You or under Your control by either more than 50% ownership or by the power to direct their activities」
  ⇒ 客戶在自己公司內部用＝不觸發 share-alike；但若客戶把紀錄（衍生資料庫）交給外部（例：給業主的報告附清單），就要依 4.3 標示、4.4 同授權、4.6 提供資料。**商用可、保存可、署名必須、對外有 share-alike 義務。**

#### 1.3.2 Overpass 公開站使用政策（`https://wiki.openstreetmap.org/wiki/Overpass_API` 主站列逐字）
- 「You can assume that you don't disturb other users when you do less than 10,000 queries per day and download less than 1 GB data per day. … If you set something up that uses the Overpass API regularly, then divide those numbers by 100 (making less than 100 queries fetching less 10 MB of data per day fine). **If you have an app or website, then the usage counts towards the sum of requests made by all your users.**」
- 「Be sure to check that your app or website adds User-Agent or Referer headers to requests that uniquely identify your app. No parallel running of multiple scripts. **Commercial use should use self-hosted or paid Overpass servers.** Cache and rate-limit calls, … If you receive an HTTP error code such as 429 or 406, pause for 30 seconds before making a new request.」
- 「Nowadays this server is overloaded - be mindful of that, do not overconsume resources and do not expect high reliability. Use alternatives if possible.」
- Overpass 使用手冊 Commons（`https://dev.overpass-api.de/overpass-doc/en/preface/commons.html`）列為 problematic behaviour：「Setting up an app for more than just OSM mappers and relying on the public instances as backend.」
- 金鑰／IP：不需金鑰；限流以 IP 計（手冊逐字「Requests usually are assigned by taking the IP address as the user.」），`/api/status` 實測「Rate limit: 4」。

#### 1.3.3 實際欄位
- OSM wiki `Tag:tourism=hotel` 建議標籤：`rooms=*`、`stars=*`、`beds=*`…；`Tag:tourism=guest_house`：`rooms=*`、`beds=*`。**沒有任何房價標籤**（逐頁搜尋 price／charge／fee 無房價條目）。
- 實測：`nwr(around:3000,24.1372,120.6867)[tourism~"^(hotel|guest_house|hostel|motel)$"];out center tags;`
  - overpass-api.de：16:35 **504**（本文「runtime error: open64: 0 Success /osm3s_osm_base Dispatcher_Client::request_read_a…」），照政策停 35 秒後重試仍 **504**；
  - overpass.private.coffee（wiki 逐字「Feel free to use our service in any project, there is no rate limit in place. Please notify us in advance if you intend to use our service in a large scale project.」）：90 秒**逾時**。
  - ⇒ 三次全失敗，筆數與標籤覆蓋率**未量到**（照實記，不推估）。

#### 1.3.4 結論
MOTRIX 是賣給多個客戶的產品 ⇒ 所有客戶的查詢合計算在「一個 app」、而且屬 commercial use ⇒ **公開站不可當後端**。OSM 也沒有房價。第一版**不接**；設計保留「來源介面」，之後可接**客戶自架或付費**的 Overpass 端點（設定填網址才啟用，預設空＝不連）。

## 2. 價格

### 2.1 免費且條款允許保存的**即時**價格來源：**不存在**
| 候選 | 查到的事實 | 結論 |
|---|---|---|
| 觀光署資料集 | 只有「參考最低／最高房價」（業者登記的區間），不是當日房價 | 可用，但標「官方登記參考房價」 |
| 縣市名冊 | 臺北「參考房價」「客房最低／最高定價」、新竹「最低／最高價格」 | 同性質（登記區間），不另接 |
| OSM | 無房價標籤（§1.3.3） | 無 |
| Google Places | CORE-SPEC 裁示已排除（ToS §3.2.3(a)(iii) 不准存店名地址，且非免費） | 不可用 |
| Booking.com Demand API | 官方 prerequisites 逐字：「Registered as a Booking.com Managed Affiliate Partner.」「Access to Partner Centre (provided by your Booking.com Account Manager after signing the agreed contract).」 | 要簽約成為聯盟夥伴 ⇒ 非公開免費 |
| Amadeus Self-Service | 官網頁面為 JS 渲染，`curl` 取不到內文 | **未查證**，不列為可用 |

### 2.2 訂房網站爬價格：不可用（條款逐字）
- **Booking.com** Terms（`https://www.booking.com/content/terms.en-gb.html`）A15.2：「Whether or not you have a commercial purpose, you’re not allowed to access, monitor, copy, scrape/crawl, download, reproduce or otherwise use anything on our Platform using any robot, spider, scraper, other automated means, or automated assistants (including, but not limited to, those that operate by interacting with or otherwise making use of your browser, such as AI-powered assistants) for any purpose without the prior, express written permission of Booking.com.」A15.3：「we’ll block anyone (and any automated system) we suspect of: conducting an unreasonable amount of searches using any device or software to gather prices or other information」
- **Airbnb** Terms of Service（`https://www.airbnb.com/help/article/2908`，Last Updated: February 5, 2026）：「Do not scrape, hack, reverse engineer, compromise or impair the Airbnb Platform Do not use bots, crawlers, scrapers, or other automated means to access or collect data or other content from or otherwise interact with the Airbnb Platform.」
- Agoda（JS 渲染，取回 18 字元）、Expedia（HTTP 429）、trivago：**未取得原文**；未查證前一律視同不可用（CORE-SPEC 限制②）。
- ⇒「用瀏覽器／GPU 自動操作去抓」同樣落在 Booking A15.2「automated assistants … making use of your browser」的明文範圍 ⇒ **不沿用舊作法**。

### 2.3 替代（第一版做 ①＋②）
1. **官方參考房價**：顯示 `LowestPrice～CeilingPrice`，標籤固定「官方登記參考房價（非即時）」＋資料日期；明顯錯值（< 300 或 > 100,000，門檻待 D 定）顯示「參考房價異常」不參與排序。
2. **人工詢價紀錄**：使用者電話或官網詢價後自己輸入（日期、房型、金額、每晚／含早、來源說明、輸入人）。這是使用者自己的資料 ⇒ 可永久保存。
3. 使用者上傳報價單（PDF／圖片）附在詢價紀錄：**第二版**，走 L1 附件（F1）。

## 3. 設計

### 3.1 模組定位
- 新 L2 模組 `lodging`（名稱「附近旅宿」，可獨立販售，`license_key: "lodging"`）。**不 import 任何 L2**；只用 L0／L1：`core.paths`、`core.registry`、`helpers.geo`（定位）、`db`。
- 定位走 L1 `helpers.geo.locate_cached(address)`：Google／TGOS／Nominatim 的選用與底圖規則（SST §6.2、`geo.google_basemap()`）**全部由 L1 決定**，模組不自己打任何定位 API。
- 距離：伺服器端 haversine（純計算，不呼叫 Distance Matrix 等外部服務）。顯示「直線距離」，不宣稱路程。

### 3.2 使用流程（地圖頁手動開啟）
1. 地圖頁出現「附近旅宿」按鈕（只在模組已載入時）；**預設關**，按了才開面板。開面板**不**對外連線。
2. 中心點二選一：
   - 「目前位置」：沿用地圖頁既有 `navigator.geolocation`（裝置定位，不經我們的伺服器對外）；
   - 「輸入地址」：送後端 → `geo.locate_cached()`。回傳精度是 `district`（行政區中心，Nominatim 無門牌）⇒ **畫面明說**「中心點只定位到行政區，距離誤差可能數公里」，仍可查。
3. 條件：半徑（1／3／5／10 km，預設 3）、類別（旅館／民宿，預設兩者）、排序（距離／參考房價）。
4. 查詢**只查本機快照**（§3.5），回清單＋地圖標記（旅館、民宿不同圖示）＋每筆：名稱、類別、證號、地址、距離、參考房價、最近一次人工詢價。
5. 「記錄這次查詢」：存成一筆紀錄（§3.3），之後可在「旅宿紀錄」頁回查、兩筆紀錄並列比較（同一家的距離／價格變化）。
6. 每一筆可「新增詢價」（§2.3②）。

### 3.3 資料表（模組自己的 migration；`module.json` `data` 宣告）

| 表 | 分類 | 內容 | 保存期限 |
|---|---|---|---|
| `lodging_catalog` | **T3**（可重建） | 觀光署快照的必要欄位：`source`('mot')、`source_id`(HotelID)、`license_no`、`name`、`class`(1/2/3/4/9)、`city`、`town`、`address`、`lat`、`lng`、`price_low`、`price_high`、`room_info`、`record_updated_at`、`dataset_updated_at` | 每次下載整批替換；可隨時刪除重抓 |
| `lodging_searches` | T1 | `id`、`created_at`、`created_by`、`center_kind`(device/address)、`center_label`（使用者輸入的地址原文或「目前位置」）、`center_lat`、`center_lng`、`center_source`（geo 回的 source）、`center_precision`、`radius_m`、`filters_json`、`dataset_updated_at`、`result_count`、`note` | 使用者資料，永久；**例外**：`center_source='google'` 的 `center_lat/lng` 在 30 天後清空（SST §6.3 lat/lng 30 天；天數取 `geo.GOOGLE_CACHE_TTL_DAYS`，不另寫數字） |
| `lodging_search_items` | T1 | `search_id`、`source`、`source_id`、`license_no`、`name`、`class`、`address`、`lat`、`lng`、`distance_m`、`price_low`、`price_high`、`dataset_updated_at` | 永久（官方資料依授權 §二(一) 不限時間；**匯出與列印必帶顯名**） |
| `lodging_quotes` | T1 | 人工詢價：`source`、`source_id`、`quoted_on`、`room_type`、`price`、`unit`（每晚／每人）、`includes`、`channel`（電話／官網／現場／其他）、`note`、`entered_by`、`entered_at` | 永久（使用者自己的資料） |

- 不存：`Organizations`（經營者、統編）、`Telephones`（民宿電話多為個人手機）；四張表都沒有這些欄位，畫面也不顯示電話。**D 審查點 Q2**：是否要顯示電話。
- 檔案：下載的 zip 與解開的 JSON 放 `core.paths` 的模組資料位置，分類 **F4**（可重建、不上雲、不匯出）；匯入 `lodging_catalog` 後刪 zip、保留最近一份 JSON 供重建。
- ⚠ **D 審查點 Q3**：`distance_m` 是由（可能來自 Google 的）中心座標算出的衍生數字。我的判讀：SST §6.3 限的是 lat/lng 本身，30 天清座標、保留距離與使用者輸入的地址文字即可；保守替代：`center_source='google'` 時連同 `distance_m` 一起清空（紀錄只剩名單與價格）。

### 3.4 個資
- 紀錄的中心點可能是使用者家／工地地址 ⇒ `center_label` 視同 IP-97 的地址：只給建立者與 admin+ 看、不寫 log、每日 JSON 匯出照 T1 但不進任何對外匯出。**D 審查點 Q4**：是否要列 `case_read_scope` 類的逐筆權限（預設：建立者＋admin+）。
- 旅宿本身是營業登記資訊（名稱、地址、證號），不是個資；經營者姓名／統編／電話不收（§3.3）。

### 3.5 對外連線：開關、速率上限、關閉方法

| 項目 | 設計 |
|---|---|
| 唯一的對外連線 | `GET https://media.taiwan.net.tw/XMLReleaseAll_public/v2.0/Zh_tw/Hotel-json.zip`（查詢本身永遠只查本機） |
| 總開關 | 環境變數 `MOTRIX_LODGING_FETCH=1` 才允許下載（`RuntimeSwitch`，同標案雷達；啟動提示只記「開著」那側） |
| 觸發 | **只有最高管理者在頁面按「更新旅宿資料」**；**不排程、不在開頁時自動抓**（裁示「不自動對外連線」） |
| 速率上限 | 兩次成功下載間隔 ≥ 24 小時（來源每日更新一次）；失敗後冷卻 1 小時；同時只跑一個（檔案鎖）。上限記在設定 `lodging_fetch_state`（上次成功／失敗時間）——計數有落點 |
| 大小與時限 | 下載上限 50 MB、逾時 60 秒、User-Agent 標明 MOTRIX；超過即中止、保留舊快照 |
| 失敗行為 | 舊快照照常可查；頁面顯示「資料日期 YYYY-MM-DD（更新失敗：原因）」；**不可以**把失敗顯示成「附近 0 間」 |
| 快照過舊 | 資料日期超過 30 天 ⇒ 頁面黃色提示（不自動去抓） |
| 關閉方法 | ①拿掉 `MOTRIX_LODGING_FETCH`（重啟生效）⇒ 按鈕隱藏、端點回 `unavailable`＋原因；②模組管理頁停用模組（不 import，零連線）；③不在產品選配內＝不出貨 |
| 沒有快照時 | 查詢回 `unavailable: "no_catalog"`＋「尚未下載旅宿資料，請最高管理者按『更新旅宿資料』」（不是 0 筆） |

### 3.6 與地圖頁（L1）的串接
- 新串接點 **`map.overlay`**（provider，多提供者；登記 INTEGRATION-POINTS，編號列車定）：L1 `GET /api/map/config` 多回 `overlays: [{key, label, script}]`，由已載入模組的 provider 提供；地圖頁依清單顯示按鈕並載入該模組的前端腳本（`modules/lodging/pages/lodging-overlay.js`）。
- 對方不在時：清單沒有這一項 ⇒ 地圖頁沒有按鈕（功能未安裝，不是「0 筆」）；直接打模組端點 ⇒ 既有「模組未載入」提示。
- 底圖規則：旅宿標記是官方開放資料座標，畫在 Google 或 OSM 底圖都不涉及 Google 內容；**中心點**若是 Google 定位，只會在 `google_basemap()` 為真時產生（L1 保證），因此不會出現「Google 座標畫在 OSM 底圖」。
- 顯名：面板底部固定顯示觀光署顯名聲明；Google 底圖時不得蓋住 Google logo（GOOGLE-BASEMAP §3、§7.2 #1）。

### 3.7 守門（實作時一起寫）
| 守什麼 | 做法 |
|---|---|
| 不自動連線 | 載入模組、開地圖頁、開面板、查詢：攔截 socket ⇒ 0 次對外連線（正對照：按「更新」且開關開 ⇒ 1 次） |
| 開關與速率 | 開關關 ⇒ 下載端點拒絕且不連線；24 小時內第二次 ⇒ 拒絕、不連線；並行兩個 ⇒ 只有一個連線 |
| 失敗≠0 筆 | 下載失敗／沒有快照 ⇒ 回應帶 `unavailable`，畫面文字不同於「半徑內沒有旅宿」 |
| 顯名 | 頁面、紀錄匯出、列印都含顯名聲明全文（字串比對；拿掉 ⇒ 紅） |
| Google 座標 30 天 | 造一筆 31 天前 `center_source='google'` ⇒ 清除工作後 lat/lng 為 NULL；`nominatim`／`device` 不動（反向控制） |
| 不存個資欄位 | 匯入後 `lodging_catalog` 沒有電話／統編／經營者欄；哨兵值不出現在任何表 |
| 邊界 | 模組不 import 其他 L2（既有 `test_module_boundaries`）；刪模組資料夾 ⇒ 地圖頁無按鈕、其餘測試照常 |
| 價格標示 | 回應每筆價格帶 `price_kind`（`official_reference`／`manual`），畫面標籤依它顯示；不可以沒有種類 |

### 3.8 步驟清單（E2 實作，依序）
1. `docs/platform/modules.json` 登記 `lodging`；建 `backend/modules/lodging/`（module.json：data 分類、license_key、pages、provides.api_prefixes `/api/lodging`、probes、customization；README／CHANGELOG 1.0.0／SPEC）。
2. migration 0001：四張表（SQL 寫在檔內，不 import 會演進的碼、不自己 commit）。
3. `source.py`：下載＋驗證（大小、zip 內只有預期檔、JSON 結構）＋整批替換 `lodging_catalog`（`core.txn.write_txn`）＋速率狀態。
4. `search.py`：bbox 預篩＋haversine、類別與半徑過濾、錯值價格標記。
5. `api.py`：`GET /api/lodging/status`（probe，純讀）、`POST /api/lodging/refresh`（superadmin）、`POST /api/lodging/search`、`POST /api/lodging/records`、`GET /api/lodging/records[/{id}]`、`POST /api/lodging/quotes`、`GET /api/lodging/compare?a=&b=`。
6. `__init__.py`：`ModuleSpec(routers, runtime_switches=[MOTRIX_LODGING_FETCH], startup_notices, providers={"map.overlay": …})`；30 天清除走 IP-11 `daily.check`（每日 08:00，不另開排程）。
7. L1：`/api/map/config` 加 `overlays`（`registry.providers("map.overlay")`）；map.html 顯示按鈕並載入腳本；INTEGRATION-POINTS 登記；CORE 版號＋CHANGELOG（L1 介面新增）。
8. 前端：`lodging-overlay.js`（面板、標記、顯名）、`lodging-records.html`（回查、比較、詢價）；`sidebar.js` `MODULE_PAGES` 登記。
9. §3.7 守門＋e2e（面板開關、查詢、記錄、比較）；PLAYBOOK §G5 自查後送測。

### 3.9 核心代碼方向（示意，非最終）
```python
# search.py —— 只查本機快照；外部連線只在 source.refresh()
def nearby(conn, lat, lng, radius_m, classes):
    dlat = radius_m / 111_320
    dlng = radius_m / (111_320 * max(cos(radians(lat)), 0.01))
    rows = conn.execute(
        "SELECT * FROM lodging_catalog WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?"
        f" AND class IN ({','.join('?' * len(classes))})",
        (lat - dlat, lat + dlat, lng - dlng, lng + dlng, *classes)).fetchall()
    out = [dict(r, distance_m=round(haversine_m(lat, lng, r["lat"], r["lng"])),
                price_kind="official_reference") for r in rows]
    return sorted((r for r in out if r["distance_m"] <= radius_m), key=lambda r: r["distance_m"])

# source.py —— 唯一對外連線
def refresh(conn, now):
    if not fetch_on():            return unavailable("switch_off")
    if not rate_ok(conn, now):    return unavailable("rate_limited", next_at=...)
    with single_flight_lock():    # 檔案鎖；拿不到 ⇒ 回「更新中」
        blob = http_get(URL, max_bytes=50 << 20, timeout=60)
        hotels = parse_and_validate(blob)          # 結構不對 ⇒ 例外、舊快照不動
        with write_txn(conn): replace_catalog(conn, hotels)
        record_success(conn, now, hotels.update_time)
```

## 4. 交 D 審查點
- Q1 觀光署座標「GOOGLE為主」是否影響我們保存與在 OSM 底圖顯示（§1.1.4）。
- Q2 旅宿電話是否顯示（民宿多為個人手機；目前設計不存不顯示）。
- Q3 Google 中心點 30 天後：只清座標，或連距離一起清（§3.3）。
- Q4 查詢紀錄的可見範圍（預設建立者＋admin+）。
- Q5 參考房價錯值門檻（< 300 或 > 100,000）。
- Q6 `map.overlay` 串接點放進 L1（CORE 小版號新增）是否可以，或改成模組自己的頁面、不動 map.html。

## 5. 未查證
- Agoda、Expedia、trivago、Amadeus 條款原文（JS 渲染／429）。
- Overpass 在台灣的旅宿筆數與標籤覆蓋（三次連線失敗）。
- 交通部 TDX 觀光 API（要會員金鑰）：全國檔已足，未查。
