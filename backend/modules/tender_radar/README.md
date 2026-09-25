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
| L1 通知偏好（事件 key：`tender_found`／`tender_fetch_failed`／`tender_source_changed`） | 事件 key 字串 | — |
| M08 地圖（讀取 `tenders` 表） | ⚠ 目前是 M08 直接讀表，改成 provider 已排入路線圖 | 拿掉本模組時，地圖上的標案點消失，其他點照常顯示 |

## 拿掉本模組時

伺服器照常啟動；`/api/tender-radar/*` 回 404；系統頁不再列出這個開關；資料表與資料保留。
