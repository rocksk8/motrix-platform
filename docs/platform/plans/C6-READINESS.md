# 固定資產 C6：上車準備度（W4b，2026-10-01）

分支：`wip/w4-c6-rebased`（基底 `origin/platform` fca93b04；合入 `origin/wip/w4-gl-c6` 16af580e／eed9c2d1／18256969）。**第 31 班候選，不在第 29 班。**
標記：**【已驗】**＝這次實際跑過／讀過；**【未驗】**＝推論；**【缺】**＝上車前要補。

## 1. 這次做了什麼
- 合併 `wip/w4-gl-c6`（舊基底 1587b384，離現在很遠）：10 個檔衝突，逐 hunk 解決。
  - **C5c+（eed9c2d1，獎金發放扣繳 native 事件）platform 上已有**（`withholding.record_native`／`forget_native`、`payroll/gl_events._bonus_withholding` 都在），所以這部分一律取 platform 版：`withholding.py`、`payroll/gl_events.py`、`engine.py`、`test_ledger_c5_withholding` 合併後與 platform **逐位元相同**（`git diff fca93b04` 為空）。**【已驗】**
  - C6 只增項目：`ledger/fixed_assets.py`、`api/ledger_assets.py`、`roles.py`（FA_COST 1431／ACCUM_DEPR 1432）、`__init__.py`（import／router／`gl.events` 提供者 `fixed_assets`）、`ledger-hub.html`／`.js`（固定資產頁籤）、`modules.json`、`INTEGRATION-POINTS.md`、accounting CHANGELOG（改成 `(next)` 條目）。module.json／payroll 版號取 platform（版號由列車取號）。**【已驗】**
- 為了讓 C6 自己的 9 題過，改了 C6 程式兩處（**舊基底寫的時候沒被抓到的真缺陷**）：
  1. `fixed_assets.gl_events` 原本在提供者裡 `ensure_categories(conn); conn.commit()`（另開連線寫入）。現在引擎收集前已持有寫入交易 ⇒ `OperationalError: database is locked` ⇒ 引擎把來源標 `error`、**固定資產事件整批消失**（只有一行 notice）。改成唯讀（類別預設在建卡／列表時已種）。
  2. `create_asset`：`int(b.get("life_years") or 類別預設)` ⇒ 耐用年數 **0 被當成沒填而退回預設**，驗證不到。改成只有 `None／""` 才用預設，0 會被擋。
  - 修之前 C6 測試 `3 failed, 6 passed`；修之後 `9 passed in 8.34s`。**【已驗】**
- 一題舊測試要跟著新事實改（不是放寬）：`test_ledger_a_contract::test_api_preview_reports_source_status_and_permissions` 原本寫死「A 階段所有來源都沒接入 ⇒ notices 非空」；固定資產接入後全部來源 ok、notices 可為空。改成「**每個不是 ok 的來源都要有一條說明**」（保住『缺席要明說』的本意）。**【改了、尚未重跑：建包期間禁跑 pytest】**

## 2. 目前測試狀態
| 範圍 | 結果 |
|---|---|
| C6 自己（`test_ledger_c6_assets`） | 9 passed **【已驗】** |
| 合併後聚焦（maps／unit cards／scope gate／page paths／module package files／case read scope／alpine／wording／C6／ledger contract／C5 withholding／mutation guard） | `1 failed, 252 passed, 1 skipped, 3 xfailed`；那 1 題即上面的 contract 測試（已改、待重跑）**【已驗（跑過）／改後未驗】** |
| 完整 pre_train_check／e2e | 沒跑（鎖被建包佔用） |

## 3. 上車前還缺什麼（依重要性）
1. **【缺】處分（C6b）整段沒做**：`fa_assets.status` 有 `disposed`、折舊表會略過處分月之後，但**沒有處分 API、沒有 E13c 事件、沒有處分損益（GAIN_DISPOSAL 7201／LOSS_DISPOSAL 7202）分錄、沒有畫面**。`features.py` 的說明文字卻寫「處分」⇒ 要嘛實作、要嘛把說明改成「處分（待做）」。這是上車最大的功能缺口。
2. **【缺】稅務折舊只有欄位**：`tax_life_years／tax_capitalized` 有存，但**沒有稅務折舊表／報表**；`features.py` 說明寫「直線折舊（管理／稅務）」與實作不符。須決定本班只做管理折舊（改文字）或補稅務。
3. **【缺】功能旗標策略**：`features.READY` 不含 `fixed_assets` ⇒ 即使最高管理者開了旗標，**有效值仍是關**（API 回 409「尚未開啟」、頁籤不顯示）。上車＝決定是否加進 READY；預設仍關。目前這個預設是安全的。**【已驗：features.py】**
4. **【缺】畫面沒有任何瀏覽器 e2e**：頁籤、新增表單、啟用、折舊表有程式，但沒有 Playwright 題與截圖；**估計變動（revision）與編輯（PATCH）沒有畫面**（只有 API）。上車前至少一條 e2e：新增→啟用→（引擎）→折舊表數字＝手算，並驗按鈕終點狀態。**【未驗】**
5. **【缺】驗收數字沒手算**：LEDGER-ACCEPTANCE（112 項）明列「不含固定資產」。要補一節固定資產情境：取得（含進項稅 IN-FA）→ 啟用 → 每月折舊 → 估計變動不追溯 → 試算表／資產負債表／401（IN-FA 已被 `tax401.py` 讀為固定資產進項）的**手算字面值**，並用反向控制（突變）證明抓得到。現有 C6 單元題只驗公式與流程，不是端到端手算驗收。**【缺】**
6. **【缺】待使用者／會計確認的口徑**（程式內已標「採用值／待覆核」）：
   - 殘值預設＝成本÷(耐用年數+1)；
   - 8 萬資本化門檻與最短 2 年（查核準則 §77-1，稅務判定）；
   - 預設類別耐用年數與表號：監視設備「比照 31905、待覆核」、辦公傢俱歸生財器具「為推論」、機器設備／租賃權益改良「依行業細目／依租期」；
   - 起算月＝開始使用日當月提滿一個月；折舊只算「已結束的月份」。
7. **權限（讀 cashier／finance；寫 finance；全部寫稽核）**：已有 `test_api_flag_permissions_and_audit`（旗標關 409、新增／改／啟用／估計變動寫稽核、啟用後不可直接改）**【已驗】**；**【未驗】** 與總帳其他寫入端點的「規則 B（只有最高管理者）」是否要求一致（G1 類別對應是只有最高管理者寫）——需主持裁示。
8. **migration**：**無新 migration**——`fa_categories／fa_assets／fa_revisions／fa_depr_runs／fa_depr_lines` 在 accounting `0001_ledger_base.py`（CREATE TABLE IF NOT EXISTS，加法、可重跑，commit 50999d0e 起就在）**【已驗：讀檔】**。**【未驗】** 正式機既有庫是否已有這五張表（0001 若在更早的班就跑過、當時不含 fa_*，就需要新的 0004）——上車前用唯讀查詢確認 `sqlite_master`。科目 1431／1432／1421／1422／1461／1462／6125／2199 都在 `account_items_112.json` **【已驗】**。
9. **引擎／事件面**：C6 事件 E13a／E13b 的內容雜湊、冪等、估計變動不追溯、卡片被改 ⇒ 對帳紅，均有單元題 **【已驗】**；**【缺】** 突變守門（比照 G5）——例如折舊最後一月不湊足、不追溯規則拿掉、提供者寫入——目前沒有。
10. **自我檢查（必做）**：`pre_train_check`、`test_scope_gate`（新增的 hub 頁籤／api 檔是否列入 `bottom_layer.json`）、UNIT-INDEX／dep_graph／test_map 已重產並提交 **【已驗：重產】**，整套守門未跑。

## 4. 建議順序（估時為粗估，**【未驗】**）
1. 決定 1／2（處分與稅務是否本班做）與 3（READY）——主持／使用者。
2. 處分 C6b：API＋E13c＋手算題＋突變（約 3～4 小時）。
3. 驗收情境＋e2e＋畫面補估計變動／編輯（約 3 小時）。
4. 突變守門＋整套守門＋完整 pre_train_check（~1 小時，需排鎖）。
