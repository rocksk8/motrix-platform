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

## 13:42 巡檢（29+30 合併班）
- int1 wip/train-29-int1@a4939253（ptc 2290 過；3 測試端紅已修）。待合：預檢工具(d7 本輪)、etype-editor-a3@8052bb75、map-zoom-2e@f29993cb、fix/login-approval-popup@2fcb4fa0、BS 預設比較(2e, fix/bs-autoload，15:30)、外包銀行遮罩(c7，16:30)、P3(a3 wip/w1-attach-p3-a3@c222c6b0，20:00)、差異分桶(d7 wip/w4-diff-buckets，20:00)。
- 裁示：已付款不可作廢、付款覆寫僅 superadmin；今晚套用；去識別化／建構器B／401／開帳／C6 不入本班（第31班主軸）；BS 預設比較＝上一年年底。
- 不入本班：clock-gates-2（4 檔紅，下班）。
- 凍結預計 ~21:00 → ptc 21:45 → 建包 22:30 → 稽核 00:30 → 套用 ~01:00。

## 14:50 巡檢
- int1 wip/train-29-int1@25179adb；GO 已發：合 mask-2@6be93619 + filehub-guards@c1dca101 → 最後完整 ptc（d7）。
- 稽核：c7(audit/train29@af0d4280，審 W1–W4/d7)、2e(audit/train29-b@97dd2bcf，審 c7 的線)；演練 a3(drill/train29@0f11a195)；建包步驟 d7(build/train29-steps@45df568c)；套用步驟 2e(wip/train-29-apply-draft@c8c3c8bb)。
- 已修稽核發現：Q1 名冊帳號洩漏(mask-2)、Q4 路徑逃逸(upload-path-guard@91c474d2)、空類別表單(emptycat@4fd54996)、w2b eb762b2f 漏合已補。
- 後續待辦：TRAIN31-BACKLOG.md。

## 15:15 巡檢
- platform = d4c43792（ff，使用者指示由主持推）；int1 = d4c43792（train 29 assign 已提交）。建包暫停：加「客戶回簽單入口」（a3，wip/w1-quote-signed-back，16:15）。
- 回簽單既有功能（signed-files, quotation-form 已送出時才顯示）；改：已送出+ 可傳、刪除限上傳者或 admin+、案件管理頁區塊、成案 modal 選擇性上傳。
- 稽核 §9.11 就緒（audit/train29@76ce5893）；演練工具就緒（drill/train29@ff8fcce7）。
- 權限：使用者「我人不在，決策給你」；正式機 Claude 已加權限；platform 推送經使用者明確指示。

## 18:30 檢討
- platform=int1=fca93b04（含回簽單；使用者指示「推 platform」）。建包由主持接手（d7 卡等待），17:5x 開跑，測試段 80%。
- 待：簽章發布 → c7/2e 稽核、a3 演練 → 正式機 Claude 套用。

## 21:40 出包
- platform=47db5613；包 20261001_212935_47db5613_full 已簽章發布（gate: full, 7848+741 過，無偶發重跑）；package.sha256 檔 SHA256 71245f7d…f3d1（772 行）。
- 流程教訓：預檢範圍窄於建包關卡；e2e 兩個負載競態（reject textarea、perf 取最快）已修；flaky_retry 解析修正。
- 進行：c7 稽核、2e 第二稽核＋套用步驟定稿、a3 演練、d7 唯讀檢視包內容。套用待稽核＋演練通過＋使用者放行確認。
