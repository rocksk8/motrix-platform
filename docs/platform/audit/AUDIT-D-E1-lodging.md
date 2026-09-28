# 稽核：E1 地圖附近旅宿——來源調查與設計（wip/e-lodging e2d794f9，LODGING-NEARBY.md）（D，2026-09-28）

> 依據：CORE-SPEC「地圖附近旅宿（新功能，第 E 線）」（09888e19）。只審文件。
> 條款引文由 D 獨立重抓原始頁比對（2026-09-28，curl 只讀，去標籤後比對、不經摘要）；Booking.com、Airbnb 沒有重抓（見 §1）。

## 0. 結論

- **必修 2、建議 5；Q1～Q6 的意見見 §4。**
- 來源判斷正確：觀光署全國檔（政府開放授權、可商用可保存、必須顯名）；Overpass 公開站依條款排除；不爬訂房網站；照實說「免費即時價格不存在」並提出替代——與 CORE-SPEC 的限制①～⑤一致。

## 1. 條款引文查證（主持指定）

| 引文 | 出處 | 結果 |
|---|---|---|
| 政府資料開放授權條款 二(一)「…不限目的、時間及地域、非專屬、不可撤回、免授權金進行利用…」 | data.gov.tw/license | 逐字相符 |
| 二(二)「使用者得再轉授權他人為前項之利用。」 | 同上 | 逐字相符 |
| 三(二)「未盡顯名標示義務者，視為自始未取得開放資料之授權。」 | 同上 | 逐字相符 |
| 附件顯名聲明「此開放資料依政府資料開放授權條款 (Open Government Data License) 進行公眾釋出…」 | 同上 | 相符（空白差異除外） |
| 資料集 7780：title、`"license": "1"`、`座標地圖:GOOGLE為主`、Hotel-json.zip | data.gov.tw/api/v2/rest/dataset/7780 | 相符 |
| Overpass「Commercial use should use self-hosted or paid Overpass servers.」「If you have an app or website, then the usage counts towards the sum of requests made by all your users.」「less than 10,000 queries per day…」 | wiki.openstreetmap.org/wiki/Overpass_API | 相符；**原頁句尾有註腳編號 [2]、[5]，文件引用時省略了**，文字本身沒有改動 |
| OSM「You are free to copy, distribute, transmit and adapt our data, as long as you credit…」 | openstreetmap.org/copyright | 相符 |
| Booking.com A15.2／A15.3、Airbnb Terms | — | **D 沒有重抓**（這兩站常是 JS 渲染或擋機器人）。E 附了網址與版本日期（Airbnb「Last Updated: February 5, 2026」），可以查。它們在設計裡的作用是「不做」的理由，不影響任何會實作的行為 |

- 取證方式（curl＋去標籤、自己讀、scratchpad 留原始檔）符合〈會截斷的指令不可以當事實來源〉。建議把原始檔的 sha256 與抓取時間寫進文件，日後條款改版時比得出來（LG-S5）

## 2. 必修

**LG-M1（必修）　`map.overlay` 讓 L2 的腳本直接寫進 L1 地圖頁，但沒有定義兩者之間的介面**
- 設計：`/api/map/config` 回 `overlays: [{key, label, script}]`，地圖頁載入該模組的前端腳本（`modules/lodging/pages/lodging-overlay.js`），由它畫面板與標記
- 缺的兩件事：
  1. **沒有定義腳本可以用的 L1 介面**。旅宿標記要同時畫在 Leaflet 與 Google 底圖上；而地圖頁剛因 Alpine Proxy 出過事（`_map` 讀回來是 Proxy，Google 不認，a-gm-raw）。沒有明定介面，L2 腳本只能伸手進 map.html 的內部（`this._map`、`_gmMarkers`、Alpine 狀態）⇒ L1 頁面的每一次內部重構都會靜默弄壞 L2，而且模組測試測不到（反方向的隱性相依）
  2. **腳本路徑由提供者回傳**：L1 要限制它只能是該模組自己宣告的靜態路徑（module.json 宣告，同源），不能讓任何提供者回傳任意網址叫地圖頁載入
- 修法（設計層）：
  - 定義 L1 的地圖覆蓋層 JS 介面（例：`window.MotrixMapOverlay.register(key, {mount(api), unmount()})`；`api` 提供 `addMarkers(list, style)`、`clear()`、`fitTo()`、`center()`、`onBasemapReady()`，兩種底圖各自實作在 L1 轉接層），寫進 INTEGRATION-POINTS 當契約
  - L2 腳本只准用這個介面
  - `script` 由 L1 依 module.json 宣告的路徑產生，提供者不回任意字串
  - 題：兩種底圖都畫得出覆蓋層；把介面以外的內部欄位改名 ⇒ 覆蓋層照常
- 這也回答 Q6：放進 L1 可以，前提是有這份契約；沒有契約的話，改成模組自己的頁面比較安全，但會失去「在地圖上手動開啟」這個使用者要求

**LG-M2（必修）　Google 定位的中心點座標存進 T1 表，「30 天後清除」清不到每日備份**
- 設計：`center_source='google'` 的 `center_lat/lng` 存在 `lodging_searches`，30 天後由 daily.check 清空
- 但 `lodging_searches` 是 T1，會進每日 JSON 匯出／備份，而月備份永久保留 ⇒ Google 經緯度會在備份裡超過 30 天（SST §6.3）
- 這正是 SST-M1 已經裁示過的同一件事：「Google 來源座標任何底圖都不寫進 profile——profile 永久保存、進每日備份，而 Google 經緯度最多快取 30 天，清不到這裡」（3587fe41）
- 修法：
  - `center_source='google'` 時**不存** center_lat/lng（只存輸入的地址文字、來源、精度）
  - distance_m 同理不存（它由 Google 座標算出；回查時要距離就用免費來源重算，或顯示「中心點為 Google 定位，距離不保存」）
  - 30 天清除工作與那條守門就不需要了（更簡單）
  - 補題：google 來源的查詢存檔後，表裡沒有座標與距離；nominatim／device 照存（反向控制）

## 3. 建議

- **LG-S1　參考房價的時效要到「每一筆」**：資料集每天更新，但每筆 `UpdateTime` 從 2025-02 到 2026-09 都有 ⇒ 畫面只標「資料日期」會讓一年半前登記的房價看起來是今天的。每筆價格旁邊標「業者登記於 YYYY-MM」；比較兩筆紀錄時，若官方參考房價兩次相同，也要標「官方登記未變動」，不要讓人讀成「價格沒漲」
- **LG-S2　顯名要涵蓋所有會顯示官方資料的地方**：除了面板、匯出、列印，還有「旅宿紀錄」頁與比較頁（`lodging_search_items` 是官方資料的衍生物）。顯名聲明依附件格式帶上「[年份] [資料集名稱與版本]」——年份取該批的 `dataset_updated_at`，不寫死。守門題對每一個畫面與輸出都驗
- **LG-S3　下載驗證加解壓上限與路徑檢查**：50 MB 限的是下載大小；zip 解開後要另設上限（例如 200 MB），並拒絕 zip 內的絕對路徑或 `..`（zip slip）。「zip 內只有預期檔」要寫成白名單
- **LG-S4　錯值門檻（Q5）**：300／100,000 可以用，但要做成具名常數＋題。錯值不參與排序時，原值仍要以灰字顯示「官方登記值：5」，不要整個藏起來，使用者才知道是資料錯、不是系統漏了
- **LG-S5　取證檔進 repo 或記雜湊**：原始檔留在 E 線 scratchpad，視窗結束就沒了。把條款頁的 sha256、抓取時間與網址記進文件（或放進 docs/platform/evidence/），日後查得到當時看到的是哪一版

## 4. Q1～Q6

| # | D 意見 |
|---|---|
| Q1 座標「GOOGLE為主」 | 同意 E 的判讀：我們依政府開放授權取得，授權方是機關，不是 Google 的客戶，也沒有呼叫 Google；它在 SST §6.2 的意義下不是「Google Maps Content」。殘餘風險是來源可能被停止提供（授權 §五），設計已處理（舊快照照用＋標日期）。這屬於法律判斷，**建議主持在 CORE-SPEC 記一列「採用此判讀」**，讓它有人做過決定（〈守門要驗有沒有人做過決定〉），不需要擋設計 |
| Q2 電話 | 同意不存、不顯示（民宿多為個人手機；不存就沒有個資外洩的出口）。需要時改顯示「請至觀光署資料查詢」的連結 |
| Q3 Google 中心點 | 見 LG-M2：乾脆不存座標與距離 |
| Q4 紀錄可見範圍 | 同意預設建立者＋admin+；地址文字照 IP-97 處理 |
| Q5 錯值門檻 | 見 LG-S4 |
| Q6 map.overlay | 見 LG-M1：可以，但要先定義 L1 覆蓋層 JS 介面與腳本路徑規則 |
