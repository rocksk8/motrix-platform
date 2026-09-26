# 稽核：A 的 approval-parse——簽核 JSON 解析下沉 L1（wip/a-approval-parse 708dbe0d；合回前）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d；L1 小包，照舊完整稽核。稽核者 D 沒有寫過任何受稽核的程式碼。
> 對象：`708dbe0d`（1 commit）。`helpers/voucher.py` 的 `parse_approval_json`／`VoucherChainUnreadable` 下沉為 L1 `helpers/tiered_approval.py` 的 `parse_approval_json(record, *, doc_label)`／`ApprovalChainUnreadable`；voucher 留別名與委派；`routers/quotations.py`（M01 轉簽）改 import L1；l2_import_baseline 刪 1 條邊（`M01 router:quotations -> M06 helper:voucher`）；新題 `tests/platform/test_approval_parse_l1.py`。
> 稽核樹 `D:\MOTRIX-PLATFORM-D`（detached），Python `D:\MOTRIX-PLATFORM\.venv312`，`-n 4`。

## 0. 結論

- **必修 0、建議 1、觀察 1**。fail-closed 規則原樣保留，別名是同一個類別，M01→M06 的 import 邊確實消失。
- 不是模組搬遷 ⇒ §B-11 不適用。

## 1. 實測

| 項目 | 結果 |
|---|---|
| 基準：新題＋em5＋呼叫端 | 10 passed |
| 守門：module_boundaries、l1_interface_snapshot、generated_maps、jv35、as3、em5 | 77 passed、**1 failed＝`test_test_map_json_is_current`**（見 O-1） |
| `grep` 產品碼呼叫端 | quotations（L1）、vouchers（別名）、voucher 內部；payroll/bonus 用自己的 `BonusChainUnreadable`，未受影響 |

## 2. 突變（D 自做，mutate.py，替換前 assert 恰好 1 處）

| # | 突變 | 結果 |
|---|---|---|
| AP1 | L1 解析失敗改回 `{}`（fail-open） | 紅（4 題：新題、em5） |
| AP2 | voucher 別名改成子類別 | 紅（4 題） |
| AP3 | M01 轉簽讀不出來改成吞成空鏈 | **存活**（唯一紅是既有的 test_map 過期，與突變無關）⇒ S-1 |
| AP4 | 忽略 `doc_label`，訊息一律「單據」 | 紅（`test_voucher_aliases_are_the_l1_objects`） |

## 3. 發現

### 建議

**AP-S1　M01 轉簽「傳票簽核資料讀不出來 ⇒ 400」沒有任何題驗**
- 本包改的正是這一段的 import；AP3 把 except 改成 `appr = {}`，受影響題全綠（只剩既有 test_map 紅）。
- 後果：日後有人把這段吞成空鏈，轉簽會落到「這張單沒有分層簽核資料」的 400，訊息錯而且沒有題會紅；若 `_active_tiers` 之後改寫成空鏈可放行，就是 fail-open。
- 建議：jv35 補一題，approval_json 放壞字串，轉簽 ⇒ 400 且訊息含「格式不正確」。原本就沒有題（JV35 起），不是本包造成，列建議。

### 觀察

**AP-O1　test_map.json 過期**：parent `--check` 一致，708dbe0d 之後不一致（新題檔未重產）。依 PLAYBOOK §C 每班列車重產三份產生檔，列車處理即可。

## 4. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆 | commit | D 確認 |
|---|---|---|---|
| AP-S1 | 補題（產品碼原本就對）：`test_jv35_an_unreadable_voucher_chain_refuses_reassign_with_its_own_reason`——驗 400 **且訊息「格式不正確」**（吞成空鏈也是 400，只驗狀態碼會照綠），並驗擋下時不改寫簽核資料；突變 AP3 轉紅 | 51f9d495 | |
