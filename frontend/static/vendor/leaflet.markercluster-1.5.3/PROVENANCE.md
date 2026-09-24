# Leaflet.markercluster 1.5.3 — 來源與雜湊

地圖 `MP2`（重疊點群聚）用。規格要求「自架於 vendor，照 leaflet 的 PROVENANCE 模式」（`HANDOFF-PENDING-2026-09-23.md`「🟢 MP 地圖優化」）。

| 項目 | 值 |
|---|---|
| 版本 | Leaflet.markercluster 1.5.3（相容 Leaflet 1.x；本 repo 用 1.9.4） |
| 來源 | `https://unpkg.com/leaflet.markercluster@1.5.3/dist/`（官方 npm 發布路徑）；授權檔取自套件根目錄 |
| 下載日期 | 2026-09-24 |
| 授權 | MIT（`MIT-LICENCE.txt`，原樣保留） |

## SHA-256（下載當下的原始位元組）

```
1e4e1d22972a3926f48598e0caf14e3fe7049835d428a344fed4f9e3665b3508  leaflet.markercluster.js    34136 bytes
614dea0a98ff3f4ead74f04918f6b1d1b9ba435c25b5fc23b21a394d1e3e4d87  MarkerCluster.css             872 bytes
61258232d98d64dc2a7b1e02130d67421bc5b9bda5994eef70228ff97570c170  MarkerCluster.Default.css    1287 bytes
3133dacd38250bd1f524d8166cc60a016a382522e062fce143691c65bf5e4b3d  MIT-LICENCE.txt              1052 bytes
```

驗證：`sha256sum leaflet.markercluster.js MarkerCluster.css MarkerCluster.Default.css MIT-LICENCE.txt`

## `.gitattributes`

與 leaflet 同一條理由加了 `frontend/static/vendor/leaflet.markercluster-1.5.3/** -text`：
發布檔目前全是 LF（沒有 CR），正規化不會改到位元組；規則仍加上，讓「保存原始位元組」不依賴這個巧合。

## 沒有抓什麼

| 檔 | 為什麼不抓 |
|---|---|
| `leaflet.markercluster-src.js` | 未壓縮版，只對除錯有用 |
| `*.js.map` | source map，同上 |

## 目錄名帶版本號

`/static/vendor/` 一律回 `Cache-Control: immutable`（一年，`main.py` `no_cache_static`），前提是「升版一定換檔名」。
目錄名不帶版本的話，升版後瀏覽器會繼續用舊檔一年 ⇒ 版本寫在目錄名上。

## 載入方式

`map.html` 的 `_loadLeaflet()` 在 Leaflet 載入**之後**才載這一支（它在載入當下就要讀 `L`）。
這一支載不到時地圖照常畫點，只是不群聚——群聚是顯示輔助，不可以讓整張圖因為它而畫不出來。
