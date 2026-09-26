# 薪資獎金 更新紀錄

## 1.0.3 — 2026-09-26
- 待我簽核（M01-PLAN §3-7）：新增 `bonus_queue.py`，提供 `approval.queue_items`（獎金分潤單 `bonus_award`、案件獎金分潤 `bonus_case_award`，欄位同原 M01 佇列）；M01 佇列與角標不再直讀 `bonus_awards`／`bonus_case_awards`。案件獎金的客戶與案名不再 JOIN M01 的 `quotations`，改由 M01 彙整端依 `linkedQuoteNo` 補

## 1.0.2 — 2026-09-26
- 規格編號隨模組走：`BN1`～`BN18`、`QS1a` 的條件（原在 STATE.md）與 `BN1`～`BN19`、`QS1a` 的範圍（原在 SCOPE.md）移進本模組 `SPEC.md`；`AC1`／`BN17` 的撞名登記改在本模組 `## 登記`（反向控制：模組不在時這些編號變成「沒有題」與「未宣告」）
- 勞報單稅額純函式題（`TestCalc`，9 題）自 `tests/test_core.py` 拆進本模組 `tests/test_payslip_calc.py`：模組層 import 讓本模組不在時整檔收集中斷（不帶 --continue-on-collection-errors 的反向控制抓到）
- 勞報單的個資告知端點登記 `api_module: payroll`（`docs/platform/pii_forms.json`）：本模組不在時不比對端點，告知區塊照驗

## 1.0.1 — 2026-09-26
- 反向控制（刪掉 modules/payroll）抓到 204 題綁著本模組 ⇒ 需要本模組的題搬進 `modules/payroll/tests/`（整檔 41、從 9 個混合檔拆出）；`payslip_seq` 分類改 T3（編號計數，本來就在備份排除清單）

## 1.0.0 — 2026-09-26
- 模組化：自 `routers/payslips.py`、`routers/bonus.py`、`helpers/bonus*.py`（6 支）搬入 `modules/payroll/`（PLAYBOOK §B；兩支 router 放 `api/`，CORE-SPEC §3）；由載入器掛載
- 提供者改由 `ModuleSpec.providers` 宣告：IP-8 `bonus.payouts`、IP-9 `expense.entries`、IP-16 `bonus.module_status`
- 不再依賴 M06：獎金分潤單的版面元件改用 L1（簽核格顯示名稱、公司抬頭、HTML→PDF、金額格式）——會計模組不在時照樣能預覽與匯出
