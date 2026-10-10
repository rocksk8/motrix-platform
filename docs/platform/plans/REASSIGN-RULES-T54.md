# 轉簽規則收緊（第 54 班；使用者裁示 2026-10-10）

分支 `wip/t54-05-reassign-rules`（基準 origin/platform）。程式見 core CHANGELOG (next)、`routers/approval_queue.py::reassign_approval`。

## 規則
- 操作者不得是送審人；轉給的對象不得是送審人（送審人不得自行核准自己送審的單據）。
- 原簽核人與其他在職最高管理者也收到通知；稽核 `approval.reassign` 與換人同一個交易（強制）；原因必填。
- 勞報單沒有轉簽提供者（使用者未要求；勞報單的卡死出口是 `payslip.approve_bypass`，見 PAYSLIP-BYPASS-T54.md）。
- 勞報單沒設簽核層、最高管理者送審即核准：維持原樣（使用者裁示）。

## 驗收字句（給步驟檔）
- 最高管理者把某單據當層簽核轉給另一人時，被轉到的人、原簽核人、其他最高管理者都收到通知；稽核紀錄有 `approval.reassign`（含原因、原簽核人、新簽核人、送審人）。
- 送審人本人按『轉簽』會被拒絕；把簽核轉給送審人本人也會被拒絕；原因空白一樣被拒絕。
