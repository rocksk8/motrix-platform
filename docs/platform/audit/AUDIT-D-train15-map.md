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
