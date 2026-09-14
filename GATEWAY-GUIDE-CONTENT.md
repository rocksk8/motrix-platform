# 閘道器與控制器選型導覽 — 內容維運手冊

> 這是「選型資料庫」眾多產品類別中的**路由器／閘道器與硬體控制器**這一類。跨類別的總索引、
> 分類邏輯、提需求格式見 [SELECTION-DB-INDEX.md](./SELECTION-DB-INDEX.md)。

---

## 這份文件怎麼用

跟其他選型導覽一樣：你提供素材（新情境、新分類、要修正的適配判斷、產品連結），我負責研究、
判斷放哪個情境/分類、寫進資料庫（透過 `/pages/gateway-guide.html` 的管理後台或
`/api/gateway-guide/*`，不改 `gateway_guide_seed.py`——那份 seed 檔只在資料庫是空的時候執行一次）。

---

## §1 · 這個類別的資料形狀

跟交換器／監控系統／門禁系統選型導覽同一種資料形狀——**「閘道器/控制器分類 × 場域情境」的
矩陣交叉**：

- **場域情境**（gateway_scenarios）：OFFICE／RETAIL／WAREHOUSE／FACTORY／OUTDOOR，與其他選型
  導覽共用同一套情境定義（描述安裝環境的典型限制）
- **產品分類**（gateway_categories）：OMADA_GW_WIRED／OMADA_GW_WIFI／OMADA_GW_4G5G／
  OMADA_GW_INTEGRATED／OMADA_CONTROLLER，欄位同其他選型導覽（key_specs/tags/price_range/
  dependency_note/watch_note）
- **適配矩陣**（gateway_fit）：情境 × 分類的交叉點，`fit_level`（適合／可用／不建議）+ `fit_note`
- **分類 → 產品**（gateway_products）：一個分類掛多個品牌型號，`specs_json` 結構化規格欄位

**與交換器選型導覽的邊界**：本類別收「路由/閘道器」（負責 WAN 連線、路由、VPN）與「硬體控制器」
（集中管理 Omada AP/交換器/閘道器），交換器選型導覽只收「交換器」本身，兩者是網路架構中不同
層級的設備，故獨立成類而非塞進 switch_categories。

**分類命名沿用 `OMADA_` 前綴慣例**：與交換器選型導覽 2026-08-10 的決策一致——這 5 個分類是
Omada 品牌自己的官方系列分級（非跨品牌通用能力分級），之後若要新增其他品牌的路由器/控制器，
先評估是否適合塞進既有 5 個分類，只有品牌自己有一套官方分級且使用者明確要求保留時，才比照
新增 `品牌前綴_系列名` 的專屬分類。

---

## §2 · 目前主力品牌

| 品牌 | 分類定位 | 官網 |
|------|---------|------|
| TP-Link（Omada） | 全 5 個分類皆有產品，路由器/閘道器產品線含 Fusion Gateway（訂閱制整合閘道，含控制器+監控功能，尚未收錄，見 §4）| omadanetworks.com |

其餘品牌（UniFi UDM／Aruba Instant On Router／Cisco Meraki MX 等）待有實際需求時再補。新增
品牌時，順手補進這張表。

---

## §3 · 待處理清單

（目前空白，之後累積在這裡；格式同 `SWITCH-GUIDE-CONTENT.md`）

---

## §4 · 已知缺口／待確認

- **Fusion Gateway 系列未收錄**：Omada 另有 Fusion／Fusion Pro／Fusion Max 三個訂閱制整合閘道
  系列（內建控制器＋視訊管理系統，官網強調「統一管理」「快速部署」），與本次收錄的 Standard
  Gateway（純路由/VPN功能，一次性購買無訂閱費）商業模式不同，本輪未收錄，待有實際專案需求時
  再研究是否需要獨立分類（訂閱制 vs 一次性購買的成本結構差異大，不建議直接併入現有分類）
- OMADA_GW_WIFI／OMADA_GW_INTEGRATED 兩個分類目前官網都只有單一型號（ER706W／ER7212PC），
  選型彈性小，非資料遺漏，是 Omada 這兩條產品線目前確實較新/較窄
- 尚無 5G（僅 4G+ Cat6）型號，OMADA_GW_4G5G 分類名稱保留 5G 字樣是為未來擴充預留
- 所有情境 fit_note 皆為初版判斷，尚未有實際專案案例驗證，之後有真實案源請回來校正

---

## §5 · 變更記錄

### 2026-08-10 — 類別上線（選型資料庫第六個類別）
- 使用者反映選型資料庫沒有路由器/控制器選項，要求派發本機研究管道搜尋 Omada 對應產品線；
  詢問使用者分類架構決策後（新建獨立類別 vs 併入交換器選型導覽），採用前者
- DB v41：新增 `gateway_scenarios`／`gateway_categories`／`gateway_fit`／`gateway_products`
  （閘道器/控制器分類 × 場域情境矩陣，資料形狀與 switch_guide/monitor_guide/access_guide 相同）
- 用 `backend/tools/local_research_pipeline.py` 抓 omadanetworks.com 5 個分類頁面（Wired／
  Wi-Fi／4G-5G Wi-Fi／Integrated Gateways + Hardware Controllers），共抽出 15 款真實型號
  （ER605/ER7206/ER7406/ER707-M2/ER7412-M2/ER8411、ER706W、ER703WP-4G-Outdoor/
  ER706WP-4G/ER706W-4G、ER7212PC、OC200/OC220/OC300/OC400），型號規格與 TP-Link 官方命名
  規則吻合，人工核對後寫入
- 5 個分類、25 組情境適配矩陣全數填滿；`price_note` 全數為「官網未列價格，需洽代理商」
  （omadanetworks.com 路由器/控制器頁面同交換器頁面，未公開牌價）
- 前端新增 `frontend/pages/gateway-guide.html`（以 monitor-guide.html 為範本複製，含
  2026-08-10 新增的深連結定位／全域搜尋功能，非最小上線版本）；`selection-db-overview.html`
  補上第 6 個區塊；側邊欄／users.html 新增 `gateway_guide`／`gateway_guide_edit` 模組旗標；
  `claude` 自動化帳號（開發機+正式機 `create_claude_account.py`）補上 `gateway_guide_edit`
- **待辦**：此為開發機資料，正式機部署套用程式碼更新後（DB v41 migration 會自動建表並灌入
  第一批 seed 資料，這批屬於全新類別不需額外同步腳本），需執行
  `backend/create_claude_account.py` 確認 claude 帳號模組旗標已更新（冪等腳本會提示手動補模組）
