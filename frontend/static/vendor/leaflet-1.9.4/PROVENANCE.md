# Leaflet 1.9.4 — 來源與雜湊

**這是本 repo 第一個從網路下載進來的前端相依。** 這份檔案的存在理由：
這些位元組將來會被打包進客戶的機器，而**「它從哪來、有沒有被動過」要現在就可查，事後查不出來。**

| 項目 | 值 |
|---|---|
| 版本 | Leaflet 1.9.4 |
| 來源 | `https://unpkg.com/leaflet@1.9.4/dist/`（官方 npm 發布路徑） |
| 下載日期 | 2026-09-21 |
| 授權 | BSD-2-Clause（見 `leaflet.js` 檔頭的 `@preserve` 區塊） |

## SHA-256（下載當下的原始位元組）

```
db49d009c841f5ca34a888c96511ae936fd9f5533e90d8b2c4d57596f4e5641a  leaflet.js                 147552 bytes
a7837102824184820dfa198d1ebcd109ff6d0ff9a2672a074b9a1b4d147d04c6  leaflet.css                 14806 bytes
574c3a5cca85f4114085b6841596d62f00d7c892c7b03f28cbfa301deb1dc437  images/marker-icon.png       1466 bytes
00179c4c1ee830d3a108412ae0d294f55776cfeb085c60129a39aa6fc4ae2528  images/marker-icon-2x.png    2464 bytes
264f5c640339f042dd729062cfc04c17f8ea0f29882b538e3848ed8f10edb4da  images/marker-shadow.png      618 bytes
```

驗證：`sha256sum leaflet.js leaflet.css images/*.png`

## ⚠️ `.gitattributes` 有一條規則是為了這份雜湊而存在

`frontend/static/vendor/leaflet-1.9.4/** -text`

本 repo `core.autocrlf=true`，而 `.gitattributes` 預設把文字檔正規化成 LF。
`leaflet.css` 發布時是 **CRLF** ⇒ 若讓它被正規化，**checkout 出來的位元組就不是廠商發布的那一份**，
上面那組雜湊會驗不起來。
🔑 **而失敗的樣子是「憑證還在，只是對不上」** —— 比沒有憑證更糟，因為它會讓人以為檔案被竄改了。

## 沒有抓什麼，以及為什麼

| 檔 | 為什麼不抓 |
|---|---|
| `leaflet.js.map` | source map，只對除錯有用，而它讓體積多一倍 |
| `images/layers*.png` | 只有用到圖層控制才需要，我們沒有用 |

## ⚠️ marker 圖一定要一起 vendor

Leaflet 預設會**從 `leaflet.css` 的位置推導** marker icon 的路徑。
沒有把 `images/` 一起帶進來的話，它會去 CDN 抓 ⇒ **那是一條沒有人注意到的對外連線**，
跟圖磚同型。
📌 而我們**明著設 `L.Icon.Default.imagePath`，不依賴推導**——
一個由外部條件維持的不變量，會在那個條件變的時候失效。

## 📌 圖磚不在這裡

底圖圖磚來自 `tile.openstreetmap.org`，**那是執行期的對外連線，vendor 不了**。
所以地圖預設**不載入**：使用者按「開啟地圖」才載。
🔑 那個按鈕本身就是那條連線的開關——**把選擇權放在會承受後果的人手上**。

## 目錄名帶版本號（2026-09-24 改名：`leaflet/` → `leaflet-1.9.4/`）

`/static/vendor/` 一律回 `Cache-Control: immutable`（一年，`main.py` `no_cache_static`），前提是「升版一定換檔名」。
原本目錄叫 `leaflet/`（不帶版本）⇒ 升版後瀏覽器會繼續用舊檔一年，而沒有任何錯誤訊息。
改名只搬目錄，**檔案位元組不變**（上面的雜湊照樣驗得過；`test_vendor_paths_are_versioned` 每次跑都驗）。
守門：`backend/tests/test_vendor_paths_are_versioned_2026_09_24.py`——vendor 底下每一項名稱都要帶版本、前端引用的路徑都要存在。

## 載入方式

`map.html` 的 `_loadLeaflet()` 在使用者按「開啟地圖」時才載入 `leaflet.css`／`leaflet.js`，並明設
`L.Icon.Default.imagePath = '../static/vendor/leaflet-1.9.4/images/'`；markercluster 在它之後載入。
