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

> 🔴 **db schema 版本變動的班次（例：第 46 班基準 116→118）**：`delivery.py` 的 `installed_db_version()` 取的是**正式機已安裝**的 `db.py`
> `CURRENT_VERSION`（獨立訊號）。本班包的 `CURRENT_VERSION` 比已安裝的大時，用預設期望值驗包會得到
> `db 版本 == 期望值：包內是 N，而期望是 M` 而失敗。**步驟檔必須明寫** `verify_package.py <包> --expect-db-version <包內的 N>`
> （N 取自本班的 `backend/db.py`，由主持在發布前核對，不取自包）。不要為了通過而改 `delivery.py` 或略過這項檢查。
> 同班的**回滾段必須寫「還原套用前的資料庫備份」**：庫被升到 N 之後，只回退程式碼會被舊版 `init_db` 以 `SchemaNewerThanBaseline` 拒絕啟動。

## 步驟 2：套用

- log 檔名一律帶時間戳：`Tee-Object <staging>\apply_trainNN_$(Get-Date -Format yyyyMMdd_HHmmss).log`。第二十五班使用者重跑一次（`duplicate_version` 正常拒絕）把成功那次的 log 覆蓋掉，步驟 3 #3／#5 因此只能部分驗證（2026-09-30）。步驟 3 引用 log 時寫「時間戳最大且 `::RESULT::` 為 success 的那份」。

## 步驟 3：套用後檢查（逐項、可機械判定）

## 步驟 4：只回程式的回滾（僅在「apply 顯示 success 但步驟 3 不過」時）

> 🔴 若本班 `CURRENT_VERSION` 變大（見步驟 1 的說明）：**只回程式不夠**——庫已被升版，舊程式會拒絕啟動。此時回滾＝還原套用前的 `motrix_erp.db` 備份＋回程式。

## 步驟 5：回報

- 步驟 0 第 2 項：`verification.mode`、`verification.scoped.base` 與 `.deployed_commit.json` 的 `commit`（兩個值都寫出來）。
