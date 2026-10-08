# 文件清理結果（第 48 班後）— 待主持裁示後才合併

> 分支 `wip/t48-doc-cleanup`（基底 `origin/train/t48-int` e526a2ef7；**未合併、未推到 train／platform**）。依據：`DOC-CLEANUP-INVENTORY-T48.md`（分支 `wip/t48-doc-inventory`）＋1d 抽查（5 筆 DELETE 安全；ARCHIVE 有 export-ignore 陷阱）。

## 數量
| 動作 | 檔數 | 位元組 |
|---|---:|---:|
| 搬到 `docs/platform/archive/<原相對路徑>`（`git mv`，歷史保留） | 45 | 1512005（1.4 MB） |
| 刪除（5 份 `plans/HANDOFF-{D7-20261003-b,HOST,W1,W2,W4}.md`） | 5 | 50,423 |
| 改文字引用 | 12 個檔（含 `.gitattributes`） | — |

清查原列 ARCHIVE 76 筆，**實際搬 45 筆**：另 31 筆（`plans/d12-verify-shots/**`、`plans/form-designer-shots/**` 截圖、`states/repro/*.py`）被**現行文件以相對路徑嵌入／引用**（`D12-VERIFY-GUIDE.md`、`FORM-DESIGNER-PREVIEW-GUIDE.md`、`STATES-PLATFORM.md`），搬走會斷圖／斷路徑，已**留在原處**（建議清查改列 KEEP）。PROTECTED／KEEP 集合未動。

搬入分佈：docs/platform/plans 19, docs/platform/prod-tasks 15, (repo 根目錄) 3, docs/platform 3, docs/ASK-ACCOUNTANT.md 1, docs/PLATFORM-CUSTOMIZATION-INVENTORY.md 1, docs/PLATFORM-FOUNDATION.md 1, docs/UI-BACKLOG.md 1

## 打包（export-ignore）
- `.gitattributes`：新增 `docs/platform/archive/** export-ignore` 與 `docs/platform/archive export-ignore`（與 `docs/windows` 同樣成對）；刪除 8 條已失效的逐檔規則（`/AUTOLOGON-FIX.md`、`/MULTI-BRANCH-AUTO-UPDATE-DESIGN.md`、`/NEXT-SESSION.md`、`docs/ASK-ACCOUNTANT.md`、`docs/UI-BACKLOG.md`、`docs/PLATFORM-FOUNDATION.md`、`docs/PLATFORM-CUSTOMIZATION-INVENTORY.md`、`docs/system-home-mockup.html`）與「內部諮詢草稿」註解，同一個 commit。
- 驗證：`git check-attr export-ignore` 對 archive 底下全部 45 個檔 ＝ `set`（0 個未設）。守門 `test_verify_package_export_ignore_list`、`test_verify_package`、`test_delivery_module`、`test_product_select`、`test_scope_gate`、`test_vendor_paths_are_versioned` 全過。**未實際建包**（48a 套用中、機器忙）；建議合併後下一班建包時由 `verify_package` 自然覆蓋。
- 備註：`docs/platform/**` 其餘文件沒有 export-ignore 規則（本次未改）——代表目前 `docs/platform` 的 KEEP 文件會進客戶包；是否要整個排除請主持另案決定。

## 文字引用修正
`DR-SOP.md`（AUTOLOGON-FIX 連結）、`MOTRIX-ERP-ARCHITECTURE-MAP.md`（3 處）、`docs/UI-REDESIGN-PLAN.md`、`frontend/css/style.css:108`（註解）、`docs/platform/RUN-PLAN.md`（RETROSPECTIVE、NIGHT-20260930-PLAN、train22 步驟檔，只改路徑）、`docs/platform/plans/expense-a2/{plan-expense-a2,proposal-expense-forms}.md`、`docs/quick/{architecture,known-limits}.md`、`docs/windows/STATE.md`（2 行）、`docs/windows/SCOPE.md`（2 行，僅路徑形式的提及）。
**刻意不改**（歷史紀錄／受保護）：各 `CHANGELOG`／`docs/quick/changelog*.md`、`docs/platform/audit/**`、`runplan/RUN-PLAN-ARCHIVE-*`、`docs/windows/{HANDOFF-PENDING,DELIVERY-NOTE}-2026-09-23.md`、STATE／SCOPE 裡只寫檔名的清單列。這些會留下指向舊位置的字樣（內容仍可由 git 歷史或 archive 找回）。另：搬進 archive 的文件內部若有相對連結指向未搬的文件，因目錄深度改變可能失效（歷史文件，不修）。

## 守門（本分支）
通過：`test_cache_index_fresh`、`test_homoglyphs_in_docs`、`test_generated_maps`（除下列一項）、上列打包相關守門——共 216 過、2 skip、1 紅。
紅的 1 項 `test_branch_does_not_touch_generated_files` 為**預期**：本分支基底是 `train/t48-int`（產生檔已重產，與 `origin/platform` 不同）；改以 `origin/platform` 為基底（48a 套用並寫基準後）即消失，與本次改動無關。
