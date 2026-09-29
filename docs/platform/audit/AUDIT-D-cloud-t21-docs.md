# AUDIT-D：wip/cloud-t21-docs（9b682e30，基底 70ec2523）

2026-09-29｜依 8c34f08a：只看文件與探針。**必修 0 項；建議 2 項。**

## 已驗
- COMPANY-SETUP-GATE §6.7 三處更正（(a) 第 2 步預期 `no_record`、(d) 路徑二第 1 步、(c) 第 3 步改請使用者手動刪）都用刪除線保留原文並註明日期、來源（RUN-PLAN §6 T21-2／T21-3），符合「更正留著錯的那一列」✔
- `helpers/company_setup.py` 仍同時定義 `NO_RECORD`／`DEVELOPER_UNSIGNED`，更正只改預期值、不動程式 ✔
- 回報摘要新增欄「使用者是否已刪雲端確認檔」：明訂不影響是否套用、`否`／`未確認` 要列完整路徑給開發機轉待辦 ✔

## 建議
### D-t21docs-S1 客戶可見的版本紀錄（manifest 29e）含供應商自家資訊
29e 最後一句「系統供應商自家使用的正式機，改以永久有效的簽章確認檔登記，不會到期、也不會提醒重簽」會隨包進客戶的版本紀錄，對客戶無用，且揭露供應商內部作法。與 CORE-SPEC「販售包去識別化」（暫緩中，但 E4 Q5 明列「版本紀錄內文的開發者資訊另開一線」）方向相反。建議刪掉該句。
### D-t21docs-S2 §6.3 L280 同錯未改
`正式機 Claude 指示寫明各代碼的處置（developer_identity_unsigned ⇒ 先做 6.2 的簽章檔 …）`：開發者庫「沒有確認紀錄」時實際回 `no_record`（更正列已寫明），這句仍只列 `developer_identity_unsigned`。同源的字面還在 `tools/apply_update.ps1:807` 的處置提示與 `tools/company_setup_cli.py:56` 註解。建議一併改成「`no_record`（developer:true）／`developer_identity_unsigned`／`install_mismatch`」，否則正式機 Claude 依訊息只認一個代碼。
