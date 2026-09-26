# 稽核：C 的 M01-PLAN §3-6——case.recognition（wip/c-m01-rec-2 a56f33e4；合回前）（D 稽核，2026-09-26 16:58）

> 完整稽核（動 analytics 產品碼）。稽核者 D 沒有寫過任何受稽核的程式碼。
> 對象：`a56f33e4`，由原 `aac6b836` 換基底而來。D 比對過兩者的 diff（排除產生檔），內容逐行相同。
> 內容：
> - M01 提供 `case.recognition`（IP-95 暫編號），6 個方法轉呼叫 `helpers.recognition`。
> - 口徑標籤 BASES、BASIS_NOTES、normalize_basis 下沉 L1 `helpers/recognition_basis.py`，M01 保留同名別名。
> - M08 報表改經提供者取用；M01 不在時：權責收入給 `incomeNotice`，支出給 `unavailable` 並明說。
> - l2_import_baseline 刪掉 M08→M01 recognition 這條邊。
> - CORE 1.38。

## 0. 結論

- **必修 0、觀察 1**。

## 1. 實測

| 項目 | 結果 |
|---|---|
| 基準（aac6b836）：tests/platform＋analytics 題＋引用 recognition／expenses-monthly 的 21 檔 | 1329 過、1 紅（sidebar，已知） |
| 基準：相關 e2e 5 檔（`-n 2`） | 11 過 |
| 突變 N1：轉呼叫時丟掉 department_id | 紅（`[material_entries]`） |
| 突變 N2：M01 不在時，權責口徑不給說明 | 紅（`test_reports_without_m01_say_why`） |
| 突變 N3：M01 不在時，支出的 unavailable 回空 | 紅（同上） |
| 突變 N4：M08 改回直接 import `helpers.recognition` | 紅（2 題，含 l2 基線） |
| 突變 N5：recognition 自己另存一份 BASES（不是別名） | 紅（`test_recognition_basis_is_pure_l1_and_aliased`） |

## 2. 觀察

- **REC-O1**：M01 不在時，`unavailable` 只列 `CASE_EXPENSES_UNAVAILABLE` 一筆。如果同時 M04 也不在，`dispatch_unavailable(basis)` 原本那一句不會出現；不過派工支出本來就是經 M01 取的，已包含在「案件模組未安裝」那句裡，所以不影響判讀。另外 `recognitionFlags` 回 `{}`，前端 getter 會把它當空清單處理，可以正常顯示。
