# 場域選型導覽 — 內容維運手冊

> 這份文件跟 `MOTRIX-ERP-QUICK.md`（開發架構）分開，專門管「場域選型導覽」模組**裡面的內容**：
> 場域定義、分層設備建議、原廠／代理商連結。開發規則不寫在這裡。
>
> 這是「選型資料庫」眾多產品類別中的**無人自動化載具部署場域**這一類。跨類別的總索引、
> 分類邏輯、提需求格式見 [SELECTION-DB-INDEX.md](./SELECTION-DB-INDEX.md)。

---

## 這份文件怎麼用

你提供素材（新場域的需求、設備想法、原廠網站連結、產品型錄、要修正的舊資料等），
我負責：**搜尋規格 → 判斷該放哪個場域／哪一層／哪一級 → 寫進資料庫 → 視需要調整既有內容讓資料維持一致。**

你可以：
- 直接在聊天視窗貼連結/需求，我隨看隨處理
- 或先寫進下面「§3 待處理清單」，之後一次請我批次處理

我完成後會回報做了什麼變動（新增/修改/刪除了哪些場域、建議、連結），並更新這份文件的「§3 待處理清單」狀態。

**重要**：資料現在在資料庫（`env_guide_environments` / `env_guide_recommendations` / `env_guide_links`），
不是寫死在 `場域選型導覽.html` 或 `env_guide_seed.py`（那份 seed 檔只在資料庫是空的時候執行一次，之後不會再套用，改了也沒用）。
新增/修改一律透過 `/pages/env-guide.html` 的「管理」模式或 `/api/env-guide/*` API，不要回頭改 seed 檔或原始 html。

---

## §1 · 資料欄位對照（填寫新內容時對照用）

### 場域（env_guide_environments）

| 欄位 | 說明 | 範例 |
|------|------|------|
| code | 場域代碼，短碼，同大類用同字首＋數字（A1/A2…、B1…、全部＝跨場域通用層） | `B3` |
| name | 場域名稱，含溫度/規格重點 | `冷凍庫 -18~-25°C` |
| group_name | 大類（目前六類，新增大類前先跟我確認，會牽動篩選側欄與代碼字首慣例） | `冷鏈` |
| temp_gate | 溫度門檻（車輛端設備需求，"~" 全形波浪號） | `-40~75°C 必要` |
| ip_gate | IP 門檻，格式「車輛端 / 環境端」 | `IP54＋密封＋加熱 / IP65` |
| cert_gate | 必要／建議認證，無則填「無」 | `ATEX Zone 2 Ex nA` |
| trap_note | 這個場域最容易踩的雷（一句話，講清楚「為什麼」） | `商規整機下限多為 -20°C，直接不合格 — 本場域最大缺口` |

### 分層建議（env_guide_recommendations，一個場域可有多筆，每筆對應一個系統分層）

| 欄位 | 說明 |
|------|------|
| env_code | 對應場域代碼 |
| layer | 分層名稱，固定用這幾種前綴之一：`通訊層`／`匯集層`／`運算層`／`定位層`／`致動層`／`環境端網路`／`維運終端`／`電源與防護`／其他自訂（前端會歸類進「其他」篩選） |
| position | 安裝位置，如「車輛端 車內電控箱」「環境端 戶外桿件」 |
| tier1 / tier2 / tier3 | 入門(PoC) / 業界普遍(建議) / 高端，沒有合規方案時填「無」或「不建議入門方案」（前端會自動標「缺口」badge，規則見下） |
| custom_note | 業界慣例，講「大家實際上怎麼做」 |
| trap_note | 這一筆特別要注意的地雷／確認事項 |

**自動 badge 判斷規則**（前端 JS，別自己加 badge 欄位）：
- `缺口`：tier2 開頭是「無」，或包含「無合規」「不建議入門方案」「現有清單無」
- `關鍵`：trap_note 開頭「關鍵」「重要」，或包含「完全不合格」「必定失敗」「最大缺口」等字樣；custom_note 開頭「關鍵」「重要」也算
- `需外箱／艙`：三個 tier 欄位合併文字含「Ex t」「Ex p」「恆溫艙」「隔熱艙」「外箱」「密封箱」「正壓」

寫新內容時，措辭盡量符合上面規則，才會正確顯示 badge。

### 連結（env_guide_links）

| 欄位 | 說明 |
|------|------|
| keyword | 型號關鍵字，前端用「建議內容是否包含這個字串」來決定要不要顯示這個連結，**盡量精確**（太短的關鍵字會誤配到別的型號） |
| url | 原廠或代理商產品頁 |
| label | 顯示用標籤，如「Sbjlink 原廠產品頁」「英菲達 RUT956（NT$xxx）」 |

---

## §2 · 常用品牌官網／型錄入口（研究新產品時的起點）

| 品牌 | 用途 | 官網／型錄 |
|------|------|-----------|
| Sbjlink | 工業交換器、戶外 PoE、ATEX/DNV/IEC61850 系列 | sbjlink.com/products_view.php?id=xxx（每個型號一個 id，先用 products.php?scat= 分類頁找） |
| Teltonika Networks | 工業路由器、車載 4G/5G | teltonika-networks.com/products |
| 英菲達 Innotrust | Teltonika 台灣代理商，含報價 | store.innotrust.com.tw |
| iEi | 車載運算主機、面板電腦 | ieiworld.com/en/product/ |
| Southco | 電子鎖閂 | southco.com |
| Moxa | 工業乙太網路、EN50155 軌道交換器 | moxa.com |
| Advantech | ATEX/IECEx 交換器 | advantech.com |
| Kollmorgen | ATEX/IECEx 防爆伺服馬達＋驅動器（Zone 2 gas／Zone 22 dust） | kollmorgen.com/en-us/products/motors/servo/akme-hazardous-location-motor |
| Pyroban | ATEX 整車防爆改裝（動力/電控/電池），forklift/AGV 系電動車輛 | pyroban.com/products |
| Neousys | 車規寬溫（-40~70°C）無風扇運算機，多款 EN50155/E-Mark 認證 | neousys-tech.com/en/product/product-lines/in-vehicle-computing |
| IBASE | 軌道／車載運算機（EN50155/EN45545/ITxPT），iEi 缺口的替代選項 | ibase.com.tw/en/product/category/Intelligent_Transportation |

新增品牌時，順手補進這張表。

---

## §3 · 待處理清單

> 格式：`- [ ] 內容摘要 — 來源/連結 — 備註`，處理完換成 `- [x]` 並簡述做了什麼。

（目前空白，之後累積在這裡）

---

## §4 · 已知缺口／待原廠確認（從原始資料承接，優先研究方向）

以下是既有資料裡標「需確認」「缺口」「關鍵」的項目，之後有新資訊可以優先補這些：

- [x] ~~B3/B4 冷凍庫運算層主控：iEi 現有清單無 -40°C 寬溫機種，需確認是否有替代型號~~
      → 已補：Neousys POC-551VTC（原生 -40~70°C）。B3 可直接用（無恆溫艙）；B4（-40°C 為其規格下限，無餘裕）仍建議保守加恆溫艙。
- [x] ~~D2/D3 防爆場域：整車（含馬達、電池、驅動器）認證範圍需另案確認~~
      → 已補：Kollmorgen AKME 系列（ATEX/IECEx，Zone 2 gas／Zone 22 dust）伺服馬達＋驅動器；Pyroban 整車防爆改裝（含 ATEX 電池）。**注意**：AKME 不涵蓋 Zone 1／Zone 21，D3 若實際是 Zone 21 仍需另向原廠確認。
- [ ] D5 高壓沖洗：三家供應商均無 IP69K 車載網通／運算設備
      （查到 WashdownPC 等廠牌的 IP69K 全不鏽鋼面板電腦，但多為**固定式**washdown設備，是否可車載/符合安裝條件尚未確認，暫不列入資料庫）
- [x] ~~E11 軌道：iEi 現有清單無 EN50155／ITxPT 認證機種，需找 IBASE 或 SINTRONES 替代~~
      → 已補：IBASE MPT-7000R／MPT-8000AR（EN50155+EN45545）；IBASE MPT-3100V（ITxPT 認證，另有 E-Mark，注意是不同產品線，需依需求分開選型）。
- [ ] Southco 型錄「不鏽鋼」未標明 304/316，港區/食品場域需要求原廠確認等級
      （查到 Southco 其他閂鎖系列有 316 SS 選項，但 R4-EM 是否有 316 版本未查到明確資料，仍需直接洽詢原廠）

---

## §5 · 變更記錄

> 每次批次處理完待處理清單，在這裡加一筆（新的在上面）。

### 2026-07-30 — 補齊 D2/D3 防爆、B3/B4 低溫、E11 軌道缺口
- D2 新增「電源與防護」建議：Kollmorgen AKME 防爆伺服馬達＋驅動器 / Pyroban 整車防爆改裝
- D3 新增同層建議，並標註 AKME 僅到 Zone 22、不含 Zone 21 的限制
- B3/B4「運算層 主控」更新：補上 Neousys POC-551VTC（原生 -40~70°C）作為 iEi 缺口的替代選項
- E11「運算層 主控」更新：補上 IBASE MPT-7000R/MPT-8000AR（EN50155/EN45545）與 MPT-3100V（ITxPT）
- 新增連結：Kollmorgen AKME、Pyroban、Neousys POC-551VTC、IBASE MPT-7000R、IBASE MPT-3100V
- D5（IP69K 車載）與 Southco 316 SS 兩項查無足夠具體資料，維持待確認狀態，未寫入資料庫
