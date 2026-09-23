# MOTRIX ERP — 模組：庫存／採購／叫料（§7.18–§7.20）

> 自 `MOTRIX-ERP-QUICK.md` 拆出（2026-09-23）。§ 編號沿用原編號，程式註解裡的「QUICK.md §N」依中樞檔的對照表找到本檔。
> 內容逐字搬移，未改寫；相對連結已改為自本目錄起算。

---

### §7.18 · 進貨批次供應商/發票/付款狀態（DB v70，2026-09-01）

| Method | Path | 說明 |
|--------|------|------|
| POST | /inventory/batches | 建立進貨批次（既有端點擴充，admin+），新接受 `supplier_id`/`invoice_no`（選填），一併寫入 `stock_batches` 表頭 |
| GET | /inventory/batches | 批次列表（既有端點擴充），新回傳 `supplier_id`/`supplier_name`/`invoice_no`/`is_paid`/`paid_by`/`paid_at`/`note`；`qty`/`total_cost` 仍即時從 `stock_items` 群組加總，不信任表頭快取 |
| GET | /inventory/batches/{batch_no} | 單批明細（既有端點擴充），新增回傳 `header`（`stock_batches` 表頭完整內容） |
| PUT | /inventory/batches/{batch_no} | 編輯批次層級屬性（供應商/發票號/備註，admin+），不動 `stock_items` 本身 |
| POST | /inventory/batches/{batch_no}/paid-toggle | `{action:'pay'\|'unpay', paid_at?}`（admin+），比照承攬商匯款申請 paid-toggle 慣例；重複標記回 409 |

前端：`inventory.html`「進貨」Modal 新增供應商/發票號欄位；新增「進貨批次」Modal（列表＋標記已付款/編輯）。

---

### §7.19 · 採購建議（2026-09-07，架構地圖 §6.6）

| Method | Path | 說明 |
|--------|------|------|
| GET | /inventory/purchase-suggestions | 依安全庫存缺口自動生成，僅回傳紅/黃燈且已設定安全庫存的料號 |

回傳 `{items, count, totalEstimatedCost}`。**跟架構地圖 §6.6 原始建議的落差**：該條建議寫「資料已齊備」，但系統其實完全沒有追蹤供應商前置時間，所以刻意不做 ETA 預估，只算「該補多少、上次跟誰買、大概要花多少」：

```
建議採購量 = ceil(安全庫存 × 1.5) − 目前在庫（補到黃燈門檻，不是只補到剛好等於安全庫存，
             否則採購完成後燈號會立刻變黃再被同一張清單抓到一次）
供應商/單價 = 該料號最近一筆 stock_batches 進貨紀錄；查無紀錄則供應商留空、單價退回 parts.cost
排序 = 紅燈優先於黃燈，同燈號內依預估金額由高到低
```

前端 `inventory.html`：工具列新增「採購建議」按鈕（`lowStockCount > 0` 才顯示，跟既有「低於安全庫存」篩選 chip 同一組判斷條件），開啟 Modal 顯示清單與預估總金額；純唯讀，不含下單/標記已處理等狀態追蹤（v1 刻意收斂範圍）。

---

### §7.20 · 叫料（材料訂購）（後端 2026-09-10、前端 2026-09-11，DB 無異動）

| Method | Path | 說明 |
|--------|------|------|
| GET | /quotations/{no}/material-orders | 回 `{quoteNo, materialOrders, totalAmount, paidAmount}`；只要求登入＋擁有者檢查 |
| PATCH | /quotations/{no}/material-orders | **整包覆蓋**（無增量更新）；需 admin+ 或 `project_manage` 模組；已結案回 400 |

資料落在 `quotations.data_json` 的 `caseRecord.materialOrders`，**沒有獨立資料表**——查不到專屬 migration 是正常的。後端逐筆驗證的三條規則（`routers/material_orders.py` 第 5 步）前端也各擋一次，只為了給看得懂的中文訊息：

```
小計必須等於 數量 × 單價（容差 0.01）  → 所以小計一律由前端算，不讓使用者手填
pending      → 已付金額必須 0、日期必須空
partial/paid → 0 ≤ 已付金額 ≤ 小計，且日期必填（paid 時已付金額 = 小計）
```

前端入口：案件管理「財務」分頁的 `#fin-material-orders` 區塊（`case-management.js` 的 `loadMaterialOrders()`／`moSave()`／`moRecalc()`／`moCanEdit()`）。**存檔刻意不併進 `saveCase()`**：那支會覆蓋整份 `data_json`，兩邊同時存會互相蓋掉，且已結案與權限的守門規則不一樣。**金額也刻意不計入財務總覽的「應付總額」**——那個數字的定義是承攬商匯款申請，混進去會跟 `/finance-summary` 算出來的對不起來。e2e `test_e2e_material_orders_2026_09_11.py`。
