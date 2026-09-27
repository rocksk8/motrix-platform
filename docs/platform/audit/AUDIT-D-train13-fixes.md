# 稽核：第十三班列車長在車上改的守門與題目（0c517469..e21b099a）（D，2026-09-27 20:02）

> 標準等級、讀碼優先（§G1 ⓪）。全量在 e21b099a 跑的期間，D 只在自己的 worktree 跑針對性的題，紀錄在全量結束後才推。

## 0. 結論

- **必修 1（T13R-M1）、建議 2**。

## 1. 逐項

| commit | 內容 | D 的驗證 | 結果 |
|---|---|---|---|
| 74d78fe4 | core-only 9 項：`test_module_boundaries` 4 題、`test_probe_leak_guard` 1 題改用獨立訊號（直接讀 modules.json 的 key、看資料夾是否**全部**不在）；`test_crm_quote_deleted_connector` 門檻 >100 ⇒ >50；`test_e2e_classification`／`test_env_and_load_guards` 各 1 題改用合成檔；`core_only_rc.py` 設 `MOTRIX_TRAIN=1` | 讀碼：略過條件不取自被檢查的掃描結果；只要任何一個模組資料夾在就不略過；掃描壞掉而不是 core-only ⇒ fail（§G5 #15 成立）。**完整安裝（e21b099a）8 題全部執行、8 過、0 略過**；core-only sparse（11 個模組全排除）：5 題明說略過、3 過 | 成立（兩點建議見 §2） |
| 239c0c69 | M01 真刪補 needs_case 6 處 | `test_accounting_connectors` 整檔標記：該檔只有 2 題、都打 M01 的 case-bundle ⇒ 整檔標記正確。**`test_case_summary_purpose::test_the_voucher_case_tab_lists_every_case_for_voucher_users` 在 M01 不在時直接 skip** ⇒ T13R-M1 | **T13R-M1** |
| 07ad32d8 | `_voucher_line` 題標 needs_accounting | 該題 import M06 內部函式，標記正確 | 成立 |
| 57692556 | 交會紅 9 題 | `_LEGACY_PROVIDERS` 改用 `registry.providers()`：找不到提供者會大聲 fail；`providers()` 每次即時組、沒有快取 ⇒ 替換確實生效（不是假綠）。json_extract 基線只往下（44→39，隨 approval-l1 移除重產）。EM10 導航基準 `_outside` 103→101、`subcontract` 2→4：總數不變，是 absent404-4 補的那頁換組。O13／O14／M01 登記為操作追蹤序號，理由寫明 | 成立 |

## 2. 發現

**T13R-M1（必修）　傳票「案件」頁籤在 M01 不在時被略過，而不是驗行為**
- `test_the_voucher_case_tab_lists_every_case_for_voucher_users` 驗的是 **M06 的頁面**。M01 不在時，產品行為是「案件頁籤空、並說明原因」：`modules/accounting/api/vouchers.py:434 CASES_UNAVAILABLE`。
- D 在真刪 M01 的 sparse 樹實打 `GET /api/vouchers/summary-sources`：200、`tabs["案件"] == []`、`notes["案件"] == "案件模組未安裝：無法從案件帶入摘要。"`。
- **全 repo 沒有任何題斷言 `CASES_UNAVAILABLE`** ⇒ 這個 skip 讓 M01 不在時傳票案件頁籤的行為完全沒被驗到（§G5 #7：驗「另一邊照常」的不可以略過）。
- 修法：M01 不在時改斷言上述行為（比照 jv4 的做法），不 skip。

**T13R-S1（建議）　`test_crm_quote_deleted_connector` 的正對照門檻放寬後，完整安裝時的部分掃描失效看不到**
- 門檻 >100 ⇒ >50，是為了 core-only（實量 85）。但完整安裝實量 152 時，掃描壞掉一部分（例如只掃到 60）也照樣過。
- 建議依獨立訊號分兩個門檻：core-only ⇒ >50；否則 ⇒ >100。

**T13R-S2（建議）　`core_only_rc.py` 無條件把 `MOTRIX_TRAIN=1` 寫進自己的行程環境**
- 工具的 `--commit` 可以指任何 commit，不限列車 HEAD。在一般分支上跑時，「分支不准改產生檔」的守門也會一起被關掉。
- 而且改的是工具自己的 `os.environ`：若之後有題目在行程內呼叫 `run()`，旗標會留在那個 worker（〈環境變數旗標會漏進子 pytest〉）。目前的題只 import 輔助函式、沒有呼叫 `run()`，所以尚未發生。
- 建議只放進子行程的 env，並加一個明確的 `--train` 旗標（或比對 commit 是否為列車分支 HEAD）才設。

## 3. 主持裁示（排程）

- T13R-M1 成立，但排在全量之後：建包條件是同一份 tree 在 12 小時內全量全綠，現在插 commit 會讓正在跑的全量作廢。
  - 全量有紅 ⇒ 併進那批修正，再跑一次全量；
  - 全量全綠 ⇒ 在那個 commit 建包。T13R-M1 屬測試檔（不進安裝包），建包後立刻補，局部驗證，交 D 複核。
- S1、S2 採納，同樣建包後處理：
  - S1：crm 正對照依 core-only 與否分兩個門檻；
  - S2：core_only_rc 只把 MOTRIX_TRAIN 傳給子行程，加明確的 `--train` 旗標。
