# 稽核：正式機 Google 底圖無標點＋取點慢（wip/a-gm-raw fdb3cee0）（D，2026-09-28）

> 起因：正式機 54a2d6b6 在 Google 底圖下，points 201、`_gmMarkers` 202，但 DOM 裡的 `gmp-advanced-marker` 是 0；`Alpine.raw(c._map) !== c._map`。另外取點慢：400 個地址開 404 次連線，冷快取約 2.5 秒。
> 範圍：`origin/platform...fdb3cee0`（10 檔）。只讀碼；非 e2e 題與突變在拋棄式樹跑，已清掉。e2e（假 google.maps 加身分檢查）沒有跑，以主持的「換回 origin 版 ⇒ 4 紅」為準。

## 0. 結論

- **必修 0、建議 2。可以發第十七班。**
- 題：read_session＋google_basemap＋sst62＋warm＋mp8 共 57 過
- 突變：

| 突變 | 結果 |
|---|---|
| R1「範圍內也不用共用連線」 | 2 紅 |
| R2「範圍結束不關連線」 | 存活，見 GM-S2 |

## 1. 主持指定

**cache_read_session 的連線生命週期與執行緒**
- 連線放在 contextvar（`_READ_CONN`），範圍進入時開、finally 還原並關閉；巢狀呼叫沿用外層那一條；只給讀用，寫入（`_remember`、負快取）照舊自己開、自己 commit
- 取點在請求執行緒（threadpool 各自一份複製出來的 context），預熱在 Timer 執行緒（Python 3.12 的新執行緒從空 context 開始）⇒ **不會拿到同一條連線**
- map_points 裡沒有另開執行緒或 executor（grep Thread／executor／asyncio：0）
- 萬一真的被誤用跨執行緒，sqlite 預設的 `check_same_thread` 會直接丟例外，不會靜默共用
- 讀取不會一直看到舊資料：legacy 交易模式下，SELECT 不會開長交易，預熱在另一條連線寫入的新快取，下一次讀取就看得到
- demo 模式：`get_db()` 在範圍開始時依同一個請求的 demo 旗標選庫，與原本逐次開連線的行為相同
- **成立**

**Alpine Proxy（__v_skip）**
- Google 物件（Map、InfoWindow、AdvancedMarker、Circle、群聚）建立後立刻 `keepRaw`（設 `__v_skip`）。@vue/reactivity 看到這個旗標就不包（markRaw 的語意）
- 傳給 Google 的地方一律 `raw(this._map)`（`Alpine.raw`）
- 點擊改用 `gmp-click`＋`gmpClickable`
- **成立**

**__v_skip 要不要也套在 Leaflet 路徑**：見 GM-S1。

## 2. 建議

**GM-S1　Leaflet 物件也標 raw（另開一包，不改行為）**
- Leaflet 目前容忍 Proxy，所以沒有壞；但地圖物件與圖層經 Proxy 存取，每一次屬性讀取都多一層攔截（大量標點時是可以量到的成本）
- `hasLayer`、`removeLayer` 這類以身分比對的 API，拿到 Proxy 與原物件時可能判定不同
- 建議與 Google 版同一個做法，另開一包，附 OSM 路徑的 e2e 回歸（標點數、點擊彈窗、圖層切換），不要夾在這一包的緊急修正裡

**GM-S2　補一題「範圍結束連線已關」**
- 突變 R2（拿掉 finally 裡的 `conn.close()`）存活
- 目前靠 CPython 的參考計數，在 contextvar 還原後回收連線，所以實害小。但這一條才是「共用連線不外洩」的保證，應該由題目釘住：範圍外呼叫該連線 ⇒ `ProgrammingError: Cannot operate on a closed database`

## 3. 其他

- info.* 空值防護 11 處：`(info || {}).x`，只影響顯示，成立
- 版本紀錄改成新條目 28i（28g／28h 已出貨）：與第十六班的判斷一致（版號比的是 commit，不會誤擋）
