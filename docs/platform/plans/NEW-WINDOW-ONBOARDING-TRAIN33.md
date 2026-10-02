# 新視窗接手指引（第 33 班；主持 bin-1c）

> 新視窗啟動後先讀本檔，再讀 `docs/platform/plans/TRAIN31-BACKLOG.md`（最底下是最新裁示）與 `docs/platform/plans/USER-DECISIONS-TRAIN33.md`（待使用者裁示題，已裁示者有標）。
> 全部在 `origin/host/quick-memory-pointer` 分支的 docs 下；用自己的 git worktree（`D:\開發測試檔\wt-<名字>`），**不要動共用樹 `D:\MOTRIX-PLATFORM`**。

## 共同規則（務必遵守）
1. **回報一律用 SendMessage 給 `bin-1c`**（主持）；回報要有分支名與 `git ls-remote` 可驗證的 sha，不只口頭。
2. **測試**：單檔、單程序、不用 `-n`；用自己的 `--basetemp` 放 `%TEMP%\motrix-pytest-<名字>-adhoc`，**不要放 repo 內**；用完刪。Python 一律用 `D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe`（你的 shell 的 python 可能是別人的 venv）。全機同時最多 2 組測試。
3. **作者端守門**：推「最終 sha」前，必須跑完整 `backend/tests/platform` 加所有 *approval*／*queue*／*pii*／*privacy*／*migration*／*spec_coverage*／*font_zoom*／*money_round*／*wording*／*changelog* 檔，以及你改動模組的所有 e2e；不要只跑自己新寫的測試（第 31、32 班因此在整合時連紅 5 輪）。
4. **權限／金額可見度／口徑變更**不自行決定，回報給主持（用選單問使用者）。
5. **你是作者就不能當稽核**；稽核由別的視窗做。
6. **上下文太長時**：先把進度、決策、分支 sha、待辦寫進 `docs/platform/plans/` 下你自己的交接檔並 push，再自行 `/compact`（或使用者替你 `/clear`）；恢復時讀交接檔，不靠記憶。
7. 時間戳用系統時間（`date`），不手寫。

## 建議新增兩個視窗與負責範圍（互不重疊）
- **視窗 E（匯款款別 31-B）**：模組 `subcontract`／`arap`。輸入：`REMIT-KINDS-31B-DESIGN.md`（a3 已寫，含正式機資料事實 §0 與 Q1–Q8）、`USER-DECISIONS-TRAIN33.md`。步驟：等使用者裁示 → S1（遷移，重建表以移除 `dispatch_id UNIQUE`，用合成資料演練）→ S2–S5。**不要碰 `case-management.html`**。
- **視窗 F（出貨單連動材料申請）**：模組 `supply`（`shipping_note`）。輸入：2e 的 `MATERIAL-FORCE-PO-AND-SHIPPING-SPEC.md`（出貨單與材料申請資料模型、數量對照）。與 2e 對介面（材料申請提供者），**不要改材料申請本身的檔**。

## 既有視窗範圍（避免撞檔）
- 2e：案件模組「材料申請／強制採購單／精算頁重做」（`case-management*.html/js`、`purchase_items`、`recognition`、`settlement`）。
- d7：建包優化（`tools/platform`、`build_deploy_package.ps1`）、31-C 守門檔（`material_guard`）與其修正項。
- c7：表單設計器（`form-designer*`、`module-builder-*`）、K-2 並行戳、已發布請款類型範本重發、版本差異。
- a3：請款類型頁、作者端守門集（`author_gate.py`）、各包演練（`drill_train*.py`）。
