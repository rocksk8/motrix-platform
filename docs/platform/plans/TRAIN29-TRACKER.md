# 第 29 班追蹤表（主持 bin-1c，2026-10-01 起）

更新規則：每則視窗回報即更新；狀態以 commit／sha 為準，不以檔案時間或口頭「進行中」為準。

| 視窗 | 工作 | 分支 | sha | 狀態 | 下一步 |
|---|---|---|---|---|---|
| hichan-2e | W2 線：A2 作廢／稽核匯出／四型 e2e | wip/w2-expense-a2-w2b（基底 ab5e2ec4） | 未推 | S0 完成（308 過）；S1 作廢進行（僅 superadmin） | S1→S2→S3 |
| hichan-a3 | W1 線：A2-2 類型定義 → A2-4 → A2-7（最後合併） | origin/wip/w1-a2-2 | bc4d25bc（基底） | A2-2 守門修正中，預估約 1.5h 變綠 | A2-4、A2-7 |
| hichan-c7 | 模組建構器（刪除、選單群組）；部門彙總跟業務負責人 | platform／新分支 | ad418e88 | 建構器兩項完成；部門彙總進行中 | 回報後 |
| 未派 | W3：dept-dim／etype-editor／map-zoom／bank 收尾 | wip/w3-* | 見 HANDOFF-HOST | 預檢未完 | 等 W1/W2 進度再派 |
| 未派 | W4：g2-5（含 A5 疑慮單獨 revert）、G4/G5、稽核 | wip/w4-g2-5 | 10f6cbdd | 未完 | 同上 |

## 使用者裁示（2026-10-01）
- 模組建構器「加進既有模組」採方案 A（選單群組）；B（內建頁分頁掛載點）延後。
- 案件部門跟業務負責人（roles.sales），不跟開單者。
- A2 金額可見度維持現狀（申請人／簽核人／出納＋admin／業務／financial_view）。
- 請款單作廢僅 superadmin。

## 待處理項目現況（2026-10-01 查證）
- 部門彙總／department_id：待處理 → c7 修。
- financial_view：後端已強制（helpers/auth.py can_see_financial；financial_mask.py），known-limits 過時。
- 16 模組後端不讀：已修，僅 dashboard／map 後端不讀（前端有讀）。
