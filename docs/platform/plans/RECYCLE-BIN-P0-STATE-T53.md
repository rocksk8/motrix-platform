# 刪除暫存區 P0 — 進度與決定（第 53 班；給 context 壓縮後接手用）

分支 `wip/t53-ab-recyclebin-p0`（工作樹 `D:\開發測試檔\t53-ab-recyclebin`，基準 origin/platform `b2486535c`）。設計稿 `RECYCLE-BIN-DESIGN-T52.md`（本班依下列裁示修訂，不另開新稿）。
規則：只有我（ab）寫這個分支；單一程序輕量測試；不 merge／不部署；(next) 區塊每模組一則；里程碑回報 node-d8（骨架、完整 P0）。

## 使用者裁示（PM node-d8 轉，2026-10-10）
- D1：**不放寬**「只有草稿能刪」；另開 superadmin 專用「刪除已核可」入口，二次確認＋影響清單（已付款／已入獎金／已回簽）——入口與影響清單是 P1 的各 adapter 責任，P0 只定介面（`impact(conn,id)`）。
- D2：獨立模組 `recyclebin`（M15）。D3：第 1 期＝10 類核心單據（P1，之後由 PM 派給各窗口寫 adapter）。
- D4：保存期固定 30 天；快照僅 superadmin 可見，**列表視圖遮罩敏感欄位**，還原時還原原文。
- P0 範圍：模組骨架、`recycle_bin` 表、隔離目錄、adapter 介面（IP 登記、L1、加性）、每日 30 天清除（稽核）、superadmin API＋「系統」頁（列表／詳情（遮罩）／還原／永久刪除二次確認）、稽核動作、還原／清除通知、三道守門（路由表、`DELETE FROM` 表覆蓋、直接刪檔）各有 EXEMPT 與突變題。**不含**任何單據 adapter。

## 我做的設計決定（PM 請複核）
1. **L1 契約** `backend/helpers/recycle_bin.py`（unit `helper:recycle_bin`）：`Adapter` 基底類別（`entity_type, label, can_delete, snapshot, delete_in_tx, restore_in_tx, impact, purge_files, mask, cascade_children`）；能力名 `recyclebin.adapter`（各擁有模組以 `ModuleSpec.providers[("recyclebin.adapter", entity_type)]` 提供）與 `recyclebin.delete`（recyclebin 模組提供，擁有模組的刪除端點呼叫 `recycle_bin.delete(...)`；**模組不在 ⇒ 回 None，呼叫端走舊的硬刪並明說**，不得靜默）。IP 編號暫定 IP-RB1／IP-RB2，列車定號。
2. **隔離目錄**：預設 `core.paths.RECYCLE_DIR` ＝ `root("資源回收筒")`（與 `報價單PDF` 等並列、git 忽略、不在 `uploads/` 下 ⇒ 不被 `_mirror_uploads` 鏡像上雲、不被檔案開啟路由服務）；`system_settings.recyclebin_dir` 可由 superadmin 改到樹外絕對路徑。檔案以 `os.replace` **搬**進 `<根>/<bin_id>/<原相對路徑>`；跨磁碟時退化為「複製→驗 sha256→刪原」。隔離檔含個資 ⇒ 視為 F2：**永不上雲**、不進每日匯出。
3. **表分類**：`recycle_bin` ＝ T1；`snapshot_json`／`files_manifest_json` 整欄在 `archive._F2_FIELDS` 宣告為 F2（一般 JSON 備份排除，完整列只進個資資料夾）。本機 sqlite 備份含整表。
4. **磁碟水位**：`GET /api/recycle-bin/status` 回總量／筆數／最舊；超過門檻（預設 5 GB）寫告警（不自動提前清除）。
5. 沒有 core schema 版本升級：新表走模組 migration（`module_schema_versions`）。

## 進度（2026-10-10）
- [x] 1 骨架：module.json／README／SPEC（RBN1～RBN11）／CHANGELOG 1.0.0／migration 0001／modules.json M15／sidebar 由 module.json 的 pages 帶入
- [x] 2 L1 契約 `helpers/recycle_bin.py` ＋ INTEGRATION-POINTS IP-RB1／IP-RB2 ＋ core CHANGELOG (next) ＋ L1 快照（core_bump --pending）
- [x] 3 service／quarantine／jobs（每日清除、孤兒搬回、水位告警）／通知／稽核
- [x] 4 API（僅 superadmin）＋ 頁面 `frontend/pages/recycle-bin.html`（Alpine 母體 +1、已更新 test_alpine_double_init 的 PAGE_POPULATION）
- [x] 5 `archive._F2_FIELDS`：`模組-recyclebin-recycle_bin` 整欄 snapshot_json／files_manifest_json 為 F2（test_pii_archive_mirror 種一列）
- [x] 6 三道守門 `tests/platform/test_recyclebin_guards_t53.py` ＋ 基線 `recyclebin_baseline_t53.json`（60 路由／70 表／16 檔；p1 路由 9 條＝報價單、額外費用單、完工單、請款單、收款憑據、勞報單、承攬商派發、承攬商匯款申請、出貨單；材料申請走 `DELETE FROM case_material_approvals` p1）
- [x] 7 模組測試 19 題（17 單元／API＋2 e2e）全綠；結構守門（package files／data classes／spec coverage／catalog／route ownership／L1 snapshot／audit／begin-only／alpine／pii／page paths／module selection）全綠
- [ ] 8 作者閘門（author_gate）、changelog 守門在最後一次 commit 後再跑、回報 PM
- 產生檔（dep_graph.json、UNIT-INDEX.md、test_map.json）**不由分支提交**（列車規則）；`regen_all --check` 會顯示過期是預期。

## P1 交接備忘（PM 派給各窗口時用）
- 每個擁有模組新增 `modules/<key>/recycle_adapter.py`（`Adapter` 子類別；`snapshot` 含子表列與附件 `{root:'uploads',rel}`；`delete_in_tx` 內的 `DELETE FROM` 免守門登記）、在 `ModuleSpec.providers` 登記 `("recyclebin.adapter","<entity_type>")`。
- 把刪除端點改成：`res = recycle_bin.delete(conn, "<type>", id, user)`；回 None（暫存區模組不在）⇒ 走舊的硬刪並在回應 notice 與稽核明說；丟 `BinError` ⇒ 轉 409/400 並帶原因。**並把基線 `routes`／`delete_from`／`file_removals` 對應項目刪掉**（棘輪）。
- 『刪除已核可』：adapter 實作 `can_delete_approved`（不可刪的狀態：已付款、已入獎金…要回 False＋原因）與 `impact`（已付款／已入獎金／已回簽）。
- 還原衝突：單號被占用 ⇒ `BinError('conflict: …')`（P1 可選擇『以新單號還原』）；父層不在 ⇒ `parent_missing:`。
