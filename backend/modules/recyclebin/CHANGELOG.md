# 刪除暫存區 更新紀錄

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
