# 稽核：B 的 D7 演練——缺席模組實際打 probes／頁面驗 404（wip/b-drill-absent404 58f844ac）（D，2026-09-27 11:02）

> 標準等級，正式 D7 的前提。
> 內容：`final_drill.absent_probe_plan`：已搬遷、登記了、包裡沒有的模組，讀來源樹 module.json 的 `provides.probes` 與 `pages`，每一項期望 404；來源樹沒有 module.json ⇒ 判不過（NO_SOURCE_DECL）；尚未搬遷（NOT_MIGRATED）不在範圍。`smoke()` 以 expect 判 ok。

## 0. 結論

- **通過。必修 0、建議 2、觀察 1**。
- 複核 -2（8b146db3）：**AB-S1、AB-S2 關閉**；salesorders-page 491f0945 通過；上車順序見 §3。
- 複核 -3（8d4cf4dd）：**必修 AB3-M1**（略過條件會把正常安裝的掃描失效變成靜默略過），見 §4。

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

## 3. 複核（wip/b-drill-absent404-2 8b146db3）＋ wip/b-m01-salesorders-page 491f0945（D，2026-09-27 11:40）

| 項目 | D 的驗證 | 結果 |
|---|---|---|
| tests/platform（8b146db3） | 1251 過、3 skip | 成立 |
| AB-S1：空宣告判紅 | module.json 在、probes 與 pages 都空 ⇒ `(modules/<key>, None)`（EMPTY_DECL）；只有頁面 ⇒ 照驗頁面。突變 AC1「空宣告不判紅」⇒ 紅 | **關閉** |
| AB-S2：page 歸屬雙向一致 | 新守門 `test_module_pages_match_units`（modules.json `page:` ＝ module.json `pages`，兩個方向都比），附合成的反向控制。突變 AC2「只比單向」⇒ 紅；AC3「拿掉 subcontract 補的頁」⇒ 紅 | **關閉** |
| salesorders-page（491f0945，疊在 c-m01-5 上） | case pages 補上 `sales-orders.html`（不帶 menu；該頁是轉址到 case-management 的退役頁），case 1.0.4。case 模組題＋menu／probes 題：27 過 | 成立（輕量） |
| 兩包的交會 | ① 491f0945＋新守門＋subcontract 修正 ⇒ 守門 2 過；② 反向：case 回到 c-m01-5 的宣告（沒有 sales-orders）⇒ 守門紅，列出 `('case', ['sales-orders.html'], [])` | 成立 |

- **上車順序**：c-m01-5 與 absent404-2 都上車時，**salesorders-page 必須同班**。否則新守門會因 case 紅，這正是它該做的事。

## 4. 複核（wip/b-drill-absent404-3 8d4cf4dd，取代 -2；B 做 ⓪ 自查時自己改的）（D，2026-09-27 14:02）

- 改動：頁面歸屬守門原本要求「已搬遷模組 ≥ 3」，core-only 時必紅 ⇒ 改成「沒有任何 module.json ⇒ `pytest.skip` 明說」，有的話要求至少比到一組。
- 主持要 D 確認：這不可以變成靜默略過，正常安裝時仍要求有東西可比。
- 突變 PM1「`_real()` 掃出的 manifests 是空的」（模擬掃描路徑或條件壞掉）⇒ **存活**（1 過 1 略過）。略過的條件和被檢查的東西是**同一個掃描的結果**：掃描壞掉時，它自己就判定「這是 core-only」而略過。

**AB3-M1（必修）　略過條件要用獨立的訊號**
- 例如：modules.json 裡有 `mod:` 單位的組（已搬遷），其 `backend/modules/<key>/` 實際存在 ⇒ 不准略過，而且每一個這樣的 key 都要在 manifests 裡。
- 只有這些資料夾一個都不存在（真正的 core-only）才略過。
- 反向控制：讓 manifests 掃出空的 ⇒ 要紅。
