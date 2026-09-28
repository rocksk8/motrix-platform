# @googlemaps/markerclusterer 2.6.2 — 來源與雜湊

地圖 Google 底圖（第十五班 ②(b)，Maps JavaScript API）的重疊點群聚用；Leaflet 底圖照舊用 `leaflet.markercluster-1.5.3`。
規格：主持裁示「markerclusterer vendor 照 PROVENANCE」。

| 項目 | 值 |
|---|---|
| 版本 | @googlemaps/markerclusterer 2.6.2（npm `latest`，2026-09-28 查） |
| 來源 | `https://registry.npmjs.org/@googlemaps/markerclusterer/-/markerclusterer-2.6.2.tgz`（npm 官方 tarball；以 registry 公布的 `sha512-U6uVhq8iWhiIckA89sgRu8OK35mjd6/3CuoZKWakKEf0QmRRWpatlsPb3kqXkoWSmbcZkopRiI4dnW6DQSd7bQ==` 驗過） |
| 取出檔案 | `package/dist/index.min.js` → `markerclusterer.min.js`（套件 `unpkg` 欄位指的就是它；IIFE，全域名 `markerClusterer`）、`package/LICENSE` |
| 下載日期 | 2026-09-28 |
| 授權 | Apache-2.0（`LICENSE`，原樣保留） |

## SHA-256（下載當下的原始位元組）

```
e4261b900608bf4918c6f613041d40150cf86a302a96667f81421716d69682ff  markerclusterer.min.js   48484 bytes
cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30  LICENSE                  11358 bytes
```

驗證：`sha256sum markerclusterer.min.js LICENSE`

## `.gitattributes`

同 leaflet：`frontend/static/vendor/markerclusterer-2.6.2/** -text`（發布檔沒有 CR；規則讓「保存原始位元組」不依賴這個巧合）。

## 沒有抓什麼

| 檔 | 為什麼不抓 |
|---|---|
| `index.umd.js`／`index.dev.js`／`index.esm.mjs` | 未壓縮／模組版，只對除錯或打包工具有用 |
| `*.map`、`*.d.ts` | source map 與型別宣告 |

## 目錄名帶版本號

`/static/vendor/` 一律 `Cache-Control: immutable`，升版一定換目錄名。

## 載入方式

`map.html` 在 Google 底圖時，於 Maps JavaScript API 載入**之後**才載這一支。載不到時照常畫點、只是不群聚。
