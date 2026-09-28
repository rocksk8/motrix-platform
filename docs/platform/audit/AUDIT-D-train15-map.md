# 稽核：第十五班 地圖修正包——B geo-warm-fix 33d39734、A google-basemap b870d8d1（D，2026-09-28）

> 依據：CORE-SPEC 裁示表「地圖底圖與 Google 條款」「地圖修正包（第十五班）」；Google Maps Platform SST §6.2 逐字：
> 「Customer must not use Google Maps Content from the Geocoding API in conjunction with a non-Google map」。
> 範圍：
> - B：`d7008526...33d39734`
> - A：`origin/platform...b870d8d1`（主持給的是 2317cb2e；origin 已前進到 b870d8d1，多了「預熱入口在非 Google 底圖時整輪只用免費來源」）
>
> 做法：只讀碼；在拋棄式樹上跑探針，並把兩包合併驗整合。暫存與拋棄式樹都已清掉。

## 0. 結論

- **必修 2**：
  - SST-M1（A，§6.2 外流）
  - GEO-M1（A＋B 整合後，背景預熱又在三筆查無就停）
- 建議 0、觀察 2。
- B 本身三個重點（負快取 7 天、contextvar 範圍、停止條件）成立；A 的 `/api/map/points` 本體成立。

## 1. 必修

**SST-M1（必修，A）　公司據點的座標在 §6.2 範圍外取得並永久存入，之後以「人工座標」畫在 OSM 底圖上**
- 路徑：
  1. 公司資料 PUT（routers/system.py:1403）呼叫 `_fill_location_coords`（:1139）
  2. 它在 `without_google_content()` 範圍**之外**呼叫 `geo.locate_cached(address)`，有金鑰時 Google 階照走
  3. 查到的座標寫進 `company_profile.locations[].lat/lon`，第一個據點再導出 `office_lat／office_lon`（:1410）
  4. 開地圖時，`geo._locate_locations` 把存下來的 lat/lon 當人工座標，走 `locate(address, manual_coord)`（geo.py:1369-1370），不看原本的來源
  5. ⇒ 在 OSM 範圍內照樣畫出據點，而距離（據點 → 標案／客戶）也用它算
- 探針（拋棄式樹 b870d8d1；替換 `_cached_stage` 讓 Google 階回 (24.2, 120.5)、`_google_key_configured` 回 True）：
  - `_fill_location_coords` 之後 ⇒ lat/lon＝(24.2, 120.5)
  - 在 `without_google_content()` 內 `_locate_locations(..., budget=0)` ⇒ 座標 (24.2, 120.5)，來源 `manual`
- 影響：
  - §6.2：OSM 底圖上的據點與所有距離可以是 Google 定位的結果
  - 另外，這份座標跟著 company_profile 永久存放、進每日備份；`MP0c` 清 Google 快取時清不到它（快取存放期限的條款也管不到這一份）
- 修法：
  - 存檔時的定位也要照底圖決定範圍：非 Google 底圖 ⇒ 包在 `without_google_content()` 內
  - 或存座標時一併存來源，Google 來源不寫進 profile、也不當人工座標
  - 補題：有金鑰、Google 階有結果、OSM 底圖 ⇒ 存檔後 profile 沒有 Google 座標；/api/map/points 的據點與距離不是 Google 座標（反向控制：Google 底圖時照舊）
  - **既有資料**：正式機的據點座標可能已經是 Google 來源（MOTRIX_GEO=1、金鑰可用）⇒ 上線時要有一次性的檢查或清除（例：與 geocode_cache 的 Google 階比對，相同就視為 Google 來源），並且讓使用者看得到

**GEO-M1（必修，A＋B 整合）　合併之後，背景預熱在 OSM 底圖時又回到「三筆查無就停」**
- 兩邊各自成立、合在一起不成立：
  - A：非 Google 底圖 ⇒ 預熱整輪在 `without_google_content()` 內；`locate_cached` 跳過 Google 階時「**不記負快取**」（skipped_google）
  - B：預熱把「查無」判成「不算失敗」的條件，是 `geocode_missed_recently(address)`，也就是**負快取有寫入**
  - ⇒ OSM 底圖（目前一律如此）下，免費來源乾淨地查無 ⇒ 沒有負快取 ⇒ 不算 miss；Google 沒有 err ⇒ 不走「只有 Google 失敗」那一支 ⇒ 落進 `failures`，連續三筆就停
- 重現：拋棄式合併樹（origin/platform＋b870d8d1＋33d39734；geo.py 四處衝突兩邊都保留，外殼＝B 的 skip token 包住 A 的範圍判斷）。四個題檔 52 題中：
  - `test_misses_do_not_stop_the_warmer_and_the_hit_is_found` **紅**（`asked` 只有 3 筆：待定位機關0～2）
  - `test_reverse_control_a_miss_between_failures_resets_the_streak` **紅**
  - 其餘 50 過
- 修法：
  - 預熱的「查無」判定不要依賴負快取：改成「本次**實際查了**的階都乾淨地查無」——例如由 `locate_cached` 回報 `clean_miss` 旗標，或預熱看 `_LAST_STAGE_ERRORS` 沒有免費階的 err，而且結果沒有座標
  - 或者：跳過 Google 時仍記負快取，但帶上「查過哪些階」，Google 底圖時不採用它
  - 兩包誰後合回，誰就在合併樹上讓這兩題綠

## 2. B（33d39734）逐項

| 主持重點 | 讀碼 | 判定 |
|---|---|---|
| 查無不再進 errors ⇒ 負快取真正寫入 | `_locate_nominatim` 只在 err≠「查無此地址」時進 errors；Google 回 `ZERO_RESULTS` 是乾淨的查無；`REQUEST_DENIED`／`OVER_QUERY_LIMIT`／`INVALID_REQUEST`／`UNKNOWN_ERROR`、回應看不懂 ⇒ 進 errors（不記負快取） | 成立（單獨時；整合見 GEO-M1） |
| 負快取 7 天的代價 | 鍵是地址字串：使用者改地址 ⇒ 新鍵，立刻重查；要當下定位的，有人工座標可以蓋過。代價只落在「對方資料 7 天內才補上」的地址——少數，而且地圖另外把它計成「查不到」（去改地址），不會混成「來不及」 | 合理 |
| contextvar 會不會外漏到使用者請求 | `_WARM_SKIP_GOOGLE` 只在 `warm_geocode_cache` 內 set，finally reset；預熱在自己的執行緒（新 context）。`_LAST_STAGE_ERRORS` 在 `locate_cached` 開頭 set，使用者請求在 threadpool 各自的 context copy 裡，互不相見 | 不外漏 |
| 停止條件 | 免費來源連續 3 次沒查成功 ⇒ 停；查無歸零；只有 Google 失敗、免費乾淨 ⇒ 不算；Google 連續 3 次失敗 ⇒ 本輪跳過 Google、免費繼續 | 成立 |
| 額度 0 的可見性 | `disabledByZero`（明填 0，不是用完、不會自動恢復）另列；None＝沒填，不是 0 | 成立 |

## 3. A（b870d8d1）逐項

| 主持重點 | 讀碼 | 判定 |
|---|---|---|
| `without_google_content()` 範圍 | contextvar，set／reset 在同一個 with；`_stage_allowed`、`cached_only`、`locate_cached` 三處都看它 ⇒ 快取讀取與對外查詢都跳過 Google | 成立 |
| /api/map/points 整段在範圍內 | `_build_points` 整段包在範圍內（點、據點、距離） | 成立；但據點的座標有一條存檔路徑在範圍外，見 SST-M1 |
| googleOnlyHidden | 快取只有 Google 座標的，不畫、另計，不混進「來不及」與「查不到」 | 成立 |
| 回應快取鍵含底圖 | `key` 加上 `google_basemap()` | 成立 |
| 預熱入口（b870d8d1） | 非 Google 底圖 ⇒ 整輪在範圍內；只有 Google 座標的地址會重新成為待辦、由免費來源補 | 成立（整合見 GEO-M1） |
| 其他呼叫定位的端點 | grep `geo.locate*`／`cached_only` 等：除了 map_points，只有 system.py 的 `_fill_location_coords`（SST-M1）；tender_radar 模組不直接定位；google-quota 端點不回座標 | 見 SST-M1 |

## 4. 觀察

- **MAP-O1**：`google_basemap()` 目前寫死回 False；②(b) 上線時「只改這一支」。屆時 SST-M1 的修法（存檔範圍依底圖決定）也要跟著走同一支，不要另寫判斷
- **MAP-O2**：`has_google_coord` 刻意不受範圍影響（用來計數被擋下的）。日後不可以把它拿去當座標來源，建議在 docstring 補一句「只回真假、不回座標」的限制

## 5. 複核（D，2026-09-28）

### SST-M1：wip/a-google-basemap 33386b56＋3587fe41

- 修正內容：
  - 存檔時的自動定位：非 Google 底圖 ⇒ 在 `without_google_content()` 內；Google 來源的座標在任何底圖都不寫進 profile
  - 記 `coord_source`／`coord_precision`，由後端推導：新填或改過＝manual；原樣送回＝沿用上次的來源，不信前端
  - `_locate_locations` 只把 manual 當人工座標；免費來源照它的來源回報；coord_source=google 不當座標
  - 沒有來源的既有資料＝手填：這是使用者裁示，依據是正式機 geocode_usage 為 0
- 探針（拋棄式樹 3587fe41；Google 階回 (24.2, 120.5)，有金鑰）：
  - 存檔後 lat／lon／coord_source 全是 None ⇒ Google 座標沒有寫進去
  - coord_source=google 的據點在 OSM 範圍內 ⇒ 不畫
- 題 test_map_sst62 13 過

### GEO-M1：wip/b-geo-warm-fix d973524c（33d39734 → ea5fbf25 → d973524c）

- 修正內容：
  - 新增 `_MISS_CACHE_FREE`（scope=free）；範圍內跳過 Google 時記 free，而不是什麼都不記
  - 預熱的查無判定改看本輪 `_LAST_STAGE_ERRORS`（免費階與 Google 階都沒有 err，而且有結果），不再依賴負快取
- 驗法：拋棄式合併樹（origin/platform dee64c54＋A 3587fe41＋B d973524c；geo.py 用主持的 `geo.py.resolved`）
  - resolved 裡沒有 A 的 `elif skipped_google` 那一支（讀碼確認，已換成 scope=free）
  - 定位與地圖九個題檔 161 過（含第一輪抓紅的兩題）
- 突變（合併樹）：
  - G1「查無判定改回依賴負快取」⇒ 紅
  - G2「免費階有錯也算查無」⇒ 4 紅

### 🔴 列車注意（T15-C1）：`D:\MOTRIX-DRILLS\handoff\b-geo-merge\geo.py.resolved` 過期，不可以直接用

- 它做在 A 的 33386b56 **之前**：整個檔沒有 `coord_source`（A 的 3587fe41 版 geo.py 有 3 處）
- 直接用它 ⇒ SST-M1 讀取端（`_locate_locations` 只把 manual 當人工座標）被靜默撤回
- 在合併樹上實測，A 的兩題紅：
  - `test_auto_filled_coords_resent_unchanged_keep_their_source`
  - `test_legacy_coords_without_source_are_treated_as_manual`
- 把 A 在 geo.py 的差異（`git diff b870d8d1 3587fe41 -- backend/helpers/geo.py`）套在 resolved 之上 ⇒ 乾淨套上，161 題全過
- **列車用的 geo.py 必須同時有 coord_source（A）與 scope=free（B）**；合回後以上面那九個題檔確認
- 另外，本機 git rerere 記著 D 第一輪的解法（「Resolved using previous resolution」）。列車合 geo.py 時要看清楚，不要讓 rerere 自動套上

### 關閉紀錄（標準格式，PLAYBOOK §E-6）

- ✅ SST-M1 關閉（3587fe41）——存檔自動定位受底圖規則約束、Google 來源不寫進 profile、只有 manual 當人工座標
- ✅ GEO-M1 關閉（d973524c）——預熱查無判定看本輪各階錯誤、不依賴負快取；範圍內記 scope=free 負快取

## 6. 第二次複核：③、T15-C1 新 resolved、A ②(b) 第一段（D，2026-09-28）

### ③ B 4115c6e4（負快取依「Google 有沒有實際回答」分兩種）

- `_MISS_CACHE`＝任何查無；`_MISS_CACHE_ALL`＝Google 實際回了查無。`_google_askable()`（有金鑰，而且 `_stage_allowed`：額度、SST 範圍、本輪跳過都在裡面）⇒ 問得到時只看 ALL，問不到時看任何查無
- `google_answered` 只在 Google 階真的被放行並執行、而且沒有新增 Google 錯誤時才成立（讀碼：跳過的階在 `_stage_allowed` 就 continue 了）⇒ 沒金鑰、額度用完、範圍外、本輪跳過時的查無，都不會擋住日後的 Google
- `_MISS_CACHE_FREE` 已移除（resolved 裡 grep 0 筆）
- **成立**

### T15-C1：新 resolved（sha256 3745e9f5…e112，與主持給的一致）

- 合併樹：origin/platform dee64c54＋3587fe41＋4115c6e4，rerere 關閉，geo.py 用新 resolved，再套 `test_map_sst62.adjust.diff`
- 檢查：
  - coord_source 3 處在（A 的 SST-M1 讀取端）
  - 沒有 `_MISS_CACHE_FREE`，也沒有 `skipped_google`
- 定位與地圖九個題檔 **164 過**
- 突變「查無一律記 all」⇒ 5 紅
- **成立**。⚠ 這份 resolved 不含 A 的 21ef7ef1（②(b) 第一段也改了 geo.py：`google_basemap()`、瀏覽器金鑰、`USAGE_SKU_DYNAMIC_MAPS`）⇒ 三段同包合回時，要再以同樣的方法重做一次、重驗

### A 21ef7ef1（②(b) 第一段：瀏覽器金鑰、/api/map/config、地圖頁 CSP）

**GB-M1（必修，隨三段同包處理）　`google_basemap()` 只看瀏覽器金鑰，與使用者裁示「瀏覽器金鑰＋地圖 ID 都填才切 Google 底圖，缺一項維持 OSM、不用 Google 內容」不符**
- 證據：`google_basemap()` 回 `bool(google_browser_key())`（geo.py，21ef7ef1）
- 這一支同時決定兩件事：
  - `/api/map/points`、背景預熱、據點存檔要不要擋 Google 座標
  - `/api/map/config` 回不回 google
- ⇒ 只填了瀏覽器金鑰、沒填地圖 ID 時，後端會放行 Google 座標並回 `basemap: google`。而依裁示，地圖此時應維持 OSM ⇒ Google 座標畫在 OSM 上（§6.2），正是這一班要防的事
- 修法：`google_basemap()`＝兩者都填（地圖 ID 由同一支讀取）；`/api/map/config` 也經這一支，google 時一併回 mapId。補題：只有金鑰、只有地圖 ID、兩者都有，三種情況各自對應的底圖與座標規則

**GB-C1（第二、三段的上線條件）　前端退回 OSM 時不可以沿用 Google 座標**
- 底圖由伺服器判定，而地圖實際在瀏覽器載入：Maps JavaScript API 載入失敗時（金鑰被 referrer 限制、網路、額度），map.html 若退回 OSM，就會把已經以 `basemap=google` 拿到的點（可能是 Google 座標）畫在 OSM 上
- 要求：
  - Google 載入失敗時，不顯示點，並說明原因
  - 或者以 osm 範圍重新取點——後端要提供明確的參數，而且這個參數只能收窄、不能放寬

**其餘成立**：
- 瀏覽器金鑰與伺服器金鑰分開；兩者都遮蔽、都不寫進稽核的值
- `/api/map/config` 只回瀏覽器那一把（有題）
- 地圖頁專用 CSP 取自 Google 官方 Allowlist 範例，只套在 `/pages/map.html`，其他頁不變。它帶 `'unsafe-eval'`，屬於官方範例的一部分，限縮在單一頁可以接受
- 開地圖次數當成 Dynamic Maps 用量的近似值，並明說以 Cloud Console 為準

### 關閉紀錄（標準格式，PLAYBOOK §E-6）

（③ 與 T15-C1 不是必修，不需要關閉行；GB-M1 仍開著，登記：owner A，wip/a-google-basemap）

## 7. 複核 A ②(b) 第二、三段：wip/a-google-basemap b54f7f25（6ef38cca、437add7a、b54f7f25）（D，2026-09-28）

| 項目 | 驗法 | 結果 |
|---|---|---|
| GB-M1 | `google_basemap()`＝`bool(google_browser_key() and google_map_id())`；`/api/map/config` 經同一支，google 時回 mapId；有題「只填金鑰／只填 ID ⇒ osm、不回金鑰」（主持的突變「只看金鑰」⇒ 紅） | **成立** |
| GB-C1 第一條（Google 載不到不退回 OSM） | map.html：`/api/map/config` 失敗 ⇒ 不畫（不退回 Leaflet）；`_loadGoogle` 的腳本載不到、Maps API 載不到 ⇒ catch ⇒ `loadError`，不載 Leaflet；`gm_authFailure` 會說明原因 | 成立 |
| ① 伺服器金鑰不外露 | `/api/map/config` 只回 `google_browser_key()`；兩把金鑰在設定 GET 都遮蔽，也都不寫進稽核的值；頁面 HTML 不嵌任何金鑰；`_locate_google` 的錯誤字串是 `str(exc)`（HTTPError／URLError 不含網址，address 有 urlencode）| 成立；觀察見 GB-O1 |
| ② Google 底圖時不發 OSM 請求 | Google 模式只走 `_loadGoogle`，不載 Leaflet ⇒ 不會請求 OSM 圖磚；OSM 出處只在非 Google 時顯示 | 成立；授權標示見 GB-S1 |
| ③ vendor 來源 | 由 D 獨立下載 npm 官方 tarball：sha512 等於 registry 公布的 integrity；解出來的 `package/dist/index.min.js` 與 repo 的 `markerclusterer.min.js` **位元組相同**（sha256 e4261b90…82ff）；LICENSE sha256 cfc7749b…3d30 與 PROVENANCE 相同 | 成立 |
| 題 | test_map_google_basemap＋test_map_sst62 共 25 過（非 e2e，拋棄式樹） | — |

**GB-M2（必修）　GB-C1 第二條沒有做到：頁面以 OSM 開著時，之後取點可能拿到 Google 座標並畫在 OSM 上**
- 底圖在開頁時只問一次（`/api/map/config` ⇒ `this.basemap`）；之後每次取點（`/api/map/points?sources=…`，切換圖層、重新整理都會打）都**沒有帶上頁面自己的底圖**，而後端每次重新判定 `google_basemap()`
- 情境：使用者 A 的地圖頁以 OSM 開著；管理員在設定頁填好瀏覽器金鑰＋地圖 ID ⇒ A 下一次取點時，後端判定 google、回 Google 座標 ⇒ A 的頁面照樣用 Leaflet 畫在 OSM 上（§6.2）
- 回應裡其實帶了 `"basemap": "google"`，但前端沒有拿它與 `this.basemap` 比對（grep map.html：`basemap` 只出現在 config 那一段）
- 修法（建議兩個都做）：
  - ① 取點時帶 `basemap=<頁面的底圖>`；後端只准收窄——頁面說 osm ⇒ 一律 `without_google_content()`，即使設定已經是 google；說 google 而設定不是 ⇒ 照設定的 osm
  - ② 前端比對回應的 `basemap` 與 `this.basemap`，不同就不畫，並提示「地圖設定已變更，請重新整理」
  - 補題：頁面 osm＋設定 google ⇒ 回的點沒有 Google 座標（反向控制：頁面 google＋設定 google ⇒ 照舊）
- 發生機率不高（要剛好在切換設定時有人開著地圖），但在設定上線當天正好會發生，而這正是本班要擋的條款違規

**GB-S1（建議）　Google 底圖上的免費來源座標要標 OpenStreetMap 出處**
- Google 模式把 OSM 出處藏起來了，但點的座標仍可能來自 Nominatim（`cached_only` 依序退到免費階）
- Nominatim 使用政策與 ODbL 都要求標示「© OpenStreetMap contributors」
- Google 條款限制的是「Google 內容配非 Google 地圖」，不限制在 Google 地圖上放第三方資料
- 建議：有任何點來自 Nominatim 時，圖面下方保留一行資料出處（不蓋住 Google 的標誌與歸屬）。要不要做、怎麼寫，屬於授權與畫面的決定，由主持／使用者裁示

**GB-O1（觀察）**：`_locate_google` 把 `str(exc)` 放進 errors，而 `googleSkipReason`（預熱狀態）會顯示在畫面上。目前的例外字串不含網址，但日後換 HTTP 函式庫（例如 requests 的例外會帶 URL，而 URL 裡有 `key=`）就會把伺服器金鑰帶到畫面。建議在放進 errors 之前，把金鑰字串遮掉（一行）

### 關閉紀錄（標準格式，PLAYBOOK §E-6）

- ✅ GB-M1 關閉（b54f7f25）——google_basemap＝瀏覽器金鑰且地圖 ID，缺一項 osm 且不回金鑰

## 8. 複核 GB-M2（＋GB-S1、GB-O1）：wip/a-google-basemap 8b7e04d3（D，2026-09-28）

- **GB-M2**：
  - 後端：`/api/map/points` 收 `basemap`，`google_map = google_basemap() and basemap != "osm"` ⇒ 只准收窄。範圍（`without_google_content`）與回應快取鍵都用收窄後的值；回應的 `basemap`＝實際採用的底圖
  - 前端：開頁先取設定，取不到維持 osm；取點帶 `&basemap=<頁面底圖>`；回應的底圖與頁面不同 ⇒ 不畫，並提示重新整理
  - 題 30 過（非 e2e）。突變：
    - M1「忽略頁面底圖」⇒ 1 紅
    - M2「頁面可以放寬」⇒ 2 紅
  - **成立**
- **GB-S1**：畫面上的點或據點有 `nominatim`／`nominatim_district` 來源時，兩種底圖都顯示「地點資料 © OpenStreetMap contributors」，放在圖面下方。已確認 points 與 locations 的回應都帶 `source` 欄位（map_points.py:241／306／372、:825）。成立
- **GB-O1**：Google 錯誤字串放進 errors 之前，先把伺服器金鑰取代成 `***`（取代之前已確認金鑰不是空字串）。成立

### 關閉紀錄（標準格式，PLAYBOOK §E-6）

- ✅ GB-M2 關閉（8b7e04d3）——取點帶頁面底圖、後端只准收窄、前端比對不同就不畫
