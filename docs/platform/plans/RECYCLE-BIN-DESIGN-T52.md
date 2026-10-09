# 刪除暫存區（資源回收筒）盤點與設計（第 52 班；唯讀調查，無程式）

基準 origin/platform `cab72495d`。裁示：任何刪除（含已核准／草稿單據）先進暫存區，連附件；僅 superadmin 可看／還原；附件隨之保存；刪除後 30 天未還原自動清除。**範圍未定**——本文給盤點＋方案＋分期。

## 1 現況盤點（程式實查）

**1.1 量體**：`@router.delete` 60 支；`DELETE FROM` 出現在約 70 處非測試程式；實體刪檔（`os.remove/unlink/rmtree`）業務面約 10 處，其餘為 PDF 暫存／備份輪替／升級。「作廢」類 POST（`void`／`cancel`）13 支，**均為軟刪除**（`voided_at`／status），不在暫存區範圍。

**1.2 關鍵事實（影響設計）**
1. **現行規則是「只有草稿能刪」**：報價單、請款單、憑據、出貨單、完工單、承攬商匯款申請、勞報單（鎖定狀態不可刪）都在端點內擋非草稿；承攬商派發擋審核中／已核准；材料申請擋審核中／已核准／有匯款。使用者要的「已核准單也進暫存區」＝**要放寬刪除條件**，或只是「現有可刪的先進暫存區」。**此為裁示點 D1**（見 §5），本設計兩者皆支援（adapter 的 `can_delete` 與入口分離）。
2. **「採購頁刪採購單」不是 DELETE 端點**：材料申請（採購單）存在報價單 `data_json.materials[]`＋`case_material_approvals` 審核表；刪除發生在報價單**存檔 diff**內（`material_guard.py:326`：被移除的項目連審核單一起 `DELETE`）。同型「隱性刪除」還有階段、進度更新、付款列、設備登載（陣列 diff）。⇒ 暫存區入口不能只掛 DELETE 路由，必須掛在**寫入層函式**。
3. **附件三種存法**：(a) 單據列的 `files_json`／`signed_files_json`／`invoice_files_json`／`issued_files_json` 欄；(b) 獨立附件表（`custom_record_files`、`voucher_attachments`、`dev_logs` files）；(c) `data_json` 內嵌 `files[]`。實體檔在 `UPLOADS_ROOT`（`core/paths.py:60`）。刪檔目前各寫各的：`helpers/uploads.py::delete_document_file／purge_document_files`、`custom_files.py:89`、`quotations.py:3023,5343`、`crm/api.py:1013`、`system.py:827`。**有些刪除根本不刪檔**（報價單 DELETE、勞報單 DELETE 不處理檔案 ⇒ 現況就有孤兒檔）。
4. **備份**：`archive.py::_mirror_uploads` 只增不減地鏡像 `uploads/` 到雲端；DB 本機備份保留 30 天、雲端每日 60 天、每月永久。⇒ 暫存區 DB 資料隨備份走；隔離檔若放 `uploads/` 底下會被鏡像（好處：免另備；代價：30 天後清除不會自雲端鏡像移除）。
5. **既有守門樣板**：`test_write_endpoints_are_audited_2026_09_24.py`（ast 掃路由表，`EXEMPT` 需附原因並被另兩題守）可直接比照。

**1.3 逐模組刪除路徑（實體／子表／附件／狀態限制／誰可呼叫）**

| 模組 | 實體（端點） | 子資料／附件 | 限制 | 呼叫者 | 分類 |
|---|---|---|---|---|---|
| case | 報價單 `DELETE /api/quotations/{no}` | 單內 JSON（stages、updates、materials、付款）；`case_stages/updates/stage_visits` 表；`signed_files_json`；連動通知、IP-13 CRM 連結解除 | 僅草稿＋`require_case` | 案件相關人 | **核心** |
| case | 階段／訪視／更新／留言（`stages/{id}`、`visits`、`updates/{uid}`＋files） | `case_stages`、`case_updates`；留言附件實刪 | 案件鎖定、作者或 admin | admin/作者 | 次要（案件子項） |
| case | 材料申請（採購單）＝存檔 diff 隱性刪除 | `case_material_approvals`、`case_material_payments/lines`、附件 `materials[].files` | 非 in-flight/已核准/有匯款 | admin/PM | **核心** |
| case | `material_approvals DELETE /receive`、`material-payments/{id}/void` | 收貨記錄／匯款（void=軟） | — | 財務/PM | 次要 |
| case | 額外費用 `extra-expenses/{id}`（＋files、change-request） | `case_extra_expenses`；`purge_document_files` 已實刪檔 | 草稿／已駁回 | 申請人/admin | 核心（費用單） |
| case | 完工單 `completion-notes/{no}`（＋signed-files） | `completion_notes` | 僅草稿 | admin | 核心 |
| case | 行動項目 `action-items/{id}` | 單表 | — | 案件相關人 | 次要 |
| arap | 請款單 `payment-requests/{no}` | `payment_requests` | 僅草稿 | admin | **核心** |
| arap | 收款憑據 `invoice-vouchers/{no}`（＋issued-files） | `invoice_vouchers` | 僅草稿 | admin | 核心 |
| payroll | 勞報單 `payslips/{no}`（＋signed-files、dispatch-links） | `payslips`＋`payslip_dispatch_links`（同交易刪） | 僅非鎖定；superadmin | superadmin | **核心** |
| payroll | 獎金群組成員、`bonus_case_award_lines`、`bonus_correction cancel` | 單表 | — | superadmin | 次要 |
| subcontract | 派發 `contractor-dispatches/{id}`（＋files、invoice-files、delete-approve/reject 二段式） | `contractor_dispatches`；`files_json`、`invoice_files_json`；匯款申請（有未作廢者擋） | 非審核中／已核准 | admin | **核心** |
| subcontract | 匯款申請 `contractor-vouchers/{no}`（＋void=軟） | `contractor_payment_vouchers` | 僅草稿 | admin | 核心 |
| subcontract | 承攬商主檔 `vendor-contractors/{id}`、派發↔勞報連結 | 主檔／連結 | — | admin | 主檔 |
| supply | 出貨單 `shipping-notes/{no}`（＋signed-files） | `shipping_notes`；庫存序號連動 | 僅草稿 | admin | 核心 |
| supply | 庫存品、供應商 | `stock_items`、`suppliers` | — | admin | 主檔 |
| accounting | 傳票附件、`void`(軟)、`voucher_lines` 重寫、註解、類別對映 | `voucher_lines` 先刪後寫（編輯＝刪） | 不可實刪傳票（只 void） | 會計 | 傳票不刪；其餘次要 |
| crm | 開發紀錄 dev-logs（＋files，實刪檔）；開發案件刪除走 request/approve 二段式 | `dev_logs` | 二段式 | 業務/admin | 次要 |
| lodging | 住宿紀錄 | `lodging_searches/items` | — | 使用者 | 次要 |
| netplan | 網路規劃 | `network_plans` | 每案可見性 | 作者 | 次要 |
| tender_radar | 關注／標案命中／抓取紀錄 | 3 表 | — | 使用者 | 次要（可重抓） |
| daily_tasks | 每日任務 | 單表 | — | 使用者 | 次要 |
| routers | 客戶、零件、使用者、部門／處、角色、自訂模組／記錄／檔案、工作日誌（＋照片）、品牌圖、模組版本、webauthn | 客戶/零件/使用者為主檔；自訂記錄＋`custom_record_files` | 使用者：不可刪超管 | admin/superadmin | 主檔／設定 |
| 排程／維護（**非使用者刪除**） | session/rate-limit/稽核留存（`audit_log_keep_days`=5 年）/備份輪替/通知清理/geocode 快取 | — | — | 系統 | **排除**（不進暫存區） |

**核心業務單據（建議第 1 期）**：報價單、材料申請（採購單）、額外費用單、完工單、請款單、收款憑據、勞報單、承攬商派發、承攬商匯款申請、出貨單。**第 2 期**：案件子項、主檔（客戶／供應商／承攬商／零件）、獎金、開發案件。**不納入**：快取／session／記錄類、軟刪（void）、設定類（個別評估）。

## 2 設計

**2.1 資料表（核心層，非模組私有）**：`recycle_bin(id, entity_type, entity_id, entity_label, parent_type, parent_id, deleted_by, deleted_at, purge_after, reason, snapshot_json, files_manifest_json, bytes, restore_status[in_bin|restored|purged|restore_failed], restored_by/at, schema_ver)`。索引 `(restore_status, purge_after)`、`(entity_type, entity_id)`。`snapshot_json`＝該列整列＋子列（`{table:[rows]}`）＋關聯補充（通知不存，連結存 id）。`files_manifest_json`＝`[{orig_path, bin_path, sha256, size}]`。

**2.2 隔離目錄**：`uploads/_recycle/<bin_id>/<原相對路徑>`；刪除＝**搬移**（`os.replace`，同磁碟原子），不複製；交易順序＝先寫 bin 列（含 manifest，狀態 `moving`）→搬檔→提交業務刪除→bin 列轉 `in_bin`；任一步失敗回搬並回滾。`_recycle` 排除於一般檔案讀取路由（`upload_readable` 拒絕）。

**2.3 Adapter 介面（L1）**：模組以 `provide("recyclebin.adapter", entity_type, adapter)` 登記（IP registry 新增 IP；對方不在＝該實體走舊的硬刪並在稽核註明，**不得靜默**）。`Adapter{ entity_type; snapshot(conn, id)->Snap; delete_in_tx(conn, id); restore_in_tx(conn, snap, ctx)->RestoreResult; purge_files(manifest); label(snap); can_delete(user,row)->(ok,why); mask(snap)->snap_view }`。核心 `recyclebin.delete(conn, entity_type, id, user)` 統一做：snapshot→移檔→`delete_in_tx`→寫 bin→稽核→通知，**同一交易**；各模組端點只改成呼叫它（加性：新模組不用改核心）。

**2.4 還原衝突規則**：(a) 主鍵／單號仍空⇒原值還原；已被占用（編號回收）⇒**不還原**，列「衝突：單號已存在」，superadmin 可選「以新單號還原」（adapter 重新取號，附註原號）；(b) 父層不存在（報價單已刪）⇒拒絕並提示先還原父層（`parent_*` 欄＋依序還原）；(c) 狀態／簽核：還原後**一律回「草稿」或原狀態的安全版**——已核准單還原時保留 approval 歷程但狀態由 adapter 決定（預設保留原狀態；若牽動庫存／付款／獎金基數則改草稿並標「還原待確認」）；(d) 外部連動（IP-13 CRM 連結、庫存序號、匯款申請）不自動重連，只在還原報告列出；(e) 還原用同一交易＋檔案搬回，失敗整體回滾，狀態 `restore_failed` 留原因。

**2.5 敏感欄位**：snapshot 為完整原始資料（勞報單身分證／銀行帳號等）以利還原，**存 DB 但不外洩**：列表／詳情 API 只回 `mask(snap)`（沿用既有遮罩函式），原文僅還原時用；僅 superadmin；`snapshot_json` 不進一般匯出／稽核明細／通知；備份層級與 DB 同。

**2.6 稽核與通知**：`recyclebin.delete/restore/purge/restore_failed` 全寫 `_audit`（新端點自動被既有稽核守門涵蓋）；刪除時通知 superadmin（彙總、有速率上限，避免大量刪除轟炸）。

**2.7 排程清除**：每日一次，`purge_after<=now AND in_bin` → adapter.purge_files＋`DELETE` bin 列（保留一筆精簡 `purged` 墓碑：type/id/label/deleted_by/purged_at，供稽核）。保護：(a) 單次上限 N 筆／M 秒；(b) 磁碟水位——bin 總量超門檻（預設 5 GB／佔 uploads 20%）告警給 superadmin，**不自動提前清**（避免違反保存承諾）；(c) 備份交互：DB 備份含 bin 列，故「30 天後清除」≠ 備份中也消失（需在 UI／文件講明）；雲端鏡像只增不減，`_recycle` 清除後鏡像殘留 ⇒ 鏡像清理列後續項；(d) 清除前再驗 bin_path 在 `_recycle` 根目錄內（路徑逃逸守門）。

**2.8 API／UI**：`/api/recycle-bin`（GET 列表可依類型／刪除者／期間篩、GET 詳情（遮罩）、POST `/{id}/restore`、POST `/{id}/purge-now` 選配）皆 `require_superadmin`；頁面 `frontend/pages/recycle-bin.html` 放「系統」群組，欄位：類型／單號／刪除者／時間／剩餘天數／檔案數與大小／還原。不給非超管任何入口（一般使用者刪除後只看到「已刪除」）。

## 3 分期與工時（估）

| 期 | 內容 | 工時 |
|---|---|---|
| P0 | 核心：表、`recyclebin.delete/restore/purge`、隔離目錄、API、頁面、排程、稽核、守門測試骨架 | 4–5 天 |
| P1 | 核心單據 10 類 adapter（§1.3 核心列）＋端點改接＋存檔 diff 隱性刪除（材料申請、階段、付款列） | 6–8 天（材料申請 diff 與報價單 JSON 子項最難，約佔一半） |
| P2 | 案件子項、主檔、獎金、開發案件、自訂記錄 | 4–5 天 |
| P3 | 鏡像清理、容量儀表、「以新單號還原」精修 | 2–3 天 |

**遷移**：新表走**核心 schema 版本 +1**（`db.py` 的 `schema_version`，新增 `recycle_bin`）；若先做成模組化則走 `core.migrations`（模組 `recyclebin`，推薦：加性、可獨立販售）——**建議做成模組 `recyclebin`（含自己的 migrations 與 manifest），核心只放 adapter 登記點與 `recyclebin.delete` 呼叫契約**，無需動核心 schema 版本。既有資料不回溯（上線前已刪的不在暫存區）。

**風險**：(1) 級聯：刪除報價單時子項（階段、材料、費用單、承攬商派發、勞報連結）要一併進**同一 bin 群組**或明示拒絕——需 `cascade_children()` 宣告，漏掉＝還原不完整；(2) 外鍵／CHECK／唯一鍵與還原順序（父先子後）；(3) 檔案在共用資料夾／網路磁碟時 `os.replace` 跨磁碟變複製＋刪除，須驗同磁碟並退化為複製→驗 sha→刪原；(4) DB 肥大：整案 snapshot（含 data_json 數百 KB）×30 天，設單筆上限＋總量告警；(5) 放寬「已核准可刪」會破壞現有簽核／獎金／庫存不變式（見 D1）；(6) 存檔 diff 隱性刪除易漏；(7) 隱私：snapshot 含個資，保存期內即為資料外洩面，須確認符合個資保存政策。

**測試**：adapter 契約參數化測試（每類：刪→bin 有列＋檔搬走＋原表無列；還原→逐欄位與檔案雜湊相等；衝突三種；父缺失）；superadmin-only（非超管 403、列表遮罩）；排程（30 天邊界、上限、路徑逃逸）；故障注入（搬檔中途失敗回滾、還原中途失敗）；與備份／`final_verify` 不衝突；前端 e2e（刪除→進暫存區→還原）。

## 4 現有刪除端點的改法與「不漏」保證

**改法**：各端點內 `conn.execute("DELETE FROM …")`＋手工刪檔 ⇒ 改為 `recyclebin.delete(conn, "<type>", id, user)`（核心函式內做 snapshot／移檔／刪列）；`delete_document_file`／`purge_document_files` 不再被業務端點直接呼叫（附件單檔刪除也可選進 bin，P2）；存檔 diff 內的隱性刪除改呼叫同一函式（`material_guard.py:326` 為首例）。

**守門（三道）**：
1. **路由表守門**（比照稽核守門）：ast 掃所有 `@router.delete` 與函式本體含 `DELETE FROM <業務表>` 的處理器，必須呼叫 `recyclebin.delete`，否則須列 `EXEMPT_DELETE`（附原因：session、快取、軟刪、設定…）；清單本身被另兩題守（端點存在、原因非空泛）。
2. **表覆蓋守門**：列出「核心＋次要業務表」清單，掃全 backend 非測試程式的 `DELETE FROM <表>`，不在 `recyclebin.delete` 內部或 EXEMPT 的 ⇒ 紅。補足路由表守門抓不到的 helper／存檔 diff 隱性刪除。
3. **實體刪檔守門**：掃 `os.remove/unlink/rmtree` 於 `UPLOADS_ROOT` 範圍，業務模組直接呼叫（除 `recyclebin` 與白名單 helper）⇒ 紅，避免繞過隔離。
另加 mutation 測試：把某端點改回硬刪，守門必須紅。

## 5 待裁示

- **D1（最重要）**：暫存區是否同時放寬「已核准／已送審單據可刪」？現行規則是保護簽核與付款／獎金鏈；建議**不放寬**，暫存區只接現有可刪者（草稿等）＋ superadmin 專用「刪除已核准」入口（有二次確認與影響清單），不開給一般使用者。
- D2：做成獨立模組 `recyclebin`（建議）或併入核心。
- D3：第 1 期範圍（建議 §1.3 核心 10 類）。
- D4：個資保存期內的遮罩／加密等級；30 天是否可由 superadmin 調整。
