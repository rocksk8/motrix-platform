# 稽核：B 的 D7 演練——缺席模組實際打 probes／頁面驗 404（wip/b-drill-absent404 58f844ac）（D，2026-09-27 11:02）

> 標準等級，正式 D7 的前提。
> 內容：`final_drill.absent_probe_plan`：已搬遷、登記了、包裡沒有的模組，讀來源樹 module.json 的 `provides.probes` 與 `pages`，每一項期望 404；來源樹沒有 module.json ⇒ 判不過（NO_SOURCE_DECL）；尚未搬遷（NOT_MIGRATED）不在範圍。`smoke()` 以 expect 判 ok。

## 0. 結論

- **通過。必修 0、建議 2、觀察 1**。

## 1. 實測

| 項目 | D 的驗證 | 結果 |
|---|---|---|
| 題 | test_final_drill_tool：23 過 | 成立 |
| 突變 | AB1「缺席項回 200 也算過」⇒ 紅；AB2「尚未搬遷也當缺席」⇒ 紅；AB3「來源樹沒宣告就略過」⇒ 紅；AB4「不打頁面」⇒ 紅 | 4/4 紅 |
| **主持重點：「尚未搬遷不在範圍」會不會自動失效** | 判準是 modules.json 群組有沒有 `mod:` 單位。① 在 58f844ac 還在豁免的只有 `accounting`（M06）與 `case`（M01）；② c-m01-5 a1e0a45b 的 modules.json 已有 `mod:case/...` ⇒ `migrated_module_keys()` 含 `case`，**M01 合回即自動納入**；③ 反向：把 supply 群組的 `mod:` 單位拿掉（模擬「搬了卻忘了改 modules.json」）⇒ tests/platform 3 紅（`test_modules_json_has_no_ownership_errors`、`test_every_router_helper_page_has_exactly_one_owner`、`test_l2_tables_written_only_by_owner`）⇒ 豁免不會靜默殘留 | **成立** |
| 缺席時 probes 真的 404（D 獨立重做） | sparse 工作樹排除 9 個已搬遷模組（core-only 的後端），以 client 打每個模組在來源樹宣告的 probes：**27 項全部 404**（數量＝各模組 probes 加總）。頁面在 sparse 樹不會被移除，由 B 的實跑（49 項）涵蓋 | 成立 |

## 2. 發現

**AB-S1（建議）　缺席模組的 module.json 在、但 probes 與 pages 都是空的 ⇒ 一項都不打，也不判紅**
- `absent_probe_plan` 只把「來源樹沒有 module.json」判成 NO_SOURCE_DECL。有 module.json、但沒有任何宣告時，計畫是空的（D 以合成的 `ee` 模組實測：`[]`）。
- 完整包的冒煙會把「沒有 probes」判成 UNDECLARED，所以 D7 整體會被接住；但「沒有 pages」兩邊都不檢查。
- 主持的描述是「非 404、或沒有宣告，都判紅」，建議把空宣告也判成 NO_SOURCE_DECL。

**AB-S2（建議）　modules.json 的 `page:` 單位不在 module.json 的 `pages` 裡 ⇒ 缺席時不會被移除，也不會被驗**
- `product_select` 的 `removed_pages` 與本工具都讀 module.json 的 `pages`。
- 不一致的有：58f844ac 的 subcontract `pages/contractor-voucher-approval-settings.html`；a1e0a45b 的 case `pages/sales-orders.html`。
- 這些頁面在 core-only 包裡仍然存在（200），而 D7 不會去打。
- 建議加守門：每個已搬遷模組 modules.json 群組的 `page:` 單位 ⊆ module.json `pages`，並補齊這兩頁的宣告。

**觀察**
- **AB-O1**：`test_smoke_runs_the_absent_plan` 是讀原始碼的字串守門（`"ok": code == expect`）。`smoke()` 的實際行為靠 D7 前哨實跑（B 記錄 49 項全 404），D 另以 sparse 樹獨立驗了 probes（§1）。
