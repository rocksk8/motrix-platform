# 權限矩陣 更新紀錄

## (next) — 2026-10-11（wip/t54-1d-permmatrix-p0-r10；05 稽核 A／B／C 修正＋perm.changed 通知）
- r10（05 稽核 B）：放寬一律不立即——勾回「種子本來就有、後來被取消」的高風險格子、取消高風險能力的個人禁止，都改走 24 小時待生效（需原因）；到期套用回種子預設時刪覆寫列。新增守門 `test_permmatrix_writes_unwired.py`：帳本接上前不得有端點／頁面／其他程式呼叫 P0 寫入函式（SPEC PMX14）。
- r7：`perm.invalidate()` 會通知所有 `perm.changed` 提供者（系統中心登記，整合點見其 IP-HUB1；只涵蓋本程序，跨程序靠 P1 `config_epoch`）。系統中心直接呼叫 `helpers.perm.can`，不需 `perm.can` 提供者。
- `load_matrix` 改為純讀取（不再呼叫 `activate_due`）；到期待生效由 `kick_activation()` 背景轉態（單一飛行、不阻塞權限檢查）。
- `activate_due`：套用前確認申請人仍是在職最高管理者，否則標 `superseded` 並稽核（不以已降級／停用帳號的名義套用）。
- `kick_activation`：執行緒起不來時放掉鎖並回 None（05 複驗備註；有測試）。
- `perm_pending`／24 小時仍是過渡實作，M1 不接端點或畫面（見 SPEC PMX13）。

## 1.0.0 — 2026-10-10（wip/t54-1d-permmatrix-p0）：里程碑 2——矩陣資料表、提供者、服務層（覆寫／代理／24 小時待生效／版本回溯）
- 新模組 `permmatrix`（M16）。表 `perm_role_caps`／`perm_user_overrides`／`perm_versions`／`perm_pending`／`perm_delegations`（皆 T1；沒有 core schema 版本升級）。
- 提供者 `perm.matrix_source`（IP-PM1）：L1 `helpers/perm.py` 取「種子 ⊕ 覆寫」＋有效代理；模組不在或讀取失敗 ⇒ L1 用種子（＝今天的行為）。
- 白話預覽（影響面板：摘要、影響、人數、適用範圍、可否復原、何時生效、風險提示）與一鍵復原；文字由 L1 `helpers/perm_text.py` 產生（畫面無代碼、無代名詞）。
- 服務層：角色格／個人覆寫／代理的寫入、高風險授予 24 小時待生效（讀取時判斷、可撤銷）、版本與回溯、稽核同交易、通知 commit 後。尚無端點與頁面。
