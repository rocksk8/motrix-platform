# 稽核：B 的第十三班守門（wip/b-t13-guards 58830897，四個 commit）（D，2026-09-27 14:52）

> 標準等級。依 §G1 ⓪：先讀 diff 列疑點，只跑針對疑點的突變。四個題檔 38 過。

## 0. 結論

- **必修 1（T13-M1）、建議 2**。B 這包之後停止，必修一次列齊於此。

## 1. 逐項

| # | 內容 | D 的驗證 | 結果 |
|---|---|---|---|
| ① M06-S4 | `KNOWN_STAR_KWARGS` 上限改成「＝」：少於上限也紅，要求同一個 commit 調低 | 讀碼：總數 > 上限、< 上限都列出；題含「刪一筆不調上限 ⇒ 紅」「調低 ⇒ 過」 | **M06-S4 關閉** |
| ② CR-S1 | 逐案 403 掃描器另認 `if not row_access.visible('case', …)` ⇒ 403；反向控制：別的實體的 visible 不算 | 讀碼成立；射程限制：只認第一個位置參數是字面 `'case'`（關鍵字參數、常數、別名呼叫都認不出） | **CR-S1 關閉**（射程限制與原建議同類，不再列） |
| ③ json_extract 棘輪 | AST 逐檔計數字串常數裡的 `json_extract(`，加上引用「值含 json_extract 的模組層常數」的次數；每檔 ≤ 基線、新檔出現就紅、降了要重產基線 | 突變 JX1「新增小寫 `json_extract(`」⇒ 紅。**JX2「`JSON_EXTRACT(`」、JX3「`json_extract (`」、JX4「`from … import SQL_DEAL_TAG as _T`＋`SQL_Y = "x, " + _T`」⇒ 存活** | 成立（繞過 ⇒ T13-S1） |
| ④ spec_coverage 模組感知 | `spec_impl_modules.json`（184 筆：tender_radar 124、accounting 42、payroll 17、subcontract 1）：模組不在時其編號免比；`test_spec_owner_map_is_fresh`：模組都在時與現場計算一致 | 主持的兩個重點：SO1「表少一筆」⇒ **紅**；SO3「模組題新增一個編號、沒列進表」⇒ **紅**（新鮮度題＋鬼列）⇒ 新代號不會被靜默免比、漂移抓得到。**但 SO2「表裡留一個不存在的模組 key」⇒ 存活**（新鮮度題整題略過） | **T13-M1** |

## 2. 發現

**T13-M1（必修）　對照表裡一個不存在的模組 key，會讓新鮮度題永遠略過**
- `test_spec_owner_map_is_fresh` 的略過條件是 `any(not _module_present(k) for k in set(rec.values()))`：取自被檢查的對照表本身。
- 模組改名、移除，或手改寫錯一個 key ⇒ 那個 key「永遠不在」⇒ 新鮮度題每一輪都略過 ⇒ 整張表之後怎麼漂都不會紅（與 AB3-M1 同一類：略過條件與被檢查的東西同源）。
- 修法：
  - 略過條件改用獨立訊號（例如 modules.json 已搬遷、而資料夾不在的組；或 `core_only_rc` 等反向控制明設的旗標）；
  - 對照表裡的 key 必須都是 modules.json 登記過的模組 key，不是的話直接紅。
- 補反向控制：表裡加一個不存在的 key ⇒ 紅。

**T13-S1（建議）　json_extract 棘輪的繞過**
- SQLite 函式名不分大小寫、`(` 前可以有空白：`JSON_EXTRACT(`、`json_extract (` 效果相同卻不計。建議改用 `re.compile(r"json_extract\s*\(", re.I)`。
- 常數經 `import … as 別名` 或再串進另一個常數時不計。可把「值引用了含 json_extract 的常數」的常數也遞移收進 consts，並把 ImportFrom 的 asname 納入。
- 依主持約定，同類繞過列建議。

**T13-S2（建議）　④ 的免比範圍**
- 一個編號的實作題一旦有任何一題在 L1，就不列入對照表（`len(ks) == 1 and None not in ks`），這是對的方向（L1 的編號永遠要比）。
- 補一句說明到 docstring，避免之後有人把「部分在模組」也收進表。
