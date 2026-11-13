# 文字盤點彙總（scan_text.py 產生）

| 區塊 | 檔數 | strings | flagged | C1 | C2 | C3 | C4 | C5 | C6 | C7 | C8 | C9 | C10 | long | log |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B1-routers | 47 | 1249 | 43 | 0 | 22 | 2 | 0 | 0 | 10 | 8 | 0 | 8 | 1 | 75 | 33 |
| B2-settings | 20 | 1873 | 23 | 0 | 5 | 0 | 0 | 0 | 6 | 7 | 0 | 2 | 5 | 411 | 26 |
| B3-module-__init__.py | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| B3-module-accounting | 48 | 1274 | 50 | 0 | 5 | 0 | 0 | 1 | 26 | 18 | 0 | 6 | 0 | 54 | 10 |
| B3-module-analytics | 6 | 884 | 22 | 0 | 0 | 1 | 0 | 15 | 2 | 4 | 0 | 2 | 0 | 28 | 10 |
| B3-module-arap | 9 | 362 | 12 | 0 | 0 | 0 | 0 | 1 | 4 | 9 | 0 | 2 | 0 | 12 | 2 |
| B3-module-case | 66 | 2819 | 53 | 0 | 10 | 0 | 0 | 2 | 8 | 33 | 0 | 20 | 1 | 167 | 51 |
| B3-module-crm | 3 | 202 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 1 | 0 |
| B3-module-daily_tasks | 2 | 128 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 |
| B3-module-filehub | 2 | 12 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 1 | 1 |
| B3-module-importer | 3 | 158 | 8 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 2 | 4 | 15 | 18 |
| B3-module-lodging | 6 | 76 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 |
| B3-module-netplan | 4 | 217 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 6 | 0 |
| B3-module-payroll | 27 | 823 | 15 | 0 | 1 | 0 | 0 | 2 | 2 | 10 | 0 | 3 | 0 | 42 | 28 |
| B3-module-permmatrix | 4 | 76 | 3 | 0 | 2 | 0 | 0 | 0 | 0 | 1 | 0 | 1 | 0 | 6 | 0 |
| B3-module-recyclebin | 5 | 72 | 5 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 1 | 0 | 0 | 4 | 9 |
| B3-module-subcontract | 20 | 763 | 14 | 0 | 0 | 0 | 0 | 0 | 7 | 7 | 0 | 2 | 0 | 28 | 3 |
| B3-module-supply | 10 | 199 | 3 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 10 | 0 |
| B3-module-tender_radar | 7 | 173 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 17 | 10 |
| B4-helpers | 130 | 5146 | 163 | 2 | 18 | 5 | 0 | 48 | 11 | 70 | 0 | 20 | 18 | 327 | 283 |
| B5-core | 20 | 441 | 17 | 2 | 6 | 0 | 0 | 1 | 4 | 3 | 0 | 4 | 1 | 17 | 31 |
| B6-other | 24 | 1146 | 42 | 9 | 0 | 1 | 3 | 1 | 17 | 16 | 0 | 12 | 1 | 83 | 82 |
| F1-pages | 90 | 13670 | 276 | 0 | 96 | 7 | 4 | 28 | 14 | 63 | 34 | 219 | 35 | 553 | 0 |
| F2-static-js | 97 | 4223 | 120 | 0 | 35 | 3 | 0 | 51 | 7 | 17 | 0 | 33 | 13 | 178 | 0 |
| J1-json | 39 | 3064 | 203 | 0 | 28 | 21 | 6 | 20 | 18 | 97 | 8 | 108 | 51 | 983 | 0 |
| **合計** | 690 | 39050 | 1074 | 13 | 228 | 40 | 14 | 170 | 147 | 364 | 43 | 446 | 130 | 3021 | 597 |

（flagged＝含 C1～C8、C10 的字串數；C9（✓✗⚠ 等版面符號）只計數；long＝25 字以上的長說明句（需通篇人讀，規則掃不出口語語氣）；log＝開發者看的 log／print，不計入。）

## 每檔（含問題的前 60 檔，依 flagged 排序）

| 檔 | strings | flagged | C1 | C2 | C3 | C4 | C5 | C6 | C7 | C8 | C9 | C10 | long |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| backend/version_manifest.json | 1258 | 186 | 0 | 17 | 21 | 6 | 20 | 15 | 97 | 8 | 103 | 48 | 604 |
| backend/helpers/greeting_phrases.py | 235 | 44 | 2 | 0 | 0 | 0 | 41 | 0 | 0 | 0 | 0 | 5 | 2 |
| frontend/pages/quotation-form.html | 854 | 32 | 0 | 10 | 0 | 0 | 0 | 0 | 8 | 1 | 31 | 13 | 43 |
| frontend/static/email-setup.js | 103 | 29 | 0 | 7 | 3 | 0 | 21 | 0 | 0 | 0 | 6 | 1 | 14 |
| frontend/pages/case-management.html | 1358 | 26 | 0 | 4 | 0 | 1 | 3 | 0 | 2 | 15 | 33 | 1 | 36 |
| backend/modules/analytics/api/reports.py | 695 | 22 | 0 | 0 | 1 | 0 | 15 | 2 | 4 | 0 | 2 | 0 | 15 |
| frontend/pages/network-plan-form.html | 308 | 20 | 0 | 0 | 1 | 1 | 0 | 0 | 18 | 1 | 4 | 0 | 7 |
| frontend/pages/my-account.html | 194 | 17 | 0 | 11 | 0 | 0 | 4 | 0 | 0 | 0 | 3 | 3 | 25 |
| frontend/pages/quotations.html | 334 | 15 | 0 | 11 | 0 | 0 | 0 | 2 | 2 | 0 | 2 | 0 | 12 |
| backend/archive.py | 322 | 15 | 0 | 0 | 1 | 0 | 0 | 10 | 5 | 0 | 1 | 0 | 21 |
| backend/modules/case/expense_notify.py | 93 | 15 | 0 | 0 | 0 | 0 | 0 | 0 | 15 | 0 | 0 | 0 | 3 |
| frontend/pages/customer-log.html | 100 | 14 | 0 | 0 | 0 | 0 | 5 | 0 | 1 | 8 | 0 | 0 | 1 |
| frontend/pages/supplier-log.html | 98 | 14 | 0 | 0 | 0 | 0 | 5 | 0 | 1 | 8 | 0 | 0 | 1 |
| backend/modules/accounting/ledger/tax401.py | 80 | 14 | 0 | 0 | 0 | 0 | 0 | 12 | 2 | 0 | 0 | 0 | 13 |
| backend/modules/accounting/ledger/tax401_media.py | 125 | 14 | 0 | 0 | 0 | 0 | 0 | 12 | 2 | 0 | 0 | 0 | 3 |
| backend/helpers/backup_monitor.py | 137 | 13 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 9 | 20 |
| frontend/static/layout-editor.js | 111 | 12 | 0 | 0 | 0 | 0 | 12 | 0 | 0 | 0 | 0 | 0 | 5 |
| backend/helpers/export_templates.py | 95 | 12 | 0 | 0 | 0 | 0 | 2 | 0 | 10 | 0 | 2 | 0 | 9 |
| backend/core/settings_help.json | 416 | 11 | 0 | 6 | 0 | 0 | 0 | 3 | 0 | 0 | 1 | 2 | 243 |
| backend/db.py | 57 | 11 | 8 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 4 |
| backend/helpers/settings_groups.py | 1153 | 11 | 0 | 1 | 0 | 0 | 0 | 6 | 0 | 0 | 2 | 4 | 297 |
| backend/routers/system.py | 396 | 11 | 0 | 2 | 2 | 0 | 0 | 4 | 3 | 0 | 6 | 0 | 20 |
| frontend/pages/backup-monitor.html | 171 | 10 | 0 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6 | 15 |
| frontend/pages/settlement.html | 581 | 10 | 0 | 8 | 0 | 1 | 0 | 0 | 1 | 0 | 10 | 0 | 36 |
| backend/routers/mail_settings.py | 101 | 10 | 0 | 4 | 0 | 0 | 0 | 5 | 1 | 0 | 1 | 0 | 8 |
| backend/helpers/option_lists.py | 126 | 9 | 0 | 0 | 0 | 0 | 0 | 0 | 9 | 0 | 0 | 0 | 8 |
| backend/helpers/perm_text.py | 33 | 9 | 0 | 1 | 0 | 0 | 0 | 0 | 9 | 0 | 0 | 0 | 1 |
| backend/modules/arap/recycle_adapter.py | 25 | 9 | 0 | 0 | 0 | 0 | 0 | 4 | 7 | 0 | 0 | 0 | 2 |
| backend/modules/case/recycle_adapter.py | 85 | 8 | 0 | 0 | 0 | 0 | 0 | 6 | 3 | 0 | 0 | 0 | 9 |
| backend/modules/importer/parser.py | 150 | 8 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 1 | 4 | 14 |
| frontend/pages/approval-queue.html | 272 | 7 | 0 | 4 | 0 | 0 | 0 | 0 | 2 | 0 | 7 | 1 | 5 |
| frontend/pages/parts.html | 143 | 7 | 0 | 1 | 0 | 0 | 0 | 5 | 1 | 0 | 1 | 0 | 2 |
| frontend/pages/payslip-form.html | 173 | 7 | 0 | 0 | 1 | 0 | 0 | 0 | 6 | 0 | 3 | 0 | 5 |
| frontend/static/attachment-slots.js | 101 | 7 | 0 | 0 | 0 | 0 | 7 | 0 | 0 | 0 | 0 | 0 | 5 |
| frontend/static/form-designer.js | 385 | 7 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 4 | 16 |
| backend/helpers/user_perm_batch.py | 52 | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 7 | 0 | 0 | 0 | 1 |
| backend/modules/case/content_fp.py | 42 | 7 | 0 | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| backend/modules/subcontract/recycle_adapter.py | 41 | 7 | 0 | 0 | 0 | 0 | 0 | 7 | 0 | 0 | 0 | 0 | 0 |
| frontend/pages/cashier.html | 385 | 6 | 0 | 1 | 0 | 0 | 3 | 0 | 1 | 0 | 12 | 1 | 11 |
| frontend/pages/company-profile-settings.html | 339 | 6 | 0 | 3 | 0 | 0 | 0 | 0 | 2 | 0 | 5 | 1 | 32 |
| frontend/pages/import-wizard.html | 148 | 6 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 3 | 4 | 12 |
| frontend/pages/module-builder.html | 349 | 6 | 0 | 2 | 0 | 0 | 1 | 2 | 0 | 0 | 1 | 1 | 15 |
| frontend/js/case-management-exec.js | 157 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 5 | 0 | 1 | 1 | 10 |
| backend/helpers/email_notify.py | 1082 | 6 | 0 | 0 | 3 | 0 | 0 | 0 | 3 | 0 | 1 | 1 | 41 |
| backend/helpers/email_setup.py | 72 | 6 | 0 | 5 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 16 |
| backend/helpers/storage_locations.py | 16 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 6 | 0 | 0 | 0 | 1 |
| backend/modules/case/material_payment.py | 63 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 6 | 0 | 0 | 0 | 4 |
| frontend/pages/contractors.html | 142 | 5 | 0 | 0 | 1 | 0 | 0 | 0 | 4 | 0 | 8 | 0 | 3 |
| frontend/pages/daily-tasks.html | 385 | 5 | 0 | 3 | 0 | 0 | 1 | 0 | 1 | 0 | 13 | 0 | 7 |
| frontend/static/custom-fields.js | 83 | 5 | 0 | 0 | 0 | 0 | 5 | 0 | 0 | 0 | 0 | 1 | 5 |
| backend/helpers/settings_notify.py | 53 | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 5 | 0 | 0 | 0 | 1 |
| backend/modules/recyclebin/service.py | 28 | 5 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 1 | 0 | 0 | 2 |
| frontend/pages/dev-crm.html | 357 | 4 | 0 | 2 | 0 | 0 | 0 | 0 | 2 | 0 | 8 | 0 | 3 |
| frontend/pages/system-hub.html | 32 | 4 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 |
| frontend/static/approval-cascade.js | 30 | 4 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 3 |
| frontend/static/settings-matrix.js | 95 | 4 | 0 | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 1 |
| frontend/static/sidebar.js | 91 | 4 | 0 | 2 | 0 | 0 | 1 | 0 | 1 | 0 | 8 | 0 | 5 |
| frontend/static/user-buttons.js | 86 | 4 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 2 | 5 |
| frontend/static/ux-help.js | 73 | 4 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 16 |
| frontend/js/case-management-list.js | 69 | 4 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 1 |
