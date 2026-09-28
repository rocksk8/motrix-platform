# 稽核：E2 附近旅宿實作（wip/e-lodging-impl：第一、二段 2e44395d；全段 7760dcf3，lodging 1.1.0）（D，2026-09-28）

> 範圍：`backend/modules/lodging/**`、INTEGRATION-POINTS、modules.json。依據 LODGING-NEARBY.md（D 審過的設計 6af9466e）。
> 題目與突變在拋棄式樹跑，暫存已清。

## 0. 結論

- **必修 0、建議 3、觀察 3。**
- 模組題 66 過（D 重跑）。突變 6 個：

| 突變 | 結果 |
|---|---|
| L1 不檢查速率 | 紅 |
| L2 非建立者也看得到紀錄 | 紅 |
| L3 CSV 拿掉顯名列 | 紅 |
| L4 地址定位不包 SST 範圍 | 紅 |
| L5 開關關著也下載 | 5 紅 |
| L6 zip 不擋 `..` | 存活，見 E2-O1 |

- 已知紅 3（T1 表沒進每日 JSON）：依主持裁示，等「宣告式自動併入」在第十七班之後處理，**不算在本包**

## 1. 主持指定

**下載的對外連線是否真的只有手動觸發**：成立。
- `fetch_raw` 只在 `refresh()` 被呼叫；`refresh()` 只由 `POST /api/lodging/refresh`（最高管理者）呼叫（grep）
- ModuleSpec 沒有 `schedulers`；startup_notice 只讀開關；沒有 Timer 或 Thread
- 開關預設關（`== "1"`）、demo 模式拒絕、24 小時／1 小時冷卻、非阻塞鎖、狀態寫進設定（計數有落點）、稽核有記
- 失敗 ⇒ 舊快照不動；沒有快照 ⇒ `available=False, reason=no_catalog`，不是 0 筆

**records 的 404 與 export 的權限一致**：成立。
- list、detail、export、compare、delete 都經 `_get_record` → `_can_see`（admin+ 或 `created_by == username`），用的是同一組欄位（§G5 #13）
- 看不到與不存在都是「查無此紀錄」404
- export 先驗 format（422）再驗身分：422 與記錄存不存在無關，不會洩漏存在與否

**顯名在匯出檔內**：成立。
- CSV 第一列「資料來源, <顯名全文>」；JSON 頂層有 `attribution`
- 列表、詳情、比較、查詢、status 都帶顯名；年份依各批的 `dataset_updated_at`
- 突變 L3（拿掉 CSV 那一列）⇒ 紅

## 2. 建議

- **E2-S1　下載要有總時限**：`urlopen(timeout=60)` 是每一次 socket 操作的逾時，不是總時限。對方以每 59 秒一個位元組的方式慢慢送，就能讓下載遠超過 60 秒，而且期間一直握著 `_REFRESH_LOCK` ⇒ 所有人按「更新」都只得到「更新中」。〈長時間沒有輸出的動作要有死線〉。建議在 `fetch_raw` 的讀取迴圈裡檢查經過時間，超過（例如 120 秒）就丟 SourceError
- **E2-S2　CSV 公式注入**：匯出的名稱、地址來自官方資料，以 `=`、`+`、`-`、`@` 開頭的字串在 Excel 會被當成公式。官方資料機率低，但這是對外的匯出檔 ⇒ 開頭是這些字元的欄位，前面加 `'`（或整欄以文字格式輸出）
- **E2-S3　「查詢 0 次對外連線」的範圍要寫清楚**：
  - 旅宿資料本身只查本機快照 ✔
  - 但「輸入地址」在定位快取沒命中時，會經 L1 `geo.locate_cached` 即時問 Nominatim。受 `MOTRIX_GEO` 控制、經 `_throttle()` 節流，屬於 L1 的定位，不是本模組的連線，可以接受；而且依過渡規則，一律在 `without_google_content()` 內（突變 L4 紅）
  - 設計與 README 的「查詢不連線」要改寫成「旅宿資料不連線；地址定位依 L1 規則」，守門也要寫明它量的是模組自己的連線

## 3. 觀察

- **E2-O1**：突變 L6（`_BAD_NAME` 拿掉 `..`）存活，因為這種檔名也不在白名單裡，由白名單擋下 ⇒ 屬於多一層的保護，行為仍然正確。要讓 `_BAD_NAME` 自己有題，可以測一個「白名單放寬之後」的單元情境。不必要
- **E2-O2**：D 第一次用 `-n 2` 跑突變 L1 時卡住（超過 10 分鐘沒有結束）；改成不用 xdist、每個突變設 240 秒死線之後，L1 正常變紅。判斷是這台機器上 xdist 的環境問題，不是題目；記錄備查
- **E2-O3**：`admin` 在列表看得到所有人的查詢紀錄（含中心點地址文字）＝D 審 Q4 的預設（建立者＋admin+），與設計一致

---

## 4. E2 全段（wip/e-lodging-impl 7760dcf3，lodging 1.1.0、CORE 1.65 暫號）

> 範圍：2043c5e4、e1ef554e、7760dcf3（c0b48473 之後 E 自己的差異）＋66d823a7 第三段。基底含 3e061d6f（祖先確認）。
> 拋棄式 worktree（detached 7760dcf3）跑題與突變，`-p no:xdist`、每個突變 300 秒死線；暫存已清，還原後 status 乾淨。

### 4.0 結論

- **必修 0、建議 3、觀察 3。**
- 相關題 92 過（覆蓋層契約、map_request_scope、宣告式備份、read_session、lodging records）；`test_system_audit` 24 過——§0 的「已知紅 3（T1 沒進每日 JSON）」已由宣告式併入轉綠。
- 突變 8 個：

| 突變 | 結果 |
|---|---|
| M1 `script_path` 只比模組、不比宣告的檔名 | 紅 |
| M2 `_file_of` 拿掉「必須在 pages/ 目錄」 | 存活，見 E3-O1 |
| M3 宣告的 script 不驗格式 | 4 紅 |
| M4 T2 也自動匯出 | 紅 |
| M5 表名不驗 | 紅 |
| M6 未載入模組的表也列 | 紅 |
| M7 亂值（含空字串）不收窄 | 7 紅 |
| M8 `missing=osm` 失效 | 3 紅 |

### 4.1 主持指定

**① T2 不自動併入、記 ERROR（偏離原裁示）：同意 E 的作法；不會每天告警，也不會被當成失敗。**
- ERROR 只是 `logger.error`。告警走的是明確的告警呼叫（main.py 啟動檢查那條 `level="ERROR"`：寄信、BACKUP_ALERT、audit），**沒有任何 handler 或工具把 log 的 ERROR 行轉成告警**（grep `addHandler`／`levelno` 在產品碼 0 筆）
- 每日備份的成敗看的是表匯出結果（`daily_partial`）。T2 表**不進** `_daily_backup_tables()` ⇒ 也不進 `expected_tables` ⇒ 兩邊同源、不會少一張、不會誤報 partial
- 現況**沒有任何模組宣告 T2**（grep module.json 0 筆）⇒ 這條 ERROR 目前不會出現
- 偏離的理由成立：T2 含祕密欄位，`SELECT *` 會把祕密寫進雲端同步的 JSON。原裁示「T1／T2 都併入」若照做，要逐欄排除，L1 做不到自動化
- 代價：宣告 T2 的表**不在 JSON 層**（仍在整庫備份那一層），而唯一的訊號是 log。見 E3-S1

**② `/map-overlays/<模組>/<檔>` 不需登入：成立，無必修。**
- 只取得到宣告的檔：`script_path` 走 `declared_overlays()`（只列**已載入**模組），要求模組 key 與完整 scriptUrl 都相等（突變 M1 紅）
- 無路徑穿越：路由參數 `{script}` 不含 `/`；宣告的檔名受 `^[a-z0-9][a-z0-9-]*\.js$` 限制（M3 紅）；另有 realpath 後 dirname 必須等於 `modules/<key>/pages`（M2 存活，見 E3-O1）；題目有 `..%2Fmodule.json`、未宣告檔、未載入模組都是 404
- 不列目錄：只有單一檔路由，沒有 index；不存在一律同一個 404
- 公開端點清單不用動：`auth_middleware`／授權 middleware 都是「非 `/api/` 一律放行」，`_PUBLIC_API_PATHS` 只管 `/api/` 底下。新路由不在 `/api/` 下，跟 `/pages/…`、`/static/sidebar.js` 同一類；**清單沒被改到**（main.py 差異只有這條路由＋註解）。`/api/map/overlays` 照常要登入（`_require_user`）
- 內容是程式碼、不含資料；資料仍經 `/api/lodging/*` 各自驗權限
- 缺的是「非 /api 路由」這一類本身沒有守門，見 E3-S2

**③ Google 底圖物件 raw 化：全在 L1，成立。**
- `map-overlay.js`：地圖一律經 `raw(_comp._map)` 取出；覆蓋層建的 Google 物件（InfoWindow、AdvancedMarkerElement、MarkerClusterer、Circle）都經 `keepRaw`（`__v_skip`）；交給 Google 的座標都是新建的純物件（`Number()`），`content` 是 L1 建的 DOM
- 物件只存在閉包的 `st.handles`；交給覆蓋層的是不透明字串 handle ⇒ 覆蓋層的 Alpine 狀態裡不會出現地圖物件
- `lodging-overlay.js`：grep `google`／`Alpine`／`_map`／`_comp`／`innerHTML` 0 筆，只用 `api.*`
- `map-google.js` 只多一行：`closeMap` 先 `_mapClosed()`

**其他一併看的**
- `map_request_scope`：None／google／osm 與原本的判斷逐一對照相同；空字串與亂值收窄成 osm（M7 紅）；`missing` 預設 osm（M8 紅）。map_points 用 `setting`、旅宿用 `osm`，與裁示相符
- 宣告式 T1：只收已載入模組、表名正規式、已在寫死清單的不重複（M4～M6 紅）

### 4.2 建議

- **E3-S1　略過的 T2 要進備份結果，不只進 log**：現在唯一的訊號是 `logger.error`，而且每次呼叫 `_daily_backup_tables()` 都會記一次（一輪備份會呼叫好幾次）。建議把「宣告 T2、未匯出」的表名寫進備份摘要（例如 `skipped_t2: [...]`），備份頁看得到；log 改成每輪一次。〈降級之後它還是會動〉：少備一張表而備份仍是「成功」
- **E3-S2　非 /api 的動態路由加一題清單守門**：「非 `/api/` 一律放行」是設計，而現在這類路由有 `/pages/…`、`/map-overlays/…`、`/static/sidebar.js`、`/` 四條，沒有題目列出它們。下一條回傳資料的非 /api 路由會直接變成公開端點。建議一題列出 app 裡所有不在 `/api/` 的路由並比對白名單（新增要一起改白名單＝有人做過決定）
- **E3-S3　覆蓋層就緒回呼沒綁同一次 mount**：`onBasemapReady` 的回呼只檢查 `_active[key]` 有沒有值。地圖還在載入時，按覆蓋層→再按（卸下）→再按（重掛），就緒時舊的回呼也會跑，用的是**第一次 mount 的 api**，畫出的標點記在舊的 handles 裡 ⇒ 之後卸下清不掉。建議回呼比對 `_active[key] === made`（掛上時那一份）。同處：`closeMap()` 經 `_mapClosed()` 卸下全部，但 `overlayOn` 沒有重設，按鈕仍顯示為開著

### 4.3 觀察

- **E3-O1**：M2（拿掉 dirname 檢查）存活：檔名正規式已擋掉分隔符，這層只剩一個作用——擋 `pages/` 裡指向外面的 symlink（realpath 之後 dirname 不同）。模組包有簽章，實際風險低；同 E2-O1，是多一層的保護
- **E3-O2**：`backend/core/CHANGELOG.md` 的 B54「不升版號」那一段在 1.65 上下各出現一次（合併 origin/platform 時重複），列車取號時一併整理
- **E3-O3**：D 自己的操作失誤：18:02 一個 `cd` 失敗後的 `git checkout --detach 7760dcf3` 落在**共用主樹 D:\MOTRIX-PLATFORM**，約 1 分鐘後依 reflog 切回 `platform`（3e061d6f），status 乾淨、沒有檔案被改。這段期間若有人在主樹跑題，看到的是 7760dcf3。之後 worktree 操作一律 `git -C`

## 5. 抽查 E3-S1～S3：wip/e-lodging-impl 487b26f0（D，2026-09-28）

- **結論：三條建議都已採納，沒有新的必修；可排第十八班。**
- 題目 17 過（白名單、宣告式備份、備份表數、覆蓋層 e2e）。D 補突變 3 個全紅：
  - X1 白名單不走進 include 的子 router ⇒ 2 紅
  - X2 彙總檔拿掉 `skipped_t2` ⇒ 紅
  - X3 就緒回呼退回只看 `_active[key]` ⇒ e2e 紅
- E3-S1：`skipped_t2` 是彙總檔的固定欄位（`_daily_backup_summary_header` 每輪呼叫一次，ERROR 也每輪一次），月備份也有。`daily_partial` 的判斷是 `v == "error"`，多一個 list 欄位不影響；「實際寫出幾筆」的固定欄位集合取自 header 本身，不是寫死的數字
- E3-S2：遞迴走 `_IncludedRouter`（逐層帶前綴）＋Mount；正對照（子 router 帶前綴的新路由會亮）、反向控制（過期、理由太短）都有。`/openapi.json`、`/docs`、`/docs/oauth2-redirect`、`/redoc` 標「待主持裁示」、行為沒改＝盤點出來、交給主持決定，不是順手做掉
- E3-S3：`current()` 比對同一次 mount；`addMarkers`／`addCircle` 在已卸下的 api 上回 null；`_mapClosed` 重設 `overlayOn`
