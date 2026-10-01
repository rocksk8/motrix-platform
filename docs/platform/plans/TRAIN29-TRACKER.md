# 第 29 班追蹤表（主持 bin-1c，2026-10-01 起）

更新規則：每則視窗回報即更新；狀態以 commit／sha 為準，不以檔案時間或口頭「進行中」為準。

| 視窗 | 工作 | 分支 | sha | 狀態 | 下一步 |
|---|---|---|---|---|---|
| hichan-2e | W2 線：A2 作廢／稽核匯出／四型 e2e | wip/w2-expense-a2-w2b | efc0ea79（12:38） | S0、S1、S2、def_version 釘版本完成；S2.5 取消 | S3 四型 e2e（ETA ~14:40） |
| hichan-a3 | W1 線：A2-2 類型定義 → A2-4 → A2-7（最後合併） | wip/w1-a2-2、wip/w1-a2-4 | b8ae49cb／8f57800d（12:36） | A2-2、A2-4、A2-7 完成；預檢 13:00 | HANDOFF 附錄、合併 |
| hichan-c7 | 模組建構器（已併 platform ad418e88）；部門彙總跟業務負責人 | fix/dept-follows-sales-owner | 422078dd | 完成（8 題綠）、待合併；待待命 | 與 wip/w3-dept-dim 合併時 reports.py _collect_expenses 一處衝突，解法：w3 區塊保留、dept_by_quote 改用 _case_dept（SELECT 要含 sales_person）|
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

| hichan-d7 | W4b 收尾（派工單 DISPATCH-W4B） | wip/w4-g2-5b | 73e606c6（12:36） | 1 A5 已撤、3 G4 文件、繼承紅燈已修 | 13:00 排預檢；4 G5 |
| hichan-c7 補充 | 補 modules.json 登記（custom_module_delete）→W3 dept-dim 收尾 | 未推 | — | 預計 13:00 | |

## 13:12 巡檢
- 整合樹 wip/train-29-int1@436749d2（d7）：已合 w4-g2-5b、w1-a2-2/a2-4、w2-w2b(9d0cee5a)、fix/module-delete-ownership；待合 wip/w3-dept-dim-c7@037ed829、補 W3 個資種子列。
- 裁示：費用類別清單為空視為未設定（方案 A，2e 實作中）；W4 低風險#3 採(a)；etype-editor／map-zoom／prodroot 不納入本班。
- a3：列印按鈕＋PDF 版面檢查；c7 待命；預檢排在 2e 新版與 d7 合併完成後（整合樹一次跑）。
