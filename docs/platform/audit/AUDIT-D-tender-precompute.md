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
