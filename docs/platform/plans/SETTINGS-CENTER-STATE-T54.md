# 設定中心 Train A 實作狀態備忘（S0＋S2；給 context 壓縮後接手）

分支 `wip/t54-n39-settings-s0s2`（工作樹 `D:\開發測試檔\n39-s0`；基底 origin/platform `b2486535c`）。設計稿 `SETTINGS-CENTER-DESIGN-T54.md`（wip/t54-n39-settings-design 4650157e7）。
規則：只有我寫這個分支；與 recyclebin 完全不重疊；單程序輕量測試；不 merge／不部署；上線**零行為變更**；(next) 區塊每模組一則；里程碑回報 node-d8。

## PM 與 1d 的決定（2026-10-10）
- 五個利潤警示門檻**不統一**（K01 之後做，群組 `profit_warning` 七個數字）；稽核紀錄保存下限 365、無上限、讀取時向上夾到 365（S2 前請 node-d8 問正式機現值，預期 1825）；非敏感群組可經公開端點給所有登入者讀，敏感／高風險群組要設定權限。
- Train A＝S0（`setting_group` kind、`helpers/settings_registry.py`、快取 `settings.get`、公開端點、登錄產生的「系統 > 設定中心」索引頁）＋S2（K05＋K06：保存期限與上傳容量）。完整編輯 UI（S1）在乙班。
- **config_ledger 與 1d 對齊（我實作）**：L1 `helpers/config_ledger.py`；`config_changes` 列不可變（觸發器）；狀態不是欄位，用 append-only `config_change_events(change_id, event pending|activated|cancelled|superseded, actor, reason, at)`，目前狀態＝最後一個事件（沒有事件＝立即生效）；`record(domain,key,changes,reason,actor,*,ip,risk,ref_version,effective_at)` 同交易寫 `audit_log` 並在 risk≥money 通知其他 superadmin；`register_domain(domain, snapshot_fn, restore_fn, diff_fn)`；`history(domain,key)`；`pending()/cancel()/activate_due(now)` 與純函式 `in_effect(row, now)`（簽名先定，實作可較晚）。權限矩陣不雙寫：只進 domain `perm`；R1/R2 `permission_changes` 當 domain `duty` 的歷史，不搬資料。還原含待生效項 ⇒ 該 domain 的 restore 取消它們。

## 進度
- [ ] 狀態備忘（本檔）
- [ ] L0 `definitions.publish_direct`（不經草稿、可不 commit）
- [ ] 核心 migration（NEXT）：`config_changes`、`config_change_events`（觸發器）
- [ ] `helpers/config_ledger.py`
- [ ] `helpers/settings_registry.py`（SettingDef、register_group、get/get_group、快取、DEFAULTS_ONLY、validate、publish）＋ kind `setting_group`
- [ ] `helpers/settings_groups.py`（登錄 `retention`、`uploads`；預設＝舊常數）
- [ ] `routers/settings_center.py`＋頁面索引＋選單＋l1_pages
- [ ] S2 接線：`archive._backup_retention`、PATCH backup-retention（稽核 ≥365、雙寫舊鍵）、`audit.NOTIFICATION_RETENTION_DAYS`、`system_checks._prune_request_log`、`uploads` 容量
- [ ] 守門與測試：registry、ledger、API、deploy baseline（`settings_deploy_baseline.json`）、no-legacy-literal、既有備份保留測試
- [ ] 登記類：core CHANGELOG (next)、`core_bump --pending` 快照、route golden（`T40_WRITE_GOLDEN=1`）、PAGE_POPULATION、modules.json、write-endpoint EXEMPT、manifest 佔位
- [ ] 作者自查（PLAYBOOK §G5）、預檢 `train_preflight.py --static-only`

## 重要實作決定
- 郵件類型本批不新增（core 類型要手寫進固定清單，守門多）；高風險變更只發站內通知，信件留給乙班。
- `ledger.record()` 在呼叫端交易內直接 INSERT notifications（不呼叫 `_notify`：它自己開連線，會撞寫鎖）。
- 寫入口：`settings_registry.publish(group, values, note, user, ...)` 是唯一入口（設定中心 POST 與舊 PATCH 都走它）。
