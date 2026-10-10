# 代理統一：步驟檔文字與正式機 SQL 預檢（T54 P1 用）

> 來源：權限矩陣設計稿 v9（`PERMISSION-MATRIX-DESIGN-T54.md`，代理統一一節）。使用者裁示（10-10）：過期代理仍被計入是安全缺陷，與代理統一一起修；**這是有意的行為變更**。
> 本檔是給「該版上線的步驟檔」直接貼用的文字，加上上線前的唯讀 SQL。程式實作（`active_delegates_of(window=True)`）在 P1，本檔先備好。

## 1. 缺陷說明（一句話版，貼進步驟檔「行為變更」）

勞報單簽核（`payroll/api/payslip_approval.py:60`）、獎金簽核（`payroll/api/bonus.py:1296`）、獎金發放（`payroll/bonus_payouts.py:117`）三處讀取簽核代理時只看「啟用中」，**不看起訖日期**；已過期或尚未開始的代理仍被當成有效。只有 `payslip_approval.py:98` 有檢查日期。統一後四處一律檢查日期區間（含起訖當天）。

## 2. 上線前唯讀 SQL 預檢（給使用者／正式機執行；只 SELECT）

**(a) 會因此失效的代理（已過期或尚未開始，但仍標示啟用）**

```sql
SELECT id, delegator_username, delegate_username, start_date, end_date, reason
FROM approval_delegates
WHERE active=1
  AND (end_date < date('now','localtime') OR start_date > date('now','localtime'))
ORDER BY end_date;
```

**(b) 其中目前實際握有待簽單據、會受影響的人**（以代理人名義可簽的勞報單／獎金）

```sql
-- 勞報單：目前在簽核中，且簽核鏈上有委派人
SELECT d.id AS delegate_row, d.delegator_username, d.delegate_username, d.end_date, p.slip_no, p.status
FROM approval_delegates d
JOIN payslips p ON p.status='簽核中' AND p.approval_json LIKE '%"' || d.delegator_username || '"%'
WHERE d.active=1
  AND (d.end_date < date('now','localtime') OR d.start_date > date('now','localtime'));
```

（獎金簽核與獎金發放的待辦表名以正式機實際結構為準；步驟檔附 b7 對照過的版本。**結果為空，或使用者逐筆確認可失效，才切換。**）

## 3. 步驟檔「行為變更清單」文字（貼用）

1. 已過期或尚未開始的簽核代理，在勞報單簽核、獎金簽核、獎金發放不再生效。
2. 驗收：以一筆已過期代理測勞報單簽核與獎金簽核，確認被擋（403／不在可簽名單）；以一筆有效代理確認仍可簽；起訖當天仍有效。
3. 回滾：旗標 `perm_delegation_source` 切回 `legacy`，並把三處改回內嵌查詢的程式回退。**本缺陷修正隨程式版本，不隨旗標。**

## 4. 關卡 D 預期（給稽核者）

- 對每一列、每一天：`active_delegates_of(window=False)` 必須與舊的三處內嵌查詢**逐字相同**（證明沒有別的改動）。
- `window=True` 與舊行為的差異集合**只能是**「當天落在 [start,end] 之外的 `active=1` 代理」；邊界日（start／end 當天）仍有效，多或少一個都紅。
- `window=False` 僅供等價測試，產品程式不使用。
