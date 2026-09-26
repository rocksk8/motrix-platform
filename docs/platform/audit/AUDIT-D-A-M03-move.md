# 稽核：A 的 M03 採購・庫存・出貨搬進 modules/supply（wip/a-m03；第八班，合回前）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。
> 對象：`origin/wip/a-m03` `b2e5f7e4`（月台 896e7761；7 個 commit：前置 `6a7399e6`、搬遷 `dc4ac420`、e2e `d39ba547`、§B-11 歸位 `371c2d5b`／`b2e5f7e4`、SPEC `4c92bd4e`、IP-20 `68dbd8b9`）。
> §B-11：D 在自己的稽核樹刪資料夾（主持裁示「刪資料夾或 sparse 都可以」；跑前 `ls backend/modules` 確認 supply 不在）。e2e 照規則 `-n 2`。

## 0. 結論

**必修 0、建議 0、觀察 1。** 搬遷完整、§B-11 獨立重做通過、IP-20 的缺席行為成立。

## 1. 搬遷完整性

- `routers/inventory.py`、`routers/suppliers.py`、`routers/shipping_notes.py` 已刪；`main.py` 不再掛；產品碼與 tools 沒有 import 舊路徑。
- `modules/supply/`：`api/`（inventory、shipping_notes、suppliers）、module.json（1.0.1、pages、probes、customization）、README、CHANGELOG、SPEC.md。
- INTEGRATION-POINTS：IP-18 `shipping.list_for_case`、IP-19 `stock.serial`、IP-20 `inventory.paid_batches`，**編號不重複**（commit 訊息裡的暫定號 IP-16／17 已在「rebase 後對齊」改掉）。

## 2. §B-11 獨立重做

範圍：`tests/platform`＋29 個提到 M03 的檔（`modules.supply`、`/api/suppliers`、`/api/inventory`、`/api/shipping`、`shipping_notes`、`paid_batches` 等；其中 8 個 e2e）。

| 輪次 | 樹 | 結果 |
|---|---|---|
| 模組在（基準） | D2 `b2e5f7e4`，＋`modules/supply/tests`，-n 2 | 1352 passed、**1 failed**：`test_generated_maps::test_test_map_json_is_current`（見 O-1） |
| 刪掉 supply（`--continue-on-collection-errors`） | D，-n 2 | **1291 passed、5 failed（皆在允許清單）**、5 skipped |
| 刪掉 supply（`--collect-only`，不加旗標） | 同上 | 1301 題，exit 0（無收集錯誤） |

允許的 5 題：`test_modules_json_lists_only_existing_units`、`test_unit_index_is_current`，以及 b-maps-2 列入的產生檔一致性三題（`test_generated_maps` 的 dep_graph／test_map／歸屬）。

## 3. IP-20 缺席行為與突變

- 缺席：T100 匯出照常、不含料件進貨的付款傳票；預覽 `notice` 明說「採購・庫存・出貨模組未安裝：本次匯出不含料件設備進貨的付款傳票」（與 IP-14 以「；」並列）。使用方 `_collect_paid_stock_batches` 在提供者不在時回空清單，不丟例外。
- D 突變（`test_supply_connectors`＋`test_stock_batch_payment`＋`test_t100_export`，20 題，-n 4）：

| # | 突變 | 結果 |
|---|---|---|
| I20a | 缺席時不加 notice | 紅（`test_without_m03_t100_preview_says_stock_batches_are_missing`） |
| I20b | ModuleSpec 不登記 IP-20 | 紅（`test_stock_batch_flows_into_t100_export_and_can_be_confirmed`） |
| I20c | 使用方永遠回空 | 紅（同上）——A 修掉的 T100 假綠（原本比料號、sourceKey 其實是批次號）現在真的會抓到「批次沒流進匯出」 |

## 4. 觀察

- **O-1　分支上的 test_map.json 過期**：模組在的完整樹紅 `test_test_map_json_is_current` 一題。依 PLAYBOOK §G3 列車疊完會重產三份產生檔，所以不列必修；列車長合回時確認重產後這題轉綠。

## 5. 回覆欄

| # | 回覆 | commit | D 確認 |
|---|---|---|---|
| — | 無待回覆項目（O-1 由列車重產） | b2e5f7e4 | ✅ 14:38 **通過（b2e5f7e4）** |
