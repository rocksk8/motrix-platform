# 薪資獎金 更新紀錄

## 1.0.1 — 2026-09-26
- 反向控制（刪掉 modules/payroll）抓到 204 題綁著本模組 ⇒ 需要本模組的題搬進 `modules/payroll/tests/`（整檔 41、從 9 個混合檔拆出）；`payslip_seq` 分類改 T3（編號計數，本來就在備份排除清單）

## 1.0.0 — 2026-09-26
- 模組化：自 `routers/payslips.py`、`routers/bonus.py`、`helpers/bonus*.py`（6 支）搬入 `modules/payroll/`（PLAYBOOK §B；兩支 router 放 `api/`，CORE-SPEC §3）；由載入器掛載
- 提供者改由 `ModuleSpec.providers` 宣告：IP-8 `bonus.payouts`、IP-9 `expense.entries`、IP-16 `bonus.module_status`
- 不再依賴 M06：獎金分潤單的版面元件改用 L1（簽核格顯示名稱、公司抬頭、HTML→PDF、金額格式）——會計模組不在時照樣能預覽與匯出
