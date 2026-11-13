# 整合守門題組＋閘門鎖（T82，測試流程改版 ①②）

## 為什麼
T81 官方閘門 14 輪（`D:\Claude-pm\t81-gate-*.log`）紅燈絕大多數是「合併後才紅」的守門類——每輪 fail-fast 只露幾題，修一個重跑一次（單輪 30～80 分）。
同時有別的視窗在閘門期間起全量／e2e 重型，把閘門拖紅（日誌＋佇列見 `heavy_run.py`）。

兩個工具：
1. **整合守門題組** `tools/platform/preflight_guards.py`——每合併一支分支就跑，約 5 分鐘內一次列出全部守門紅，依守門種類分組，點名最近哪幾次合併可能是肇因，附標準修法。
2. **閘門鎖** `tools/platform/heavy_run.py --gate-lock …`＋conftest 的直接跑檢查——整合者持有鎖期間，不是閘門的重型自動等（排隊）或被拒（直接跑）。**定位：防意外的護欄，不是強制機制**——有人刻意設 `MOTRIX_QUEUE_GUARD=0`、帶 `MOTRIX_CI_TICKET` 或自稱 `--class official` 都繞得過（與 conftest 鎖檔同一個哲學：防「順手跑一下」，不防蓄意）。

與既有工具分工：`train_preflight.py`（T47）＝A 靜態旗標＋窄版便宜集合＋受影響模組；`pre_train_check.py`＝分支推上月台前在拋棄式樹預演合併。本題組＝**T76／T81 實際紅過的守門類別的固定清單**＋分組＋肇因合併；A 靜態旗標也順手跑一次（`--no-static` 關）。

## 分支作者：交件前怎麼跑（3～5 行）
**基底＝PM 公告的「目前列車分支」**：T82 期間是 **`origin/train/t82-int`**（整合者每次綠就推）；之後的班次以 PM 公告為準。`git fetch origin` 後 `git rev-parse --verify origin/train/t82-int` 沒有東西 ⇒ 整合者還沒推，先問 PM，不要自己改用別的基底。
不是 `origin/main`（那是 repo 預設分支，不是整合基底），也不是你自己去猜：守門題組要驗的是「合進列車之後」會不會紅，所以要對齊列車現在的樣子。
在你自己的 worktree 根目錄，用 `D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe`（下面 `<列車>` 一律是上面那條，T82 期間＝`origin/train/t82-int`）：
```
git fetch origin && git merge <列車>        # 先把目前列車合進你的分支（或 rebase），再跑
python tools/platform/preflight_guards.py --window <你的視窗> --base <列車> --skip generated      # 約 7 分（加 static_scans2 後）、3 worker、自動排隊；結束碼 0＝綠
python tools/platform/preflight_guards.py --window <你的視窗> --base <列車> --only <紅的組id>       # 照報告的「修法」改完，只重跑出紅的組
```
- `--base <列車>`：靜態旗標比對與「可能肇因的合併」都從這條之後算；指到不存在的 rev ⇒ 結束碼 2（不是空結果）。預設值 `origin/platform` 只適合基底就是 platform 的情況。
- **分支模式**：在你的**具名分支**上跑時，樹裡的 `(next)` 版號佔位不算紅（列車 `train_number assign` 取號）；格式錯／快照與 CHANGELOG 不一致仍紅。**整合者要在 `train/<n>-int` 具名分支上跑 preflight，不要在 detached 或 wip 暫存分支上跑**——detached 且 HEAD 已包含在 `--base` 裡（凍結列車 tip 的 worktree）會自動維持嚴格（佔位照紅）；但名叫 wip/* 的暫存分支會被當成分支模式。
- `--skip generated`：feature 分支不 commit 產生檔（dep_graph／UNIT-INDEX／test_map），列車模式下那組必紅，由整合者重產；其餘紅都是你的。
- 紅的報告會點名最近哪幾次合併可能是肇因；「未能檢查」（exit 1）＝沒證明題有跑，不是綠。整合者持有閘門鎖時你會最多等 120 秒（75）——等鎖放掉再跑。
- 題組綠 ≠ 閘門綠；交件仍要附你自己的測試結果。

## ① 整合守門題組

### 用法（整合樹根目錄；Python 用 `D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe`）
```
python tools/platform/preflight_guards.py --window <整合者視窗>      # 每次合併後
python tools/platform/preflight_guards.py --only changelog,version_manifest   # 修完只重跑出紅的組
python tools/platform/preflight_guards.py --list                      # 看題組
python tools/platform/preflight_guards.py --dry-run                   # 印指令＋預估耗時，不跑
python tools/platform/preflight_guards.py --with-e2e-goldens          # 另加 e2e golden（獨佔排隊）
```
- `MOTRIX_TRAIN=1`、`-m "not e2e"`、不載 failfast ⇒ **一次看到全部的紅**；3 worker、經 `heavy_run` 排隊（`--window` 要和閘門鎖的視窗一致才不會被自己的閘門鎖擋住）。
- 預算 12 分（`--budget-min`，不含排隊時間），由**牆鐘 watchdog** 強制：卡住沒輸出也會被停、結束碼 3（**不是綠**）。
- **證明有跑**：每組用 junit 結果算 過／略過／紅；收集 0、全部略過、收集數低於該組 `min_tests`（json 內，實收集數的 80%）、拿不到結果檔 ⇒ 「未能檢查」，結束碼 1，不會印全綠。有略過但有過 ⇒ 只列出。pytest 結束碼不是 0／1（例如 4＝nodeid 改名）⇒ 印輸出尾段。
- `--window` **必填**（沒有預設）。閘門鎖被別人持有、而你的視窗不是持有者 ⇒ 最多排 120 秒就放棄（75），訊息點名持有者。`--base`（預設 origin/platform）不存在 ⇒ 結束碼 2。
- 結束碼：0 全綠｜1 有紅或未能檢查｜2 工具出錯／--base 不存在／required 組找不到檔（守門被改名）｜3 超過預算｜75 排隊逾時。
- 不寫追蹤檔、不 commit、不 push。`--json-out F` 存機器可讀結果。

### 題組清單
單一來源 `tools/platform/preflight_guards.json`：每組＝一類守門（`paths`）＋出紅標準修法（`fix`）＋肇因搜尋的 `watch` glob。23 組、約 165 個檔、收集約 2000 題（`--list` 看每組檔數與題數下限）。
守門類別對照 T82 單：CHANGELOG 跟著程式、version_slots／version_manifest、spec_coverage、page_paths、no_direct_js_enumeration、modules.json 歸屬、L1 快照、route_inventory、response_keys、write_golden、unscoped_reads、u0a_sinks、view_filter 標記、mail_registry、recyclebin_guards、generated_maps（train mode）、golden（route table）；另加 T81 實紅過的：AH-O7 套用腳本版本、表單版號、用語守門、no_admin_bypass、寫入路徑登記、靜態掃描（raw-vh 等）；最後一組 `recent_interplay` 是近兩班互踩過的功能題（選用，找不到不擋）。
**`static_scans2`（全倉靜態掃描補收）**：T82 預跑才抓到 `test_no_truthy_request_flags`、`test_case_summary_purpose`（image-bomb／xlsx-guard 合併後才紅）——它們是「掃整個 repo 的寫法」的守門，沒被任何組收進來。
2026-11-13 把其餘 **88 個**同類檔一次補收（約 810 題；做法：列出沒被任何組收的測試檔，挑「掃原始碼／頁面、不起 client／瀏覽器」的，**逐檔單獨跑**確認各檔 ≤ 25 秒，
排除測工具本身或依賴所在目錄的檔：prepush_check／module_update／subproc_helper／testcache_shadow／basetemp_cleanup／pdf_concurrency，與單檔 > 25 秒的 scope_gate／pii_forms／modtest_scope／module_update_delivery／stage_select）。
當天在 t82-int tip 上這組另外抓到 5 個真紅（unit_cards、motrix_format、no_import_time_clock、case_summary_purpose 的 `**` 呼叫、truthy_request_flags），預跑原本看不到。
之後新增「掃全倉」型守門請加進這組（或對應的組）；`test_preflight_guards_tool.py` 的 min_tests 下限會在檔被刪或改名時報「未能檢查」。
`tests/platform/test_preflight_guards_tool.py` 會驗：每個 pattern 都找得到檔（改名＝測試紅）、T82 單列的類別與 T76/T81 日誌裡紅過的守門檔都在清單內。

### 報告
```
紅 3 題，依守門種類（2 類）：
■ [version_manifest／表單版號] 2 紅
    FAILED tests/test_version_manifest_no_future_stamps_2026_10_07.py::… — msg
    可能肇因（最近的合併）：
      1a2b3c4d merge: LINE 通知管道… （動到 backend/version_manifest.json）
    修法：manifest 新條目日期不可是未來、…
```
肇因＝`<--since（預設 origin/platform）>..HEAD` 的 first-parent 合併（沒有就最近 25 個），計分：動到紅題所在測試檔 +3、動到紅題所屬模組 +2、動到該組 `watch` glob +1，列前 3。**只是線索，不是判決**（沒有命中會明說）。

### 限制（誠實標註）
- 題組綠 ≠ 閘門綠：只涵蓋已知的合併後守門類別。T81 的「超管登入改內網直連」「通知層更名」這類**功能題互踩**只有完整閘門抓得到；`recent_interplay` 組只是把已知的幾支便宜功能題先跑。
- 耗時：`--dry-run` 依 `preflight_seconds.json` 估（量過的檔加總，沒量過的另列檔數）；實測值見交件回報。
- 新的守門類別出現 ⇒ 在 json 加一組（同時更新 PLAYBOOK §G 4b）。

## ② 閘門鎖與重型佇列強制

### 用法
```
python tools/platform/heavy_run.py --gate-lock acquire --window <整合者視窗> --note "T82 閘門" [--ttl-hours 4]
python tools/platform/heavy_run.py --gate-lock renew   --window <整合者視窗>
python tools/platform/heavy_run.py --gate-lock release --window <整合者視窗>
python tools/platform/heavy_run.py --gate-lock status          # 或 --status（一行含閘門鎖）
```
- 鎖檔 `<MOTRIX_CI_DIR>/gate.lock`（預設 `D:\開發測試檔\_ci`）；**顯式取放、不綁行程**（所以閘門跑完到下一輪開跑之間、合併／修紅的空檔也擋得住別人）。忘了放 ⇒ TTL（預設 4 小時；剩不到 30 分鐘 `--status` 會警告，整合者用 `--gate-lock renew` 續期）自動過期；別人持有時 `acquire` 退 1（`--force` 才接手）。
- 持有期間：`heavy_run` 的 heavy／e2e／watcher 票**自動等**到放鎖或過期（`--max-wait` 逾時回 75）；放行的是 `--class official`、`--window` 等於持有者視窗、環境變數 `MOTRIX_GATE_TOKEN` 等於鎖內 token。light（單檔單 worker）不受影響。放行的票會把 token 帶進子行程。
- conftest（`backend/conftest.py` `_queue_guard`）對**重型 pytest（全量／-n≥2）沒走 heavy_run** 的處置：
  - 閘門鎖持有中：不是持有者（沒 token、沒票根、不是建包子行程）⇒ **直接拒絕**（UsageError，訊息指到 heavy_run 用法）。
  - 沒有閘門鎖：只**印警告**（`MOTRIX_REQUIRE_QUEUE=1` ⇒ 警告改拒絕）。
  - `--collect-only` 不算；`MOTRIX_QUEUE_GUARD=0` 關掉整道檢查；找不到 heavy_run／讀鎖出錯 ⇒ 放行（出貨包沒有 tools/，這道只防順手跑一下）。
  - 單檔、單 worker 的臨時跑完全不受影響。
- 閘門自己的路徑不被擋：建包腳本的子行程（`MOTRIX_PYTEST_BUILD_CHILD`／`EXCLUSIVE_OWNER`）、`heavy_run --class official`、持有者視窗。持有者自己**直接**跑重型時 `$env:MOTRIX_GATE_TOKEN='<acquire 印出的 token>'`。

### 每次整合的建議流程（給整合者）
1. 開窗口：`--gate-lock acquire --window <我> --note "T82 整合"`。
2. 每合併一支：`preflight_guards.py --window <我>` → 看分組紅 → 修 → `--only` 重跑。
3. 全部綠才開完整閘門（`heavy_run --class official --window <我> -- …` 或建包腳本；`run_stage` 在持有者起它時會**自動**帶 token，不用手動 export）。
4. 閘門結束或交班：`--gate-lock release --window <我>`。
5. 你自己的 shell 建議設 `$env:MOTRIX_WINDOW='<我>'`（acquire 會印這一行）：conftest 認持有者視窗，直接跑的重型 pytest 才不會被自己的鎖擋。

### 死結防護
別人在鎖期間先排的 heavy／e2e（被鎖擋住、放鎖前不會開跑）**不算排在持有者前面**（`can_start(me, tickets, gate)`）：持有者的票插隊，不會與它互等到過期。已經在跑的票照算（鎖只擋新開跑，不殺舊的）。

## 附錄：T76／T81 閘門日誌的紅（題組來源）
T81（`t81-gate-*.log`，節錄；failfast 只含已出現的）：test_menu_ux_batch0（空 base_url）、test_module_no_admin_bypass（超管登入）、test_review_edit_chain_reset／test_warranty_mail_owner（通知層更名）、
test_expense_wording、test_form_version_bumped、test_version_manifest_no_future_stamps、test_module_changelog_follows_code、
modules/case route_table_golden、payroll test_recycle_adapter_t53、supply bp1_layout_suppliers、tender_radar tender_reset_endpoint、
e2e：off_state_golden ×2、builder3_singlepage ×2、test_browser_netguard、ledger_p1_pages、home_waiting_for_me_sync。
T81 整合者 fix 提交：u0a_sinks、modules.json 登記（role-label.js／log_setup／motrix-error.js）、bottom_layer 全域釘子、page_paths／no_direct_js_enumeration（static_cache 測試）、
L1 快照 `--pending`、manifest 順序／未來日期、六模組 `(next)` 佔位、題名規格編號撞名、AH-O7（apply_update.version.json）。
T76：prod_status_snapshot、response_keys_baseline、font_zoom raw-vh、quote_alt_write_paths、spec_coverage ×2。

## 全閘門前的「不中斷」預跑（T82）
`modtest --full` 預設 fail-fast（紅達 N 筆就停）且 slice0 紅就不開第二片與 e2e——適合正式放行，但預跑要「一次收齊」做不到。
預跑用 **`modtest --full --keep-going --window <視窗>`**：關 fail-fast／紅燈上限、slice0 紅也照跑其餘片與 e2e；結果照寫，`keep_going: true`，**紅就是紅、不可當放行證據**；
全綠時與正常全量同一份證據。只要某一段的紅清單用 `run-stage <段> --no-failfast`。正式閘門仍用不帶旗標的 `modtest --full`。
（測試：`tests/platform/test_gate_slices_2026_10_07.py::test_keep_going_*`。）

## run-stage 只重試失敗題＋閘門期間全機安靜（2026-11-13，T82 使用者要求）
**① 只重試失敗題**（`python backend/tools/build_test_reuse.py run-stage --stage <段>`，預設開；`--retry-failed N` 調上限、`--no-retry` 關）：
一段跑完、**紅的題數 ≤ N（預設 5）** ⇒ 自動把這幾題在安靜環境（單程序 `-n 0`、無 failfast）單獨重跑一次。
- 全過 ⇒ 這一段記 **「綠（重試 k 題）」**，建包可沿用；紀錄 `stages.<段>.retry` 帶原始紅、重試結果、明細目錄；`deploy_logs/retry_log.jsonl` 每題一行（原始紅摘要＋pass/fail）。
- 重試仍紅 ⇒ 這段記紅。
- **只有「這一輪確定跑完、紅的就是這幾題」才重試**：被中斷／failfast 提早停／collect 階段紅／沒有 fail_stream summary／紅清單比 summary 少／exit code 不是 1 ⇒ 不重試（沒跑到的題不能靠重試補）。紅超過 N 題＝真的問題，不重試。
- 為了讓「紅 ≤ N」的一輪能跑完，run-stage 的 failfast 改成「紅超過 N 才停」（`MOTRIX_FAILFAST_N`＝N＋1、關掉第一個紅後靜默 3 分鐘那條）；`--no-retry` 回舊值。
- **這不是 flake 登記**：`known_flakes.json` 不動、建包的偶發重跑規則不變。同一題累計重試次數：`build_test_reuse.py retry-counts [--json]`（雜訊排行榜的來源）。
**② 閘門期間全機安靜**：閘門鎖（`heavy_run --gate-lock acquire`）被持有時，conftest 會拒絕非持有者的 pytest——**含單檔**（`【閘門期間：不開始臨時 pytest】`，exit 4）。放行：持有者（`MOTRIX_WINDOW`＝持有者視窗或帶對 `MOTRIX_GATE_TOKEN`）、heavy_run 排過隊的行程（`MOTRIX_CI_TICKET`）、建包子行程、`--collect-only`、`MOTRIX_QUEUE_GUARD=0`（知道後果才用）。
`run-stage` 真的跑的時候**自己持有閘門鎖**（沒人持有才取；綁行程 `holder_pid`，被殺就不再擋；TTL 3 小時兜底；跑完放；別人已持有就不動）。整合者顯式取的鎖不綁行程、照舊靠 TTL。
測試：`tests/platform/test_gate_retry_failed_and_quiet_2026_11_13.py`。
**已知限制（h10 審查）**：①任何**真跑**的 run-stage（`--no-failfast` 診斷跑除外）都會持有閘門鎖整段（15～30 分鐘）⇒ 這段時間其他視窗的 pytest 被拒絕——這是設計；診斷用 `--no-failfast`（不重試、不取鎖）。②單程序重試會洗掉「順序污染」型的紅（例如同 worker 前一題留下的 audit_log 列）——這類交給污染偵測器（h4）；run-stage 對同一題 24 小時內重試達 3 次以上會在結束訊息警告，累計看 `retry-counts`。③「綠（重試 k 題）」會標在 run-stage 結束訊息、`explain`、建包沿用訊息與 manifest verification（儀表板的建包閘門讀的是 modtest 全量結果，不經 run-stage 紀錄）。

## 升級演練只在正式閘門跑（`gate_only`，2026-11-13 chore/test-prune）
`tests/test_upgrade_drill_2026_09_25.py`（2 題）與 `tests/platform/test_stepfile_drill_2026_09_30.py`（7 題）合計約 100 秒，標了 `gate_only`（整檔 pytestmark）。
- **跑不跑看環境變數 `MOTRIX_GATE_OFFICIAL`**：等於 `1` 才跑，否則 conftest（`_skip_gate_only`，掛在既有的 `pytest_collection_modifyitems` 上）把它們 skip。
- **只有兩條正式閘門路徑會設 1**：`heavy_run --class official -- …`（子行程）與建包／`run-stage`（`build_test_reuse.run_stage`）。
  守門題組、`--keep-going` 預跑、自己直接跑 pytest／`modtest --full`、`heavy_run` 的其他級別都不設 ⇒ 跳過（顯示 9 skipped）。
- **跳過演練的綠燈不能當建包證據**：沒設 1 的 `modtest --full` 在結果檔記 `gate_official: false`，**不寫建包沿用紀錄**，建包會自己重跑。
  ⇒ 要讓建包沿用，請用 `python tools/platform/heavy_run.py --class official --window <我> -- python tools/platform/modtest.py --full`（或直接 run-stage／建包）。
- 該旗標不進建包指紋（`_ENV_IGNORE`），不然 official 與非 official 的紀錄永遠對不上。
- 守門：`tests/platform/test_gate_only_wiring_2026_11_13.py`（標記有註冊、兩檔都帶、只有一個同名 hook、兩條路徑都設 1、非 official 票不繼承 1、modtest 非 official 不寫紀錄）。

## 預跑與閘門必須同一個直譯器（2026-11-13，T82 閘門抓到）
預跑用 `.venv`、閘門用 `.venv312` ⇒ `test_merge_drivers` 兩題（假設 `sys.executable` 不在 `.venv312` 之下）預跑綠、閘門紅。現在：
- **`modtest --full`（真的跑時）直譯器不是主工作樹的 `.venv312` ⇒ 拒跑，回 2**；`run-stage`（建包同一支）同樣拒跑、不寫紀錄。判定只有一份：`tools/platform/project_env.py::interpreter_mismatch`。
- 明知要用別的環境（例：測 3.13）才放行：`modtest --full --allow-other-python` 或環境變數 `MOTRIX_ALLOW_OTHER_PYTHON=1`。沒有 `.venv312` 的機器不擋。
- `preflight_guards` 本來就固定 `.venv312`；`--dry-run` 與 pytest 內呼叫 modtest 的工具測不受影響。
- 守門：`tests/platform/test_formal_interpreter_2026_11_13.py`。
