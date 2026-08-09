# 監控系統選型導覽 — 內容維運手冊

> 這是「選型資料庫」眾多產品類別中的**監控系統**這一類（IP 攝影機／NVR，未來可加車牌辨識、
> 人流分析等進階分析功能）。跨類別的總索引、分類邏輯、提需求格式見
> [SELECTION-DB-INDEX.md](./SELECTION-DB-INDEX.md)。

---

## 這份文件怎麼用

跟 `ENV-GUIDE-CONTENT.md`／`NETARCH-GUIDE-CONTENT.md`／`SWITCH-GUIDE-CONTENT.md` 一樣：你提供
素材（新情境、新分類、要修正的適配判斷、產品連結），我負責研究、判斷放哪個情境/分類、寫進
資料庫（透過 `/pages/monitor-guide.html` 的管理後台或 `/api/monitor-guide/*`，不改
`monitor_guide_seed.py`——那份 seed 檔只在資料庫是空的時候執行一次）。

---

## §1 · 這個類別的資料形狀

跟交換器選型導覽同一種資料形狀——**「相機分類 × 場域情境」的矩陣交叉**，因為監控系統跟交換器
一樣，分類本身沒有演進順序（子彈型不會「進化」成 PTZ，兩者是不同定位），而是同一個分類在不同
情境下適配度不同：

- **場域情境**（monitor_scenarios）：OFFICE／RETAIL／WAREHOUSE／FACTORY／OUTDOOR，描述監控
  場域的典型需求（隱蔽性、涵蓋範圍、防護等級、嚇阻力）
- **相機分類**（monitor_categories）：BULLET／DOME／TURRET／PTZ／PANORAMIC，欄位：
  | 欄位 | 說明 |
  |------|------|
  | key_specs | 核心規格說明 |
  | tags | 標籤，逗號分隔 |
  | price_range | 建議售價區間（需標明查價年月） |
  | dependency_note | 依賴／相關備註 |
  | watch_note | 注意事項／地雷 |
- **適配矩陣**（monitor_fit）：情境 × 分類的交叉點，`fit_level`（適合／可用／不建議）+ `fit_note`
- **分類 → 產品**（monitor_products）：一個分類掛多個品牌型號，`specs_json` 結構化規格欄位
  （`[["規格名","值"], …]`），格式與 switch-guide/netarch-guide 相同

**重要相依性**：所有 UniFi Protect 產品都需要搭配一台執行 Protect 應用程式的 UniFi OS Console
（如 Cloud Gateway／Dream Machine／NVR），純相機本身不能獨立錄影運作，這點已寫進每個分類的
`watch_note` 或 `dependency_note`。

**與門禁系統的邊界**：車牌辨識這類需求，實際觸發開閘動作要看門禁系統的 GATE_CONTROLLER 分類；
本類別的相機只負責影像擷取與 AI 偵測，不涉及開閘邏輯。

---

## §2 · 目前主力品牌

| 品牌 | 強項 | 官網 |
|------|------|------|
| UniFi（Ubiquiti） | G6 世代全形式相機（子彈/半球/砲塔/PTZ/全景），需搭配 UniFi OS Console | store.ui.com、techspecs.ui.com |
| Hikvision | 全球最主流專業監控品牌，全系列涵蓋子彈/半球/砲塔/PTZ/全景五種形式，ColorVu 全彩夜視與 AcuSense AI 偵測為特色，需搭配 Hikvision NVR/主機錄影 | hikvision.com（美規經銷商查價：a1securitycameras.com／networkcamerastore.com／surveillance-video.com） |

其餘品牌（Dahua／Reolink／Axis 等）待有實際需求時再補。新增品牌時，順手補進這張表。

---

## §3 · 待處理清單

（目前空白，之後累積在這裡；格式同 `SWITCH-GUIDE-CONTENT.md`）

---

## §4 · 已知缺口／待確認

- Hikvision 目前每個分類只有 1 款代表型號，尚未比照 Omada Wi-Fi 6 的深度擴充做法補齊完整產品線
- G6 Dome 只列了標準款，高階款 G6 Pro Dome（US$499，更高解析度/更遠 IR 距離）尚未建立獨立產品項
- 尚未涵蓋 NVR/錄影主機本身的選型（本類別目前只涵蓋相機，NVR 容量/通道數規劃留待有實際需求時再開）
- RETAIL／FACTORY 情境目前只是初版判斷，尚未有實際專案案例驗證，之後有真實案源請回來校正
  `fit_note`

---

## §5 · 變更記錄

### 2026-08-09b — 新增 Hikvision 品牌（第二個品牌，可跨品牌比較）
- 使用者要求每個類別都要有多品牌深度，委派 subagent（`SELECTION-DB-INDEX.md` §3.1 流程）研究
  一個資料公開透明、適合跟 UniFi 對照的品牌，選定 Hikvision（全球最主流專業監控品牌）
- 5 個分類各補 1 款：BULLET → DS-2CD2T47G2-LSU/SL、DOME → DS-2CD2147G2-LSU、
  TURRET → DS-2CD2347G2-LU、PTZ → DS-2DE4425IW-DE、PANORAMIC → DS-2CD6365G0E-IVS，皆用
  WebSearch 查證美規經銷商（a1securitycameras.com／networkcamerastore.com／
  surveillance-video.com）真實規格與售價（2026-08 查價）
- Hikvision 走 ColorVu 全彩夜視＋AcuSense AI 偵測路線，與 UniFi Protect 的紅外夜視＋
  Multi-TOPS AI 形成技術路線對照

### 2026-08-09 — 類別上線（選型資料庫第四個類別）
- DB v39：新增 `monitor_scenarios`／`monitor_categories`／`monitor_fit`／`monitor_products`
  （相機分類 × 場域情境矩陣，與交換器選型導覽同一種資料形狀，`specs_json` 直接隨建表加入）
- 第一批資料：5 個場域情境（辦公室/機房、零售店面、物流倉儲、工廠產線、戶外/周界/停車場）
  × 5 個相機分類（子彈型、半球型、砲塔型、雲台變焦、全景型），25 組適配矩陣全數填滿
- 第一批產品連結：UniFi G6 Bullet／G6 Dome／G6 Turret／G6 PTZ／G6 180，皆用 WebSearch 查證
  techspecs.ui.com 真實規格與售價（2026-08 查價）
- 前端 `frontend/pages/monitor-guide.html`：以交換器選型導覽為範本（依情境查看／對照矩陣總覽／
  規格比較／管理後台 CRUD 全數沿用，非最小上線版本）
- 側邊欄／users.html 新增 `monitor_guide`／`monitor_guide_edit` 模組旗標；audit-log.html／
  module-versions.html 同步補上
