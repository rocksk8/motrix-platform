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
- **元件分類**（access_categories）：ALLINONE_HUB／MULTI_DOOR_HUB／READER／GATE_CONTROLLER，
  欄位：
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

---

## §2 · 目前主力品牌

| 品牌 | 強項 | 官網 |
|------|------|------|
| UniFi（Ubiquiti） | 讀頭＋控制主機＋雲端軟體三件式架構，需搭配 UniFi OS Console | store.ui.com、techspecs.ui.com |

目前僅 UniFi 一個品牌（本次新增），其餘品牌（HID／Kisi／Brivo 等傳統門禁廠牌）待有實際需求時
再補。新增品牌時，順手補進這張表。

---

## §3 · 待處理清單

（目前空白，之後累積在這裡；格式同 `SWITCH-GUIDE-CONTENT.md`）

---

## §4 · 已知缺口／待確認

- `MULTI_DOOR_HUB`／`READER`／目前部分型號（EAH-8、Reader Pro、Hub Gate）官網未列牌價，
  `price_note` 標記「洽詢報價」，之後有實際報價案例請回來補上區間
- 目前只有 UniFi 一個品牌，尚無法做跨品牌規格比較
- 電鎖／門禁五金（磁力鎖、電插鎖）本身不在本類別範圍內，選型時仍需另外評估搭配的機械五金
- RETAIL／WAREHOUSE_DOCK 情境目前只是初版判斷，尚未有實際專案案例驗證，之後有真實案源請回來
  校正 `fit_note`

---

## §5 · 變更記錄

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
