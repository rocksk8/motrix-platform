# BP-3 交接（合併者必讀；t61，wip/t61-bp3-templates-r1）

## 合併順序與疊法
1. `wip/t61-xl-safe-r1`（公式注入中和＋守門）先合——BP-3 分支疊在它上面，**兩個一起合併**。
2. 再合 `wip/t61-bp3-templates-r1`。
3. 預覽閘門：BP-3 的 `export_template` 加入了 `routers/definitions._PREVIEW_ENFORCED_KINDS`，但這個分支的 `_governance_enabled` 仍是舊版（讀不到設定時回 False＝閘門放行）。**合併時請採用 `wip/t62-preview-gate-r1` 83252867 的嚴格版本**（讀設定不 fail-open、發布一律綁定看過的雜湊、還原也有閘門）；兩邊都改 `routers/definitions.py` 與 `routers/def_governance.py`，預期有小衝突——衝突時以 t62 為準，保留 BP-3 的 `_lazy_kinds()` 呼叫（`_group_gate`／`_managed_guard`／`list_definition_kinds`）與 `_SCOPE_TEXT` 的 `export_template` 項。

## 生效條件（04 審核後）
- `builder_exports.enabled` **必須同時** `builder_governance.enabled`=1 才生效（`helpers/export_templates.enabled`）；讀不到任一個設定 ⇒ 關。
- kind `export_template` 惰性登記：旗標關時 `/api/definition-kinds` 沒有它；旗標開後，第一次碰到定義介面時登記（`ensure_kind`）。重新關旗標不會在同一個行程內把 kind 移除（重啟後恢復），驗證器會回「尚未開放」。
- 頁首／頁尾／浮水印文字：只能從白名單挑；Cc/Cf/Zl/Zp/Co/Cs 與填充字元一律拒絕；官方狀態字樣在『只留字母與數字的骨架』上比對（中文、英文、簡體）；任何文字的新增或更換都算放寬（需第二位最高管理者核准）。
- `POST /api/exports/client-log`：旗標開時才記錄；需要該頁清單的模組權限（與清單 API 同一組）；同一位使用者同一個名稱 5 秒內只記一筆，過快靜默丟掉（`logged:false`）；永不回 429。

## 需要列車重產的生成物
L1 介面快照（新名稱：`xl_safe_xlsx`、`csv_safe`、`render_rows`、`apply_pdf_text`、`decorate_pdf`、`ensure_kind`、`PRESET_TEXTS`…）、`route_inventory`／`route_table_golden`（+2 POST、+1 GET）、設定部署基準（+`builder_exports`）、`response_keys` 基準、`test_map`／`dep_graph`／`UNIT-INDEX`。`unscoped_reads_baseline.json` 已手動改名兩筆（`export_task_history`→`_history_load`、`export_contractors`→`_roster_rows`），總數不變（838）。

## 首次真瀏覽器驗證
`BP3-FIRST-BROWSER-PASS-T61.md`。
