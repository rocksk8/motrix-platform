# 稽核：C 的 D7 probes（crm／subcontract／payroll）與 probe 無副作用守門（wip/c-probes；第八班）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。合回前稽核。
> 對象：`origin/wip/c-probes` `b2ef6439`（`584499cc` probes＋守門、`324b1504` 步驟表移入 docs/platform/plans/、`b2ef6439` 操作軌跡精確判定）。
> crm 3 支（`/api/dev-cases`、`/api/dev-logs/pending`、`/api/dev-crm/activity-stats`）、subcontract 4 支（`/api/contractors`、`/api/vendor-contractors`、`/api/contractor-dispatches`、`/api/contractor-vouchers`）、payroll 4 支（`/api/payslips`、`/api/tax-rules`、`/api/bonus/awards`、`/api/bonus/items`）。全速模式 `-n 4`。

## 0. 結論

**必修 0、建議 2。** 主持點名的四點都成立，但守門的兩個分支沒有被題目鎖住（突變存活）。

## 1. 逐點

| # | 主持點名 | 結果 | 證據 |
|---|---|---|---|
| ① | 允許分支夠不夠窄 | ✅ 目前的程式夠窄 | PS2：crm 列表 handler 多寫一列別的路徑（`/api/other`）的軌跡 ⇒ 紅；PS3：多寫一列同形但路徑是 `/api/dev-cases-x` 的軌跡 ⇒ 紅 |
| ① | 窄度有沒有題目鎖住 | ⚠ 沒有 | PS1：把允許條件放寬成「至少一列、不看內容」⇒ **5 passed（存活）**，見 S-1 |
| ② | 超過 30 秒還成不成立 | ✅ | TM1：暖機後等 31 秒 ⇒ 過；TM2：等 31 秒**而且**拿掉「每支先清軌跡」⇒ 仍然過（判準比的是打之前的軌跡，不靠去重）；TM3：不等、不清 ⇒ 過（去重 ⇒ 0 列新增） |
| ③ | log 外洩的反向控制 | ⚠ 部分 | PS4：crm 列表把回應 log 出來 ⇒ 主題紅；`test_rc_log_leak_and_thread_are_caught` 也驗得到合成外洩。但 PS5：把**主題**比對文字裡的 caplog 拿掉 ⇒ **5 passed（存活）**，見 S-2 |
| ④ | 11 支實跑 200、純讀 | ✅ | 基準 5 passed：主題在迴圈裡對每支 probe 逐一斷言 200、表不變、不寄信、不起背景工作、不外洩 |

## 2. 發現

### 建議

- **S-1　允許分支沒有反向控制**：目前「恰好一列：本人、GET、這支 probe 的路徑、200」寫得對（PS2、PS3 紅），但把條件改成 `len(new) >= 1` 沒有任何題會紅（PS1）。建議補一題合成：路由除了中介層那一列，自己再寫一列 `user_request_log` ⇒ 要報；只寫中介層那一列 ⇒ 不報。C 自報「中介層記的路徑不對」那項突變證明允許分支每支都有走到，但它證明的是「會走到」，不是「夠窄」。
- **S-2　主題與反向控制各自組比對文字**：主題第 201 行、反向控制第 260 行各寫一份「caplog＋capsys」的組法，反向控制保護不到主題的那一份（PS5 存活）。建議抽成一支 `_captured_text(caplog, out)`，兩邊都呼叫它。

## 3. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | D 確認 |
|---|---|---|---|
| S-1 | | | |
| S-2 | | | |
