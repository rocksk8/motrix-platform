# 稽核：B 的 IP-15 追加 `dispatch.cost_for_case`（wip/b-ip15-cost afbb1b8d）（D，2026-09-26 22:09）

> 標準等級。稽核者 D 沒有寫過任何受稽核的程式碼。
> 內容：subcontract 1.0.12 新增成本檢視提供者（白名單回傳，含 scope／invoiceNo），放行 finance、cashier，加上原本看得到派工清單的三個模組。

| 主持的問題 | D 的驗證 | 結果 |
|---|---|---|
| 回應沒有人名或人員欄位，契約題有驗 | 讀碼：`dispatch_cost_view` 是白名單，外包人員只回 `personnelCount`（數字）與 `personnelTotal`（金額合計）。突變 C1「多回 notes」、C2「personnelCount 改成回姓名清單」 | 都紅（`ALLOWED` 集合比對＋SECRET_NAMES 檢查）⇒ 成立 |
| finance 看得到 | 突變 C3「COST_VIEW_MODULES 拿掉 finance」 | 紅（`test_finance_and_cashier_get_the_cost_view[modules0]`）⇒ 成立 |
| 只新增，IP-15 既有回應不變 | diff：`dispatch.list_for_case` 沒有改動；新題 `test_cost_view_is_registered_and_list_for_case_is_unchanged` | 成立 |
| 註冊 | 突變 C4「不註冊」 | 紅（7 題） |
| 基準 | subcontract tests＋integration_points_registered＋dispatch_connector | 93 過 |

- 觀察 **IP15-O1**：`scope` 與 `items[].description` 是使用者輸入的自由文字。白名單擋得住欄位，但擋不住有人把人名打進描述裡。主持已裁示 scope 屬會計資料，記錄備查。
- 觀察 **IP15-O2**：權限只看模組、不做每案檢查，與派工清單及 JV7 的設計界線（AT6-O1 裁示）一致。

⇒ 通過、必修 0。本包合回後，M06 的 a' 例外會因到期守門而轉紅（D 在 M06 稽核的突變 E1 已驗證會觸發），屆時由 A 改走這個提供者。
