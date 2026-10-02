# 建包優化 step 3（依賴增量）dry-run：第 31／32 班回放＋e2e 穩定性（d7；2026-10-02；影子模式，**不閘任何建包**）

## 0. 結論先行
- **工具已就緒且可重複**：`tools/platform/stage_select.py plan`（只算不跑）＋`tools/platform/replay_incremental.py`（離線重放，只讀 git 與 `fail_stream` 紀錄，3 分鐘跑完）；測試 `test_stage_select_2026_10_02.py` **25 題全綠**（63 s，單程序）。回放列：`tools/platform/replay_rows_t31_t32.json`（由 `test_results.jsonl`＋`fail_stream` 的 fail 紀錄機械產生；12 段、24 列＝A／B 兩種基準）。
- **漏報：18 個紅檔漏 3 個（召回 83.3%）——現況不得當閘門（要求是 0 漏）。** 3 個漏報都屬「同一個家族」，補進底板後 18／18；但**家族是事後從這 3 個紅燈歸納的**（見 §3，誠實標註），要靠上線前的影子期（≥2 個班）驗證沒有第 4 型。
- **預期省（B·M 建議版）：169 分 → 129 分，省 40.9 分（24%）**；補底板家族後約 **省 34 分（20%）**。保守基準 A（以「最後一次綠」為基準）在本班 **省 0**：本班一開始就改了選題器自己（`build_test_reuse.py` 等 → selector_sha 變 ⇒ 全量），之後多數輪因硬底層檔（`spec_impl_modules.json`、`core/CHANGELOG`）改動也全量。
- 與第 29／30 班回放（省 31%）比較：**第 31／32 班少省**，因為 8 個非 e2e 輪裡 3 輪被判全量（選題器變更 1、硬底層 2），且 6 個紅輪中有 3 輪的紅燈是「跨模組守門」型（§3）。

## 1. 資料與方法（[實測] vs [推論]）
- [實測]：段、commit、紅檔、實際分鐘取自 `backend/tools/deploy_logs/test_results.jsonl`（段與 commit）＋`tools/platform/fail_stream/20261002_*.jsonl`（`fail` 紀錄的 nodeid、`summary.duration_s`）。第 31 班 7 輪非 e2e（fc5f4080→6aaa5fb0→09d13fdf→26bd438d→e7bae66a→70db060a→a5dea50c 綠）＋e2e 3 次（fa64e2c4 紅、fc5f4080 綠、a5dea50c 綠）；第 32 班目前 1 輪（deb8c273：非 e2e 紅 1、e2e 紅 3）。注意：主持說的「31 班 5 輪」實際紀錄是 **7 輪非 e2e（6 紅 1 綠）**，這裡全部納入。
- 基準：A＝同段最後一次綠（首輪＝正式機包 6b5d2865）；B＝同段上一輪（含紅，紅檔重選）。紅檔召回＝「選題（M 分層）＋底板」是否涵蓋該紅檔，**不含**「硬底層⇒全量」逃生門（逃生門會讓召回虛高）。
- [推論]：選到的題數與分鐘（靜態計題×校正、各檔秒數用已知 63 檔實測、其餘 0.60 s/題）；沿用 BUILD-OPT-ITEM3 §3.1 的模型。

## 2. 逐輪結果（B 基準；全量＝選題器或硬底層判定）
| 輪 | 段 | 實際 | 判定 | 估計 | 省 | 紅檔（召回） |
|---|---|---|---|---|---|---|
| t31r1 | 非e2e | 9:37 | 全量（選題器改了） | 9:37 | 0 | 7 紅（首輪＝以正式機基準算，皆在底板／選題內） |
| t31r2 | 非e2e | 6:40 | 增量 89% | 6:40 | 0 | changelog 守門（命中） |
| t31r3 | 非e2e | 12:56 | 增量 39% | 10:33 | 2:24 | **漏：`test_e2e_font_zoom_fits_viewport`**（無 e2e marker 的瀏覽器測試，跑進非 e2e 段） |
| t31r4 | 非e2e | 17:47 | 增量 37% | 9:09 | 8:39 | **漏：`test_money_round_half_up`**（analytics 測試，因 case 金額 r2 改 half-up 而紅）；`spec_coverage` 命中 |
| t31r5 | 非e2e | 22:24 | 全量（硬底層：spec_impl_modules.json） | 22:24 | 0 | approval_providers（全量涵蓋） |
| t31r6 | 非e2e | 25:31 | 增量 39% | 10:33 | **14:58** | **漏：`subcontract/test_pii_archive_mirror`**（case 新增 F2 封存項目，子模組的鏡像題跨模組讀它） |
| t31r7 | 非e2e | 25:47 | 增量 40% | 10:56 | 14:51 | 綠 |
| t32r1 | 非e2e | 9:59 | 全量（硬底層：core/CHANGELOG、registry） | 9:59 | 0 | version_slots（全量涵蓋） |
| e2e 4 段 | e2e | 7:41／10:53／11:07／8:58 | 全量／增量 93%／全量／全量 | 同 | 0 | 紅檔皆命中或全量涵蓋 |
合計（B 列）：實際 169.4 分 → **B·M 128.5（省 40.9／24%）**；B·S（現行分層）137.2（省 32.2／19%）；出貨包強制全量 143.4（省 26.0）。A·M／A·S 皆 169.4（省 0）。

## 3. 3 個漏報：根因與補法（必讀）
| 漏報 | 為什麼選題沒選到 | 補法（底板家族） |
|---|---|---|
| font_zoom（t31r3） | 測試沒有 `@pytest.mark.e2e`，被分到非 e2e 段，但 test_map 把它當頁面測試掛在 e2e 單位 | 底板加「檔名樣式」`*font_zoom*`；根因已另有守門（e2e marker 分類題） |
| money_round（t31r4） | 金額規則改在 case，測試在 analytics；test_map 沒有 case→analytics 這條邊（用字串常數與 `r2` 的語意連結，不是 import） | `*money_round*`、`*legal_amount_rounding*` |
| pii_archive_mirror（t31r6） | 封存項目是**資料驅動**（`archive.py` 掃所有模組的登記表），子模組測試跨讀 | `*pii*`、`*privacy*`、`*archive*` |
- 這與作者端閘門（AUTHOR-GATE-DESIGN §2 的 A2 底板樣式：`*approval* *queue* *pii* *privacy* *migration* *spec_coverage* *font_zoom* *money_round* *changelog*`）是**同一組家族**：建議**共用一份樣式清單**（`tools/platform/guard_patterns.json`），建包增量選題與作者閘門各讀它，不各維護一份。
- **誠實限制**：家族是看到這 3 個紅燈之後才歸納的（樣本內），18／18 **不是**樣本外證明。所以上線條件定為：影子模式連跑 ≥2 個班（≈10 個以上輪次）、實際紅燈 0 漏，才讓增量選題擔任建包的跳過依據；在那之前建包照舊全量跑，工具只在建包尾端印「若採增量會選 X 題／省 Y 分／漏報 Z」。
- 補家族後的成本：樣式集合 37 檔／315 題＝69～81 s（與底板重疊部分已計在內），B·M 約少省 5～7 分 ⇒ **省約 34 分（20%）**。

## 4. 影子模式怎麼用（不閘任何建包）
1. 建包尾端（或任何時候）：`python tools/platform/stage_select.py plan --base <基準> --head <HEAD> --stage not_e2e`，印選題數、判定（增量／全量與原因）、估計分鐘；**只印，不改變實際跑的題**。
2. 每班結束：`python tools/platform/replay_incremental.py <rows.json>`（rows 由 `test_results.jsonl`＋`fail_stream` 機械產生；產生器見本檔 §6），累計召回與省分鐘；召回 < 100% 就補家族、不上線。
3. 選題器自己變更 ⇒ 判全量（上表 t31r1 即是）；反向控制與合成 repo 測試台見 `test_stage_select_2026_10_02.py`（25 題）。

## 5. e2e 穩定性（睡眠隱患；與建包優化的關係）
**為什麼放在建包優化**：e2e 偶發紅會讓整段重跑（e2e 約 11 分一次），e2e 紅過 2 次（第 31 班 fa64e2c4＝material_approval 那題；第 32 班 deb8c273＝案件頁 3 題）；`flaky_retry` 只能重跑紅檔，抓不到「假綠」。
- **證實的機制**：同步 Playwright 只在呼叫它的 API 時才處理頁面事件；測試執行緒 `time.sleep` 輪詢資料庫時，頁面剛送出的請求（conftest 的 route 讓每個請求先停下來等 Python 放行）被卡在瀏覽器裡約 40～50 秒才出去。`test_e2e_material_approval` 修前 3/8、6/10、2/3 紅，換成 `page.wait_for_timeout` 後 12／12 綠。
- **全樹盤點**（唯讀 grep，`E2E-SLEEP-HAZARD-AUDIT.md`；c7 審查補了兩處）：248 個 Playwright 測試檔、`time.sleep(` 在 18 檔 27 處；**同型高風險 5 處／4 檔**（H1×2、H2、H3、H4）；中風險＝**負向斷言**（「標紅時沒有存進資料庫」「沒存」）睡著後斷言——請求被卡住時會**假綠**，比紅燈更該注意；c7 另找出 `test_e2e_pdf_unapproved` 的 `_eventually`／`_last_audit`、`test_e2e_case_payment_number_input:89`。
- **修正**（`wip/t32-sleep-fix-d7` d3a3dc1a ＋ c7 的 `wip/t32-sleep-fix-c7` 4dd5048d）：輪詢改 `page.wait_for_timeout`；負向斷言改觀察請求（`page.on("request")`，請求被卡住＝紅，而不是 DB 沒變＝綠）並附正對照（有效儲存要看得到請求）；c7 補反向控制（請求卡住：舊寫法假綠、新寫法紅）、`case_data_loss` 等待 2 s→3 s（去抖 1.5 s 留餘裕）。
- **A/B 實測**（5 檔各 5 輪，修前樹 vs 修後樹，平均秒）：quote_number_input 16→13、case_data_loss 25→23、cashier_receive_amount 7→7、cashier_remit_payslip_link 8→7、case_close_checklist 22→27；**全部 25／25 綠兩邊**——修前沒有紅，因為這 5 檔平常沒撞到（機制要「頁面有請求在途＋測試睡著」才會發作），A/B 證明的是**修後不退步、耗時持平**，不是證明消除了偶發。`case_close_checklist` 慢了約 5 秒屬量測雜訊內（單次 5 輪、機器非獨占），未做進一步量測。
- **對建包的意義**：假綠風險比偶發紅小但更危險（建包綠＝錯放行）；已修的負向斷言都有「請求觀察＋正對照」。仍建議（待決定）加靜態守門：e2e 檔的 `for/while` 迴圈體內有 `time.sleep(` 且沒有任何 `page.`／`expect(`／`locator(` 呼叫 ⇒ 紅（掃描器要附正對照）。

## 6. 重現
```
cd <repo>
python tools/platform/replay_incremental.py tools/platform/replay_rows_t31_t32.json --json out.json \
   --fail-stream-dir D:/MOTRIX-PLATFORM/tools/platform/fail_stream --release-ids t31r7,t31e7
```
列的產生：段與 commit 取自 `test_results.jsonl`；同段 `fail_stream/<日期>_*.jsonl` 中 `summary.t` 最接近該筆 `tested_at` 者，其 `type=fail` 的 nodeid 去掉 `::…` 加 `backend/` 前綴即 `red_files`；`duration_s` 即實際分鐘。本次 12 段的對應：t31r1 104352、r2 112144、r3 112956、r4 114536、r5 120823、r6 123215、r7 131453、t32r1 160031；e2e：fa64e2c4＝092350、fc5f4080＝103232、a5dea50c＝130339、deb8c273＝155126。
## 7. 待決定
1. 影子期長度與上線門檻（建議：≥2 班、0 漏）。
2. 是否共用 `guard_patterns.json`（建包增量＋作者閘門）。
3. 靜態守門（迴圈內 `time.sleep` 無 Playwright 呼叫）要不要做。
