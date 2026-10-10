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

## 進度
- [ ] 1 骨架（module.json／README／SPEC／CHANGELOG／migration／註冊 modules.json、sidebar）
- [ ] 2 L1 契約 helpers/recycle_bin.py ＋ IP 文件 ＋ core CHANGELOG (next) ＋ L1 快照
- [ ] 3 store／quarantine／purge job／通知／稽核
- [ ] 4 API ＋ 頁面
- [ ] 5 archive F2 宣告
- [ ] 6 三道守門＋EXEMPT＋突變題
- [ ] 7 測試（模組內）、guards 全跑一次、author_gate
