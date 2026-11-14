# 刪除暫存區 更新紀錄

## 1.0.13 — 2026-11-14（feat/t86-b1-h2；T86 文字：看得到／看到等權限與顯示用語）
- 文字（行為、API、欄位、設定鍵、錯誤碼不變）：說明與提示中的「看得到／看不到／看到」依語境改為「可檢視／無法檢視」（權限）或「顯示／所見」（畫面），並補正前一批漏改的空狀態文字。
- **（併入）(next) — 2026-11-14（feat/t86-short-labels-h2；T86 短標籤專業化）**
- 文字（行為、API、欄位、設定鍵、錯誤碼不變）：按鈕、卡片標題、表頭、空狀態與提示等短標籤改為正式、一致的用語（前往／查看、尚無／查無符合條件的…、僅顯示、無法…等）；前後對照見整合者的 T86 前後對照表。

## 1.0.12 — 2026-11-14（train/t85-text；T85 文字專業化；版號由列車取）
- 文字（行為、API、欄位、設定鍵、錯誤碼不變）：畫面、通知、錯誤提示與說明文字改為正式、一致的用語（您、尚未／尚無、是否、其他使用者、無法／不可等），標點與中英文間距依 `docs/platform/plans/TEXT-STYLE-GUIDE.md`；同一提交同步更新斷言字串的測試。逐項前後對照見 `docs/platform/plans/TEXT-DIFF-TABLE.md`。

## 1.0.11（next，未取號）— 2026-11-13（fix/demo-approver-h11；展示帳號不列入簽核／通知名單）
- 變更（內部，不影響對外介面）：`service.superadmins` 通知名單改用真人最高管理者，不含展示帳號 `demo`。

## 1.0.10 — 2026-11-13（feat/ux-p15-dashboard；UX P1.5）
- 前端（文字）：頁面 `<title>` 後綴「專案管理系統」一律改為「MOTRIX PLATFORM」（系統標語改由公司設定 `brand.tagline` 決定，預設 MOTRIX PLATFORM）；不動 API／資料／權限。

## 1.0.9 — 2026-11-13（fix/t81-line-reds；T81 LINE 全信件接線的 CHANGELOG 補記，版號由列車取）
- 變更（前端）：`recycle-bin.html` 手機（≤767px）與直立平板（≤1023px）版面——8 欄表格改一筆一張卡，「還原」「永久刪除」並排且加大間距避免誤觸，輸入框 16px／44px 高。桌機版不變。（由 fix/mobile-cases-layout-v2 合入；條目於 T81 整合補記。）無 API／資料／權限判斷變更。

## 1.0.8 — 2026-11-11（fix/t80-conn-leak-net；每日清除失敗分支先放寫鎖；L1 介面不變）
- 修正（後端）：`jobs.py run_daily` 的 purge 失敗 `except` 先 `conn.rollback()` 再呼叫 `_audit`。`purge()` 在 `begin_write` 之後遇到非預期例外不會自己 rollback，這條連線仍握著寫鎖，而 `_audit` 另開連線寫入會卡滿 30 秒並吞掉例外（稽核紀錄靜默丟失）。每日背景工作，不影響使用者請求。
- 測試：`tests/test_run_daily_releases_lock_t80.py`（`_audit` 被呼叫那一刻別條連線寫得進去；舊碼紅、新碼綠）。
- 來源：`docs/platform/GET-DB-CONNECTION-LEAK-AUDIT-T80.md` §4.3／R3。無 migration、無新表。

## 1.0.7 — 2026-10-17（wip/t69-recycle-dir-panel-r1；回收筒頁加隔離目錄設定面板）
- `recycle-bin.html` 狀態列下方新增『隔離目錄』面板：可填新目錄或改回預設位置，呼叫既有 `PUT /api/recycle-bin/settings`（最高管理者限定，規則不變：樹外絕對路徑、不可在 uploads 底下、暫存區還有項目時伺服器拒絕）。暫存區有項目時面板停用並說明原因。無新端點、無權限變更、無 migration。守門測試 `tests/platform/test_recycle_bin_dir_panel_t69.py`。
- **（併入）(next) — 2026-10-17（wip/t69-retention-r1；T69 SO-S2：保留天數走設定 `recycle_bin.retention_days`）**
- `service.py` 新增 `retention_days(conn=None)`（讀設定，預設 30；讀不到或不在 7～365 ⇒ 後備 `RB.RETENTION_DAYS`＝30）；`purge_after_for(dt, conn=None)`、狀態 `retentionDays`、`jobs.py` 每日清理的通知文字、`api.py` 刪除已核可的通知，都改用它。預設 30 時輸出與先前逐字相同；已在暫存區的項目到期日不回頭改寫。
- `frontend/pages/recycle-bin.html`：頁首說明與「已送進暫存區」提示的「30 天」改顯示狀態回傳的 `retentionDays`（後備 30）。
- 無 migration、無新表。

## 1.0.6 — 2026-10-10（wip/t50-int；第 50 班）
- **（併入）(next) — 2026-10-10（wip/t54-b5-system-hub-p1；系統中心 P1）：module.json 新增 `system_cards`（『刪除暫存區』卡片；r2）**
- 加性宣告：在系統中心登記資源回收筒；只影響索引顯示，頁面與 API 的權限、行為完全不變。
- **（併入）(next) — 2026-10-10（wip/t54-b5-system-hub-p1；系統中心 P1；r5）：module.json 新增 `system_cards`（『刪除暫存區』卡片；r2）**

## 1.0.5 — 2026-10-10（wip/t53b-int；ab 稽核修正 r5）
- **請求保險網**：`main.py` 中介層 ＋ `recycle_bin.request_scope_begin／end`：請求結束時資料列沒 commit 的刪除，附件搬回（涵蓋報價存檔 PUT 裡 `material_guard` 刪材料申請）。
- **永久刪除改先 commit 再刪檔**（commit 失敗不會出現『列還在、檔案已不見』）；刪不掉的隔離資料夾由 `reconcile` 再刪。
- **孤兒檔搬回遇到原路徑被占用**：改存為 `名稱.rb-<token前6碼>.副檔名` 並記 log，不再把資料夾永遠留在隔離區。
- 守門 `test_recyclebin_guards_t53`：`delete_scope` 不可用在 `async def` 端點。
- **M1 連帶刪除中途失敗**：`service.delete()` 外層 try/except——子單據已搬進隔離區的附件在父層（或後面的子單據）失敗時搬回；另回傳 `rollback_files()` 供呼叫端在 delete() 之後、commit 之前失敗時使用（`/api/recycle-bin/delete-approved` 已用）。
- **刪除已核可必填原因**（`reason` 空白 ⇒ 422，adapter 404 檢查在前）。
- **精確 30 天**：`purge_after` 改存完整時間（秒），到期比對用現在時間；舊列只有日期者仍以當天起算到期。
- **稽核與操作同一交易**：還原／永久刪除／刪除已核可／每日自動清除的稽核紀錄改在同一個交易內寫入（`service.audit_tx`），寫不進去 ⇒ 整筆失敗（永久刪除在刪隔離檔『之前』先寫稽核；刪除已核可失敗會把附件搬回）。
- **呼叫端在 delete() 之後失敗**：L1 新增 `helpers.recycle_bin.delete_scope()`（區塊以例外結束 ⇒ 附件搬回）；擁有模組的刪除端點（arap／case／payroll／subcontract／supply）全部改用。
- 測試 `tests/test_recyclebin_fixes_r5_t53.py`；各 adapter 測試的 delete-approved 請求補 `reason`。

## 1.0.4 — 2026-10-10（wip/t53b-int 整合修正 2）
- `api.py`：內部守門 helper `_sa` 更名 `_require_sa`（系統稽核掃描器認 `_require*` 開頭的守門呼叫；行為不變：仍是 `_require_user(require_superadmin=True)`）。
- `frontend/pages/recycle-bin.html`：狀態下拉標 `class="filter"`（看法類篩選標記守門）。
- 備份匯出祕密欄位守門：`recycle_bin.token`／`group_token`（隔離資料夾名，不是認證素材）登記進 `_SECRET_NAME_OK` 並註明理由。

## 1.0.3 — 2026-10-10（wip/t53b-int 整合修正）
- `frontend/pages/recycle-bin.html`：對話框 `max-height: 86vh` 改為 `calc(86vh / var(--fz,1))`（字級放大時不超出畫面；守門 `test_fz_no_raw_vh_is_left_in_the_frontend`）。純樣式，行為不變。

## 1.0.2 — 2026-10-10（wip/t50-int；第 50 班）
- **（併入）(next) — 2026-10-10（wip/t53-ab-recyclebin-p0）：頁面 e2e、『刪除已核可』入口改用 write_txn、隔離目錄預設從 UPLOADS_ROOT 推；稽核 node-39 六個必修＋兩個建議；1d／05 審查跟進；node-39 再驗證小項；delete 快照前拿寫鎖；adapter after_commit hook；保留單號 reserved_ids；管理員快照上限 50 MB；codes 欄**
- **codes 欄**（json_extract 棘輪守門）：`recycle_bin.codes`（換行分隔的單據代號）在進暫存區當下從快照 `meta.codes` 抄出；`reserved_ids` 只讀這一欄，不再 `json_extract` 讀幾 MB 的快照。模組尚未出貨 ⇒ 直接改 migration 0001（建表含 codes；已建過表的開發庫由同一支 migration 冪等補欄）。

## 1.0.1 — 2026-10-10（wip/t53-ab-recyclebin-p0）：頁面 e2e、『刪除已核可』入口改用 write_txn、隔離目錄預設從 UPLOADS_ROOT 推；稽核 node-39 六個必修＋兩個建議；1d／05 審查跟進；node-39 再驗證小項；delete 快照前拿寫鎖；adapter after_commit hook；保留單號 reserved_ids；管理員快照上限 50 MB（同步）
- 『刪除已核可』端點的寫入交易改走 `core.txn.write_txn`（begin-only 守門）；隔離目錄預設＝uploads 的上一層「資源回收筒」（測試換 UPLOADS_ROOT 時自動跟著換，不寫真的安裝目錄）。
- 頁面 `recycle-bin.html` 的 e2e（superadmin：列表、詳情遮罩、還原、永久刪除二次確認；一般管理員被平台權限頁擋下）。
- **保留單號**（node-39：單號產生器取現存最大號 + 1，最新一張進暫存區後號碼會被重發、還原撞號）：新增 provider `recyclebin.reserved` 與 L1 `helpers.recycle_bin.reserved_ids(conn, entity_type)`（in_bin／restore_failed 的 entity_id ＋ 快照 `meta.codes`）；已還原／已清除釋放。快照上限：一般使用者 5 MB、管理員／最高管理者 50 MB（很大的草稿報價單仍可刪）。
- **commit 之後的 hook**（05／PM 要求）：`Adapter.after_commit(event, entity_id, snap, result)`——還原與『刪除已核可』由本模組在 commit 後自動呼叫；一般刪除的 `delete()` 結果帶 `after_commit` 可呼叫物，端點在自己 commit 後呼叫；錯誤只記 log。`service.delete` 快照前先拿寫鎖。
- node-39 再驗證小項：遮罩加 `tax_id`（個人承攬商的統編可能是身分證）；隔離目錄不可放在雲端存檔／個資／交付資料夾或常見雲端同步資料夾（Google 雲端硬碟、OneDrive、Dropbox、Public…）底下；刪除失敗後空的隔離資料夾清不掉改丟 `BinError`（不丟裸 OSError）；`rmtree onerror` 加 TODO（3.12 改 onexc）。
- 1d／05 審查跟進：provider 宣告改字面字串 `"recyclebin.delete"`（整合點登記表守門只認字面值）；`delete-approved` 的 `confirm_text` 改嚴格字串（truthy 旗標守門）；三道守門的掃描補盲點（別名 import、`api_route`／`add_api_route`、f-string 表名、`from os import remove`、`Path.unlink(p)`、模組內叫 tools 的資料夾）；暫存區自己的永久刪除路由進基線（exempt）；SPEC RBN18 說明『刪除已核可』不跑擁有模組的領域後續動作。
- 稽核 node-39 修正：①遮罩解開 JSON 字串欄位、敏感鍵整個值遮罩、鍵名放寬（`helpers/recycle_bin.mask_obj`）；②隔離目錄設定拒絕 UNC／磁碟機根目錄／系統目錄／包含或在安裝目錄與 uploads 內；③還原與清除拿寫鎖、鎖內重讀、條件式 UPDATE（連點第二次不翻狀態）；④刪除失敗又搬不回附件時保留隔離資料夾（不 rmtree）；⑤清除驗證資料夾真的刪乾淨，刪不掉維持暫存中並稽核 `recyclebin.purge_failed`；⑥`.gitignore` 加 `資源回收筒/`。建議：壞掉的 adapter 工廠記 log；『刪除已核可』通知其他最高管理者。

## 1.0.0 — 2026-10-10（wip/t53-ab-recyclebin-p0）：P0——模組骨架、隔離目錄、adapter 契約、每日清除、最高管理者 API 與頁面
- 新模組 `recyclebin`（M15；使用者 D2 獨立模組）。表 `recycle_bin`（T1；`snapshot_json`／`files_manifest_json` 整欄為 F2，一般備份排除）。沒有 core schema 版本升級。
- L1 契約 `helpers/recycle_bin.py`：能力 `recyclebin.adapter`（擁有模組提供）、`recyclebin.delete`（本模組提供）；擁有模組不在／本模組不在都是明確的缺席，不靜默。
- 隔離目錄 `<安裝根目錄>\資源回收筒`（可改到樹外）：附件搬進（不複製），還原搬回，清除整個刪掉；交易回滾留下的孤兒由每日工作搬回原路徑。
- 每日工作：清除超過 30 天（固定，D4）的項目並逐筆稽核、孤兒隔離檔搬回、磁碟水位告警；清除／水位超標通知所有最高管理者。
- API（僅最高管理者）：列表、狀態、詳情（快照欄位遮罩）、還原（失敗保留在暫存區並記原因）、永久刪除（二次確認）、『刪除已核可』入口與影響清單（P0 無 adapter ⇒ 404）、隔離目錄設定；頁面 `recycle-bin.html`（系統群組）。
- 稽核動作：recyclebin.restore／restore_failed／purge_manual／purge_auto／delete_approved／reconcile／disk_warn／settings。
- 三道守門（tests/platform/test_recyclebin_guards_t53.py）：DELETE 路由、`DELETE FROM` 表覆蓋、直接刪檔——各有基線（P1 逐步接入）與突變題。P0 **不含**任何單據 adapter。
