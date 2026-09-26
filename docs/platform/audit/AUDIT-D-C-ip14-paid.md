# 稽核：C 的 IP-14 `contractor_voucher.paid_between`（wip/c-ip14-paid 6c8406c5；合回前）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d：改到產品碼，完整稽核，範圍小。稽核者 D 沒有寫過任何受稽核的程式碼。
> 對象：`6c8406c5`（1 commit）。M04 新增 provider `contractor_voucher.paid_between(start, end)`；M06 `routers/accounting_export.py::_collect_contractor…` 不再自己讀 `contractor_payment_vouchers`，改走 provider；subcontract 1.0.5；IP-14 表格更新；新增靜態守門 `test_accounting_export_no_longer_reads_the_subcontract_tables`。
> 稽核樹 `D:\MOTRIX-PLATFORM-D`（detached），`-n 4`。

## 0. 結論

- **必修 1、建議 0、觀察 1**。
- 搬移前後邏輯逐字相同：SQL、日期邊界、`include_snapshot=False` 都一樣。突變 4/4 紅。
- 必修的原因：「M04 不在」那題只模擬拿掉 `contractor_voucher.public`，新的資料路徑沒有被模擬到。

## 1. 實測

| 項目 | 結果 |
|---|---|
| 基準：providers、subcontract 與 L1 的 t100_export、subcontract_connectors、t100_config、cashier_split、stock_batch_payment、voucher_no_category、generated_maps、module_boundaries | 97 過 |

## 2. 突變

| # | 突變 | 結果 |
|---|---|---|
| P1 | `_paid_between` 不看 `is_paid=1` | 紅（`test_paid_between_lists_only_paid...`） |
| P2 | T100 `return paid(start, end)` 改成 `return []` | 紅（subcontract 的 t100_export 2 題） |
| P3 | 迄日改成 `T00:00:00`（不含當天） | 紅 |
| P4 | 形狀改成 `include_snapshot=True` | 紅 |
| P5 | 拿掉 accounting_export 的 `if paid is None: return []`（M04 不在時的防護） | **存活**（23 過）⇒ IP-M1 |

## 3. 發現

### 必修

**IP-M1　「M04 不在」的模擬只拿掉 `contractor_voucher.public`，T100 的資料路徑已經改走 `paid_between`**
- `test_cashier_and_t100_without_m04` 用 `_without(monkeypatch, "contractor_voucher.public")`。本包之後，T100 取資料看的是 `contractor_voucher.paid_between`，所以這題在「M04 不在」的模擬下，其實照常拿到付款資料。
- 預覽 notice 仍以 `public` 判斷，所以斷言照綠。題目名稱說驗了「M04 不在」，實際沒有驗到新的那條路。
- P5 證明：防護拿掉之後，真正的 M04 不在會變成 `None(start, end)` 的 TypeError（500），而這批題照綠。只有真的刪掉模組的 §B-11 或 core-only 才可能抓到。
- 建議修法：`_without` 一次拿掉 IP-14 的兩個能力（`contractor_voucher.public`、`contractor_voucher.paid_between`），和真的缺模組時一致；修完後 P5 要轉紅。
- 附帶：T100 預覽 notice 也可以改成看 `paid_between`，或兩個都看，讓「說明」和「資料來源」依據同一個能力。

### 觀察

- **IP-O1**　IP-14 同一個串接點現在有兩個能力。之後如果只有其中一個被拿掉或改名，notice 和資料會各看各的；IP-M1 的修法會順便把這個守住。

## 4. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆 | commit | D 確認 |
|---|---|---|---|
| IP-M1 | | | |
