# 給正式機 Claude：標案雷達載入量測（唯讀）

目的：確認「點進標案雷達第一次載入約 7 秒」慢在哪。開發機下一版（第二十二班，tender_radar 1.5.x）已把清單改成伺服器端預先算好；這份量測是**套用新版之前的基準**，請在套用第二十二班更新**之前**做（已套用就照做，並在摘要註明）。

規則：**只讀**——不改任何檔、不重啟服務、不呼叫寫入端點、不 `import main`（會觸發建庫與備份）。Claude 端不要自行登入或取 token 呼叫 API。

## 0. 先確認
- 安裝目錄：`C:\Users\Motrix\Desktop\V9.0`（以實際安裝目錄為準，下面路徑都跟著換）
- 目前版本：讀 `<安裝目錄>\backend\.deployed_commit.json` 的 `commit`，取前 8 碼（回報資料夾名稱要用）

## 1. 資料量（Claude 執行）
資料庫檔＝`<安裝目錄>\backend\motrix_erp.db`（`core/paths.py` 的 `DB_PATH`）。用任一 Python 以**唯讀模式**開：

```python
import sqlite3
c = sqlite3.connect(r"file:C:/Users/Motrix/Desktop/V9.0/backend/motrix_erp.db?mode=ro", uri=True)
print("tenders", c.execute("select count(*) from tenders").fetchone()[0])
print("watches(總數, 啟用)", c.execute("select count(*), coalesce(sum(enabled),0) from tender_watches").fetchone())
print("marked", c.execute("select count(*) from tenders where marked_at is not null").fetchone()[0])
print("hits", c.execute("select count(*) from tender_hits").fetchone()[0])
print("fetch_log 最近 3 筆", c.execute("select * from tender_fetch_log order by rowid desc limit 3").fetchall())
```

## 2. 請求耗時與回應大小（請使用者操作，Claude 記錄）
請使用者在正式機瀏覽器（已登入）：
1. 開標案雷達頁 → F12 → Network → 勾「Disable cache／停用快取」→ 重新整理
2. 點 `/api/tender-radar/tenders` 這一列 → Timing 分頁：記 **Waiting for server response（TTFB）**、**Content Download**；列表上記 **Size**（傳輸大小／實際大小）
3. 記 `/api/tender-radar/status`、`/api/tender-radar/watches` 的 **Time**
4. 記從重新整理到清單出現大約幾秒（體感即可）
5. 在搜尋框輸入一個關鍵字，記新出現的 `tenders?q=` 請求的 **Time**

判讀參考：TTFB 大 ⇒ 伺服器計算慢；Content Download 或 Size 大 ⇒ 傳輸慢；兩者都小但畫面還是慢 ⇒ 瀏覽器畫表慢。

## 3. 同時段有沒有別的東西在忙（Claude 執行）
- 量測時間是否落在標案抓取時段（預設 9／12／15／18 點；抓取會持有寫鎖）
- `<安裝目錄>\backend\logs\server.log` 量測時間前後 5 分鐘的 WARNING／ERROR：只列行數與前 5 行

## 4. 回報
改放 GitHub：寫到 repo 內 `docs/platform/prod-reports/<yyyyMMdd_HHmm>_<commit 前 8 碼>_標案量測/摘要.md`，用 `docs/platform/prod-tasks/tools/tender_radar_measure.py`（不帶 `--report-root` 即預設寫到此處），然後 `git add`、`git commit`、`git push` 到 `main`（或使用者指定的分支），開發機再 pull 讀取。不再寫雲端硬碟。

`摘要.md` 只要：
- 第 0 節：commit 前 8 碼、量測時間、量測時是否已套用第二十二班
- 第 1 節：tenders、watches（總數／啟用）、marked、hits
- 第 2 節：TTFB、Content Download、Size、status／watches 的 Time、體感秒數、`q=` 請求的 Time
- 第 3 節：結論一行

**repo 是版本庫，一旦推上去就留在歷史裡**，所以**不要**附資料庫檔、license.key、任何金鑰或個資（fetch_log 內容只摘要，不整段貼）。
