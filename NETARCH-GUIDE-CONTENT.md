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
| Omada（TP-Link） | Wi-Fi AP（EAP 系列）、SDN 雲端管理 | omadanetworks.com |
| Peplink | 行動網路路由器（MAX BR 系列）、SD-WAN、多 WAN 綁定 | peplink.com |
| Netgear | 行動熱點路由器（Nighthawk M 系列）、商用 Insight 雲端管理 | netgear.com |

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

### 2026-08-09 — UniFi 內容校正（文件追上資料庫現況）
- 使用者提出「新增 UniFi」需求，核對後發現 UniFi Wi-Fi 產品其實已完整覆蓋 Wi-Fi 6/6E/7 三個世代
  （U6-Pro／U6-Enterprise／U7-Pro／U7-Lite／U7-Pro-Max 共 5 筆），§4「6E 尚無產品」是過時記錄，
  這次一併校正；U6-Pro 的 `price_note` 補上查價日期（原本缺日期標記，跟其他筆格式不一致）

### 2026-07-30 — 類別上線
- 建立 Wi-Fi（Wi-Fi 6/6E/7）、行動網路（4G LTE/5G Sub-6/5G mmWave）兩條族系
- 第一批產品連結：UniFi U6-Pro/U7-Pro、Omada WiFi6 系列/EAP773、Peplink MAX BR1 Pro 5G、Netgear Nighthawk M6 Pro
