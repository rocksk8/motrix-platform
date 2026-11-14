# 檔案中心 更新紀錄

## (next) — 2026-11-14（feat/t86-short-labels-h2；T86 短標籤專業化）
- 文字（行為、API、欄位、設定鍵、錯誤碼不變）：按鈕、卡片標題、表頭、空狀態與提示等短標籤改為正式、一致的用語（前往／查看、尚無／查無符合條件的…、僅顯示、無法…等）；前後對照見整合者的 T86 前後對照表。

## 1.0.10 — 2026-11-14（train/t85-text；T85 文字專業化；版號由列車取）
- 文字（行為、API、欄位、設定鍵、錯誤碼不變）：畫面、通知、錯誤提示與說明文字改為正式、一致的用語（您、尚未／尚無、是否、其他使用者、無法／不可等），標點與中英文間距依 `docs/platform/plans/TEXT-STYLE-GUIDE.md`；同一提交同步更新斷言字串的測試。逐項前後對照見 `docs/platform/plans/TEXT-DIFF-TABLE.md`。

## 1.0.9 — 2026-11-13（feat/ux-p15-dashboard；UX P1.5）
- 前端（文字）：頁面 `<title>` 後綴「專案管理系統」一律改為「MOTRIX PLATFORM」（系統標語改由公司設定 `brand.tagline` 決定，預設 MOTRIX PLATFORM）；不動 API／資料／權限。

## 1.0.8（next，未取號）— 2026-11-13（ui/mobile-tablet-combined 的改動；條目由 fix/mobile-cases-layout-v2 補，依各頁 git 歷史照實記錄；僅前端版面，不動 API／資料／權限判斷）
- `file-center.html`：手機／平板版面——768–900px 時檔案分類樹改為橫向捲動的一列分類鈕（每顆 ≥40px 高），其餘為手機版間距與觸控目標調整；桌機版不變。

## 1.0.7 — 2026-11-11（feat/ux-navigation-hierarchy；UX 提案批次 1+2「導覽與資訊架構＋視覺層級」；不動 API／資料／權限判斷；L1 介面不變）
- 前端視覺（D3）：本模組頁面內文字最小 12px（原有 9～11px 一律拉到 12px）；文字色改用語意 token（`--text-secondary` #595959／`--text-dim` #666666／深底 `--text-on-dark-dim` #A3A3A3，在頁底 #F5F4F0 上對比 ≥4.5:1）。只改 CSS 值，不改版面結構、不改 API、資料、權限。規格見 `docs/UI-HEADER-COLOR-SPEC.md`。
- 測試：`tests/test_e2e_nav_hierarchy_2026_11_11.py`（7 項真瀏覽器：每個舊入口仍可達、群組與報表中心頁籤、權限過濾、頁頭麵包屑）。

## 1.0.6 — 2026-10-10（wip/t50-int；第 50 班）
- **（併入）(next) — 2026-10-10（wip/t54-b5-system-hub-p1；系統中心 P1）：module.json 新增 `system_cards`（檔案中心卡片）**
- 加性宣告：在系統中心（`/pages/system-hub.html`）登記這個模組擁有的系統頁面；只影響索引顯示，頁面與 API 的權限、行為完全不變。
- **（併入）(next) — 2026-10-10（wip/t54-b5-system-hub-p1；系統中心 P1；r5）：module.json 新增 `system_cards`（檔案中心卡片）**

## 1.0.5 — 2026-10-08（第 46 班：探針路徑修正）
- `module.json`：探針 `GET /api/filehub/search` 不帶查詢字串（守門 test_product_drill_probes 要求）。1.0.4 的版號條目寫的就是這支探針；行為與介面不變。

## 1.0.4 — 2026-10-08（第 46 班：D7 演練冒煙）
- `module.json`：宣告 `provides.probes`＝`GET /api/filehub/search`（唯讀；探針路徑不帶查詢字串，守門 test_product_drill_probes）。原本是空陣列 ⇒ 完整演練冒煙把模組判為「沒宣告 probes」而紅（D7-CHECKLIST §4）。API、頁面、權限不變。

## 1.0.3 — 2026-10-01（wip/t31-filecenter-open-a3：開啟檔案）
- `file-center.html`：結果列主動作改為「開啟檔案」（圖片／PDF 於新分頁開上傳的檔，其他類型走預覽窗；已刪除／無權限顯示明確訊息、不留空白分頁）；原「開啟原單據」降為次要連結「前往原單據」。取檔仍是 `attachments/open`，API 與權限不變。

## 1.0.2 — 2026-10-01（fix/t29-w1：建包全量關卡三紅）
- `file-center.html`：登記為唯讀頁（理由：只有 `GET /api/filehub/search`；上傳與刪除在來源單據）；`daysAgo` 改用 `MotrixDate`（不以 UTC 切日期，台北 00:00–08:00 不會變前一天）並補 `motrix-date.js`。介面不變。

## 1.0.1 — 2026-10-01（fix/filehub-guards：守門三紅）
- `api.py`：類別清單合併改用 `{"type": t, **meta}`（不以 `**` 當呼叫引數，守門 `test_case_summary_purpose`）；補 `SPEC.md`（FHB1～FHB8，模組檔案齊全守門）。行為與介面不變。

## 1.0.0 — 2026-09-30（暫用號，列車取號；wip/w1-attach-p3 附件目錄 P3）
- 新增：`GET /api/filehub/search`（關鍵字、類別、副檔名、上傳日期區間、上傳者、案件號／單號、客戶；合併各 `attachments.catalog` 提供者的 `search`／`count`，依上傳時間由新到舊、`page ≤ 20`、`size ≤ 50`；回 `items`／`facets`／`categories`／`unavailable`；項目沒有 path，看不到的不列也不回個數；模組不在或提供者失敗明說）。
- 新增：頁面 `file-center.html`（系統群組「檔案中心」，權限／模組開關 `file_center`）：左側分類樹（模組→單據類別＋命中數）、條件列（條件寫進網址）、結果表、點列用共用預覽元件（◀ ▶ 在結果內切換）、「開啟原單據」；預設只查近 90 天（可改）。
- 案件管理頁「全部附件」頁籤（檔案中心在才出現）呼叫同一支 API 固定 `quote_no`。
