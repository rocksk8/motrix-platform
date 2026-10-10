# 刪除暫存區（recyclebin）

任何單據的刪除先進這裡（資料列快照＋附件搬進隔離目錄），**只有最高管理者看得到、能還原**；30 天沒人還原就自動清除。
使用者決定（2026-10-10）：D1 不放寬『只有草稿能刪』，另設最高管理者專用『刪除已核可』入口（二次確認＋影響清單）；D2 獨立模組；D3 第一期 10 類核心單據；D4 固定 30 天、列表遮罩敏感欄位。

## 功能（P0）
- 頁面：「系統 → 刪除暫存區」（`recycle-bin.html`）：列表／詳情（遮罩）／還原／永久刪除（二次確認）。
- 端點（`/api/recycle-bin`，僅最高管理者）：`GET /`、`GET /status`、`GET /impact`、`GET /{id}`、`POST /{id}/restore`、`DELETE /{id}?confirm=永久刪除`、`POST /delete-approved`、`PUT /settings`。
- 每日工作：清除超過 30 天、孤兒隔離檔搬回、磁碟水位告警。
- **P0 沒有任何單據 adapter**——P1 由各擁有模組各自提供（`ModuleSpec.providers[("recyclebin.adapter", "<entity_type>")]`），並把刪除端點改呼叫 `helpers.recycle_bin.delete`。

## 資料分類
- 表 `recycle_bin`：T1。`snapshot_json`、`files_manifest_json` 含個資原文 ⇒ F2 欄位（一般每日 JSON 備份排除，完整列只進個資資料夾）。
- 隔離檔（`資源回收筒` 資料夾）：F3——**永不上雲、不進每日匯出**；本機 DB 備份只含表。

## 串接點
- IP-RB1 `recyclebin.adapter`（擁有模組 → 本模組；多提供者）、IP-RB2 `recyclebin.delete`（本模組 → 擁有模組的刪除端點；單一提供者）。編號暫定，列車定號。
- 對方不在：本模組不在 ⇒ `helpers.recycle_bin.delete()` 回 None，擁有模組端點照舊硬刪並在回應與稽核明說；某擁有模組不在 ⇒ 該類型沒有 adapter，列表照顯示但還原回 409『擁有模組未載入』。

## 開發者
- 契約與預設遮罩規則：`backend/helpers/recycle_bin.py`；核心動作：`service.py`；隔離檔搬移（模組內唯一動檔案的地方）：`quarantine.py`；每日工作：`jobs.py`。
- 守門：`tests/platform/test_recyclebin_guards_t53.py`；模組測試：`modules/recyclebin/tests/`。
