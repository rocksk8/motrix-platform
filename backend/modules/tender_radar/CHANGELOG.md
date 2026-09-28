# 標案雷達 更新紀錄

## 1.3.4 — 2026-09-29 00:02（暫用號；D 觀察，主持派工）
- 只改註解：`source._tender_scan_tick` 的說明不再點名 `archive._schedule_daily` 當反例（B54-S2 已把它改成同一個形狀），只講「工作包 try、重排放 finally」這條規則本身；行為不變

## 1.3.3 — 2026-09-28 14:50（暫用號；第十五班緊急修補 B54，主持裁示）
- `source.schedule_tender_scan()` 改為立即返回：第一輪排進 daemon Timer（`_TENDER_SCAN_FIRST_DELAY_SECONDS`＝30 秒）在背景跑，之後每輪結束（含丟例外）再排下一輪（`_tender_scan_tick`，重排維持 finally）。原本同步跑第一輪 ⇒ 套用時間落在抓取時段且未抓過時啟動被卡最多約 340 秒 ⇒ 健康檢查失敗、自動回滾

## 1.3.2 — 2026-09-27 23:02（暫用號；H10 品牌設定，主持派工）
- 頁面的分頁圖示（favicon）改讀 `/api/system/branding/favicon`（L1 品牌設定，可在公司資料設定更換；沒上傳回預設圖）：`tender-radar.html`

## 1.3.1 — 2026-09-26
- 宣告 `provides.probes`（D7 演練與產品演練打這幾支確認模組在；純讀、無副作用，D7-CHECKLIST §4）

## 1.3.0 — 2026-09-26
- P9 排版器套用（CUSTOMIZATION-SPEC §3.10）：標案清單、搜尋條件清單、搜尋條件表單、按鈕與條件列操作改由 `$store.layout`（layout-runtime.js）渲染 ⇒ 依 `resolve(layout, module:tender_radar, 角色)` 套用（角色 ＞ 公司 ＞ 程式預設），標案清單可依個人偏好隱藏欄位與調整順序；超級管理員在本頁按「編輯版面」同頁排版
- module.json：搜尋條件表單分成兩個區塊「條件」（名稱、關鍵字、排除詞）與「篩選範圍」（機關、預算上下限、狀態），讓區塊可以排序、欄位可以跨區塊移動

## 1.2.0 — 2026-09-26
- module.json 新增 `customization`（CUSTOMIZATION-SPEC P3 可自訂點）：標案清單 11 欄、搜尋條件清單 7 欄、搜尋條件與排程兩張表單、8 個按鈕、1 組條件列操作；核心欄位＝標註、機關、案號、標案名稱、預算、條件名稱、關鍵字、狀態、抓取／寄信時段。本模組沒有匯出與輸出版型（寫空清單）

## 1.1.0 — 2026-09-26
- 新增：三種通知信在模組載入時登記信件類型（標案雷達新標案＝業務；無法連線來源網站、來源網站格式異動＝系統技術，預設只寄超級管理員）
- 修改：通知信主旨改為【MOTRIX 系統通知】分類－事由，內文依事由、影響、建議處理、發送時間與來源；用語正式化
- module.json `pages[].menu`：選單項改由模組自己宣告（階段 C／C3，core.menu；群組 business、order 20＝業務開發與地圖之間）；模組沒載入 ⇒ 選單不出現

## 1.0.1 — 2026-09-25
- module.json 新增 `license_key: tender_radar`（CORE-SPEC §9c ② 模組授權；授權金鑰的 modules 清單寫這個值）

## 1.0.0 — 2026-09-25
- 模組化：自 `routers/tender_radar.py`、`helpers/tender_source.py`、`helpers/tender_match.py` 搬入 `modules/tender_radar/`（a150e52a）
- 三支通知信自 `helpers/email_notify.py` 移入 `notify.py`（967fe6b1）
- V9 之前的歷史見 `docs/quick/changelog*.md`（標案雷達自 2026-09-21 起）
