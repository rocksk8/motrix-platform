# 薪資獎金 更新紀錄

## 1.0.5 — 2026-09-26（C；第九班之後 rebase 重編，原暫用 1.0.3，列車取號）
- 待我簽核（M01-PLAN §3-7）：新增 `bonus_queue.py`，提供 `approval.queue_items`（獎金分潤單 `bonus_award`、案件獎金分潤 `bonus_case_award`，欄位同原 M01 佇列）；M01 佇列與角標不再直讀 `bonus_awards`／`bonus_case_awards`。案件獎金的客戶與案名不再 JOIN M01 的 `quotations`，改由 M01 彙整端依 `linkedQuoteNo` 補

## 1.0.4 — 2026-09-26〔稽核 X C4-S5：c-probes 先上第八班、用了 1.0.3 ⇒ 本段改 1.0.4〕
- D7 演練：`module.json` 宣告 `provides.probes`（`/api/payslips`、`/api/tax-rules`、`/api/bonus/awards`、`/api/bonus/items`）——純讀的 GET、在本模組前綴下、模組在時回 200（守門 `tests/platform/test_product_drill_probes.py`、`test_probe_side_effects.py`：不寫表、不寄信、不排程、不把回應值寫進 log）
- 選單宣告搬進本模組：`payslips.html`、`bonus.html` 的 `pages[].menu`（原寫在 L1 的 `core/menu_l1.json`；group／order／perm／badge 原值照搬）。階段 C／C4（主持裁示 A）：本模組不在時它的入口隨宣告一起消失，不再靠前端寫死的頁面⇒模組對照表；版號與 c-probes／h-probes 交會，列車取號

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
