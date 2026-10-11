# 系統中心（System Hub）狀態與 M2 清單（第 54 班；給交接用）

分支：設計 `wip/t54-b5-system-hub`；實作 `wip/t54-b5-system-hub-p1`（舊，已被取代）→ **`wip/t54-b5-system-hub-p1-r2`**（疊在設定中心 Train A r2 之上）。稽核：node-39 靜態稽核 8b267cb41 = NOT PASS → r2 已逐項處理（見下）。

## r2 已處理（node-39 稽核）
- MUST：『沒有權限的項目要不要列出』改為設定登錄表的設定（`system_hub.show_denied`，放寬 up、風險 security、預設隱藏、白話影響與風險說明；放寬走確認期間＋第二人核准、稽核同交易）；移除自建的 PUT 端點與 UI 開關，頁面只留『到設定中心調整』連結；凍結基準 `settings_deploy_baseline.json` 已加此群組。
- SHOULD：卡片名稱『資源回收筒』→『刪除暫存區』、『Schema 狀態』→『資料庫結構』；白話檢查擴充英文術語（schema／token／SMTP／SQL…）；徽章改每個提供者一條 daemon 執行緒＋『上一次還沒結束就跳過』（四個卡住不影響其他，附測試）；設定中心卡片不再是 planned（頁面隨 Train A 同班）。

## M2（權限矩陣 perm.can 接上之前必須完成）
1. **快取失效**：整頁回應快取現為『依使用者＋角色＋模組＋show_denied、15 秒』。接上 perm.can 之前必須加 `config_epoch`（`config_changes`／`config_change_events` 最大 id）比對與 `next_change_at` 到期失效（設計稿 §3.1）；`perm.changed` 只清本行程。
2. 卡片 `cap` 由 1d 的 `capabilities.menu_cap_key(unit, href)` 衍生（種子卡片目前不寫 cap）。
3. 非作者的 `train_preflight --full-lint` 與完整 tests/platform 在新基準上的結果（舊基準上的部分結果：41% 時 2 題失敗，未辨識）。
4. 備註：導覽列麵包屑對沒有 `<main>` 的頁面用退路容器；`module-versions.html` 結構特殊，版面位置待目測確認。
