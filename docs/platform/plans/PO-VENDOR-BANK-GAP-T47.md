# 採購單廠商銀行資料缺口（下一班設計項目；本班只修收款人顯示）

> 2026-10-07 使用者裁示：採購單的廠商銀行資料**不在本班**。本文件只記錄缺口，供下一班設計。

## 現況
- 費用單據（請購單／採購單／差旅／零用金）的建立畫面（`payment-request.html`）只送 `{kind, data, lines, departmentId, expenseDate, plannedPayDate}`；**沒有**收款人類型（`payee_type`）、銀行代碼／名稱、帳號（`payee_bank`／`payee_account`）。
- 採購單的廠商只有一個文字欄 `data.vendor`；出納「待付款申請」的收款人顯示已改為取它（`payables._payee_name`），但出納的「查看收款人銀行資料」（`payee-bank`）對採購單仍是空的（沒有銀行資料來源）。
- 員工收款（差旅等）可走員工收款帳號（IP-BK1 `payee.bank_profile`）；廠商沒有對應的主檔。

## 要決定的事（下一班）
1. 採購單要不要收集廠商銀行資料？收在單據上（`payee_bank`／`payee_account` 欄位、F2 個資分流與遮蔽）或建立「廠商主檔」重用（有 `suppliers` 表與叫料匯款申請的收款帳戶快照可參考）？
2. 收款人類型（employee／vendor）由誰填、預設值（採購單＝vendor、差旅＝employee、零用金＝依支付對象）。
3. 個資：廠商可能是自然人 ⇒ 沿用叫料匯款的「已告知收款人」規則與帳號遮蔽（末四碼；完整帳號只給財務角色與最高管理者）。
4. 出納端 `payee_info`：目前 `payeeName` 取 `payee_name or payer_name`；若採購單改成有收款人欄，名稱也要對齊 `data.vendor`。
