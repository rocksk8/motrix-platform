# 給正式機 Claude：標案雷達載入量測（唯讀）

目的：確認「點進標案雷達第一次載入約 7 秒」慢在哪。**只讀，不改任何檔、不重啟服務、不呼叫寫入端點。**

## 1. 資料量（唯讀 SQLite）
用正式機自己的資料庫檔（路徑取自安裝目錄的設定，不要猜），以唯讀模式開：

```python
import sqlite3
c = sqlite3.connect("file:<資料庫路徑>?mode=ro", uri=True)
print("tenders",        c.execute("select count(*) from tenders").fetchone()[0])
print("watches",        c.execute("select count(*), coalesce(sum(enabled),0) from tender_watches").fetchone())
print("marked",         c.execute("select count(*) from tenders where marked_at is not null").fetchone()[0])
print("hits",           c.execute("select count(*) from tender_hits").fetchone()[0])
print("fetch_log 最近", c.execute("select * from tender_fetch_log order by rowid desc limit 3").fetchall())
```

## 2. 請求耗時與回應大小
請使用者在正式機瀏覽器（已登入）開標案雷達，F12 → Network → 勾「停用快取」→ 重新整理頁面，記下這兩個請求：
- `/api/tender-radar/tenders`：Waiting（TTFB）、Content Download、Size（傳輸／解壓後）
- `/api/tender-radar/status`、`/api/tender-radar/watches`：Time
再在搜尋框輸入一個關鍵字，記下新出現的 `tenders?q=` 請求的 Time。
（Claude 端不要自行登入取 token 呼叫 API。）

## 3. 同時段有沒有別的東西在忙
- 該時段是否落在抓取／寄信時段（標案抓取會持有寫鎖）
- `server.log` 同時段有無 WARNING／ERROR（只列行數與前 5 行）

## 4. 回報
放在 `G:\我的雲端硬碟\MOTRIX-交付\正式機回報\<時間>_<commit8>_標案量測\摘要.md`，內容只要：
tenders／watches／marked 筆數、第 2 節三個數字（時間與大小）、第 3 節結論一行。
**不要**附資料庫、license.key、任何金鑰或個資。
