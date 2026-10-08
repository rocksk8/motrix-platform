# 第 48 班小項票（不在第 47 班修）

> 第 47 班獨立審查／稽核時順手發現、使用者決定先不修的小項。每項：現象、位置、建議。

1. **供應商紀錄頁 JS 例外（一般角色）**：`frontend/pages/supplier-log.html` 以業務／工程師角色開啟時會丟 `Cannot read properties of undefined (reading 'length')`（pageerror）。未改動的基底就同樣發生（第 47 班 `test_e2e_users_list_privacy_pages` 量到，該頁在 e2e 內先濾掉這一條）。建議：找出讀 `.length` 的未定義陣列（多半是只有管理員才回的欄位），加預設空陣列；修好後把 e2e 的濾除拿掉。
2. **audit_log 直接寫入繞過 `helpers.audit._derive_fields`**：R2 第 2 步的 `helpers/duty_roles._write_audit` 直接 INSERT，`module` 取動作前綴、不推 `case_no`／`ref_no`、不套 detail 上限。建議：改用 `_derive_fields`（或抽出共用的『在既有交易內寫一筆稽核』函式），讓稽核頁依模組篩選時 `duty_roles.*` 與其他動作一致。
3. **使用者清單 `hasAccess()` 對空 `modules` 回退到基礎類別樣板**：`frontend/pages/users.html` 的存取矩陣對 `modules` 為空者仍顯示樣板權限，但後端 `effective_modules` 沒有這個回退（實際零權限）。R2 第 3 步（停用回收、重新啟用＝全空）上線前要一併改，否則清單顯示與實際不一致。
4. **R2 第 2 步存檔順序的殘餘**：`users-duty.js` 先解除扣項再 PUT；若 PUT 失敗，解除扣項已生效（管理員自己的意圖、有稽核），但畫面只在『解除扣項失敗』時說明『基本資料尚未儲存』。建議：PUT 失敗時補一句『已解除扣項 X，但其餘變更未儲存』。
