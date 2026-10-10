# 設定中心 Train A 實作狀態備忘（S0＋S2；給 context 壓縮／換手接手）

更新：2026-10-10 傍晚。分支 `wip/t54-n39-settings-s0s2`（工作樹 `D:\開發測試檔\n39-s0`；基底 origin/platform `b2486535c`；**本地 commit，尚未 push**，HEAD d7140d627 之後只有本檔更新）。
規則：只有我寫這個分支；與 recyclebin 完全不重疊；單程序輕量測試；不 merge／不部署；上線**零行為變更**；(next) 區塊每模組一則；里程碑回報 node-d8。
**安靜規則（node-d8，10-10）**：官方閘門（第 53 班）在跑時，不跑 pytest／建置；等 node-d8 宣布 gate 結束再跑 `tests/platform` 全跑。第 54 班小修與第 55 班框架**合併為一班**，在第 53 班上線後出貨，Train A 搭這一班；保持可 rebase（新分支名，不強推）。

## 相關分支與最新 SHA
| 分支 | 內容 | SHA |
|---|---|---|
| wip/t54-n39-settings-s0s2（本地） | Train A 程式 | d7140d627 |
| wip/t54-n39-settings-design | 設計稿（§2.1 與 1d 同文、附錄 B 鎖定清單、C 零技術門檻/影響、D 安全/雙人/預設組） | 846f04f9e |
| wip/t54-n39-guide-framework | MODULE-GUIDE §15（含 15.8–15.10 UX/影響/碰到就框架化）、CORE-SPEC 裁示列、plans/FRAMEWORKIZE-DEBT-T54.md | dad3ab7d8 |
| wip/t54-n39-program | FRAMEWORKIZE-PROGRAM-T54.md（DONE、框架層、矩陣 363 項、合併班 M1–M4）、LOCKED-LIST-CHECKLIST（已裁示）、framework_sweep_matrix_t54.csv、configurability_gaps_t54.csv | 8451d9c3e |

## 已完成（Train A 程式，皆有測試）
- L0 `definitions.publish_direct`；core migration（NEXT 佔位）`config_changes`（含 approvals_required）＋`config_change_events`（含 approved）；
- `helpers/config_ledger.py`（record/history/register_domain/pending/cancel/supersede/approve/activate_due(domain)/in_effect/restore_version…）；
- `helpers/settings_registry.py`（SettingDef 必填 question/label/help/impact＋risk_text；requires_pending 24h；loosen＋雙人核准；edition bounds；profiles；materialize_due；15 秒快取以 DB 路徑為鍵；DEFAULTS_ONLY）；
- `helpers/settings_groups.py`（retention 8 欄、uploads 3 欄，預設＝舊常數；凍結基準 `tests/platform/settings_deploy_baseline.json`）；
- S2 接線：archive._backup_retention、舊 PATCH backup-retention（稽核下限 365＋publish 雙寫舊鍵）、audit.purge_old_notifications、system_checks._prune_request_log、uploads.limits_for/max_file_bytes、daily_checks 呼叫 materialize_due；
- `routers/settings_center.py`（groups、pending、pending/cancel、pending/approve、profiles/preview/apply、public）＋`frontend/pages/settings-center.html`＋menu_l1（order 75）＋l1_pages＋main.py；
- 登記：core CHANGELOG (next)、L1 快照（--update --pending）、route golden（T40_WRITE_GOLDEN）、PAGE_POPULATION+1、write-endpoint EXEMPT（groups POST、profiles apply）。
- 測試：`tests/platform/test_settings_registry_t54.py`、`test_settings_pending_t54.py`、`test_settings_security_t54.py`、`test_settings_ui_plain_language.py`（共 49+ 項綠）；相關既有 110 項綠（backup retention、attach caps、notifications、online activity、voucher attachments、daily checks）。

## 待辦（依序）
1. node-d8 宣布 gate 結束 ⇒ `tests/platform` 全跑（單程序，BelowNormal，basetemp 放 %TEMP%，輸出到檔案，用 `-rf` 列名失敗；不要設會砍掉的 timeout）。上次部分跑到 47%：有 4 個失敗尚未點名（另一次 -x 曾紅 `test_case_summary_purpose::test_only_the_voucher_module_passes_the_voucher_link_purpose`，未確認是否與我有關）。逐一判斷是否為我造成。
2. 修完 ⇒ 若 route/L1/PAGE 計數再變就重產（route golden：`T40_WRITE_GOLDEN=1 pytest modules/case/tests/test_route_table_golden_2026_10_05.py`；L1：`python tests/platform/_l1_interface.py --update --pending`）。
3. `train_preflight.py --static-only`；push `wip/t54-n39-settings-s0s2`；回報 SHA。
4. 第 53 班上線後 rebase（新分支名，不強推）。
5. 之後（M1）：S1 編輯 UI（問句卡片、預設組挑選器、儲存前一句話確認＋影響面板、精靈、一鍵復原）、K01／K08／K10 群組、棘輪守門 `test_no_new_hardcoded_business_values`、各框架操作手冊（系統內頁側顯示）。
6. 盤點補漏已完成（GAP 82 列）；credit 僅名目。

## 重要實作決定
- 郵件類型本批不新增；高風險變更只發站內通知（`ledger.record` 在呼叫端交易內直接 INSERT notifications）。
- 寫入口唯一：`settings_registry.publish(...)`；放寬（loosen）方向＝待生效＋雙人核准；只有一位超管＝原因＋24h＋警告。
- 版本邊界 `set_edition_bounds` 只由程式／授權載入器呼叫，沒有客戶 API（有守門）。
- 部署不寫任何定義列；無列＝程式預設（正式機實查：backup_retention 無列，audit_log_keep_days 實際 1825）。
- `UPLOAD_LIMITS_BY_SUBFOLDER`／`_MAX_FILE_SIZE` 保留為程式預設與測試覆寫縫隙。
- 使用者裁示摘要：框架優先不鎖死內容；碰到就框架化；白話零技術介面；每選項說明影響；安全項目雙向可調、放寬雙人核准；鎖定清單 A/B/C/D 已裁示（見 LOCKED-LIST-CHECKLIST-T54.md）。
