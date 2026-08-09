# 網路架構選型導覽 — 內容維運手冊

> 這是「選型資料庫」眾多產品類別中的**網路架構**這一類（Wi-Fi、行動網路 4G/5G，未來可加乙太網路
> 速率、PoE 供電標準、交換器管理層級…）。跨類別的總索引、分類邏輯、提需求格式見
> [SELECTION-DB-INDEX.md](./SELECTION-DB-INDEX.md)。

---

## 這份文件怎麼用

跟 `ENV-GUIDE-CONTENT.md` 一樣：你提供素材（新族系、新世代、產品連結、要修正的舊資料），
我負責研究、判斷放哪個族系/世代、寫進資料庫（透過 `/pages/netarch-guide.html` 的管理後台或
`/api/netarch-guide/*`，不改 `netarch_guide_seed.py`——那份 seed 檔只在資料庫是空的時候執行一次）。

---

## §1 · 這個類別的資料形狀

跟無人載具的「情境×分層×三級」不一樣，網路架構是**「技術族系 → 世代演進 → 產品」**：

- **技術族系**（netarch_families）：一條世代演進的軸線，例：Wi-Fi 無線網路、行動網路（4G/5G）
- **世代／規格**（netarch_generations）：族系底下依序排列的世代，欄位：
  | 欄位 | 說明 |
  |------|------|
  | gen_name | 世代名稱，如「Wi-Fi 7」「5G Sub-6」 |
  | key_specs | 核心規格（頻寬/速率/延遲等，看族系而定） |
  | upgrade_note | 相對上一代的關鍵進步；第一代填「（基準世代）」 |
  | typical_scenario | 典型適用情境（一句話） |
  | tags | 標籤，逗號分隔，供未來分類/篩選用（如「高密度,企業級,未來性」） |
  | price_range | 建議售價區間（新台幣或美金皆可，標明幣別） |
  | dependency_note | 依賴／相關備註——這代需要搭配什麼才能發揮，或跟其他世代/類別的關聯（如「需 PoE++ 供電」「建議搭配 Sub-6 做基礎覆蓋」） |
  | watch_note | 注意事項／地雷 |
- **世代 → 產品**（netarch_products）：一個世代掛多個品牌型號（brand/model/url/label/price_note）

**排序很重要**：`sort_order` 決定世代演進的先後順序，畫面上是照這個順序橫向排列成對照卡片，
不需要另外做「世代 A 對比世代 B」的邏輯——同族系內天然就是一條時間軸。

---

## §2 · 目前主力品牌

| 品牌 | 強項 | 官網 |
|------|------|------|
| UniFi（Ubiquiti） | Wi-Fi AP（U6/U7 系列）、交換器、路由器，全線 | store.ui.com、techspecs.ui.com |
| Omada（TP-Link） | Wi-Fi AP（EAP 系列，2026-08-09 深度擴充至吸頂/牆插/戶外近 20 款）、SDN 雲端管理 | omadanetworks.com |
| Peplink | 行動網路路由器（MAX BR/Transit 系列）、SD-WAN、多 WAN 綁定 | peplink.com |
| Netgear | 行動熱點路由器（Nighthawk M 系列）、Orbi Mesh、商用 Insight 雲端管理 | netgear.com |
| Ruckus | 企業級 Wi-Fi AP（R 系列），內建 BLE/Zigbee IoT | ruckusnetworks.com |
| Teltonika | 工業級蜂巢路由器（RUT/RUTM 系列），偏物聯網/M2M 取向 | teltonika-networks.com |
| Cisco／Cisco Meraki | Cisco 為蜂巢閘道器（IR/Catalyst 系列）；Cisco Meraki 是獨立的雲端管理 Wi-Fi AP 產品線（MR/CW9 系列，訂閱授權制），**兩者是不同 brand 欄位值，勿混淆** | cisco.com、meraki.cisco.com |
| Askey／Inseego／ZTE | 電信通路蜂巢 CPE／MiFi 熱點，多為電信客製化產品，官網通常未列公開牌價 | askey.com、inseego.com、zte.com.cn |

新增品牌時，順手補進這張表。

---

## §3 · 待處理清單

（目前空白，之後累積在這裡；格式同 ENV-GUIDE-CONTENT.md）

---

## §4 · 已知缺口／待確認

- ~~Wi-Fi 6E 目前尚無具體對應產品~~ 已補：UniFi U6-Enterprise（三頻含 6GHz）已掛在 Wi-Fi 6E 世代下
  （2026-08-09 校正，此條缺口記錄本身已過時，實際資料庫早於此之前就已補上，只是文件沒同步更新）；
  Omada 的 6E 專屬型號仍待查
- 4G LTE 世代目前掛的是 Peplink MAX BR1 Pro 5G 的降頻相容資訊，尚無獨立的純 LTE 型號連結
- 乙太網路速率（1G/2.5G/10G）、PoE 供電標準（802.3af/at/bt）、交換器管理層級（L2/L2+/L3）
  三個潛在新族系尚未建立，等你有具體需求再開

---

## §5 · 變更記錄

### 2026-08-09e — Omada 官網完整品項總表掃描（不篩選重複，力求 1:1 對應）
- 使用者反映即使做完第二輪深度擴充，Omada 官網還是有很多品項沒收錄——上一輪 agent 自己承認
  因為「規格跟已列的重疊」主動篩選跳過了 EAP650 D30/D120-Outdoor、EAP603-Outdoor、
  EAP650-Desktop／EAP650GP-Desktop、EAP653／EAP653 UR、EAP673 等型號，這次改派 agent
  直接逐一造訪 omadanetworks.com 的吸頂/牆插/戶外/桌上型/GPON 分類頁面，不因「看起來重複」
  就篩選，力求官網列表與資料庫 1:1 對應
- **Wi-Fi 6** 補 8 款：EAP673、EAP653、EAP653 UR（天花板系列）、EAP650 D120-Outdoor／
  EAP650 D30-Outdoor（指向性天線變體）、EAP603-Outdoor、EAP650-Desktop／EAP650GP-Desktop
  （桌上型/GPON），該世代現有 **20 款**
- **Wi-Fi 6E** 查證後確認官網僅 EAP690E HD 一款，未新增（非缺漏，是真的只有這一款）
- **Wi-Fi 7** 補 9 款：EAP770／EAP783／EAP727／EAP723／EAP720（天花板系列，涵蓋入門到旗艦
  BE22000）、EAP725-Wall（牆插）、EAP772-Outdoor／EAP775-Outdoor／EAP725-Outdoor（戶外），
  該世代現有 **13 款**
- Omada 品牌在 `netarch_products` 現有 **34 筆**（`netarch_products` 全體共 77 筆）
- **已知範圍外，留待之後有需求再處理**：官網另有「Wireless Bridge」分類 7 款（Sector
  Bridge 5、Flex Bridge 5、Beam Bridge 5 UR KIT 等），是點對點無線橋接器，跟一般用戶端 AP
  定位不同，未計入本次（若要收錄建議另立分類/家族，不要硬塞進現有 WIFI 家族）；官網也還有
  Wi-Fi 5/4 世代舊機型仍在售（EAP225／EAP225-Outdoor／EAP235-Wall／EAP110-Outdoor），本類別
  目前只涵蓋 Wi-Fi 6/6E/7，未往前擴充涵蓋舊世代

### 2026-08-09c — 全品牌深度擴充第二輪（使用者要求「每個項目都要完整」）
- 使用者指出光靠「每個品牌補 1-2 款代表款」還不夠完整，舉例 Omada Wi-Fi 6 實際產品線遠超過
  當時的 2-4 款；改用 `SELECTION-DB-INDEX.md` §3.1 流程，針對剩餘薄弱品牌各自委派 subagent
  深入查證，這次全數寫入資料庫（netarch_products 從約 30 筆擴充到 60 筆）：
  - **Omada Wi-Fi 6**：重新深度研究，新增 10 款（吸頂型 EAP610/613/620 HD/660 HD/683 UR、
    牆插型 EAP615-Wall/655-Wall、戶外型 EAP610-Outdoor/625-Outdoor HD/650-Outdoor），連同既有
    EAP670/EAP650，Wi-Fi 6 世代現有 **12 款**，涵蓋吸頂/牆插/戶外三種安裝型態與入門到旗艦價位帶
  - **Ruckus**：Wi-Fi 6/6E 各補 1 款（R350／R560），Wi-Fi 7 世代原本完全沒有型號，新增 R770
  - **Teltonika**：4G LTE 新增 RUT200，5G Sub-6 新增 RUTM50；5G mmWave 查證後確認全產品線
    皆無 mmWave 機種，未硬湊
  - **Askey／Inseego／ZTE**：三個原本各只有 1 款的品牌，各補 1-2 款（Askey 4G LTE+5G Sub-6、
    Inseego 5G Sub-6〔MiFi 8000 因已停產未收錄〕、ZTE 4G LTE+5G mmWave）
  - **Cisco／Cisco Meraki**：Cisco 5G mmWave 查證後確認官方文件明列插拔模組不支援 mmWave
    （FR2），未新增；4G LTE／5G Sub-6 各補 1 款不同定位型號；Cisco Meraki 三個 Wi-Fi 世代
    各補 1 款，形成該品牌內部的高中低階對照
- 部分查證結果據實回報「查無實據，不新增」而非硬湊（Peplink mmWave、Teltonika mmWave、
  Cisco mmWave），符合 §3.1 訂下的查證標準

### 2026-08-09b — Omada／Peplink 型號深度擴充（委派 subagent 研究）
- 使用者反映 Omada／Peplink／Netgear 產品線資料太薄弱，比照 `SELECTION-DB-INDEX.md` §3.1 新訂的
  「委派 subagent 研究、只回傳結構化摘要」流程處理
- **Omada**：Wi-Fi 6 世代原本掛的「EAP670 等 WiFi 6 系列」是模糊佔位資料（非真實單一型號），已刪除
  並用 **EAP670**（US$155~170，中高階 AX5400）＋ **EAP650**（US$89.99~121.99，入門 AX3000）兩款
  具體型號取代；Wi-Fi 7 世代新增 **EAP787**（US$249.99，旗艦款，10G 上行埠、8-Stream）與
  **EAP775-Wall**（約US$250~280，牆插式，適合會議室/客房）；Wi-Fi 6E 世代經查證後**未新增**，
  Omada 目前只有既有的 EAP690E HD 一款真實在售的 6E 機型，未強行湊數
- **Peplink**：MAX BR1 Pro 5G 原本 `price_note` 空白，已補上 US$999（2026-08 查價）；5G Sub-6
  世代新增 **MAX BR2 Pro 5G**（US$2,899，雙 5G modem 備援＋7 種 WAN 來源）；4G LTE 世代新增
  **MAX Transit Duo Pro**（US$1,199，雙 modem 跨業者備援）；5G mmWave 世代查證後**未新增**，
  Peplink 現行產品線均只支援 Sub-6GHz（mmWave 天線設計與 Peplink 外接天線/工業殼體衝突），據實
  回報未硬湊
- **Ruckus**：Wi-Fi 6/6E 各補 1 款（**R350**US$495~695、**R560**US$843~1,755，內建 BLE/Zigbee
  IoT）；Wi-Fi 7 世代原本完全沒有 Ruckus 型號，新增 **R770**（US$2,500~3,103）
- **Teltonika**：4G LTE 新增 **RUT200**（US$102.60~114.94，入門工業款）；5G Sub-6 新增
  **RUTM50**（US$499~599）；5G mmWave 查證後確認 Teltonika 全產品線皆無 mmWave 機種，未新增
- **Netgear**：Nighthawk M6 Pro（型號 MR6550）原本兩個世代（5G Sub-6／5G mmWave）都是空白
  `price_note`，已查證確認為同一雙模型號（Snapdragon X65，同時支援 n260/n261 mmWave 頻段），
  兩世代都保留、補上 US$900~1000（2026-08 查價）；原 DB 網址已失效（誤導向瑞典站型號總覽），
  一併修正為正確的美規產品頁；4G LTE 世代新增 **Nighthawk AX4（LAX20）**（US$170~200）；
  Wi-Fi 6E 世代新增 **Orbi RBRE960**（US$600~700，可擴充 Mesh）

### 2026-08-09 — UniFi 內容校正（文件追上資料庫現況）
- 使用者提出「新增 UniFi」需求，核對後發現 UniFi Wi-Fi 產品其實已完整覆蓋 Wi-Fi 6/6E/7 三個世代
  （U6-Pro／U6-Enterprise／U7-Pro／U7-Lite／U7-Pro-Max 共 5 筆），§4「6E 尚無產品」是過時記錄，
  這次一併校正；U6-Pro 的 `price_note` 補上查價日期（原本缺日期標記，跟其他筆格式不一致）

### 2026-07-30 — 類別上線
- 建立 Wi-Fi（Wi-Fi 6/6E/7）、行動網路（4G LTE/5G Sub-6/5G mmWave）兩條族系
- 第一批產品連結：UniFi U6-Pro/U7-Pro、Omada WiFi6 系列/EAP773、Peplink MAX BR1 Pro 5G、Netgear Nighthawk M6 Pro
