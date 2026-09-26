# 稽核：B 的計數／棘輪守門漏掃 modules/（wip/b-scan-modules 64c3a9f6）

> 標準等級（主持指定）。§0 由受稽核方 B 寫（送審說明，主持要求寫明）；§1 起由 D 填寫。

## 0. 送審說明（B，2026-09-26 22:31）

### GW1 範圍歸類（主持裁示 ③，已核可）

新守門 `test_every_mail_sender_is_classified` 首跑找出 3 支未歸類的送信檔，全數歸入 `SCAN_FILES`：

| 檔 | 送什麼 | 收件人 | 目前行內文案（`intro=`／`note=`／`title=` 字面值） |
|---|---|---|---|
| `archive.py` | 備份失敗告警信 | 客戶端超級管理員（`_superadmin_emails`） | 2 |
| `routers/system.py` | 寄信設定的測試信 | 客戶端管理員（`_admin_emails`） | 1 |
| `helpers/geo.py` | 地圖定位額度警戒信 | 客戶端的通知群組（`_group_emails`） | 1 |

- 理由：收件人不是維護者，照本檔頭「寫給誰看的」那條線屬範圍內。主持裁示：歸進來是收緊不是放寬。
- `NOT_SCANNED` 目前為空。主持裁示：日後被抓到的用詞違規**修內容**，不可改放排除清單。
- GW1 本身仍是 xfail（使用者 2026-09-24 裁示：WD1 併入平台化內容層）⇒ 這 4 處併入既有欠帳（email_notify 45 處），`helpers/wording.py` 建立時一起搬；此包不改文案。
- 「送信檔」判準：呼叫 `helpers/email_notify.py` 的 `_send*`／`_async_send*`／`_build_html`（由 AST 算出，新增原語自動納入）或 import smtplib。**射程**：透過 `notify_*` 公開函式送信的呼叫端不算（文案在 email_notify 內，已掃）；自己組 HTML 再交給第三方寄信庫的寫法抓不到。

### 其他請 D 看的點

- ① payroll 題範圍改成 `router_files()`＋`logic_files()`＋`main.py`，正對照是 `modules/payroll/api/bonus.py` 在集合內；擴大後沒有新違規。
- ② `page_files()` 本來就有，沒有新增 L0 介面。`check_double_init` 另外做了兩件主持沒有點名的事：模組 js（`modules/*/js`）納入共用母體；模組頁的 `../static/` 依 `/pages/` 網址解析到 frontend。
- `PAGE_POPULATION=49` 保留，因為它數的是「會跑兩遍的頁」，不是頁面總數；新增一題釘住工具的頁面集合等於 `page_files()`。
- 頁面路徑棘輪：新註解與沙盒原本寫了 `frontend/pages` 字面，首跑轉紅；已改寫。`test_view_filter_marking` 的基線從 1 降到 0，已重產。
- 突變 8 項皆紅（見 commit 訊息）。
