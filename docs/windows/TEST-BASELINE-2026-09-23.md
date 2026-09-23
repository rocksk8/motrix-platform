# TEST-BASELINE-2026-09-23

> ### ⚠️ **非官方紀錄。** 手動執行的裸 `pytest`，**不是 `build_deploy_package.ps1` 產生的**。
> 🔑 不要把它與 `backend/tools/deploy_logs/build_history.jsonl` 的紀錄混在一起引用 ——
> 那一份是打包流程寫的，**而這一份沒有經過打包**。
> 📌 量測由 **D**（唯讀視窗）執行，**A** 落檔。

---

## 🔑 這份基準證明什麼、不證明什麼
```
✅ 證明：**2026-09-23 這一天，在 e70527e 這棵樹上，哪些題會過、哪些不會**
✅ 而它是**今天唯一一次「從頭到尾沒有人動工作樹」的量測**
❌ 不證明：功能是對的（題本身可能是錯的、可能根本沒有題）
❌ 不證明：`passed` 的那 2,440 支「驗過」—— 它們只是今天沒有紅
```
⚠️ 而要與 `HANDOVER-2026-09-23.md` 第 2 節**一起讀**：那一節記的是**證據強弱**。

---

## 凍結完整性
兩階段（`not_e2e` / `e2e`）在同一次凍結內完成。
```
HEAD（跑前跑後相同）：e70527e5b17c0e48e99bb22535ed9a6a34952c5a

git status --porcelain（跑前跑後相同）：
 M docs/windows/D.md
 M docs/windows/tools/README.md
?? docs/windows/tools/px1_scan.py
```
📌 那三個未提交檔案**是量測者自己的**，而它們在兩次量測之間沒有變化。
🔑 而它們之所以被發現，是 A-2 停手時順手跑了 `git status` ——
  ☠️ **不是流程，是副作用**（`STATE.md §356`）。

---

## not_e2e
```
python -m pytest -q -m "not e2e" -n 6 --durations=20 --basetemp=<scratchpad>
30 failed, 2440 passed, 53 skipped, 1 xfailed, 19 warnings, 520.00s (0:08:40)
```

### 甲欄（6 支）— **成因已知**：今天新增 10 個編號而題還沒寫
```
test_spec_coverage_2026_09_21.py::test_every_declared_condition_has_a_test
test_spec_coverage_2026_09_21.py::test_the_numbers_this_gate_cannot_tell_apart_are_all_written_down
test_spec_coverage_2026_09_21.py::test_no_test_claims_a_number_the_spec_never_declared
test_spec_coverage_2026_09_21.py::test_the_scope_list_does_not_use_any_elision
test_spec_coverage_2026_09_21.py::test_every_prefix_in_the_spec_appears_somewhere_in_the_scope_file
test_spec_coverage_2026_09_21.py::test_gt1_every_this_number_is_declared_in_the_spec
```
> ### ⚠️ **不要讀成「預期內」** —— 它是一張**欠條**：閘門正在報告「我們宣告了工作而還沒驗它」。
🔴 而第 4 支（`..._does_not_use_any_elision`）**是那支守門自己的 parser bug**（C 查）：
  它把**任何含「THIS」字樣的標題**都當成進入 `THIS` 區塊 ⇒ 掃到說明用的程式碼片段裡的省略號。
  ☠️ **而 A 自己的腳本今天犯了一模一樣的錯**（`^## .*THIS` 撈到 6 個標題）——
  🔑 同一個缺陷、兩支獨立的工具。

### 乙欄（24 支）— 交 C 判定
```
test_alpine_double_init_2026_09_23.py            ×2  (AL1)
test_bonus_manual_and_picker_2026_09_23.py       ×4  (BN3 ×3 / BN4 ×1)
test_demo_reset_2026_09_23.py                    ×1  (DM1)
test_bonus_award_reject_record_2026_09_23.py     ×1  (BN17 · 資料庫層擋刪除)
test_em9_silent_write_failure_2026_09_23.py      ×4  (EM9)
test_error_detail_leak_2026_09_23.py             ×2  (EM3)
test_navigation_destination_2026_09_23.py        ×4  (EM10)
test_page_script_deps_2026_09_23.py              ×1
test_system_audit_2026_09_14.py                  ×2  (備份登記 / BG1)
test_wording_guards_2026_09_23.py                ×3  (GW1 / GW2)
```

### skipped 53
**只有數字，沒有名單**（跑時未加 `-rs`）。
⇒ 名單改用**靜態掃描**（`@pytest.mark.skip` / `skipif` / `pytest.skip(`）—— 唯讀、不必再凍一次。
⚠️ 而靜態掃到的數量**可能不是 53**（`skipif` 的條件在執行時才決定）——
  🔑 **那個差額本身就是一個發現，不要調整它去湊。**

### population 缺口（誠實留白，不猜）
```
collect-only（HEAD 61cc80b）量到 **2,498**
git diff --stat 61cc80b -> e70527e -- backend/tests/ ：6 檔異動，逐檔 def test_ 淨增 **+30**（程式算的）
   test_bn17_award_reject_record_2026_09_23.py            0 -> 10
   test_bonus_award_reject_record_2026_09_23.py          10 -> 10
   test_bonus_empty_state_2026_09_23.py                   8 ->  9
   test_company_profile_ql26_save_button_2026_09_23.py    0 ->  6
   test_em5_reload_flag_2026_09_23.py                     0 ->  9
   test_em5_voucher_chain_unreadable_2026_09_23.py        0 ->  4
2498 + 30 = 2528，而實跑 30+2440+53+1 = **2524** => **差 4 未查明**
```
✅ **本基準採用的是實跑數字**（直接觀測）。這個缺口不影響任何判斷，所以沒有去追。

### 最慢 20（節錄前 5）
```
17.53s test_voucher_pdf_export_2026_09_23.py::test_jv5_a_zero_page_attachment_is_reported_not_silently_dropped
17.05s test_voucher_pdf_export_2026_09_23.py::test_jv5_an_encrypted_attachment_does_not_blow_up_the_export
16.30s test_quote_location_snapshot_2026_09_23.py::test_ql25_submitting_freezes_the_location_identity
16.28s test_quote_location_snapshot_2026_09_23.py::test_ql25_a_draft_still_tracks_live_settings
15.51s test_voucher_export_gate_2026_09_23.py::test_jv10_an_export_that_merged_nothing_does_not_claim_it_did
```

---

## e2e
```
python -m pytest -q -rf -m "e2e" --durations=20 --basetemp=<scratchpad>
2 failed, 73 passed, 2 skipped, 2524 deselected, 5 warnings, 387.00s (0:06:27)
```
兩支**都不是新缺陷**，兩支都是 A 早先知道而沒有解決的：
```
① test_e2e_bonus_empty_state::test_ac1_an_admin_is_told_who_can_fix_it_and_gets_no_button
   admin 空狀態三件只有一件（缺「誰能解決」「去哪裡解決」）
   docstring 自指 SPEC-BN1-PLAN §2 **待決**；A 早先裁「先不要修」
② test_voucher_preview_iframe_height::test_jv25_iframe_height_is_stable_...
   374.2 -> 380.0（差 **5.8px**，門檻 ≤5）；對應 JV25，
   A 早先派過「定位 10 分鐘：哪個元素動 5.8px」—— **尚未執行**
```

---

## 與歷史基準並排
> ### ⚠️ 口徑相同（passed/failed/skipped 計數）**而來源不同**：
> 下面那一列是**打包流程內**跑的，本次是**裸 pytest 手動跑**。
```
                    not_e2e                                      e2e
2026-09-22 20:06    1,831 passed / 53 skipped / 604.71s          53 passed / 2 skipped / 260.31s
  （7bc1fb8，打包內，build_history.jsonl 的**唯一一筆**）
2026-09-23 本次     2,440 passed / 30 failed / 53 skipped / 520.00s   73 passed / 2 failed / 2 skipped / 387.00s
  （e70527e，裸 pytest）
```
⚠️ 而**更早的 `1,440 passed / 53 skipped`（09-22 03:33）沒有原始紀錄** ——
  那個包已被 `KeepPackages = 2` 輪替掉，而 `build_history.jsonl` 是那之後才加的。
  🔑 **那個數字現在只存在於 A 的記憶裡。**
