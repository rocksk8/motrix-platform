# 網路交換器選型導覽 — 內容維運手冊

> 這是「選型資料庫」眾多產品類別中的**商用/工業網路交換器**這一類。跨類別的總索引、分類邏輯、
> 提需求格式見 [SELECTION-DB-INDEX.md](./SELECTION-DB-INDEX.md)。

---

## 這份文件怎麼用

跟 `ENV-GUIDE-CONTENT.md`／`NETARCH-GUIDE-CONTENT.md` 一樣：你提供素材（新情境、新分類、要修正的
適配判斷、產品連結），我負責研究、判斷放哪個情境/分類、寫進資料庫（透過 `/pages/switch-guide.html`
的管理後台或 `/api/switch-guide/*`，不改 `switch_guide_seed.py`——那份 seed 檔只在資料庫是空的時候
執行一次）。

---

## §1 · 這個類別的資料形狀

跟無人載具的「情境×分層×三級」、網路架構的「族系×世代演進×產品」都不一樣，交換器是
**「產品分類 × 行業情境」的矩陣交叉**——分類本身沒有演進順序（Smart 不會「進化」成 L3，
兩者是不同定位），而是同一個分類在不同情境下適配度不同：

- **行業情境**（switch_scenarios）：OFFICE／RETAIL／WAREHOUSE／FACTORY／OUTDOOR，描述安裝環境的
  典型限制（空間、共用網路、PoE 需求、溫控）
- **產品分類**（switch_categories）：UNMANAGED／SMART_L2PLUS／MANAGED_L3／INDUSTRIAL，欄位：
  | 欄位 | 說明 |
  |------|------|
  | key_specs | 核心規格說明 |
  | tags | 標籤，逗號分隔 |
  | price_range | 建議售價區間（需標明查價年月） |
  | dependency_note | 依賴／相關備註 |
  | watch_note | 注意事項／地雷 |
- **適配矩陣**（switch_fit）：情境 × 分類的交叉點，`fit_level`（適合／可用／不建議）+ `fit_note`
  （為什麼這個情境適合/不適合這個分類的具體判斷）——這是本類別的核心資料，瀏覽 UI 依此排序/上色
- **分類 → 產品**（switch_products）：一個分類掛多個品牌型號，跟 netarch-guide 的產品連結同構，
  同樣有 **`specs_json`** 結構化規格欄位（`[["規格名","值"], …]`），瀏覽頁「規格比較」按鈕邏輯
  與 netarch-guide 共用同一套 JS helper（`parseSpecs`/`specKeysFor`/`isBestInRow`）

**與場域選型導覽的邊界**：INDUSTRIAL 分類與 env-guide 的場域門檻高度重疊。本類別的 INDUSTRIAL
只作「這個情境大概需要工業級」的起點判斷，**實際專案的精確規格（溫度/IP/認證）一律回頭查
場域選型導覽對應場域**，不在這裡重新展開一次，避免兩份資料以後各自更新而失準。

---

## §2 · 目前主力品牌

| 品牌 | 分類定位 | 官網 |
|------|---------|------|
| TP-Link（含 Omada） | 非網管入門機種、Smart/L2+ 桌上型 | tp-link.com、omadanetworks.com |
| UniFi（Ubiquiti） | Smart/L2+ 桌上/機架型，雲端/App 管理 | store.ui.com |
| Aruba（HPE Instant On） | 全網管 L2/L3 機架式，中小企業定位 | arubainstanton.com |
| Sbjlink | 工業導軌型（沿用場域選型導覽已驗證型號） | sbjlink.com |
| Moxa | 工業導軌型，國際品牌知名度高 | moxa.com |
| Cisco Business／Catalyst 1200 | 非網管／Smart／L3 Lite 全系列，**無需訂閱授權**、終身硬體保固 | cisco.com |
| Cisco IE-1000 | 工業導軌型，輕網管，客戶指名度高（品牌辨識度優勢） | cisco.com |
| Hirschmann（Belden） | 工業導軌型老牌，SPIDER III 系列以耐用/認證完整著稱，價位高於 Sbjlink/Moxa | hirschmann.com |
| HPE Aruba Networking（CX 系列） | 企業級 L2+/L3 機架式，**與 Aruba Instant On 是不同產品線**（不同報價/支援管道，勿混淆） | hpe.com |
| Netgear | 入門非網管/桌上型交換器（GS308），也有真 L3 動態路由的 M4350 系列 | netgear.com |

**Cisco 系列注意**：Business／Catalyst 1200 這條產品線（非 Meraki）**不需要雲端訂閱授權**，`price_note`
即為完整成本，跟 netarch-guide 的 Cisco Meraki（需另計授權年費）是不同商業模式，報價時不要混淆。

新增品牌時，順手補進這張表。

---

## §3 · 待處理清單

（目前空白，之後累積在這裡；格式同其他兩份手冊）

---

## §4 · 已知缺口／待確認

- INDUSTRIAL 分類的 Sbjlink 型號沿用 env-guide 已驗證的 RPT-M1810GP-T-X2，未針對「交換器選型」情境
  重新核對是否有更適合一般工業場景（非 AMR 專用）的型號/包裝
- RETAIL、FACTORY 情境目前只是初版判斷，尚未有實際專案案例驗證，之後有真實案源請回來校正
  `fit_note`

---

## §5 · 變更記錄

### 2026-08-09 — MANAGED_L3 補 UniFi（品牌缺口補齊）
- 使用者提出「新增 UniFi」需求，§4 記錄的「MANAGED_L3 只有 Aruba 一個品牌」缺口這次一併處理
- 新增 **UniFi Pro 24 PoE**（US$699，24 埠 GbE＋2×10G SFP+，PoE 預算 400W，完整 L3）作為中階代表、
  **UniFi Enterprise 48 PoE**（US$1,599，48 埠 2.5GbE＋4×10G SFP+，PoE 預算 720W，本分類目前埠數
  與 PoE 預算最高的選項）作為大型代表，兩款皆用 WebSearch 查證 techspecs.ui.com／官網通路真實規格
  與售價，非憑印象填入
- **注意**：Enterprise 48 PoE 在 techspecs.ui.com 已被標記為「Vintage」，`price_note` 已註記提醒
  下單前向代理商核實現貨/是否已有後續機種，避免報價後才發現停產
- MANAGED_L3 現有 4 個品牌（Aruba／Cisco／HPE Aruba／Netgear）＋ UniFi，共 5 個品牌可比較

### 2026-07-30p — 規格比較寬度公式重算
- 同步修正（詳見 NETARCH-GUIDE-CONTENT.md §5 同日條目）：`compareBoxWidth()` 公式從
  `220+n×165`（上限1500）改為 `220+n×250`（上限2600），欄位最小寬度 170→220px，
  用 `javascript_tool` 實測確認表格內容寬度與容器寬度的落差從 32% 縮小到 5%

### 2026-07-30o — 產品規格改為預設全部展開顯示
- 同步 netarch-guide 的修法（詳見該文件 §5 同日條目）：每個產品項目下方直接展開顯示完整
  `specs_json` 內容，不必點「規格比較」才看得到單一產品的規格細節

### 2026-07-30n — 用 Chrome 實際打開頁面檢查，抓到真的視覺 bug
- 同一輪修正，詳見 NETARCH-GUIDE-CONTENT.md §5 同日條目——這幾輪的驗證從來沒真正在瀏覽器
  打開頁面看過，全靠 curl/node 檢查邏輯正確性，結果售價備註被裁切、型號斷字這種一眼就看得到
  的問題完全沒發現
- 產品項目改成兩行顯示（品牌+型號一行，售價備註獨立一行），修正 `.prod-item` 的
  `white-space`/`overflow-wrap` 設定；實測交換器各分類的長型號（如 Hirschmann SPIDER III
  SSL20-8TX）與長售價備註都能完整顯示

### 2026-07-30m — 進階搜尋 + 全域檢視
- 與 netarch-guide 同步（詳見該文件 §5 同日條目）：產品清單加搜尋框（品牌/型號/規格 key+value
  即時過濾，排除「無/不支援」開頭的否定敘述避免搜「PoE」誤中不支援 PoE 的款式）；比較 Modal
  改為 92vh 固定高度 flex 版面，標題/工具列固定、僅表格區域捲動，產品欄標題加大並加 accent 色條，
  比照報價單 PDF 預覽的全螢幕呈現方式

### 2026-07-30l — 規格比較加入「勾選比較對象」
- 同一輪用戶端視角檢視，詳見 NETARCH-GUIDE-CONTENT.md §5 同日條目——問題核心是深度擴充後
  單一分類最多到 11 款產品，全部一起比較資訊量過大，且清單原本不是依品牌排序
- 加了勾選框（勾 2 項以上才會只比較所選，否則預設比較全部）+ 全選/清除快捷鍵 + 已選數量提示；
  比較 Modal 寬度改吃選取後的產品數；產品清單改依「品牌→售價由低到高」排序（`sort_order` 直接
  在資料庫重排，不是前端排序）

### 2026-07-30k — 同品牌產品線深度擴充
- 使用者要求：同一品牌在同一分類下實際常有 4-5 款不同規格的產品（例如埠數不同），這些都該納入資料庫
  並且能清楚區分，不能只放單一代表型號
- 4 個分類、每個既有品牌都補了 2-3 款同系列不同規格的實際型號（皆為 WebSearch 查證真實存在，非憑印象）：
  - **非網管**：TP-Link 補 TL-SG1016／TL-SG1024；Cisco 補 CBS110-24T；Netgear 補 GS305／GS316；
    D-Link 補 DGS-1016D／DGS-1024D
  - **Smart/L2+**：UniFi 補 Switch Lite 16 PoE；Omada 補 TL-SG2428P；Cisco 補 CBS250-16P-2G／
    CBS250-24FP-4X；Zyxel 補 GS1200-5HP／GS1200-8HP
  - **全網管 L3**：Aruba 補 Instant On 1960 48G；Cisco 補 1200-8P-E-2G／1200-48P-4X；HPE Aruba
    補 CX 6100 48G 4SFP+（並把原本籠統的「CX 6100」條目改為具體的 12G 型號，不再用模糊描述代表整條產品線）
  - **工業導軌**：Sbjlink 補 RPT-1010GP-2F-X2／RPT-1005-X4；Moxa 補 EDS-205A／EDS-208A；
    Cisco 補 IE-1000-8P2S-LM；Hirschmann 補 SPIDER-PL-20-16T／SPIDER-PL-30-24T
- 同系列不同埠數的型號用「埠數」欄位自然區分，比較表的「該列最高值」標記在埠數/PoE預算等量化欄位上
  能正確反映同品牌內部的大小規格差異（如 UNMANAGED 分類 11 款產品裡，D-Link/Cisco/TP-Link 的 24 埠
  款會一起在「埠數」列被標為並列最高值）
- 資料量變大後重新驗證規格比較與「只顯示差異」邏輯（`verify_compare3.js`／`verify_diffonly2.js`），
  4 個分類皆無誤判

### 2026-07-30j — 規格比較表視覺改版 + 版本紀錄補登 + 補品牌
- 規格比較表視覺改版（sticky 表頭/欄、斑馬紋、hover 高亮、最高值改底色+icon、「只顯示有差異的規格」
  開關）與 netarch-guide 同步，詳見該文件 §5 同日條目
- **版本紀錄補登**：`backend/version_manifest.json` 之前完全沒有本模組的條目，已補回上線以來完整歷史。
  **⚠️ 之後每次異動都要記得同步補一筆進 `version_manifest.json`**，這是站內「版本紀錄」頁面的
  唯一資料來源，跟這份 CONTENT.md 是兩個獨立的東西
- UNMANAGED 新增 **D-Link DGS-1008D**（US$30~140）→ 3→4 品牌；SMART_L2PLUS 新增
  **Zyxel GS1200-8**（洽詢報價）→ 3→4 品牌——4 個分類現在都有 4 個品牌可比較

### 2026-07-30i — 依資料庫現況補品牌缺口
- 做法改成先查 `SELECT COUNT(DISTINCT brand)` 找出最弱分類再搜尋，詳見 NETARCH-GUIDE-CONTENT.md §5 同日條目
- MANAGED_L3 新增 **Netgear M4350-24G4XF**（洽詢報價，128Gbps／95.23Mpps），是本分類唯一支援完整
  RIP/OSPF/PIM 動態路由的選項，跟既有兩款的 L2+/L3 Lite 形成明顯對比 → 3→4 品牌
- 目前最弱兩類：**UNMANAGED（3）、SMART_L2PLUS（3）**，下次優先補這裡

### 2026-07-30h — 修正世代代號誤判 + 新增 HPE Aruba CX 6100／Netgear GS308
- `parseLeadingNumber` 修正邏輯與 netarch-guide 同步（見該文件 §5 同日條目）
- MANAGED_L3 新增 **HPE Aruba CX 6100**（洽詢報價，PoE 預算最高 740W，注意這是 Aruba 的新一代
  企業主力線，跟既有的 Instant On 1960 是不同產品線/不同報價支援管道）；
  UNMANAGED 新增 **Netgear GS308**（US$21~35，此類別目前最低價品牌）——兩分類現在都有 3 個品牌
- 本輪 Ollama 建議的 4 個品牌全數查無實據，捨棄未採用，詳見 NETARCH-GUIDE-CONTENT.md §5 同日條目

### 2026-07-30g — 比較表寬度改用 CSS min() + 新增 Hirschmann
- 比較 Modal 寬度邏輯與 netarch-guide 同步修正（見該文件 §5 同日條目）
- INDUSTRIAL 分類新增 **Hirschmann SPIDER III SSL20-8TX**（Belden，UL 認證，非 PoE 入門款），該分類現有
  4 個品牌可比較。詳見 NETARCH-GUIDE-CONTENT.md §5 同日條目關於本機 Ollama 腦力激盪品牌名單的查證教訓
  （建議清單有兩個錯誤，只採用查證屬實的部分）

### 2026-07-30f — 規格比較表寬度自適應 + 新增 Cisco 品牌
- 規格比較 Modal 寬度改依產品數量動態計算，不再固定 1000px，邏輯與 netarch-guide 共用
- **新增 Cisco 品牌**，4 個分類各補一款：UNMANAGED → CBS110-8T-D（US$55~95）、
  SMART_L2PLUS → CBS250-8T-E-2G（無 PoE，另有 CBS250-8P-E-2G PoE 版可選，未來可再補）、
  MANAGED_L3 → Catalyst 1200-24P-4G（US$700~1,000，PoE+ 195W）、INDUSTRIAL → IE-1000-4T1T-LM
  （US$545，-40~70°C，IP30）
- 每個分類現在至少 2 個品牌可比較

### 2026-07-30e — 結構化技術規格 + 規格比較功能（DB v33）
- `switch_products` 新增 `specs_json` 欄位；管理後台的產品 Modal 新增可增減列的規格 key-value 編輯器
- 6 款既有產品全數補上規格（埠數/PoE 埠數與預算/交換容量/管理層級/防護等級/認證等，依產品性質而定）
- 瀏覽模式每個分類卡片「對應產品」區塊加「規格比較」按鈕，與 netarch-guide 同一套比較邏輯
  （欄=產品，列=規格聯集，數值型規格自動加粗同列最高值）

### 2026-07-30d — 類別上線
- DB v32：新增 `switch_scenarios`／`switch_categories`／`switch_fit`／`switch_products`
  （產品分類 × 行業情境矩陣，非族系演進、非場域三級——選型資料庫第三種資料形狀）
- 第一批資料：5 個行業情境（辦公室/機房、零售店面、物流倉儲、工廠產線、戶外/路側基礎設施）
  × 4 個產品分類（非網管、Smart/L2+、全網管 L2/L3、工業導軌寬溫），20 組適配矩陣全數填滿
- 第一批產品連結：TP-Link TL-SG1008P、UniFi Switch Lite 8 PoE、TP-Link Omada TL-SG2210P、
  Aruba Instant On 1960 24G、Sbjlink RPT-M1810GP-T-X2、Moxa EDS-P510A-8PoE-2GTXSFP-T
- 前端 `frontend/pages/switch-guide.html`：瀏覽模式兩個子視圖——「依情境查看」（點情境→分類卡片
  依適配度排序，適合在前不建議在後）、「對照矩陣總覽」（情境×分類完整矩陣表，色塊快速掃視）；
  管理模式為 4 張表的 CRUD 後台
- 側邊欄／users.html 新增 `switch_guide`／`switch_guide_edit` 模組旗標；比照 env-guide/netarch-guide
  慣例，**無**模組通知 badge
