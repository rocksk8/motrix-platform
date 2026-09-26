# 稽核：C 的 M01 ②——本體搬進 modules/case、由載入器掛載（wip/c-m01-s2 cefc5ecd；基底 8151bdc6）（D，2026-09-27 00:24）

> 完整稽核。① 那兩個 commit（afa9808a、c4c679dc）已在 `AUDIT-D-C-m01-3.md` 審過；本包新增的是 83a7fc37（搬遷）、913cf37b（rebase）、cefc5ecd（arap T100 題）。

## 0. 結論

- **必修 0、觀察 2**。

## 1. 實測

| 項目 | 結果 |
|---|---|
| 題目盤點（83a7fc37^ ⇔ cefc5ecd，AST 比對每個 `test_*`） | 4484 → 4485，**消失 0**。M01 的題都留在 tests/（沒有搬家）；本體有改的 92 題中，assert 少了的 **0** 題，新增 skip 的只有 `test_voucher_revision_no…`（舊 skip 換成新模組路徑的訊息） |
| 搬遷前後掛載的 API 路由（M01 在時，`/openapi.json` 的方法＋路徑） | **566 ⇔ 566，完全相同**：main 不再掛 M01、改由載入器依 ModuleSpec 掛載，對外路由沒有少 |
| plat: 探測（D 在 M013-O1 的建議） | 突變：`core/catalog.py` 加 `import modules.case.quotations` ⇒ **紅**（`test_importing_every_l1_unit_loads_no_m01_unit` 與 plat 覆蓋題） |
| **真刪 M01**（D2 刪 `modules/case`，只跑 tests/platform，與 C 抽樣 93b90c0b 同範圍） | 1155 過、4 skip、66 failed＋14 errors＝80 紅＝允許 5＋**75 項**（63 個題名，依參數展開 75 項）；C 抽樣時是 66 項 |

## 2. 主持重點：66 題有沒有增加、有沒有被默默略過

- **有增加：66 → 75 項（+9）**。多出來的主要是 `test_attachments_providers`（8 個題名，抽樣時不在清單上）。那是第十班合進來的 A 附件題（a-attachments-4／-5／-6），本身需要 M01 的附件提供者，**不是本包造成的**；另外 approval_providers、supply_connectors、m01_sink2 也有增減（抽樣時依項目計數，與題名計數有差）。
- **沒有默默略過**：真刪時的 skip 只有 3 種，都附明確理由：`test_l1_connections`（/api/sales-orders 的擁有者 M01 不在）、`test_module_boundaries`（基線裡沒有可拿來突變的邊）、`test_subcontract_connectors`（modules/case/api/quotations.py 的模組不在）。
- 觀察 **M012-O1**：M01-PLAN ④ (c) 的待辦清單應該更新為 75 項，並把 `test_attachments_providers` 納入，因為它們也要搬進 `modules/case/tests` 或依 M01 在不在處理。
- 觀察 **M012-O2**：包內順手修了 arap 的 T100 交會紅（cefc5ecd）。第十一班也在修同一題，合併時二擇一（主持已知）。
