# 設定中心 Train A 實作狀態備忘（S0＋S2；給 context 壓縮／換手接手）

更新：2026-10-12（換手：node-39 → hichan-1d）。分支 `wip/t54-n39-settings-s0s2-r8` @ `09c9c2c53`（鏈：r4 5ad288732→r5 23b57f5fc→r6 32e319606→r7 6438b57cf→r8；已 push；ab 稽核 PASS；M2 r2 官方閘門 `train/m2-int-r2` 8207b54d8 測試中）。本檔更新在 r9（只動文件）。
規則：**閘門期間（安靜規則）不跑 pytest／重型作業**；M2 上線並驗證前不開始新程式；自己寫的分支不自審（ab／05／b5 稽核）；新分支名、不強推；上線零行為變更；(next) 區塊每模組一則；里程碑回報 node-d8。

## 相關分支與最新 SHA
| 分支 | 內容 | SHA |
|---|---|---|
| wip/t54-n39-settings-s0s2-r8 | Train A 程式（工作樹 `D:\開發測試檔
39-s0b`；紀錄 `n39-s0b-*.txt`） | 09c9c2c53 |
| wip/t54-n39-settings-design-r2 | 設計稿；含報價單「擇一方案」§9.12（`QUOTE-CASE-DISPLAY-FRAMEWORK-SCOPE-T54.md`，工作樹 `n39-sd`） | 921c6ddf9 |
| wip/t54-n39-program-r3 | 專案總表 FRAMEWORKIZE-PROGRAM-T54.md（§5.2；工作樹 `n39-prog`） | 576fca1b0 |
| wip/t54-n39-guide-framework | MODULE-GUIDE §15、CORE-SPEC 裁示列、FRAMEWORKIZE-DEBT-T54.md | dad3ab7d8 |

## 已完成（Train A 程式，皆有測試）
- L0 `definitions.publish_direct`；core migration（NEXT 佔位）`config_changes`（含 approvals_required）＋`config_change_events`（含 approved）；
- `helpers/config_ledger.py`（record/history/register_domain/pending/cancel/supersede/approve/promote_due(domain)/in_effect/restore_version…）；
- `helpers/settings_registry.py`（SettingDef 必填 question/label/help/impact＋risk_text；requires_pending 24h；loosen＋雙人核准；edition bounds；profiles；materialize_due；15 秒快取以 DB 路徑為鍵；DEFAULTS_ONLY）；
- `helpers/settings_groups.py`（retention 8 欄、uploads 3 欄，預設＝舊常數；凍結基準 `tests/platform/settings_deploy_baseline.json`）；
- S2 接線：archive._backup_retention、舊 PATCH backup-retention（稽核下限 365＋publish 雙寫舊鍵）、audit.purge_old_notifications、system_checks._prune_request_log、uploads.limits_for/max_file_bytes、daily_checks 呼叫 materialize_due；
- `routers/settings_center.py`（groups、pending、pending/cancel、pending/approve、profiles/preview/apply、public）＋`frontend/pages/settings-center.html`＋menu_l1（order 75）＋l1_pages＋main.py；
- 登記：core CHANGELOG (next)、L1 快照（--update --pending）、route golden（T40_WRITE_GOLDEN）、PAGE_POPULATION+1、write-endpoint EXEMPT（groups POST、profiles apply）。
- 測試：`tests/platform/test_settings_registry_t54.py`、`test_settings_pending_t54.py`、`test_settings_security_t54.py`、`test_settings_ui_plain_language.py`（共 49+ 項綠）；相關既有 110 項綠（backup retention、attach caps、notifications、online activity、voucher attachments、daily checks）。

## r4–r8 修正（稽核與閘門紅燈；皆已綠）
- r4：`modules.json` 補 `/api/settings-center` 前綴（core）。
- r5：舊「備份保留」端點不再雙寫稽核（只留 `publish()` 同交易稽核）＋測試斷言恰一列。
- r6：`config_ledger` 單元卡（EVENTS、audit_event、契約測試檔）；設定變更帳本表納入每日 JSON 備份。
- r7：單元卡 `settings_groups` 公開介面「無」（群組名移至不變式）、`settings_registry` 補 11 個公開名稱。
- r8（M2 not_e2e 紅燈）：`config_ledger.activate_due` 改名 **`promote_due`**（PMX14 名稱守門：權限矩陣的 `activate_due` 不得被其他程式呼叫）；`settings-center.html` 登記為唯讀頁並附理由（AC1，S1 編輯 UI 上線時要從 `READ_ONLY_PAGES` 拿掉）；示範資料重設（DM1）一併清設定帳本（暫時拿掉 append-only 觸發器後重建）＋測試。
- 稽核第 1 輪（b0c285ce1）：`confirm_period_days`（預設 7 天、下限 1 天；來源 `change_control.confirm_period_days`）；retention／uploads 全欄位的放寬判定（0＝永久為最寬）；每個送出欄位都取代既有待生效；取消／核准用 `begin_write` 並同交易稽核；`/pending` 含核准資訊；`materialize` 重新驗證邊界；公司資料頁在有待生效時顯示「已送出，N 天後生效」。

## 待辦（依序）
0. **（現在）** M2 閘門結束且正式機驗證前：只做文件／設計／唯讀稽核；不跑測試。

1. M2 r2 閘門（not_e2e → e2e）通過並上線驗證後：node-d8 宣布結束，才可恢復跑測試。
2. 之後（依 node-d8 指示順序）：S1 編輯 UI（問句卡片、預設組挑選器、儲存前一句話確認＋影響面板、精靈、一鍵復原；上線時從 AC1 `READ_ONLY_PAGES` 移除 `settings-center.html`）→ K01／K08／K10 群組 → `config_epoch`／`next_change_at`（跨程序一致）→ 棘輪守門 `test_no_new_hardcoded_business_values` → 各框架操作手冊。
3. 與權限矩陣（hichan-1d）的接點：權限放寬的真正規則（第二位超管核准＋確認期間）P1 走本帳本；權限端不得呼叫 `promote_due` 以外的本帳本寫入口之外的東西；權限矩陣自己的函式叫 `activate_due`，兩邊名字不可再撞（PMX14）。
4. 報價單「擇一方案」另案：見設計稿 §9.12（`wip/t54-n39-settings-design-r2`）與專案總表 §5.2（`wip/t54-n39-program-r3`）。
6. 盤點補漏已完成（GAP 82 列）；credit 僅名目。

## 重要實作決定
- 郵件類型本批不新增；高風險變更只發站內通知（`ledger.record` 在呼叫端交易內直接 INSERT notifications）。
- 寫入口唯一：`settings_registry.publish(...)`；放寬（loosen）方向＝待生效＋雙人核准；只有一位超管＝原因＋24h＋警告。
- 版本邊界 `set_edition_bounds` 只由程式／授權載入器呼叫，沒有客戶 API（有守門）。
- 部署不寫任何定義列；無列＝程式預設（正式機實查：backup_retention 無列，audit_log_keep_days 實際 1825）。
- `UPLOAD_LIMITS_BY_SUBFOLDER`／`_MAX_FILE_SIZE` 保留為程式預設與測試覆寫縫隙。
- 使用者裁示摘要：框架優先不鎖死內容；碰到就框架化；白話零技術介面；每選項說明影響；安全項目雙向可調、放寬雙人核准；鎖定清單 A/B/C/D 已裁示（見 LOCKED-LIST-CHECKLIST-T54.md）。
