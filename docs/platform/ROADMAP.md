# 模組化路線圖（第一階段）

> 依據：DEPENDENCY-MAP.md（相依）、CORE-SPEC.md（裁示）。每一步完成的定義＝該步驟的測試通過＋反向控制（拆掉後其餘照常）。
> 順序原則：先切逆向依賴（L1→L2），再拆耦合最少的 L2；跨多檔的工作在各自 worktree 做。

## 階段 A：L1 清乾淨（逆向依賴歸零）

| # | 項目 | 來源 | 狀態 |
|---|---|---|---|
| A1 | 寫鎖下沉 `core/txn.py` | §0-4 | ✅ 7db88381 |
| A2 | 紅點常數改取 module_registry | §3 #4 | ✅ 7cdec57b |
| A3 | 案件／業務開發案可見性 → `helpers/row_access.py` | §3 #2 #3 #5 #6 | ✅ 50e8c2cc／0411f818 |
| A4 | 路徑解析層 `core/paths.py` | DATA-COMPAT | ✅ bef3e25d／41151687 |
| A5 | `pdf_gen` 的完工單樣板搬回 M01，L1 只留引擎 | §3 #1 | ✅ 4ba73907 |
| A6 | `recognition`／reports／vouchers 的 `_dispatch_row` → M04 公開連接器 | §3 #7 #8 #9 | 🔄 A |
| A7 | `bonus_vouchers` → M06「建立傳票草稿」連接器 | §3 #18 #19 | ⏳ |
| A8 | Excel 樣式與匯出速率限制下沉 L1 輸出；`_COMPANY` → company_identity | §3 #10 #12 #13 #17 | 🔄 C |
| A9 | system 指名 L2（tender／bonus／quote_terms）→ 模組登錄表 | §3 #26 #27 #28 | 🔄 tender 已完成；bonus、quote_terms 尚未 |
| A10 | 案件聚合（vouchers_by_case、list_dispatches、list_shipping_notes）→ L1「案件關聯資料提供者」 | §3 #20–22 | ⏳ |
| A11 | google_calendar、case_stage_tasks 跨領域寫入 → 事件／連接器 | §3.1 | ⏳ |
| A12 | 共用表直寫（stock_items、vouchers_all、dev_cases、system_settings、user_request_log）→ 擁有者連接器 | §4 | ⏳ |

## 階段 B：L2 逐一搬進 `modules/<key>/`

建議順序，理由是阻擋它的逆向依賴或共用表最少：

1. M11 標案雷達 — ✅ 後端完成；剩地圖 provider（等 M08）與前端頁面
2. M12 每日任務 — 需要 A11（case_stage_tasks）與 §4 的 system_settings、user_request_log
3. M10 網路規劃 — 依賴 M01 的路由前綴，需要 A10
4. M02 業務開發 — 需要 A3、§4 的 dev_cases
5. M04 外包工班 — 需要 A6
6. M05 應收應付 — 需要 A6、A8
7. M06 會計 — 需要 A7、A8
8. M07 薪資獎金 — 需要 A7、A9
9. M03 採購庫存出貨 — 需要 §4 的 stock_items
10. M08 分析（唯讀）— 改走各模組的讀取連接器；地圖 provider
11. M01 案件 — 最後搬，此時其他模組已不依賴它的內部實作

## 階段 C：前端跟著模組走（第二階段的前置）

- 模組頁面搬進 `modules/<key>/pages/`，由載入器掛載靜態路徑
- sidebar 選單改由登錄表產生（模組沒裝就不出現）
- 端點登錄表 `GET /api/platform/endpoints`（CORE-SPEC §7）
