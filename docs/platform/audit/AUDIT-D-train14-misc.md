# 稽核：第十四班其餘各包（D，2026-09-28）

> 範圍：主持派工第 4 項，逐包 `git diff origin/platform...<commit>`。更新交付另見 AUDIT-D-update-delivery.md。
> 做法：只讀碼；針對疑點在拋棄式 worktree 跑題目與探針，暫存已刪，`git status` 乾淨。

## 0. 總表

| 包 | commit | 必修 | 建議 | 觀察 | 結論 |
|---|---|---|---|---|---|
| a-build-python-2 | b86bc4c8 | 0 | 0 | 0 | BP-M1 關閉（見 AUDIT-D-A-build-python.md）；11 過 |
| a-prod-status-upgrade | b8858fee | 0 | 0 | 1 | 成立；11 過 |
| a-cr-network-errors | db9aeb51 | 0 | 1 | 0 | 成立（突變 N1～N3 由主持跑過） |
| a-drill-d7extra | cd8aa5aa | 0 | 0 | 1 | 兩條判準與 D 2b8afa60 審定一致；51 過 |
| a-mustfix-scan | 2456a0cc | **1** | 0 | 0 | 13 行關閉紀錄逐筆核對成立；守門本身見 MS-M1 |
| b-jv36-needs-m01＋a-jv36-escape-404 | 424fe442＋ba140a2c | 0 | 0 | 0 | 成立；AB43-O1 處置正確（原句斷言＋abs_path 直驗兩棵樹都跑） |
| b-rc-scope | a7db2503 | 0 | 0 | 1 | 成立；3 過；正對照：jv33／jv36／voucher_summary 都被選到 |
| b-arap-needs | b58a2047 | 0 | 0 | 0 | 5 題逐題核對都用到 M05 的資料（invoice_voucher 候選、tax-export） |
| b-rc-marker-gaps | 6237c7d4 | 0 | 1 | 0 | subcontract 拆題保住了「缺席時照樣驗」；crm 標記見 RM-S1 |
| h-monthly-alert-text | 6a8dea90 | **1** | 0 | 0 | 告警文字成立；自動清除見 MA-M1 |

## 1. 必修

**MS-M1（必修，a-mustfix-scan）　散文中的「關閉」會被當成關閉紀錄，真的未關必修因此從掃描裡消失**
- 證據：`CLOSE = re.compile(r"✅|關閉(?!才)|已關")`（tools/platform/mustfix_scan.py:32）。同一行只要同時出現 ID 與「關閉」兩個字，就算關閉紀錄（沿用 D 舊腳本的判準，為了相容既有的散文式關閉）
- 重現（實例）：D 今天的 AUDIT-D-H12-apply.md 宣告了 DM1、DM2 兩條必修，結論寫了一句「前提是 DM1、DM2 關閉」⇒ 用 2456a0cc 的 `open_items` 掃描，DM1、DM2 **不在未關清單裡**，PM1 在（同一天、同一種宣告寫法）。這句改寫之後，DM1、DM2 才出現（D 已改寫，見 AUDIT-D-H12-apply.md §0）
- 後果：這道守門就是為了抓「被忘了的必修」而設，而一句最普通的「修好 X 之後」式句子就讓它漏掉。PLAYBOOK §E-6 已經規定關閉一律用標準單行，舊檔的散文關閉也已經由 A 補上標準行
- 修法：
  - 標準寫法之外的關閉判準，限定在一份凍結的舊 ID 清單（今天以前宣告的），從今天起宣告的 ID 只認 `CANON`
  - 或者：已有標準單行的稽核檔，一律只認 CANON
  - 補題：正對照「前提是 X 關閉」這種句子 ⇒ X 仍在未關清單；反向控制：舊清單裡的散文關閉仍被採信
- 登記表：第十四班合回時，`mustfix_open.json` 要新增 DM1、DM2（H，wip/h-apply-platform）、PM1（B，wip/b-payreq）、MA-M1、MS-M1，移除 BP-M1（已關）

**MA-M1（必修，h-monthly-alert-text）　「條件解除才自動清」沒有照做：清除只看雲端通不通；月備份的告警在條件還在時，每一輪被清掉一次、稽核記一次、再重寫一次**
- 使用者裁示（CORE-SPEC 2026-09-28 03:07「備份告警自動解除」）：「告警**條件解除**後系統自動清掉即時告警檔……清除動作本身寫一筆稽核」
- 證據：
  - `_clear_backup_alert_if_healthy`（archive.py:583-609）只檢查 `_archive_ok()`（雲端可寫、:311），不看告警檔裡的原因是哪一個條件
  - 每日排程「今天 .done 已在」的分支（:2526-2535）先呼叫它，接著才呼叫 `_check_previous_month_backup()`，後者在月備份還沒補好時立刻重寫告警
  - 新加的 `_system_audit("backup.alert_cleared", …)`（:607）沒有節流；告警本身的 audit 與寄信是「同原因每日一次」（:462-）
- 重現（探針，拋棄式 worktree；只替換 `_write_backup_alert` 為寫檔、`_system_audit` 為收集）：上個月沒有 `.done`、雲端正常，同一天跑三輪「清 → 查上個月」 ⇒ 告警檔最後仍在，而 `backup.alert_cleared` 記了 **2 筆**，原因欄寫的就是「上個月的月備份沒有完成」
- 後果：
  - 稽核日誌一直記「已解除」，而問題並沒有解除（每一輪一筆）
  - 使用者讀稽核會以為解除過了；告警檔在清掉到重寫之間也短暫消失
- 修法：
  - 清除依原因決定：告警檔的原因屬於哪一類，就只在那一類的條件解除時清。月備份類 ⇒ `_check_previous_month_backup()` 為 False（上個月 `.done` 在）；雲端類 ⇒ `_archive_ok()`
  - 或把順序改成先查所有條件，全部解除才清
  - 補題：月備份條件未解除、雲端正常 ⇒ 不清、不寫 audit；補上 `.done` ⇒ 清一次、audit 一筆（帶原因）

## 2. 建議

**NS1（a-cr-network-errors）　「核准／退回」網路失敗時的「重試」會直接重送，而這個動作不冪等**
- 證據：`decide(approve)` 失敗時，retry 是 `run: () => this.decide(approve)`（custom-records.html，afterAction 的 retry 參數）。新增單據已經改成「重新整理列表」、不直接重送（因為回應可能在路上掉了、伺服器其實已經做完）；核准與流程轉換是同一個情形，卻直接重送
- 風險：第一次核准其實已生效、只是回應掉了 ⇒ 重送時單據已到下一層。如果同一個人也是下一層的簽核人，就會連簽兩層；如果不是，伺服器會回 409／403，這是無害的。實際會不會連簽，取決於引擎是否允許同一人跨層，這一點沒有查證
- 建議：核准、退回、流程轉換的網路失敗改成「重新載入單據」（`openRecord(no)`），看了狀態再決定；只有儲存（PUT）維持直接重試

**RM-S1（b-rc-marker-gaps）　`test_feed_attachment_serving` 三題驗的是 L1 的 `/api/uploads` 讀檔，只因為 fixture 借用 CRM 建附件而整題標了 needs_crm**
- 三題（讀回的位元組相同、session token 不能當 photo token、要有憑證）驗的是 `routers/uploads.py`（L1）。CRM 不在的樹上，這三件 L1 行為就沒有任何一題在驗；`test_api_integration` 只驗到 photo-token 與路徑守門的一部分
- §G5 #7：「驗『L1 照常』的不可以標」
- 建議：fixture 改成不經 CRM，直接在 UPLOADS_ROOT 放檔，再走同一個讀取端點，就可以不標。或者保留 CRM 版、另加一題不經 CRM 的讀回題

## 3. 觀察

- **PS-O1（a-prod-status-upgrade）**：upgrade.py 在沒寫部署標記時印「⚠ …」（:159）。在沒有設 PYTHONIOENCODING 的 cp950／cp932 主控台上，這一行會 UnicodeEncodeError（:156 已有同型的句子，是既有行為）。儀表板遠端執行時有設（_dashboard_remote.ps1:363），手動照 RUNBOOK 跑的時候沒有。建議 main 開頭 `sys.stdout.reconfigure(errors="backslashreplace")`，與 apply_plan／delivery 一致
- **FD-O1（a-drill-d7extra）**：冒煙那一步的摘要與 `absence` 列會帶回應本文（前 400 字）與最新一張報價單的單號，寫進 `docs/platform/FINAL-DRILL-REPORT.md`。開發機的 V9 是測試資料，所以可以接受；如果日後改用正式資料演練，報告不可以帶本文
- **RS-O1（b-rc-scope）**：「只靠資料依賴」的偵測只追到 conftest.py 的 fixture。從**別的測試檔** import 的播種 helper（repo 裡有「測試檔 import 另一個測試檔的夾具與 helper」的寫法，例：test_deploy_dashboard_prod_status 從 test_upgrade_deployed_marker 取 `_manifest`）不會被追到。目前沒有找到實例（grep 非 conftest 的 helper 寫 quotations：0），記錄備查

## 4. mustfix-scan：13 行關閉紀錄（主持指定看一次）

逐行核對「關閉行的 commit」與「原檔的複核段落」：

- 10 行：commit 在同檔的複核段落出現過
- 3 行在他檔：
  - M4-M1（a1e0a45b）：AUDIT-D-C-m01-5 §1 複核的 head
  - M4-M3（e67879f2）：同檔 §5 的補記，依 §3、§4 的驗證
  - CA3-M1（221adaa0）：AUDIT-D-C-m01-4 §1「CA3-M1 複核」審的 head

M4-M1 與 CA3-M1 的 commit 標題寫的是同分支上別的修正，但判準是「關閉當時複核的分支 head」，所以成立。**13 行全部成立**。

## 5. 第二輪複核：h-monthly-alert-text dcfadc11（D，2026-09-28）

- MA-M1：清除時先看告警原因。「上個月（」開頭的告警，只在 `_previous_month_missing()` 為 False（上個月 `.done` 在，或上個月系統根本沒在跑）時才清；其他類照舊看雲端。`_check_previous_month_backup` 改呼叫同一支判定，語意不變（讀碼逐行比對）
- 探針（同第一輪的做法，拋棄式 worktree）：
  - 條件未解除，連跑三輪 ⇒ 告警在、`backup.alert_cleared` 0 筆
  - 補上 `.done` 之後再跑三輪 ⇒ 告警清掉、`backup.alert_cleared` 1 筆
- 題：test_states_data_ops＋test_monthly_backup＋test_backup_stale_alert 共 40 過

### 關閉紀錄（標準格式，PLAYBOOK §E-6）

- ✅ MA-M1 關閉（dcfadc11）——告警依原因判斷條件是否解除，月備份類只在上個月 .done 在時才清，不再每輪假記已解除

## 6. 第二輪複核：a-mustfix-scan a170d560（D，2026-09-28）

- 修正：凍結清單 `docs/platform/mustfix_legacy_closures.json`（63 筆，只准減少，有題：過期或變多都紅）以外的 ID，只認標準單行；正對照題 `test_ms_m1_a_prose_close_does_not_hide_a_new_must_fix`。凍結清單裡沒有 DM1、DM2、PM1、MA-M1、MS-M1（grep 只出現在說明文字）
- 拋棄式合併樹（origin/platform＋wip/d-audit-train14 b3c75769＋a170d560）：
  - 掃描宣告 100 筆、未關只剩 MS-M1。DM1、DM2、PM1、MA-M1 都認得標準單行
  - 登記表拿掉那 4 筆之後，29 題全過
  - 反向控制：在本檔末尾加一句「前提是 MS-M1 關閉」⇒ MS-M1 仍在未關清單（先前就是這種句子藏住 DM1、DM2）
- 列車順序：**wip/d-audit-train14 要與 a-mustfix-scan 同班、排在它之前**（反過來的話，登記表的 5 筆在 platform 上找不到宣告，會判「登記過期」而紅）。合回時 `mustfix_open.json` 要移除 DM1、DM2、PM1、MA-M1、MS-M1（全部已關，登記表變成空的）

### 關閉紀錄（標準格式，PLAYBOOK §E-6）

- ✅ MS-M1 關閉（a170d560）——凍結清單以外的必修只認標準單行，散文中的「關閉」不再藏住新必修
