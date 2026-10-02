# 建構器掛載 B 的「我的工作」：現況與做法（2026-10-02，W1/a3）

## 現況（已查證，origin/wip/train-31-int1 83cb132c）
- 「我的工作」是**側欄選單群組**（`core/menu_l1.json` key `mywork`），不是一頁。底下的頁面分屬不同模組：
  | 頁面 | 模組 | 有頁籤列 | 掛載點 |
  |---|---|---|---|
  | `daily-tasks.html` 每日工作事項 | daily_tasks | 有（`.dt-tab-bar`） | **已有** `daily_tasks.daily-tasks`（第 30 班出貨，`module.json mount_points`，頁面 `x-data="motrixMountTabs(...)"`） |
  | `work-log.html` 工作日誌 | 內建（menu_l1） | 無 | 無 |
  | `approval-queue.html` 簽核佇列／`approval-delegates.html` 簽核代理人 | 內建（menu_l1） | 無 | 無 |
  | `payment-request.html` 新增請款／`approval-history.html` 簽核歷史 | case | 無 | 無 |
- 機制已齊：`core.mounts`（宣告驗證、容量 8）、`GET /api/platform/mount-points`、`GET /api/platform/mounts?point=`（權限＝模組可見 ∩ 點 perm ∩ 自訂模組可見）、建構器「掛到哪一頁」下拉、`static/mount-tabs.js` 元件、iframe 嵌入；e2e：`test_e2e_builder_b_mount`（頁籤出現／嵌入／建單／刪除後消失、無權限者看不到）、`_embed`、`_ui`、守門 `test_mount_points_guards`、`test_builder_b_mounts`。
- 所以「先掛我的工作」的**首批已完成**：自訂模組選「每日工作事項頁籤」發布後就出現在每日工作事項頁。無自訂模組掛載時畫面不變（元件在 0 個頁籤時不輸出任何按鈕；`test_e2e_builder_b_mount` 有驗）。

## 還沒做、需要你裁示的
「我的工作」群組其餘 5 頁都沒有頁籤列，要掛就得**先替該頁加一排頁籤**（UI 變動），不是只加宣告：
1. 做法 A（建議，最小）：不再加頁面，維持「我的工作 = 每日工作事項頁」這一個掛載點；已可用。
2. 做法 B：再選 1～2 頁（建議 `payment-request.html` 新增請款、`approval-history.html` 簽核歷史，屬 case 模組）：頁面加一排頁籤列（原內容成為第一個頁籤「原有內容」，無掛載時整排不顯示 ⇒ 畫面完全不變），case 的 `module.json` 加 `mount_points`，各一題 e2e。每頁約 0.3 班；須動 case 模組（版本／CHANGELOG／模組邊界）。
3. 做法 C：全部 5 頁（含 menu_l1 內建頁 work-log／approval-*）：menu_l1 頁面沒有 module.json 可宣告掛載點 ⇒ 需先擴 `core.mounts` 支援 L1 宣告（L0/L1 契約變更，要走 PLAYBOOK §C-7）。不建議本班做。

## 要你回答
- 「我的工作」要掛的是哪一頁？若 A（已完成）就不用再動；若 B，請指定頁面。
- 掛在這些頁時要不要帶上下文（例：簽核歷史頁帶單據號 `doc_no`）？首批不帶（`context: []`）。
