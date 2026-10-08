# 文件清查（第 48 班後清理用）— 唯讀盤點，尚未刪除任何檔

> 產生：b7（2026-10-09）；基底 `origin/train/t48-int` e526a2ef7。範圍：`docs/platform/**`、`docs/*.md|html`（docs 根）、repo 根目錄的 `*.md|txt|html`；`docs/windows/**`、`docs/quick/**`、`docs/reference/**` 不在本次範圍（STATE／SCOPE 等受保護）。**本檔只提供證據與建議，不執行任何刪除／搬移；實際動作由主持裁示後另開分支。**

## 一、結論（數量）

| 類別 | 檔數 | 容量 | 意義 |
|---|---:|---:|---|
| PROTECTED | 125 | 2882 KB | 規定保留（CHANGELOG／SPEC／RUN-PLAN／稽核紀錄／產生檔） |
| KEEP | 94 | 2200 KB | 有程式／測試／工具引用、最近 3 天仍有異動或被多份現行文件引用 |
| ARCHIVE | 76 | 5290 KB | 搬到 `docs/platform/archive/`（或封存冊）；保留歷史、移出日常視野 |
| DELETE | 5 | 49 KB | 可刪（git 歷史仍可找回）；僅限無引用的交接／草稿類 |
| 合計 | 300 | 10421 KB | |

### 各資料夾分佈

| 資料夾 | PROTECTED | KEEP | ARCHIVE | DELETE | 合計 |
|---|---:|---:|---:|---:|---:|
| `docs/platform/audit` | 113 | 0 | 0 | 0 | 113 |
| `docs/platform/plans` | 2 | 32 | 48 | 5 | 87 |
| `docs/platform` | 7 | 37 | 3 | 0 | 47 |
| `docs/platform/prod-tasks` | 0 | 7 | 15 | 0 | 22 |
| `(repo 根目錄)` | 2 | 13 | 3 | 0 | 18 |
| `docs（根目錄）` | 0 | 3 | 5 | 0 | 8 |
| `docs/platform/states` | 0 | 2 | 2 | 0 | 4 |
| `docs/platform/runplan` | 1 | 0 | 0 | 0 | 1 |

## 二、判定規則（可重現；腳本見提交說明）

1. **PROTECTED**：任何 `CHANGELOG.md`／`changelog*`、檔名含 `SPEC` 者（模組與核心規格）、`RUN-PLAN.md`＋`runplan/`、`docs/platform/audit/**`（整個資料夾）、產生檔（`test_map.json`、`dep_graph.json`、`UNIT-INDEX.md`、`CACHE-INDEX*`）。
2. **KEEP（硬引用）**：全部 tracked 的程式／測試／工具／設定／腳本文字檔（`.py .json .ps1 .sh .js .html…`，不含文件）裡出現該檔的**完整相對路徑、檔名（≥6 字）或主檔名（≥8 字，例如測試只寫「CUSTOMIZATION-SPEC §8.3」）**——代表有東西會讀它或登記它。
3. **KEEP（近期／現行）**：最後一次 commit ≥ 2026-10-06（最近 3 天），或被 ≥3 份文件引用且其中含 `docs/platform` 根的現行入口文件（非交接、非計畫、非稽核）；僅被少數文件引用但最近才動（≥ 2026-10-04）者暫留。
4. **DELETE**：無硬引用、無任何文件引用、最後異動 ≤ 2026-10-03（6 天以上）、檔名屬 HANDOFF／NEXT-SESS／SESSION-END／DRAFT 類（一次性交接，內容已被後續交接或實作取代）。
5. **ARCHIVE**：其餘（無硬引用、非近期、非多方引用）——規劃稿、報告、設計稿、已出貨班次的步驟檔；工作已出貨但留作歷史。
6. **限制（請主持知悉）**：①引用以**字串比對**判定，文字內改寫過檔名者可能漏判（偏向保守＝多數落在 ARCHIVE 而非 DELETE）；②「工作已出貨」只用日期與引用推定，**未逐檔核對對應分支是否已併入**——DELETE／ARCHIVE 都需主持或原作者抽查；③`.md` 內以相對連結 `[..](x.md)` 引用者會被視為文件引用（soft），不是硬引用。

## 三、逐檔清單

### DELETE（5）

| 檔案 | KB | 最後異動 | 硬/文件引用 | 證據 |
|---|---:|---|---:|---|
| `docs/platform/plans/HANDOFF-D7-20261003-b.md` | 5.6 | 2026-10-03 | 0/0 | 交接／草稿類、無任何引用、2026-10-03 後沒動；內容已被後續交接或實作取代（需人工抽查） |
| `docs/platform/plans/HANDOFF-HOST-20261001.md` | 5.6 | 2026-10-01 | 0/0 | 交接／草稿類、無任何引用、2026-10-01 後沒動；內容已被後續交接或實作取代（需人工抽查） |
| `docs/platform/plans/HANDOFF-W1-20261001.md` | 11.9 | 2026-10-01 | 0/0 | 交接／草稿類、無任何引用、2026-10-01 後沒動；內容已被後續交接或實作取代（需人工抽查） |
| `docs/platform/plans/HANDOFF-W2-20261001.md` | 10.8 | 2026-10-01 | 0/0 | 交接／草稿類、無任何引用、2026-10-01 後沒動；內容已被後續交接或實作取代（需人工抽查） |
| `docs/platform/plans/HANDOFF-W4-20261001.md` | 15.3 | 2026-10-01 | 0/0 | 交接／草稿類、無任何引用、2026-10-01 後沒動；內容已被後續交接或實作取代（需人工抽查） |

### ARCHIVE（76）

| 檔案 | KB | 最後異動 | 硬/文件引用 | 證據 |
|---|---:|---|---:|---|
| `AUTOLOGON-FIX.md` | 2.6 | 2026-08-01 | 0/1 | 僅被 1 份文件引用（例：DR-SOP.md）；最後 2026-08-01；非即時入口 |
| `MULTI-BRANCH-AUTO-UPDATE-DESIGN.md` | 11.4 | 2026-09-01 | 0/3 | 僅被 3 份文件引用（例：MOTRIX-ERP-ARCHITECTURE-MAP.md）；最後 2026-09-01；非即時入口 |
| `NEXT-SESSION.md` | 7.8 | 2026-09-12 | 0/1 | 交接類，仍被 1 份文件引用（例：docs/windows/HANDOFF-PENDING-2026-09-23.md）；最後 2026-09-12 |
| `docs/ASK-ACCOUNTANT.md` | 4.8 | 2026-09-23 | 0/3 | 僅被 3 份文件引用（例：docs/windows/DELIVERY-NOTE-2026-09-23.md）；最後 2026-09-23；非即時入口 |
| `docs/PLATFORM-CUSTOMIZATION-INVENTORY.md` | 9.3 | 2026-09-23 | 0/1 | 僅被 1 份文件引用（例：docs/PLATFORM-FOUNDATION.md）；最後 2026-09-23；非即時入口 |
| `docs/PLATFORM-FOUNDATION.md` | 55.4 | 2026-09-24 | 0/1 | 僅被 1 份文件引用（例：docs/windows/HANDOFF-PENDING-2026-09-23.md）；最後 2026-09-24；非即時入口 |
| `docs/UI-BACKLOG.md` | 9.7 | 2026-09-14 | 0/3 | 僅被 3 份文件引用（例：docs/quick/changelog.md）；最後 2026-09-14；非即時入口 |
| `docs/platform/MODULE-UPDATE-DRILL-20260928.md` | 5.5 | 2026-09-29 | 0/1 | 僅被 1 份文件引用（例：docs/platform/audit/AUDIT-D-B55-module-delivery.md）；最後 2026-09-29；非即時入口 |
| `docs/platform/PROD-UPGRADE-RESULT-20260927.md` | 3.3 | 2026-09-27 | 0/1 | 僅被 1 份文件引用（例：docs/platform/runplan/RUN-PLAN-ARCHIVE-2026-09-26_2026-09-27.md）；最後 2026-09-27；非即時入口 |
| `docs/platform/RETROSPECTIVE.md` | 22.8 | 2026-09-27 | 0/1 | 僅被 1 份文件引用（例：docs/platform/RUN-PLAN.md）；最後 2026-09-27；非即時入口 |
| `docs/platform/plans/AUTHOR-GATE-USAGE.md` | 4.7 | 2026-10-03 | 0/0 | 無任何引用；最後 2026-10-03；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/BUILD-WINDOW-POPUP-AUDIT.md` | 2.0 | 2026-10-02 | 0/0 | 無任何引用；最後 2026-10-02；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/M05-PLAN.md` | 7.7 | 2026-09-26 | 0/0 | 無任何引用；最後 2026-09-26；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/MATERIAL-PAID-LEGACY-PRICE-CHANGE.md` | 4.0 | 2026-10-02 | 0/0 | 無任何引用；最後 2026-10-02；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/NIGHT-20260930-PLAN.md` | 19.4 | 2026-09-30 | 0/2 | 僅被 2 份文件引用（例：docs/platform/RUN-PLAN.md）；最後 2026-09-30；非即時入口 |
| `docs/platform/plans/PN-M1-PLAN.md` | 4.2 | 2026-09-26 | 0/0 | 無任何引用；最後 2026-09-26；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/PROBES-PLAN.md` | 4.9 | 2026-09-26 | 0/0 | 無任何引用；最後 2026-09-26；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/SETTLEMENT-ACTUALS-PROBE.sql` | 1.2 | 2026-10-02 | 0/1 | 僅被 1 份文件引用（例：backend/modules/case/CHANGELOG.md）；最後 2026-10-02；非即時入口 |
| `docs/platform/plans/d12-verify-shots/01-builder-designer-default.png` | 148.8 | 2026-10-03 | 0/1 | 僅被 1 份文件引用（例：docs/platform/plans/D12-VERIFY-GUIDE.md）；最後 2026-10-03；非即時入口 |
| `docs/platform/plans/d12-verify-shots/02-builder-dragging.png` | 149.3 | 2026-10-03 | 0/1 | 僅被 1 份文件引用（例：docs/platform/plans/D12-VERIFY-GUIDE.md）；最後 2026-10-03；非即時入口 |
| `docs/platform/plans/d12-verify-shots/03-expense-types-designer-default.png` | 138.0 | 2026-10-03 | 0/1 | 僅被 1 份文件引用（例：docs/platform/plans/D12-VERIFY-GUIDE.md）；最後 2026-10-03；非即時入口 |
| `docs/platform/plans/d12-verify-shots/preview-after-fix.png` | 240.4 | 2026-10-03 | 0/0 | 無任何引用；最後 2026-10-03；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/d12-verify-shots/widths/et-1366.png` | 126.1 | 2026-10-03 | 0/0 | 無任何引用；最後 2026-10-03；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/d12-verify-shots/widths/et-2000.png` | 155.6 | 2026-10-03 | 0/0 | 無任何引用；最後 2026-10-03；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/d12-verify-shots/widths/et-2560.png` | 182.4 | 2026-10-03 | 0/0 | 無任何引用；最後 2026-10-03；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/d12-verify-shots/widths/et-400.png` | 59.9 | 2026-10-03 | 0/0 | 無任何引用；最後 2026-10-03；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/d12-verify-shots/widths/mb-1366.png` | 135.4 | 2026-10-03 | 0/0 | 無任何引用；最後 2026-10-03；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/d12-verify-shots/widths/mb-2000.png` | 154.4 | 2026-10-03 | 0/0 | 無任何引用；最後 2026-10-03；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/d12-verify-shots/widths/mb-400.png` | 77.6 | 2026-10-03 | 0/0 | 無任何引用；最後 2026-10-03；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/expense-a2/ledger-crosscheck.md` | 14.8 | 2026-10-01 | 0/1 | 僅被 1 份文件引用（例：docs/platform/plans/HANDOFF-HOST-20261001.md）；最後 2026-10-01；非即時入口 |
| `docs/platform/plans/expense-a2/payment-request-facts.md` | 7.4 | 2026-10-01 | 0/2 | 僅被 2 份文件引用（例：docs/platform/plans/HANDOFF-HOST-20261001.md）；最後 2026-10-01；非即時入口 |
| `docs/platform/plans/expense-a2/w2-expense-slices-design.md` | 13.4 | 2026-10-01 | 0/2 | 僅被 2 份文件引用（例：docs/platform/plans/HANDOFF-HOST-20261001.md）；最後 2026-10-01；非即時入口 |
| `docs/platform/plans/expense-types-designer-shots/new_dark_desktop.png` | 104.0 | 2026-10-02 | 0/0 | 無任何引用；最後 2026-10-02；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/expense-types-designer-shots/new_dark_phone.png` | 80.2 | 2026-10-02 | 0/0 | 無任何引用；最後 2026-10-02；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/expense-types-designer-shots/new_light_desktop.png` | 98.7 | 2026-10-02 | 0/0 | 無任何引用；最後 2026-10-02；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/expense-types-designer-shots/new_light_phone.png` | 76.5 | 2026-10-02 | 0/0 | 無任何引用；最後 2026-10-02；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/expense-types-designer-shots/old_dark_desktop.png` | 216.8 | 2026-10-02 | 0/0 | 無任何引用；最後 2026-10-02；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/expense-types-designer-shots/old_dark_phone.png` | 142.5 | 2026-10-02 | 0/0 | 無任何引用；最後 2026-10-02；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/expense-types-designer-shots/old_light_desktop.png` | 192.1 | 2026-10-02 | 0/0 | 無任何引用；最後 2026-10-02；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/expense-types-designer-shots/old_light_phone.png` | 126.0 | 2026-10-02 | 0/0 | 無任何引用；最後 2026-10-02；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/form-designer-shots/dark-fixed-1-builder.png` | 125.2 | 2026-10-02 | 0/0 | 無任何引用；最後 2026-10-02；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/form-designer-shots/dark-fixed-2-dialog.png` | 140.9 | 2026-10-02 | 0/0 | 無任何引用；最後 2026-10-02；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/form-designer-shots/fd_1_light.png` | 177.0 | 2026-10-02 | 0/0 | 無任何引用；最後 2026-10-02；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/form-designer-shots/fd_2_calc.png` | 172.8 | 2026-10-02 | 0/0 | 無任何引用；最後 2026-10-02；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/form-designer-shots/fd_3_fill.png` | 176.1 | 2026-10-02 | 0/0 | 無任何引用；最後 2026-10-02；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/form-designer-shots/fd_4_dark.png` | 181.0 | 2026-10-02 | 0/0 | 無任何引用；最後 2026-10-02；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/form-designer-shots/fd_5_checklist.png` | 258.1 | 2026-10-02 | 0/0 | 無任何引用；最後 2026-10-02；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/form-designer-shots/fd_7_mobile.png` | 78.0 | 2026-10-02 | 0/0 | 無任何引用；最後 2026-10-02；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/form-designer-shots/impl-1-light-calc.png` | 110.9 | 2026-10-02 | 0/0 | 無任何引用；最後 2026-10-02；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/form-designer-shots/impl-2-dark-options.png` | 120.3 | 2026-10-02 | 0/0 | 無任何引用；最後 2026-10-02；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/form-designer-shots/impl-3-mobile.png` | 43.4 | 2026-10-02 | 0/0 | 無任何引用；最後 2026-10-02；一次性規劃／報告，工作多半已出貨（需人工確認） |
| `docs/platform/plans/form-designer-shots/preview-1-light.png` | 111.9 | 2026-10-02 | 0/1 | 僅被 1 份文件引用（例：docs/platform/plans/FORM-DESIGNER-PREVIEW-GUIDE.md）；最後 2026-10-02；非即時入口 |
| `docs/platform/plans/form-designer-shots/preview-2-dark.png` | 120.0 | 2026-10-02 | 0/1 | 僅被 1 份文件引用（例：docs/platform/plans/FORM-DESIGNER-PREVIEW-GUIDE.md）；最後 2026-10-02；非即時入口 |
| `docs/platform/plans/form-designer-shots/preview-3-checklist.png` | 139.7 | 2026-10-02 | 0/1 | 僅被 1 份文件引用（例：docs/platform/plans/FORM-DESIGNER-PREVIEW-GUIDE.md）；最後 2026-10-02；非即時入口 |
| `docs/platform/plans/form-designer-shots/preview-4-mobile-form.png` | 44.3 | 2026-10-02 | 0/1 | 僅被 1 份文件引用（例：docs/platform/plans/FORM-DESIGNER-PREVIEW-GUIDE.md）；最後 2026-10-02；非即時入口 |
| `docs/platform/plans/form-designer-shots/preview-5-mobile-settings.png` | 42.2 | 2026-10-02 | 0/1 | 僅被 1 份文件引用（例：docs/platform/plans/FORM-DESIGNER-PREVIEW-GUIDE.md）；最後 2026-10-02；非即時入口 |
| `docs/platform/plans/form-designer-shots/preview-6-expense-light.png` | 97.5 | 2026-10-02 | 0/1 | 僅被 1 份文件引用（例：docs/platform/plans/FORM-DESIGNER-PREVIEW-GUIDE.md）；最後 2026-10-02；非即時入口 |
| `docs/platform/plans/form-designer-shots/preview-7-expense-dark.png` | 102.2 | 2026-10-02 | 0/1 | 僅被 1 份文件引用（例：docs/platform/plans/FORM-DESIGNER-PREVIEW-GUIDE.md）；最後 2026-10-02；非即時入口 |
| `docs/platform/prod-tasks/20260929-tender-radar-measure.md` | 3.3 | 2026-09-29 | 0/0 | 已出貨班次的正式機步驟檔（歷史紀錄；最後 2026-09-29）；現行範本＝TEMPLATE-apply.md |
| `docs/platform/prod-tasks/20260929-train22-apply.md` | 10.3 | 2026-09-29 | 0/1 | 已出貨班次的正式機步驟檔（歷史紀錄；最後 2026-09-29）；現行範本＝TEMPLATE-apply.md |
| `docs/platform/prod-tasks/20260930-train23-apply.md` | 12.1 | 2026-09-30 | 0/0 | 已出貨班次的正式機步驟檔（歷史紀錄；最後 2026-09-30）；現行範本＝TEMPLATE-apply.md |
| `docs/platform/prod-tasks/20260930-train24-apply.md` | 9.9 | 2026-09-30 | 0/0 | 已出貨班次的正式機步驟檔（歷史紀錄；最後 2026-09-30）；現行範本＝TEMPLATE-apply.md |
| `docs/platform/prod-tasks/20260930-train25-apply.md` | 10.1 | 2026-09-30 | 0/0 | 已出貨班次的正式機步驟檔（歷史紀錄；最後 2026-09-30）；現行範本＝TEMPLATE-apply.md |
| `docs/platform/prod-tasks/20260930-train26-apply.md` | 11.1 | 2026-09-30 | 0/0 | 已出貨班次的正式機步驟檔（歷史紀錄；最後 2026-09-30）；現行範本＝TEMPLATE-apply.md |
| `docs/platform/prod-tasks/20261001-train27-apply.md` | 13.0 | 2026-10-01 | 0/0 | 已出貨班次的正式機步驟檔（歷史紀錄；最後 2026-10-01）；現行範本＝TEMPLATE-apply.md |
| `docs/platform/prod-tasks/20261001-train28-apply.md` | 10.9 | 2026-10-01 | 0/1 | 已出貨班次的正式機步驟檔（歷史紀錄；最後 2026-10-01）；現行範本＝TEMPLATE-apply.md |
| `docs/platform/prod-tasks/20261004-train37-apply.md` | 9.0 | 2026-10-04 | 0/0 | 已出貨班次的正式機步驟檔（歷史紀錄；最後 2026-10-04）；現行範本＝TEMPLATE-apply.md |
| `docs/platform/prod-tasks/20261004-train37b-apply.md` | 6.6 | 2026-10-04 | 0/0 | 已出貨班次的正式機步驟檔（歷史紀錄；最後 2026-10-04）；現行範本＝TEMPLATE-apply.md |
| `docs/platform/prod-tasks/20261004-train38-apply.md` | 8.2 | 2026-10-04 | 0/0 | 已出貨班次的正式機步驟檔（歷史紀錄；最後 2026-10-04）；現行範本＝TEMPLATE-apply.md |
| `docs/platform/prod-tasks/20261005-train39-apply.md` | 7.9 | 2026-10-05 | 0/0 | 已出貨班次的正式機步驟檔（歷史紀錄；最後 2026-10-05）；現行範本＝TEMPLATE-apply.md |
| `docs/platform/prod-tasks/20261005-train40-apply.md` | 8.5 | 2026-10-05 | 0/0 | 已出貨班次的正式機步驟檔（歷史紀錄；最後 2026-10-05）；現行範本＝TEMPLATE-apply.md |
| `docs/platform/prod-tasks/20261005-train40-quick-apply.md` | 7.9 | 2026-10-05 | 0/0 | 已出貨班次的正式機步驟檔（歷史紀錄；最後 2026-10-05）；現行範本＝TEMPLATE-apply.md |
| `docs/platform/prod-tasks/20261005-train41-apply.md` | 8.2 | 2026-10-05 | 0/0 | 已出貨班次的正式機步驟檔（歷史紀錄；最後 2026-10-05）；現行範本＝TEMPLATE-apply.md |
| `docs/platform/states/repro/r1_loader.py` | 3.1 | 2026-09-26 | 0/1 | 僅被 1 份文件引用（例：docs/platform/states/STATES-PLATFORM.md）；最後 2026-09-26；非即時入口 |
| `docs/platform/states/repro/r2_disabled_list.py` | 1.1 | 2026-09-26 | 0/1 | 僅被 1 份文件引用（例：docs/platform/states/STATES-PLATFORM.md）；最後 2026-09-26；非即時入口 |
| `docs/system-home-mockup.html` | 86.4 | 2026-09-14 | 0/4 | 僅被 4 份文件引用（例：docs/UI-REDESIGN-PLAN.md）；最後 2026-09-14；非即時入口 |

### KEEP（94）

| 檔案 | KB | 最後異動 | 硬/文件引用 | 證據 |
|---|---:|---|---:|---|
| `AGENT-HANDOFF-TEMPLATE.md` | 2.7 | 2026-09-10 | 1/4 | 程式／測試／工具／設定引用（1 處，例：backend/tools/verify_package.py） |
| `DEPLOY.md` | 21.9 | 2026-09-23 | 11/12 | 程式／測試／工具／設定引用（11 處，例：backend/helpers/startup.py） |
| `DR-SOP.md` | 20.7 | 2026-09-30 | 8/9 | 程式／測試／工具／設定引用（8 處，例：backend/archive.py） |
| `GITFLOW.md` | 2.6 | 2026-07-22 | 4/4 | 程式／測試／工具／設定引用（4 處，例：backend/tools/apply_update.ps1） |
| `HTTPS-DEPLOY-CHECKLIST.md` | 3.7 | 2026-08-28 | 1/3 | 程式／測試／工具／設定引用（1 處，例：backend/version_manifest.json） |
| `LETSENCRYPT-PUBLIC-CERT-PLAN.md` | 11.4 | 2026-09-11 | 1/5 | 程式／測試／工具／設定引用（1 處，例：backend/tools/letsencrypt_renew.ps1） |
| `MODULE-AUDIT-2026-09-13.md` | 26.1 | 2026-09-14 | 6/6 | 程式／測試／工具／設定引用（6 處，例：backend/helpers/auth.py） |
| `MOTRIX-ERP-ARCHITECTURE-MAP.md` | 44.8 | 2026-09-15 | 1/6 | 程式／測試／工具／設定引用（1 處，例：backend/tools/verify_package.py） |
| `MOTRIX-ERP-QUICK.md` | 28.7 | 2026-09-23 | 32/35 | 程式／測試／工具／設定引用（32 處，例：backend/archive.py） |
| `MULTIWIN-PROTOCOL.md` | 76.4 | 2026-09-30 | 8/15 | 程式／測試／工具／設定引用（8 處，例：backend/conftest.py） |
| `NETWORK-PLAN-MODULE-DESIGN.md` | 28.3 | 2026-08-26 | 5/3 | 程式／測試／工具／設定引用（5 處，例：backend/db.py） |
| `PASSKEY-CA-ROLLOUT.md` | 16.6 | 2026-09-11 | 2/7 | 程式／測試／工具／設定引用（2 處，例：backend/tools/fetch_root_ca.ps1） |
| `WEEKLY-AUDIT-2026-09-07_2026-09-10.md` | 45.8 | 2026-09-11 | 3/7 | 程式／測試／工具／設定引用（3 處，例：backend/modules/case/api/material_orders.py） |
| `docs/MOTRIX_ERP_System_Plan.md` | 32.1 | 2026-09-06 | 1/2 | 程式／測試／工具／設定引用（1 處，例：backend/version_manifest.json） |
| `docs/UI-REDESIGN-PLAN.md` | 22.7 | 2026-09-14 | 1/3 | 程式／測試／工具／設定引用（1 處，例：frontend/index.html） |
| `docs/module-viz-mockup.html` | 95.2 | 2026-09-14 | 2/3 | 程式／測試／工具／設定引用（2 處，例：backend/modules/case/api/quotations.py） |
| `docs/platform/BENCHMARK.md` | 42.0 | 2026-09-25 | 9/3 | 程式／測試／工具／設定引用（9 處，例：backend/helpers/legal_params.py） |
| `docs/platform/BUILD-VERIFY-OPTIMIZATION-T47.md` | 13.0 | 2026-10-08 | 0/1 | 最近 3 天內有異動（最後 2026-10-08）；第 47～48 班仍在流動 |
| `docs/platform/BUILDER-UX.md` | 27.8 | 2026-09-30 | 18/2 | 程式／測試／工具／設定引用（18 處，例：backend/helpers/custom_modules.py） |
| `docs/platform/COMPANY-SETUP-GATE.md` | 67.9 | 2026-09-29 | 41/4 | 程式／測試／工具／設定引用（41 處，例：backend/conftest.py） |
| `docs/platform/D7-CHECKLIST.md` | 10.7 | 2026-10-08 | 3/0 | 程式／測試／工具／設定引用（3 處，例：backend/tests/platform/test_final_drill_tool.py） |
| `docs/platform/DATA-COMPAT.md` | 24.2 | 2026-10-08 | 9/1 | 程式／測試／工具／設定引用（9 處，例：backend/archive.py） |
| `docs/platform/DEPENDENCY-MAP.md` | 21.6 | 2026-09-26 | 19/3 | 程式／測試／工具／設定引用（19 處，例：backend/core/txn.py） |
| `docs/platform/FINAL-DRILL-REPORT.md` | 45.7 | 2026-09-27 | 1/5 | 程式／測試／工具／設定引用（1 處，例：tools/platform/final_drill.py） |
| `docs/platform/FINANCE-INTEGRATION.md` | 15.9 | 2026-10-02 | 0/3 | 被 3 份文件引用，含現行入口文件（例：docs/platform/CACHE-INDEX.md） |
| `docs/platform/GOOGLE-BASEMAP.md` | 13.1 | 2026-09-28 | 4/3 | 程式／測試／工具／設定引用（4 處，例：backend/tests/test_e2e_map_google_basemap_2026_09_28.py） |
| `docs/platform/IMPROVEMENT-REPORT.md` | 56.8 | 2026-09-28 | 9/3 | 程式／測試／工具／設定引用（9 處，例：backend/core/upgrade.py） |
| `docs/platform/INTEGRATION-POINTS.md` | 139.6 | 2026-10-08 | 36/21 | 程式／測試／工具／設定引用（36 處，例：backend/core/catalog.py） |
| `docs/platform/LEDGER-ACCEPTANCE.md` | 9.0 | 2026-10-01 | 1/3 | 程式／測試／工具／設定引用（1 處，例：backend/modules/accounting/tests/test_ledger_acceptance_2026_10_01.py） |
| `docs/platform/LODGING-NEARBY.md` | 47.6 | 2026-09-29 | 17/7 | 程式／測試／工具／設定引用（17 處，例：backend/archive.py） |
| `docs/platform/MODULE-GUIDE.md` | 42.6 | 2026-10-08 | 53/3 | 程式／測試／工具／設定引用（53 處，例：backend/archive.py） |
| `docs/platform/MODULE-UPDATE-DELIVERY.md` | 50.8 | 2026-09-29 | 12/3 | 程式／測試／工具／設定引用（12 處，例：backend/tests/platform/test_apply_module_update_ps1_2026_09_28.py） |
| `docs/platform/MODULE-UPDATE-PROD-INSTRUCTIONS.md` | 10.9 | 2026-09-29 | 2/0 | 程式／測試／工具／設定引用（2 處，例：backend/tools/apply_plan.py） |
| `docs/platform/MONEY-FLOWS.md` | 24.0 | 2026-10-02 | 25/6 | 程式／測試／工具／設定引用（25 處，例：backend/helpers/gl_status.py） |
| `docs/platform/PLAYBOOK.md` | 74.4 | 2026-10-08 | 190/3 | 程式／測試／工具／設定引用（190 處，例：backend/core/catalog.py） |
| `docs/platform/PO-VENDOR-BANK-GAP-T47.md` | 5.4 | 2026-10-08 | 1/2 | 程式／測試／工具／設定引用（1 處，例：backend/modules/case/tests/test_po_vendor_bank_t47_2026_10_08.py） |
| `docs/platform/PROD-DEV-CHANNEL.md` | 6.5 | 2026-09-30 | 2/0 | 程式／測試／工具／設定引用（2 處，例：backend/tests/platform/test_prod_status_snapshot_2026_09_30.py） |
| `docs/platform/ROADMAP.md` | 28.6 | 2026-09-27 | 0/3 | 被 3 份文件引用，含現行入口文件（例：docs/platform/PLAYBOOK.md） |
| `docs/platform/RUN-LOG.md` | 105.6 | 2026-09-27 | 0/3 | 被 3 份文件引用，含現行入口文件（例：docs/platform/CORE-SPEC.md） |
| `docs/platform/STAGE-C-DESIGN.md` | 15.9 | 2026-09-26 | 4/3 | 程式／測試／工具／設定引用（4 處，例：backend/core/menu.py） |
| `docs/platform/TAX401-OFFICIAL-FIELDS.md` | 9.9 | 2026-10-01 | 1/4 | 程式／測試／工具／設定引用（1 處，例：backend/modules/accounting/ledger/tax401.py） |
| `docs/platform/THIRD-PARTY-LICENSES.md` | 1.5 | 2026-09-30 | 2/0 | 程式／測試／工具／設定引用（2 處，例：backend/tests/platform/test_font_license_2026_09_30.py） |
| `docs/platform/TRAIN-PREFLIGHT-T47.md` | 7.6 | 2026-10-08 | 1/0 | 程式／測試／工具／設定引用（1 處，例：tools/platform/train_preflight.py） |
| `docs/platform/UPDATE-DELIVERY.md` | 18.5 | 2026-09-29 | 20/6 | 程式／測試／工具／設定引用（20 處，例：backend/tests/platform/test_apply_module_update_ps1_2026_09_28.py） |
| `docs/platform/UPGRADE-RUNBOOK.md` | 28.9 | 2026-10-08 | 7/2 | 程式／測試／工具／設定引用（7 處，例：backend/tools/_dashboard_remote.ps1） |
| `docs/platform/case_read_scope.json` | 8.7 | 2026-10-06 | 7/6 | 程式／測試／工具／設定引用（7 處，例：backend/modules/case/api/case_extra_expenses.py） |
| `docs/platform/deprecations.json` | 1.9 | 2026-09-27 | 5/7 | 程式／測試／工具／設定引用（5 處，例：backend/helpers/tiered_approval.py） |
| `docs/platform/modules.json` | 22.5 | 2026-10-09 | 45/50 | 程式／測試／工具／設定引用（45 處，例：backend/core/menu.py） |
| `docs/platform/money_flows.json` | 1.9 | 2026-10-02 | 4/4 | 程式／測試／工具／設定引用（4 處，例：backend/tests/platform/test_money_flows_registered.py） |
| `docs/platform/mustfix_legacy_closures.json` | 2.9 | 2026-09-28 | 1/2 | 程式／測試／工具／設定引用（1 處，例：tools/platform/mustfix_scan.py） |
| `docs/platform/mustfix_open.json` | 1.5 | 2026-09-29 | 2/4 | 程式／測試／工具／設定引用（2 處，例：backend/tests/platform/test_mustfix_closure_scan.py） |
| `docs/platform/pii_forms.json` | 8.6 | 2026-10-02 | 8/12 | 程式／測試／工具／設定引用（8 處，例：backend/helpers/privacy_notice.py） |
| `docs/platform/plans/ATTACHMENTS-PLAN.md` | 9.0 | 2026-09-26 | 1/4 | 程式／測試／工具／設定引用（1 處，例：backend/tests/platform/test_attachments_providers.py） |
| `docs/platform/plans/AUTHOR-GATE-DESIGN.md` | 10.0 | 2026-10-02 | 1/0 | 程式／測試／工具／設定引用（1 處，例：tools/platform/author_gate.py） |
| `docs/platform/plans/BUILD-OPT-ITEM3-INCREMENTAL-DESIGN.md` | 33.2 | 2026-10-02 | 2/0 | 程式／測試／工具／設定引用（2 處，例：tools/platform/replay_incremental.py） |
| `docs/platform/plans/BUILD-OPTIMIZATION-2.md` | 32.6 | 2026-10-02 | 3/0 | 程式／測試／工具／設定引用（3 處，例：backend/tools/build_deploy_package.ps1） |
| `docs/platform/plans/BUILDER-B-DESIGN.md` | 11.0 | 2026-10-01 | 6/2 | 程式／測試／工具／設定引用（6 處，例：backend/core/mounts.py） |
| `docs/platform/plans/D12-VERIFY-GUIDE.md` | 7.3 | 2026-10-03 | 1/1 | 程式／測試／工具／設定引用（1 處，例：backend/tests/test_e2e_designer_real_mouse_2026_10_03.py） |
| `docs/platform/plans/DISPATCH-APPROVAL-DESIGN.md` | 39.9 | 2026-10-01 | 2/1 | 程式／測試／工具／設定引用（2 處，例：backend/modules/subcontract/dispatch_flow.py） |
| `docs/platform/plans/DRAFT-CONCURRENCY-DESIGN.md` | 7.2 | 2026-10-02 | 1/2 | 程式／測試／工具／設定引用（1 處，例：backend/tests/test_definitions_draft_etag_2026_10_02.py） |
| `docs/platform/plans/E2E-SLEEP-HAZARD-AUDIT.md` | 5.8 | 2026-10-02 | 1/0 | 程式／測試／工具／設定引用（1 處，例：backend/tests/test_e2e_sleep_fix_reverse_control_2026_10_02.py） |
| `docs/platform/plans/FINANCE-ROLE-GOLIVE.md` | 10.3 | 2026-10-05 | 8/0 | 程式／測試／工具／設定引用（8 處，例：backend/modules/accounting/tests/test_ledger_annotations_2026_09_30.py） |
| `docs/platform/plans/FORM-DESIGNER-DESIGN.md` | 26.0 | 2026-10-02 | 4/0 | 程式／測試／工具／設定引用（4 處，例：backend/tests/test_e2e_form_designer_beginner_tasks_2026_10_02.py） |
| `docs/platform/plans/FORM-DESIGNER-PREVIEW-GUIDE.md` | 6.3 | 2026-10-02 | 1/0 | 程式／測試／工具／設定引用（1 處，例：backend/tests/test_e2e_designer_default_on_2026_10_03.py） |
| `docs/platform/plans/GENERATED-FILES-PROPOSAL.md` | 8.1 | 2026-09-26 | 3/1 | 程式／測試／工具／設定引用（3 處，例：backend/tests/platform/test_generated_maps.py） |
| `docs/platform/plans/HANDOFF-AB-T47.md` | 6.7 | 2026-10-09 | 0/0 | 最近 3 天內有異動（最後 2026-10-09）；第 47～48 班仍在流動 |
| `docs/platform/plans/M01-PLAN.md` | 25.2 | 2026-09-27 | 46/0 | 程式／測試／工具／設定引用（46 處，例：backend/helpers/__init__.py） |
| `docs/platform/plans/M06-PLAN.md` | 21.4 | 2026-09-26 | 3/3 | 程式／測試／工具／設定引用（3 處，例：backend/modules/arap/module.json） |
| `docs/platform/plans/NOTE-DASHBOARD-CACHE-T40.md` | 1.8 | 2026-10-05 | 0/1 | 僅被 1 份文件引用，但最近才動（2026-10-05）；下一輪再看 |
| `docs/platform/plans/NOTE-REPORT-LABELS-T38.md` | 4.5 | 2026-10-04 | 0/2 | 僅被 2 份文件引用，但最近才動（2026-10-04）；下一輪再看 |
| `docs/platform/plans/PAYSLIP-LEDGER-OPTIONS-T46.md` | 3.6 | 2026-10-08 | 1/1 | 程式／測試／工具／設定引用（1 處，例：backend/modules/accounting/tests/test_ledger_payslip_approval_pin_t46.py） |
| `docs/platform/plans/PO-VENDOR-BANK-GAP-T47.md` | 3.6 | 2026-10-08 | 1/3 | 程式／測試／工具／設定引用（1 處，例：backend/modules/case/tests/test_po_vendor_bank_t47_2026_10_08.py） |
| `docs/platform/plans/R2-STEP2-IMPLEMENTATION-NOTES.md` | 5.4 | 2026-10-09 | 0/1 | 最近 3 天內有異動（最後 2026-10-09）；第 47～48 班仍在流動 |
| `docs/platform/plans/SHIPPING-MATERIAL-LINK-CONTRACT-S1.md` | 7.7 | 2026-10-03 | 6/3 | 程式／測試／工具／設定引用（6 處，例：backend/modules/case/material_change.py） |
| `docs/platform/plans/T46-BASELINE-118-RELEASE-NOTES.md` | 1.8 | 2026-10-08 | 0/0 | 最近 3 天內有異動（最後 2026-10-08）；第 47～48 班仍在流動 |
| `docs/platform/plans/T47-POLICY-QUESTIONS.md` | 5.0 | 2026-10-08 | 0/1 | 最近 3 天內有異動（最後 2026-10-08）；第 47～48 班仍在流動 |
| `docs/platform/plans/T48-SMALL-ITEMS.md` | 1.7 | 2026-10-08 | 0/0 | 最近 3 天內有異動（最後 2026-10-08）；第 47～48 班仍在流動 |
| `docs/platform/plans/USER-DECISIONS.md` | 17.4 | 2026-10-04 | 1/1 | 程式／測試／工具／設定引用（1 處，例：backend/modules/case/settlement_actuals.py） |
| `docs/platform/plans/expense-a2/GL-BASE-HOOKS.md` | 9.9 | 2026-10-01 | 2/3 | 程式／測試／工具／設定引用（2 處，例：backend/helpers/custom_finance.py） |
| `docs/platform/plans/expense-a2/expense-forms-design-ae.md` | 19.8 | 2026-10-01 | 2/1 | 程式／測試／工具／設定引用（2 處，例：backend/modules/payroll/bank_account.py） |
| `docs/platform/plans/expense-a2/plan-expense-a2.md` | 38.1 | 2026-10-01 | 5/3 | 程式／測試／工具／設定引用（5 處，例：backend/helpers/expense_types.py） |
| `docs/platform/plans/expense-a2/proposal-expense-forms.md` | 29.4 | 2026-10-01 | 1/3 | 程式／測試／工具／設定引用（1 處，例：backend/modules/accounting/ledger/category_map.py） |
| `docs/platform/plans/expense-types-designer-shots/README.md` | 1.3 | 2026-10-02 | 7/14 | 程式／測試／工具／設定引用（7 處，例：backend/modules/accounting/ledger/__init__.py） |
| `docs/platform/plans/form-designer-prototype.html` | 81.9 | 2026-10-02 | 1/1 | 程式／測試／工具／設定引用（1 處，例：backend/helpers/prefill_sources.py） |
| `docs/platform/prod-tasks/20261006-train42-apply.md` | 12.0 | 2026-10-06 | 0/1 | 最近 3 天內有異動（最後 2026-10-06）；第 47～48 班仍在流動 |
| `docs/platform/prod-tasks/20261006-train43-apply.md` | 29.8 | 2026-10-06 | 0/2 | 最近 3 天內有異動（最後 2026-10-06）；第 47～48 班仍在流動 |
| `docs/platform/prod-tasks/20261007-train44-apply.md` | 20.2 | 2026-10-07 | 0/2 | 最近 3 天內有異動（最後 2026-10-07）；第 47～48 班仍在流動 |
| `docs/platform/prod-tasks/20261007-train45-apply.md` | 25.2 | 2026-10-08 | 0/2 | 最近 3 天內有異動（最後 2026-10-08）；第 47～48 班仍在流動 |
| `docs/platform/prod-tasks/20261008-train46-apply.md` | 32.2 | 2026-10-08 | 0/0 | 最近 3 天內有異動（最後 2026-10-08）；第 47～48 班仍在流動 |
| `docs/platform/prod-tasks/20261009-train47-apply.md` | 23.8 | 2026-10-09 | 0/0 | 最近 3 天內有異動（最後 2026-10-09）；第 47～48 班仍在流動 |
| `docs/platform/prod-tasks/TEMPLATE-apply.md` | 3.9 | 2026-10-08 | 0/2 | 步驟檔範本 |
| `docs/platform/states/STATES-DATA-OPS.md` | 29.2 | 2026-09-26 | 4/1 | 程式／測試／工具／設定引用（4 處，例：backend/archive.py） |
| `docs/platform/states/STATES-PLATFORM.md` | 32.8 | 2026-09-26 | 19/2 | 程式／測試／工具／設定引用（19 處，例：backend/core/loader.py） |
| `docs/platform/upload_points.json` | 4.1 | 2026-09-30 | 4/2 | 程式／測試／工具／設定引用（4 處，例：backend/tests/platform/test_upload_points_registered.py） |

### PROTECTED（125）

| 檔案 | KB | 最後異動 | 硬/文件引用 | 證據 |
|---|---:|---|---:|---|
| `CHANGELOG.md` | 0.4 | 2026-09-23 | 32/26 | 各 CHANGELOG（G2／G4 守門讀） |
| `SELLABLE-AND-MOBILE-SPEC.md` | 57.3 | 2026-09-21 | 1/4 | 模組／核心 SPEC |
| `docs/platform/CACHE-INDEX.md` | 6.9 | 2026-09-30 | 2/0 | 產生檔／索引（regen_all／測試讀） |
| `docs/platform/CORE-SPEC.md` | 74.0 | 2026-10-08 | 114/9 | 模組／核心 SPEC |
| `docs/platform/CUSTOMIZATION-SPEC.md` | 56.3 | 2026-09-26 | 88/1 | 模組／核心 SPEC |
| `docs/platform/RUN-PLAN.md` | 98.0 | 2026-10-09 | 19/3 | RUN-PLAN（開工必讀） |
| `docs/platform/UNIT-INDEX.md` | 15.0 | 2026-10-09 | 10/2 | 產生檔／索引（regen_all／測試讀） |
| `docs/platform/audit/AUDIT-A-B41-payreq.md` | 16.3 | 2026-09-28 | 0/0 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-A-B42-B43.md` | 5.6 | 2026-09-28 | 0/0 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-A-H12-apply.md` | 23.0 | 2026-09-28 | 0/0 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-B-host-O7.md` | 9.4 | 2026-09-26 | 2/0 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-C-B-guards.md` | 13.7 | 2026-09-25 | 2/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-C-host-D3D5.md` | 13.1 | 2026-09-26 | 1/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-C-host-dashboard.md` | 12.5 | 2026-09-28 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-A-M03-move.md` | 3.4 | 2026-09-26 | 0/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-A-M06-move.md` | 19.9 | 2026-09-28 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-A-M10-M12.md` | 10.5 | 2026-09-26 | 0/3 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-A-M12-move.md` | 10.4 | 2026-09-26 | 4/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-A-analytics-dispatch.md` | 1.1 | 2026-09-26 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-A-approval-parse.md` | 3.3 | 2026-09-26 | 0/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-A-attachments.md` | 21.6 | 2026-09-28 | 1/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-A-bonus-U4.md` | 8.1 | 2026-09-26 | 1/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-A-branding-race.md` | 0.9 | 2026-09-28 | 0/0 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-A-build-python.md` | 2.7 | 2026-09-28 | 0/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-A-mail-settings.md` | 10.5 | 2026-09-26 | 2/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-A-switch-warn.md` | 2.4 | 2026-09-29 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-A46-api-docs-off.md` | 2.7 | 2026-09-28 | 0/0 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-A48-archive-bg.md` | 2.4 | 2026-09-29 | 0/0 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-C1-pages.md` | 10.0 | 2026-09-27 | 0/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-D1b-scope.md` | 13.5 | 2026-09-26 | 1/3 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-G1.md` | 11.6 | 2026-09-26 | 5/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-attr-modtestenv.md` | 2.1 | 2026-09-26 | 0/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-drill-absent404.md` | 6.6 | 2026-09-27 | 1/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-e2e-deadline.md` | 4.3 | 2026-09-26 | 1/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-env-guards.md` | 16.3 | 2026-09-26 | 2/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-genfiles.md` | 7.5 | 2026-09-26 | 1/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-hardcap-dir.md` | 1.8 | 2026-09-26 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-ip15-cost.md` | 1.7 | 2026-09-26 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-maps.md` | 5.2 | 2026-09-26 | 3/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-modtest-batch.md` | 4.7 | 2026-09-26 | 1/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-modtest-durations.md` | 0.5 | 2026-09-26 | 0/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-modtest-workers.md` | 6.7 | 2026-09-27 | 1/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-newctx-rule.md` | 1.8 | 2026-09-27 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-o10.md` | 1.3 | 2026-09-26 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-o11.md` | 3.0 | 2026-09-26 | 1/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-o13-o14.md` | 5.4 | 2026-09-28 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-o5-s1.md` | 3.5 | 2026-09-26 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-o5-s2.md` | 5.6 | 2026-09-26 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-o6.md` | 5.8 | 2026-09-26 | 1/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-o9-2.md` | 2.8 | 2026-09-26 | 1/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-o9.md` | 1.5 | 2026-09-26 | 1/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-probe-tmp.md` | 4.1 | 2026-09-27 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-rebasecheck.md` | 3.6 | 2026-09-26 | 1/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-routes.md` | 5.9 | 2026-09-26 | 1/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-scan-modules.md` | 4.2 | 2026-09-28 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B-t13-guards.md` | 5.2 | 2026-09-27 | 1/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B41-payreq.md` | 8.5 | 2026-09-28 | 0/0 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B54-warm-async.md` | 7.2 | 2026-09-28 | 0/0 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-B55-module-delivery.md` | 44.9 | 2026-09-29 | 1/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-C-D7-drill.md` | 14.2 | 2026-09-26 | 1/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-C-M02-move.md` | 8.9 | 2026-09-26 | 1/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-C-M04-move.md` | 11.9 | 2026-09-26 | 1/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-C-M05-move.md` | 8.8 | 2026-09-26 | 1/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-C-M07-move.md` | 8.6 | 2026-09-26 | 0/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-C-P4P5P8.md` | 19.0 | 2026-09-27 | 2/3 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-C-approval-l1.md` | 17.8 | 2026-09-27 | 1/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-C-approval.md` | 6.9 | 2026-09-26 | 1/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-C-case-access.md` | 12.2 | 2026-09-26 | 2/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-C-case404.md` | 4.8 | 2026-09-27 | 1/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-C-ip14-paid.md` | 3.4 | 2026-09-26 | 1/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-C-m01-3.md` | 2.4 | 2026-09-26 | 0/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-C-m01-4.md` | 22.6 | 2026-09-28 | 1/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-C-m01-5-red-nodeids.txt` | 87.0 | 2026-09-27 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-C-m01-5.md` | 7.1 | 2026-09-27 | 1/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-C-m01-ca3.md` | 5.8 | 2026-09-28 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-C-m01-rec.md` | 2.0 | 2026-09-26 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-C-m01-s2.md` | 2.5 | 2026-09-27 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-C-m01-s3.md` | 6.3 | 2026-09-28 | 0/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-C-probes.md` | 4.4 | 2026-09-26 | 0/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-C-tax-sink2.md` | 3.0 | 2026-09-26 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-D7-drill.md` | 4.6 | 2026-09-27 | 1/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-E1-lodging.md` | 13.5 | 2026-09-28 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-E2-lodging-impl.md` | 13.7 | 2026-09-28 | 0/0 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-E4-company-gate.md` | 43.0 | 2026-09-29 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-H-branding.md` | 4.8 | 2026-09-28 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-H-o15.md` | 1.9 | 2026-09-27 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-H12-apply.md` | 17.1 | 2026-09-28 | 1/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-H2-sale-deid.md` | 9.3 | 2026-09-28 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-H3-builder3.md` | 9.5 | 2026-09-28 | 1/0 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-P1P3-catalog.md` | 15.0 | 2026-09-26 | 1/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-P8-frontend.md` | 7.6 | 2026-09-26 | 0/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-R1-R3-legal.md` | 25.2 | 2026-09-26 | 4/4 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-builder-chain.md` | 3.2 | 2026-09-28 | 0/0 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-builder.md` | 4.7 | 2026-09-27 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-gm-raw.md` | 4.9 | 2026-09-28 | 0/0 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-host-P6-voucher-rollback.md` | 13.9 | 2026-09-26 | 0/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-host-U14-hist.md` | 8.9 | 2026-09-26 | 1/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-host-U15.md` | 7.4 | 2026-09-26 | 0/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-host-corered.md` | 1.7 | 2026-09-26 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-host-fonts-woff2.md` | 1.6 | 2026-09-26 | 0/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-host-probes.md` | 3.8 | 2026-09-26 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-host-smoke-probes.md` | 2.8 | 2026-09-26 | 0/0 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-host-train8.md` | 2.1 | 2026-09-26 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-lodging-daily.md` | 3.5 | 2026-09-29 | 0/0 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-pii-notice.md` | 11.4 | 2026-09-26 | 1/3 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-tender-precompute.md` | 7.2 | 2026-09-29 | 0/0 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-train13-fixes.md` | 6.3 | 2026-09-28 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-train14-misc.md` | 10.3 | 2026-09-28 | 0/0 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-train14-r2.md` | 14.2 | 2026-09-28 | 0/0 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-train15-map.md` | 23.3 | 2026-09-28 | 0/0 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-train18-final.md` | 4.8 | 2026-09-28 | 0/0 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-train19-final.md` | 2.7 | 2026-09-29 | 0/0 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-D-update-delivery.md` | 4.9 | 2026-09-28 | 0/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-X-9b-upgrade-paths-pii.md` | 36.9 | 2026-09-26 | 1/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-X-9c-module-select.md` | 26.3 | 2026-09-26 | 0/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-X-B-C4.md` | 18.2 | 2026-09-26 | 1/0 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-X-B-M08-move.md` | 34.0 | 2026-09-26 | 1/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-X-C-batch1.md` | 25.7 | 2026-09-26 | 5/2 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/AUDIT-X-IP1-4-row-access.md` | 26.3 | 2026-09-27 | 1/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/audit/INVESTIGATION-D-O5-index-load.md` | 5.0 | 2026-09-26 | 1/1 | 稽核紀錄（主持規定整個資料夾保留） |
| `docs/platform/dep_graph.json` | 507.2 | 2026-10-09 | 25/10 | 產生檔／索引（regen_all／測試讀） |
| `docs/platform/plans/BUILDER-ATTACH-EXISTING-MODULE-SPEC.md` | 3.4 | 2026-10-01 | 0/2 | 模組／核心 SPEC |
| `docs/platform/plans/SETTLEMENT-ACTUALS-SPEC.md` | 21.7 | 2026-10-03 | 3/1 | 模組／核心 SPEC |
| `docs/platform/runplan/RUN-PLAN-ARCHIVE-2026-09-26_2026-09-27.md` | 58.3 | 2026-09-30 | 0/1 | RUN-PLAN（開工必讀） |
| `docs/platform/test_map.json` | 842.2 | 2026-10-09 | 39/16 | 產生檔／索引（regen_all／測試讀） |

