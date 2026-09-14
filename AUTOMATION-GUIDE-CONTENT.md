# 自動化系統選型導覽 — 內容維運手冊

> 這是「選型資料庫」眾多產品類別中的**自動化系統**這一類（倉儲/產線自動化設備：
> AGV／AMR／協作型機械手臂／工業型機械手臂）。跨類別的總索引、分類邏輯、提需求格式見
> [SELECTION-DB-INDEX.md](./SELECTION-DB-INDEX.md)。

---

## 這份文件怎麼用

跟 `MONITOR-GUIDE-CONTENT.md`／`ACCESS-GUIDE-CONTENT.md`／`GATEWAY-GUIDE-CONTENT.md` 一樣：你提供
素材（新情境、新分類、要修正的適配判斷、產品連結），我負責研究、判斷放哪個情境/分類、寫進
資料庫（透過 `/pages/automation-guide.html` 的管理後台或 `/api/automation-guide/*`，不改
`automation_guide_seed.py`——那份 seed 檔只在資料庫是空的時候執行一次）。

---

## §1 · 這個類別的資料形狀

跟監控/門禁/閘道器選型導覽同一種資料形狀——**「設備分類 × 場域情境」的矩陣交叉**，因為自動化
設備跟這幾類一樣，分類本身沒有演進順序（AGV 不會「進化」成 AMR，兩者是不同定位），而是同一個
分類在不同情境下適配度不同：

- **場域情境**（automation_scenarios）：WAREHOUSE_PICKING／PRODUCTION_LINE／
  MIXED_TRAFFIC_FACILITY／HEAVY_PAYLOAD_YARD，描述自動化導入場域的典型需求（動線是否固定、
  是否與人員/堆高機混流、承重需求）
- **設備分類**（automation_categories）：AGV／AMR／COBOT／INDUSTRIAL_ARM，欄位：
  | 欄位 | 說明 |
  |------|------|
  | key_specs | 核心規格說明 |
  | tags | 標籤，逗號分隔 |
  | price_range | 建議售價區間（需標明查價年月） |
  | dependency_note | 依賴／相關備註 |
  | watch_note | 注意事項／地雷 |
- **適配矩陣**（automation_fit）：情境 × 分類的交叉點，`fit_level`（適合／可用／不建議）+ `fit_note`
- **分類 → 產品**（automation_products）：一個分類掛多個品牌型號，`specs_json` 結構化規格欄位
  （`[["規格名","值"], …]`），格式與 monitor-guide/access-guide 相同

---

## §2 · 目前主力品牌

（目前空白——2026-08-27 上線時刻意先只建立情境/分類骨架＋適配矩陣，未塞入具體品牌/型號/報價，
留待後續獨立任務用 WebSearch 查證補上，比照 monitor_guide 過去「先上線骨架、品牌深度後續逐批
補齊」的作法。）

---

## §3 · 待處理清單

- 【最優先】幫四個分類（AGV／AMR／協作型機械手臂／工業型機械手臂）各補至少 1～2 款真實品牌型號
  （查證來源：官網 techspecs、經銷商報價頁），格式同 `SWITCH-GUIDE-CONTENT.md`

---

## §4 · 已知缺口／待確認

- 目前完全沒有 automation_products 資料（0 款），瀏覽頁「對應產品」區塊會全部顯示「尚無對應產品」
- 情境/分類/適配矩陣是依一般產業知識推導的骨架判斷，尚未有實際專案案例驗證，之後有真實案源
  請回來校正 `fit_note`
- 尚未涵蓋 AGV/AMR 調度管理軟體、產線周邊治具/夾爪等周邊選型（本類別目前只涵蓋主設備本身）

---

## §5 · 變更記錄

### 2026-08-27 — 類別上線（選型資料庫第七個類別）
- DB v65：新增 `automation_scenarios`／`automation_categories`／`automation_fit`／
  `automation_products`（設備分類 × 場域情境矩陣，與監控/門禁/閘道器選型導覽同一種資料形狀）
- 第一批資料：4 個場域情境（倉儲/物流中心揀貨搬運、產線工站上下料/組裝、人車混流廠區/走道、
  重件/棧板搬運場域）× 4 個設備分類（AGV、AMR、協作型機械手臂、工業型機械手臂），16 組適配
  矩陣全數填滿；**刻意不塞入具體品牌/型號/報價**（PRODUCTS_JSON 留空），這批需要後續獨立任務
  用 WebSearch 查證補上
- 前端 `frontend/pages/automation-guide.html`：以門禁系統選型導覽為範本（依情境查看／對照矩陣
  總覽／規格比較／管理後台 CRUD 全數沿用，非最小上線版本）
- 側邊欄／users.html 新增 `automation_guide`／`automation_guide_edit` 模組旗標；audit-log.html
  同步補上
