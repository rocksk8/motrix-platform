# M11 標案雷達（tender_radar）

每天從政府電子採購網抓取公開標案，比對使用者設定的關鍵字與排除詞，命中後每日寄一封彙總信。

## 開關

| 環境變數 | 作用 |
|---|---|
| `MOTRIX_TENDER_RADAR=1` | 開啟對外抓取；沒設就不連外網（排程照排、不做事） |

啟動時只記「開著」的情況：不小心開著而沒人知道，才是安靜的錯。

## 端點

前綴 `/api/tender-radar`，權限 key `tender_radar`（詳細清單見 `api.py`）。

## 資料（依 MODULE-GUIDE §3 分類）

| 名稱 | 類別 | 說明 |
|---|---|---|
| `tenders` | T1 | 抓到的標案 |
| `tender_hits` | T1 | 命中紀錄 |
| `tender_watches` | T1 | 使用者設定的搜尋條件 |
| `tender_fetch_log` | T3 | 抓取紀錄（可重建） |

本模組不擁有任何檔案（F 類）。表由凍結的 V9 migration 建立，本模組還沒有自己的 migration。

## 串接點

| 對象 | 形式 | 對方不在時 |
|---|---|---|
| L1 `helpers.email_notify`（寄信原語） | 模組屬性晚綁定 | L1 一定存在 |
| L1 通知偏好（事件 key：`tender_found`／`tender_fetch_failed`／`tender_source_changed`／`tender_detail_blocked`） | 事件 key 字串 | — |
| M08 地圖（讀取 `tenders` 表） | ⚠ 目前是 M08 直接讀表，改成 provider 已排入路線圖 | 拿掉本模組時，地圖上的標案點消失，其他點照常顯示 |

## 不寄信日與假日表

週六、週日、國定假日不寄信（彙總信與健康告警）；掃描照常。判定在 L1 `helpers/business_days.py`（`calendar_tw.py` 轉出舊名），資料在 `helpers/holidays_tw.json`
（官方政府行政機關辦公日曆表；來源、取得日期、涵蓋範圍、sha256 記在檔內）。**每年要用新一年的官方 CSV 更新**；
表外年份只認得週末，頁面會明說。補班日（週末但要上班）可寄信；官方 2026、2027 沒有補班日。

## 維護清單

- **假日表到期前更新**：`helpers/holidays_tw.json` 目前涵蓋到 2027-12-31。**2027 年中**（最晚到期前 60 天，頁面與每日排程日誌會開始提示）
  取官方 117 年（2028）辦公日曆表 CSV，重轉並更新 `coverage`、`source`（網址、取得日期、sha256）；用「錨點」測試對照新年度的官方列
  （國慶日補假、春節連假），不要憑記憶補日期。

## 拿掉本模組時

伺服器照常啟動；`/api/tender-radar/*` 回 404；系統頁不再列出這個開關；資料表與資料保留。
