# 地圖附近旅宿：來源調查與設計（E 線 E1，2026-09-28）

> 狀態：**來源調查＋設計，尚未實作**（主持派工：交 D 審，過了才寫產品碼）。
> 〔修訂 2026-09-28 16:50：D 審 AUDIT-D-E1-lodging.md（wip/d-audit-train16 fb225dd9）必修 LG-M1／LG-M2、建議 LG-S1～S5 全收；Q2 不顯示電話、Q4 建立者＋admin+ 照原設計；Q1 使用者裁示採用 §1.1.4 判讀（CORE-SPEC ff3b1e14）。被取代的原句以刪除線保留〕
> 〔修訂 2026-09-28 16:55：D 複審（wip/d-audit-train16 7a9cddb2 §5）LG-M1／LG-M2 關閉；新必修 LG2-M1、建議 LG2-S1～S3 全收〕
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
- 「Be sure to check that your app or website adds User-Agent or Referer headers to requests that uniquely identify your app. No parallel running of multiple scripts. **Commercial use should use self-hosted or paid Overpass servers.**〔原頁句尾的註腳編號 [1]～[8] 引用時省略，文字未改〕 Cache and rate-limit calls, … If you receive an HTTP error code such as 429 or 406, pause for 30 seconds before making a new request.」
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
   〔LG-S1〕每一筆價格旁標「業者登記於 YYYY-MM」（取該筆 `UpdateTime`，實測 2025-02～2026-09 都有），不只標整批資料日期；比較兩筆紀錄時，官方參考房價兩次相同 ⇒ 標「官方登記未變動」，不寫成「價格沒漲」。
   〔LG-S4〕錯值門檻做成具名常數 `PRICE_SANE_MIN = 300`、`PRICE_SANE_MAX = 100_000`（附題）；錯值不參與排序，但原值以灰字顯示「官方登記值：5」，不隱藏。
2. **人工詢價紀錄**：使用者電話或官網詢價後自己輸入（日期、房型、金額、每晚／含早、來源說明、輸入人）。這是使用者自己的資料 ⇒ 可永久保存。
3. 使用者上傳報價單（PDF／圖片）附在詢價紀錄：**第二版**，走 L1 附件（F1）。

## 3. 設計

### 3.1 模組定位
- 新 L2 模組 `lodging`（名稱「附近旅宿」，可獨立販售，`license_key: "lodging"`）。**不 import 任何 L2**；只用 L0／L1：`core.paths`、`core.registry`、`helpers.geo`（定位）、`db`。
- ~~定位走 L1 `helpers.geo.locate_cached(address)`：Google／TGOS／Nominatim 的選用與底圖規則（SST §6.2、`geo.google_basemap()`）**全部由 L1 決定**，模組不自己打任何定位 API。~~
  〔更正 LG2-M1（D 複審）：不成立——`locate_cached()` 擋 Google 靠 contextvar，範圍要由**呼叫端**用 `with geo.without_google_content()` 包；目前只有 map_points、背景預熱、據點存檔三處有包，旅宿直接呼叫就會在 OSM 底圖＋有伺服器金鑰時問 Google（SST §6.2）。改為下一條〕
- 定位走 L1 `helpers.geo.locate_cached(address)`，而且**一律包在 L1 新函式 `geo.map_request_scope(page_basemap, missing=…)` 裡**（§3.1.1）；模組不自己打任何定位 API、不自己判斷底圖。
- 距離：伺服器端 haversine（純計算，不呼叫 Distance Matrix 等外部服務）。顯示「直線距離」，不宣稱路程。

#### 3.1.1 地圖請求的 Google 範圍（LG2-M1；L1，旅宿與 map_points 共用）
- 現況：`routers/map_points.py` 自己寫 `google_map = geo.google_basemap() and (basemap or "google") != "osm"`，否則 `with geo.without_google_content()`（GB-M2「只准收窄」）。
- 抽成 L1 一支（CORE 小版號新增）：
  ```python
  @contextmanager
  def map_request_scope(page_basemap, missing="osm"):
      """地圖頁送來的請求：頁面底圖只准收窄設定。yield True＝這次可以用 Google 內容。
      page_basemap: 'google'｜'osm'｜None；None 依 missing（'osm'＝視同 osm，'setting'＝照設定）。"""
      page = page_basemap if page_basemap in ("google", "osm") else (None if page_basemap is None else "osm")
      if page is None:
          page = "google" if missing == "setting" else "osm"
      allowed = google_basemap() and page != "osm"
      if allowed:
          yield True
      else:
          with without_google_content():
              yield False
  ```
  - 不認得的值（例 `"GOOGLE "`、`"x"`）⇒ 當 osm（收窄，不猜）。
  - map_points 改用 `map_request_scope(basemap, missing="setting")`——`None`／`google`／`osm` 三種值的行為與現在相同（沒帶＝照設定，給標案雷達計數這類非地圖呼叫者），由既有 GB-M2 題守住；⚠ **唯一的行為差異**：不認得的值（例 `basemap=x`）現在是 `"x" != "osm"` ⇒ 可用 Google，改後視同 osm ⇒ **收窄**（有意的，符合「只准收窄」；map_points 升版並寫 CHANGELOG，加一題）。
  - 旅宿用 `missing="osm"`：旅宿搜尋只會從地圖頁來，沒帶底圖＝失敗關閉。
- 旅宿搜尋端點 `POST /api/lodging/search` 收 `basemap`（覆蓋層取 `api.basemap()` 帶上）；整段（定位中心點＋距離）在 `with geo.map_request_scope(body.basemap, missing="osm") as google_ok:` 內；回應帶 `basemap: "google" if google_ok else "osm"`，覆蓋層拿它與 `api.basemap()` 比對，不一致 ⇒ 重新查詢（GB-M2 同型：頁面 osm、設定剛改 google）。
- 題：
  - 伺服器金鑰在、Google 階會命中（攔截回一個 Google 座標）、頁面 `osm` ⇒ 中心點 `source` 不是 google、Google 階 0 次呼叫；
  - 頁面沒帶 `basemap` ⇒ 同上（missing="osm"）；不認得的值 ⇒ 同上；
  - 設定 osm、頁面 google ⇒ 不用 Google（只准收窄）；
  - **反向控制**：頁面 google＋設定 google（有地圖金鑰與 Map ID）⇒ 可以是 google（且依 LG-M2 不保存座標與距離）；
  - map_points 既有 GB-M2 題不改而全過（證明抽函式沒改行為）；另加 `map_request_scope` 單元題（四種頁面值 × 兩種設定）。

### 3.2 使用流程（地圖頁手動開啟）
1. 地圖頁出現「附近旅宿」按鈕（只在模組已載入時）；**預設關**，按了才開面板。開面板**不**對外連線。
2. 中心點二選一：
   - 「目前位置」：沿用地圖頁既有 `navigator.geolocation`（裝置定位，不經我們的伺服器對外）；
   - 「輸入地址」：送後端 → ~~`geo.locate_cached()`~~〔LG2-M1：→ `map_request_scope(頁面底圖)` 內的 `geo.locate_cached()`，§3.1.1〕。回傳精度是 `district`（行政區中心，Nominatim 無門牌）⇒ **畫面明說**「中心點只定位到行政區，距離誤差可能數公里」，仍可查。
3. 條件：半徑（1／3／5／10 km，預設 3）、類別（旅館／民宿，預設兩者）、排序（距離／參考房價）。
4. 查詢**只查本機快照**（§3.5），回清單＋地圖標記（旅館、民宿不同圖示）＋每筆：名稱、類別、證號、地址、距離、參考房價、最近一次人工詢價。
5. 「記錄這次查詢」：存成一筆紀錄（§3.3），之後可在「旅宿紀錄」頁回查、兩筆紀錄並列比較（同一家的距離／價格變化）。
6. 每一筆可「新增詢價」（§2.3②）。

### 3.3 資料表（模組自己的 migration；`module.json` `data` 宣告）

| 表 | 分類 | 內容 | 保存期限 |
|---|---|---|---|
| `lodging_catalog` | **T3**（可重建） | 觀光署快照的必要欄位：`source`('mot')、`source_id`(HotelID)、`license_no`、`name`、`class`(1/2/3/4/9)、`city`、`town`、`address`、`lat`、`lng`、`price_low`、`price_high`、`room_info`、`record_updated_at`（每筆 `UpdateTime`＝業者登記時間，LG-S1）、`dataset_updated_at` | 每次下載整批替換；可隨時刪除重抓 |
| `lodging_searches` | T1 | `id`、`created_at`、`created_by`、`center_kind`(device/address)、`center_label`（使用者輸入的地址原文或「目前位置」）、`center_lat`、`center_lng`（**`center_source='google'` 時一律 NULL**，LG-M2）、`center_source`（geo 回的 source）、`center_precision`、`radius_m`、`filters_json`、`dataset_updated_at`、`result_count`、`note` | 使用者資料，永久。~~例外：`center_source='google'` 的 `center_lat/lng` 在 30 天後清空（SST §6.3…）~~〔更正 LG-M2：T1 會進每日備份、月備份永久保留，30 天清不到備份（同 SST-M1 裁示 3587fe41）⇒ Google 座標**從不寫入**，不需要清除工作〕 |
| `lodging_search_items` | T1 | `search_id`、`source`、`source_id`、`license_no`、`name`、`class`、`address`、`lat`、`lng`、`distance_m`（中心點為 Google 定位時 NULL，LG-M2）、`price_low`、`price_high`、`price_registered_at`（該筆業者登記時間，LG-S1）、`dataset_updated_at` | 永久（官方資料依授權 §二(一) 不限時間；**匯出與列印必帶顯名**） |
| `lodging_quotes` | T1 | 人工詢價：`source`、`source_id`、`quoted_on`、`room_type`、`price`、`unit`（每晚／每人）、`includes`、`channel`（電話／官網／現場／其他）、`note`、`entered_by`、`entered_at` | 永久（使用者自己的資料） |

- 不存：`Organizations`（經營者、統編）、`Telephones`（民宿電話多為個人手機）；四張表都沒有這些欄位，畫面也不顯示電話。**D 審查點 Q2**：是否要顯示電話。
- 檔案：下載的 zip 與解開的 JSON 放 `core.paths` 的模組資料位置，分類 **F4**（可重建、不上雲、不匯出）；匯入 `lodging_catalog` 後刪 zip、保留最近一份 JSON 供重建。
- ~~⚠ **D 審查點 Q3**：`distance_m` 是由（可能來自 Google 的）中心座標算出的衍生數字。我的判讀：SST §6.3 限的是 lat/lng 本身，30 天清座標、保留距離與使用者輸入的地址文字即可；保守替代：`center_source='google'` 時連同 `distance_m` 一起清空（紀錄只剩名單與價格）。~~
  〔更正 LG-M2（D 審）：`center_source='google'` 時**座標與距離都不存**，只存地址文字、來源、精度；紀錄頁該筆顯示「中心點為 Google 定位，距離不保存」。回查時要距離 ⇒ 使用者按「重算」以當下 L1 定位重算並顯示，**不寫回**。device／nominatim／tgos／manual 照存〕

#### 3.3a 每日 JSON 備份的接點（主持裁示 2026-09-28 17:13，E 線提問、採建議）
- lodging 是第一個「自己 migration 建表」的模組；每日 JSON 備份清單寫死在 L1 `archive._daily_backup_tables()`，
  硬加 L2 表名 ⇒ 模組未載入／停用時表不存在 ⇒ 該表 "error" ⇒ 每日備份誤報 daily_partial。
- 裁示：archive 自動併入**已載入**模組 `module.json` `data.tables` 宣告的表（表名只取已驗證宣告、`SELECT * … ORDER BY rowid`；
  未載入或停用＝不列、不 error，資料仍在整庫備份）；非法表名 ⇒ 不列並記 ERROR；已在寫死清單的不重複匯出。
  L1 不可寫死 L2 表名：現行 payment_requests／tender_* 是既有債，本次不動，列下一輪「改為宣告式」。
- 〔實作差異，E 2026-09-28 17:48：只自動併入 **T1**；宣告 T2 的表不自動列、記 ERROR——T2 有祕密欄位，`SELECT *` 會把祕密寫進 JSON
  （MODULE-GUIDE §3.3「匯出但必須排除祕密欄位」）；T2 仍照舊在 archive 逐欄明列。〕
- 實作：`archive._module_declared_backup_tables`（鍵 `模組-<key>-<表>`）；守門 `tests/test_archive_module_declared_tables_2026_09_28.py`
  （合成模組：T1 列、T2／T3／非法名不列、寫死的不重複；停用 ⇒ 不列不 error；正對照：載入中而表不在 ⇒ "error"）；CORE 1.65。

### 3.4 個資
- 紀錄的中心點可能是使用者家／工地地址 ⇒ `center_label` 視同 IP-97 的地址：只給建立者與 admin+ 看、不寫 log、每日 JSON 匯出照 T1 但不進任何對外匯出。**D 審查點 Q4**：是否要列 `case_read_scope` 類的逐筆權限（預設：建立者＋admin+）。
- 旅宿本身是營業登記資訊（名稱、地址、證號），不是個資；經營者姓名／統編／電話不收（§3.3）。

### 3.5 對外連線：開關、速率上限、關閉方法

〔補 D 稽核 E2-S3（2026-09-28）：**旅宿資料**只在下表的手動更新時連線；但「輸入地址」查詢時，若 L1 定位快取沒命中，會經
`geo.locate_cached()` 對外定位（受 `MOTRIX_GEO` 開關與 L1 節流；TGOS／Nominatim；頁面與設定都是 Google 底圖時才可能用 Google，§3.1.1）。
「目前位置」只用瀏覽器定位，不經伺服器對外。E2-S1：下載另有整次總時限 `FETCH_TOTAL_SECONDS`（180 秒），慢送不會一直握著更新鎖。〕

| 項目 | 設計 |
|---|---|
| 唯一的對外連線 | `GET https://media.taiwan.net.tw/XMLReleaseAll_public/v2.0/Zh_tw/Hotel-json.zip`（查詢本身永遠只查本機） |
| 總開關 | 環境變數 `MOTRIX_LODGING_FETCH=1` 才允許下載（`RuntimeSwitch`，同標案雷達；啟動提示只記「開著」那側） |
| 觸發 | **只有最高管理者在頁面按「更新旅宿資料」**；**不排程、不在開頁時自動抓**（裁示「不自動對外連線」） |
| 速率上限 | 兩次成功下載間隔 ≥ 24 小時（來源每日更新一次）；失敗後冷卻 1 小時；同時只跑一個（檔案鎖）。上限記在設定 `lodging_fetch_state`（上次成功／失敗時間）——計數有落點 |
| 大小與時限 | 下載上限 50 MB、逾時 60 秒、User-Agent 標明 MOTRIX；超過即中止、保留舊快照 |
| 解壓驗證（LG-S3） | zip 內檔名**白名單**＝`HotelList.json`、`manifest.csv`、`schema-HotelList.csv`、`schema-HotelList-s.csv`（其他檔名 ⇒ 整包拒絕）；拒絕絕對路徑、含 `..`、含磁碟代號的項目（zip slip）；只在記憶體或暫存目錄解開白名單內的檔；解壓後總大小上限 200 MB（實測 37 MB）、單檔宣告大小與實際讀出不符 ⇒ 拒絕；任一不過 ⇒ 舊快照不動、記原因 |
| 失敗行為 | 舊快照照常可查；頁面顯示「資料日期 YYYY-MM-DD（更新失敗：原因）」；**不可以**把失敗顯示成「附近 0 間」 |
| 快照過舊 | 資料日期超過 30 天 ⇒ 頁面黃色提示（不自動去抓） |
| 關閉方法 | ①拿掉 `MOTRIX_LODGING_FETCH`（重啟生效）⇒ 按鈕隱藏、端點回 `unavailable`＋原因；②模組管理頁停用模組（不 import，零連線）；③不在產品選配內＝不出貨 |
| 沒有快照時 | 查詢回 `unavailable: "no_catalog"`＋「尚未下載旅宿資料，請最高管理者按『更新旅宿資料』」（不是 0 筆） |

### 3.6 與地圖頁（L1）的串接

〔實作差異，E 2026-09-28 17:48（D 完整稽核時請看）：
① 覆蓋層清單另開 `GET /api/map/overlays`，**不併進** `/api/map/config`——config 的回應形狀有金鑰守門題逐字比對（`test_map_google_basemap` 的 `== {"basemap": "osm"}`），不動它。
② 腳本網址是 `/map-overlays/<模組>/<檔名>`（main.py 在 StaticFiles 之前的路由，同 /pages）：`<script src>` 帶不了 Authorization ⇒ 不能放在 /api 底下；
   只提供「已載入模組宣告、檔案在該模組 `pages/` 底下」的腳本，其餘 404。腳本是程式碼、不含資料；資料一律經模組自己的 /api 端點。
③ 宣告的驗證放在 L1 `helpers.map_overlays.declared_overlays()`（不合格式 ⇒ 不列、記 ERROR），沒有放進 loader（不因覆蓋層宣告寫錯而整個模組載入失敗）。〕

〔更正 LG-M1（D 審）：原設計只說「地圖頁載入模組腳本」，沒有定義兩者介面、腳本路徑由提供者回傳。原句保留如下（刪除線），新設計接在後面〕

- ~~新串接點 **`map.overlay`**（provider，多提供者；登記 INTEGRATION-POINTS，編號列車定）：L1 `GET /api/map/config` 多回 `overlays: [{key, label, script}]`，由已載入模組的 provider 提供；地圖頁依清單顯示按鈕並載入該模組的前端腳本（`modules/lodging/pages/lodging-overlay.js`）。~~
- ~~對方不在時：清單沒有這一項 ⇒ 地圖頁沒有按鈕（功能未安裝，不是「0 筆」）；直接打模組端點 ⇒ 既有「模組未載入」提示。~~
- ~~底圖規則：旅宿標記是官方開放資料座標，畫在 Google 或 OSM 底圖都不涉及 Google 內容；**中心點**若是 Google 定位，只會在 `google_basemap()` 為真時產生（L1 保證），因此不會出現「Google 座標畫在 OSM 底圖」。~~
- ~~顯名：面板底部固定顯示觀光署顯名聲明；Google 底圖時不得蓋住 Google logo（GOOGLE-BASEMAP §3、§7.2 #1）。~~

#### 3.6.1 L1 地圖覆蓋層契約（新串接點 `map.overlay`，已登記 INTEGRATION-POINTS「IP-101（暫定）」，編號列車定；兩處內容相同，以 INTEGRATION-POINTS 為準）

**原則**：L2 腳本**只准**經下列 L1 介面碰地圖；不得讀寫 map.html 的 Alpine 元件、`_map`、`_layer`、`_gmMarkers`、`L`、`google.maps` 物件
（第十五班 a-gm-raw：`_map` 從 Alpine 讀回來是 Proxy，Google 不認——內部欄位不是契約）。

| 項目 | 內容 |
|---|---|
| 提供方 | 任何 L2（首個：`lodging`） |
| 使用方 | L1 地圖頁 `frontend/pages/map.html`＋新的 L1 轉接層 `frontend/static/map-overlay.js` |
| 形式 | ①模組 `module.json` 宣告（**不經** `core.registry` provider）＋②前端 JS 註冊 |
| 後端語法 | 模組在 `module.json` 宣告 `"map_overlays": [{"key": "lodging", "label": "附近旅宿", "script": "lodging-overlay.js"}]`（`script` 只能是檔名，位於模組 `pages/` 底下）；L1 `/api/map/config` 回 `overlays: [{key, label, script_url}]`——**`script_url` 由 L1 依已載入模組的宣告組出同源路徑**（`/modules/<key>/pages/<檔名>` 之類，格式隨階段 C 的頁面路徑），提供者不回傳任何網址；檔名不合 `^[a-z0-9-]+\.js$` 或檔案不存在 ⇒ 不列、記 ERROR |
| 前端語法 | 腳本載入後呼叫 `window.MotrixMapOverlay.register(key, {mount(api), unmount()})`；使用者按該覆蓋層的按鈕 ⇒ L1 呼叫 `mount(api)`；再按或離頁 ⇒ `unmount()`，L1 清掉該覆蓋層所有標記 |
| `api`（L1 提供，Leaflet 與 Google 各自實作在 L1 轉接層） | ~~`addMarkers(list, style) -> handle`（`list`：`[{id, lat, lng, title, popupHtml}]`；…；popupHtml 由 L1 以純文字＋白名單標籤清洗）~~〔更正 LG2-S1／S2〕`addMarkers(list, style) -> handle`：**`handle` 是不透明字串**（L1 內部表的鍵；Google／Leaflet 物件永遠只留在 L1，覆蓋層把 handle 存進任何狀態再交回都不受 Proxy 影響）；`list`：`[{id, lat, lng, title, popup: {title, lines: [字串], links: [{label, href}]}}]`——**彈窗由 L1 以結構化欄位自己組 DOM（textContent），覆蓋層不交 HTML**；`href` 只收同源相對路徑或 `https:`；`style`：`{icon: 'hotel'｜'homestay'｜'center', color: 語意 token 名}`；**大量標點由 L1 群聚**（OSM＝既有 markercluster、Google＝既有 @googlemaps/markerclusterer），覆蓋層不自己處理；`focus(handle, id)`：移到該點並開彈窗（清單點一筆用）；`addCircle(center, radius_m, style) -> handle`：畫搜尋半徑；`clear(handle?)`、`fitTo(handle)`、`center() -> {lat, lng, source} | null`（地圖頁目前的「目前位置」，沒有則 null）、`onBasemapReady(cb)`、`onMarkerClick(handle, cb(id))`、`panel(title) -> HTMLElement`（L1 給一個側邊容器，覆蓋層只在裡面畫自己的 UI；容器位置由 L1 保證不蓋 Google logo 與資料歸屬）、`basemap() -> 'google'｜'osm'` |
| 回傳／錯誤 | `mount` 丟例外 ⇒ L1 在該覆蓋層面板顯示「附近旅宿載入失敗」、其他覆蓋層與地圖照常 |
| 對方不在時 | 模組未載入 ⇒ `overlays` 沒有這一項 ⇒ 沒有按鈕（功能未安裝，不是 0 筆）；直接打模組端點 ⇒ 既有「模組未載入」提示 |
| 契約版本 | 1（加方法＝相容；改名／改參數＝版本 +1，並寫 core CHANGELOG） |
| 守門 | ①兩種底圖（OSM 真的 Leaflet、Google 用既有攔截的假 `google.maps`）各跑一次合成覆蓋層：`addMarkers`／`clear`／`fitTo`／`panel` 都生效；②**反向控制**：把 map.html 的 `_map`／`_layer` 等內部欄位改名後，合成覆蓋層照常（證明它沒碰內部）；③靜態掃描：`modules/*/pages/*overlay*.js` 不得出現 `_map`、`_layer`、`_gm`、`Alpine`、`__x`、`google.maps`、`L.`；④`script_url` 一律是 L1 組出的同源路徑：提供者宣告 `https://…`、`../x.js`、不存在的檔 ⇒ 不列（反向控制三種）；⑤合成的第二個覆蓋層（非 lodging）也能註冊——守門不綁 lodging（MODULE-GUIDE §7）；⑥〔LG2-S1〕合成覆蓋層把 handle 存進 Alpine `reactive` 再交回 `clear`／`focus` ⇒ 照常（兩種底圖）；⑦〔LG2-S2〕`focus`、`addCircle`、500 點群聚兩種底圖各一題；彈窗 `lines` 內含 `<img onerror>` ⇒ 顯示為文字；`href` 為 `javascript:`／`//evil` ⇒ 不產生連結；⑧〔LG2-S3〕custom-records 的 JS 寫入點守門（`tests/test_custom_records_no_js_html_sink_2026_09_28.py` 的 sink_sites／check）掃描對象擴到 `modules/*/pages/*overlay*.js`，白名單預設 0（覆蓋層畫面板清單只准 textContent／createElement）；正對照：合成覆蓋層寫 `innerHTML` ⇒ 紅 |

- ~~底圖規則（不變）：旅宿標記是官方開放資料座標，畫在 Google 或 OSM 底圖都不涉及 Google 內容；中心點若是 Google 定位，只會在 `google_basemap()` 為真時產生（L1 保證），且依 LG-M2 不保存。~~
  〔更正 LG2-M1：「L1 保證」不成立（範圍要呼叫端包）。改為：旅宿標記是官方開放資料座標，任何底圖可顯示（Q1 裁示 ff3b1e14）；中心點的定位與距離計算包在 `geo.map_request_scope(頁面底圖, missing="osm")` 內，頁面是 osm 或沒帶就不會用到 Google（§3.1.1）；是 Google 時依 LG-M2 不保存〕
- 顯名：見 §3.6.2。

#### 3.6.2 顯名範圍（LG-S2）
- 出現官方資料的**每一個畫面與輸出**都帶附件格式顯名：地圖覆蓋層面板、旅宿紀錄頁、比較頁、紀錄匯出（CSV／JSON）、列印。
- 格式：「交通部觀光署 {年份} 旅館民宿 - 觀光資訊資料庫（觀光資料標準 V2.1）　此開放資料依政府資料開放授權條款 (Open Government Data License) 進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。　政府資料開放授權條款：https://data.gov.tw/license」
- `{年份}` 取該批（紀錄頁＝該筆紀錄）的 `dataset_updated_at` 年份，不寫死；同一畫面混有多批 ⇒ 列出各年份。
- 顯名文字由模組一支函式產生（前後端共用同一份模板字串來源），不各處手寫。

### 3.7 守門（實作時一起寫）
| 守什麼 | 做法 |
|---|---|
| 不自動連線 | 載入模組、開地圖頁、開面板、查詢：攔截 socket ⇒ 0 次對外連線（正對照：按「更新」且開關開 ⇒ 1 次） |
| 開關與速率 | 開關關 ⇒ 下載端點拒絕且不連線；24 小時內第二次 ⇒ 拒絕、不連線；並行兩個 ⇒ 只有一個連線 |
| 失敗≠0 筆 | 下載失敗／沒有快照 ⇒ 回應帶 `unavailable`，畫面文字不同於「半徑內沒有旅宿」 |
| 顯名（LG-S2） | 覆蓋層面板、紀錄頁、比較頁、CSV／JSON 匯出、列印**逐一**含顯名全文，且年份＝該批 `dataset_updated_at` 年份（造兩批不同年份 ⇒ 兩個年份都出現）；拿掉任一處 ⇒ 紅 |
| ~~Google 座標 30 天~~ | ~~造一筆 31 天前 `center_source='google'` ⇒ 清除工作後 lat/lng 為 NULL；`nominatim`／`device` 不動（反向控制）~~〔更正 LG-M2：改為下一列〕 |
| Google 中心點不保存（LG-M2） | 以 `center_source='google'` 存一筆紀錄 ⇒ `lodging_searches.center_lat/lng` 為 NULL、所有 `lodging_search_items.distance_m` 為 NULL、每日 JSON 匯出裡也沒有；反向控制：`nominatim`／`device` 來源照存座標與距離 |
| 解壓驗證（LG-S3） | 合成 zip：多一個檔名、`../x`、絕對路徑、解壓超過上限 ⇒ 各自拒絕且舊快照不變 |
| 錯值價格（LG-S4） | 價格 5 與 200,000 ⇒ 不參與排序、回應帶原值與 `price_suspect: true`；300 與 100,000 邊界各一題 |
| 登記時間（LG-S1） | 每筆價格帶 `price_registered_at`；比較兩筆同價 ⇒ 回 `official_unchanged: true` |
| 不存個資欄位 | 匯入後 `lodging_catalog` 沒有電話／統編／經營者欄；哨兵值不出現在任何表 |
| 邊界 | 模組不 import 其他 L2（既有 `test_module_boundaries`）；刪模組資料夾 ⇒ 地圖頁無按鈕、其餘測試照常 |
| 覆蓋層契約（LG-M1） | 見 §3.6.1 守門 ①～⑤ |
| 價格標示 | 回應每筆價格帶 `price_kind`（`official_reference`／`manual`），畫面標籤依它顯示；不可以沒有種類 |

### 3.8 步驟清單（E2 實作，依序）
1. `docs/platform/modules.json` 登記 `lodging`；建 `backend/modules/lodging/`（module.json：data 分類、license_key、pages、provides.api_prefixes `/api/lodging`、probes、customization；README／CHANGELOG 1.0.0／SPEC）。
2. migration 0001：四張表（SQL 寫在檔內，不 import 會演進的碼、不自己 commit）。
3. `source.py`：下載＋驗證（大小、zip 內只有預期檔、JSON 結構）＋整批替換 `lodging_catalog`（`core.txn.write_txn`）＋速率狀態。〔LG-S3：加檔名白名單、zip slip、解壓上限〕
4. `search.py`：bbox 預篩＋haversine、類別與半徑過濾、錯值價格標記。
5. `api.py`：`GET /api/lodging/status`（probe，純讀）、`POST /api/lodging/refresh`（superadmin）、`POST /api/lodging/search`（收 `basemap`，LG2-M1）、`POST /api/lodging/records`、`GET /api/lodging/records[/{id}]`、`POST /api/lodging/quotes`、`GET /api/lodging/compare?a=&b=`。
6. `__init__.py`：`ModuleSpec(routers, runtime_switches=[MOTRIX_LODGING_FETCH], startup_notices)`；覆蓋層改在 `module.json` 宣告 `map_overlays`。~~`__init__.py`：`ModuleSpec(routers, runtime_switches=[MOTRIX_LODGING_FETCH], startup_notices, providers={"map.overlay": …})`；30 天清除走 IP-11 `daily.check`（每日 08:00，不另開排程）。~~〔更正 LG-M2：不需要 30 天清除；LG-M1：覆蓋層不經 provider 回傳腳本〕
7. L1（**先做、獨立一個 commit**）：`geo.map_request_scope`＋map_points 改用它（LG2-M1，§3.1.1）；`static/map-overlay.js`（`MotrixMapOverlay.register` 與 `api`，Leaflet／Google 兩套實作）；`/api/map/config` 依已載入模組的 `map_overlays` 宣告組 `overlays`；map.html 顯示按鈕、只經契約 mount／unmount；loader 驗 `map_overlays` 格式；INTEGRATION-POINTS 登記 §3.6.1；CORE 版號＋CHANGELOG；§3.6.1 守門 ①～⑤。~~L1：`/api/map/config` 加 `overlays`（`registry.providers("map.overlay")`）；map.html 顯示按鈕並載入腳本；INTEGRATION-POINTS 登記；CORE 版號＋CHANGELOG（L1 介面新增）。~~
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
                price_kind="official_reference",
                price_suspect=not (PRICE_SANE_MIN <= (r["price_low"] or 0) <= PRICE_SANE_MAX)) for r in rows]
    # 存紀錄時：center_source == geo.SOURCE_GOOGLE ⇒ center_lat/lng、distance_m 寫 NULL（LG-M2）
    return sorted((r for r in out if r["distance_m"] <= radius_m), key=lambda r: r["distance_m"])

# source.py —— 唯一對外連線
def refresh(conn, now):
    if not fetch_on():            return unavailable("switch_off")
    if not rate_ok(conn, now):    return unavailable("rate_limited", next_at=...)
    with single_flight_lock():    # 檔案鎖；拿不到 ⇒ 回「更新中」
        blob = http_get(URL, max_bytes=50 << 20, timeout=60)
        files = safe_unzip(blob, allow=ZIP_ALLOWED_NAMES, max_total=200 << 20)  # LG-S3：白名單、zip slip、解壓上限
        hotels = parse_and_validate(files["HotelList.json"])   # 結構不對 ⇒ 例外、舊快照不動
        with write_txn(conn): replace_catalog(conn, hotels)
        record_success(conn, now, hotels.update_time)
```

## 4. 交 D 審查點〔D 審結果 2026-09-28，見 AUDIT-D-E1-lodging.md §4〕
- Q1 觀光署座標「GOOGLE為主」是否影響我們保存與在 OSM 底圖顯示（§1.1.4）。〔使用者裁示（CORE-SPEC ff3b1e14）：採用此判讀——官方座標照常保存、任何底圖可顯示、依授權顯名；風險＝來源停更 ⇒ 畫面標資料日期（§3.5 已有）〕
- Q2 旅宿電話是否顯示（民宿多為個人手機；目前設計不存不顯示）。〔D：同意不存、不顯示〕
- Q3 Google 中心點 30 天後：只清座標，或連距離一起清（§3.3）。〔LG-M2：座標與距離都不存〕
- Q4 查詢紀錄的可見範圍（預設建立者＋admin+）。〔D：同意；地址文字照 IP-97〕
- Q5 參考房價錯值門檻（< 300 或 > 100,000）。〔LG-S4：具名常數＋原值灰字〕
- Q6 `map.overlay` 串接點放進 L1（CORE 小版號新增）是否可以，或改成模組自己的頁面、不動 map.html。〔LG-M1：可以，先定義 §3.6.1 契約；LG2-S1～S3 補強〕

## 5. 未查證
- Agoda、Expedia、trivago、Amadeus 條款原文（JS 渲染／429）。
- Overpass 在台灣的旅宿筆數與標籤覆蓋（三次連線失敗）。
- 交通部 TDX 觀光 API（要會員金鑰）：全國檔已足，未查。

## 6. 取證檔雜湊（LG-S5）

原始檔在 E 線 session scratchpad（不進 repo：Booking／Airbnb 頁面 1 MB 級且含其網站程式碼）。以下是 **2026-09-28 抓取當下**的 sha256（`sha256sum`）與檔案時間；
⚠ HTML 頁每次抓會因動態內容（session、追蹤碼）而雜湊不同 ⇒ 雜湊用來證明「當時看到的就是這一份」，日後比對條款改版請比對上文的逐字引文，不比雜湊。

| 抓取時間 | sha256 | 檔 | 網址 |
|---|---|---|---|
| 16:31 | 3f7c2a1140f2ab6688cc0bf39857cd45f680658d5dd1c58daa9f98cd6f5f3f65 | ds_7780.json | https://data.gov.tw/api/v2/rest/dataset/7780 |
| 16:33 | b8332b101b8e23ec19edf45b7d41e95d8b7d95c243af3971bcb50142c7a28c55 | lic.html | https://data.gov.tw/license |
| 16:32 | 553485810a98d0d77d3a1a3183ade382f0fab0af481d0c86c7bbf093f225ead5 | hotel.zip（Last-Modified: Mon, 28 Sep 2026 06:30:52 GMT） | https://media.taiwan.net.tw/XMLReleaseAll_public/v2.0/Zh_tw/Hotel-json.zip |
| 16:32 | e212394b7f980ff9ccbcf8af37e3caa7588ad817360736d9bd275befb174e795 | std21.pdf | https://media.taiwan.net.tw/Upload/觀光資料標準V2.1.pdf |
| 16:34 | 936c9bfc9fdc58444035c0bce214100562b268aa20cde54da2345b7ed405543e | all.csv（資料集清單） | https://data.gov.tw/datasets/export/csv |
| 16:34 | 2c3463b46faaea21ff7cb748d2e092a17685d52b5add06ee6ec659876fc599e9 | copyright.html | https://www.openstreetmap.org/copyright |
| 16:34 | b8d8aebb21bf405f93f6e21bbf0d8f0a749844f9812ec58692f189add6402b47 | odbl.html | https://opendatacommons.org/licenses/odbl/1-0/ |
| 16:34 | 44e82168e569de77e94331f7ced27e2ffc7023d1d521c10fb3a04f8543cd18d7 | ovwiki.html | https://wiki.openstreetmap.org/wiki/Overpass_API |
| 16:34 | 664ae364690159d960ea919539a9e399f773aaa2ada8c751a53795f4d7a54785 | ovcommons.html | https://dev.overpass-api.de/overpass-doc/en/preface/commons.html |
| 16:39 | 509cf1b7b713644466b2672567ecdcabe08ed52c549b393180168b321ad8019f | tghotel.html | https://wiki.openstreetmap.org/wiki/Tag:tourism%3Dhotel |
| 16:39 | 6dd18d14432b6d9be8e1148cfb761a810111f8039fb042bb644d32d3bbdd32b3 | tgguest.html | https://wiki.openstreetmap.org/wiki/Tag:tourism%3Dguest_house |
| 16:36 | 505495cbc6859b78bbce17e5accdeba1082386352d24ca69dc63fb0d9109a4a8 | booking.html | https://www.booking.com/content/terms.en-gb.html |
| 16:36 | 956ae96b03270ba9b5d60aeecac6b6c3f026459d60bbbde539045300d2e8eddd | airbnb.html | https://www.airbnb.com/help/article/2908 |
| 16:39 | 61c157b9b17d7fbe122fad8e77fb1be6541bdfd90f72a9c189382448695aaf15 | bkdemand.html | https://developers.booking.com/demand/docs/getting-started/prerequisites |
