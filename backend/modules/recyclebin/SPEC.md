# M15 刪除暫存區（recyclebin）· 規格條件

> 2026-10-10 建立（第 53 班 P0；設計 `docs/platform/plans/RECYCLE-BIN-DESIGN-T52.md`，進度 `RECYCLE-BIN-P0-STATE-T53.md`）。本模組**不認識任何單據**：單據怎麼快照／刪除／還原由擁有模組的 adapter（L1 契約 `helpers/recycle_bin.py`）決定。
> 格式同 `modules/filehub/SPEC.md`（`backend/tests/test_spec_coverage_2026_09_21.py` 讀各模組的 `SPEC.md`）。

## 用途與 API

- 單據刪除先進暫存區（資料列快照＋附件搬進隔離目錄），只有最高管理者看得到與還原；30 天後自動清除。
- `/api/recycle-bin`：`GET /`（列表）、`GET /status`、`GET /impact`、`GET /{id}`（詳情，快照遮罩）、`POST /{id}/restore`、`DELETE /{id}?confirm=永久刪除`、`POST /delete-approved`、`PUT /settings`。

## 規格條件

- **RBN1.** 所有端點只有最高管理者可用（其他角色 403、未登入 401）；選單入口 `perm: ["superadmin"]`。
- **RBN2.** 進暫存區＝資料列刪除＋附件**搬**進隔離目錄（原路徑不再有檔、隔離區有檔、`recycle_bin` 有一列含完整快照）；`purge_after` ＝ 刪除日 + 30 天（固定，不可設定）。
- **RBN3.** 不放寬任何刪除條件：adapter 的 `can_delete` 不通過 ⇒ 丟 `BinError`、資料與檔案原封不動；『刪除已核可』只有最高管理者、且 adapter 的 `can_delete_approved` 通過、並需要二次確認。
- **RBN4.** 缺席要明說：本模組不在 ⇒ `helpers.recycle_bin.delete()` 回 None（擁有模組照舊硬刪並明說）；沒有該類型的 adapter ⇒ `BinError`，不刪任何東西。
- **RBN5.** 還原把資料列與附件放回；任何失敗（衝突、父層不在、adapter 例外、附件搬不回）⇒ 資料列留在暫存區、附件回到隔離區、狀態 `restore_failed` 並記原因；不覆蓋既有資料。
- **RBN6.** 每日工作清除 `purge_after` 已到的項目（隔離檔刪除、快照清空、留墓碑），逐筆稽核 `recyclebin.purge_auto`；未到期的與已還原的不碰；有清除或磁碟水位超標 ⇒ 通知所有最高管理者。
- **RBN7.** 列表與詳情的快照欄位遮罩敏感值（帳號、身分證、電話、信箱、地址、影像、簽名…）；還原用的原文不受影響。
- **RBN8.** 呼叫端的交易回滾（隔離區有檔、資料庫沒有列）⇒ 每日工作 `reconcile` 把檔案搬回原路徑，不遺失、不覆蓋既有檔。
- **RBN9.** 快照超過上限（5 MB）⇒ 拒絕進暫存區（`too_large`），單據與附件原封不動，不悄悄硬刪。
- **RBN10.** 永久刪除需要二次確認（`confirm=永久刪除`）；寫稽核 `recyclebin.purge_manual` 並通知其他最高管理者；隔離檔與快照一併刪除，只留墓碑。
- **RBN11.** 隔離目錄只能被本模組的 `quarantine.py` 動檔案；目錄設定在暫存區有項目時不准改，且不可設在 uploads／backend／frontend 底下。

- **RBN12.** 遮罩涵蓋『JSON 字串欄位』（`data_json`／`snapshot_json` 這類整份存成字串的欄位會被解開再遮罩，巢狀的 JSON 字串也是）、敏感鍵底下的整個值（含 dict／list）、與較寬的鍵名（account_no／acct_no／id_no／national_id／birthday／payee_account／credit_card／tel…）；`data:` 內嵌影像一律遮罩；壞掉的 adapter 工廠要留 log，不得靜默。
- **RBN13.** 隔離目錄設定只收本機絕對路徑：拒絕網路路徑（UNC）、磁碟機根目錄、系統目錄（Windows／Program Files／ProgramData…）、以及等於／在／包含安裝目錄與 uploads 的位置；留空＝預設位置。
- **RBN14.** 還原與清除先拿寫鎖、鎖內重讀狀態，且狀態更新用條件式 UPDATE 並檢查影響列數：連點兩次還原時第二次被擋下、不會把已還原的列翻成 `restore_failed`；已還原的不能永久刪除。
- **RBN15.** 進暫存區失敗（資料列刪除或寫列失敗）而附件又搬不回原路徑時，隔離資料夾與檔案原封不動保留（不 rmtree），單據視為未刪除並回報；每日工作 reconcile 之後會再搬回。
- **RBN16.** 永久清除要驗證隔離資料夾真的刪乾淨：刪不掉（檔案被占用）⇒ 這一筆維持在暫存區（快照與清單不清）、回 409、稽核 `recyclebin.purge_failed`；每日工作同樣不可把刪不掉的標成已清除。
- **RBN18.** 『刪除已核可』入口（`POST /api/recycle-bin/delete-approved`）直接呼叫通用 `service.delete`，**不會執行擁有模組刪除端點裡的領域後續動作**（例如清除該單據的站內通知、領域稽核動作名稱）；這些由 adapter 的 `delete_in_tx` 負責（P1 各 adapter 要把原端點的後續清理搬進去，或在 adapter 的 `after_delete` 擴充點補）。通用稽核 `recyclebin.delete_approved` 與通知其他最高管理者一定會做。
- **RBN19.** Adapter 可實作 `after_commit(event, entity_id, snap, result)`（`delete`｜`restore`）：還原與『刪除已核可』由暫存區模組在**commit 之後**自動呼叫；一般刪除由擁有模組的端點在自己 commit 之後呼叫 `delete()` 回傳的 `result["after_commit"]()`。錯誤只記 log、不往外丟（資料已 commit）；回傳給前端的結果不含 hook。
- **RBN17.** 隔離資料夾 `資源回收筒/` 在 `.gitignore` 內（隔離檔含個資，`git add -A` 不可帶走）；『刪除已核可』也通知其他最高管理者。

## 非目標

- P0 不含任何單據 adapter、不改任何既有刪除端點（P1 由各擁有模組接入）；不做單據的『批次還原』；不做保存期設定。

## 測試

`backend/modules/recyclebin/tests/test_recyclebin_p0_t53.py`（以合成 adapter 驗 RBN2～RBN11）、`test_recyclebin_hardening_t53.py`（RBN12～RBN19，稽核回歸題）、`backend/tests/platform/test_recyclebin_guards_t53.py`（三道守門）。
