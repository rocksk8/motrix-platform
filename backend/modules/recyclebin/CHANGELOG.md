# 刪除暫存區 更新紀錄

## (next) — 2026-10-10（wip/t53-ab-recyclebin-p0）：頁面 e2e、『刪除已核可』入口改用 write_txn、隔離目錄預設從 UPLOADS_ROOT 推
- 『刪除已核可』端點的寫入交易改走 `core.txn.write_txn`（begin-only 守門）；隔離目錄預設＝uploads 的上一層「資源回收筒」（測試換 UPLOADS_ROOT 時自動跟著換，不寫真的安裝目錄）。
- 頁面 `recycle-bin.html` 的 e2e（superadmin：列表、詳情遮罩、還原、永久刪除二次確認；一般管理員被平台權限頁擋下）。

## 1.0.0 — 2026-10-10（wip/t53-ab-recyclebin-p0）：P0——模組骨架、隔離目錄、adapter 契約、每日清除、最高管理者 API 與頁面
- 新模組 `recyclebin`（M15；使用者 D2 獨立模組）。表 `recycle_bin`（T1；`snapshot_json`／`files_manifest_json` 整欄為 F2，一般備份排除）。沒有 core schema 版本升級。
- L1 契約 `helpers/recycle_bin.py`：能力 `recyclebin.adapter`（擁有模組提供）、`recyclebin.delete`（本模組提供）；擁有模組不在／本模組不在都是明確的缺席，不靜默。
- 隔離目錄 `<安裝根目錄>\資源回收筒`（可改到樹外）：附件搬進（不複製），還原搬回，清除整個刪掉；交易回滾留下的孤兒由每日工作搬回原路徑。
- 每日工作：清除超過 30 天（固定，D4）的項目並逐筆稽核、孤兒隔離檔搬回、磁碟水位告警；清除／水位超標通知所有最高管理者。
- API（僅最高管理者）：列表、狀態、詳情（快照欄位遮罩）、還原（失敗保留在暫存區並記原因）、永久刪除（二次確認）、『刪除已核可』入口與影響清單（P0 無 adapter ⇒ 404）、隔離目錄設定；頁面 `recycle-bin.html`（系統群組）。
- 稽核動作：recyclebin.restore／restore_failed／purge_manual／purge_auto／delete_approved／reconcile／disk_warn／settings。
- 三道守門（tests/platform/test_recyclebin_guards_t53.py）：DELETE 路由、`DELETE FROM` 表覆蓋、直接刪檔——各有基線（P1 逐步接入）與突變題。P0 **不含**任何單據 adapter。
