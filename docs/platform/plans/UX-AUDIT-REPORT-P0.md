# UX 守門報告（P0，只出報告、不擋 CI）

- 掃描：82 個 HTML、169 個檔案（含 JS）。產生工具：`backend/tools/ux_audit.py`；詞彙與白名單：`backend/tools/ux_audit_config.json`。
- 判讀：**『畫面文字』欄是真正會被使用者看到的；『JS 字串』欄多半是資料鍵或程式識別字（例：資料鍵『待審核』不改），只當參考。**

## 1. 總計（ratchet 指標，之後只許降不許升）

| 指標 | 現況 |
|---|---|
| 行內樣式 `style="` | 5943 |
| 直接呼叫 `toLocaleString(`（應改走 `MotrixFormat`） | 95 |
| 頁頭 `.pg__a` 內 `.btn-primary` 超過 1 顆的總超出數 | 0 |
| 禁用詞（畫面文字、扣除白名單） | 12 |
| `<th>` 欄標題總數 | 1000 |

## 2. 舊用語（使用者已裁示要改的詞；先看『畫面文字』）

| 舊用語 | 改成 | 畫面文字 | JS 字串 | 檔案數 | 備註 |
|---|---|---|---|---|---|
| 待審核 | 待簽核 | 31 | 64 | 27 | 使用者 2026-11-13 裁示：畫面顯示改「待簽核」；資料鍵『待審核』不變，故 JS 字串內的出現多半是資料鍵，不是畫面字。 |
| 審核中 | 待簽核 | 12 | 2 | 6 | 報價單清單的簡稱（status_display _NAMES0） |
| 送審中 | 待簽核 | 5 | 3 | 5 | 報價單清單分組標題 |
| 申請送出審核 | 申請送出簽核 | 2 | 1 | 2 |  |
| 刪除暫存區 | 資源回收筒 | 2 | 0 | 1 | 使用者裁示 |
| 歷史紀錄 | 操作紀錄 | 10 | 2 | 6 | 使用者裁示；僅指 audit-log 頁。單據自己的『簽核歷史』『審核歷史』不在此列，需人工判讀 |
| 等我簽核 | 待我簽核 | 3 | 0 | 1 | 儀表板卡片；與簽核頁、選單用語統一 |
| 簽核佇列 | 待我簽核 | 9 | 3 | 8 | 簽核頁頁名；『佇列』是 IT 詞（選單項目名稱由 menu_l1.json 決定，隨 PM 裁示） |
| 估價單 | 報價單 | 0 | 0 | 0 |  |
| 超級管理員 | 最高管理者 | 23 | 12 | 11 |  |
| 最高管理員 | 最高管理者 | 11 | 15 | 12 |  |
| 超管 | 最高管理者 | 1 | 1 | 2 |  |
| 拒絕結案 | 駁回結案 | 9 | 3 | 2 |  |
| 提交 | 送出 | 7 | 0 | 2 |  |
| 保存 | 儲存 | 7 | 2 | 8 | 『保存期限』作為名詞可保留 |

### 各檔『畫面文字』舊用語（前 40）

| 檔案 | 詞 | 次數 |
|---|---|---|
| `frontend/pages/dev-crm.html` | 待審核 | 7 |
| `frontend/pages/settlement.html` | 待審核 | 6 |
| `frontend/pages/ledger-periods.html` | 待審核 | 6 |
| `frontend/pages/daily-tasks.html` | 提交 | 6 |
| `frontend/pages/case-management.html` | 審核中 | 6 |
| `frontend/pages/quotation-form.html` | 拒絕結案 | 5 |
| `frontend/pages/approval-settings.html` | 超級管理員 | 5 |
| `frontend/pages/users.html` | 超級管理員 | 4 |
| `frontend/pages/mail-settings.html` | 超級管理員 | 4 |
| `frontend/pages/ledger-periods.html` | 審核中 | 4 |
| `frontend/pages/duty-roles.html` | 超級管理員 | 4 |
| `frontend/pages/case-management.html` | 待審核 | 4 |
| `frontend/pages/approval-queue.html` | 拒絕結案 | 4 |
| `frontend/pages/daily-tasks.html` | 歷史紀錄 | 3 |
| `frontend/pages/custom-def-review.html` | 送審中 | 3 |
| `frontend/pages/company-profile-settings.html` | 最高管理員 | 3 |
| `frontend/pages/cashier.html` | 待審核 | 3 |
| `frontend/pages/case-management.html` | 最高管理員 | 3 |
| `frontend/pages/audit-log.html` | 歷史紀錄 | 3 |
| `frontend/index.html` | 簽核佇列 | 3 |
| `frontend/index.html` | 等我簽核 | 3 |
| `frontend/pages/shipping-export-history.html` | 歷史紀錄 | 2 |
| `frontend/pages/recycle-bin.html` | 刪除暫存區 | 2 |
| `frontend/pages/quotation-form.html` | 申請送出審核 | 2 |
| `frontend/pages/quotation-form.html` | 待審核 | 2 |
| `frontend/pages/module-builder.html` | 送審中 | 2 |
| `frontend/pages/map.html` | 最高管理員 | 2 |
| `frontend/pages/company-setup-required.html` | 最高管理員 | 2 |
| `frontend/pages/company-profile-settings.html` | 超級管理員 | 2 |
| `frontend/pages/change-password.html` | 保存 | 2 |
| `frontend/pages/approval-queue.html` | 簽核佇列 | 2 |
| `frontend/pages/voucher.html` | 保存 | 1 |
| `frontend/pages/users.html` | 超管 | 1 |
| `frontend/pages/recycle-bin.html` | 保存 | 1 |
| `frontend/pages/quotations.html` | 簽核佇列 | 1 |
| `frontend/pages/quotations.html` | 待審核 | 1 |
| `frontend/pages/quotation-form.html` | 超級管理員 | 1 |
| `frontend/pages/payslips.html` | 待審核 | 1 |
| `frontend/pages/org-structure.html` | 超級管理員 | 1 |
| `frontend/pages/dev-crm.html` | 歷史紀錄 | 1 |

## 3. 禁用詞（扣除白名單後）

| 檔案 | 詞 | 畫面文字 | JS 字串 |
|---|---|---|---|
| `frontend/pages/audit-log.html` | 影子模式 | 1 | 1 |
| `frontend/pages/change-password.html` | Provider | 1 | 0 |
| `frontend/pages/company-profile-settings.html` | endpoint | 1 | 0 |
| `frontend/pages/expense-types.html` | JSON | 1 | 0 |
| `frontend/pages/expense-types.html` | 版本帳本 | 1 | 0 |
| `frontend/pages/lodging-records.html` | JSON | 1 | 0 |
| `frontend/pages/module-builder.html` | 版本帳本 | 1 | 0 |
| `frontend/pages/notification-settings.html` | SMTP | 4 | 1 |
| `frontend/pages/remit-kinds-settings.html` | 版本帳本 | 1 | 0 |

## 4. 各頁頁頭與主按鈕（HTML 頁，只列有問題者）

| 檔案 | H1 | 有 `.pg` 頁頭 | 頁頭內主按鈕 | 全頁 `.btn-primary` | 行內樣式 | `toLocaleString(` |
|---|---|---|---|---|---|---|
| `frontend/pages/account-items.html` | 0 | 否 | 0 | 1 | 11 | 0 |
| `frontend/pages/approval-queue.html` | 0 | 否 | 0 | 3 | 108 | 3 |
| `frontend/pages/audit-log.html` | 0 | 否 | 0 | 0 | 10 | 3 |
| `frontend/pages/bank-account.html` | 0 | 否 | 0 | 0 | 7 | 0 |
| `frontend/pages/bonus-corrections.html` | 0 | 否 | 0 | 0 | 22 | 3 |
| `frontend/pages/bonus.html` | 0 | 否 | 0 | 0 | 29 | 3 |
| `frontend/pages/case-management.html` | 0 | 否 | 0 | 2 | 1557 | 3 |
| `frontend/pages/completion-note-form.html` | 0 | 否 | 0 | 0 | 62 | 0 |
| `frontend/pages/contractor-voucher-approval-settings.html` | 0 | 否 | 0 | 0 | 0 | 0 |
| `frontend/pages/customer-log.html` | 0 | 否 | 0 | 0 | 20 | 0 |
| `frontend/pages/daily-tasks.html` | 0 | 否 | 0 | 5 | 241 | 0 |
| `frontend/pages/dev-crm.html` | 0 | 否 | 0 | 13 | 111 | 0 |
| `frontend/pages/ledger-hub.html` | 0 | 否 | 0 | 0 | 21 | 3 |
| `frontend/pages/ledger-periods.html` | 0 | 否 | 0 | 0 | 19 | 3 |
| `frontend/pages/ledger-reports.html` | 0 | 否 | 0 | 0 | 7 | 3 |
| `frontend/pages/ledger-settings.html` | 0 | 否 | 0 | 0 | 15 | 0 |
| `frontend/pages/ledger-statements.html` | 0 | 否 | 0 | 0 | 7 | 3 |
| `frontend/pages/login-qr-approve.html` | 0 | 否 | 0 | 0 | 3 | 0 |
| `frontend/pages/login.html` | 0 | 否 | 0 | 0 | 9 | 0 |
| `frontend/pages/module-versions.html` | 0 | 否 | 0 | 2 | 11 | 0 |
| `frontend/pages/quotation-form.html` | 0 | 否 | 0 | 6 | 462 | 3 |
| `frontend/pages/quotations.html` | 0 | 否 | 0 | 1 | 85 | 3 |
| `frontend/pages/receivables.html` | 0 | 否 | 0 | 0 | 0 | 0 |
| `frontend/pages/reports.html` | 0 | 否 | 0 | 0 | 288 | 3 |
| `frontend/pages/sales-orders.html` | 0 | 否 | 0 | 0 | 0 | 0 |
| `frontend/pages/schema-status.html` | 0 | 否 | 0 | 0 | 2 | 3 |
| `frontend/pages/settlement.html` | 0 | 否 | 0 | 2 | 273 | 3 |
| `frontend/pages/shipping-export-history.html` | 0 | 否 | 0 | 0 | 2 | 0 |
| `frontend/pages/supplier-log.html` | 0 | 否 | 0 | 0 | 20 | 0 |
| `frontend/pages/voucher.html` | 0 | 否 | 0 | 0 | 47 | 3 |
| `frontend/pages/work-log.html` | 0 | 否 | 0 | 0 | 7 | 0 |

## 5. 狀態詞彙一致性（`status-chip.js` MAP vs `status_display.py` STATUS_KEYS）

- MAP 鍵 14 個、顯示名稱表鍵 30 個。
- 只在 `status-chip.js`：（無）
- 只在顯示名稱表：draft、finalized、差額已核可、差額待審核、已成案、已提供、已收款、已結案、已送出、已過帳、待收款、成案、暫擱置、未成案、未提供、洽談中（這些鍵沒有色調對照，畫面會是中性色；多數是 deal／devcase 群組，屬預期）
