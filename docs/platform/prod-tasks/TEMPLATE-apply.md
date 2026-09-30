# 給正式機 Claude：第 N 班更新步驟（<舊 commit> → <新 commit>）——範本

> 範本（2026-09-30，稽核 W4 M4）：每一份 `YYYYMMDD-trainNN-apply.md` 從這裡複製。步驟 0 的第 1、2 項是**必備**，不可以刪。

## 這一班有什麼

- （條列；使用者看得懂的話）

## 步驟 0：前置（全部成立才往下；任一不成立 ⇒ 停下回報，不動任何東西）

1. 目前版本：`<ROOT>\backend\.deployed_commit.json` 的 `commit` 以 `<舊 commit 前 8 碼>` 開頭；已是 `<新 commit>` ⇒ 回報「已是這一版」結束。
2. **驗證基準（PLAYBOOK §D-1a）**：讀部署包 `deploy_manifest.json` 的 `verification`：
   - `mode` 是 `scoped` ⇒ `verification.scoped.base`（40 碼完整 SHA）必須等於 `.deployed_commit.json` 的 `commit` 的開頭（`commit` 是完整 SHA 時兩者完全相等）。**不相等 ⇒ 停下回報兩個值**：這一包的範圍驗證是對著另一個基準算的，沒驗到正式機實際的改動範圍。
   - `mode` 是 `full` ⇒ 記下即可（全量不依基準）。
   - 沒有 `verification` 欄位 ⇒ 停下回報（建包工具版本不對）。
3. 服務健康：`http://127.0.0.1:666/api/ping` 回 200。
4. 磁碟可用空間（系統碟）≥ 5 GB。
5. 記下套用前的 `<ROOT>\backend\logs\module_states.json`（模組總數與每個模組的 `key`／`version`／`state`）。

## 步驟 1：取包並驗證（不套用）

## 步驟 2：套用

## 步驟 3：套用後檢查（逐項、可機械判定）

## 步驟 4：只回程式的回滾（僅在「apply 顯示 success 但步驟 3 不過」時）

## 步驟 5：回報

- 步驟 0 第 2 項：`verification.mode`、`verification.scoped.base` 與 `.deployed_commit.json` 的 `commit`（兩個值都寫出來）。
