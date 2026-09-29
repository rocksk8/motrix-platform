# AUDIT-D：tender_radar 1.4.0 標案清單快取（164a3881，基底 60520f8f）

日期 2026-09-29｜依 8c34f08a：以作者結果為準（2084 過／4 skip、新題 10、突變 5/5 紅），只跑探針、突變與疑慮處。

## 結論：必修 0 項；建議 3 項

## 重點驗證
| # | 項目 | 結果 |
|---|---|---|
| ① | 快取回應＝即時算 | 對照舊 `list_tenders`：SELECT、排序（先截止日、再命中提前、再標註提前，兩次穩定排序）、標籤、`matchedEmptyReason`（在 watch／q 過濾前定案）、`q` 的 normalize 比對逐段相同；`hay` 以同欄位（name／org／caseNo）預算。**不因使用者而異**：舊端點只做 `_require_radar`、無逐人可見範圍過濾，快取為全域無誤。回傳 `items` 為共用物件，端點只 `list()` 淺複製、不改內容 ✔ |
| ② | 寫入路徑是否漏 bump | 全庫 grep `INSERT／UPDATE／DELETE … tenders／tender_watches`（非測試）共 7 處：`create_watch`／`update_watch`／`delete_watch`／`mark_tender`／`unmark_tender`／`source._store`／`source._fetch_details` ⇒ 前 5 個直接 bump；後 2 個都只在 `run_scan()` 內，`recognised` 時於 commit 後 bump ✔。無標案手動改／連結案件的寫入端；無 `DELETE FROM tenders` 清理。備份還原（archive）與 `map_points` 只讀或走簽章／TTL |
| ② | bump 與簽章的必要性 | 自做突變：拿掉 `update_watch` 的 bump ⇒ `test_every_write_endpoint_bumps` 紅（條件改內容而 `updated_at` 同秒時簽章看不到，證明 bump 不是多餘）；拿掉 `unmark_tender` 的 bump ⇒ 同題紅 ✔（已還原） |
| ② | 競態 | key 含 gen＋簽章；建構中被 bump ⇒ 存入舊 key，下一次請求 key 不符而重建，最壞多算一次，不會回舊資料；兩把鎖分離，`bump()` 不被建構卡住 ✔ |
| ③ | 背景執行緒 | `enable_warm` 只排 20 秒 daemon Timer 後返回，不阻塞啟動；`_warm_once` 先清 pending 再算、例外全接住；重排不靠自身（由 bump 再排），故無「排程靜默死亡」型問題；`MOTRIX_DISABLE_SCHEDULERS` 閘門由 loader 管 ✔ |
| ④ | ship_tier | `python tools/platform/ship_tier.py --prod 60520f8f` ⇒ 「等級 2（模組 tender_radar）」；`docs/platform/modules.json` 只加 `mod:tender_radar/listing` 一列 ✔ |
| 前端 | 去抖／AbortController | 500ms、字沒變不送、`_listSeq` 只採最後一趟（fetch 後與 json 後各驗一次）、AbortError 不當失敗、controller 放 window 避開 Alpine Proxy ✔ |

## 建議（非必修）
### D-tender-S1 標註人改名／刪除最久 5 分鐘才反映
`markedByName` 來自 users，簽章不含 users；CHANGELOG 已載明 TTL 兜底。若要即時：簽章加 `SELECT COUNT(*),MAX(id) FROM users` 不夠（改名不變這兩值），可在改使用者名稱處呼叫 `bump()`，或接受現況。
### D-tender-S2 前端：載入失敗後同字不重送
`loadTenders` 一開始就設 `_lastQ = q`；請求失敗（listError）後使用者再輸入同一字串，`onSearch` 因 `q === _lastQ` 不送，只能改字或重整。建議失敗時把 `_lastQ` 設回 `null`。
### D-tender-S3 標註後立即重取仍會吃到冷算
`bump()` 使快取失效、背景預算延遲 1 秒；若前端在標註後立刻重取清單，請求端仍會自行同步重算（與舊行為同、不是退步）。若要受益，可在 bump 內直接於背景執行緒立即算（delay=0）或前端標註後延遲重取；不影響正確性。

---
## 複核（tender_radar 1.5.0，a084e3e1）— 必修 1 項（測試缺口）；建議 2 項
依 8c34f08a：以作者結果為準（2091 過），只跑探針與突變。新題 17 過（含 S2 e2e）；ship_tier `--prod 60520f8f` ⇒ 等級 2（模組 tender_radar）✔。

### TR-M1 「stale 讀時補排背景重算」是唯一的保底、卻沒有題守
`listing._snapshot` 在「gen 已變、背景預算已啟用」時回舊資料並 `_schedule_warm(0)`。這一行是唯一防止「背景重算失敗一次 ⇒ 永遠回舊資料」的機制：`_warm_once` 先清 `pending` 再算，例外只記錄、**不會自己重排**（例如抓取寫入期間資料庫鎖住導致那一次重算丟例外）。
**自做突變**：把該行改成 `pass` ⇒ 標案新題 17 題全過（未被抓到）。即：現在程式是對的，但之後有人刪掉或改壞它，測試不會紅，而症狀是「使用者永遠看不到新抓的標案」。
**必修**：補一題——`enable_warm` 後 `bump(background=True)`，令第一次 `_rebuild` 丟例外（monkeypatch `_build` 失敗一次）；驗證①這段時間讀取回舊資料、不同步分類 ②下一次讀取會重排（`timers` 可觀測）③重排的那次成功後讀取得到新資料。

### 已驗（無問題）
| 項目 | 結果 |
|---|---|
| stale 會不會被去重吞掉 | `pending` 在 `_warm_once` 開頭就清；建構中再來 bump 會排新的一輪（`_rebuild` 以 gen＋簽章判斷；建構中 gen 變 ⇒ built_gen 不等 ⇒ 下次仍認定過期並補排）；排隊中的 warm 讀的是當下最新 gen ✔ |
| 寫入端同步算的鎖 | 抓取寫入（`run_scan`）走 `bump(background=True)`，不在寫入端算、不持鎖，**不會卡住抓取**。使用者寫入（條件增刪改／標註）在 commit 之後才 bump，與寫入連線無巢狀；`bump()` 先加 gen（`_META` 短鎖）再進 `_LOCK`，若背景重算正在跑則排隊等它、之後因 gen 已變再算一次 ✔ |
| 位元組快取 | `respond` 的序列化參數與 FastAPI 預設一致（`ensure_ascii=False`、緊湊分隔）；快取放在 data 底下，隨重算整份換掉；上限 64 組 ✔ |
| 突變（自做） | `bump()` 一律走背景 ⇒ `test_user_write_rebuilds_in_the_write…` 紅 ✔ |
| 前端 S2 | 失敗（HTTP 非 ok、連線例外）都把 `_lastQ` 設回 null；AbortError 不清（是被新一趟取代）✔ |

### 建議（非必修）
- **TR-S1 使用者寫入的回應時間＝一次完整重算**（含可能先等一輪背景重算再自己算一次，最壞約兩倍）。這是本次裁示（寫入端算完才回），不算缺陷；建議 CHANGELOG 補一行量測值（目前資料量下標註／條件異動要等幾秒），讓使用者預期；若太久，可把「標註」改成只就地更新快取中那一筆的 marked 欄位與提前順序。
- **TR-S2 多程序部署**：`bump()` 只在本程序生效；別的程序只靠簽章。抓取寫入會被簽章看到（讀時同步重算，與「請求端永不同步」有出入），就地改欄位（補詳情的 location／url）與使用者改名則要等該程序自己的下一次 bump。目前若為單程序部署則無影響；請在 listing 說明註明此前提。
