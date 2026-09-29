# AUDIT-D：lodging 1.2.0 旅宿檔案更新（bedd8201）

日期 2026-09-29｜稽核依 8c34f08a：以作者結果為準（1918 過／4 skip、新題 10 過、突變 3/3 紅、ship_tier 第 2 級），只跑探針、突變與有疑慮處。

## 結論：必修 0 項；建議 3 項

## 已驗
| 項目 | 結果 |
|---|---|
| 新題 `test_lodging_daily_2026_09_29.py` | 10 過（自跑） |
| 啟動不阻塞 | `schedule_daily_refresh` 只建 daemon Timer（120 秒）後返回；形狀同 `schedule_tender_scan`；`MOTRIX_DISABLE_SCHEDULERS` 由 loader 閘門管 ✔ |
| 例外後照排 | 重排在 `finally`；題以 `_FakeTimer` 驗 ✔ |
| 開關／展示模式不連線 | `run_daily_refresh` 先擋、`refresh()` 內再擋一次（雙層）✔ |
| 20h vs 24h | 探針：昨 10:00 手動成功、今 03:00 ⇒ 因 17h<20h 不連線，06:00 起可（同日重試不失敗、不記失敗）；昨 03:59 成功、今 03:05 ⇒ 過（防逐日漂移）；手動仍 24h ✔ |
| 失敗冷卻 | 03:05 失敗 ⇒ 下次 04:05（1 小時冷卻仍有效）✔ |
| 多程序 | 成功／失敗時間記在 DB 設定，跨程序仍受間隔限制；`_REFRESH_LOCK` 僅同程序，但間隔擋得住 ✔ |
| 選單 | 選單按項目 perm 過濾，`system` 群組為 L1 既有群組，項目 perm 仍為 `lodging` ✔ |
| 突變（自做 2 個） | ①拿掉 `run_daily_refresh` 的 `is_demo_mode` ⇒ `[demo]` 紅；②`ok.date() < now.date()` 改 `<=` ⇒ 2 紅 ✔（已還原） |
| CORE-SPEC 新裁示列 | 引使用者原話、標明「改到系統內」為主持解讀且可推翻、寫明取代對象 ✔ |
| LODGING-NEARBY §3.5 更正 | 用刪除線保留原文並註明更正時間與原話（符合「更正留著錯的那一列」）✔ |

## 建議（非必修）
### D-lodging-S1 來源長期故障時每小時重試、每小時一行 WARNING
`daily_due` 在「今天未成功」時每次檢查都放行，失敗冷卻僅 1 小時 ⇒ 來源掛一整天最多約 21 次連線與 21 行 warning。對政府來源尚可，但與「告警必須有速率上限」同型；可加「當天失敗 N 次後今天不再試」或 warning 每日只記一次。
### D-lodging-S2 LODGING-NEARBY §（測試計畫）「不自動連線：載入模組…0 次對外連線」
現在載入模組會排 Timer，120 秒後（開關開著時）可能連線。既有題在 120 秒內結束所以綠，但敘述已不精確；建議註明「排程第一輪除外／關閉 `MOTRIX_DISABLE_SCHEDULERS`」。
### D-lodging-S3 殘留舊名
`tests/test_lodging_records_e2e_2026_09_28.py` 檔頭、`test_alpine_double_init` 註解仍稱「附近旅宿紀錄」；CHANGELOG 舊條為歷史、不動。純字面，可下次順手。
