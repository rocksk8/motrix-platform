# 門禁系統選型導覽 — 內容維運手冊

> 這是「選型資料庫」眾多產品類別中的**門禁系統**這一類（讀頭／控制主機／閘道控制器）。跨類別的
> 總索引、分類邏輯、提需求格式見 [SELECTION-DB-INDEX.md](./SELECTION-DB-INDEX.md)。

---

## 這份文件怎麼用

跟其他三份內容手冊一樣：你提供素材（新情境、新分類、要修正的適配判斷、產品連結），我負責
研究、判斷放哪個情境/分類、寫進資料庫（透過 `/pages/access-guide.html` 的管理後台或
`/api/access-guide/*`，不改 `access_guide_seed.py`——那份 seed 檔只在資料庫是空的時候執行一次）。

---

## §1 · 這個類別的資料形狀

跟交換器選型導覽／監控系統選型導覽同一種資料形狀——**「元件分類 × 場域情境」的矩陣交叉**：

- **場域情境**（access_scenarios）：SINGLE_DOOR／MULTI_DOOR_OFFICE／WAREHOUSE_DOCK／
  GATE_GARAGE／RETROFIT_EXISTING，描述門禁部署場景的典型限制（門數、供電條件、既有配線）
- **元件分類**（access_categories）：ALLINONE_HUB／MULTI_DOOR_HUB／READER／GATE_CONTROLLER／
  ACCESSORY（2026-08-10 新增，見下方說明），欄位：
  | 欄位 | 說明 |
  |------|------|
  | key_specs | 核心規格說明 |
  | tags | 標籤，逗號分隔 |
  | price_range | 建議售價區間（需標明查價年月） |
  | dependency_note | 依賴／相關備註 |
  | watch_note | 注意事項／地雷 |
- **適配矩陣**（access_fit）：情境 × 分類的交叉點，`fit_level`（適合／可用／不建議）+ `fit_note`
- **分類 → 產品**（access_products）：一個分類掛多個品牌型號，`specs_json` 結構化規格欄位

**重要相依性**：UniFi Access 是讀頭＋控制主機＋軟體三件式架構，**所有分類都需要一台執行 UniFi
Access App 的 UniFi OS Console**（如 Cloud Gateway／Dream Machine）才能運作，非純硬體獨立系統，
這點已寫進每個分類的 `watch_note`。`READER` 分類的產品**不能單獨運作**，必須搭配
`MULTI_DOOR_HUB`（或既有第三方控制器）才能控制門鎖。

**與監控系統的邊界**：`GATE_CONTROLLER` 若需要車牌辨識觸發開閘，鏡頭與辨識能力要另外搭配監控
系統選型導覽的相機（見該文件 §1），本類別的控制器本身不含影像辨識能力，只負責繼電器輸出。

**`ACCESSORY` 分類的定位（2026-08-10 新增）**：電子鎖（陽極鎖/磁力鎖）、開門按鈕、開關電源
供應器、感應卡片、控制器專用網卡/PoE模組等週邊配件，跟其餘 4 個分類「門禁決策主體」（讀頭/
控制主機）的選型邏輯不同，是配套耗材/週邊。新增品牌的配件產品時歸這一類；比較同分類產品時
留意子類型差異（鎖具 vs 按鈕 vs 電源 vs 卡片 vs 網卡模組），不要跨子類型直接比較數值規格。

---

## §2 · 目前主力品牌

| 品牌 | 強項 | 官網 |
|------|------|------|
| UniFi（Ubiquiti） | 讀頭＋控制主機＋雲端軟體三件式架構，需搭配 UniFi OS Console | store.ui.com、techspecs.ui.com |
| Akuvox | IP 門禁/對講整合商常用品牌，同樣走 PoE＋雲端（SmartPlus）管理路線；**無獨立的閘道/車庫
  控制器產品**，車輛出入需用 UHF 長距離讀頭或既有終端機繼電器輸出觸發第三方欄杆機 | akuvox.com（美規經銷商查價：akuvoxdealer.com／lowvoltagedealer.com） |
| SOYAL（茂旭資訊） | 台灣老牌門禁系統廠商，傳統 RS-485/Wiegand 有線架構（非 PoE＋雲端路線），產品線最完整
  （讀頭/一體機/多門控制器/配件皆有），官網不公開定價；**無獨立的閘道/車庫控制器商品化型號**，
  車道應用是用多門控制器＋I/O擴充模組＋第三方欄杆機組成系統整合方案 | soyal.com.tw |

其餘品牌（HID／Kisi／Brivo 等傳統門禁廠牌）待有實際需求時再補。新增品牌時，順手補進這張表。

---

## §3 · 待處理清單

（目前空白，之後累積在這裡；格式同 `SWITCH-GUIDE-CONTENT.md`）

---

## §4 · 已知缺口／待確認

- `MULTI_DOOR_HUB`／`READER`／目前部分型號（EAH-8、Reader Pro、Hub Gate）官網未列牌價，
  `price_note` 標記「洽詢報價」，之後有實際報價案例請回來補上區間
- `GATE_CONTROLLER` 分類目前仍只有 UniFi Hub Gate 一款（Akuvox／SOYAL 皆查證確認無獨立閘道/
  車庫控制器商品化硬體，車道應用各自要用其他分類產品＋第三方欄杆機組成系統整合方案）
- `ACCESSORY` 分類目前只有 SOYAL 一個品牌（7 款），UniFi／Akuvox 的對應配件（如 UniFi 的
  Ultra Door Lock 系列電鎖）尚未收錄，之後有需求再補以達成跨品牌比較
- RETAIL／WAREHOUSE_DOCK 情境目前只是初版判斷，尚未有實際專案案例驗證，之後有真實案源請回來
  校正 `fit_note`

---

## §5 · 變更記錄

### 2026-08-10 — 新增 SOYAL 品牌＋新建 ACCESSORY 分類（第五個分類）
- 使用者要求門禁系統補 SOYAL（台灣廠商）的卡機/配件/控制器，委派 background subagent 深度研究
  soyal.com.tw（傳統多層 PHP 型錄網站，逐一點入產品詳細頁確認非停產型號，非只看列表頁摘要）
- **READER**（3 款）：AR-101-U／AR-723-U／AR-721-K，皆為純讀頭（無繼電器輸出，只輸出訊號給
  外部控制器判斷）
- **ALLINONE_HUB**（3 款）：AR-725-H（觸控背光鍵盤）／AR-837-EF9DO（指紋型）／AR-837-EA
  （臉部辨識型），分類依據是這些型號官網明確標示「門鎖繼電器輸出」可單機獨立判斷開鎖，功能上
  對應一體式讀頭主機而非純讀頭
- **MULTI_DOOR_HUB**（3 款）：AR-716-E16（16門）／AR-716-E18（18門）／AR-716-E16-1608R-PU
  （10門中控式後備電源款）
- **GATE_CONTROLLER**：查證後確認 SOYAL 無獨立閘道/車庫控制器商品化型號（車道應用是用多門
  控制器＋I/O擴充模組＋第三方欄杆機組成系統整合方案），未硬湊，據實記錄於 §4
- **新增 `ACCESSORY` 分類**（7 款）：磁力鎖180磅/600磅、防盜陽極鎖、紅外線開門按鈕、100W開關
  電源供應器、感應卡片、控制器專用網卡+PoE模組（DMOD-POE1204B）。這類配件跟既有 4 分類「門禁
  決策主體」的選型邏輯不同（詳見 §1 說明），5 個場域情境的適配矩陣全數補上（GATE_GARAGE 為
  「可用」，其餘「適合」）
- SOYAL 為傳統 RS-485/Wiegand 有線架構，與 UniFi/Akuvox 的 PoE+雲端管理路線是不同技術路線，
  同分類比較時注意通訊介面與是否需要額外主機/App 的差異
- 準備了 `backend/sync_2026-08-10_soyal_access.py`（用程式從資料庫匯出產生）供正式機套用更新
  後執行，補齊 ACCESSORY 分類（既有類別新增分類/內容不會隨部署包自動同步）

### 2026-08-09b — 新增 Akuvox 品牌（第二個品牌，可跨品牌比較）
- 使用者要求每個類別都要有多品牌深度，委派 subagent（`SELECTION-DB-INDEX.md` §3.1 流程）研究
  一個資料形狀類似（PoE＋雲端管理）、適合跟 UniFi Access 對照的品牌，選定 Akuvox
- 3 個分類各補 1 款：ALLINONE_HUB → Akuvox A02、MULTI_DOOR_HUB → Akuvox A095（4 門控制器，
  需外接讀頭）、READER → Akuvox ACR-CRM11，皆用 WebSearch 查證美規經銷商
  （akuvoxdealer.com／lowvoltagedealer.com）真實規格與售價（2026-08 查價）
- `GATE_CONTROLLER` 分類查證後確認 Akuvox 無對應硬體產品，未硬湊，據實記錄於 §4

### 2026-08-09 — 類別上線（選型資料庫第五個類別）
- DB v40：新增 `access_scenarios`／`access_categories`／`access_fit`／`access_products`
  （元件分類 × 場域情境矩陣，與交換器/監控系統選型導覽同一種資料形狀，`specs_json` 直接隨建表
  加入）
- 第一批資料：5 個場域情境（單一門禁、多門辦公室、倉儲出入口、車輛閘門/車庫、既有配線改裝）
  × 4 個元件分類（一體式讀頭主機、多門控制器、獨立讀頭、閘道/車庫控制器），20 組適配矩陣全數
  填滿
- 第一批產品連結：UniFi Access Ultra／Retrofit Hub 2／Enterprise Access Hub／Reader Lite／
  Reader Pro／Hub Gate，皆用 WebSearch 查證 techspecs.ui.com 真實規格（2026-08 查價，部分型號
  官網未列牌價標記「洽詢報價」）
- 前端 `frontend/pages/access-guide.html`：以交換器選型導覽為範本（依情境查看／對照矩陣總覽／
  規格比較／管理後台 CRUD 全數沿用，非最小上線版本）
- 側邊欄／users.html 新增 `access_guide`／`access_guide_edit` 模組旗標；audit-log.html／
  module-versions.html 同步補上
